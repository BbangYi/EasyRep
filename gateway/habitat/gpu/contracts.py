"""Pi Compute API 1.0.0 wire models and constraints beyond its JSON Schemas.

The supplied Pi schemas make schema_version/capture_method/kind/preset
optional with defaults; accept those defaults and always emit the full model.
"""

from datetime import datetime
from pathlib import PurePath
import re
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field,
    StrictBool, StrictInt, StrictStr, field_validator, model_validator,
)


def _uuid(value: Any) -> Any:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
    ):
        raise ValueError("expected RFC UUID string")
    return value


def _timestamp(value: Any) -> Any:
    if not isinstance(value, (str, datetime)):
        raise ValueError("expected timezone-aware ISO 8601 timestamp")
    if isinstance(value, str) and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("expected timezone-aware ISO 8601 timestamp")
    return value


Identifier = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
SHA256 = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
WireUUID = Annotated[UUID, BeforeValidator(_uuid)]
Timestamp = Annotated[AwareDatetime, BeforeValidator(_timestamp)]
Revision = Annotated[StrictInt, Field(ge=1)]
FileBytes = Annotated[StrictInt, Field(gt=0, le=20 * 1024**2)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def integer_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value


class Scope(WireModel):
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier


class CaptureFile(WireModel):
    file_id: WireUUID
    name: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    size_bytes: FileBytes
    sha256: SHA256
    captured_at: Timestamp

    @field_validator("name")
    @classmethod
    def image_filename(cls, value: str) -> str:
        if any(c in value for c in "/\\:") or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("name must be a filename without a path")
        if PurePath(value).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("only JPEG and PNG filenames are supported")
        return value


class CaptureManifest(Scope):
    schema_version: Literal[1] = 1
    capture_id: WireUUID
    geometry_revision: Revision
    placement_revision: Revision
    captured_at: Timestamp
    capture_method: Literal["multiview_rgb"] = "multiview_rgb"
    files: Annotated[list[CaptureFile], Field(min_length=3, max_length=500)]

    @model_validator(mode="after")
    def unique_files_and_size(self) -> Self:
        if len({f.file_id for f in self.files}) != len(self.files):
            raise ValueError("file_id must be unique within a capture")
        if sum(f.size_bytes for f in self.files) > 2 * 1024**3:
            raise ValueError("capture exceeds 2 GiB")
        return self


class CaptureStatus(Scope):
    schema_version: Literal[1] = 1
    capture_id: WireUUID
    status: Literal["uploading", "ready"]
    verified_file_ids: Annotated[list[WireUUID], Field(max_length=500)]
    missing_file_ids: Annotated[list[WireUUID], Field(max_length=500)]

    @model_validator(mode="after")
    def file_partition(self) -> Self:
        ids = self.verified_file_ids + self.missing_file_ids
        if len(ids) != len(set(ids)) or not 3 <= len(ids) <= 500:
            raise ValueError("file lists must form a unique partition of 3-500 files")
        if (self.status == "ready") != (not self.missing_file_ids):
            raise ValueError("ready requires all files to be verified")
        return self


class FileReceipt(WireModel):
    schema_version: Literal[1] = 1
    capture_id: WireUUID
    file_id: WireUUID
    size_bytes: FileBytes
    sha256: SHA256
    status: Literal["verified"] = "verified"


class JobRequest(Scope):
    schema_version: Literal[1] = 1
    job_id: WireUUID
    capture_id: WireUUID
    kind: Literal["3dgs"] = "3dgs"
    preset: Literal["preview"] = "preview"


class Artifact(WireModel):
    artifact_id: WireUUID
    format: Literal["gaussian_splat_ply"] = "gaussian_splat_ply"
    size_bytes: Annotated[StrictInt, Field(gt=0)]
    sha256: SHA256
    download_path: StrictStr
    metric_scale_verified: Literal[False] = False
    metadata: dict[str, Any]

    @field_validator("metric_scale_verified", mode="before")
    @classmethod
    def unverified_scale(cls, value: Any) -> Any:
        if value is not False:
            raise ValueError("v1 metric_scale_verified must be false")
        return value


class JobError(WireModel):
    code: StrictStr
    message: StrictStr


class JobStatus(JobRequest):
    status: Literal["queued", "running", "succeeded", "failed", "interrupted"]
    stage: Literal["queued", "colmap", "training", "exporting", "complete", "failed", "interrupted"]
    created_at: Timestamp
    updated_at: Timestamp
    geometry_revision: Revision
    placement_revision: Revision
    artifacts: Annotated[list[Artifact], Field(max_length=32)]
    error: JobError | None

    @model_validator(mode="after")
    def state_and_artifacts(self) -> Self:
        stages = {
            "queued": {"queued"}, "running": {"colmap", "training", "exporting"},
            "succeeded": {"complete"}, "failed": {"failed"}, "interrupted": {"interrupted"},
        }
        if self.stage not in stages[self.status]:
            raise ValueError("status and stage do not agree")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")
        if (self.status in {"failed", "interrupted"}) != (self.error is not None):
            raise ValueError("failed and interrupted jobs require an error")
        if (self.status == "succeeded") != bool(self.artifacts):
            raise ValueError("only succeeded jobs have artifacts")
        if len({a.artifact_id for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact IDs must be unique")
        for artifact in self.artifacts:
            if artifact.download_path != f"/v1/gpu/jobs/{self.job_id}/artifacts/{artifact.artifact_id}":
                raise ValueError("artifact download_path must match job and artifact IDs")
        return self


class ComputeLimits(WireModel):
    max_files_per_capture: Annotated[StrictInt, Field(ge=3, le=500)] = 500
    max_file_bytes: FileBytes = 20 * 1024**2
    max_capture_bytes: Annotated[StrictInt, Field(gt=0, le=2 * 1024**3)] = 2 * 1024**3
    max_concurrent_jobs: Annotated[StrictInt, Field(ge=1)] = 1


class GPUInfo(WireModel):
    name: StrictStr | None
    cuda_available: StrictBool
    vram_total_bytes: Annotated[StrictInt, Field(ge=0)] | None
    reconstruction_ready: StrictBool


class ComputeHealth(WireModel):
    schema_version: Literal[1] = 1
    service: Literal["habitat-gpu"] = "habitat-gpu"
    api_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ok", "degraded"]
    backend: Literal["splatfacto", "mock", "not_configured"]
    gpu: GPUInfo
    limits: ComputeLimits

    @model_validator(mode="after")
    def real_backend_readiness(self) -> Self:
        if self.gpu.reconstruction_ready and (self.backend != "splatfacto" or not self.gpu.cuda_available):
            raise ValueError("reconstruction requires the real CUDA backend")
        if self.status == "ok" and not self.gpu.reconstruction_ready:
            raise ValueError("unready backends must report degraded")
        return self
