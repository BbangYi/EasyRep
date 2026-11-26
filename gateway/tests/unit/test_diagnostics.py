"""Persistence and v2-compatible diagnostic summaries, without a GPU dependency."""

import json
import errno
from dataclasses import dataclass
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from habitat.gpu.contracts import JobStatus
from habitat.gpu.backend import Backend, BackendError
from habitat.gpu.diagnostics import atomic_json, file_hash, public_summary, tree_hashes
from scripts.compare_reconstruction_study import config_leaves, verify_report_provenance


class DiagnosticsTests(unittest.TestCase):
    def test_training_harness_rejects_wrong_metrics_and_shape_only_improvement(self):
        from scripts.verify_training_harness import metric_parity, nonregression_gate
        original = {"psnr": 20.0, "psnr_std": 1.0, "ssim": .8, "ssim_std": .01, "lpips": .2, "lpips_std": .02}
        self.assertEqual(max(metric_parity(original, original).values()), 0)
        for value in (21.0, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                metric_parity(original, {**original, "psnr": value})
        worse = {**original, "ssim": .7}
        pair = {"full_frame": {"O1": original, "O2": original},
                "roi": [{"id": "floor", "O1": original, "O2": worse}],
                "gaussians": {"O1": {"max_scale": 200}, "O2": {"max_scale": 1}}}
        self.assertEqual(nonregression_gate(pair)["status"], "fail")
        pair["roi"][0]["O2"] = original
        self.assertEqual(nonregression_gate(pair)["status"], "no_measured_regression")
        self.assertFalse(nonregression_gate(pair)["absolute_quality_validated"])

    def test_comparison_rejects_stale_or_misbound_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / str(uuid4())
            config, checkpoint = job / "trained/config.yml", job / "trained/step-000003000.ckpt"
            atomic_json(config, {"seed": 42})
            atomic_json(checkpoint, {"step": 3000})
            collectors = {name: str(index) * 64 for index, name in enumerate(
                ("diagnostics.py", "colmap_diagnostics.py", "splat_diagnostics.py"), 1)}
            report = {"source_job_id": job.name, "status": "ok",
                "provenance": {"training_config_sha256": file_hash(config), "collector_sha256": collectors},
                "splatfacto": {"status": "ok", "checkpoints": [{"status": "ok", "checkpoint": str(checkpoint),
                    "checkpoint_sha256": file_hash(checkpoint)}]}}
            verify_report_provenance(report, job, config, collectors)
            unrelated_checkpoint = Path(directory) / "other-job/step-000003000.ckpt"
            atomic_json(unrelated_checkpoint, {"step": 3000})
            for keys, value in ((("source_job_id",), str(uuid4())), (("status",), "partial"),
                    (("splatfacto", "status"), "partial"),
                    (("provenance", "training_config_sha256"), "f" * 64),
                    (("provenance", "collector_sha256"), {}),
                    (("splatfacto", "checkpoints", 0, "status"), "running"),
                    (("splatfacto", "checkpoints", 0, "checkpoint"), str(unrelated_checkpoint)),
                    (("splatfacto", "checkpoints", 0, "checkpoint_sha256"), "f" * 64)):
                with self.subTest(field=keys):
                    changed = json.loads(json.dumps(report))
                    target = changed
                    for key in keys[:-1]:
                        target = target[key]
                    target[keys[-1]] = value
                    with self.assertRaises(ValueError):
                        verify_report_provenance(changed, job, config, collectors)
            with self.assertRaises(ValueError):
                verify_report_provenance(report, job, config, {**collectors, "diagnostics.py": "f" * 64})
            atomic_json(checkpoint, {"step": 3001})
            with self.assertRaises(ValueError):
                verify_report_provenance(report, job, config, collectors)

    def test_visual_comparison_is_local_and_escapes_labels(self):
        from scripts.compare_reconstruction_study import visual_page
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = {"actual_step": 3000, "views": [{"image_name": "<window>",
                "images": {"gt": "gt.png", "pred": "pred.png"}, "rois": []}]}
            reports = {key: {"splatfacto": {"checkpoints": [checkpoint]}} for key in ("O1", "O2")}
            page = visual_page(reports, {key: root / key for key in reports}, root / "comparison.html")
            self.assertIn("&lt;window&gt;", page)
            self.assertEqual(page.count("<img "), 3)
            self.assertNotIn("<script", page)
            self.assertNotIn("https://", page)

    def test_atomic_strict_json_and_immutable_file_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_json(root / "report.json", {"metric": None})
            before = tree_hashes(root)
            with self.assertRaises(ValueError):
                atomic_json(root / "report.json", {"metric": float("nan")})
            self.assertEqual(before, tree_hashes(root))
            self.assertEqual(json.loads((root / "report.json").read_text()), {"metric": None})

    def test_summary_allowlist_and_current_pi_contract(self):
        summary = public_summary({"status": "partial", "source_job_id": str(uuid4()),
            "provenance": {"roi_sha256": "a" * 64, "secret": "not-public"},
            "colmap": {"status": "ok", "observations": 6, "local_path": "/private/job"},
            "splatfacto": {"status": "error", "local_path": "/private/checkpoint"}})
        self.assertNotIn("private", json.dumps(summary))
        self.assertNotIn("not-public", json.dumps(summary))
        self.assertLess(len(json.dumps(summary).encode()), 64 * 1024)
        job_id, artifact_id = str(uuid4()), str(uuid4())
        job = dict(schema_version=1, site_id="STORE-001", gateway_id="PI-001", cage_id="CAGE-001",
            capture_id=str(uuid4()), job_id=job_id, geometry_revision=1, placement_revision=1,
            kind="3dgs", preset="preview", status="succeeded", stage="complete",
            created_at="2026-09-21T00:00:00Z", updated_at="2026-09-21T00:00:00Z", error=None,
            artifacts=[dict(artifact_id=artifact_id, format="gaussian_splat_ply", size_bytes=100,
                sha256="a" * 64, download_path=f"/v1/gpu/jobs/{job_id}/artifacts/{artifact_id}",
                metric_scale_verified=False, metadata={"diagnostics": summary})])
        value = JobStatus.model_validate(job).model_dump(mode="json")
        schema = Path(__file__).resolve().parents[2] / "configs/schemas/compute-v1/JobStatus.schema.json"
        Draft202012Validator(json.loads(schema.read_text()), format_checker=FormatChecker()).validate(value)

    def test_deep_summary_rejects_paths_and_preserves_numeric_evidence(self):
        leak = "/private/secret"
        aggregate = {"view_count": 3, "psnr": 20.1, "psnr_std": 1.2, "ssim": 0.8, "lpips": None,
                     "valid_metric_counts": {"psnr": 3, "ssim": 3, "lpips": 0, "path": leak}, "path": leak}
        gaussian = {"count": 42, "path": leak, "coordinates": leak,
                    "max_axis_scale": {"p99": 0.25, "max": 500.0, "nonfinite_count": 0, "path": leak},
                    "axis_ratio": {"max": 15.0}, "opacity": {"p50": 0.9},
                    "initial_sparse": {"count": 7, "min": [-1, 0, 1], "max": [1, 2, 3], "path": leak},
                    "scene_bounds": {"aabb": [[-1, 0, 1], [1, 2, 3]], "extent": 3.4,
                        "coordinate_system": "nerfstudio_normalized", "metric_scale_verified": False,
                        "extent_definition": "initial_sparse_aabb_diagonal", "path": leak},
                    "centers": {"min": [-1, 0, 1], "outside_initial_aabb_count": 2, "path": leak},
                    "nonfinite_parameter_counts": {"means": 0, "path": leak}}
        report = {"status": "ok", "source_job_id": str(uuid4()), "report_sha256": "a" * 64,
                  "provenance": {"roi_sha256": "b" * 64},
                  "colmap": {"status": "ok", "input_images": 38, "registered_images": 38,
                             "track_length": {"mean": 4.5, "source": leak, "unit": leak, "path": leak},
                             "stored_point_error_px": {"mean": 0.2, "source": "points3D.ERROR", "unit": "px"}},
                  "splatfacto": {"status": "ok", "checkpoints": [{"actual_step": 2999,
                      "checkpoint_sha256": "c" * 64, "checkpoint": leak, "aggregate": aggregate,
                      "train_aggregate": aggregate, "roi_aggregate": {"floor": aggregate, "reflection_window": aggregate,
                          "matte_control": aggregate, "sky": aggregate, leak: aggregate},
                      "gaussians": gaussian, "views": [{"image_name": leak}]}]}}
        summary = public_summary(report)
        self.assertNotIn(leak, json.dumps(summary))
        row = summary["evaluation"]["checkpoints"][0]
        self.assertEqual(row["checkpoint_sha256"], "c" * 64)
        self.assertEqual(row["actual_step"], 2999)
        self.assertEqual(row["aggregate"]["valid_metric_counts"], {"psnr": 3, "ssim": 3, "lpips": 0})
        self.assertEqual(set(row["roi_aggregate"]), {"floor", "reflection_window", "matte_control", "sky"})
        self.assertEqual(row["gaussians"]["initial_sparse"]["min"], [-1, 0, 1])
        self.assertEqual(row["gaussians"]["scene_bounds"]["aabb"], [[-1, 0, 1], [1, 2, 3]])
        self.assertEqual(row["gaussians"]["centers"]["outside_initial_aabb_count"], 2)
        self.assertEqual(summary["colmap"]["stored_point_error_px"]["source"], "points3D.ERROR")

    def test_summary_validates_scalars_hashes_enums_and_size(self):
        row = {"actual_step": True, "checkpoint_sha256": "/private/checkpoint",
               "aggregate": {"view_count": -1, "psnr": float("nan"), "ssim": True,
                             "valid_metric_counts": {"psnr": "/private/secret"}},
               "gaussians": {"count": "/private/secret", "max_axis_scale": {"max": float("inf")},
                             "centers": {"min": [0, "/private/secret", 1]}}}
        report = {"status": "/private/status", "source_job_id": "/private/id", "report_sha256": "g" * 64,
                  "provenance": {"roi_sha256": "A" * 64}, "splatfacto": {"checkpoints": [row]}}
        summary = public_summary(report)
        self.assertNotIn("/private", json.dumps(summary, allow_nan=False))
        self.assertIsNone(summary["source_job_id"])
        self.assertIsNone(summary["report_sha256"])
        self.assertIsNone(summary["roi_sha256"])
        cleaned = summary["evaluation"]["checkpoints"][0]
        self.assertIsNone(cleaned["actual_step"])
        self.assertIsNone(cleaned["checkpoint_sha256"])
        self.assertIsNone(cleaned["aggregate"]["psnr"])
        self.assertIsNone(cleaned["gaussians"]["centers"]["min"])
        report["splatfacto"]["checkpoints"] = [row] * 1000
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            public_summary(report)

    def test_diagnostic_hook_partial_vs_fatal_and_storage_failures(self):
        for code, fatal in (("timeout", False), ("subprocess_failed", False), ("input_corrupt", True),
                            ("storage_unavailable", True), ("interrupted", True)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                work = Path(directory) / str(uuid4())
                work.mkdir()
                backend = Backend({})
                with patch.object(backend, "_command", side_effect=BackendError(code, "test failure")):
                    if fatal:
                        with self.assertRaises(BackendError) as error:
                            backend._diagnostics(work, None, threading.Event(), {"stage_seconds": {}})
                        self.assertEqual(error.exception.code, code)
                        self.assertFalse((work / "diagnostics/summary.json").exists())
                    else:
                        result = backend._diagnostics(work, None, threading.Event(), {"stage_seconds": {}})
                        self.assertEqual(result["status"], "partial")
                        self.assertEqual(result["reason"], code)
        with tempfile.TemporaryDirectory() as directory:
            backend, cancel = Backend({}), threading.Event()
            cancel.set()
            with patch.object(backend, "_command", side_effect=BackendError("timeout", "test failure")), self.assertRaises(BackendError):
                backend._diagnostics(Path(directory), None, cancel, {"stage_seconds": {}})
            with patch.object(backend, "_command", side_effect=BackendError("timeout", "test failure")), \
                    patch("habitat.gpu.diagnostics.atomic_json", side_effect=OSError(errno.ENOSPC, "test disk full")), \
                    self.assertRaises(OSError):
                backend._diagnostics(Path(directory), None, threading.Event(), {"stage_seconds": {}})

    def test_config_leaves_flattens_instances_but_not_dataclass_types(self):
        @dataclass
        class Nested:
            seed: int
            data: Path

        value = {"pipeline": {"datamanager": Nested(seed=42, data=Path("processed")), "target": Nested}}
        self.assertEqual(config_leaves(value), {
            ".pipeline.datamanager.seed": "42", ".pipeline.datamanager.data": "processed",
            ".pipeline.target": str(Nested)})
        self.assertEqual(config_leaves(value, "config")["config.pipeline.datamanager.seed"], "42")


if __name__ == "__main__":
    unittest.main()
