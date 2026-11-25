import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_seed import padded_crop, confirm_seed
from behavior_recorder import vision_seed


class SeedConfirmationTests(unittest.TestCase):
    def test_padding_clips_and_rounds_outward_without_cutting_the_proposal(self):
        self.assertEqual(padded_crop([2, 3, 12, 13], 20, 20, .25), [0, 0, 15, 16])
        self.assertEqual(padded_crop([80, 80, 100, 100], 100, 100, .25), [75, 75, 100, 100])

    def test_confirmation_maps_crop_coordinates_back_to_original_pixels(self):
        result = confirm_seed([120, 70, 180, 130], [100, 50, 200, 150],
                              [{'xyxy': [20, 20, 80, 80], 'confidence': .8}], 300, 200)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['confirmed_box'], [120, 70, 180, 130])
        self.assertEqual(result['iou'], 1)
        self.assertEqual(result['confidence'], .8)

    def test_unrelated_high_score_and_weak_overlapping_box_cannot_confirm(self):
        proposals = [{'xyxy': [0, 0, 10, 10], 'confidence': .99},
                     {'xyxy': [20, 20, 80, 80], 'confidence': .39}]
        result = confirm_seed([120, 70, 180, 130], [100, 50, 200, 150], proposals, 300, 200)
        self.assertFalse(result['accepted'])
        self.assertIsNone(result['confirmed_box'])

    def test_empty_verification_cannot_create_a_seed(self):
        self.assertFalse(confirm_seed([10, 10, 20, 20], [0, 0, 30, 30], [], 100, 100)['accepted'])

    def test_best_confident_matching_body_wins_over_unrelated_prediction(self):
        candidates = [{'xyxy': [0, 0, 10, 10], 'confidence': .99},
                      {'xyxy': [20, 20, 80, 80], 'confidence': .7},
                      {'xyxy': [21, 20, 80, 80], 'confidence': .9}]
        result = confirm_seed([120, 70, 180, 130], [100, 50, 200, 150], candidates, 300, 200)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['confirmed_box'], [121, 70, 180, 130])
        self.assertEqual(result['confidence'], .9)

    def test_invalid_boxes_and_crop_geometry_are_rejected(self):
        for box in ([0, 0, 0, 10], [-1, 0, 10, 10], [0, 0, float('nan'), 10]):
            with self.assertRaises(RecorderError):
                padded_crop(box, 100, 100)
        with self.assertRaises(RecorderError):
            confirm_seed([20, 20, 40, 40], [25, 25, 50, 50], [], 100, 100)
        with self.assertRaises(RecorderError):
            confirm_seed([20, 20, 40, 40], [10, 10, 50, 50],
                         [{'xyxy': [0, 0, 50, 50], 'confidence': .8}], 100, 100)


class ConsensusSeedTests(unittest.TestCase):
    def setUp(self):
        self.choose = getattr(vision_seed, 'choose_consensus_seed', None)
        self.assertTrue(callable(self.choose), 'full-frame consensus seed selection is missing')

    def test_background_box_cannot_override_a_lower_scoring_agreed_body(self):
        primary = [{'xyxy': [0, 0, 100, 100], 'confidence': .99},
                   {'xyxy': [20, 20, 40, 40], 'confidence': .6}]
        secondary = [{'xyxy': [21, 20, 41, 40], 'confidence': .8}]
        result = self.choose(primary, secondary, 100, 100)
        self.assertEqual(result['box'], [20, 20, 40, 40])
        self.assertEqual(result['primary_index'], 1)
        self.assertAlmostEqual(result['agreement_iou'], 19/21)

    def test_neither_model_alone_or_low_confidence_agreement_can_start_tracking(self):
        body = {'xyxy': [20, 20, 40, 40], 'confidence': .8}
        for primary, secondary in [([body], []), ([], [body]),
                ([dict(body, confidence=.39)], [body]), ([body], [dict(body, confidence=.24)])]:
            with self.subTest(primary=primary, secondary=secondary):
                self.assertIsNone(self.choose(primary, secondary, 100, 100))

    def test_exact_overlap_threshold_is_inclusive_and_primary_box_is_retained(self):
        primary = [{'xyxy': [10, 10, 30, 30], 'confidence': .4}]
        secondary = [{'xyxy': [10, 10, 20, 30], 'confidence': .25}]
        self.assertEqual(self.choose(primary, secondary, 100, 100)['box'], [10, 10, 30, 30])
        self.assertIsNone(self.choose(primary, secondary, 100, 100, iou=.51))

    def test_invalid_geometry_and_nonfinite_scores_fail_before_selection(self):
        valid = [{'xyxy': [10, 10, 20, 20], 'confidence': .8}]
        for invalid in ([{'xyxy': [-1, 0, 20, 20], 'confidence': .8}],
                        [{'xyxy': [10, 10, 20, 20], 'confidence': float('nan')}],
                        [{'xyxy': [10, 10, 10, 20], 'confidence': .1}]):
            with self.subTest(invalid=invalid), self.assertRaises(RecorderError):
                self.choose(invalid, valid, 100, 100)
        with self.assertRaises(RecorderError):
            self.choose(valid, [{'xyxy': [0, 0, 200, 200], 'confidence': .8}], 100, 100)


if __name__ == '__main__':
    unittest.main()
