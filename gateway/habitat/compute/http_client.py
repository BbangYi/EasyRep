"""HTTP adapter for the versioned GPU API. Used only by the independent worker."""
from contextlib import contextmanager
import hashlib
import os
import time

import httpx
from pydantic import ValidationError

from .contracts import (API_PREFIX, CaptureStatus, ComputeHealth, FileReceipt, JobStatus,
                        artifact_path, capture_path, job_path)
from .errors import ComputeFailure
from .files import CHUNK_BYTES, file_digest, fsync_directory, verify_gaussian_ply

JSON_LIMIT = 4 * 1024 * 1024


class HTTPComputeClient:
    def __init__(self, config, token, *, transport=None):
        self.config = config
        self.origin = config.origin
        self.client = httpx.Client(
            transport=transport, trust_env=False, follow_redirects=False, timeout=config.timeout_s,
            headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
        )

    def close(self):
        self.client.close()

    @contextmanager
    def response(self, method, path, *, expected=200, transfer=False, **kwargs):
        allowed = path.startswith(API_PREFIX + "/") or path in (
            "/v1/environment/health", "/v1/environment/predict", "/v1/livescene/health", "/v1/livescene/models", "/v1/livescene/render")
        if not self.origin or not allowed or "?" in path or "#" in path:
            raise ComputeFailure("invalid_compute_path")
        budget = self.config.transfer_timeout_s if transfer else self.config.timeout_s
        deadline = time.monotonic() + budget
        try:
            with self.client.stream(method, self.origin + path, timeout=min(budget, self.config.timeout_s),
                                    follow_redirects=False, **kwargs) as response:
                if response.status_code != expected:
                    # Controlled codes only; remote error text can contain URLs, secrets or filesystem paths.
                    raise ComputeFailure(f"http_{response.status_code}",
                        retryable=response.status_code in (408, 425, 429) or response.status_code >= 500,
                        status_code=response.status_code)
                yield response, deadline
        except httpx.TimeoutException:
            raise ComputeFailure("compute_timeout", retryable=True) from None
        except httpx.HTTPError:
            raise ComputeFailure("compute_network_error", retryable=True) from None

    def json(self, method, path, model, *, expected=200, transfer=False, **kwargs):
        with self.response(method, path, expected=expected, transfer=transfer, **kwargs) as (response, deadline):
            data = bytearray()
            for chunk in response.iter_bytes(CHUNK_BYTES):
                if time.monotonic() > deadline:
                    raise ComputeFailure("compute_deadline_exceeded", retryable=True)
                data.extend(chunk)
                if len(data) > JSON_LIMIT:
                    raise ComputeFailure("compute_response_too_large")
        try:
            return model.model_validate_json(data)
        except ValidationError:
            raise ComputeFailure("invalid_compute_response") from None

    def health(self):
        return self.json("GET", API_PREFIX + "/health", ComputeHealth)

    def register_capture(self, manifest):
        return self.json("POST", API_PREFIX + "/captures", CaptureStatus, json=manifest.model_dump(mode="json"))

    def get_capture(self, capture_id):
        return self.json("GET", capture_path(capture_id), CaptureStatus)

    def upload_file(self, capture_id, entry, path):
        if path.is_symlink() or not path.is_file() or file_digest(path) != (entry.size_bytes, entry.sha256):
            raise ComputeFailure("local_capture_file_changed")
        deadline = time.monotonic() + self.config.transfer_timeout_s

        def chunks():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                    if time.monotonic() > deadline:
                        raise ComputeFailure("compute_deadline_exceeded", retryable=True)
                    yield chunk

        return self.json("PUT", f"{capture_path(capture_id)}/files/{entry.file_id}", FileReceipt,
                         transfer=True, content=chunks(),
                         headers={"Content-Type": "application/octet-stream", "Content-Length": str(entry.size_bytes)})

    def submit_reconstruction(self, request):
        return self.json("POST", API_PREFIX + "/jobs", JobStatus, expected=202, json=request.model_dump(mode="json"))

    def get_job_status(self, job_id):
        return self.json("GET", job_path(job_id), JobStatus)

    def get_artifact(self, job_id, artifact, destination):
        path = artifact_path(job_id, artifact.artifact_id)
        if artifact.download_path != path:
            raise ComputeFailure("artifact_path_mismatch")
        if artifact.size_bytes > self.config.max_artifact_bytes:
            raise ComputeFailure("artifact_size_limit")
        if destination.is_symlink():
            raise ComputeFailure("unsafe_artifact_destination")
        if destination.is_file() and file_digest(destination) == (artifact.size_bytes, artifact.sha256):
            verify_gaussian_ply(destination)
            return
        temporary = destination.with_suffix(".part")
        if temporary.is_symlink():
            raise ComputeFailure("unsafe_artifact_destination")
        try:
            with self.response("GET", path, transfer=True) as (response, deadline):
                if (response.headers.get("Content-Length") != str(artifact.size_bytes)
                        or response.headers.get("X-Content-SHA256") != artifact.sha256
                        or response.headers.get("Content-Encoding", "identity") != "identity"):
                    raise ComputeFailure("artifact_headers_mismatch")
                digest, size = hashlib.sha256(), 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        if time.monotonic() > deadline:
                            raise ComputeFailure("compute_deadline_exceeded", retryable=True)
                        size += len(chunk)
                        if size > artifact.size_bytes:
                            raise ComputeFailure("artifact_size_mismatch")
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if size != artifact.size_bytes or digest.hexdigest() != artifact.sha256:
                    raise ComputeFailure("artifact_checksum_mismatch")
                verify_gaussian_ply(temporary)
                os.replace(temporary, destination)
                fsync_directory(destination.parent)
        finally:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
