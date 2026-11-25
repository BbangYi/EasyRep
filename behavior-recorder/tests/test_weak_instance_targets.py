import unittest

import numpy as np

from behavior_recorder.core import RecorderError
from scripts.weak_instance_targets import build_weak_target


class WeakTargetTests(unittest.TestCase):
    def test_missing_tail_is_unknown_and_other_animal_is_separate_negative(self):
        masks = np.zeros((2, 64, 64), dtype=bool)
        masks[0, 10:30, 10:30] = True
        masks[1, 38:58, 38:58] = True
        labels = build_weak_target(masks, [[8, 8, 36, 36], [36, 36, 60, 60]], 0, margin=2)
        self.assertEqual(labels[20, 20], 1)
        self.assertEqual(labels[32, 32], -1)  # Tail omitted by the source mask.
        self.assertEqual(labels[10, 10], -1)  # Uncertain contour.
        self.assertEqual(labels[48, 48], 2)  # Other instance, not this animal.
        self.assertEqual(labels[0, 0], 0)

    def test_overlapping_masks_never_create_conflicting_supervision(self):
        masks = np.zeros((2, 64, 64), dtype=bool)
        masks[0, 8:40, 8:40] = True
        masks[1, 24:56, 24:56] = True
        boxes = [[8, 8, 40, 40], [24, 24, 56, 56]]
        first = build_weak_target(masks, boxes, 0, margin=2)
        second = build_weak_target(masks, boxes, 1, margin=2)
        self.assertTrue(np.all(first[24:40, 24:40] == -1))
        self.assertTrue(np.all(second[24:40, 24:40] == -1))
        self.assertFalse(np.any((first == 1) & (second == 1)))

    def test_invalid_inputs_and_erased_foreground_are_rejected(self):
        masks = np.zeros((1, 64, 64), dtype=bool)
        masks[0, 10:30, 10:30] = True
        for boxes, index, margin in [([], 0, 2), ([[0, 0, 65, 64]], 0, 2),
                                     ([[0, 0, 64, 64]], 1, 2), ([[0, 0, 64, 64]], 0, 0),
                                     ([[0, 0, 64, 64]], 0, 20)]:
            with self.subTest(boxes=boxes, index=index, margin=margin), self.assertRaises(RecorderError):
                build_weak_target(masks, boxes, index, margin=margin)


if __name__ == '__main__':
    unittest.main()
