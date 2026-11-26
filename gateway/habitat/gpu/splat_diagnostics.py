"""Opt-in diagnostics for trusted local Splatfacto checkpoints, not an API route.

Run in the existing GPU environment. Evaluation uses Nerfstudio's undistorted
cached_eval images/cameras; it never trains, resumes, prunes, or rewrites inputs.
ROI xyxy coordinates are integer, half-open rectangles in the original distorted
processed image (downscale_factor=1). PNGs are unresized 8-bit RGB; metrics use
the float tensors before PNG quantization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _distribution(values) -> dict:
    import numpy as np

    values = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = values[np.isfinite(values)]
    result = {"nonfinite_count": int(len(values) - len(finite))}
    result.update(dict(zip(("p50", "p95", "p99", "max"),
                           np.percentile(finite, [50, 95, 99, 100]).tolist() if finite.size else [None] * 4)))
    return result


def summarize_gaussians(means, log_scales, opacity_logits, initial_sparse_points) -> dict:
    """CPU-only statistics in the same normalized coordinates as the checkpoint."""
    import numpy as np

    means, logs, sparse = (np.asarray(value, dtype=np.float64)
                           for value in (means, log_scales, initial_sparse_points))
    logits = np.asarray(opacity_logits, dtype=np.float64).reshape(-1)
    if (means.ndim != 2 or means.shape[1] != 3 or means.shape != logs.shape
            or len(logits) != len(means) or not len(means)
            or sparse.ndim != 2 or sparse.shape[1] != 3 or not len(sparse)):
        raise ValueError("Expected nonempty Nx3 Gaussian means/scales and Mx3 initial sparse points")
    if not np.isfinite(sparse).all():
        raise ValueError("Initial sparse points contain nonfinite coordinates")
    with np.errstate(over="ignore", invalid="ignore"):
        max_scale = np.exp(logs.max(axis=1))
        axis_ratio = np.exp(logs.max(axis=1) - logs.min(axis=1))
    # Stable sigmoid without clipping malformed values into apparently valid ones.
    opacity = np.exp(-np.logaddexp(0, -logits))
    low, high = sparse.min(axis=0), sparse.max(axis=0)
    qlow, qhigh = np.percentile(sparse, [1, 99], axis=0)
    finite_centers = np.isfinite(means).all(axis=1)
    centers = means[finite_centers]
    large, opaque = max_scale > 0.5, opacity > 0.1
    return {
        "count": len(means), "coordinates": "Nerfstudio normalized COLMAP coordinates, not metric",
        "nonfinite_scalar_count": int(sum((~np.isfinite(a)).sum() for a in (means, logs, logits))),
        "initial_sparse": {"count": len(sparse), "min": low.tolist(), "max": high.tolist(),
                           "p01": qlow.tolist(), "p99": qhigh.tolist()},
        "scene_bounds": {"coordinate_system": "nerfstudio_normalized", "metric_scale_verified": False,
                         "aabb": [low.tolist(), high.tolist()], "extent": float(np.linalg.norm(high - low)),
                         "extent_definition": "initial_sparse_aabb_diagonal",
                         "robust_aabb": [qlow.tolist(), qhigh.tolist()],
                         "robust_extent_diagonal": float(np.linalg.norm(qhigh - qlow)),
                         "robust_extent_definition": "initial_sparse_axiswise_p01_p99_aabb_diagonal"},
        "centers": {"nonfinite_count": int((~finite_centers).sum()),
                    "min": centers.min(axis=0).tolist() if len(centers) else None,
                    "max": centers.max(axis=0).tolist() if len(centers) else None,
                    "outside_initial_aabb_count": int(((centers < low) | (centers > high)).any(axis=1).sum()),
                    "outside_initial_p01_p99_count": int(((centers < qlow) | (centers > qhigh)).any(axis=1).sum())},
        "max_axis_scale": _distribution(max_scale), "axis_ratio": _distribution(axis_ratio),
        "opacity": _distribution(opacity),
        "max_scale_above_0_5_count": int(large.sum()),
        "opacity_above_0_1_count": int(opaque.sum()),
        "large_and_opacity_above_0_1_count": int((large & opaque).sum()),
        "large_and_opacity_at_most_0_1_count": int((large & ~opaque).sum()),
    }


def _interior_rectangle(mask) -> list[int] | None:
    """Largest all-valid axis-aligned rectangle, deterministic ties, half-open."""
    import numpy as np

    mask = np.asarray(mask, dtype=bool)
    heights = np.zeros(mask.shape[1] + 1, dtype=np.int64)
    best, rectangle = 0, None
    # ponytail: O(HW) CPU scan per ROI; mappings are reused across checkpoints.
    for y, row in enumerate(mask):
        heights[:-1] = np.where(row, heights[:-1] + 1, 0)
        stack = []
        for x, height in enumerate(heights):
            start = x
            while stack and stack[-1][1] > height:
                left, previous = stack.pop()
                area = previous * (x - left)
                if area > best:
                    best, rectangle = area, [left, y - previous + 1, x, y + 1]
                start = left
            if height and (not stack or stack[-1][1] < height):
                stack.append((start, int(height)))
    return rectangle


def map_roi(xyxy, raw_k, distortion, eval_k, raw_size, eval_size, valid_mask=None) -> dict:
    """Map raw pixel-index ROI to a fully valid eval crop with OpenCV remapping.

    K uses Nerfstudio pixel-center convention; subtract 0.5 as its own loader does.
    Distortion is the Nerfstudio order [k1,k2,k3,k4,p1,p2]; only perspective k4=0
    is supported, matching FullImageDatamanager's perspective undistorter.
    """
    import cv2
    import numpy as np

    if (len(xyxy) != 4 or any(isinstance(x, bool) or not isinstance(x, int) for x in xyxy)
            or not 0 <= xyxy[0] < xyxy[2] <= raw_size[0]
            or not 0 <= xyxy[1] < xyxy[3] <= raw_size[1]):
        raise ValueError("ROI xyxy must be integer half-open coordinates within the raw image")
    k, target_k = np.array(raw_k, dtype=float, copy=True), np.array(eval_k, dtype=float, copy=True)
    distortion = np.asarray(distortion, dtype=float).reshape(-1)
    if k.shape != (3, 3) or target_k.shape != (3, 3) or distortion.shape != (6,):
        raise ValueError("Expected 3x3 intrinsics and six Nerfstudio distortion parameters")
    if not all(np.isfinite(x).all() for x in (k, target_k, distortion)) or distortion[3] != 0:
        raise ValueError("Invalid intrinsics or unsupported perspective k4 distortion")
    k[:2, 2] -= 0.5
    target_k[:2, 2] -= 0.5
    coefficients = distortion[[0, 1, 4, 5, 2, 3]].tolist() + [0, 0]
    map_x, map_y = cv2.initUndistortRectifyMap(k, np.array(coefficients), None, target_k,
                                             tuple(eval_size), cv2.CV_32FC1)
    # Require every bilinear source sample to stay inside the requested raw ROI.
    valid = ((map_x >= xyxy[0]) & (map_x <= xyxy[2] - 1)
             & (map_y >= xyxy[1]) & (map_y <= xyxy[3] - 1))
    if valid_mask is not None:
        provided = np.asarray(valid_mask, dtype=bool).squeeze()
        if provided.shape != valid.shape:
            raise ValueError("Eval validity mask dimensions do not match the camera")
        valid &= provided
    rectangle = _interior_rectangle(valid)
    return {"raw_xyxy": list(xyxy), "eval_xyxy": rectangle,
            "raw_size_wh": list(raw_size), "eval_size_wh": list(eval_size),
            "raw_k_pixel_center": np.asarray(raw_k).tolist(),
            "eval_k_pixel_center": np.asarray(eval_k).tolist(),
            "distortion_nerfstudio": distortion.tolist(),
            "mapped_valid_pixels": int(valid.sum()),
            "crop_pixels": (rectangle[2] - rectangle[0]) * (rectangle[3] - rectangle[1]) if rectangle else 0,
            "method": "OpenCV inverse map; bilinear support inside raw ROI; largest fully-valid rectangle"}


def _aggregate(rows: list[dict]) -> dict:
    result = {"view_count": len(rows), "valid_metric_counts": {}}
    for key in ("psnr", "ssim", "lpips"):
        values = [row[key] for row in rows if row.get(key) is not None and math.isfinite(row[key])]
        result["valid_metric_counts"][key] = len(values)
        if values:
            mean = sum(values) / len(values)
            result[key] = mean
            result[key + "_std"] = (math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))
                                   if len(values) > 1 else None)
        else:
            result[key] = result[key + "_std"] = None
    return result


def _metrics(model, gt, pred) -> tuple[dict, dict]:
    """Use the installed official modules without upsampling small ROI crops."""
    scores, status = {}, {}
    size = min(gt.shape[0], gt.shape[1])
    for key, minimum in (("psnr", 1), ("ssim", 11), ("lpips", 64)):
        scores[key] = None
        if size < minimum:
            status[key] = "unsupported_small_crop"
            continue
        value = float(getattr(model, key)(gt.permute(2, 0, 1)[None], pred.permute(2, 0, 1)[None]).item())
        status[key] = "measured" if math.isfinite(value) else "nonfinite"
        scores[key] = value if math.isfinite(value) else None
    return scores, status


def _save_images(gt, pred, directory: Path, output_dir: Path) -> dict:
    import numpy as np
    from PIL import Image

    directory.mkdir()
    target, prediction = ((value.detach().cpu().clamp(0, 1).numpy() * 255 + 0.5).astype(np.uint8)
                          for value in (gt, pred))
    result = {}
    for name, array in (("gt", target), ("pred", prediction), ("comparison", np.concatenate([target, prediction], axis=1))):
        path = directory / f"{name}.png"
        Image.fromarray(array).save(path)
        result[name] = str(path.relative_to(output_dir))
    return result


def _snapshot(report: dict, output_dir: Path) -> None:
    from habitat.gpu.diagnostics import atomic_json

    atomic_json(output_dir / "diagnostics.json", report)


def collect_splat(config: Path, output_dir: Path, rois: list[dict] | None = None,
                  steps: list[int] | None = None) -> dict:
    """Write new diagnostics only; requires explicit access to a trusted GPU config."""
    import numpy as np
    import torch
    from nerfstudio.cameras.cameras import CameraType
    from nerfstudio.data.datamanagers.full_images_datamanager import FullImageDatamanager
    from nerfstudio.utils.eval_utils import eval_setup
    from habitat.gpu.diagnostics import DiagnosticIntegrityError

    config, output_dir = Path(config).resolve(strict=True), Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError("Diagnostic output must be a new directory")
    if steps is not None and (not steps or len(set(steps)) != len(steps)
                              or any(isinstance(s, bool) or not isinstance(s, int) or s < 0 for s in steps)):
        raise ValueError("Steps must be a nonempty list of distinct nonnegative checkpoint indices")
    rois = rois or []
    if not isinstance(rois, list):
        raise ValueError("ROIs must be a list")
    if any(not isinstance(r, dict) or not all(isinstance(r.get(k), str) and r[k]
           for k in ("id", "category", "image_name")) or "xyxy" not in r for r in rois):
        raise ValueError("Each ROI requires id, category, image_name and raw xyxy")
    if len({r["id"] for r in rois}) != len(rois):
        raise ValueError("ROI ids must be unique")
    sources, mappings = {}, {}
    output_created = False
    report = {"status": "running", "config": str(config), "checkpoints": [], "roi_coordinate_system": "raw distorted processed pixel xyxy, half-open",
              "evaluation": "official Nerfstudio test cached_eval; metrics before 8-bit PNG quantization",
              "holdout_caveat": "photometric holdout can still contribute to COLMAP; not independent geometry ground truth"}
    for requested in steps if steps is not None else [None]:
        def configure(cfg):
            nonlocal output_created
            data = Path(cfg.pipeline.datamanager.data or cfg.data or cfg.pipeline.datamanager.dataparser.data).resolve()
            transforms = data if data.is_file() else data / "transforms.json"
            metadata = json.loads(transforms.read_text(encoding="utf-8"))
            if not isinstance(metadata.get("ply_file_path"), str):
                raise ValueError("Existing ply_file_path required; refuse Nerfstudio's legacy dataset rewrite")
            sparse = (transforms.parent / metadata["ply_file_path"]).resolve(strict=True)
            if not sparse.is_file():
                raise ValueError("Existing sparse point cloud is required")
            # The coordinator enforces completed-job immutability; a running job
            # may put diagnostics beside (never inside) its dataset/model outputs.
            protected = [transforms.parent, config.parent, Path(cfg.output_dir).resolve()]
            if any(output_dir.is_relative_to(path) for path in protected):
                raise ValueError("Diagnostics must be outside the source dataset and original job/model directories")
            if (cfg.method_name != "splatfacto" or cfg.pipeline.datamanager.camera_res_scale_factor != 1
                    or cfg.pipeline.datamanager.dataparser.downscale_factor != 1):
                raise ValueError("This helper requires Splatfacto with native processed-image resolution")
            for path in (config, transforms, sparse):
                digest = _sha256(path)
                if str(path) in sources and sources[str(path)] != digest:
                    raise DiagnosticIntegrityError("Source files changed between checkpoints")
                sources[str(path)] = digest
            cfg.load_step = requested  # None deliberately selects the latest checkpoint.
            if not output_created:
                output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
                output_dir.chmod(0o700)
                output_created = True
            return cfg

        pipeline = dm = model = gt = pred = outputs = batch = camera = undistorted = validity = None
        batches = train_cache = None
        try:
            _, pipeline, checkpoint, actual_step = eval_setup(config, test_mode="test", update_config_callback=configure)
            if requested is not None and actual_step != requested:
                raise DiagnosticIntegrityError("Loaded checkpoint does not match the requested step")
            dm, model = pipeline.datamanager, pipeline.model
            if not isinstance(dm, FullImageDatamanager) or "cached_eval" in dm.__dict__:
                raise ValueError("Expected an unmodified lazy FullImageDatamanager")
            names = [Path(p).name for p in dm.eval_dataset._dataparser_outputs.image_filenames]
            train_files = dm.train_dataset._dataparser_outputs.image_filenames
            train_names = [Path(p).name for p in train_files]
            train_indices = sorted({0, len(train_names) // 2, len(train_names) - 1})
            if len(set(train_names + names)) != len(train_names) + len(names):
                raise DiagnosticIntegrityError("Training/eval image basenames must be unique and disjoint")
            if any(r["image_name"] not in names for r in rois):
                raise DiagnosticIntegrityError("ROI image_name must identify an actual held-out image")
            raw_cameras = deepcopy(dm.eval_dataset.cameras).to("cpu")
            if any(int(c.item()) != CameraType.PERSPECTIVE.value for c in raw_cameras.camera_type):
                raise ValueError("Only perspective ROI mapping has been verified")
            sparse = dm.train_dataparser_outputs.metadata["points3D_xyz"].detach().cpu().numpy()
            image_hashes = {str(p): _sha256(Path(p)) for p in
                            list(train_files) + list(dm.eval_dataset._dataparser_outputs.image_filenames)}
            split = {"train": train_names, "test": names,
                     "auxiliary_train_views": [train_names[i] for i in train_indices],
                     "image_sha256": {Path(path).name: digest for path, digest in image_hashes.items()}}
            split_hash = hashlib.sha256(json.dumps(split, sort_keys=True).encode()).hexdigest()
            if "split_sha256" in report and report["split_sha256"] != split_hash:
                raise DiagnosticIntegrityError("Input images or split changed between checkpoints")
            report["split"], report["split_sha256"] = split, split_hash
            sources.update(image_hashes)
            report["source_sha256"] = sources
            params = {name: value.detach().cpu().numpy() for name, value in model.gauss_params.items()}
            stats = summarize_gaussians(params["means"], params["scales"], params["opacities"], sparse)
            stats["nonfinite_parameter_counts"] = {name: int((~np.isfinite(value)).sum()) for name, value in params.items()}
            del params
            if (any(stats["nonfinite_parameter_counts"].values())
                    or stats["max_axis_scale"]["nonfinite_count"] or stats["axis_ratio"]["nonfinite_count"]):
                raise ValueError("Checkpoint has nonfinite Gaussian parameters; rendering refused")
            step_dir = output_dir / f"step-{actual_step:09d}"
            step_dir.mkdir(parents=True, exist_ok=False)
            item = {"actual_step": actual_step, "requested_step": requested,
                    "checkpoint": str(checkpoint), "checkpoint_sha256": _sha256(checkpoint),
                    "render_model_step": model.step, "gaussians": stats, "views": [], "train_views": [],
                    "dataparser_transform": dm.train_dataparser_outputs.dataparser_transform.detach().cpu().tolist(),
                    "dataparser_scale": float(dm.train_dataparser_outputs.dataparser_scale), "status": "running"}
            report["checkpoints"].append(item)
            _snapshot(report, output_dir)
            pipeline.eval()
            batches = [("test", index, camera, batch) for index, (camera, batch) in
                       enumerate(dm.fixed_indices_eval_dataloader)]
            train_cache = dm.cached_train  # Match the training loader's undistortion, not raw ns-render images.
            batches.extend(("train", index, dm.train_dataset.cameras[index:index + 1].to(model.device), train_cache[index])
                           for index in train_indices)
            with torch.no_grad():
                for split_name, index, camera, batch in batches:
                    outputs = model.get_outputs_for_camera(camera=camera)
                    gt = model.composite_with_background(model.get_gt_img(batch["image"]), outputs["background"])
                    pred = outputs["rgb"]
                    if gt.shape != pred.shape or gt.shape[-1] != 3:
                        raise ValueError("Evaluation RGB dimensions differ")
                    image_name = names[index] if split_name == "test" else train_names[index]
                    view_dir = step_dir / f"{split_name}-view-{index:03d}"
                    metrics, metric_status = _metrics(model, gt, pred)
                    view = {"image_name": image_name, "split": split_name, "width": int(gt.shape[1]), "height": int(gt.shape[0]),
                            "metrics": metrics, "metric_status": metric_status,
                            "images": _save_images(gt, pred, view_dir, output_dir), "rois": []}
                    if split_name == "train":
                        item["train_views"].append(view)
                        continue
                    raw, undistorted = raw_cameras[index], camera.to("cpu")
                    signature = {"raw_k": raw.get_intrinsics_matrices().numpy().reshape(3, 3).tolist(),
                                 "eval_k": undistorted.get_intrinsics_matrices().numpy().reshape(3, 3).tolist(),
                                 "distortion": (raw.distortion_params.numpy().reshape(-1).tolist()
                                                if raw.distortion_params is not None else [0.] * 6),
                                 "raw_size": [int(raw.width.item()), int(raw.height.item())],
                                 "eval_size": [int(gt.shape[1]), int(gt.shape[0])]}
                    for roi in (r for r in rois if r["image_name"] == names[index]):
                        validity = batch.get("mask")
                        mask = validity.detach().cpu().numpy() if validity is not None else None
                        signature["validity_mask_sha256"] = hashlib.sha256(mask.tobytes()).hexdigest() if mask is not None else None
                        if roi["id"] not in mappings:
                            mappings[roi["id"]] = {"signature": signature,
                                "mapping": map_roi(roi["xyxy"], signature["raw_k"], signature["distortion"],
                                                   signature["eval_k"], signature["raw_size"], signature["eval_size"], mask)}
                        elif mappings[roi["id"]]["signature"] != signature:
                            raise DiagnosticIntegrityError("ROI camera mapping changed between checkpoints")
                        mapping = mappings[roi["id"]]["mapping"]
                        result = {"id": roi["id"], "category": roi["category"], "mapping": mapping,
                                  "metrics": None, "status": "insufficient_valid_crop"}
                        rectangle = mapping["eval_xyxy"]
                        if rectangle:
                            x0, y0, x1, y1 = rectangle
                            result["metrics"], result["metric_status"] = _metrics(model, gt[y0:y1, x0:x1], pred[y0:y1, x0:x1])
                            result["status"] = "measured" if all(s == "measured" for s in result["metric_status"].values()) else "partial"
                            result["images"] = _save_images(gt[y0:y1, x0:x1], pred[y0:y1, x0:x1],
                                                            view_dir / f"roi-{rois.index(roi):03d}", output_dir)
                        view["rois"].append(result)
                    item["views"].append(view)
            item["aggregate"] = _aggregate([v["metrics"] for v in item["views"]])
            item["train_aggregate"] = _aggregate([v["metrics"] for v in item["train_views"]])
            item["roi_aggregate"] = {category: _aggregate([r["metrics"] for v in item["views"]
                for r in v["rois"] if r["category"] == category and r["metrics"] is not None])
                for category in sorted({r["category"] for r in rois})}
            item["status"] = "ok"
            for path, digest in sources.items():
                if _sha256(Path(path)) != digest:
                    raise DiagnosticIntegrityError("An input file changed during evaluation")
            _snapshot(report, output_dir)
        except Exception as exc:
            report["status"] = "partial"
            report["error"] = {"type": type(exc).__name__, "message": str(exc)}
            if output_created:
                _snapshot(report, output_dir)
            raise
        finally:
            pipeline = dm = model = gt = pred = outputs = batch = camera = undistorted = validity = None
            batches = train_cache = None
    report["source_sha256"] = sources
    report["status"] = "ok"
    _snapshot(report, output_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rois", type=Path, help="JSON list of {id, category, image_name, xyxy}")
    parser.add_argument("--steps", nargs="+", type=int, help="Exact zero-based checkpoint indices; default: latest")
    args = parser.parse_args()
    rois = json.loads(args.rois.read_text(encoding="utf-8")) if args.rois else None
    if isinstance(rois, dict):
        rois = rois["rois"]
    result = collect_splat(args.config, args.output, rois, args.steps)
    print(json.dumps({"output": str(args.output / "diagnostics.json"),
                      "actual_steps": [item["actual_step"] for item in result["checkpoints"]]}))


if __name__ == "__main__":
    main()
