"""Offline color collection must not turn uncertain pixels into shedding advice."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("PIL") and importlib.util.find_spec("numpy"), "requires vision environment")
class AppearanceTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        image = Image.new("RGB", (16, 16), (0, 0, 255))
        image.paste((120, 60, 30), (0, 0, 8, 8))
        image.save(self.root / "image.png")
        mask = Image.new("L", (16, 16), 0)
        mask.paste(255, (0, 0, 8, 8))
        mask.save(self.root / "mask.png")
        self.row = {
            "schema_version": 1, "kind": "color_observation", "dataset_kind": "test",
            "record_id": "sample-01", "animal_id": "fixture-animal", "species": "crested_gecko",
            "enclosure_id": "fixture-enclosure", "observed_at": "2026-10-29T01:00:00+00:00",
            "image": "image.png", "mask": "mask.png", "body_region": "dorsal",
            "capture": {"camera_id": "cam-1", "camera_revision": "mount-1", "mode": "visible_rgb",
                        "color_space": "sRGB", "illumination_revision": "day-1", "settings_revision": "fixed-1",
                        "reference_revision": "gray-card-1", "exposure_locked": True, "white_balance_locked": True},
            "review": {"observer": "fixture-reviewer", "identity_confirmed": True,
                       "skin_only": True, "dry": True, "sharp": True},
        }

    def run_cli(self, row=None, name="result.json"):
        import sys
        source = self.root / "input.json"
        source.write_text(json.dumps(self.row if row is None else row))
        output = self.root / name
        result = subprocess.run([sys.executable, "-m", "behavior_recorder.appearance",
                                 "--input", str(source), "--output", str(output)],
                                capture_output=True, text=True, timeout=15,
                                env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
        return result, output

    def test_mask_excludes_background_and_preserves_test_provenance(self):
        result, output = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(output.read_text())
        self.assertEqual(row["status"], "measured")
        self.assertEqual(row["features"]["rgb_median"], [120, 60, 30])
        self.assertEqual(row["features"]["rgb_iqr"], [0, 0, 0])
        self.assertEqual(row["features"]["selected_pixels"], 64)
        self.assertEqual(row["features"]["saturation_median"], .75)
        self.assertEqual(row["metadata"]["dataset_kind"], "test")
        self.assertIsNone(row["shedding_prediction"])
        self.assertFalse(row["actuation_allowed"])
        self.assertEqual(row["files"]["image"]["sha256"], hashlib.sha256((self.root / "image.png").read_bytes()).hexdigest())

    def test_ir_unknown_settings_and_uncertain_skin_do_not_yield_color_features(self):
        for section, key, value in [("capture", "mode", "infrared"), ("capture", "reference_revision", None),
                                    ("capture", "white_balance_locked", False), ("review", "identity_confirmed", False),
                                    ("review", "skin_only", False), ("review", "dry", False)]:
            with self.subTest(key=key):
                row = copy.deepcopy(self.row)
                row[section][key] = value
                result, output = self.run_cli(row, f"excluded-{key}.json")
                self.assertEqual(result.returncode, 0, result.stderr)
                record = json.loads(output.read_text())
                self.assertEqual(record["status"], "excluded")
                self.assertIsNone(record["features"])
                self.assertTrue(record["reasons"])

    def test_soft_mask_and_empty_mask_fail_without_output(self):
        from PIL import Image
        for value in (0, 128):
            Image.new("L", (16, 16), value).save(self.root / "mask.png")
            result, output = self.run_cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_invalid_time_and_escaping_paths_fail_without_output(self):
        for key, value in [("observed_at", None), ("observed_at", "2026-10-29T01:00:00"),
                           ("image", "../outside.png"), ("dataset_kind", "simulation")]:
            row = copy.deepcopy(self.row)
            row[key] = value
            result, output = self.run_cli(row)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_existing_observation_cannot_be_overwritten(self):
        result, output = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = output.read_bytes()
        self.row["animal_id"] = "another-animal"
        result, _ = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), before)

    def test_capture_revision_changes_comparison_group(self):
        result, path = self.run_cli(name="first.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.row["capture"]["illumination_revision"] = "day-2"
        result, second = self.run_cli(name="second.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(json.loads(path.read_text())["comparison_group"], json.loads(second.read_text())["comparison_group"])

    def test_human_shed_event_preserves_interval_without_inventing_exact_time(self):
        row = {"schema_version": 1, "kind": "shedding_event", "dataset_kind": "test", "record_id": "shed-1",
               "animal_id": "fixture-animal", "species": "crested_gecko", "enclosure_id": "fixture-enclosure",
               "stage": "completed", "earliest_at": "2026-10-28T22:00:00Z", "latest_at": "2026-10-29T01:00:00Z",
               "observer": "fixture-reviewer", "evidence_reference": "local-care-record:001"}
        result, output = self.run_cli(row)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(output.read_text())
        self.assertEqual(record["metadata"], row)
        self.assertIsNone(record["shedding_prediction"])
        row["latest_at"] = "2026-10-27T01:00:00Z"
        result, output = self.run_cli(row, "invalid-event.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
