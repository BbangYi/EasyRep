"""Pi ↔ GPU contract v1.0.0. Independent of HTTP, SQLite and hardware drivers."""
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from habitat.common.models import Identifier, Model, Timestamp

API_PREFIX = "/v1/gpu"
CONTRACT_VERSION = "1.0.0"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CAPTURE_BYTES = 2 * 1024 * 1024 * 1024
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def capture_path(capture_id):
    return f"{API_PREFIX}/captures/{UUID(str(capture_id))}"


def job_path(job_id):
    return f"{API_PREFIX}/jobs/{UUID(str(job_id))}"


def artifact_path(job_id, artifact_id):
    return f"{job_path(job_id)}/artifacts/{UUID(str(artifact_id))}"


class Scope(Model):
    schema_version: Literal[1] = 1
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier


class CaptureFile(Model):
    file_id: UUID
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=MAX_FILE_BYTES)
    sha256: Sha256
    captured_at: Timestamp

    @field_validator("name")
    @classmethod
    def filename(cls, value):
        if any(c in value for c in ("/", "\\", "\x00")) or value in (".", ".."):
            raise ValueError("image name must be a basename")
        if not value.lower().endswith((".jpg", ".jpeg", ".png")):
            raise ValueError("only JPEG/PNG inputs are supported")
        return value


class CaptureManifest(Scope):
    capture_id: UUID
    geometry_revision: int = Field(ge=1)
    placement_revision: int = Field(ge=1)
    captured_at: Timestamp
    capture_method: Literal["multiview_rgb"] = "multiview_rgb"
    files: list[CaptureFile] = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def unique_files(self):
        if len({f.file_id for f in self.files}) != len(self.files) or len({f.name for f in self.files}) != len(self.files):
            raise ValueError("duplicate file ID/name")
        if sum(f.size_bytes for f in self.files) > MAX_CAPTURE_BYTES:
            raise ValueError("capture exceeds 2 GiB")
        return self


class CaptureStatus(Scope):
    capture_id: UUID
    status: Literal["uploading", "ready"]
    verified_file_ids: list[UUID] = Field(max_length=500)
    missing_file_ids: list[UUID] = Field(max_length=500)


class FileReceipt(Model):
    schema_version: Literal[1]
    capture_id: UUID
    file_id: UUID
    size_bytes: int = Field(gt=0, le=MAX_FILE_BYTES)
    sha256: Sha256
    status: Literal["verified"]


class JobRequest(Scope):
    job_id: UUID
    capture_id: UUID
    kind: Literal["3dgs"] = "3dgs"
    preset: Literal["preview"] = "preview"


class Artifact(Model):
    artifact_id: UUID
    format: Literal["gaussian_splat_ply"]
    size_bytes: int = Field(gt=0)
    sha256: Sha256
    download_path: str
    metric_scale_verified: Literal[False]
    metadata: dict[str, Any]


class JobError(Model):
    code: str
    message: str


class JobStatus(JobRequest):
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    stage: Literal["queued", "colmap", "training", "exporting", "complete", "failed", "interrupted"]
    created_at: Timestamp
    updated_at: Timestamp
    geometry_revision: int = Field(ge=1)
    placement_revision: int = Field(ge=1)
    artifacts: list[Artifact] = Field(max_length=32)
    error: JobError | None

    @model_validator(mode="after")
    def lifecycle(self):
        stages = {"queued": {"queued"}, "running": {"colmap", "training", "exporting"},
                  "succeeded": {"complete"}, "failed": {"failed"}, "interrupted": {"interrupted"}}
        if self.stage not in stages[self.status] or self.updated_at < self.created_at:
            raise ValueError("inconsistent job lifecycle")
        if self.status == "succeeded" and (not self.artifacts or self.error is not None):
            raise ValueError("success requires artifacts and no error")
        if self.status != "succeeded" and self.artifacts:
            raise ValueError("artifacts are only accepted after success")
        if len({a.artifact_id for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate artifact IDs")
        if any(a.download_path != artifact_path(self.job_id, a.artifact_id) for a in self.artifacts):
            raise ValueError("artifact must use its exact relative API path")
        return self


class GPUInfo(Model):
    name: str | None
    cuda_available: bool
    vram_total_bytes: int | None = Field(ge=0)
    reconstruction_ready: bool


class ComputeLimits(Model):
    max_files_per_capture: int = Field(ge=3, le=500)
    max_file_bytes: int = Field(gt=0, le=MAX_FILE_BYTES)
    max_capture_bytes: int = Field(gt=0, le=MAX_CAPTURE_BYTES)
    max_concurrent_jobs: int = Field(ge=1)


class ComputeHealth(Model):
    schema_version: Literal[1]
    service: Literal["habitat-gpu"]
    api_version: Literal["1.0.0"]
    status: Literal["ok", "degraded"]
    backend: Literal["splatfacto", "mock", "not_configured"]
    gpu: GPUInfo
    limits: ComputeLimits

    @model_validator(mode="after")
    def backend_ready(self):
        if self.gpu.reconstruction_ready and (self.backend != "splatfacto" or not self.gpu.cuda_available):
            raise ValueError("real reconstruction readiness requires a CUDA backend")
        return self
