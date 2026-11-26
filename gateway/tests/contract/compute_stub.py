"""Synthetic HTTP protocol peer. No GPU, learned model or reconstruction is simulated as real evidence."""
import hashlib
import json
from uuid import uuid4

import httpx

from habitat.common.models import utcnow
from habitat.compute.contracts import CaptureManifest, JobRequest, artifact_path

TEST_TOKEN = "test-compute-token-at-least-32-characters"


def gaussian_fixture():
    names = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2",
             "rot_0", "rot_1", "rot_2", "rot_3"]
    return ("ply\nformat ascii 1.0\ncomment synthetic contract fixture, not reconstructed\nelement vertex 1\n"
            + "".join(f"property float {name}\n" for name in names)
            + "end_header\n" + " ".join("0" for _ in names) + "\n").encode()


class ComputeStub:
    def __init__(self):
        self.captures, self.files, self.jobs, self.upload_count = {}, {}, {}, {}
        self.requests = []
        self.artifact = gaussian_fixture()
        self.artifact_id = str(uuid4())
        self.fail_upload_once = False
        self.lose_job_response_once = False
        self.corrupt_download = False
        self.forbidden_scope = False
        self.backend_ready = True
        self.override = None

    def capture_status(self, manifest):
        verified = [f["file_id"] for f in manifest["files"] if f["file_id"] in self.files]
        missing = [f["file_id"] for f in manifest["files"] if f["file_id"] not in self.files]
        return {k: manifest[k] for k in ("schema_version", "site_id", "gateway_id", "cage_id", "capture_id")} | {
            "status": "uploading" if missing else "ready", "verified_file_ids": verified, "missing_file_ids": missing,
        }

    def __call__(self, request):
        self.requests.append((request.method, request.url.path))
        if request.headers.get("Authorization") != f"Bearer {TEST_TOKEN}":
            return httpx.Response(401)
        if self.override:
            response = self.override(request)
            if response is not None:
                return response
        path = request.url.path
        if path == "/v1/gpu/health":
            return httpx.Response(200, json={"schema_version": 1, "service": "habitat-gpu", "api_version": "1.0.0",
                "status": "ok" if self.backend_ready else "degraded", "backend": "splatfacto",
                "gpu": {"name": "SYNTHETIC CONTRACT PEER", "cuda_available": self.backend_ready,
                        "vram_total_bytes": None, "reconstruction_ready": self.backend_ready},
                "limits": {"max_files_per_capture": 500, "max_file_bytes": 20 * 1024**2,
                           "max_capture_bytes": 2 * 1024**3, "max_concurrent_jobs": 1}})
        if path == "/v1/gpu/captures":
            body = CaptureManifest.model_validate_json(request.content).model_dump(mode="json")
            previous = self.captures.setdefault(body["capture_id"], body)
            if previous != body:
                return httpx.Response(409)
            status = self.capture_status(body)
            if self.forbidden_scope:
                status["site_id"] = "OTHER-STORE"
            return httpx.Response(200, json=status)
        if "/captures/" in path:
            capture_id = path.split("/")[4]
            manifest = self.captures[capture_id]
            if request.method == "GET":
                return httpx.Response(200, json=self.capture_status(manifest))
            file_id = path.split("/")[-1]
            if self.fail_upload_once and self.files:
                self.fail_upload_once = False
                raise httpx.ReadTimeout("test response was lost; never log this body")
            entry = next(f for f in manifest["files"] if f["file_id"] == file_id)
            content = request.read()
            assert len(content) == entry["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]
            self.files[file_id] = content
            self.upload_count[file_id] = self.upload_count.get(file_id, 0) + 1
            return httpx.Response(200, json={"schema_version": 1, "capture_id": capture_id,
                "file_id": file_id, "size_bytes": len(content), "sha256": entry["sha256"], "status": "verified"})
        if path == "/v1/gpu/jobs":
            job = JobRequest.model_validate_json(request.content).model_dump(mode="json")
            manifest = self.captures[job["capture_id"]]
            assert not self.capture_status(manifest)["missing_file_ids"]
            now = utcnow().isoformat()
            existing = self.jobs.setdefault(job["job_id"], {**job, "created_at": now, "updated_at": now,
                "status": "queued", "stage": "queued", "geometry_revision": manifest["geometry_revision"],
                "placement_revision": manifest["placement_revision"], "artifacts": [], "error": None})
            if self.lose_job_response_once:
                self.lose_job_response_once = False
                raise httpx.ReadTimeout("job persisted but ACK lost")
            return httpx.Response(202, json=existing)
        if "/artifacts/" in path:
            content = b"corrupted" if self.corrupt_download else self.artifact
            return httpx.Response(200, content=content, headers={"Content-Length": str(len(self.artifact)),
                "X-Content-SHA256": hashlib.sha256(self.artifact).hexdigest()})
        if "/jobs/" in path:
            job_id = path.split("/")[-1]
            previous = self.jobs[job_id]
            previous.update(status="succeeded", stage="complete", updated_at=utcnow().isoformat(), artifacts=[{
                "artifact_id": self.artifact_id, "format": "gaussian_splat_ply", "size_bytes": len(self.artifact),
                "sha256": hashlib.sha256(self.artifact).hexdigest(), "download_path": artifact_path(job_id, self.artifact_id),
                "metric_scale_verified": False, "metadata": {"backend": "synthetic_contract_test"},
            }])
            return httpx.Response(200, json=previous)
        return httpx.Response(404)
