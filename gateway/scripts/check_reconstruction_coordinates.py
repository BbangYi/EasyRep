"""CPU-only coordinate/data harness for trusted completed Nerfstudio jobs.

Reads native configuration and artifacts; never loads a model or writes to a job.
This checks conversion consistency, not the physical truth of COLMAP geometry.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from habitat.gpu.diagnostics import atomic_json, file_hash, input_measurements, stored_records, tree_hashes


def self_test():
    """A known camera/point pair must survive world and OpenGL axis changes."""
    import numpy as np
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    world = np.eye(4)
    world[:3, :3], world[:3, 3] = rotation, [3., -2., 4.]
    camera_to_world = np.eye(4)
    camera_to_world[:3, 3] = [1., 2., 3.]
    point = np.array([2., 4., 8., 1.])
    axes = np.diag([1., -1., -1., 1.])
    expected = np.linalg.inv(camera_to_world) @ point
    converted = np.linalg.inv(world @ camera_to_world @ axes) @ world @ point
    if not np.allclose(axes @ converted, expected):
        raise ValueError("Known coordinate transformation did not round-trip")
    if np.allclose(converted, expected):
        raise ValueError("Negative axis-flip control did not fail")
    return {"known_transform_round_trip": True, "missing_axis_flip_rejected": True}


def check_coordinates(job_dir: Path) -> dict:
    import cv2
    import numpy as np
    import yaml
    from PIL import Image
    from nerfstudio.data.datamanagers.full_images_datamanager import _undistort_image
    from nerfstudio.data.utils.colmap_parsing_utils import (
        qvec2rotmat, read_cameras_binary, read_images_binary, read_points3D_binary,
    )

    job = job_dir.resolve(strict=True)
    processed = job / "processed"
    before = tree_hashes(processed)
    payload, capture = stored_records(job)
    if payload["status"] != "succeeded":
        raise ValueError("Coordinate audit requires a completed job")
    source = json.loads((processed / "transforms.json").read_text())
    # The native parser has a legacy auto-rewrite branch; never enter it.
    ply = (processed / source["ply_file_path"]).resolve(strict=True)
    if not ply.is_relative_to(processed) or "applied_transform" not in source:
        raise ValueError("Expected an existing processed PLY and explicit coordinate transform")
    config_path = job / "trained/habitat-preview/splatfacto/run/config.yml"
    config_sha = file_hash(config_path)
    config = yaml.load(config_path.read_text(), Loader=yaml.Loader)  # Trusted local native config only.
    if config.pipeline.model.random_init or not config.pipeline.datamanager.dataparser.load_3D_points:
        raise ValueError("Expected sparse-point initialization")
    config.pipeline.datamanager.dataparser.data = processed
    parser = config.pipeline.datamanager.dataparser.setup()
    train = parser.get_dataparser_outputs("train")
    test = parser.get_dataparser_outputs("test")
    cameras_by_name = {f.name: out.cameras[i] for out in (train, test)
                       for i, f in enumerate(out.image_filenames)}
    model = json.loads((job / "reconstruction.json").read_text())["selected_colmap_model"]
    if not str(model).isdecimal():
        raise ValueError("Unexpected COLMAP model name")
    sparse = processed / "colmap/sparse" / model
    cameras = read_cameras_binary(sparse / "cameras.bin")
    images = read_images_binary(sparse / "images.bin")
    points = read_points3D_binary(sparse / "points3D.bin")
    indices = {pid: i for i, pid in enumerate(points)}
    xyz = np.array([point.xyz for point in points.values()])
    colors = np.array([point.rgb for point in points.values()])
    world = np.eye(4)
    world[:3] = source["applied_transform"]
    axes = np.diag([1., -1., -1., 1.])
    transform = train.dataparser_transform.numpy()
    scale = train.dataparser_scale
    expected_points = (xyz @ transform[:3, :3].T + transform[:3, 3]) * scale
    native_points = train.metadata["points3D_xyz"].numpy()
    pose_errors, calibration_errors, projection_errors, residuals = [], [], [], []
    image_errors, intrinsics_errors, negative_axis_errors = [], [], []
    image_sizes = set()
    for frame in source["frames"]:
        image = images[frame["colmap_im_id"]]
        if Path(frame["file_path"]).name != image.name:
            raise ValueError("COLMAP image identity differs from transforms.json")
        camera = cameras[image.camera_id]
        if camera.model != "OPENCV":
            raise ValueError("This harness currently validates the pipeline's OPENCV camera model only")
        fx, fy, cx, cy, k1, k2, p1, p2 = camera.params
        calibration_errors.append(np.max(np.abs(camera.params - np.array([
            source[key] for key in ("fl_x", "fl_y", "cx", "cy", "k1", "k2", "p1", "p2")]))))
        world_to_camera = np.eye(4)
        world_to_camera[:3, :3] = qvec2rotmat(image.qvec)
        world_to_camera[:3, 3] = image.tvec
        expected_pose = world @ np.linalg.inv(world_to_camera) @ axes
        pose_errors.append(np.max(np.abs(expected_pose - frame["transform_matrix"])))
        native_camera = cameras_by_name[image.name].reshape(())
        valid = image.point3D_ids >= 0
        selected = [indices[int(pid)] for pid in image.point3D_ids[valid]]
        rotation = native_camera.camera_to_worlds.numpy()[:3, :3]
        translation = native_camera.camera_to_worlds.numpy()[:3, 3]
        camera_points = (native_points[selected] - translation) @ rotation
        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1.]])
        distortion = np.array([k1, k2, p1, p2])
        projected = cv2.projectPoints(xyz[selected], cv2.Rodrigues(world_to_camera[:3, :3])[0],
                                     image.tvec, K, distortion)[0][:, 0]
        native_K = native_camera.get_intrinsics_matrices().numpy()
        broken = cv2.projectPoints(camera_points, np.zeros(3), np.zeros(3), native_K, distortion)[0][:, 0]
        negative_axis_errors.extend(np.linalg.norm(projected - broken, axis=1))
        camera_points[:, 1:] *= -1
        converted = cv2.projectPoints(camera_points, np.zeros(3), np.zeros(3), native_K, distortion)[0][:, 0]
        projection_errors.extend(np.linalg.norm(projected - converted, axis=1))
        residuals.extend(np.linalg.norm(projected - image.xys[valid], axis=1))
        with Image.open(processed / frame["file_path"]) as original:
            raw = np.array(original.convert("RGB"))
        if raw.shape[:2] != (camera.height, camera.width):
            raise ValueError("Image resolution differs from calibration")
        result_K, native, _ = _undistort_image(native_camera, native_camera.distortion_params.numpy(),
                                               {}, raw, native_K.copy())
        # Independent direct OpenCV calculation, including NS's pixel-center convention.
        opencv_K = native_K.copy()
        opencv_K[:2, 2] -= .5
        native_distortion = native_camera.distortion_params.numpy()
        opencv_distortion = np.array([native_distortion[i] for i in (0, 1, 4, 5, 2, 3)] + [0., 0.])
        expected_K, roi = cv2.getOptimalNewCameraMatrix(opencv_K, opencv_distortion, raw.shape[1::-1], 0)
        x, y, width, height = roi
        expected = cv2.undistort(raw, opencv_K, opencv_distortion, None, expected_K)[y:y + height, x:x + width]
        expected_K[0, 2] += .5 - x
        expected_K[1, 2] += .5 - y
        image_errors.append(int(np.max(np.abs(expected.astype(int) - native.astype(int)))))
        intrinsics_errors.append(float(np.max(np.abs(expected_K - result_K))))
        image_sizes.add(tuple(native.shape[:2]))

    saved = json.loads((config_path.parent / "dataparser_transforms.json").read_text())
    # Reuse capture-integrity validation, including UUID ordering, EXIF and RGB/downscale pixels.
    mapping = input_measurements(job, capture, [])
    measurements = {
        "images": len(images), "observations": len(residuals), "initial_points": len(native_points),
        "json_pose_max_abs_error": float(max(pose_errors)),
        "json_calibration_max_abs_error": float(max(calibration_errors)),
        "native_initial_point_max_abs_error": float(np.max(np.abs(native_points - expected_points))),
        "projection_parity_max_pixels": float(max(projection_errors)),
        "projection_parity_mean_pixels": float(np.mean(projection_errors)),
        "colmap_observation_rmse_pixels": float(np.sqrt(np.mean(np.square(residuals)))),
        "native_opencv_undistortion_max_pixel_difference": max(image_errors),
        "native_opencv_undistortion_max_intrinsics_difference": max(intrinsics_errors),
        "negative_missing_axis_flip_mean_projection_error_pixels": float(np.mean(negative_axis_errors)),
        "undistorted_height_width": [list(size) for size in sorted(image_sizes)],
        "dataparser_scale": scale,
    }
    tolerances = {"json_pose_max_abs_error": 1e-10, "json_calibration_max_abs_error": 1e-10,
                  "native_initial_point_max_abs_error": 1e-4, "projection_parity_max_pixels": .02,
                  "native_opencv_undistortion_max_pixel_difference": 0,
                  "native_opencv_undistortion_max_intrinsics_difference": 1e-6}
    checks = {key: measurements[key] <= limit for key, limit in tolerances.items()}
    checks.update({
        "all_registered_images_mapped": len(cameras_by_name) == len(images) == len(source["frames"]),
        "capture_pixel_mapping": all(row["pixel_mapping_verified"] for row in mapping["views"]),
        "native_initial_colors_equal": bool(np.array_equal(colors, train.metadata["points3D_rgb"].numpy())),
        "saved_transform_matches_native": bool(np.allclose(transform, saved["transform"], atol=1e-7, rtol=0)),
        "saved_scale_matches_native": abs(scale - saved["scale"]) < 1e-12,
        "train_test_disjoint": not bool(set(train.image_filenames) & set(test.image_filenames)),
        "negative_missing_axis_flip_detected": float(np.mean(negative_axis_errors)) > 10,
        "processed_data_unchanged": before == tree_hashes(processed),
        "native_config_unchanged": config_sha == file_hash(config_path),
        **self_test(),
    })
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "source_job_id": job.name, "status": "pass" if all(checks.values()) else "fail",
            "scope": "Coordinate/data consistency, not physical geometry truth or trained Gaussian placement",
            "provenance": {"training_config_sha256": config_sha, "processed_files": before,
                           "harness_sha256": file_hash(Path(__file__))},
            "checks": checks, "tolerances": tolerances, "measurements": measurements,
            "train_filenames": [p.name for p in train.image_filenames],
            "test_filenames": [p.name for p in test.image_filenames]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test()))
        return
    if args.job_dir is None or args.output is None:
        parser.error("--job-dir and --output are required unless --self-test")
    if args.output.exists() or args.output.resolve().is_relative_to(args.job_dir.resolve().parent):
        raise ValueError("Use a new report outside all job directories")
    report = check_coordinates(args.job_dir)
    atomic_json(args.output, report)
    print(json.dumps({key: report[key] for key in ("source_job_id", "status", "checks", "measurements")}))
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
