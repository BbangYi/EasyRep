import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import ExitStack

from behavior_recorder.core import RecorderError, atomic_json, digest, read_json
from behavior_recorder.vision_data import init_plan, load_dataset, output_directory, prepare_dataset, read_boxes
from behavior_recorder.vision_model import TrainingBudget, assert_unseen, learner_data, load_model_card, train
from behavior_recorder.vision_video import export_tracking_review, infer_video, observation, preview_geometry, render_review_frame, render_saved_review, sampled_frames, selected_boxes, source_video, validate_tracking_config

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("PIL"), "vision tests require requirements-vision.txt")
class VisionDatasetTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        rows = []
        for i, split in enumerate(("train", "val", "test")):
            (self.source / "images" / split).mkdir(parents=True)
            (self.source / "labels" / split).mkdir(parents=True)
            image = f"images/{split}/image-{i}.png"
            label = f"labels/{split}/image-{i}.txt"
            Image.new("RGB", (32, 24), (50 + i * 40, 30, 80)).save(self.source / image)
            (self.source / label).write_text("0 0.5 0.5 0.5 0.5\n")
            rows.append({"id": f"sample-{i}", "image": image, "label": label, "source_id": "fixture",
                         "group_id": f"recording-{i}", "split": split, "reviewer": "synthetic_fixture_generator",
                         "review_method": "synthetic_fixture", "species_confirmed": True})
        self.plan = {"schema_version": 1, "species": "crested_gecko", "dataset_kind": "synthetic_test",
                     "split_policy": "source_group_disjoint", "sources": [{"id": "fixture", "url": "test-fixture",
                     "license": "test-only", "attribution": "unit test", "provenance": "synthetic_test"}], "records": rows}
        self.plan_path = self.root / "plan.json"

    def prepare(self, name="prepared"):
        atomic_json(self.plan_path, self.plan)
        destination = self.root / name
        prepare_dataset(self.source, self.plan_path, destination)
        return destination

    def test_portable_dataset_preserves_inventory_and_labels(self):
        data = self.prepare()
        before = load_dataset(data)
        moved = self.root / "different-computer"
        shutil.move(data, moved)
        self.assertEqual(before, load_dataset(moved))
        self.assertNotIn(str(self.root), json.dumps(before))

    def test_original_group_leakage_is_rejected(self):
        self.plan["records"][2]["group_id"] = "recording-0"
        with self.assertRaisesRegex(RecorderError, "group leaks"):
            self.prepare()

    def test_lizard_target_survives_preparation_and_learner_staging(self):
        import yaml
        self.plan["species"] = "lizard"
        self.plan["split_policy"] = "asset_family_disjoint"
        self.plan["grouping_limit"] = "Original capture sessions and individual identities unavailable."
        data = self.prepare()
        manifest = load_dataset(data)
        self.assertEqual(manifest["class_names"], ["lizard"])
        self.assertEqual(manifest["grouping_limit"], self.plan["grouping_limit"])
        run = self.root / "learner"
        run.mkdir()
        configuration = learner_data(data, manifest, run)
        self.assertEqual(yaml.safe_load(configuration.read_text())["names"], ["lizard"])

    def test_asset_grouping_requires_explicit_limit(self):
        self.plan["split_policy"] = "asset_family_disjoint"
        with self.assertRaisesRegex(RecorderError, "grouping_limit"):
            self.prepare()

    def test_image_ids_are_portable_and_review_method_is_explicit(self):
        for key in ("frame:1", "CON", "com1", "x."):
            self.plan["records"][0]["id"] = key
            with self.assertRaisesRegex(RecorderError, "portable filename"):
                self.prepare()
        self.plan["records"][0]["id"] = "sample-0"
        self.plan["records"][0]["review_method"] = "human"
        with self.assertRaisesRegex(RecorderError, "review method"):
            self.prepare()

    def test_decoded_duplicates_are_rejected_even_in_another_container(self):
        from PIL import Image
        first, last = self.plan["records"][0], self.plan["records"][2]
        with Image.open(self.source / first["image"]) as image:
            image.save(self.source / last["image"], compress_level=0)
        with self.assertRaisesRegex(RecorderError, "duplicate decoded"):
            self.prepare()

    def test_case_insensitive_image_ids_cannot_overwrite_on_windows(self):
        self.plan["records"][1]["id"] = self.plan["records"][0]["id"].upper()
        with self.assertRaisesRegex(RecorderError, "duplicate image ID"):
            self.prepare()

    def test_missing_annotations_are_not_negative_examples(self):
        (self.source / self.plan["records"][0]["label"]).unlink()
        with self.assertRaisesRegex(RecorderError, "missing/oversized label"):
            self.prepare()

    def publisher_background(self):
        from PIL import Image
        self.plan['dataset_kind'] = 'real'
        self.plan['sources'][0]['provenance'] = 'public_real'
        for row in self.plan['records']:
            row['review_method'] = 'publisher_annotations'
        row = dict(self.plan['records'][0], id='background', group_id='background-capture',
                   image='images/train/background.png', label='labels/train/background.txt')
        Image.new('RGB', (32, 24), (5, 100, 200)).save(self.source / row['image'])
        (self.source / row['label']).write_text('')
        self.plan['records'].append(row)
        return row

    def test_missing_publisher_target_boxes_do_not_prove_target_absence(self):
        self.publisher_background()
        with self.assertRaisesRegex(RecorderError, 'target absence'):
            self.prepare()

    def test_publisher_background_requires_visual_review_of_the_exact_image(self):
        row = self.publisher_background()
        review = dict(verdict='no_visible_target', review_method='assistant', reviewer='visual review',
                      image_sha256=digest(self.source / row['image']), note='Whole image checked for lizards.')
        row['target_absence_review'] = review
        self.assertEqual(len(load_dataset(self.prepare())['records']), 4)
        for field, value in [('image_sha256', '0'*64), ('verdict', 'unknown'),
                             ('review_method', 'publisher_annotations'), ('reviewer', ''), ('note', '')]:
            row['target_absence_review'] = {**review, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(RecorderError, 'target absence'):
                self.prepare('invalid-' + field)

    def test_archived_incomplete_labels_are_viewable_but_cannot_train_or_score(self):
        from behavior_recorder.analysis_features import fingerprint
        row = self.publisher_background()
        row['target_absence_review'] = dict(verdict='no_visible_target', review_method='assistant',
            reviewer='visual review', image_sha256=digest(self.source / row['image']), note='Whole image checked.')
        dataset = self.prepare()
        manifest = load_dataset(dataset)
        del manifest['records'][-1]['target_absence_review']
        manifest['dataset_id'] = fingerprint({k:v for k,v in manifest.items() if k != 'dataset_id'})
        atomic_json(dataset / 'dataset.json', manifest)
        self.assertEqual(len(load_dataset(dataset, inspection_only=True)['records']), 4)
        with self.assertRaisesRegex(RecorderError, 'target absence'):
            load_dataset(dataset)

    def test_unreviewed_and_other_species_cannot_train(self):
        for change in ({"reviewer": None}, {"species_confirmed": False}, {"group_id": None}):
            plan = copy.deepcopy(self.plan)
            self.plan["records"][0].update(change)
            with self.assertRaises(RecorderError):
                self.prepare()
            self.plan = plan
        self.plan["species"] = "leopard_gecko"
        with self.assertRaisesRegex(RecorderError, "crested_gecko"):
            self.prepare()

    def test_annotation_damage_and_class_mismatch(self):
        label = self.source / self.plan["records"][0]["label"]
        for text in ("0 nan 0.5 0.2 0.2", "0 0.01 0.5 0.9 0.5", "1 0.5 0.5 0.5 0.5", "0 0.5 0.5 0 0.5"):
            label.write_text(text)
            with self.assertRaises(RecorderError):
                read_boxes(label)

    def test_paths_cannot_escape_dataset(self):
        self.plan["records"][0]["image"] = "../escape.png"
        with self.assertRaisesRegex(RecorderError, "unsafe relative"):
            self.prepare()

    def test_symlink_is_not_an_input_image(self):
        path = self.source / self.plan["records"][0]["image"]
        original = path.with_name("original.png")
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            self.skipTest("platform cannot create symlinks")
        with self.assertRaisesRegex(RecorderError, "symlink"):
            self.prepare()

    def test_mutated_and_unlisted_files_are_rejected(self):
        data = self.prepare()
        row = load_dataset(data)["records"][0]
        (data / row["label"]).write_text("0 0.5 0.5 0.25 0.25\n")
        with self.assertRaisesRegex(RecorderError, "integrity failure"):
            load_dataset(data)
        other = self.prepare("other")
        shutil.copyfile(other / row["image"], other / "images/train/unlisted.png")
        with self.assertRaisesRegex(RecorderError, "unlisted"):
            load_dataset(other)

    def test_failed_run_and_overwrite_do_not_look_complete(self):
        output = self.root / "failed"
        with self.assertRaisesRegex(RuntimeError, "broken"):
            with output_directory(output, "fixture"):
                raise RuntimeError("broken")
        self.assertEqual(read_json(output / "status.json")["state"], "failed")
        with self.assertRaises(FileExistsError):
            with output_directory(output, "fixture"):
                self.fail("must not enter")

    def test_synthetic_fixture_is_refused_by_training(self):
        data = self.prepare()
        with self.assertRaisesRegex(RecorderError, "real animal"):
            train(data, self.root / "missing.pt", self.root / "run")
        self.assertFalse((self.root / "run").exists())

    def test_import_stays_unreviewed(self):
        output = self.root / "import.json"
        result = init_plan(self.source, output, "https://example.invalid/dataset", "CC0", "test publisher")
        plan = read_json(output)
        self.assertFalse(result["ready_for_training"])
        self.assertTrue(all(r["reviewer"] is None and r["group_id"] is None for r in plan["records"]))
        with self.assertRaises(RecorderError):
            prepare_dataset(self.source, output, self.root / "invalid")

    def test_test_set_checks_training_and_validation_exposure(self):
        data = load_dataset(self.prepare())
        seen = data["records"][0]
        card = {"seen_groups": [seen["group_id"]], "seen_image_hashes": [seen["image_sha256"]],
                "seen_pixel_hashes": [seen["pixel_sha256"]]}
        assert_unseen(card, [data["records"][2]])
        with self.assertRaisesRegex(RecorderError, "training inventory is unknown"):
            assert_unseen({**card, "training_inventory_known": False}, [data["records"][2]])
        with self.assertRaises(RecorderError):
            assert_unseen(card, [seen])
        renamed = {**seen, "group_id": "different", "image_sha256": "different"}
        with self.assertRaisesRegex(RecorderError, "image was used"):
            assert_unseen(card, [renamed])


class TrackingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.config = read_json(ROOT / "examples/vision.tracking.json")
        self.config["zones"] = {"left": [0, 0, 0.5, 1], "right": [0.5, 0, 0.5, 1]}

    def box(self, x=10, track=1):
        return {"xyxy": [x, 10, x + 10, 20], "confidence": 0.9, "track_id": track}

    def observe(self, boxes, previous=None, time=0):
        return observation(boxes, previous, time, 100, 100, self.config)

    def test_missing_multiple_and_untracked_are_unknown(self):
        for boxes in ([], [self.box(), self.box(60, 2)], [self.box(track=None)]):
            row = self.observe(boxes)
            self.assertNotEqual(row["status"], "observed")
            self.assertIsNone(row["speed_diagonals_per_second"])
            self.assertIsNone(row["behavior"])

    def test_motion_is_not_connected_across_occlusion_identity_or_time_gap(self):
        first = self.observe([self.box()])
        moving = self.observe([self.box(15)], first, 0.3)
        self.assertGreater(moving["speed_diagonals_per_second"], 0)
        self.assertIsNone(self.observe([self.box(15)], first, 2)["speed_diagonals_per_second"])
        self.assertIsNone(self.observe([self.box(15, 2)], first, 0.3)["speed_diagonals_per_second"])
        hidden = self.observe([], first, 0.3)
        self.assertIsNone(self.observe([self.box(15)], hidden, 0.6)["speed_diagonals_per_second"])

    def test_large_jump_is_abstention(self):
        row = self.observe([self.box(70)], self.observe([self.box()]), 0.3)
        self.assertEqual(row["status"], "implausible_track_jump")
        self.assertIsNone(row["zone"])

    def test_zone_boundary_and_overlap(self):
        self.assertEqual(self.observe([self.box(45)])["zone"], "right")
        self.config["zones"]["whole"] = [0, 0, 1, 1]
        row = self.observe([self.box()])
        self.assertIsNone(row["zone"])
        self.assertEqual(row["zone_status"], "overlapping_zones")
        self.config["zones"]["whole"] = [0.5, 0, 1, 1]
        with self.assertRaises(RecorderError):
            validate_tracking_config(self.config)


class LearnerContractTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("cv2"), "requires OpenCV")
    def test_scene_change_breaks_identity_and_expires_manual_target(self):
        import cv2
        import numpy as np
        config = read_json(ROOT / "examples/vision.tracking.json")
        config['sample_fps'] = 5
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.avi"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'FFV1'), 5, (100, 100))
            self.assertTrue(writer.isOpened())
            try:
                for i in range(4):
                    writer.write(np.full((100, 100, 3), 0 if i < 2 else 255, dtype=np.uint8))
            finally:
                writer.release()
            (root / "weights.pt").write_bytes(b"mock checkpoint")
            metadata = {"width": 100, "height": 100, "sha256": digest(source), "duration_seconds": 1}
            times = [{"frame_index": i, "pts": i, "offset_seconds": i * .2,
                      "time_base": "1/5", "estimated_capture_at": None} for i in range(4)]
            card = {"species": config["species"], "class_names": [config["species"]],
                    "weights": {"path": "weights.pt"}, "recipe": {"image_size": 640},
                    "model_id": "mock-model", "status": "unvalidated_detector"}
            detector = SimpleNamespace(names={0: config["species"]})
            for seeded in (False, True):
                selected = dict(config)
                if seeded:
                    selected['target_seed'] = {'source_sha256': digest(source), 'xyxy': [.1, .2, .3, .4]}
                with ExitStack() as stack:
                    overrides = {"load_model_card": card, "runtime": lambda *a, **k: detector,
                                 "source_video": (source, metadata, times),
                                 "probe": ({}, times, 1), "check_device": None}
                    for name, value in overrides.items():
                        stack.enter_context(patch("behavior_recorder.vision_video." + name, return_value=value))
                    stack.enter_context(patch("behavior_recorder.vision_video.predict_frame",
                        side_effect=lambda *a, **k: ([{'xyxy': [10, 20, 30, 40], 'confidence': .9}], {'actual_device': 'cpu'})))
                    stack.enter_context(patch("cv2.VideoWriter"))
                    output = root / str(seeded)
                    infer_video(root, output, selected, video=source)
                rows = [json.loads(line) for line in (output / 'observations.jsonl').read_text().splitlines()]
                self.assertEqual(rows[1]['status'], 'observed')
                if seeded:
                    self.assertEqual(rows[2]['detections'], [])
                    self.assertEqual(rows[2]['target_selection'], 'seed_lost_requires_new_selection')
                else:
                    self.assertNotEqual(rows[2]['detections'][0]['track_id'], rows[1]['detections'][0]['track_id'])
                    self.assertFalse(rows[2]['detections'][0]['motion_allowed'])
                    self.assertIsNone(rows[3]['speed_diagonals_per_second'])
                    self.assertEqual(rows[3]['detections'][0]['identity_status'], 'active')

    def test_video_resolution_is_bounded_and_integer(self):
        config = read_json(ROOT / "examples/vision.tracking.json")
        for invalid in [True, 640.0, 63, 641, 1312, None]:
            with self.subTest(value=invalid), self.assertRaises(RecorderError):
                validate_tracking_config({**config, "inference_image_size": invalid})

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "requires OpenCV")
    def test_video_resolution_reaches_detector_and_saved_evidence(self):
        import numpy as np
        from unittest.mock import MagicMock
        config = read_json(ROOT / "examples/vision.tracking.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            source.write_bytes(b"mock video")
            (root / "weights.pt").write_bytes(b"mock checkpoint")
            metadata = {"width": 100, "height": 100, "sha256": digest(source), "duration_seconds": 1}
            timing = {"frame_index": 0, "pts": 0, "offset_seconds": 0.0,
                      "time_base": "1/25", "estimated_capture_at": None, "scene_boundary": {"cut": False}}
            card = {"species": config["species"], "class_names": [config["species"]],
                    "weights": {"path": "weights.pt"}, "recipe": {"image_size": 640},
                    "model_id": "mock-model", "status": "unvalidated_detector"}
            boxes = MagicMock()
            boxes.__iter__.return_value = iter([])
            boxes.data.device = "cpu"
            detector = MagicMock()
            detector.names = {0: config["species"]}
            detector.predict.return_value = [SimpleNamespace(boxes=boxes)]
            with ExitStack() as stack:
                overrides = {"load_model_card": card, "runtime": lambda *a, **k: detector,
                             "source_video": (source, metadata, [timing]),
                             "sampled_frames": [(np.zeros((100, 100, 3), dtype=np.uint8), timing)],
                             "probe": ({}, [timing], 1), "check_device": None}
                for name, value in overrides.items():
                    stack.enter_context(patch("behavior_recorder.vision_video." + name, return_value=value))
                stack.enter_context(patch("cv2.VideoWriter"))
                for index, size in enumerate([None, 1280]):
                    selected = dict(config)
                    if size is not None:
                        selected["inference_image_size"] = size
                    report = infer_video(root, root / str(index), selected, video=source)
                    expected = size or 640
                    self.assertEqual(detector.predict.call_args.kwargs["imgsz"], expected)
                    self.assertEqual(report["config"]["inference_image_size"], expected)
                self.assertNotIn("inference_image_size", config)

    def test_budget_stops_without_changing_epoch_limit(self):
        with patch("behavior_recorder.vision_model.time.monotonic", side_effect=[100, 105, 107]):
            budget = TrainingBudget(0.1)
            trainer = SimpleNamespace(stop=False, epochs=1)
            budget(trainer)
            self.assertFalse(trainer.stop)
            budget(trainer)
            self.assertTrue(trainer.stop)
            self.assertEqual(trainer.epochs, 1)

    def test_train_adapter_preserves_recipe_and_failure_status(self):
        # Entire learner and data loader are mocked. No fixture is sent to real training.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "initial.pt"
            weights.write_bytes(b"mock checkpoint")
            manifest = {"dataset_kind": "real", "species": "crested_gecko", "class_names": ["crested_gecko"],
                        "dataset_id": "mock-data", "records": [
                {"split": "train", "group_id": "train-recording", "image_sha256": "a", "pixel_sha256": "b"},
                {"split": "val", "group_id": "val-recording", "image_sha256": "c", "pixel_sha256": "d"}]}
            calls = []

            class LearnerOptimizer:
                def __init__(self):
                    self.hooks = []

                def register_step_post_hook(self, callback):
                    self.hooks.append(callback)
                    return SimpleNamespace(remove=lambda: self.hooks.remove(callback))

                def step(self):
                    for callback in self.hooks:
                        callback(self, (), {})

            class MockYOLO:
                def __init__(self, *args, **kwargs):
                    self.callbacks = {}

                def add_callback(self, event, callback):
                    calls.append(event)
                    self.callbacks.setdefault(event, []).append(callback)

                def train(self, **kwargs):
                    calls.append(kwargs)
                    optimizer = LearnerOptimizer()
                    trainer = SimpleNamespace(device="cpu", amp=False,
                        scaler=SimpleNamespace(is_enabled=lambda: False), optimizer=optimizer,
                        train_loader=[None], batch_size=kwargs["batch"], epoch=0, stop=False)
                    for event in ("on_train_start", "on_train_epoch_start"):
                        for callback in self.callbacks.get(event, []):
                            callback(trainer)
                    optimizer.step()
                    for event in ("on_train_batch_end", "on_train_epoch_end", "on_fit_epoch_end"):
                        for callback in self.callbacks.get(event, []):
                            callback(trainer)
                    output = Path(kwargs["project"]) / "fit/weights/best.pt"
                    output.parent.mkdir(parents=True)
                    output.write_bytes(b"mock trained checkpoint")
                    return SimpleNamespace(results_dict={"mock_metric": 0.0})

            import torch
            self.addCleanup(torch.set_num_threads, torch.get_num_threads())

            def mock_runtime(directory, threads=2):
                torch.set_num_threads(threads)
                return MockYOLO

            with patch("behavior_recorder.vision_model.load_dataset", return_value=manifest), \
                 patch("behavior_recorder.vision_model.runtime", side_effect=mock_runtime), \
                 patch("behavior_recorder.vision_model.check_device"), \
                 patch("behavior_recorder.vision_model.environment", return_value={"mock": True}), \
                 patch("behavior_recorder.vision_model.dataset_summary", return_value={"mock": True}), \
                 patch("behavior_recorder.vision_model.learner_data", return_value=root / "mock.yaml"):
                options = {"optimizer": "AdamW", "lr0": 0.0001, "freeze": 11, "patience": 20,
                           "mosaic": 0.5, "degrees": 30, "flipud": 0.2, "fliplr": 0.0, "nbs": 2}
                train(root, weights, root / "fit", smoke=True, training_options=options)
                card = load_model_card(root / "fit")
                self.assertEqual(card["status"], "smoke_only")
                self.assertFalse(card["production_validated"])
                self.assertEqual(card["seen_groups"], ["train-recording", "val-recording"])
                self.assertEqual(calls[-1]["epochs"], 1)
                self.assertIsNone(calls[-1]["time"])
                self.assertFalse(calls[-1]["amp"])
                self.assertEqual(card["training_progress"]["optimizer_steps"], 1)
                self.assertEqual(card["training_progress"]["full_passes_processed"], 1)
                self.assertEqual(card["recipe"]["training_options"], options)
                self.assertTrue(all(calls[-1][key] == value for key, value in options.items()))
                self.assertIn("on_train_batch_end", calls)
                parent = {"model_id": "prior-model", "class_names": ["crested_gecko"], "weights": {"sha256": digest(weights)},
                          "seen_groups": ["ancestral-group"], "seen_image_hashes": ["prior-image"],
                          "seen_pixel_hashes": ["prior-pixels"]}
                with patch("behavior_recorder.vision_model.load_model_card", return_value=parent):
                    train(root, weights, root / "child", smoke=True, parent_model_directory=root / "parent")
                    manifest["records"].append({"split": "test", "group_id": "ancestral-group",
                                                "image_sha256": "unseen", "pixel_sha256": "unseen"})
                    with self.assertRaisesRegex(RecorderError, "original group"):
                        train(root, weights, root / "leaked", smoke=True, parent_model_directory=root / "parent")
                    manifest["records"].pop()
                    manifest.update(species="lizard", class_names=["lizard"])
                    with self.assertRaisesRegex(RecorderError, "targets differ"):
                        train(root, weights, root / "wrong-target", smoke=True, parent_model_directory=root / "parent")
                child = load_model_card(root / "child")
                self.assertEqual(child["parent_model_id"], "prior-model")
                self.assertIn("ancestral-group", child["seen_groups"])
                self.assertIn("prior-pixels", child["seen_pixel_hashes"])
                train(root, weights, root / "generic", smoke=True)
                self.assertEqual(load_model_card(root / "generic")["task"], "lizard_detection")
                self.assertFalse((root / "leaked").exists())
                with patch.object(MockYOLO, "train", side_effect=RuntimeError("learner failure")):
                    with self.assertRaisesRegex(RuntimeError, "learner failure"):
                        train(root, weights, root / "failed", smoke=True)
                self.assertEqual(read_json(root / "failed/status.json")["state"], "failed")
                self.assertFalse((root / "failed/model.json").exists())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe") and importlib.util.find_spec("cv2"),
                     "video adapter tests need FFmpeg and OpenCV")
class VideoSamplingTests(unittest.TestCase):
    def test_saved_review_and_export_follow_recorded_indices_after_sampling_changes(self):
        import cv2
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x120:rate=5', '-frames:v', '10', '-c:v', 'ffv1',
                            '-threads', '1', str(video)], check=True, timeout=20)
            _, metadata, timeline = source_video(video=video, provenance='synthetic_test')
            config = read_json(ROOT / 'examples/vision.tracking.json')
            config['sample_fps'] = 3
            indices = [0, 2, 4, 6, 8]  # Saved by the previous minimum-spacing sampler.
            rows = [{**timeline[i], 'status': 'no_confident_track', 'detections': []} for i in indices]
            analysis = root / 'analysis'
            analysis.mkdir()
            atomic_json(analysis / 'summary.json', dict(source=metadata, config=config, model_id='fixture'))
            atomic_json(analysis / 'status.json', dict(state='complete'))
            observations = analysis / 'observations.jsonl'
            observations.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            checksum = digest(observations)
            report = render_saved_review(analysis, video, root / 'preview')
            self.assertEqual(report['frames'], 5)
            export_tracking_review(analysis, video, root / 'labels', selection='consecutive', limit=5)
            refs = read_json(root / 'labels/references.json')['records']
            self.assertEqual([r['frame_index'] for r in refs], indices)
            self.assertEqual([r['pts'] for r in refs], [timeline[i]['pts'] for i in indices])
            decoder = cv2.VideoCapture(str(video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
            try:
                expected = [decoder.read()[1] for _ in range(10)]
            finally:
                decoder.release()
            for ref in refs:
                actual = cv2.imread(str(root / 'labels' / ref['image']))
                self.assertTrue((actual == expected[ref['frame_index']]).all())
            self.assertEqual(digest(observations), checksum)

    def test_millisecond_pts_keep_every_native_frame_when_sampling_at_30_fps(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / 'rounded.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x120:rate=30000/1001', '-frames:v', '10',
                            '-c:v', 'ffv1', '-threads', '1', str(video)], check=True, timeout=20)
            path, metadata, timeline = source_video(video=video)
            self.assertEqual(metadata['time_base'], '1/1000')
            self.assertEqual([r['offset_seconds'] for r in timeline],
                             [0, .033, .067, .100, .133, .167, .200, .234, .267, .300])
            selected = [row for _, row in sampled_frames(path, metadata, timeline, 30)]
            self.assertEqual(selected, timeline)

    def test_timestamp_gap_does_not_create_frames_or_shift_future_sampling(self):
        import cv2
        import numpy as np
        from unittest.mock import MagicMock
        frames = [np.full((4, 4, 3), i, dtype=np.uint8) for i in range(6)]
        timeline = [dict(frame_index=i, offset_seconds=t, pts=round(t * 1000))
                    for i, t in enumerate([0, .100, .190, 2.010, 2.020, 2.340])]
        capture = MagicMock()
        capture.read.side_effect = [(True, frame) for frame in frames] + [(False, None)]
        with patch.object(cv2, 'VideoCapture', return_value=capture):
            selected = list(sampled_frames('fixture.mkv', dict(width=4, height=4, time_base='1/1000'), timeline, 3))
        self.assertEqual([row['frame_index'] for _, row in selected], [0, 3, 5])
        self.assertEqual([int(frame[0, 0, 0]) for frame, _ in selected], [0, 3, 5])
        self.assertEqual([row['pts'] for _, row in selected], [0, 2010, 2340])
        capture.release.assert_called_once()

    def test_sampler_limits_real_decoder_workers_without_changing_frames(self):
        import cv2
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x120:rate=5', '-t', '1', '-c:v', 'libx264',
                            '-threads', '1', str(path)], check=True, timeout=20)
            original, metadata, timeline = source_video(video=path)
            real_capture = cv2.VideoCapture
            opened = []

            def observe_capture(*args, **kwargs):
                capture = real_capture(*args, **kwargs)
                opened.append((capture.getBackendName(), capture.get(cv2.CAP_PROP_N_THREADS)))
                return capture

            with patch.object(cv2, 'VideoCapture', side_effect=observe_capture):
                frames = list(sampled_frames(original, metadata, timeline, 5))
            self.assertEqual(opened, [('FFMPEG', 1.0)])
            self.assertEqual([row['frame_index'] for _, row in frames], list(range(5)))
            reference = real_capture(str(path), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
            try:
                for frame, _ in frames:
                    ok, expected = reference.read()
                    self.assertTrue(ok)
                    self.assertTrue((frame == expected).all())
            finally:
                reference.release()

    def test_display_and_tracking_use_same_inclusive_threshold(self):
        import numpy as np
        config=read_json(ROOT / 'examples/vision.tracking.json')
        boxes=[{'xyxy':[10,10,20,20],'confidence':0.3999,'track_id':2},
               {'xyxy':[60,60,90,80],'confidence':0.4,'track_id':1}]
        self.assertEqual(selected_boxes(boxes,config),[boxes[1]])
        row=observation(boxes,None,0,200,100,config)
        self.assertEqual(row['track_id'],1)
        row['detections']=boxes
        frame=np.zeros((100,200,3),dtype=np.uint8)
        rendered=render_review_frame(frame,row,config)
        width,height=preview_geometry(200,100)
        self.assertEqual(rendered.shape,(height+112,width,3))
        self.assertEqual(rendered[112+round(20*height/100),round(10*width/200)].tolist(),[0,0,0])
        self.assertEqual(rendered[112+round(80*height/100),round(90*width/200)].tolist(),[20,165,255])
        self.assertFalse(frame.any())

    def test_saved_preview_preserves_observations_and_rejects_wrong_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=160x120:rate=5',
                            '-t','1','-c:v','mpeg4','-threads','1',str(video)],check=True,timeout=15)
            path,metadata,timeline=source_video(video=video,provenance='synthetic_test')
            config=read_json(ROOT/'examples/vision.tracking.json')
            rows=[]
            for frame,timing in sampled_frames(path,metadata,timeline,config['sample_fps']):
                rows.append({**timing,'status':'no_confident_track','detections':[]})
            analysis=root/'analysis';analysis.mkdir()
            atomic_json(analysis/'summary.json',{'source':metadata,'config':config,'model_id':'fixture'})
            observations=analysis/'observations.jsonl'
            observations.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            before=digest(observations)
            report=render_saved_review(analysis,video,root/'new-review')
            self.assertEqual(before,digest(observations))
            self.assertEqual(report['frames'],len(rows))
            self.assertFalse(report['model_rerun'])
            self.assertFalse(report['metrics_changed'])
            atomic_json(analysis/'status.json',{'state':'complete'})
            exported=export_tracking_review(analysis,video,root/'label-queue',limit=2,spacing_seconds=0.3)
            queue=read_json(root/'label-queue/review.json')
            self.assertEqual(exported['frames'],2)
            self.assertFalse(queue['ready_for_training'])
            self.assertTrue(all(r['reference_boxes'] is None and not r['reviewed'] for r in queue['records']))
            self.assertEqual(len({r['group_id'] for r in queue['records']}),1)
            self.assertEqual(before,digest(observations))
            export_tracking_review(analysis,video,root/'uniform-review',limit=2,selection='uniform')
            uniform=read_json(root/'uniform-review/references.json')
            self.assertEqual([r['frame_index'] for r in uniform['records']], [rows[0]['frame_index'],rows[-1]['frame_index']])
            self.assertEqual(uniform['selection'],'uniform')
            self.assertTrue(all(r['visibility'] is None and r['reference_boxes'] is None and not r['reviewed'] for r in uniform['records']))
            export_tracking_review(analysis,video,root/'consecutive-review',limit=3,selection='consecutive')
            sequence=read_json(root/'consecutive-review/references.json')
            self.assertEqual([r['frame_index'] for r in sequence['records']], [r['frame_index'] for r in rows[:3]])
            rows[0]['frame_index']=99
            observations.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            with self.assertRaisesRegex(RecorderError,'frame differs'):
                render_saved_review(analysis,video,root/'wrong-review')

    def test_sampling_preserves_pts_and_never_duplicates_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                            "testsrc2=size=160x120:rate=5", "-t", "2", "-c:v", "libx264",
                            "-threads", "1", "-bf", "2", "-output_ts_offset", "7", str(path)],
                           check=True, timeout=20)
            original, metadata, timeline = source_video(video=path)
            self.assertEqual(metadata["provenance"], "unverified_file")
            _, declared, _ = source_video(video=path, provenance="synthetic_test")
            self.assertEqual(declared["provenance"], "synthetic_test")
            self.assertEqual(declared["provenance_basis"], "operator_declaration")
            with self.assertRaisesRegex(RecorderError, "invalid video provenance"):
                source_video(video=path, provenance="verified_animal_behavior")
            self.assertIsNone(metadata["captured_at"])
            self.assertGreater(timeline[0]["pts"], 0)
            selected = [row for frame, row in sampled_frames(original, metadata, timeline, 3)]
            self.assertEqual([r["frame_index"] for r in selected], [0, 2, 4, 5, 7, 9])
            self.assertEqual([r["offset_seconds"] for r in selected], [0, 0.4, 0.8, 1.0, 1.4, 1.8])
            self.assertEqual(len(list(sampled_frames(original, metadata, timeline, 30))), 10)
            with self.assertRaisesRegex(RecorderError, "more frames"):
                list(sampled_frames(original, metadata, timeline[:-1], 3))
            with self.assertRaisesRegex(RecorderError, "decode ended"):
                list(sampled_frames(original, metadata, timeline + [timeline[-1]], 3))


if __name__ == "__main__":
    unittest.main()
