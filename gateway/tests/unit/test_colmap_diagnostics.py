"""CPU-only geometry checks; optional reconstruction environment dependencies."""

import csv
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from habitat.gpu.colmap_diagnostics import collect_colmap, compare_camera_geometry, maximum_triangulation_angle, project_opencv


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ("numpy", "cv2", "nerfstudio")),
                     "Run in the existing reconstruction Python environment (CPU only)")
class ColmapDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from nerfstudio.data.utils.colmap_parsing_utils import Camera, Image, Point3D, write_model

        self.np = np
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.processed = self.root / "processed"
        self.model = self.processed / "colmap" / "sparse" / "0"
        self.model.mkdir(parents=True)
        (self.processed / "images").mkdir()
        self.camera = Camera(1, "OPENCV", 100, 80, np.array([100., 120., 50., 40., .1, .01, .001, .002]))
        # Expected distorted x/y calculated analytically, not with project_opencv.
        self.images = {
            1: Image(1, np.array([1., 0, 0, 0]), np.zeros(3), 1, "one.png",
                     np.array([[50., 40.], [10., 10.]]), np.array([1, -1])),
            2: Image(2, np.array([1., 0, 0, 0]), np.array([-1., 0, 0]), 1, "two.png",
                     np.array([[29.94368 + 3, 40.0048 + 4]]), np.array([1])),
        }
        self.points = {1: Point3D(1, np.array([0., 0, 5.]), np.array([1, 2, 3]), 99., np.array([1, 2]), np.array([0, 0]))}
        self.write_model = write_model
        self.write_model({1: self.camera}, self.images, self.points, str(self.model), ".bin")
        import cv2
        for index, name in enumerate(("one.png", "two.png", "unregistered.png")):
            cv2.imwrite(str(self.processed / "images" / name), np.full((80, 100, 3), index, dtype=np.uint8))

    def test_projection_tracks_roi_and_preservation(self):
        initial = {p.name: p.read_bytes() for p in self.model.iterdir()}
        roi = [{"id": "floor", "category": "floor", "image_name": "one.png", "xyxy": [40, 30, 60, 50]},
               {"id": "empty", "category": "reflection", "image_name": "one.png", "xyxy": [80, 60, 100, 80]}]
        (self.root / "colmap_refine.log").write_text("Initial cost : 1.5 [px]\nFinal cost : 0.2 [px]\nTermination : Convergence\n")
        report = collect_colmap(self.processed, self.model, self.root / "diagnostics", roi)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["registered_images"], 2)
        self.assertEqual(report["input_images"], 3)
        self.assertEqual(report["unregistered_images"], ["unregistered.png"])
        self.assertEqual(report["observations"], 2)
        self.assertTrue(report["observation_sums_match"])
        residual = report["observation_reprojection_error_px"]
        self.assertAlmostEqual(residual["mean"], 2.5)
        self.assertAlmostEqual(residual["rmse"], math.sqrt(12.5))
        self.assertEqual(report["stored_point_error_px"]["mean"], 99.)
        self.assertEqual(report["stored_point_error_px"]["source"], "points3D.ERROR")
        self.assertTrue(report["stored_point_error_px"]["ba_log_present"])
        self.assertEqual(report["ba"]["final_cost_px"], .2)
        self.assertAlmostEqual(report["max_triangulation_angle_deg"]["mean"], math.degrees(math.atan(.2)))
        self.assertEqual(report["shared_track_graph"]["components"], [[1, 2]])
        region = report["roi"]["regions"][0]
        self.assertEqual(region["keypoints"], 1)
        self.assertEqual(region["supporting_views"], 2)
        self.assertEqual(region["observation_grid_coverage"], 1 / 64)
        self.assertEqual(report["roi"]["regions"][1]["status"], "unavailable")
        self.assertEqual(report["roi"]["overlays"][0]["status"], "ok")
        self.assertTrue((self.root / "diagnostics" / "overlay-image-1.png").is_file())
        output = self.root / "diagnostics"
        self.assertEqual(json.loads((output / "summary.json").read_text()), report)
        with gzip.open(output / "observations.csv.gz", "rt") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)
        self.assertEqual(initial, {p.name: p.read_bytes() for p in self.model.iterdir()})
        if os.name == "posix":
            self.assertEqual((output.stat().st_mode & 0o777), 0o700)
            self.assertEqual(((output / "summary.json").stat().st_mode & 0o777), 0o600)
        with self.assertRaises(ValueError):
            collect_colmap(self.processed, self.model, self.model / "bad-output")

    def test_world_to_camera_rotation_and_unsupported_model(self):
        np = self.np
        rotation = np.array([[0., -1, 0], [1., 0, 0], [0, 0, 1.]])
        projected = project_opencv(self.camera, rotation, np.array([0., 0, 1]), [1., 0, 4.])[0]
        self.assertAlmostEqual(projected[0], 50.008)
        self.assertAlmostEqual(projected[1], 64.110784)
        self.assertIsNone(maximum_triangulation_angle([0, 0, 0], [[0, 0, 0], [1, 0, 0]]))
        unsupported = self.camera._replace(model="PINHOLE", params=np.array([100., 120., 50., 40.]))
        self.write_model({1: unsupported}, self.images, self.points, str(self.model), ".bin")
        report = collect_colmap(self.processed, self.model, self.root / "unsupported")
        self.assertEqual(report["status"], "partial")
        self.assertIsNone(report["observation_reprojection_error_px"]["mean"])
        self.assertEqual(report["observation_reprojection_error_px"]["excluded_by_reason"], {"unsupported_camera_model": 2})
        self.assertEqual(report["roi"]["status"], "not_run")

    def test_invalid_tracks_nonfinite_points_and_roi_bounds(self):
        np = self.np
        self.points[1] = self.points[1]._replace(xyz=np.array([0., 0, np.nan]),
                                              image_ids=np.array([1, 2, 123]), point2D_idxs=np.array([0, 99, 0]))
        self.write_model({1: self.camera}, self.images, self.points, str(self.model), ".bin")
        report = collect_colmap(self.processed, self.model, self.root / "invalid")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["invalid_track_references"], 2)
        self.assertEqual(report["observation_reprojection_error_px"]["excluded_by_reason"], {"nonfinite_or_invalid_pose": 1})
        json.dumps(report, allow_nan=False)
        with self.assertRaises(ValueError):
            collect_colmap(self.processed, self.model, self.root / "invalid-roi",
                           [{"id": "bad", "category": "floor", "image_name": "one.png", "xyxy": [-1, 0, 10, 10]}])
        self.assertFalse((self.root / "invalid-roi").exists())

    def test_multiple_observations_in_same_image_are_not_missing_views(self):
        np = self.np
        self.images[1] = self.images[1]._replace(xys=np.array([[50., 40.], [10., 10.], [50., 40.]]),
                                               point3D_ids=np.array([1, -1, 1]))
        self.points[1] = self.points[1]._replace(image_ids=np.array([1, 2, 1]), point2D_idxs=np.array([0, 0, 2]))
        self.write_model({1: self.camera}, self.images, self.points, str(self.model), ".bin")
        report = collect_colmap(self.processed, self.model, self.root / "same-view")
        self.assertEqual(report["invalid_track_references"], 0)
        self.assertEqual(report["observation_reprojection_error_px"]["n"], 3)
        self.assertEqual(report["same_view_extra_observations"], 1)
        self.assertEqual(report["track_length"]["mean"], 3)
        self.assertEqual(report["track_unique_views"]["mean"], 2)
        self.assertEqual(report["shared_track_graph"]["edges"], 1)
        self.assertEqual(report["shared_track_graph"]["edge_shared_points"]["mean"], 1)

    def test_sim3_alignment_pairs_image_bytes_and_rotates_poses(self):
        import shutil
        np = self.np
        self.images[3] = self.images[1]._replace(id=3, name="unregistered.png", tvec=np.array([0., -1., 0.]))
        self.write_model({1: self.camera}, self.images, self.points, str(self.model), ".bin")
        second = self.root / "second"
        shutil.copytree(self.processed, second)
        model_b = second / "colmap" / "sparse" / "0"
        rotation = np.array([[0., -1., 0], [1., 0, 0], [0, 0, 1.]])
        translation = np.array([1., -2., 3.])
        images_b = {}
        for index, image in self.images.items():
            center = 2 * rotation @ (-image.tvec) + translation
            images_b[index] = image._replace(qvec=np.array([math.sqrt(.5), 0, 0, -math.sqrt(.5)]),
                                             tvec=-rotation.T @ center)
        self.write_model({1: self.camera}, images_b, self.points, str(model_b), ".bin")
        result = compare_camera_geometry(self.processed, self.model, second, model_b)
        self.assertEqual(result["common_images"], 3)
        self.assertAlmostEqual(result["scale"], 2.)
        self.assertLess(result["center_residual_over_diameter"]["max"], 1e-14)
        self.assertLess(result["rotation_difference_deg"]["max"], 1e-5)
        (second / "images" / "two.png").write_bytes(b"different-image")
        with self.assertRaises(ValueError):
            compare_camera_geometry(self.processed, self.model, second, model_b)


if __name__ == "__main__":
    unittest.main()
