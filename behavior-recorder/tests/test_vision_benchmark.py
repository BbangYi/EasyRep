import copy
import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_benchmark import match_detections, select_candidate, summarize
from behavior_recorder.vision_model import validate_training_options


def selection_reports():
    box = {"xyxy": [0, 0, 10, 10], "confidence": .9}
    positive = {"reference_boxes": [box["xyxy"]], "predictions": [box],
                "true_positive": 1, "false_positive": 0, "false_negative": 0,
                "negative_image": False, "negative_image_false_positive": False}
    baseline = {"split": "val", "dataset_id": "data", "confidence": .4, "iou": .5,
                "per_image": [{"image_id": name, **copy.deepcopy(positive)} for name in ("a", "b", "c")]
                + [{"image_id": "negative", "reference_boxes": [], "predictions": [copy.deepcopy(box) for _ in range(4)],
                    "true_positive": 0, "false_positive": 4, "false_negative": 0,
                    "negative_image": True, "negative_image_false_positive": True}],
                "metrics": {"true_positive": 3, "false_positive": 4, "false_negative": 0,
                            "negative_image": 1, "negative_image_false_positive": 1, "images": 4,
                            "precision": 3 / 7, "recall": 1., "f1": .6, "negative_image_false_positive_rate": 1.}}
    better = copy.deepcopy(baseline)
    better["per_image"][2].update(predictions=[], true_positive=0, false_negative=1)
    better["per_image"][3].update(predictions=[], false_positive=0, negative_image_false_positive=False)
    better["metrics"] = {"true_positive": 2, "false_positive": 0, "false_negative": 1,
                         "negative_image": 1, "negative_image_false_positive": 0, "images": 4,
                         "precision": 1., "recall": 2 / 3, "f1": .8, "negative_image_false_positive_rate": 0.}
    return baseline, better


class BenchmarkTests(unittest.TestCase):
    def test_duplicate_and_background_predictions_are_false_positives(self):
        reference = [[0, 0, 10, 10]]
        box = {"xyxy": reference[0], "confidence": 0.9}
        positive = match_detections(reference, [box, box])
        negative = match_detections([], [box])
        missing = match_detections(reference, [])
        result = summarize([positive, negative, missing])
        self.assertEqual((result["true_positive"], result["false_positive"], result["false_negative"]), (1, 2, 1))
        self.assertEqual(result["negative_image_false_positive_rate"], 1)
        self.assertAlmostEqual(result["f1"], 0.4)

    def test_low_confidence_and_poor_localization_do_not_count_as_matches(self):
        result = match_detections([[0, 0, 10, 10]], [
            {"xyxy": [0, 0, 10, 10], "confidence": 0.399},
            {"xyxy": [0, 0, 20, 20], "confidence": 0.9}])
        self.assertEqual((result["true_positive"], result["false_positive"], result["false_negative"]), (0, 1, 1))
        self.assertIsNone(summarize([result])["negative_image_false_positive_rate"])

    def test_invalid_confidence_cannot_silently_improve_detection_metrics(self):
        for score in (float('nan'), float('inf'), -float('inf'), -0.01, 1.01, True):
            for references in ([], [[0, 0, 10, 10]]):
                with self.subTest(score=score, references=references):
                    with self.assertRaises(RecorderError):
                        match_detections(references, [{"xyxy": [0, 0, 10, 10], "confidence": score}])

    def test_candidate_selection_never_uses_test_or_incomparable_reports(self):
        baseline, better = selection_reports()
        self.assertEqual(select_candidate({"baseline": baseline, "new": better}), "new")
        self.assertEqual(select_candidate({"baseline": baseline, "tied": copy.deepcopy(baseline)}), "baseline")
        for key, value in [("split", "test"), ("dataset_id", "other"), ("confidence", 0.5),
                           ("nms_iou", 0.3),
                           ("per_image", [{"image_id": "different"}])]:
            invalid = {**better, key: value}
            with self.assertRaises(RecorderError):
                select_candidate({"baseline": baseline, "invalid": invalid})

    def test_optimizer_options_fail_closed(self):
        self.assertEqual(validate_training_options({"optimizer": "AdamW", "lr0": 0.0001, "freeze": 11})["freeze"], 11)
        self.assertEqual(validate_training_options({"freeze": 23})["freeze"], 23)
        for options in ([], {"lr0": 0.0001}, {"optimizer": "auto"}, {"device": "0"},
                        {"freeze": 24}, {"freeze": True}, {"optimizer": "AdamW", "lr0": float("nan")}):
            with self.assertRaises(RecorderError):
                validate_training_options(options)

    def test_candidate_selection_rejects_changed_or_missing_reference_boxes(self):
        baseline, candidate = selection_reports()
        for boxes in ([], [[0, 0, 20, 20]], None):
            candidate["per_image"][0]["reference_boxes"] = boxes
            with self.subTest(boxes=boxes):
                with self.assertRaises(RecorderError):
                    select_candidate({"baseline": baseline, "candidate": candidate})
        for report in (baseline, candidate):
            for row in report["per_image"]:
                del row["reference_boxes"]
        with self.assertRaises(RecorderError):
            select_candidate({"baseline": baseline, "candidate": candidate})

    def test_recall_guard_rejects_a_higher_f1_with_more_misses(self):
        report, candidate = selection_reports()
        self.assertEqual(select_candidate({"baseline": report, "new": candidate}), "new")
        self.assertEqual(select_candidate({"baseline": report, "new": candidate}, preserve_baseline_recall=True), "baseline")

    def test_candidate_selection_rejects_stale_aggregate_metrics(self):
        baseline, candidate = selection_reports()
        for key, value in (("f1", .99), ("recall", 1.), ("true_positive", 3),
                           ("negative_image_false_positive_rate", .2), ("images", 5)):
            invalid = copy.deepcopy(candidate)
            invalid["metrics"][key] = value
            with self.subTest(key=key):
                with self.assertRaises(RecorderError):
                    select_candidate({"baseline": baseline, "candidate": invalid})

    def test_candidate_selection_replays_predictions_instead_of_trusting_row_counts(self):
        baseline, candidate = selection_reports()
        # Counts and totals agree with one another, but this detection was removed.
        candidate["per_image"][0]["predictions"] = []
        with self.assertRaises(RecorderError):
            select_candidate({"baseline": baseline, "candidate": candidate})

    def test_candidate_selection_requires_prediction_evidence(self):
        baseline, candidate = selection_reports()
        for missing in (None, "missing"):
            invalid = copy.deepcopy(candidate)
            if missing is None:
                invalid["per_image"][0]["predictions"] = None
            else:
                del invalid["per_image"][0]["predictions"]
            with self.subTest(missing=missing):
                with self.assertRaises(RecorderError):
                    select_candidate({"baseline": baseline, "candidate": invalid})

    def test_repeated_images_cannot_reweight_candidate_selection(self):
        baseline, candidate = selection_reports()
        self.assertEqual(select_candidate({"baseline": baseline, "candidate": candidate}), "candidate")
        for report in (baseline, candidate):
            report["per_image"].extend(copy.deepcopy(report["per_image"][2]) for _ in range(5))
        baseline["metrics"].update(images=9, true_positive=8, precision=2 / 3, f1=.8)
        candidate["metrics"].update(images=9, false_negative=6, recall=.25, f1=.4)
        with self.assertRaises(RecorderError):
            select_candidate({"baseline": baseline, "candidate": candidate})

    def test_selection_requires_usable_image_identity(self):
        for identity in (None, True, [], "", " "):
            baseline, candidate = selection_reports()
            for report in (baseline, candidate):
                report["per_image"][0]["image_id"] = identity
            with self.subTest(identity=identity), self.assertRaises(RecorderError):
                select_candidate({"baseline": baseline, "candidate": candidate})


if __name__ == "__main__":
    unittest.main()
