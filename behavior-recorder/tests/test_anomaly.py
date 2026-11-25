import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from behavior_recorder.ai import main
from behavior_recorder.analysis_features import build_dataset, extract_clip, fingerprint, load_dataset, review_window, save_artifact, sensor_feature, validate_dataset
from behavior_recorder.anomaly import apply_persistence, evaluate, fit, predict
from behavior_recorder.core import RecorderError, Session, digest, read_json

ROOT = Path(__file__).resolve().parents[1]


def reseal(dataset):
    dataset["dataset_id"] = fingerprint({k: v for k, v in dataset.items() if k != "dataset_id"})
    return dataset


class AnomalyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "demo"
        spec = importlib.util.spec_from_file_location("make_anomaly_demo", ROOT / "examples/make_anomaly_demo.py")
        cls.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.generator)
        cls.generator.run(cls.root)
        cls.training = load_dataset(cls.root / "training.features.json")
        cls.calibration = load_dataset(cls.root / "calibration.features.json")
        cls.test = load_dataset(cls.root / "test.features.json")
        cls.model = read_json(cls.root / "model.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_video_training_inference_evaluation(self):
        self.assertEqual(len(self.training["rows"]), 24)
        self.assertEqual(self.model["training"]["normal_windows"], 24)
        self.assertEqual(self.model["status"], "synthetic_pipeline_only")
        result = predict(self.model, self.test)
        self.assertGreater(len(result["alerts"]), 0)
        self.assertTrue(all(a["original_video_id"].startswith("sha256:") for a in result["alerts"]))
        report = evaluate(self.model, self.test)
        self.assertEqual(report["leakage_check"], "passed")
        self.assertTrue(report["chronology_checked"])
        self.assertGreater(report["model"]["detected_episodes"], 0)
        self.assertFalse(report["production_validated"])
        self.assertIn("fixed_motion_baseline", report)

    def test_empty_or_unreviewed_data_cannot_train(self):
        for case in ("empty", "unreviewed"):
            data = copy.deepcopy(self.training)
            if case == "empty":
                data["rows"] = []
            else:
                for row in data["rows"]:
                    row["human_assessment"] = None
                    row["review_label_ids"] = []
            with self.subTest(case=case), self.assertRaisesRegex(RecorderError, "insufficient reviewed"):
                fit(reseal(data), self.calibration)

    def test_anomalies_never_fit_normal_center(self):
        data = copy.deepcopy(self.training)
        for row in data["rows"][:4]:
            row["human_assessment"] = "anomaly"
            row["features"]["motion_mean"] = 1.0
        model = fit(reseal(data), self.calibration)
        self.assertEqual(model["training"]["normal_windows"], 20)
        self.assertLess(model["parameters"]["motion_mean"]["center"], 0.1)

    def test_calibration_never_refits_center(self):
        data = copy.deepcopy(self.calibration)
        for row in data["rows"]:
            row["features"]["motion_mean"] = 0.5
        model = fit(self.training, reseal(data))
        self.assertEqual(model["parameters"], self.model["parameters"])
        self.assertGreater(model["threshold"], self.model["threshold"])

    def test_all_source_groups_block_leakage(self):
        for key in ("session_id", "recording_id", "original_video_id"):
            data = copy.deepcopy(self.test)
            data["rows"][0][key] = self.training["rows"][0][key]
            with self.subTest(key=key), self.assertRaisesRegex(RecorderError, "data leakage"):
                evaluate(self.model, reseal(data))
        with self.assertRaisesRegex(RecorderError, "data leakage"):
            fit(self.training, self.training)

    def test_time_order_is_enforced(self):
        data = copy.deepcopy(self.test)
        for row in data["rows"]:
            row["observed_start"] = "2025-01-01T00:00:00Z"
            row["observed_end"] = "2025-01-01T00:00:01Z"
        with self.assertRaisesRegex(RecorderError, "chronology"):
            evaluate(self.model, reseal(data))

    def test_real_data_requires_known_time(self):
        training, calibration = copy.deepcopy(self.training), copy.deepcopy(self.calibration)
        for dataset in (training, calibration):
            dataset["dataset_kind"] = "real"
            for row in dataset["rows"]:
                row.update(provenance="real_camera", observed_start=None, observed_end=None)
            reseal(dataset)
        with self.assertRaisesRegex(RecorderError, "capture timestamps"):
            fit(training, calibration)

    def test_real_test_provenance_and_scope_cannot_mix(self):
        data = copy.deepcopy(self.test)
        data["dataset_kind"] = "real"
        for row in data["rows"]:
            row["provenance"] = "real_camera"
        with self.assertRaisesRegex(RecorderError, "test model and real"):
            predict(self.model, reseal(data))
        for key, value in (("animal_id", "different-animal"), ("placement_revision", "new-placement"), ("context", "night")):
            data = copy.deepcopy(self.test)
            data["scope"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RecorderError, "scope mismatch"):
                predict(self.model, reseal(data))

    def test_missing_features_abstain_and_count_missed_episode(self):
        data = copy.deepcopy(self.test)
        for row in data["rows"]:
            if row["human_assessment"] == "anomaly":
                row["features"]["motion_mean"] = None
                row["quality_reasons"] = ["insufficient_frames"]
        result = predict(self.model, reseal(data))
        unavailable = [r for r in result["predictions"] if r["human_assessment"] == "anomaly"]
        self.assertTrue(all(r["status"] == "insufficient_data" and r["score"] is None for r in unavailable))
        report = evaluate(self.model, data)["model"]
        self.assertEqual(report["abstained_windows"], 8)
        self.assertEqual(report["event_recall"], 0)
        self.assertIsNone(report["window_recall"])

    def test_artifact_hash_and_duplicate_original_guard(self):
        data = copy.deepcopy(self.test)
        data["rows"][0]["features"]["motion_mean"] = 0.1
        with self.assertRaisesRegex(RecorderError, "fingerprint"):
            predict(self.model, data)
        data = copy.deepcopy(self.test)
        copy_row = copy.deepcopy(data["rows"][0])
        copy_row.update(row_id="different-row", session_id="another-session", clip_id="another-clip")
        data["rows"].append(copy_row)
        with self.assertRaisesRegex(RecorderError, "duplicate original"):
            validate_dataset(reseal(data))
        model = copy.deepcopy(self.model)
        model["threshold"] = 0
        with self.assertRaisesRegex(RecorderError, "model fingerprint"):
            predict(model, self.test)

    def test_preprocessing_cannot_change_at_inference(self):
        data = copy.deepcopy(self.test)
        data["config"]["sample_fps"] = 2
        with self.assertRaisesRegex(RecorderError, "preprocessing"):
            predict(self.model, reseal(data))

    def test_human_review_requires_full_certain_coverage(self):
        row = {"label_id": "review", "animal_id": "a", "start_seconds": 0, "end_seconds": 2,
               "assessment": "normal", "certainty": "certain", "visibility": "visible"}
        self.assertEqual(review_window([row], "a", 0, 2)[0], "normal")
        self.assertIsNone(review_window([row], "a", 0, 3)[0])
        self.assertIsNone(review_window([{**row, "certainty": "uncertain"}], "a", 0, 2)[0])
        self.assertIn("human_visibility_incomplete", review_window([{**row, "visibility": "unobservable"}], "a", 0, 2)[1])
        self.assertIn("conflicting_human_assessments", review_window([row, {**row, "assessment": "anomaly"}], "a", 0, 2)[1])

    def test_persistence_resets_at_gap_clip_or_abstention(self):
        base = {"session_id": "s", "recording_id": "r", "original_video_id": "o", "clip_id": "c", "status": "elevated"}
        rows = [{**base, "row_id": str(i), "start_seconds": i, "end_seconds": i + 1} for i in range(4)]
        rows[1]["status"] = "insufficient_data"
        rows[3]["clip_id"] = "other"
        self.assertEqual(apply_persistence(rows, 2), [])
        self.assertNotIn("alert", [r["status"] for r in rows])
        contiguous = [{**base, "row_id": str(i), "start_seconds": i, "end_seconds": i + 1} for i in range(3)]
        alerts = apply_persistence(contiguous, 2)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["trigger_seconds"], 2)
        self.assertEqual(alerts[0]["end_seconds"], 3)

    def test_sensor_join_preserves_clock_quality_revision_and_no_future(self):
        config = {"max_clock_error_ms": 500}
        sensor = {"sensor_id": "T1", "unit": "degC", "max_age_seconds": 10, "geometry_revision": 1, "placement_revision": 2}
        clip = {"enclosure_id": "e", "capture_clock": {"accuracy_ms": 100}}
        target = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
        row = {"record_id": "r", "enclosure_id": "e", "observed_at": "2026-01-01T00:00:00Z",
               "observed_clock": {"accuracy_ms": 100}, "geometry_revision": 1, "placement_revision": 2,
               "readings": [{"sensor_id": "T1", "value": 23, "unit": "degC", "quality": "valid"}]}
        self.assertEqual(sensor_feature([row], sensor, clip, target, config), (23, "r", None))
        for update, expected in (({"placement_revision": 3}, "sensor_revision_mismatch"), ({"observed_at": "2025-12-31T23:59:00Z"}, "sensor_stale"),
                                 ({"observed_clock": {"accuracy_ms": None}}, "clock_alignment_unverified"), ({"observed_at": "2026-01-01T00:00:06Z"}, "sensor_missing")):
            self.assertEqual(sensor_feature([{**row, **update}], sensor, clip, target, config)[2], expected)
        invalid = {**row, "record_id": "bad", "observed_at": "2026-01-01T00:00:04Z", "readings": [{"sensor_id": "T1", "value": None, "unit": "degC", "quality": "disconnected"}]}
        self.assertEqual(sensor_feature([row, invalid], sensor, clip, target, config)[2], "sensor_invalid")
        self.assertEqual(sensor_feature([row], sensor, clip, None, config)[2], "capture_time_unknown")

    def test_features_and_model_survive_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            copied = destination / "session-moved"
            shutil.copytree(self.root / "sessions/synthetic-4", copied)
            config = read_json(self.root / "features.config.json")
            before = build_dataset([self.root / "sessions/synthetic-4"], config)
            after = build_dataset([copied], config)
            self.assertEqual(before["dataset_id"], after["dataset_id"])
            self.assertEqual(predict(self.model, before), predict(self.model, after))
            with self.assertRaisesRegex(RecorderError, "duplicate session"):
                build_dataset([copied, self.root / "sessions/synthetic-4"], config)

    def test_blackout_and_incomplete_frames_abstain(self):
        session = Session(self.root / "sessions/synthetic-4")
        clip = next(session.items("clip"))
        config = read_json(self.root / "features.config.json")
        with patch("behavior_recorder.analysis_features.decode_frames", return_value=[bytes(64 * 48)] * 48):
            rows = extract_clip(session, clip, config, [], [])
        self.assertTrue(all("exposure_out_of_range" in r["quality_reasons"] for r in rows))
        with patch("behavior_recorder.analysis_features.decode_frames", return_value=[]):
            rows = extract_clip(session, clip, config, [], [])
        self.assertTrue(all("insufficient_frames" in r["quality_reasons"] for r in rows))

    def test_calibration_size_and_versioned_output_guards(self):
        data = copy.deepcopy(self.calibration)
        data["rows"] = data["rows"][:10]
        with self.assertRaisesRegex(RecorderError, "insufficient independent"):
            fit(self.training, reseal(data))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            save_artifact(path, {"original": True})
            with self.assertRaisesRegex(RecorderError, "already exists"):
                save_artifact(path, {"original": False})
            self.assertEqual(read_json(path), {"original": True})

    def test_upsampled_source_frames_are_not_new_observations(self):
        session = Session(self.root / "sessions/synthetic-4")
        clip = {**next(session.items("clip")), "frame_count": 12}
        config = read_json(self.root / "features.config.json")
        with patch("behavior_recorder.analysis_features.decode_frames", return_value=[bytes([100]) * (64 * 48)] * 48):
            rows = extract_clip(session, clip, config, [], [])
        self.assertTrue(all("source_sampling_below_requested_rate" in r["quality_reasons"] for r in rows))

    def test_cli_train_infer_evaluate_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("sys.stdout", io.StringIO()):
                self.assertEqual(main(["train", "--training", str(self.root / "training.features.json"), "--calibration", str(self.root / "calibration.features.json"), "--output", str(root / "model.json")]), 0)
                model_hash = digest(root / "model.json")
                self.assertEqual(main(["infer", "--model", str(root / "model.json"), "--data", str(self.root / "test.features.json"), "--output", str(root / "predictions.json")]), 0)
                self.assertEqual(main(["evaluate", "--model", str(root / "model.json"), "--data", str(self.root / "test.features.json"), "--output", str(root / "evaluation.json")]), 0)
                self.assertEqual(digest(root / "model.json"), model_hash)
            with patch("sys.stderr", io.StringIO()):
                self.assertEqual(main(["infer", "--model", str(root / "model.json"), "--data", str(self.root / "test.features.json"), "--output", str(root / "predictions.json")]), 1)


if __name__ == "__main__":
    unittest.main()
