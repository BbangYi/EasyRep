import json
import tempfile
import unittest
from pathlib import Path

from behavior_recorder.core import RecorderError
from behavior_recorder.core import atomic_json, read_json
from behavior_recorder.behavior_classifier import examples_from_windows, evaluate, fit, predict
from behavior_recorder.cli import parser, run


def window(identifier, start, end, speed, moving_fraction, recording):
    return {
        "window_id": identifier,
        "start_seconds": start,
        "end_seconds": end,
        "recording_id": recording,
        "source_sha256": recording * 16,
        "quality": "usable",
        "features": {
            "speed": speed,
            "moving_fraction": moving_fraction,
            "x_span": speed / 2,
            "y_span": speed / 4,
        },
        "scope": {"animal_id": "crest-01"},
    }


def label(identifier, behavior, start, end, *, visibility="visible", certainty="certain"):
    return {
        "label_id": identifier,
        "clip_id": "clip-01",
        "animal_id": "crest-01",
        "start_seconds": start,
        "end_seconds": end,
        "behavior": behavior,
        "visibility": visibility,
        "certainty": certainty,
    }


class BehaviorClassifierTests(unittest.TestCase):
    def test_only_full_certain_visible_labels_create_training_examples(self):
        result = examples_from_windows(
            [window("w-moving", 0, 5, .8, .9, "run-a"),
             window("w-unlabelled", 5, 10, .1, .1, "run-a"),
             window("w-hidden", 10, 15, .1, .1, "run-a")],
            [label("moving", "moving", 0, 5),
             label("partial", "resting", 6, 10),
             label("hidden", None, 10, 15, visibility="unobservable")],
            clip_id="clip-01", dataset_kind="test",
        )
        self.assertEqual([row["behavior"] for row in result["rows"]], ["moving"])
        self.assertEqual(result["excluded"], {
            "no_full_certain_visible_label": ["w-unlabelled"],
            "ambiguous_or_unobservable_label": ["w-hidden"],
        })

    def test_fit_predict_and_evaluate_hold_out_whole_recordings(self):
        training = [
            {**window("r1-rest", 0, 5, .04, .05, "run-1"), "behavior": "resting", "group_id": "run-1"},
            {**window("r2-rest", 0, 5, .08, .10, "run-2"), "behavior": "resting", "group_id": "run-2"},
            {**window("r3-move", 0, 5, .80, .85, "run-3"), "behavior": "moving", "group_id": "run-3"},
            {**window("r4-move", 0, 5, .95, .90, "run-4"), "behavior": "moving", "group_id": "run-4"},
        ]
        held_out = [
            {**window("r5-rest", 0, 5, .06, .08, "run-5"), "behavior": "resting", "group_id": "run-5"},
            {**window("r6-move", 0, 5, .88, .88, "run-6"), "behavior": "moving", "group_id": "run-6"},
        ]
        model = fit(training, dataset_kind="test")
        predictions = predict(model, held_out)
        self.assertEqual([row["predicted_behavior"] for row in predictions["rows"]], ["resting", "moving"])
        report = evaluate(model, held_out)
        self.assertEqual(report["counts"], {"correct": 2, "incorrect": 0, "abstained": 0})
        self.assertEqual(report["evaluation_groups"], ["run-5", "run-6"])

    def test_evaluation_rejects_recording_seen_during_training(self):
        training = [
            {**window("r1-rest", 0, 5, .04, .05, "run-1"), "behavior": "resting", "group_id": "run-1"},
            {**window("r2-rest", 0, 5, .08, .10, "run-2"), "behavior": "resting", "group_id": "run-2"},
            {**window("r3-move", 0, 5, .80, .85, "run-3"), "behavior": "moving", "group_id": "run-3"},
            {**window("r4-move", 0, 5, .95, .90, "run-4"), "behavior": "moving", "group_id": "run-4"},
        ]
        model = fit(training, dataset_kind="test")
        with self.assertRaisesRegex(RecorderError, "overlap"):
            evaluate(model, [{**window("leak", 5, 10, .06, .08, "run-1"), "behavior": "resting", "group_id": "run-1"}])

    def test_unobservable_window_is_withheld_not_called_resting(self):
        training = [
            {**window("r1-rest", 0, 5, .04, .05, "run-1"), "behavior": "resting", "group_id": "run-1"},
            {**window("r2-rest", 0, 5, .08, .10, "run-2"), "behavior": "resting", "group_id": "run-2"},
            {**window("r3-move", 0, 5, .80, .85, "run-3"), "behavior": "moving", "group_id": "run-3"},
            {**window("r4-move", 0, 5, .95, .90, "run-4"), "behavior": "moving", "group_id": "run-4"},
        ]
        model = fit(training, dataset_kind="test")
        hidden = {**window("hidden", 0, 5, .0, .0, "run-5"), "group_id": "run-5",
                  "quality": "unobservable", "features": None}
        prediction = predict(model, [hidden])["rows"][0]
        self.assertEqual(prediction["status"], "unobserved")
        self.assertIsNone(prediction["predicted_behavior"])
        self.assertIsNone(prediction["distance"])

    def test_cli_writes_model_then_group_held_out_evaluation(self):
        training = [
            {**window("r1-rest", 0, 5, .04, .05, "run-1"), "behavior": "resting", "group_id": "run-1"},
            {**window("r2-rest", 0, 5, .08, .10, "run-2"), "behavior": "resting", "group_id": "run-2"},
            {**window("r3-move", 0, 5, .80, .85, "run-3"), "behavior": "moving", "group_id": "run-3"},
            {**window("r4-move", 0, 5, .95, .90, "run-4"), "behavior": "moving", "group_id": "run-4"},
        ]
        held_out = [
            {**window("r5-rest", 0, 5, .06, .08, "run-5"), "behavior": "resting", "group_id": "run-5"},
            {**window("r6-move", 0, 5, .88, .88, "run-6"), "behavior": "moving", "group_id": "run-6"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train_path, held_path = root / "train.json", root / "held.json"
            model_path, report_path = root / "model.json", root / "report.json"
            atomic_json(train_path, {"dataset_kind": "test", "rows": training})
            atomic_json(held_path, {"dataset_kind": "test", "rows": held_out})
            result = run(parser().parse_args(["behavior-fit", str(train_path), str(model_path)]))
            self.assertEqual(result["status"], "synthetic_pipeline_only")
            self.assertEqual(read_json(model_path)["kind"], "tracked_behavior_centroid_classifier")
            report = run(parser().parse_args(["behavior-evaluate", str(model_path), str(held_path), str(report_path)]))
            self.assertEqual(report["counts"], {"correct": 2, "incorrect": 0, "abstained": 0})
            self.assertEqual(read_json(report_path)["evaluation_groups"], ["run-5", "run-6"])

    def test_cli_builds_examples_from_windows_and_active_labels(self):
        windows = [window("w-moving", 0, 5, .8, .9, "run-a")]
        labels = [label("active", "moving", 0, 5),
                  {**label("replaced", "resting", 0, 5), "supersedes": "active"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            windows_path, labels_path, output_path = root / "windows.json", root / "labels.jsonl", root / "examples.json"
            atomic_json(windows_path, {"windows": windows})
            labels_path.write_text("".join(json.dumps(row) + "\n" for row in labels), encoding="utf-8")
            result = run(parser().parse_args([
                "behavior-examples", str(windows_path), str(labels_path), "clip-01", str(output_path),
                "--dataset-kind", "test",
            ]))
            self.assertEqual(result["rows"], 1)
            self.assertEqual(read_json(output_path)["rows"][0]["behavior"], "resting")


if __name__ == "__main__":
    unittest.main()
