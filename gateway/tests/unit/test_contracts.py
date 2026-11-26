import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from habitat.gpu.config import Config, Credential, load_config
from habitat.gpu.contracts import CaptureManifest, CaptureStatus, ComputeHealth, FileReceipt, JobRequest, JobStatus


PROJECT = Path(__file__).resolve().parents[2]


def manifest():
    return {
        "schema_version": 1, "site_id": "STORE-001", "gateway_id": "PI-001", "cage_id": "CAGE-001",
        "capture_id": str(uuid4()), "geometry_revision": 1, "placement_revision": 1,
        "captured_at": "2026-09-20T00:00:00Z", "capture_method": "multiview_rgb",
        "files": [dict(file_id=str(uuid4()), name=f"{i}.jpg", size_bytes=100, sha256="a" * 64,
                       captured_at="2026-09-20T00:00:00Z") for i in range(3)],
    }


class ContractTests(unittest.TestCase):
    def test_supplied_examples_round_trip_through_pi_schemas(self):
        for name, model in [("capture-manifest", CaptureManifest), ("capture-ready", CaptureStatus),
                            ("capture-uploading", CaptureStatus), ("file-receipt", FileReceipt),
                            ("health-not-configured", ComputeHealth), ("job-queued", JobStatus),
                            ("job-request", JobRequest)]:
            with self.subTest(example=name):
                payload = (PROJECT / "docs/gpu/examples" / f"{name}.json").read_text(encoding="utf-8")
                parsed = model.model_validate_json(payload)
                schema = json.loads((PROJECT / "configs/schemas/compute-v1" / f"{model.__name__}.schema.json").read_text(encoding="utf-8"))
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(parsed.model_dump(mode="json"))

    def test_manifest_validates_and_rejects_unsafe_inputs(self):
        payload = manifest()
        self.assertEqual(CaptureManifest.model_validate_json(json.dumps(payload)).schema_version, 1)
        repeated_names = copy.deepcopy(payload)
        for file in repeated_names["files"]:
            file["name"] = "frame.jpg"
        CaptureManifest.model_validate(repeated_names)  # Identity and storage use file_id, not name.
        for field, value in [("geometry_revision", True), ("placement_revision", "1"),
                             ("schema_version", True), ("captured_at", "2026-09-20T00:00:00"),
                             ("captured_at", 1234), ("captured_at", "1234"),
                             ("capture_id", "../oops"), ("cage_id", "x/y")]:
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                CaptureManifest.model_validate(dict(payload, **{field: value}))
        for name in ["../1.jpg", "x\\1.jpg", "C:1.jpg", "x.txt", "x\x00.jpg"]:
            invalid = copy.deepcopy(payload)
            invalid["files"][0]["name"] = name
            with self.subTest(name=name), self.assertRaises(ValidationError):
                CaptureManifest.model_validate(invalid)
        for change in [lambda p: p["files"].__setitem__(1, p["files"][0]),
                       lambda p: p["files"][0].__setitem__("size_bytes", True),
                       lambda p: p.__setitem__("unknown", "unexpected")]:
            invalid = copy.deepcopy(payload)
            change(invalid)
            with self.assertRaises(ValidationError):
                CaptureManifest.model_validate(invalid)
        huge = copy.deepcopy(payload)
        huge["files"] = [dict(huge["files"][0], file_id=str(uuid4()), name=f"{i}.jpg", size_bytes=20 * 1024**2)
                         for i in range(103)]
        with self.assertRaises(ValidationError):
            CaptureManifest.model_validate(huge)

    def test_pi_schema_defaults_and_status_partition(self):
        payload = manifest()
        del payload["schema_version"], payload["capture_method"]
        capture = CaptureManifest.model_validate(payload)
        self.assertEqual(capture.model_dump()["schema_version"], 1)
        request = JobRequest(site_id=capture.site_id, gateway_id=capture.gateway_id,
                             cage_id=capture.cage_id, capture_id=capture.capture_id, job_id=uuid4())
        self.assertEqual(request.kind, "3dgs")
        status = dict(site_id=capture.site_id, gateway_id=capture.gateway_id, cage_id=capture.cage_id,
                      capture_id=capture.capture_id, status="uploading", verified_file_ids=[],
                      missing_file_ids=[f.file_id for f in capture.files])
        CaptureStatus.model_validate(status)
        with self.assertRaises(ValidationError):
            CaptureStatus.model_validate(dict(status, status="ready"))
        with self.assertRaises(ValidationError):
            CaptureStatus.model_validate(dict(status, verified_file_ids=[capture.files[0].file_id]))

    def test_job_state_invariants(self):
        capture = CaptureManifest.model_validate(manifest())
        job = dict(site_id=capture.site_id, gateway_id=capture.gateway_id, cage_id=capture.cage_id,
                   capture_id=capture.capture_id, job_id=uuid4(), geometry_revision=1, placement_revision=1,
                   status="queued", stage="queued", created_at=capture.captured_at,
                   updated_at=capture.captured_at, artifacts=[], error=None)
        JobStatus.model_validate(job)
        for overrides in [dict(status="running"), dict(status="succeeded", stage="complete"),
                          dict(status="failed", stage="failed")]:
            with self.assertRaises(ValidationError):
                JobStatus.model_validate(dict(job, **overrides))
        JobStatus.model_validate(dict(job, status="failed", stage="failed", error={"code": "failure", "message": "failed"}))

    def test_readiness_and_boolean_types(self):
        health = dict(status="degraded", backend="mock", limits={},
                      gpu=dict(name=None, cuda_available=False, vram_total_bytes=None, reconstruction_ready=False))
        ComputeHealth.model_validate(health)
        for gpu in [dict(health["gpu"], cuda_available="false"),
                    dict(health["gpu"], cuda_available=True, reconstruction_ready=True)]:
            with self.assertRaises(ValidationError):
                ComputeHealth.model_validate(dict(health, gpu=gpu))

    def test_config_secrets_scope_and_file(self):
        token = "test-only-credential-" + "x" * 32
        with patch.dict(os.environ, HABITAT_GPU_TOKEN=token):
            credential = Credential(site_id="STORE-001", gateway_id="PI-001", cage_ids=["CAGE-001"])
            config = Config(credentials=[credential])
            self.assertNotIn(token, repr(config))
            self.assertNotIn(token, config.model_dump_json())
            self.assertEqual(credential.token.get_secret_value(), token)
            example = Path(__file__).resolve().parents[2] / "configs/examples/gpu.toml"
            self.assertTrue(load_config(example).storage_dir.is_absolute())
            with self.assertRaises(ValidationError):
                Config(credentials=[credential, credential])
            with self.assertRaises(ValidationError):
                Config(credentials=[credential], host="0.0.0.0")
        for token in ["short", "x" * 32 + " ", "x" * 32 + "\n", "x" * 32 + "é"]:
            with patch.dict(os.environ, HABITAT_GPU_TOKEN=token), self.assertRaises(ValidationError) as raised:
                Credential(site_id="STORE-001", gateway_id="PI-001", cage_ids=["CAGE-001"])
            self.assertNotIn(token, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
