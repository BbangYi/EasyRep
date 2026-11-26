"""Read-only sparse-model diagnostics, using the installed COLMAP reader.

Runs in the reconstruction Python environment, on CPU. No model is modified.
Pixel coordinates below are raw, distorted COLMAP-image coordinates.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
import gzip
import hashlib
from itertools import combinations
import json
import math
import os
from pathlib import Path
import re
import tempfile

from habitat.persistence.gpu import sync_directory


@contextmanager
def _atomic_file(path: Path, binary: bool = False):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(temporary, "wb" if binary else "wt", **({} if binary else {"encoding": "utf-8", "newline": ""})) as stream:
            yield stream
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _csv(path: Path, columns: list[str], rows):
    with _atomic_file(path) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _distribution(values) -> dict:
    import numpy as np

    values = np.asarray(list(values), dtype=np.float64)
    valid = values[np.isfinite(values)]
    result = {"n": int(values.size), "finite_n": int(valid.size),
              "nonfinite_n": int(values.size - valid.size), "percentile_method": "linear"}
    names = ("min", "p10", "p50", "p90", "p95", "p99", "max")
    result.update(dict.fromkeys(("mean", *names)))
    if valid.size:
        result["mean"] = float(valid.mean())
        result.update(zip(names, map(float, np.percentile(valid, [0, 10, 50, 90, 95, 99, 100]))))
    return result


def project_opencv(camera, rotation, translation, xyz):
    """COLMAP OPENCV [fx,fy,cx,cy,k1,k2,p1,p2], world-to-camera R/t."""
    import cv2
    import numpy as np

    if camera.model != "OPENCV":
        raise ValueError("unsupported_camera_model")
    params = np.asarray(camera.params, dtype=np.float64)
    xyz = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    if params.shape != (8,) or not np.isfinite(params).all() or np.any(params[:2] <= 0):
        raise ValueError("invalid_camera_parameters")
    matrix = np.array([[params[0], 0, params[2]], [0, params[1], params[3]], [0, 0, 1.]])
    vector, _ = cv2.Rodrigues(np.asarray(rotation, dtype=np.float64))
    pixels, _ = cv2.projectPoints(xyz, vector, np.asarray(translation, dtype=np.float64), matrix, params[4:])
    return pixels.reshape(-1, 2)


def maximum_triangulation_angle(xyz, centers):
    """Maximum acute-or-obtuse ray-pair angle, degrees; not a pruning rule."""
    import numpy as np

    rays = np.asarray(centers, dtype=np.float64).reshape(-1, 3) - np.asarray(xyz, dtype=np.float64)
    lengths = np.linalg.norm(rays, axis=1)
    if len(rays) < 2 or not np.isfinite(rays).all() or np.any(lengths <= 0):
        return None
    rays /= lengths[:, None]
    return float(np.degrees(np.arccos(np.clip((rays @ rays.T).min(), -1, 1))))


def _roi_summary(rois, images, cameras, observations, points):
    import numpy as np

    if rois is None:
        return {"status": "not_run", "reason": "annotations_not_defined", "regions": []}
    if not isinstance(rois, list):
        raise ValueError("ROI annotations must be a list")
    if not rois:
        return {"status": "not_run", "reason": "annotations_not_defined", "regions": []}
    by_name = {image.name: image for image in images.values()}
    seen, regions = set(), []
    for roi in rois:
        if (not isinstance(roi, dict) or not isinstance(roi.get("id"), str) or not roi["id"]
                or roi["id"] in seen or not isinstance(roi.get("category"), str) or not roi["category"]
                or not isinstance(roi.get("image_name"), str)):
            raise ValueError("ROI requires unique id, category and image_name")
        seen.add(roi["id"])
        image = by_name.get(roi["image_name"])
        rectangle = np.asarray(roi.get("xyxy"), dtype=np.float64)
        if image is None or rectangle.shape != (4,) or not np.isfinite(rectangle).all():
            raise ValueError("ROI requires a registered image and finite xyxy rectangle")
        camera = cameras[image.camera_id]
        x0, y0, x1, y1 = map(float, rectangle)
        if not (0 <= x0 < x1 <= camera.width and 0 <= y0 < y1 <= camera.height):
            raise ValueError("ROI rectangle is outside the raw distorted camera image")
        inside = lambda x, y: x0 <= x < x1 and y0 <= y < y1
        features = [(float(x), float(y)) for x, y in image.xys if inside(x, y)]
        rows = [row for row in observations if row["image_id"] == image.id and
                row["observed_x_px"] is not None and inside(row["observed_x_px"], row["observed_y_px"])]
        valid_rows = [row for row in rows if row["status"] == "ok"]
        point_ids = {row["point_id"] for row in rows}
        supported_views = {int(i) for point_id in point_ids for i in points[point_id].image_ids if int(i) in images}
        point_angles = {row["point_id"]: row["max_triangulation_angle_deg"] for row in rows
                        if row["max_triangulation_angle_deg"] is not None}
        grid = lambda xy: (min(7, int((xy[0] - x0) / (x1 - x0) * 8)),
                           min(7, int((xy[1] - y0) / (y1 - y0) * 8)))
        area = (x1 - x0) * (y1 - y0)
        regions.append({"id": roi["id"], "category": roi["category"], "image_name": image.name,
                        "xyxy": [x0, y0, x1, y1], "area_px2": area,
                        "status": "ok" if valid_rows else "unavailable",
                        "reason": None if valid_rows else "no_valid_reprojection_observations",
                        "keypoints": len(features), "observations": len(rows), "valid_observations": len(valid_rows),
                        "unique_points": len(point_ids), "supporting_views": len(supported_views),
                        "keypoints_per_megapixel": len(features) / area * 1e6,
                        "observations_per_megapixel": len(rows) / area * 1e6,
                        "grid_shape": [8, 8], "feature_grid_coverage": len({grid(xy) for xy in features}) / 64,
                        "observation_grid_coverage": len({grid((r["observed_x_px"], r["observed_y_px"])) for r in rows}) / 64,
                        "residual_px": _distribution(r["error_px"] for r in valid_rows),
                        "track_length": _distribution(len(points[p].image_ids) for p in point_ids),
                        "max_triangulation_angle_deg": _distribution(point_angles.values())})
    return {"status": "ok" if all(r["status"] == "ok" for r in regions) else "partial",
            "coordinate_space": "raw_distorted_colmap_image_pixels", "xyxy_bounds": "left/top inclusive; right/bottom exclusive",
            "regions": regions}


def _overlays(processed, output_dir, rois, observations, images):
    import cv2
    import numpy as np

    outputs = []
    for image in images.values():
        regions = [roi for roi in rois if roi["image_name"] == image.name]
        if not regions:
            continue
        source = (processed / "images" / image.name).resolve()
        if (processed / "images").resolve() not in source.parents:
            raise ValueError("COLMAP image filename escapes processed images")
        canvas = cv2.imread(str(source))
        if canvas is None:
            outputs.append({"image_name": image.name, "status": "unavailable", "reason": "image_decode_failed"})
            continue
        for roi in regions:
            x0, y0, x1, y1 = map(int, roi["xyxy"])
            cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (255, 180, 0), 1)
            cv2.putText(canvas, roi["id"], (x0, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, .4, (255, 180, 0), 1)
        for row in observations:
            x, y = row["observed_x_px"], row["observed_y_px"]
            if row["image_id"] != image.id or x is None or y is None or not any(
                    r["xyxy"][0] <= x < r["xyxy"][2] and r["xyxy"][1] <= y < r["xyxy"][3] for r in regions):
                continue
            observed = (round(x), round(y))
            if row["projected_x_px"] is not None and row["projected_y_px"] is not None:
                target = np.rint([row["projected_x_px"], row["projected_y_px"]])
                # Prevent integer overflow in OpenCV drawing of malformed models.
                if np.abs(target).max() < 2**30:
                    projected = tuple(map(int, target))
                    cv2.line(canvas, observed, projected, (0, 255, 255), 1)
                    cv2.circle(canvas, projected, 2, (0, 0, 255), 1)
            cv2.circle(canvas, observed, 4, (0, 255, 0), 1)
        cv2.putText(canvas, "GREEN observed / RED projected / YELLOW residual (actual pixel length)",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
        success, encoded = cv2.imencode(".png", canvas)
        if not success:
            raise ValueError("failed to encode reprojection overlay")
        filename = f"overlay-image-{image.id}.png"
        with _atomic_file(output_dir / filename, binary=True) as stream:
            stream.write(encoded.tobytes())
        outputs.append({"image_name": image.name, "status": "ok", "file": filename,
                        "sha256": _digest(output_dir / filename)})
    return outputs


def collect_colmap(processed: Path, model: Path, output_dir: Path, rois: list[dict] | None = None) -> dict:
    """Return a JSON-safe summary; write protected CSV.gz detail and summary.json.

    No dependencies on Torch/CUDA. Unsupported camera models are explicit partial
    results. File/storage errors propagate to the existing worker error handling.
    """
    import numpy as np
    from nerfstudio.data.utils.colmap_parsing_utils import read_model

    processed, model, output_dir = Path(processed), Path(model), Path(output_dir)
    if any(source.resolve() == output_dir.resolve() or source.resolve() in output_dir.resolve().parents
           for source in (processed, model)):
        raise ValueError("diagnostic output must be outside the processed input")
    cameras, images, points = read_model(str(model), ".bin")
    rotations = {i: image.qvec2rotmat() for i, image in images.items()}
    centers = {i: -rotations[i].T @ image.tvec for i, image in images.items()}
    observations, point_rows, edges = [], [], Counter()
    invalid_tracks, invalid_poses = 0, 0
    for image_id, image in images.items():
        if (not np.isfinite(rotations[image_id]).all() or not np.isfinite(image.tvec).all()
                or not np.isclose(np.linalg.norm(image.qvec), 1., atol=1e-5)):
            invalid_poses += 1
    for point in points.values():
        valid_tracks = []
        track_pairs = list(zip(point.image_ids, point.point2D_idxs))
        if len(point.image_ids) != len(point.point2D_idxs):
            invalid_tracks += abs(len(point.image_ids) - len(point.point2D_idxs))
        visited = set()
        for image_id, point_index in track_pairs:
            image_id, point_index = int(image_id), int(point_index)
            image = images.get(image_id)
            if (image is None or (image_id, point_index) in visited or point_index < 0 or point_index >= len(image.xys)
                    or int(image.point3D_ids[point_index]) != point.id):
                invalid_tracks += 1
                continue
            visited.add((image_id, point_index))
            valid_tracks.append((image_id, point_index))
        angle = maximum_triangulation_angle(point.xyz, [centers[i] for i, _ in valid_tracks])
        unique_views = sorted({i for i, _ in valid_tracks})
        point_rows.append({"point_id": int(point.id), "x": _finite(point.xyz[0]), "y": _finite(point.xyz[1]),
                           "z": _finite(point.xyz[2]), "track_length": len(point.image_ids),
                           "valid_track_length": len(valid_tracks), "unique_view_count": len(unique_views),
                           "stored_error_px": _finite(point.error),
                           "max_triangulation_angle_deg": angle})
        edges.update(combinations(unique_views, 2))
        for image_id, point_index in valid_tracks:
            image, rotation = images[image_id], rotations[image_id]
            camera = cameras[image.camera_id]
            observed = image.xys[point_index]
            depth = _finite((rotation @ point.xyz + image.tvec)[2])
            status, projected, error = "ok", (None, None), None
            if not (np.isfinite(point.xyz).all() and np.isfinite(observed).all()
                    and np.isfinite(rotation).all() and np.isfinite(image.tvec).all()
                    and np.isclose(np.linalg.norm(image.qvec), 1., atol=1e-5)):
                status = "nonfinite_or_invalid_pose"
            elif depth is None or depth <= 0:
                status = "nonpositive_depth"
            elif camera.model != "OPENCV":
                status = "unsupported_camera_model"
            else:
                try:
                    projected = project_opencv(camera, rotation, image.tvec, point.xyz)[0]
                    error = _finite(np.linalg.norm(projected - observed))
                    if error is None:
                        status = "nonfinite_projection"
                except ValueError:
                    status = "invalid_camera_parameters"
            observations.append({"point_id": int(point.id), "image_id": image_id, "image_name": image.name,
                                 "point2D_index": point_index, "observed_x_px": _finite(observed[0]),
                                 "observed_y_px": _finite(observed[1]), "projected_x_px": _finite(projected[0]),
                                 "projected_y_px": _finite(projected[1]), "depth": depth, "error_px": error,
                                 "track_length": len(point.image_ids), "max_triangulation_angle_deg": angle,
                                 "status": status})
    per_image, adjacent = [], {i: set() for i in images}
    for (first, second), count in edges.items():
        adjacent[first].add(second)
        adjacent[second].add(first)
    for image_id, image in sorted(images.items()):
        rows = [r for r in observations if r["image_id"] == image_id]
        residuals = [r["error_px"] for r in rows if r["error_px"] is not None]
        count = int(np.count_nonzero(image.point3D_ids >= 0))
        distribution = _distribution(residuals)
        per_image.append({"image_id": image_id, "image_name": image.name, "camera_id": int(image.camera_id),
                          "keypoints": len(image.xys), "triangulated": count,
                          "triangulated_fraction": count / len(image.xys) if len(image.xys) else None,
                          "valid_residuals": len(residuals), "error_mean_px": distribution["mean"],
                          "error_p95_px": distribution["p95"], "shared_track_degree": len(adjacent[image_id])})
    components, unseen = [], set(images)
    while unseen:
        pending, component = [min(unseen)], set()
        while pending:
            node = pending.pop()
            if node not in component:
                component.add(node)
                pending.extend(adjacent[node] - component)
        unseen -= component
        components.append(sorted(component))
    residuals = [row["error_px"] for row in observations if row["status"] == "ok"]
    residual_stats = _distribution(residuals)
    residual_stats.update({"status": "ok" if len(residuals) == len(observations) and residuals else "partial" if residuals else "unavailable",
                           "source": "recomputed_current_model_parameters", "unit": "px", "aggregation": "per_observation_euclidean_norm",
                           "coordinate_space": "raw_distorted_colmap_image_pixels",
                           "rmse": float(np.sqrt(np.mean(np.square(residuals)))) if residuals else None,
                           "excluded_by_reason": dict(Counter(r["status"] for r in observations if r["status"] != "ok"))})
    stored_errors = _distribution(float(p.error) for p in points.values())
    stored_errors.update({"source": "points3D.ERROR", "unit": "px",
                          "aggregation": "unweighted_per_point_mean_errors",
                          "ba_log_present": (processed.parent / "colmap_refine.log").is_file()})
    present_images = {p.relative_to(processed / "images").as_posix() for p in (processed / "images").rglob("*")
                      if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}}
    registered_names = {image.name for image in images.values()}
    log = processed.parent / "colmap_refine.log"
    ba = {"log_present": log.is_file()}
    if log.is_file():
        contents = log.read_text(encoding="utf-8", errors="replace")
        ba["log_sha256"] = _digest(log)
        for field, pattern in (("initial_cost_px", r"Initial cost\s*:\s*([0-9.eE+\-]+)"),
                               ("final_cost_px", r"Final cost\s*:\s*([0-9.eE+\-]+)")):
            match = re.search(pattern, contents)
            ba[field] = _finite(float(match[1])) if match else None
        match = re.search(r"Termination\s*:\s*([^\r\n]+)", contents)
        ba["termination"] = match[1].strip() if match else None
    observation_sum = sum(len(p.image_ids) for p in points.values())
    image_sum = sum(r["triangulated"] for r in per_image)
    roi = _roi_summary(rois, images, cameras, observations, points)
    result = {"schema_version": 1, "status": "ok" if residual_stats["status"] == "ok" and not invalid_tracks
              and not invalid_poses and observation_sum == image_sum and not (registered_names - present_images) else "partial",
              "selected_model": model.name, "model_sha256": {name: _digest(model / name) for name in ("cameras.bin", "images.bin", "points3D.bin")},
              "input_images": len(present_images), "registered_images": len(images),
              "registration_fraction": len(images) / len(present_images) if present_images else None,
              "unregistered_images": sorted(present_images - registered_names),
              "registered_files_missing": sorted(registered_names - present_images),
              "cameras": [{"id": int(c.id), "model": c.model, "width": int(c.width), "height": int(c.height),
                           "params": [_finite(v) for v in c.params]} for c in cameras.values()],
              "sparse_points": len(points), "observations": observation_sum, "image_observations": image_sum,
              "valid_track_references": len(observations), "invalid_track_references": invalid_tracks,
              "invalid_poses": invalid_poses, "observation_sums_match": observation_sum == image_sum,
              "keypoints": sum(r["keypoints"] for r in per_image),
              "track_length": _distribution(len(p.image_ids) for p in points.values()),
              "track_unique_views": _distribution(r["unique_view_count"] for r in point_rows),
              "same_view_extra_observations": sum(r["valid_track_length"] - r["unique_view_count"] for r in point_rows),
              "two_view_points": sum(len(p.image_ids) == 2 for p in points.values()),
              "three_view_points": sum(len(p.image_ids) == 3 for p in points.values()),
              "stored_point_error_px": stored_errors, "observation_reprojection_error_px": residual_stats,
              "max_triangulation_angle_deg": _distribution(r["max_triangulation_angle_deg"] for r in point_rows
                                                           if r["max_triangulation_angle_deg"] is not None),
              "ba": ba, "shared_track_graph": {"source": "retained_sparse_tracks_not_database_verified_pairs",
                        "nodes": len(images), "edges": len(edges), "components": components,
                        "degree": _distribution(len(neighbors) for neighbors in adjacent.values()),
                        "edge_shared_points": _distribution(edges.values())},
              "per_image": per_image, "roi": roi}
    # Validate before publishing any report; JSON never silently emits NaN/Infinity.
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        output_dir.chmod(0o700)
    _csv(output_dir / "observations.csv.gz", ["point_id", "image_id", "image_name", "point2D_index", "observed_x_px",
         "observed_y_px", "projected_x_px", "projected_y_px", "depth", "error_px", "track_length", "max_triangulation_angle_deg", "status"], observations)
    _csv(output_dir / "points.csv.gz", ["point_id", "x", "y", "z", "track_length", "valid_track_length", "unique_view_count", "stored_error_px", "max_triangulation_angle_deg"], point_rows)
    _csv(output_dir / "edges.csv.gz", ["image_id_a", "image_id_b", "shared_points"],
         ({"image_id_a": a, "image_id_b": b, "shared_points": count} for (a, b), count in sorted(edges.items())))
    _csv(output_dir / "images.csv.gz", ["image_id", "image_name", "camera_id", "keypoints", "triangulated", "triangulated_fraction",
         "valid_residuals", "error_mean_px", "error_p95_px", "shared_track_degree"], per_image)
    if rois:
        result["roi"]["overlays"] = _overlays(processed, output_dir, rois, observations, images)
        encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    with _atomic_file(output_dir / "summary.json") as stream:
        stream.write(encoded + "\n")
    return result


def _finite(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def compare_camera_geometry(processed_a: Path, model_a: Path, processed_b: Path, model_b: Path) -> dict:
    """Align A camera centers to B by Sim(3), pairing only identical image bytes.

    Describes relative pose variation, not which reconstruction is correct.
    Geometry units are arbitrary. No model or image is modified.
    """
    import numpy as np
    from nerfstudio.data.utils.colmap_parsing_utils import read_model

    reconstructions = [read_model(str(model), ".bin") for model in (model_a, model_b)]
    image_sets = [reconstruction[1] for reconstruction in reconstructions]
    by_hash = []
    for processed, images in zip((Path(processed_a), Path(processed_b)), image_sets):
        mapping = {}
        for image in images.values():
            path = (processed / "images" / image.name).resolve()
            if (processed / "images").resolve() not in path.parents:
                raise ValueError("COLMAP image filename escapes processed images")
            digest = _digest(path)
            if digest in mapping:
                raise ValueError("ambiguous duplicate image contents for camera matching")
            mapping[digest] = image
        by_hash.append(mapping)
    common = sorted(set(by_hash[0]) & set(by_hash[1]))
    if len(common) < 3:
        raise ValueError("at least three identical registered images required for Sim(3)")
    paired = [(by_hash[0][digest], by_hash[1][digest]) for digest in common]
    centers = [np.array([-pair[k].qvec2rotmat().T @ pair[k].tvec for pair in paired]) for k in (0, 1)]
    a, b = centers
    ac, bc = a - a.mean(axis=0), b - b.mean(axis=0)
    if not np.isfinite(a).all() or not np.isfinite(b).all() or min(np.linalg.matrix_rank(ac), np.linalg.matrix_rank(bc)) < 2:
        raise ValueError("nonfinite or collinear camera centers cannot determine a stable Sim(3)")
    u, singular, vt = np.linalg.svd(bc.T @ ac / len(a))
    signs = np.array([1., 1., np.linalg.det(u @ vt)])
    rotation = u @ np.diag(signs) @ vt
    scale = float(np.dot(singular, signs) / np.mean(np.sum(ac * ac, axis=1)))
    translation = b.mean(axis=0) - scale * rotation @ a.mean(axis=0)
    aligned = scale * (a @ rotation.T) + translation
    # ponytail: pairwise diameter is O(n²); use a bounded subsample for very large captures.
    diameter = float(np.max(np.linalg.norm(b[:, None] - b[None, :], axis=-1)))
    distances = np.linalg.norm(aligned - b, axis=1)
    normalized_residual = distances / diameter
    points_b = np.asarray([p.xyz for p in reconstructions[1][2].values()], dtype=np.float64).reshape(-1, 3)
    points_b = points_b[np.isfinite(points_b).all(axis=1)]
    scene_diagonal = float(np.linalg.norm(np.ptp(points_b, axis=0))) if len(points_b) else 0.
    angle = [float(np.degrees(np.arccos(np.clip((np.trace(second.qvec2rotmat() @ rotation @ first.qvec2rotmat().T) - 1) / 2, -1, 1))))
             for first, second in paired]
    result = {"schema_version": 1, "status": "ok", "pairing": "identical_processed_image_sha256",
              "model_sha256_a": {name: _digest(Path(model_a) / name) for name in ("cameras.bin", "images.bin", "points3D.bin")},
              "model_sha256_b": {name: _digest(Path(model_b) / name) for name in ("cameras.bin", "images.bin", "points3D.bin")},
              "common_images": len(common), "registered_images_a": len(image_sets[0]), "registered_images_b": len(image_sets[1]),
              "fit": "all_common_camera_centers_unweighted_Sim3_A_to_B", "scale": scale,
              "rotation": rotation.tolist(), "translation": translation.tolist(),
              "normalizer": "maximum_pairwise_common_camera_center_distance_in_B_not_physical_scene_extent",
              "camera_center_diameter_b": diameter, "center_residual_over_diameter": _distribution(normalized_residual),
              "sparse_scene_bbox_diagonal_b": scene_diagonal or None,
              "scene_normalizer_caveat": "finite_B_sparse_point_AABB_diagonal; arbitrary_units; sensitive_to_outliers; not_verified_physical_scene_diameter",
              "center_residual_over_scene_bbox_diagonal": _distribution(distances / scene_diagonal if scene_diagonal else []),
              "rotation_difference_deg": _distribution(angle), "metric_scale_verified": False,
              "per_image": [{"sha256": digest, "image_a": pair[0].name, "image_b": pair[1].name,
                             "center_residual_over_diameter": float(distance),
                             "center_residual_over_scene_bbox_diagonal": float(distance * diameter / scene_diagonal) if scene_diagonal else None,
                             "rotation_difference_deg": degrees}
                            for digest, pair, distance, degrees in zip(common, paired, normalized_residual, angle)]}
    json.dumps(result, allow_nan=False)
    return result
