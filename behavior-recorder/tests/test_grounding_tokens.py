import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_grounding import category_token_indices


class GroundingTokenTests(unittest.TestCase):
    def test_complete_wordpiece_sequence_excludes_articles_and_punctuation(self):
        result = category_token_indices(
            [101, 1037, 15181, 1012, 1037, 2522, 10231, 1012, 102],
            {"lizard": [15181], "crocodile": [2522, 10231]},
        )
        self.assertEqual(result, {"lizard": [2], "crocodile": [5, 6]})

    def test_missing_partial_and_repeated_categories_are_rejected(self):
        for input_ids, category in (
            ([101, 5, 102], [6]),
            ([101, 5, 102], [5, 6]),
            ([101, 5, 5, 102], [5]),
        ):
            with self.subTest(input_ids=input_ids, category=category), self.assertRaises(RecorderError):
                category_token_indices(input_ids, {"target": category})

    def test_empty_invalid_and_overlapping_categories_are_rejected(self):
        for categories in ({}, {"target": []}, {"target": [True]},
                           {"target": [5], "background": [5, 6]}):
            with self.subTest(categories=categories), self.assertRaises(RecorderError):
                category_token_indices([101, 5, 6, 102], categories)


if __name__ == "__main__":
    unittest.main()
