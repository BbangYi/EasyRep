"""Read-only reconstruction measurements, kept outside immutable source artifacts.

Runs in the installed GPU environment, not the lightweight API interpreter.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from habitat.persistence.gpu import sync_directory
from habitat.gpu.backend import DiagnosticIntegrityError


def file_hash(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def atomic_json(path: Path, value) -> None:
    content = json.dumps(value, indent=2, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("wb") as output:
        if os.name == "posix":
            os.fchmod(output.fileno(), 0o600)
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def tree_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in frozen experiment inputs")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = file_hash(path)
    return result


def stored_records(job: Path) -> tuple[dict, dict]:
    database = job.parent.parent / "compute.sqlite3"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
        row = db.execute("SELECT payload FROM jobs WHERE id=?", (job.name,)).fetchone()
        if row is None:
            raise ValueError("Unknown source job")
        payload = json.loads(row[0])
        capture = db.execute("SELECT payload FROM captures WHERE id=?", (payload["capture_id"],)).fetchone()
    return payload, json.loads(capture[0])


def freeze_source(job: Path, output: Path) -> dict:
    """One immutable manifest for both the full original and reusable processed data."""
    job, output = job.resolve(), output.resolve()
    if output.is_relative_to(job.parent) or output.exists():
        raise ValueError("Snapshot must be new and outside the original job")
    payload, capture = stored_records(job)
    if payload["status"] != "succeeded":
        raise ValueError("Only completed jobs can be frozen")
    configs = list((job / "trained").rglob("config.yml"))
    if len(configs) != 1:
        raise ValueError("Expected exactly one training configuration")
    manifest = {"schema_version": 1, "source_job_id": job.name,
                "capture_id": payload["capture_id"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "processed_files": tree_hashes(job / "processed"),
                "training_config_sha256": file_hash(configs[0]),
                "original_files": tree_hashes(job),
                "original_job_payload": payload, "capture_manifest": capture}
    atomic_json(output, manifest)
    return manifest


def verify_frozen(job: Path, manifest: dict) -> None:
    if job.name != manifest["source_job_id"] or tree_hashes(job) != manifest["original_files"]:
        raise ValueError("Original job files changed after freezing")
    payload, capture = stored_records(job)
    if payload != manifest["original_job_payload"] or capture != manifest["capture_manifest"]:
        raise ValueError("Original job/capture record changed after freezing")


def input_measurements(job: Path, capture: dict, rois: list[dict]) -> dict:
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    uploaded = job.parent.parent / "captures" / capture["capture_id"]
    files = sorted(capture["files"], key=lambda f: f["file_id"] + Path(f["name"]).suffix.lower())
    views = []
    for index, item in enumerate(files):
        raw = uploaded / (item["file_id"] + Path(item["name"]).suffix.lower())
        # ns-process-data renames prepared 0-indexed frames to 1-indexed frames.
        processed = job / "processed" / "images" / f"frame_{index + 1:05d}.png"
        if raw.stat().st_size != item["size_bytes"] or file_hash(raw) != item["sha256"]:
            raise DiagnosticIntegrityError("Capture content no longer matches its manifest")
        with Image.open(raw) as original:
            raw_size = list(original.size)
            expected = ImageOps.exif_transpose(original).convert("RGB")
        if not processed.is_file():
            raise DiagnosticIntegrityError("Processed frame mapping is incomplete")
        with Image.open(processed) as actual:
            expected.thumbnail(actual.size, Image.Resampling.LANCZOS)
            if expected.size != actual.size or expected.tobytes() != actual.convert("RGB").tobytes():
                raise DiagnosticIntegrityError("Processed pixels do not match the recorded UUID-to-frame mapping")
        gray = cv2.imread(str(processed), cv2.IMREAD_GRAYSCALE)
        measurements = []
        for roi in rois:
            if roi["image_name"] != processed.name:
                continue
            x0, y0, x1, y1 = map(int, roi["xyxy"])
            crop = gray[y0:y1, x0:x1]
            if crop.size == 0 or x0 < 0 or y0 < 0 or x1 > gray.shape[1] or y1 > gray.shape[0]:
                raise ValueError("ROI outside processed image")
            measurements.append({"id": roi["id"], "category": roi["category"],
                                 "pixel_count": int(crop.size),
                                 "laplacian_variance": float(cv2.Laplacian(crop, cv2.CV_64F).var()),
                                 "gray_std": float(crop.std()),
                                 "dark_fraction_le_3": float(np.mean(crop <= 3)),
                                 "bright_fraction_ge_252": float(np.mean(crop >= 252))})
        views.append({"file_id": item["file_id"], "capture_name": item["name"],
                      "uploaded_sha256": item["sha256"], "uploaded_size": raw_size,
                      "prepared_name": f"frame_{index:05d}.png", "pixel_mapping_verified": True,
                      "processed_name": processed.name, "processed_size": list(gray.shape[::-1]),
                      "processed_sha256": file_hash(processed),
                      "laplacian_variance": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                      "roi": measurements})
    return {"status": "ok", "n_images": len(views), "views": views,
            "limitations": ["Laplacian variance mixes texture and blur; not a blur diagnosis",
                             "Frame numbering follows uploaded UUID ordering, not capture chronology",
                             "Source capture timing and exposure consistency are unverified",
                             "ROI image counts cover annotated validation views, not all visible surfaces"]}


def public_summary(report: dict) -> dict:
    """Bounded allowlist; detailed paths, file lists and raw measurements stay local."""
    import math
    from uuid import UUID

    statuses = {"ok", "partial", "unavailable", "error", "not_run"}

    def mapping(value):
        return value if isinstance(value, dict) else {}

    def number(value):
        try:
            return value if type(value) in (int, float) and math.isfinite(value) else None
        except OverflowError:
            return None

    def count(value):
        return value if type(value) is int and 0 <= value <= 2**63 - 1 else None

    def sha256(value):
        return value if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value) else None

    def uuid(value):
        try:
            return str(UUID(value)) if isinstance(value, str) else None
        except ValueError:
            return None

    def fields(value, numbers=(), counts=(), enums=None):
        value = mapping(value)
        result = {key: number(value[key]) for key in numbers if key in value}
        result.update({key: count(value[key]) for key in counts if key in value})
        for key, allowed in (enums or {}).items():
            if isinstance(value.get(key), str) and value[key] in allowed:
                result[key] = value[key]
        return result

    def distribution(value):
        result = fields(value, ("mean", "min", "p10", "p50", "p90", "p95", "p99", "max", "rmse"),
                        ("n", "finite_n", "nonfinite_n", "nonfinite_count"), {
                            "status": statuses, "percentile_method": {"linear"}, "unit": {"px", "deg"},
                            "source": {"points3D.ERROR", "recomputed_current_model_parameters"},
                            "aggregation": {"unweighted_per_point_mean_errors", "per_observation_euclidean_norm"},
                            "coordinate_space": {"raw_distorted_colmap_image_pixels"}})
        value = mapping(value)
        if type(value.get("ba_log_present")) is bool:
            result["ba_log_present"] = value["ba_log_present"]
        if "excluded_by_reason" in value:
            result["excluded_by_reason"] = fields(value["excluded_by_reason"], counts=(
                "nonfinite_or_invalid_pose", "nonpositive_depth", "unsupported_camera_model",
                "nonfinite_projection", "invalid_camera_parameters"))
        return result

    def aggregate(value):
        value = mapping(value)
        result = fields(value, ("psnr", "ssim", "lpips", "psnr_std", "ssim_std", "lpips_std"), ("view_count",))
        if "valid_metric_counts" in value:
            result["valid_metric_counts"] = fields(value["valid_metric_counts"], counts=("psnr", "ssim", "lpips"))
        return result

    def vector(value):
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        result = [number(x) for x in value]
        return result if all(x is not None for x in result) else None

    def bounds(value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        result = [vector(x) for x in value]
        return result if all(x is not None for x in result) else None

    def gaussians(value):
        value = mapping(value)
        result = fields(value, counts=("count", "nonfinite_scalar_count", "max_scale_above_0_5_count",
            "opacity_above_0_1_count", "large_and_opacity_above_0_1_count", "large_and_opacity_at_most_0_1_count"),
            enums={"coordinates": {"Nerfstudio normalized COLMAP coordinates, not metric"}})
        for key in ("max_axis_scale", "axis_ratio", "opacity"):
            if key in value:
                result[key] = distribution(value[key])
        if "nonfinite_parameter_counts" in value:
            result["nonfinite_parameter_counts"] = fields(value["nonfinite_parameter_counts"], counts=(
                "means", "scales", "quats", "features_dc", "features_rest", "opacities"))
        for key, counts, vectors in (("initial_sparse", ("count",), ("min", "max", "p01", "p99")),
                ("centers", ("nonfinite_count", "outside_initial_aabb_count", "outside_initial_p01_p99_count"), ("min", "max"))):
            if key in value:
                item = mapping(value[key])
                result[key] = fields(item, counts=counts)
                result[key].update({name: vector(item[name]) for name in vectors if name in item})
        if "scene_bounds" in value:
            item = mapping(value["scene_bounds"])
            result["scene_bounds"] = fields(item, ("extent", "robust_extent_diagonal"), enums={
                "coordinate_system": {"nerfstudio_normalized"}, "extent_definition": {"initial_sparse_aabb_diagonal"},
                "robust_extent_definition": {"initial_sparse_axiswise_p01_p99_aabb_diagonal"}})
            if item.get("metric_scale_verified") is False:
                result["scene_bounds"]["metric_scale_verified"] = False
            result["scene_bounds"].update({name: bounds(item[name]) for name in ("aabb", "robust_aabb") if name in item})
        return result

    colmap = mapping(report.get("colmap"))
    evaluation = mapping(report.get("splatfacto"))
    colmap_summary = fields(colmap, ("registration_fraction",), ("input_images", "registered_images", "sparse_points",
        "observations", "keypoints", "two_view_points", "three_view_points"), {"status": statuses})
    for key in ("track_length", "stored_point_error_px", "observation_reprojection_error_px", "max_triangulation_angle_deg"):
        if key in colmap:
            colmap_summary[key] = distribution(colmap[key])
    summary = {"schema_version": 1, "status": fields(report, enums={"status": statuses}).get("status", "partial"),
               "quality_status": "review_required", "causal_attribution": "unresolved",
               "source_job_id": uuid(report.get("source_job_id")),
               "report_sha256": sha256(report.get("report_sha256")),
               "roi_sha256": sha256(mapping(report.get("provenance")).get("roi_sha256")),
               "colmap": colmap_summary,
               "evaluation": {"status": fields(evaluation, enums={"status": statuses}).get("status", "not_run"),
                              "protocol": "installed-nerfstudio-undistorted-no-color-correction",
                              "split_role": "sfm_conditioned_validation"},
               "details": "protected_local_diagnostics_json"}
    checkpoints = []
    for row in evaluation.get("checkpoints", []) if isinstance(evaluation.get("checkpoints", []), list) else []:
        row = mapping(row)
        item = fields(row, counts=("actual_step",))
        if "checkpoint_sha256" in row:
            item["checkpoint_sha256"] = sha256(row["checkpoint_sha256"])
        for key in ("aggregate", "train_aggregate"):
            if key in row:
                item[key] = aggregate(row[key])
        if "roi_aggregate" in row:
            item["roi_aggregate"] = {category: aggregate(value) for category, value in mapping(row["roi_aggregate"]).items()
                                     if category in {"floor", "reflection_window", "sky", "matte_control"}}
        if "gaussians" in row:
            item["gaussians"] = gaussians(row["gaussians"])
        checkpoints.append(item)
    summary["evaluation"]["checkpoints"] = checkpoints
    # Summaries have an explicit ceiling even when a collector grows new fields.
    if len(json.dumps(summary, allow_nan=False).encode()) > 64 * 1024:
        raise ValueError("Diagnostic summary exceeds 64 KiB")
    return summary


def collect(job: Path, output: Path, rois_path: Path | None = None,
            steps: list[int] | None = None, evaluate: bool = True) -> dict:
    from habitat.gpu.colmap_diagnostics import collect_colmap

    job, output = job.resolve(), output.resolve()
    if output == job or (job / "processed").is_relative_to(output):
        raise ValueError("Diagnostics output must not contain original inputs")
    if output.is_relative_to(job / "processed") or output.is_relative_to(job / "trained"):
        raise ValueError("Diagnostics output overlaps immutable inputs")
    if (output / "diagnostics.json").exists():
        raise ValueError("Use a new output directory; diagnostics are not overwritten")
    payload, capture = stored_records(job)
    if output.is_relative_to(job.parent) and (payload["status"] != "running" or output != job / "diagnostics"):
        raise ValueError("Completed jobs require separate external diagnostic output")
    rois = json.loads(rois_path.read_text(encoding="utf-8"))["rois"] if rois_path else []
    reconstruction = json.loads((job / "reconstruction.json").read_text()) if (job / "reconstruction.json").exists() else {}
    from habitat.gpu.backend import select_colmap_model
    model, counts = select_colmap_model(job / "processed" / "colmap" / "sparse")
    if "selected_colmap_model" in reconstruction:
        model = model.parent / reconstruction["selected_colmap_model"]
    configs = list((job / "trained").rglob("config.yml"))
    report = {"schema_version": 1, "source_job_id": job.name, "status": "partial",
              "quality_status": "review_required", "causal_attribution": "unresolved",
              "provenance": {"processed_files": tree_hashes(job / "processed"),
                             "roi_sha256": file_hash(rois_path) if rois_path else None,
                             "capture_manifest_sha256": hashlib.sha256(json.dumps(capture, sort_keys=True).encode()).hexdigest(),
                             "collector_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in
                                 ("diagnostics.py", "colmap_diagnostics.py", "splat_diagnostics.py")},
                             "training_config_sha256": file_hash(configs[0]) if len(configs) == 1 else None},
              "rois": rois, "colmap_model_image_counts": counts,
              "selected_colmap_model": model.name}
    report["input"] = input_measurements(job, capture, rois)
    atomic_json(output / "diagnostics.json", report)
    report["colmap"] = collect_colmap(job / "processed", model, output / "colmap", rois)
    if (job / "colmap-pre-ba").is_dir():
        report["colmap_pre_ba"] = collect_colmap(job / "processed", job / "colmap-pre-ba", output / "colmap-pre-ba", rois)
    atomic_json(output / "diagnostics.json", report)
    if evaluate and len(configs) == 1:
        from habitat.gpu.splat_diagnostics import collect_splat
        report["splatfacto"] = collect_splat(configs[0], output / "evaluation", rois, steps)
    else:
        report["splatfacto"] = {"status": "not_run", "reason": "evaluation_disabled_or_config_missing"}
    if tree_hashes(job / "processed") != report["provenance"]["processed_files"]:
        raise DiagnosticIntegrityError("Processed inputs changed during diagnostics")
    report["status"] = "ok" if all(report[key].get("status") == "ok" for key in ("colmap", "splatfacto")) else "partial"
    atomic_json(output / "diagnostics.json", report)
    report["report_sha256"] = file_hash(output / "diagnostics.json")
    summary = public_summary(report)
    atomic_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rois", type=Path)
    parser.add_argument("--steps", type=int, nargs="+")
    parser.add_argument("--no-evaluation", action="store_true")
    parser.add_argument("--freeze-source", action="store_true")
    parser.add_argument("--verify-frozen", type=Path)
    args = parser.parse_args()
    if args.verify_frozen:
        verify_frozen(args.job_dir, json.loads(args.verify_frozen.read_text()))
        print(json.dumps({"source_job_id": args.job_dir.name, "integrity": "unchanged"}))
    elif args.freeze_source:
        value = freeze_source(args.job_dir, args.output)
        print(json.dumps({"source_job_id": value["source_job_id"], "frozen_files": len(value["original_files"])}))
    else:
        print(json.dumps(collect(args.job_dir, args.output, args.rois, args.steps, not args.no_evaluation), allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except DiagnosticIntegrityError:
        print("diagnostics_input_integrity_error", flush=True)
        raise SystemExit(65)
    except (OSError, sqlite3.Error):
        print("diagnostics_storage_error", flush=True)
        raise SystemExit(73)
