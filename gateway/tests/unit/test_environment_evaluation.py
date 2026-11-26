"""Offline forecast evaluator checks, runnable without pytest or hardware."""
import copy
import hashlib
import json
import math
import unittest

from habitat.compute.environment_evaluation import CHANNELS, HORIZONS, evaluate_predictions


def window(name="one", *, split="test", source="sensor", baseline=None, target=None):
    return {
        "window_id": hashlib.sha256(name.encode()).hexdigest(),
        "split": split,
        "session_id": "session-1",
        "cage_id": "cage-A",
        "data_source": source,
        "origin_epoch": 1_800_000_000.0,
        "history": [list(baseline or [20, 50, 25, 18]) + [0] for _ in range(30)],
        "targets": [list(target or [22, 55, 28, 20]) for _ in range(60)],
        "future_executed_seconds": [0] * 60,
    }


def prediction(item, *, values=None, kind="prospective", model="model-1"):
    return {
        "window_id": item["window_id"],
        "model_id": model,
        "origin_epoch": item["origin_epoch"],
        "generated_at_epoch": item["origin_epoch"] + 1,
        "planned_seconds": [0] * 60,
        "prediction_kind": kind,
        "values": {str(h): list(values or [22, 55, 28, 20]) for h in HORIZONS},
    }


class EnvironmentEvaluationTests(unittest.TestCase):
    def test_known_metrics_and_same_sample_persistence(self):
        first = window()
        second = window("two", baseline=[24, 60, 29, 23], target=[26, 61, 30, 24])
        predictions = [prediction(first, values=[23, 53, 31, 18]),
                       prediction(second, values=[23, 65, 29, 28])]
        original = copy.deepcopy(([first, second], predictions))
        report = evaluate_predictions(iter([first, second]), iter(predictions))
        self.assertEqual(report["status"], "declared_prospective_evaluated")
        self.assertFalse(report["field_validated"])
        self.assertEqual(report["data_source"], "sensor")
        model = ([2, 3, 2, 3], [math.sqrt(5), math.sqrt(10), math.sqrt(5), math.sqrt(10)], [-1, 1, 1, 1])
        baseline = ([2, 3, 2, 1.5], [2, math.sqrt(13), math.sqrt(5), math.sqrt(2.5)], [-2, -3, -2, -1.5])
        for horizon in HORIZONS:
            result = report["modes"]["prospective"]["horizons"][str(horizon)]
            self.assertEqual(result["eligible_windows"], 2)
            self.assertEqual(result["excluded_action_mismatch"], 0)
            self.assertEqual(result["missing_predictions"], 0)
            for j, channel in enumerate(CHANNELS):
                for label, expected in (("model", model), ("persistence", baseline)):
                    for metric, array in zip(("mae", "rmse", "bias"), expected):
                        self.assertAlmostEqual(result["metrics"][channel][label][metric], array[j])
        self.assertEqual(([first, second], predictions), original)
        json.dumps(report, allow_nan=False)

    def test_targets_are_indexed_at_each_requested_horizon(self):
        item = window()
        pred = prediction(item)
        for horizon in HORIZONS:
            item["targets"][horizon - 1] = [horizon] * 4
            pred["values"][str(horizon)] = [horizon] * 4
        report = evaluate_predictions([item], [pred])
        for result in report["modes"]["prospective"]["horizons"].values():
            for channel in CHANNELS:
                self.assertEqual(result["metrics"][channel]["model"], {"mae": 0, "rmse": 0, "bias": 0})

    def test_action_change_excludes_that_horizon_and_later(self):
        items = [window(str(i), baseline=[20] * 4, target=[i + 21] * 4) for i in range(4)]
        items[0]["future_executed_seconds"][5] = 2
        items[1]["future_executed_seconds"][0] = 2
        report = evaluate_predictions(items, [prediction(w) for w in items[:3]])
        horizons = report["modes"]["prospective"]["horizons"]
        self.assertEqual(horizons["5"]["eligible_windows"], 2)
        self.assertEqual(horizons["5"]["excluded_action_mismatch"], 1)
        self.assertEqual(horizons["5"]["metrics"]["air_C"]["persistence"]["mae"], 2)
        for horizon in (10, 30, 60):
            result = horizons[str(horizon)]
            self.assertEqual(result["eligible_windows"], 1)
            self.assertEqual(result["excluded_action_mismatch"], 2)
            self.assertEqual(result["metrics"]["air_C"]["persistence"]["mae"], 3)
        for result in horizons.values():
            self.assertEqual(result["missing_predictions"], 1)

    def test_absolute_action_tolerance_and_no_eligible_report(self):
        item = window()
        pred = prediction(item)
        pred["planned_seconds"][0] = 1e-6
        accepted = evaluate_predictions([item], [pred])
        self.assertEqual(accepted["status"], "declared_prospective_evaluated")
        pred["planned_seconds"][0] = 2e-6
        rejected = evaluate_predictions([item], [pred])
        self.assertEqual(rejected["status"], "no_eligible_predictions")
        self.assertFalse(rejected["modes"]["prospective"]["prospective_evidence"])
        for result in rejected["modes"]["prospective"]["horizons"].values():
            self.assertEqual(result["eligible_windows"], 0)
            self.assertEqual(result["excluded_action_mismatch"], 1)
            for channel in CHANNELS:
                for label in ("model", "persistence"):
                    self.assertEqual(result["metrics"][channel][label], {"mae": None, "rmse": None, "bias": None})
        json.dumps(rejected, allow_nan=False)

    def test_prospective_issuance_boundaries_and_origin_identity(self):
        item = window()
        for seconds in (-0.5, 60.5):
            with self.subTest(seconds=seconds):
                pred = prediction(item)
                pred["generated_at_epoch"] = item["origin_epoch"] + seconds
                with self.assertRaisesRegex(ValueError, "issued outside"):
                    evaluate_predictions([item], [pred])
        for seconds in (0, 60):
            pred = prediction(item)
            pred["generated_at_epoch"] = item["origin_epoch"] + seconds
            self.assertEqual(evaluate_predictions([item], [pred])["status"], "declared_prospective_evaluated")
        pred["origin_epoch"] += 0.5
        with self.assertRaisesRegex(ValueError, "origin_epoch does not match"):
            evaluate_predictions([item], [pred])

    def test_retrospective_is_separate_and_never_prospective_evidence(self):
        item = window(source="simulation")
        retro = prediction(item, kind="retrospective_action_conditioned", model="model-retro")
        retro["generated_at_epoch"] += 3600
        report = evaluate_predictions([item], [retro])
        self.assertEqual(report["status"], "retrospective_only")
        self.assertFalse(report["field_validated"])
        self.assertEqual(report["data_source"], "simulation")
        self.assertEqual(report["modes"]["prospective"]["status"], "no_predictions")
        self.assertFalse(report["modes"]["retrospective_action_conditioned"]["prospective_evidence"])
        self.assertEqual(report["modes"]["retrospective_action_conditioned"]["issuance_provenance"],
                         "retrospective_declared")
        both = evaluate_predictions([item], [prediction(item), retro])
        self.assertEqual(both["prediction_count"], 2)
        self.assertEqual(both["modes"]["prospective"]["model_id"], "model-1")
        self.assertEqual(both["modes"]["retrospective_action_conditioned"]["model_id"], "model-retro")
        retro["planned_seconds"][0] = 1
        mismatch = evaluate_predictions([item], [retro])
        self.assertEqual(mismatch["status"], "no_eligible_predictions")

    def test_backdated_perfect_answers_never_establish_prospective_evidence(self):
        item = window()
        pred = prediction(item)
        # A caller can copy observed future targets and claim an earlier issue
        # time. Valid dimensions and perfect scores cannot authenticate it.
        pred["values"] = {str(h): list(item["targets"][h - 1]) for h in HORIZONS}
        pred["generated_at_epoch"] = item["origin_epoch"]
        report = evaluate_predictions([item], [pred])
        self.assertEqual(report["status"], "declared_prospective_evaluated")
        self.assertFalse(report["field_validated"])
        self.assertEqual(report["modes"]["prospective"]["issuance_provenance"],
                         "caller_declared_unverified")
        for mode in report["modes"].values():
            self.assertFalse(mode["prospective_evidence"])
        for result in report["modes"]["prospective"]["horizons"].values():
            self.assertEqual(result["eligible_windows"], 1)
            for channel in CHANNELS:
                self.assertEqual(result["metrics"][channel]["model"]["mae"], 0)

    def test_duplicate_unknown_window_and_multiple_models_are_rejected(self):
        first, second = window(), window("two")
        pred = prediction(first)
        cases = (
            ([first, first], [pred], "duplicate window"),
            ([first], [prediction(second)], "unknown window"),
            ([first], [pred, pred], "duplicate prediction"),
            ([first, second], [pred, prediction(second, model="different")], "multiple model"),
        )
        for windows, predictions, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                evaluate_predictions(windows, predictions)

    def test_selected_split_counts_and_empty_submission_errors(self):
        selected, other = window(), window("other", split="train")
        report = evaluate_predictions([selected, other], [prediction(selected), prediction(other)])
        self.assertEqual(report["window_count"], 1)
        self.assertEqual(report["excluded_other_split_windows"], 1)
        self.assertEqual(report["prediction_count"], 1)
        self.assertEqual(report["ignored_other_split_predictions"], 1)
        for windows, predictions in (([], []), ([other], [prediction(other)]),
                                     ([selected], []), ([selected, other], [prediction(other)])):
            with self.subTest(windows=len(windows), predictions=len(predictions)), self.assertRaises(ValueError):
                evaluate_predictions(windows, predictions)
        with self.assertRaisesRegex(ValueError, "split must be"):
            evaluate_predictions([selected], [prediction(selected)], split="all")

    def test_sources_cannot_be_mixed_even_across_splits(self):
        sensor, simulation = window(), window("sim", split="train", source="simulation")
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            evaluate_predictions([sensor, simulation], [prediction(sensor)])

    def test_dimensions_horizons_durations_and_record_identity_are_strict(self):
        cases = (
            ("history", lambda w, p: w["history"].pop()),
            ("history columns", lambda w, p: w["history"][0].pop()),
            ("targets", lambda w, p: w["targets"].pop()),
            ("future actions", lambda w, p: w["future_executed_seconds"].pop()),
            ("planned actions", lambda w, p: p["planned_seconds"].pop()),
            ("prediction values", lambda w, p: p["values"]["5"].pop()),
            ("missing horizon", lambda w, p: p["values"].pop("5")),
            ("extra horizon", lambda w, p: p["values"].update({"15": [0] * 4})),
            ("negative history duration", lambda w, p: w["history"][0].__setitem__(4, -1)),
            ("negative execution", lambda w, p: w["future_executed_seconds"].__setitem__(0, -1)),
            ("negative planned duration", lambda w, p: p["planned_seconds"].__setitem__(0, -1)),
            ("missing field", lambda w, p: p.pop("model_id")),
            ("invalid sha", lambda w, p: w.update(window_id="not-sha256")),
            ("invalid kind", lambda w, p: p.update(prediction_kind="forecast")),
            ("blank model", lambda w, p: p.update(model_id=" ")),
        )
        for label, mutate in cases:
            item = window()
            pred = prediction(item)
            mutate(item, pred)
            with self.subTest(label=label), self.assertRaises(ValueError):
                evaluate_predictions([item], [pred])

    def test_nonfinite_and_boolean_numbers_are_rejected(self):
        for invalid in (float("nan"), float("inf"), float("-inf"), True, "20"):
            for location in ("history", "targets", "values", "issued", "origin", "actions"):
                item = window()
                pred = prediction(item)
                if location == "history":
                    item["history"][0][0] = invalid
                elif location == "targets":
                    item["targets"][0][0] = invalid
                elif location == "values":
                    pred["values"]["5"][0] = invalid
                elif location == "issued":
                    pred["generated_at_epoch"] = invalid
                elif location == "origin":
                    item["origin_epoch"] = invalid
                else:
                    item["future_executed_seconds"][0] = invalid
                with self.subTest(invalid=invalid, location=location), self.assertRaises(ValueError):
                    evaluate_predictions([item], [pred])
        item = window(target=[-1e308] * 4)
        with self.assertRaisesRegex(ValueError, "non-finite residual"):
            evaluate_predictions([item], [prediction(item, values=[1e308] * 4)])


if __name__ == "__main__":
    unittest.main()
