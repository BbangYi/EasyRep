"""Durable capture/job orchestration through a replaceable compute client."""
from datetime import timedelta
import logging
import random

from .contracts import CaptureManifest, JobRequest, JobStatus
from .errors import ComputeFailure
from .files import file_digest

logger = logging.getLogger(__name__)


class ComputeWorker:
    def __init__(self, repository, client, config, cages):
        self.repository, self.client, self.config = repository, client, config
        self.cages = {c.id: c for c in cages}

    def _capture_status(self, manifest, status):
        for key in ("site_id", "gateway_id", "cage_id", "capture_id"):
            if getattr(manifest, key) != getattr(status, key):
                raise ComputeFailure("capture_scope_mismatch")
        expected = {f.file_id for f in manifest.files}
        verified, missing = set(status.verified_file_ids), set(status.missing_file_ids)
        if (len(verified) != len(status.verified_file_ids) or len(missing) != len(status.missing_file_ids)
                or verified & missing or verified | missing != expected
                or (status.status == "ready") != (not missing)):
            raise ComputeFailure("capture_file_status_mismatch")

    def _job_status(self, manifest, request, status):
        for key in JobRequest.model_fields:
            if getattr(request, key) != getattr(status, key):
                raise ComputeFailure("job_scope_mismatch")
        if (status.geometry_revision, status.placement_revision) != (
                manifest.geometry_revision, manifest.placement_revision):
            raise ComputeFailure("job_revision_mismatch")

    def advance(self, job_id):
        if not self.config.enabled:
            return self.repository.task(job_id)
        task = self.repository.task(job_id)
        if task["state"] in ("complete", "blocked", "failed", "interrupted"):
            return task
        try:
            self.repository.bind(job_id, self.client.origin)
            manifest = CaptureManifest.model_validate(task["manifest"])
            request = JobRequest.model_validate(task["request"])
            cage = self.cages.get(manifest.cage_id)
            if cage is None:
                raise ComputeFailure("cage_not_configured")
            # This capture retains its original revision. Never silently retag an old scan.
            if (cage.geometry_revision, cage.placement_revision) != (
                    manifest.geometry_revision, manifest.placement_revision):
                raise ComputeFailure("capture_revision_changed")
            if task["remote"] is None:
                health = self.client.health()
                if (len(manifest.files) > health.limits.max_files_per_capture
                        or sum(f.size_bytes for f in manifest.files) > health.limits.max_capture_bytes
                        or any(f.size_bytes > health.limits.max_file_bytes for f in manifest.files)):
                    raise ComputeFailure("backend_capture_limit")
                status = self.client.register_capture(manifest)
                self._capture_status(manifest, status)
                self.repository.update(job_id, state="uploading")
                missing = set(status.missing_file_ids)
                for entry in manifest.files:
                    if entry.file_id not in missing:
                        continue
                    receipt = self.client.upload_file(manifest.capture_id, entry,
                        self.repository.input_path(manifest.capture_id, entry.file_id))
                    if (receipt.capture_id != manifest.capture_id or receipt.file_id != entry.file_id
                            or receipt.size_bytes != entry.size_bytes or receipt.sha256 != entry.sha256):
                        raise ComputeFailure("file_receipt_mismatch")
                status = self.client.get_capture(manifest.capture_id)
                self._capture_status(manifest, status)
                if status.status != "ready":
                    raise ComputeFailure("capture_not_ready", retryable=True)
                if not health.gpu.reconstruction_ready:
                    raise ComputeFailure("backend_not_ready", retryable=True)
                remote = self.client.submit_reconstruction(request)
            else:
                remote = self.client.get_job_status(request.job_id)
            self._job_status(manifest, request, remote)
            if task["remote"]:
                previous = JobStatus.model_validate(task["remote"])
                if (remote.updated_at < previous.updated_at
                        or previous.status == "running" and remote.status == "queued"
                        or previous.status == "succeeded" and remote.status != "succeeded"):
                    raise ComputeFailure("remote_job_state_regressed")
            body = remote.model_dump(mode="json")
            # Keep only machine-readable errors in local state/logs, not arbitrary server messages.
            if body["error"]:
                body["error"] = {"code": "remote_job_failed", "message": "Inspect GPU worker logs"}
            if remote.status in ("failed", "interrupted"):
                self.repository.update(job_id, state=remote.status, error=f"remote_{remote.status}", remote=body)
            elif remote.status == "succeeded":
                self.repository.update(job_id, state="downloading", remote=body)
                for artifact in remote.artifacts:
                    if artifact.size_bytes > self.config.max_artifact_bytes:
                        raise ComputeFailure("artifact_size_limit")
                    destination = self.repository.artifact_path(job_id, artifact.artifact_id)
                    if (not destination.is_file() or destination.is_symlink()
                            or file_digest(destination) != (artifact.size_bytes, artifact.sha256)):
                        self.repository.require_space(artifact.size_bytes)
                    self.client.get_artifact(request.job_id, artifact, destination)
                self.repository.update(job_id, state="complete", remote=body)
            else:
                next_at = self.repository.now() + timedelta(seconds=self.config.poll_interval_s)
                self.repository.update(job_id, state="waiting", remote=body, next_attempt_at=next_at.isoformat())
        except ComputeFailure as error:
            self._failure(job_id, error)
        except OSError:
            self._failure(job_id, ComputeFailure("local_compute_io_error"))
        return self.repository.task(job_id)

    def _failure(self, job_id, error):
        attempts = self.repository.task(job_id)["attempts"] + 1
        next_at = None
        if error.retryable:
            delay = min(self.config.retry_max_s, self.config.poll_interval_s * 2 ** min(attempts, 16))
            delay = random.uniform(self.config.poll_interval_s, delay)
            next_at = (self.repository.now() + timedelta(seconds=delay)).isoformat()
        self.repository.update(job_id, state="retry" if error.retryable else "blocked", error=error.code,
                               next_attempt_at=next_at, increment_attempt=True)
        logger.warning("Compute job %s: %s", job_id, error.code)

    def cycle(self):
        if not self.config.enabled:
            return []
        return [self.advance(job_id) for job_id in self.repository.due()]
