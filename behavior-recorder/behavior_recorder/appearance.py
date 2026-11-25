"""Offline, reviewed color observations and human shedding events; no device control."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

from .analysis_features import fingerprint, save_artifact
from .core import RecorderError, identifier, now, read_json, relative, require, timestamp


def validate_metadata(row):
    require(isinstance(row, dict), "observation must be an object")
    common = {"schema_version", "kind", "dataset_kind", "record_id", "animal_id", "species", "enclosure_id"}
    require(common <= row.keys(), "missing observation identity")
    require(type(row["schema_version"]) is int and row["schema_version"] == 1, "unsupported schema")
    require(row["dataset_kind"] in {"test", "real"}, "dataset_kind must be test or real")
    require(row["species"] in {"crested_gecko", "leopard_gecko"}, "explicit supported species required")
    for key in ("record_id", "animal_id", "enclosure_id"):
        identifier(row[key])
    if row["kind"] == "shedding_event":
        require(set(row) == common | {"stage", "earliest_at", "latest_at", "observer", "evidence_reference"},
                "invalid shedding event fields")
        require(row["stage"] in {"started", "completed", "uncertain"}, "invalid shedding stage")
        earliest, latest = timestamp(row["earliest_at"]), timestamp(row["latest_at"])
        require(earliest is not None and latest is not None and earliest <= latest, "ordered observation interval required")
        identifier(row["observer"])
        require(isinstance(row["evidence_reference"], str) and 0 < len(row["evidence_reference"].strip()) <= 1024,
                "human observation evidence reference required")
        return []
    require(row["kind"] == "color_observation", "unknown observation kind")
    require(set(row) == common | {"observed_at", "image", "mask", "body_region", "capture", "review"},
            "invalid color observation fields")
    require(timestamp(row["observed_at"]) is not None, "capture timestamp required")
    identifier(row["body_region"])
    capture, review = row["capture"], row["review"]
    require(isinstance(capture, dict) and set(capture) == {
        "camera_id", "camera_revision", "mode", "color_space", "illumination_revision", "settings_revision",
        "reference_revision", "exposure_locked", "white_balance_locked"}, "invalid capture fields")
    identifier(capture["camera_id"])
    require(capture["mode"] in {"visible_rgb", "infrared", "unknown"}, "invalid capture mode")
    require(capture["color_space"] in {"sRGB", "unknown"}, "unsupported color space")
    reasons = []
    if capture["mode"] != "visible_rgb":
        reasons.append("visible_rgb_required")
    if capture["color_space"] != "sRGB":
        reasons.append("color_space_unknown")
    for key in ("camera_revision", "illumination_revision", "settings_revision", "reference_revision"):
        if capture[key] is None:
            reasons.append(key + "_unknown")
        else:
            identifier(capture[key])
    for key in ("exposure_locked", "white_balance_locked"):
        require(type(capture[key]) is bool, key + " must be boolean")
        if not capture[key]:
            reasons.append(key + "_not_confirmed")
    require(isinstance(review, dict) and set(review) == {
        "observer", "identity_confirmed", "skin_only", "dry", "sharp"}, "invalid review fields")
    identifier(review["observer"])
    for key in ("identity_confirmed", "skin_only", "dry", "sharp"):
        require(type(review[key]) is bool, key + " must be boolean")
        if not review[key]:
            reasons.append(key + "_not_confirmed")
    return reasons


def local_bytes(root, name):
    path = relative(root, name)
    limit = 16 * 1024**2
    require(path.is_file() and path.stat().st_size <= limit, "image/mask must be a local file up to 16 MiB")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    require(len(content) <= limit, "image/mask exceeds 16 MiB")
    return content, {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def color_features(image_bytes, mask_bytes):
    import numpy as np
    from PIL import Image
    with Image.open(BytesIO(image_bytes)) as image, Image.open(BytesIO(mask_bytes)) as mask:
        for item in (image, mask):
            require(getattr(item, "n_frames", 1) == 1, "single-frame image required")
            require(item.width * item.height <= 4 * 1024**2, "image exceeds 4 megapixels")
            require(item.getexif().get(274, 1) == 1, "image/mask orientation must already match; no implicit rotation")
        require(image.format in {"PNG", "JPEG"} and image.mode == "RGB", "RGB PNG/JPEG required")
        require(not image.info.get("icc_profile"), "embedded color profile requires a separately reviewed sRGB conversion")
        require(mask.format == "PNG" and mask.mode == "L" and mask.size == image.size,
                "mask must be same-size 8-bit grayscale PNG")
        selection = np.asarray(mask)
        require(bool(np.all((selection == 0) | (selection == 255))), "mask must contain only 0 and 255")
        selection = selection == 255
        pixels = np.asarray(image)[selection].astype(np.float32)
        require(len(pixels) >= 64, "at least 64 reviewed skin pixels required")
        lower, median, upper = np.percentile(pixels, [25, 50, 75], axis=0)
        maximum = pixels.max(axis=1)
        saturation = np.divide(maximum - pixels.min(axis=1), maximum,
                               out=np.zeros_like(maximum), where=maximum > 0)
        return {"selected_pixels": len(pixels), "image_fraction": float(selection.mean()),
                "rgb_median": median.tolist(), "rgb_iqr": (upper - lower).tolist(),
                "saturation_median": float(np.median(saturation)),
                "value_median": float(np.median(maximum) / 255),
                "clipped_pixel_fraction": float(((pixels == 0) | (pixels == 255)).any(axis=1).mean())}


def collect(input_path, output_path):
    input_path, output_path = Path(input_path), Path(output_path)
    require(not output_path.exists(), "output already exists; choose a new versioned filename")
    row = read_json(input_path)
    reasons = validate_metadata(row)
    result = {"schema_version": 1, "feature_version": "reviewed-srgb-v1", "created_at": now(),
              "metadata": row, "metadata_sha256": fingerprint(row), "features": None,
              "comparison_group": None, "files": {}, "reasons": reasons,
              "shedding_prediction": None, "actuation_allowed": False,
              "evidence": "operator-declared identity, capture conditions and human observations; not independently verified"}
    if row["kind"] == "color_observation":
        image_bytes, result["files"]["image"] = local_bytes(input_path.parent, row["image"])
        mask_bytes, result["files"]["mask"] = local_bytes(input_path.parent, row["mask"])
        result["status"] = "excluded" if reasons else "measured"
        if not reasons:
            result["features"] = color_features(image_bytes, mask_bytes)
            result["comparison_group"] = fingerprint({key: row[key] for key in (
                "dataset_kind", "animal_id", "species", "enclosure_id", "body_region", "capture")})
    else:
        result["status"] = "human_event_recorded"
    save_artifact(output_path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect local color observations or human shedding events; no predictions or control")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = collect(args.input, args.output)
        print(json.dumps({"output": str(args.output.resolve()), "status": result["status"],
                          "reasons": result["reasons"], "actuation_allowed": False}, ensure_ascii=False))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
