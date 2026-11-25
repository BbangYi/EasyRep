"""Bounded local YOLO training and held-out evaluation; no cloud logging."""
import importlib.metadata
import math
import os
from pathlib import Path
import platform
import shutil
import time
from collections import Counter, defaultdict

from .analysis_features import fingerprint, save_artifact
from .core import atomic_json, digest, number, read_json, relative, require
from .vision_data import DETECTION_TARGETS, dataset_summary, load_dataset, output_directory, read_boxes, write_training_yaml
from .worker_power import keep_awake


def runtime(directory, threads=2):
    require(type(threads) is int and 1 <= threads <= 16, "threads must be an integer from 1 to 16")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ultralytics").mkdir(exist_ok=True)
    (directory / "matplotlib").mkdir(exist_ok=True)
    for key, value in {"YOLO_CONFIG_DIR": str(directory / "ultralytics"), "MPLCONFIGDIR": str(directory / "matplotlib"),
                       "YOLO_AUTOINSTALL": "false", "YOLO_OFFLINE": "true", "NO_ALBUMENTATIONS_UPDATE": "1", "OMP_NUM_THREADS": str(threads),
                       "MKL_NUM_THREADS": str(threads)}.items():
        os.environ[key] = value
    import cv2
    import torch
    from ultralytics import YOLO, settings
    from ultralytics.utils import torch_utils
    settings.update({key: False for key in ("sync", "hub", "mlflow", "wandb", "clearml", "comet", "neptune", "raytune", "dvc", "tensorboard") if key in settings})
    # CPU trainer/validator device selection otherwise restores the library's default.
    torch_utils.NUM_THREADS = threads
    torch.set_num_threads(threads)
    cv2.setNumThreads(threads)
    return YOLO


def environment():
    import torch
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in ("ultralytics", "torch", "torchvision", "numpy", "opencv-python", "lap")},
            "cuda_available": torch.cuda.is_available(), "mps_available": torch.backends.mps.is_available(),
            "cuda_devices": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]}


def check_device(device):
    import torch
    require(device == "cpu" or device == "mps" or (isinstance(device, str) and device.isdigit()), "device must be cpu, mps, or one CUDA device index")
    if device == "mps":
        require(torch.backends.mps.is_available(), "requested MPS device is unavailable; no silent CPU fallback")
    elif device != "cpu":
        require(torch.cuda.is_available() and int(device) < torch.cuda.device_count(), "requested CUDA device is unavailable; no silent CPU fallback")


def metric_values(result):
    return {str(k): float(v) if math.isfinite(float(v)) else None for k, v in result.results_dict.items()}


class TrainingBudget:
    """Soft limit checked between batches/epochs; validation/save may run past it."""
    def __init__(self, minutes):
        self.deadline = time.monotonic() + minutes * 60
        self.reached = False

    def __call__(self, trainer):
        self.reached |= time.monotonic() >= self.deadline
        trainer.stop |= self.reached


class TrainingProgress:
    """Count completed batches and actual optimizer calls, including partial/retried epochs."""
    def __init__(self, path, *, amp, expected_threads=None):
        require(expected_threads is None or (type(expected_threads) is int and 1 <= expected_threads <= 16),
                "invalid expected thread count")
        self.expected_threads = expected_threads
        self.path, self.requested_amp = Path(path), amp
        self.started = time.monotonic()
        self.hook = self.optimizer = None
        self.stats = dict(state="starting", requested_amp=amp, batches=0, optimizer_steps=0,
                          full_passes_processed=0, epoch_attempts=[])

    def save(self):
        self.stats["elapsed_seconds"] = time.monotonic() - self.started
        atomic_json(self.path, self.stats)

    def start(self, trainer):
        self.check_threads()
        active = bool(trainer.amp)
        self.stats.update(actual_amp=active, actual_device=str(trainer.device))
        require(active == self.requested_amp and
                (not active or (trainer.device.type == "cuda" and trainer.scaler.is_enabled())),
                "requested CUDA AMP is not active; refusing silent precision fallback")
        require(self.hook is None, "training progress already started")
        self.optimizer = trainer.optimizer
        self.hook = self.optimizer.register_step_post_hook(self.optimizer_step)
        self.stats["state"] = "running"
        self.save()

    def check_threads(self):
        import torch
        actual = torch.get_num_threads()
        self.stats['actual_torch_threads'] = actual
        require(self.expected_threads is None or actual == self.expected_threads,
                "learner thread count differs from requested limit")

    def optimizer_step(self, optimizer, args, kwargs):
        # GradScaler does not call optimizer.step when it skips a nonfinite update.
        self.stats["optimizer_steps"] += 1

    def epoch_start(self, trainer):
        self.check_threads()
        require(self.hook is not None and trainer.optimizer is self.optimizer,
                "training optimizer changed; update count would be incomplete")
        self.stats["epoch_attempts"].append(dict(epoch=trainer.epoch + 1,
            batches=0, expected_batches=len(trainer.train_loader), batch_size=trainer.batch_size, ended=False))
        self.save()

    def batch_end(self, trainer):
        attempt = self.stats["epoch_attempts"][-1]
        require(attempt["epoch"] == trainer.epoch + 1 and not attempt["ended"], "batch outside active epoch")
        attempt["batches"] += 1
        self.stats["batches"] += 1
        require(attempt["batches"] <= attempt["expected_batches"], "batch count exceeds training loader")
        if self.stats["batches"] % 25 == 0:
            self.save()

    def epoch_end(self, trainer):
        self.stats["epoch_attempts"][-1]["ended"] = True
        self.stats["full_passes_processed"] = sum(
            a["ended"] and a["batches"] == a["expected_batches"] for a in self.stats["epoch_attempts"])
        self.save()

    def finish(self, *, completed):
        if self.hook is not None:
            self.hook.remove()
            self.hook = None
        recorded = self.stats["optimizer_steps"] > 0 and self.stats["batches"] > 0
        self.stats["state"] = "complete" if completed and recorded else "failed"
        self.save()
        if completed:
            require(recorded, "training completed without recorded batches and optimizer updates")


def learner_data(source, manifest, run):
    """Each learner gets its own copy: framework caches never mutate reviewed data."""
    target = run / "learner-data"
    for row in manifest["records"]:
        for key, checksum in (("image", "image_sha256"), ("label", "label_sha256")):
            destination = target / row[key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(relative(Path(source), row[key]), destination)
            require(digest(destination) == row[checksum], "dataset changed while staging learner input")
    return write_training_yaml(target, run / "data.yaml", manifest["class_names"])


def write_training_sampling(manifest, run, preset):
    """Replay reviewed training examples with bounded, auditable source exposure."""
    import yaml
    require(isinstance(preset, str) and preset in {"small-body-v1", "target-replay-v1"},
            "unknown training sampling preset")
    run = Path(run).resolve()
    rows = sorted((r for r in manifest["records"] if r["split"] == "train"), key=lambda r: r["id"])
    require(bool(rows), "training sampling requires training images")
    groups, fractions, reasons = defaultdict(list), {}, {}
    for row in rows:
        label = relative(run / "learner-data", row["label"])
        boxes = read_boxes(label)
        fractions[row["id"]] = min((w*h for _,_,w,h in boxes), default=None)
        if preset == "target-replay-v1":
            review = row.get("training_focus_review")
            if review is None:
                continue
            require(isinstance(review, dict) and isinstance(review.get("review_method"), str) and
                    review["review_method"] in {"assistant", "human"},
                    "target replay requires a named review method")
            require(review.get("image_sha256") == row["image_sha256"] and
                    review.get("label_sha256") == row.get("label_sha256") == digest(label),
                    "target replay review differs from image or label")
            focus = review.get("reasons")
            require(isinstance(focus, list) and 0 < len(focus) <= 3 and
                    all(isinstance(reason, str) and reason in {"crested", "night", "negative"} for reason in focus) and
                    len(set(focus)) == len(focus), "invalid target replay reasons")
            require("negative" not in focus or not boxes, "negative replay image has target boxes")
            require(not ({"crested", "night"} & set(focus)) or bool(boxes),
                    "positive target replay image has no target boxes")
            require("crested" not in focus or (row.get("original_taxon") == "Correlophus ciliatus" and
                    row.get("species_confirmed") is True), "crested replay needs confirmed source taxon")
            reasons[row["id"]] = sorted(focus)
            groups[row["group_id"]].append(row)
        elif fractions[row["id"]] is not None and fractions[row["id"]] < .05:
            groups[row["group_id"]].append(row)
    repeats = {row["id"]: 1 for row in rows}
    for group in groups.values():
        ordered = sorted(group, key=lambda r: (r["image_sha256"], r["id"]))
        if preset == "small-body-v1":
            for row in ordered[:8]:
                repeats[row["id"]] = 3
        else:
            # Round-robin extras prevent a few frames consuming the whole group cap.
            remaining = 48
            for _ in range(3):
                for row in ordered:
                    if remaining:
                        repeats[row["id"]] += 1
                        remaining -= 1
    inventory, paths = [], []
    for row in rows:
        repeat = repeats[row["id"]]
        path = relative(run / "learner-data", row["image"]).relative_to(run).as_posix()
        require("\n" not in path and "\r" not in path, "invalid training sampling path")
        paths.extend(["./" + path] * repeat)
        inventory.append(dict(image_id=row["id"], group_id=row["group_id"], image=path,
            image_sha256=row["image_sha256"], repeat=repeat, smallest_box_fraction=fractions[row["id"]]))
        if preset == "target-replay-v1":
            inventory[-1]["reviewed_reasons"] = reasons.get(row["id"], [])
    listing = run / "train-samples.txt"
    listing.write_text("\n".join(paths)+"\n", encoding="utf-8")
    configuration = run / "data.yaml"
    content = yaml.safe_load(configuration.read_text(encoding="utf-8"))
    content["train"] = str(listing)
    configuration.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    audit = dict(preset=preset, dataset_id=manifest["dataset_id"], unique_training_images=len(rows),
                 training_entries=len(paths), repeated_images=sum(value > 1 for value in repeats.values()),
                 extra_exposures_are_new_images=False,
                 list_sha256=digest(listing), records=inventory)
    if preset == "small-body-v1":
        audit["max_repeated_images_per_group"] = 8
    else:
        audit.update(max_repeat_per_image=4, max_extra_exposures_per_group=48,
            review_bound_to_image_and_label=True, reasons_can_overlap=True)
    atomic_json(run / "training-sampling.json", audit)
    return audit


def verify_training_sampling(trainer, run):
    """Reject framework deduplication, unintended images or split leakage before optimization."""
    run = Path(run).resolve()
    audit = read_json(run / "training-sampling.json", 64 * 1024**2)
    require(digest(run / "train-samples.txt") == audit["list_sha256"], "training sampling list changed")
    expected = Counter({str(relative(run, r["image"])): r["repeat"] for r in audit["records"]})
    actual = Counter(str(Path(p).resolve()) for p in trainer.train_loader.dataset.im_files)
    require(actual == expected, "training sampling differs from the reviewed training inventory")
    atomic_json(run / "sampling-runtime.json", dict(verified=True,
        unique_training_images=len(actual), training_entries=sum(actual.values()),
        sampling_sha256=digest(run / "training-sampling.json")))


def validate_training_options(options):
    require(isinstance(options, dict), "training options must be an object")
    limits = {"lr0": (1e-6, 0.01), "lrf": (0.001, 1), "warmup_bias_lr": (0, 0.01),
              "warmup_epochs": (0, 10), "scale": (0, 0.5), "translate": (0, 0.3),
              "hsv_h": (0, 0.1), "hsv_s": (0, 0.7), "hsv_v": (0, 0.5),
              "mosaic": (0, 1), "degrees": (0, 180), "flipud": (0, 1), "fliplr": (0, 1)}
    allowed = set(limits) | {"optimizer", "freeze", "patience", "cos_lr", "amp", "camera_augmentation", "training_sampling", "nbs"}
    require(not set(options) - allowed, "unknown training option")
    for name, value in options.items():
        if name in limits:
            number(value, *limits[name])
        elif name == "nbs":
            require(type(value) is int and 1 <= value <= 128, "nbs must be an integer between 1 and 128")
        elif name in {"freeze", "patience"}:
            # YOLO11's detection head follows 23 feature layers.
            require(type(value) is int and 0 <= value <= (23 if name == "freeze" else 100), "invalid " + name)
        elif name in {"cos_lr", "amp"}:
            require(type(value) is bool, name + " must be boolean")
        elif name == "camera_augmentation":
            require(value == "grayscale-v1", "unknown camera augmentation preset")
        elif name == "training_sampling":
            require(isinstance(value, str) and value in {"small-body-v1", "target-replay-v1"},
                    "unknown training sampling preset")
        else:
            require(value in {"AdamW", "SGD"}, "use an explicit AdamW or SGD optimizer")
    require("lr0" not in options or "optimizer" in options, "explicit optimizer required to honor lr0")
    return dict(options)


def camera_augmentations(preset):
    """Photometric changes only: boxes and source-image counts stay unchanged."""
    if preset is None:
        return []
    require(preset == "grayscale-v1", "unknown camera augmentation preset")
    try:
        import albumentations as A
    except ImportError:
        require(False, "camera augmentation requires Albumentations; refusing an unaugmented run")
    require(A.__version__ == "2.0.8", "camera augmentation requires pinned Albumentations 2.0.8")
    return [A.ToGray(num_output_channels=3, method="weighted_average", p=0.35),
            A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.3, p=0.5)]


def verify_camera_augmentation(trainer):
    """Ultralytics can swallow an import/setup error; reject that before batches run."""
    pipeline = trainer.train_loader.dataset.transforms.transforms
    active = {}
    for wrapper in pipeline:
        if type(wrapper).__name__ == "Albumentations" and wrapper.transform is not None:
            active.update({type(t).__name__: t.p for t in wrapper.transform.transforms})
    require(active.get("ToGray") == 0.35 and active.get("RandomBrightnessContrast") == 0.5,
            "requested camera augmentation is not active in the training pipeline")


def train(dataset, weights, output, *, device="cpu", epochs=30, image_size=640, batch=4, threads=2,
          max_minutes=30, seed=42, smoke=False, training_options=None, parent_model_directory=None):
    options = validate_training_options({} if training_options is None else training_options)
    require(not options.get("amp", False) or (isinstance(device, str) and device.isdigit()),
            "AMP training requires an explicit CUDA device")
    manifest = load_dataset(dataset)
    require(manifest["dataset_kind"] == "real", "training requires reviewed real animal images; synthetic fixtures are not training data")
    weights = Path(weights).resolve()
    require(weights.is_file() and weights.suffix == ".pt", "supply an existing trusted pretrained .pt checkpoint")
    parent = load_model_card(parent_model_directory) if parent_model_directory else None
    if parent:
        require(parent["class_names"] == manifest["class_names"], "parent and dataset detection targets differ")
        require(digest(weights) == parent["weights"]["sha256"], "initial weights differ from parent model")
        assert_unseen(parent, [r for r in manifest["records"] if r["split"] == "test"])
    for value, low, high in ((epochs, 1, 1000), (batch, 1, 128), (threads, 1, 16), (image_size, 64, 1280), (max_minutes, 0.1, 1440)):
        number(value, low, high)
    require(image_size % 32 == 0, "image size must be a multiple of 32")
    if smoke:
        epochs, image_size, batch = 1, 160, 2
    with keep_awake(), output_directory(output, "train_detector") as run:
        YOLO = runtime(run / "runtime", threads)
        check_device(device)
        augmentation = camera_augmentations(options.get("camera_augmentation"))
        save_artifact(run / "environment.json", environment())
        save_artifact(run / "dataset-snapshot.json", manifest)
        recipe = {"initial_weights_sha256": digest(weights), "epochs": epochs, "image_size": image_size,
                  "batch": batch, "device": device, "threads": threads, "max_minutes": max_minutes,
                  "seed": seed, "smoke": smoke, "cloud_logging": False, "training_options": options}
        if augmentation:
            import albumentations as A
            recipe["augmentation_runtime"] = {"package": "albumentations", "version": A.__version__,
                                              "transforms": [A.to_dict(t) for t in augmentation],
                                              "real_infrared_images": False}
        save_artifact(run / "recipe.json", recipe)
        data_yaml = learner_data(dataset, manifest, run)
        sampling = write_training_sampling(manifest, run, options["training_sampling"]) if options.get("training_sampling") else None
        model = YOLO(str(weights), task="detect")
        budget = TrainingBudget(max_minutes)
        progress = TrainingProgress(run / "training-progress.json", amp=options.get("amp", False), expected_threads=threads)
        for event, callback in (("on_train_start", progress.start), ("on_train_epoch_start", progress.epoch_start),
                                ("on_train_batch_end", progress.batch_end), ("on_train_epoch_end", progress.epoch_end)):
            model.add_callback(event, callback)
        model.add_callback("on_train_batch_end", budget)
        model.add_callback("on_fit_epoch_end", budget)
        if augmentation:
            model.add_callback("on_train_start", verify_camera_augmentation)
        if sampling:
            model.add_callback("on_train_start", lambda trainer: verify_training_sampling(trainer, run))
        learner_options = {"patience": 10, "mosaic": 0.0, "amp": False, **options}
        learner_options.pop("camera_augmentation", None)
        learner_options.pop("training_sampling", None)
        # Keep optional package installation from changing recipes without an explicit choice.
        learner_options["augmentations"] = augmentation
        completed = False
        try:
            result = model.train(data=str(data_yaml), epochs=epochs, imgsz=image_size, batch=batch,
                                 device=device, workers=0, seed=seed, deterministic=True, cache=False,
                                 project=str(run), name="fit", exist_ok=False, plots=False, verbose=False,
                                 time=None, save=True, val=True, mixup=0.0, close_mosaic=0, **learner_options)
            completed = True
        finally:
            progress.finish(completed=completed)
        best = run / "fit" / "weights" / "best.pt"
        require(best.is_file(), "training produced no best checkpoint")
        if sampling:
            require(read_json(run / "sampling-runtime.json")["verified"] is True, "training sampling was not verified")
        shutil.copyfile(best, run / "best.pt")
        seen = [r for r in manifest["records"] if r["split"] in {"train", "val"}]
        card = {"schema_version": 1, "task": manifest["species"] + "_detection", "species": manifest["species"],
                "class_names": manifest["class_names"], "dataset_id": manifest["dataset_id"],
                "dataset_summary": dataset_summary(manifest), "recipe": recipe,
                "weights": {"path": "best.pt", "sha256": digest(run / "best.pt")},
                "seen_groups": sorted({r["group_id"] for r in seen}),
                "seen_image_hashes": sorted({r["image_sha256"] for r in seen}),
                "seen_pixel_hashes": sorted({r["pixel_sha256"] for r in seen}),
                "validation_metrics": metric_values(result), "status": "smoke_only" if smoke else "unvalidated_detector",
                "training_budget_reached": budget.reached,
                "training_progress": dict(path="training-progress.json", sha256=digest(progress.path),
                    **{k: v for k, v in progress.stats.items() if k != "epoch_attempts"}),
                "production_validated": False, "behavior_classifier": False, "anomaly_detector": False}
        if sampling:
            card["training_sampling"] = {k:v for k,v in sampling.items() if k != "records"}
        if parent:
            card["parent_model_id"] = parent["model_id"]
            for key in ("seen_groups", "seen_image_hashes", "seen_pixel_hashes"):
                card[key] = sorted(set(card[key]) | set(parent[key]))
        card["model_id"] = fingerprint(card)
        save_artifact(run / "model.json", card)
    return {"model_id": card["model_id"], "status": card["status"], "validation_metrics": card["validation_metrics"]}


def load_model_card(directory):
    directory = Path(directory).resolve()
    require(read_json(directory / "status.json")["state"] == "complete", "model run is incomplete")
    card = read_json(directory / "model.json", 64 * 1024**2)
    require(card["model_id"] == fingerprint({k: v for k, v in card.items() if k != "model_id"}), "model card integrity failure")
    require(card["schema_version"] == 1 and card["species"] in DETECTION_TARGETS and
            card["task"] == card["species"] + "_detection" and
            card["class_names"] == [card["species"]], "incompatible model task/species")
    require(digest(relative(directory, card["weights"]["path"])) == card["weights"]["sha256"], "model checkpoint integrity failure")
    return card


def assert_unseen(card, rows):
    require(card.get("training_inventory_known", True) is True,
            "publisher model training inventory is unknown; cannot claim held-out evaluation")
    for row in rows:
        require(row["group_id"] not in card["seen_groups"], "evaluation original group was used for training/validation")
        require(row["image_sha256"] not in card["seen_image_hashes"] and row["pixel_sha256"] not in card["seen_pixel_hashes"],
                "evaluation image was used for training/validation")


def evaluate(dataset, model_directory, output, *, device="cpu", threads=2):
    manifest = load_dataset(dataset)
    require(manifest["dataset_kind"] == "real", "held-out evaluation requires real images")
    card = load_model_card(model_directory)
    require(card["class_names"] == manifest["class_names"], "model and dataset detection targets differ")
    rows = [r for r in manifest["records"] if r["split"] == "test"]
    assert_unseen(card, rows)
    with keep_awake(), output_directory(output, "evaluate_detector") as run:
        YOLO = runtime(run / "runtime", threads)
        check_device(device)
        data_yaml = learner_data(dataset, manifest, run)
        model = YOLO(str(relative(Path(model_directory), card["weights"]["path"])), task="detect")
        require(list(model.names.values()) == card["class_names"], "checkpoint classes differ from model card")
        result = model.val(data=str(data_yaml), split="test", imgsz=card["recipe"]["image_size"], batch=2,
                           device=device, workers=0, plots=False, verbose=False, project=str(run), name="validation")
        report = {"model_id": card["model_id"], "dataset_id": manifest["dataset_id"], "split": "test",
                  "images": len(rows), "original_groups": len({r["group_id"] for r in rows}),
                  "metrics": metric_values(result), "evidence_scope": manifest["split_policy"],
                  "grouping_limit": dataset_summary(manifest)["grouping_limit"],
                  "model_status": card["status"], "animal_generalization_verified": False,
                  "label_review_methods": dataset_summary(manifest)["label_review_methods"],
                  "field_anomaly_performance_verified": False,
                  "test_reuse_note": "Changing the model after inspecting this report makes this test development data."}
        save_artifact(run / "evaluation.json", report)
    return report
