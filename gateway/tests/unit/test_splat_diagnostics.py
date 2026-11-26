"""CPU checks for the optional GPU-env diagnostics; never run a model or CUDA."""

import importlib.util
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from habitat.gpu.splat_diagnostics import _aggregate, _interior_rectangle, _metrics, map_roi, summarize_gaussians


@unittest.skipUnless(importlib.util.find_spec("numpy"), "run in the existing GPU environment for NumPy checks")
class SplatDiagnosticsTests(unittest.TestCase):
    def test_checkpoint_statistics_and_sparse_bounds(self):
        import numpy as np

        result = summarize_gaussians([[0, 0, 0], [2, 0, 0]], np.log([[0.1, 0.2, 0.4], [1, 0.1, 0.1]]),
                                     [[0], [math.log(0.05 / 0.95)]], [[-1, -1, -1], [1, 1, 1]])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["centers"]["outside_initial_aabb_count"], 1)
        self.assertAlmostEqual(result["max_axis_scale"]["max"], 1)
        self.assertAlmostEqual(result["axis_ratio"]["max"], 10)
        self.assertEqual(result["max_scale_above_0_5_count"], 1)
        self.assertEqual(result["large_and_opacity_at_most_0_1_count"], 1)
        self.assertEqual(result["nonfinite_scalar_count"], 0)
        self.assertEqual(result["scene_bounds"]["aabb"], [[-1., -1., -1.], [1., 1., 1.]])
        self.assertAlmostEqual(result["scene_bounds"]["extent"], math.sqrt(12))
        self.assertEqual(result["scene_bounds"]["extent_definition"], "initial_sparse_aabb_diagonal")
        self.assertFalse(result["scene_bounds"]["metric_scale_verified"])

    def test_invalid_shapes_and_sparse_nan_rejected(self):
        for means, logs, sparse in (([], [], [[0, 0, 0]]), ([[0, 0, 0]], [[0, 0]], [[0, 0, 0]]),
                                    ([[0, 0, 0]], [[0, 0, 0]], [[float("nan"), 0, 0]])):
            with self.assertRaises(ValueError):
                summarize_gaussians(means, logs, [0], sparse)

    def test_nonfinite_and_overflow_are_reported_not_clipped(self):
        result = summarize_gaussians([[float("nan"), 0, 0]], [[1000, 0, 0]], [float("inf")], [[0, 0, 0]])
        self.assertEqual(result["nonfinite_scalar_count"], 2)
        self.assertEqual(result["max_axis_scale"]["nonfinite_count"], 1)
        self.assertIsNone(result["max_axis_scale"]["max"])

    def test_largest_valid_rectangle_never_contains_masked_pixels(self):
        import numpy as np

        mask = np.array([[0, 1, 1, 0], [1, 1, 1, 1], [1, 1, 1, 1]], dtype=bool)
        rectangle = _interior_rectangle(mask)
        self.assertEqual(rectangle, [0, 1, 4, 3])
        x0, y0, x1, y1 = rectangle
        self.assertTrue(mask[y0:y1, x0:x1].all())
        self.assertIsNone(_interior_rectangle(np.zeros((2, 3), dtype=bool)))

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV lives in the GPU environment")
    def test_identity_roi_and_validity_mask(self):
        import numpy as np

        k = np.array([[80, 0, 50.5], [0, 80, 40.5], [0, 0, 1]])
        mapped = map_roi([20, 10, 70, 60], k, [0] * 6, k, [100, 80], [100, 80])
        self.assertEqual(mapped["eval_xyxy"], [20, 10, 70, 60])
        cropped_k = k.copy()
        cropped_k[:2, 2] -= [10, 5]
        cropped = map_roi([20, 10, 70, 60], k, [0] * 6, cropped_k, [100, 80], [80, 70])
        self.assertEqual(cropped["eval_xyxy"], [10, 5, 60, 55])
        mask = np.ones((80, 100), dtype=bool)
        mask[30:] = False
        mapped = map_roi([20, 10, 70, 60], k, [0] * 6, k, [100, 80], [100, 80], mask)
        self.assertEqual(mapped["eval_xyxy"], [20, 10, 70, 30])
        with self.assertRaises(ValueError):
            map_roi([-1, 0, 30, 30], k, [0] * 6, k, [100, 80], [100, 80])

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV lives in the GPU environment")
    def test_distorted_roi_uses_conservative_bilinear_support(self):
        import cv2
        import numpy as np

        k = np.array([[80., 0, 50.5], [0, 80, 40.5], [0, 0, 1]])
        distortion = [-0.15, 0.03, 0, 0, 0.001, -0.001]
        mapped = map_roi([15, 10, 85, 70], k, distortion, k, [100, 80], [100, 80])
        opencv_k = k.copy()
        opencv_k[:2, 2] -= 0.5
        coefficients = np.array(distortion)[[0, 1, 4, 5, 2]]
        map_x, map_y = cv2.initUndistortRectifyMap(opencv_k, coefficients, None, opencv_k, (100, 80), cv2.CV_32FC1)
        x0, y0, x1, y1 = mapped["eval_xyxy"]
        self.assertTrue(((map_x[y0:y1, x0:x1] >= 15) & (map_x[y0:y1, x0:x1] <= 84)).all())
        self.assertTrue(((map_y[y0:y1, x0:x1] >= 10) & (map_y[y0:y1, x0:x1] <= 69)).all())


class AggregateTests(unittest.TestCase):
    def test_mean_and_sample_std_match_official_aggregation(self):
        result = _aggregate([{key: value for key in ("psnr", "ssim", "lpips")} for value in (1., 3., 5.)])
        self.assertEqual(result["psnr"], 3.)
        self.assertEqual(result["psnr_std"], 2.)
        self.assertIsNone(_aggregate([{"psnr": 1., "ssim": 1., "lpips": 0.}])["psnr_std"])

    def test_small_roi_keeps_psnr_ssim_without_running_lpips(self):
        pixels = Mock()
        pixels.shape = (37, 90, 3)
        pixels.permute.return_value = {None: pixels}
        model = SimpleNamespace(**{key: Mock(return_value=SimpleNamespace(item=lambda: 0.5))
                                   for key in ("psnr", "ssim", "lpips")})
        scores, status = _metrics(model, pixels, pixels)
        self.assertEqual(scores, {"psnr": 0.5, "ssim": 0.5, "lpips": None})
        self.assertEqual(status["lpips"], "unsupported_small_crop")
        model.lpips.assert_not_called()
        result = _aggregate([scores])
        self.assertEqual(result["valid_metric_counts"], {"psnr": 1, "ssim": 1, "lpips": 0})
        self.assertIsNone(result["lpips"])


if __name__ == "__main__":
    unittest.main()
