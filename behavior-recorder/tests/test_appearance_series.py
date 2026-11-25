"""Synthetic record integrity checks; no camera, pixels, model or device access."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from behavior_recorder.analysis_features import fingerprint
from behavior_recorder.appearance import collect
from behavior_recorder.appearance_series import build_series, write_series
from behavior_recorder.core import RecorderError


class AppearanceSeriesTests(unittest.TestCase):
    def setUp(self):
        # Preserve fixtures for inspection; never remove existing user files.
        self.root = Path(tempfile.mkdtemp(prefix="easyrep-appearance-series-"))
        self.manifest = {"schema_version": 1, "kind": "appearance_series", "dataset_kind": "test",
                         "animal_id": "fixture-animal", "species": "crested_gecko",
                         "enclosure_id": "fixture-enclosure", "records": []}

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def event(self, record_id, stage, earliest, latest):
        metadata = {key: self.manifest[key] for key in (
            "schema_version", "dataset_kind", "animal_id", "species", "enclosure_id")}
        metadata.update(kind="shedding_event", record_id=record_id, stage=stage,
                        earliest_at=earliest, latest_at=latest, observer="fixture-reviewer",
                        evidence_reference="synthetic fixture, not a biological observation")
        source = self.save(record_id + "-input.json", metadata)
        output = self.root / (record_id + ".json")
        result = collect(source, output)
        self.manifest["records"].append(output.name)
        return result

    def color(self, record_id, observed_at, revision="camera-v1", wet=False, image_hash=None):
        metadata = {key: self.manifest[key] for key in (
            "schema_version", "dataset_kind", "animal_id", "species", "enclosure_id")}
        metadata.update(kind="color_observation", record_id=record_id, observed_at=observed_at,
                        image="rgb.png", mask="skin.png", body_region="dorsal",
                        capture={"camera_id": "fixture-camera", "camera_revision": revision,
                                 "mode": "visible_rgb", "color_space": "sRGB",
                                 "illumination_revision": "light-v1", "settings_revision": "settings-v1",
                                 "reference_revision": "reference-v1", "exposure_locked": True,
                                 "white_balance_locked": True},
                        review={"observer": "fixture-reviewer", "identity_confirmed": True,
                                "skin_only": True, "dry": not wet, "sharp": True})
        result = {"schema_version": 1, "feature_version": "reviewed-srgb-v1",
                  "created_at": "2026-11-01T00:00:00Z", "metadata": metadata,
                  "metadata_sha256": fingerprint(metadata), "shedding_prediction": None,
                  "actuation_allowed": False, "evidence": "synthetic artifact, no pixels processed",
                  "status": "excluded" if wet else "measured",
                  "reasons": ["dry_not_confirmed"] if wet else [],
                  "features": None if wet else {"selected_pixels": 64, "rgb_median": [80, 90, 100]},
                  "comparison_group": None if wet else fingerprint({key: metadata[key] for key in (
                      "dataset_kind", "animal_id", "species", "enclosure_id", "body_region", "capture")}),
                  "files": {"image": {"path": "rgb.png", "bytes": 100, "sha256": image_hash or fingerprint(record_id)},
                            "mask": {"path": "skin.png", "bytes": 80, "sha256": "a" * 64}}}
        self.save(record_id + ".json", result)
        self.manifest["records"].append(record_id + ".json")
        return result

    def report(self):
        return build_series(self.save("series.json", self.manifest))

    def test_empty_series_reports_missing_observations_without_predictions(self):
        result = self.report()
        self.assertEqual(result["counts"], {"records": 0, "measured": 0, "excluded": 0,
                                           "started": 0, "completed": 0, "uncertain": 0})
        self.assertIn("no_measured_color_observations", result["missing_evidence"])
        self.assertIn("no_confirmed_shedding_start", result["missing_evidence"])
        self.assertIsNone(result["shedding_prediction"])
        self.assertFalse(result["actuation_allowed"])
        self.assertEqual(result["training_readiness"], "not_assessed")

    def test_chronology_uses_timezones_and_keeps_conditions_and_uncertainty_separate(self):
        self.color("b", "2026-11-01T04:00:00Z", revision="camera-v2")
        self.color("a", "2026-11-01T12:00:00+09:00")
        self.color("wet", "2026-11-01T05:00:00Z", wet=True)
        self.event("uncertain", "uncertain", "2026-11-02T01:00:00Z", "2026-11-03T01:00:00Z")
        self.event("started", "started", "2026-11-04T01:00:00Z", "2026-11-04T02:00:00Z")
        self.event("completed", "completed", "2026-11-05T01:00:00Z", "2026-11-05T02:00:00Z")
        result = self.report()
        self.assertEqual([r["record_id"] for r in result["records"]],
                         ["a", "b", "wet", "uncertain", "started", "completed"])
        self.assertEqual(result["counts"], {"records": 6, "measured": 2, "excluded": 1,
                                           "started": 1, "completed": 1, "uncertain": 1})
        self.assertEqual(len(result["comparison_groups"]), 2)
        self.assertEqual(result["excluded_reasons"], {"dry_not_confirmed": 1})
        self.assertEqual(result["records"][3]["latest_at"], "2026-11-03T01:00:00Z")
        self.assertEqual(result["cycle_pairing"], "not_performed")
        self.assertEqual(result["training_readiness"], "not_assessed")

    def test_other_animal_species_enclosure_and_test_real_mixing_are_rejected(self):
        self.event("e", "completed", "2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z")
        for field, other in [("animal_id", "other"), ("species", "leopard_gecko"),
                             ("enclosure_id", "other"), ("dataset_kind", "real")]:
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                manifest[field] = other
                with self.assertRaises(RecorderError):
                    build_series(self.save("other.json", manifest))

    def test_duplicate_paths_ids_and_relabelled_frame_do_not_inflate_counts(self):
        first = self.color("a", "2026-11-01T00:00:00Z", image_hash="b" * 64)
        self.manifest["records"].append("a.json")
        with self.assertRaises(RecorderError):
            self.report()
        self.manifest["records"][-1] = "copy.json"
        self.save("copy.json", first)
        with self.assertRaises(RecorderError):
            self.report()
        self.manifest["records"].pop()
        self.color("b", "2026-11-02T00:00:00Z", image_hash="b" * 64)
        with self.assertRaises(RecorderError):
            self.report()

    def test_tampered_or_inconsistent_artifacts_are_rejected(self):
        original = self.color("a", "2026-11-01T00:00:00Z")
        mutations = [("metadata_sha256", "0" * 64), ("comparison_group", "0" * 64),
                     ("status", "excluded"), ("reasons", ["dry_not_confirmed"]),
                     ("shedding_prediction", 0.8), ("actuation_allowed", True),
                     ("feature_version", "unknown"), ("files", {}), ("features", None)]
        for key, value in mutations:
            with self.subTest(key=key):
                artifact = copy.deepcopy(original)
                artifact[key] = value
                self.save("a.json", artifact)
                with self.assertRaises(RecorderError):
                    self.report()

    def test_excluded_colors_cannot_supply_features(self):
        artifact = self.color("wet", "2026-11-01T00:00:00Z", wet=True)
        artifact["features"] = {"rgb_median": [1, 2, 3]}
        self.save("wet.json", artifact)
        with self.assertRaises(RecorderError):
            self.report()

    def test_missing_unsafe_and_symlink_paths_are_rejected(self):
        self.save("target.json", {})
        (self.root / "linked.json").symlink_to(self.root / "target.json")
        for name in ["../outside.json", "/tmp/outside.json", "linked.json", "missing.json"]:
            with self.subTest(name=name):
                self.manifest["records"] = [name]
                with self.assertRaises((RecorderError, OSError)):
                    self.report()

    def test_manifest_identity_and_bounded_record_count_are_required(self):
        for change in [{"animal_id": None}, {"species": None}, {"records": "a.json"},
                       {"records": ["a.json"] * 513}]:
            with self.subTest(change=list(change)):
                manifest = {**self.manifest, **change}
                with self.assertRaises(RecorderError):
                    build_series(self.save("invalid.json", manifest))

    def test_cli_publishes_once_and_preserves_source_and_existing_output(self):
        self.event("event", "uncertain", "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")
        source = self.save("series.json", self.manifest)
        original = source.read_bytes()
        output = self.root / "report.json"
        command = [sys.executable, "-m", "behavior_recorder.appearance_series",
                   "--manifest", str(source), "--output", str(output)]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        first = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = output.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(output.read_bytes(), saved)
        self.assertEqual(source.read_bytes(), original)
        result = json.loads(saved)
        self.assertEqual(result["counts"]["uncertain"], 1)
        self.assertEqual(len(result["records"][0]["artifact_sha256"]), 64)
        self.assertIsNone(result["shedding_prediction"])
        with self.assertRaises(RecorderError):
            write_series(source, source)


if __name__ == "__main__":
    unittest.main()
