"""Reviewed, grouped YOLO detection datasets with a portable content inventory."""
from collections import Counter
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import shutil

from .analysis_features import fingerprint, save_artifact
from .core import atomic_json, digest, identifier, now, number, read_json, relative, require

SPECIES = "crested_gecko"
DETECTION_TARGETS = {SPECIES, "lizard"}
SPLITS = ("train", "val", "test")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@contextmanager
def output_directory(path, operation):
    """Reserve one run; failed/interrupted outputs cannot look complete or be overwritten."""
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    status = {"operation": operation, "state": "running", "started_at": now()}
    atomic_json(path / "status.json", status)
    try:
        yield path
    except BaseException as exc:
        atomic_json(path / "status.json", {**status, "state": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                                          "finished_at": now(), "error": str(exc)})
        raise
    else:
        atomic_json(path / "status.json", {**status, "state": "complete", "finished_at": now()})


def image_info(path):
    from PIL import Image
    require(path.suffix.lower() in IMAGE_SUFFIXES and path.is_file(), f"unsupported/missing image: {path.name}")
    require(0 < path.stat().st_size <= 32 * 1024**2, "image size limit exceeded")
    with Image.open(path) as image:
        require(image.width * image.height <= 24_000_000, "image pixel limit exceeded")
        require(image.width >= 16 and image.height >= 16, "image is too small")
        require(image.getexif().get(274, 1) == 1, "normalize EXIF orientation before labeling")
        require(getattr(image, "n_frames", 1) == 1, "animated images are not supported")
        image.load()
        rgb = image.convert("RGB")
        pixel_hash = hashlib.sha256(f"{image.width}x{image.height}:".encode() + rgb.tobytes()).hexdigest()
        return {"width": image.width, "height": image.height, "pixel_sha256": pixel_hash}


def read_boxes(path):
    require(path.is_file() and path.stat().st_size <= 1024**2, f"missing/oversized label: {path.name}")
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        require(len(parts) == 5 and parts[0] == "0", "labels must contain class 0 and cx cy width height")
        x, y, w, h = [number(float(v), 0, 1) for v in parts[1:]]
        require(w > 0 and h > 0 and x - w / 2 >= -1e-6 and y - h / 2 >= -1e-6
                and x + w / 2 <= 1 + 1e-6 and y + h / 2 <= 1 + 1e-6, "box outside image")
        result.append([x, y, w, h])
    require(len(result) <= 100, "too many boxes in an image")
    return result


def init_plan(root, output, source_url, license_name, attribution):
    """Import a YOLO/CVAT layout as an explicitly unreviewed plan, never as ground truth."""
    root = Path(root).resolve()
    records = []
    for split in SPLITS:
        variants = [root / "images" / split, root / split / "images"]
        if split == "val":
            variants.append(root / "valid" / "images")
        present = [p for p in variants if p.is_dir()]
        require(len(present) <= 1, f"ambiguous {split} image directory")
        if not present:
            continue
        image_dir = present[0]
        label_dir = root / "labels" / split if image_dir == root / "images" / split else image_dir.parent / "labels"
        for image in sorted(image_dir.rglob("*")):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            local = image.relative_to(image_dir)
            records.append({"id": f"image-{len(records):06d}", "image": image.relative_to(root).as_posix(),
                            "label": (label_dir / local.with_suffix(".txt")).relative_to(root).as_posix(),
                            "source_id": "source-1", "group_id": None, "split": split,
                            "reviewer": None, "review_method": None, "species_confirmed": False})
    require(records, "no images found; use images/train, images/val, images/test or train/images, valid/images, test/images")
    plan = {"schema_version": 1, "species": SPECIES, "dataset_kind": "real",
            "split_policy": "source_group_disjoint", "sources": [{"id": "source-1", "url": source_url,
            "license": license_name, "attribution": attribution, "provenance": "public_real"}], "records": records}
    save_artifact(output, plan)
    return {"images": len(records), "ready_for_training": False,
            "next": "Review labels/species and assign original-video/session group_id plus reviewer to every image."}


def validate_plan(plan, root, *, inspection_only=False):
    require(plan.get("schema_version") == 1 and plan.get("species") in DETECTION_TARGETS,
            "dataset schema 1 supports crested_gecko or lizard detection")
    require(plan.get("dataset_kind") in {"real", "synthetic_test"}, "dataset_kind required")
    require(plan.get("split_policy") in {"source_group_disjoint", "asset_family_disjoint"}, "explicit disjoint split policy required")
    if plan["split_policy"] == "asset_family_disjoint":
        require(isinstance(plan.get("grouping_limit"), str) and plan["grouping_limit"].strip(),
                "asset grouping requires grouping_limit; capture sessions/individuals may be unknown")
    sources = {}
    for source in plan["sources"]:
        key = identifier(source["id"])
        require(key not in sources, "duplicate source ID")
        for field in ("url", "license", "attribution"):
            require(isinstance(source.get(field), str) and source[field].strip(), f"source {field} required")
        allowed = {"public_real", "real_camera"} if plan["dataset_kind"] == "real" else {"synthetic_test"}
        require(source.get("provenance") in allowed, "source provenance differs from dataset kind")
        sources[key] = source
    require(isinstance(plan["records"], list) and 0 < len(plan["records"]) <= 100000, "empty/oversized dataset")
    records, ids, seen_paths, seen_pixels, groups = [], set(), set(), {}, {}
    positives = Counter()
    for row in plan["records"]:
        item = dict(row)
        key = identifier(item["id"])
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", key) and
                key.upper() not in {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
                                    *{f"LPT{i}" for i in range(1, 10)}}, "image ID must be a portable filename")
        require(key.casefold() not in ids, "duplicate image ID (case-insensitive)")
        ids.add(key.casefold())
        require(item["source_id"] in sources and item["split"] in SPLITS, "unknown source or split")
        group = identifier(item["group_id"])
        require(group not in groups or groups[group] == item["split"], "original group leaks across splits")
        groups[group] = item["split"]
        require(isinstance(item.get("reviewer"), str) and item["reviewer"].strip(), "label reviewer required")
        require(item.get("review_method") in {"human", "publisher_annotations", "assistant", "synthetic_fixture"},
                "explicit label review_method required")
        require((item["review_method"] == "synthetic_fixture") == (plan["dataset_kind"] == "synthetic_test"),
                "review method differs from dataset kind")
        require(item.get("species_confirmed") is True, "detection target/negative-image review required")
        image = relative(root, item["image"])
        label = relative(root, item["label"])
        require(item["image"] not in seen_paths, "duplicate image path")
        seen_paths.add(item["image"])
        boxes = read_boxes(label)
        info = image_info(image)
        image_hash = digest(image)
        if not inspection_only and not boxes and item['review_method'] == 'publisher_annotations':
            # A publisher may label only lamps/insects in an image that also contains a lizard.
            review = item.get('target_absence_review')
            require(isinstance(review, dict) and review.get('verdict') == 'no_visible_target'
                    and review.get('review_method') in {'human', 'assistant'}
                    and review.get('image_sha256') == image_hash
                    and all(isinstance(review.get(field), str) and review[field].strip()
                            for field in ('reviewer', 'note')),
                    f"target absence needs a visual review of this exact image: {key}; empty publisher labels are insufficient")
        require(info["pixel_sha256"] not in seen_pixels, "duplicate decoded image; remove duplicate or re-encoded copy")
        seen_pixels[info["pixel_sha256"]] = key
        item.update(info, image_sha256=image_hash, label_sha256=digest(label), box_count=len(boxes))
        records.append(item)
        positives[item["split"]] += len(boxes)
    for split in SPLITS:
        require(positives[split] > 0, f"{split} needs reviewed positive images; these are computational minima, not sufficient sample sizes")
    return records


def prepare_dataset(root, plan_path, output):
    root = Path(root).resolve()
    plan = read_json(Path(plan_path), 64 * 1024**2)
    records = validate_plan(plan, root)
    with output_directory(output, "prepare_dataset") as destination:
        for split in SPLITS:
            (destination / "images" / split).mkdir(parents=True)
            (destination / "labels" / split).mkdir(parents=True)
        prepared = []
        for row in records:
            image = relative(root, row["image"])
            image_name = f"images/{row['split']}/{row['id']}{image.suffix.lower()}"
            label_name = f"labels/{row['split']}/{row['id']}.txt"
            shutil.copyfile(image, destination / image_name)
            shutil.copyfile(relative(root, row["label"]), destination / label_name)
            require(digest(destination / image_name) == row["image_sha256"] and
                    digest(destination / label_name) == row["label_sha256"], "input changed while preparing dataset")
            prepared.append({**row, "original_image": row["image"], "original_label": row["label"],
                             "image": image_name, "label": label_name})
        manifest = {k: plan[k] for k in ("schema_version", "species", "dataset_kind", "split_policy", "sources")}
        manifest.update(records=prepared, class_names=[plan["species"]])
        if "grouping_limit" in plan:
            manifest["grouping_limit"] = plan["grouping_limit"]
        manifest["dataset_id"] = fingerprint(manifest)
        save_artifact(destination / "dataset.json", manifest)
    return dataset_summary(manifest)


def load_dataset(root, *, inspection_only=False):
    """Check inventory integrity; inspection_only permits viewing archived incomplete labels.

    Training, evaluation and dataset preparation use the strict default. Inspection
    never establishes that an unlabeled target is absent.
    """
    root = Path(root).resolve()
    require(read_json(root / "status.json")["state"] == "complete", "dataset preparation did not complete")
    manifest = read_json(root / "dataset.json", 64 * 1024**2)
    require(manifest["dataset_id"] == fingerprint({k: v for k, v in manifest.items() if k != "dataset_id"}), "dataset manifest integrity failure")
    require(manifest.get("class_names") == [manifest.get("species")], "model class mismatch")
    checked = validate_plan(manifest, root, inspection_only=inspection_only)
    for original, current in zip(manifest["records"], checked):
        for key in ("image_sha256", "label_sha256", "pixel_sha256", "width", "height", "box_count"):
            require(original[key] == current[key], f"dataset file integrity failure: {original['id']} {key}")
    # The learner scans directories; reject extra files not included in the reviewed inventory.
    for kind, key in (("images", "image"), ("labels", "label")):
        actual = {p.relative_to(root).as_posix() for p in (root / kind).rglob("*") if p.is_file() or p.is_symlink()}
        expected = {row[key] for row in manifest["records"]}
        require(actual == expected, f"unlisted or missing {kind} files")
    return manifest


def dataset_summary(manifest):
    return {"dataset_id": manifest["dataset_id"], "species": manifest["species"],
            "dataset_kind": manifest["dataset_kind"], "splits": {
                split: {"images": sum(r["split"] == split for r in manifest["records"]),
                        "negative_images": sum(r["split"] == split and r["box_count"] == 0 for r in manifest["records"]),
                        "groups": len({r["group_id"] for r in manifest["records"] if r["split"] == split}),
                        "boxes": sum(r["box_count"] for r in manifest["records"] if r["split"] == split)} for split in SPLITS},
            "label_review_methods": dict(Counter(r["review_method"] for r in manifest["records"])),
            "all_labels_human_reviewed": all(r["review_method"] == "human" for r in manifest["records"]),
            "animal_generalization_verified": False,
            "split_policy": manifest["split_policy"],
            "grouping_limit": manifest.get("grouping_limit", "Operator-declared original groups; near-duplicate crops and unknown individual identities require review.")}


def write_training_yaml(root, destination, class_names=None):
    import yaml
    content = {"path": str(Path(root).resolve()), "names": class_names or [SPECIES],
               **{split: f"images/{split}" for split in SPLITS}}
    destination.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return destination
