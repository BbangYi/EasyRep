import math
import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_verifier import (
    crop_verifier_image, padded_crop_box, presence_threshold, score_feature_vector, source_balanced_weights,
)


class VerifierTests(unittest.TestCase):
    def test_padding_preserves_visible_extent_at_image_edges(self):
        self.assertEqual(padded_crop_box([-0.0003, 10, 20, 40], 100, 80), [0, 7, 23, 43])
        self.assertEqual(padded_crop_box([80, 60, 100.0003, 80], 100, 80), [77, 58, 100, 80])

    def test_invalid_and_empty_crops_are_rejected(self):
        for box in ([2, 2, 1, 5], [0, 0, float("nan"), 5], [200, 0, 220, 20]):
            with self.subTest(box=box), self.assertRaises(RecorderError):
                padded_crop_box(box, 100, 80)

    def test_extra_crops_do_not_increase_a_source_images_total_weight(self):
        rows = [{"id": "one", "presence_label": 1}, {"id": "two", "presence_label": 1},
                {"id": "negative", "presence_label": 0}, {"id": "negative", "presence_label": 0}]
        weights = source_balanced_weights(rows)
        self.assertEqual(weights, [.25, .25, .25, .25])
        rows.append({"id": "one", "presence_label": 1})
        weights = source_balanced_weights(rows)
        self.assertEqual(weights, [.125, .25, .25, .25, .125])
        self.assertAlmostEqual(sum(weights), 1)

    def test_conflicting_source_labels_and_missing_class_are_rejected(self):
        for rows in (
            [{"id": "one", "presence_label": 1}],
            [{"id": "one", "presence_label": 1}, {"id": "one", "presence_label": 0}],
        ):
            with self.assertRaises(RecorderError):
                source_balanced_weights(rows)

    def test_threshold_uses_required_integer_count_and_keeps_ties(self):
        self.assertEqual(presence_threshold([.1, .2, .2, .8], .75), .2)
        self.assertEqual(presence_threshold([.1, .2, .8], .95), .1)
        self.assertEqual(presence_threshold([.2, .7], 1), .2)
        for values in ([], [.5, float("nan")], [-.1, .4]):
            with self.assertRaises(RecorderError):
                presence_threshold(values, .95)

    def test_scoring_uses_fit_statistics_and_ignores_excluded_dimensions(self):
        head = {"feature_dim": 3, "mean": [1., 2., 9.], "std": [2., 1., 0.],
                "active_indices": [0, 1], "coefficients": [2., -1.], "bias": .5}
        self.assertAlmostEqual(score_feature_vector([3., 3., 10000.], head), 1/(1+math.exp(-1.5)))
        self.assertAlmostEqual(score_feature_vector([3., 3., -10000.], head), 1/(1+math.exp(-1.5)))
        with self.assertRaises(RecorderError):
            score_feature_vector([3., 3.], head)
        with self.assertRaises(RecorderError):
            score_feature_vector([3., float("nan"), 1.], head)

    def test_sigmoid_does_not_overflow(self):
        head = {"feature_dim": 1, "mean": [0.], "std": [1.],
                "active_indices": [0], "coefficients": [1.], "bias": 0.}
        self.assertEqual(score_feature_vector([1000.], head), 1.)
        self.assertEqual(score_feature_vector([-1000.], head), 0.)

    def test_square_padding_retains_wide_and_tall_object_edges(self):
        from PIL import Image
        wide = crop_verifier_image(Image.new("RGB", (3, 1), (255, 0, 0)), [0, 0, 3, 1])
        self.assertEqual(wide.size, (224, 224))
        for point in ((0, 112), (223, 112)):
            self.assertLessEqual(max(abs(a-b) for a, b in zip(wide.getpixel(point), (255, 0, 0))), 1)
        self.assertEqual(wide.getpixel((112, 0)), (124, 116, 104))
        tall = crop_verifier_image(Image.new("RGB", (1, 3), (0, 255, 0)), [0, 0, 1, 3])
        for point in ((112, 0), (112, 223)):
            self.assertLessEqual(max(abs(a-b) for a, b in zip(tall.getpixel(point), (0, 255, 0))), 1)
        self.assertEqual(tall.getpixel((0, 112)), (124, 116, 104))
        with self.assertRaises(RecorderError):
            crop_verifier_image(wide, [0, 0, 225, 224])


if __name__ == "__main__":
    unittest.main()
