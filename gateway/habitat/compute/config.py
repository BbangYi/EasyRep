from pathlib import Path
import tomllib

from pydantic import AnyHttpUrl, Field, model_validator

from habitat.common.http import bearer_token, validate_service_url
from habitat.common.models import Model


class ComputeConfig(Model):
    enabled: bool = False
    base_url: AnyHttpUrl | None = None
    token_env: str = "HABITAT_GPU_TOKEN"
    storage_dir: str = "var/data/compute"
    timeout_s: float = Field(default=15, ge=1, le=60)
    transfer_timeout_s: float = Field(default=300, ge=1, le=3600)
    poll_interval_s: float = Field(default=5, ge=0.1, le=300)
    retry_max_s: float = Field(default=300, ge=1, le=86400)
    max_artifact_bytes: int = Field(default=1024 * 1024 * 1024, gt=0, le=8 * 1024**3)
    max_storage_bytes: int = Field(default=8 * 1024**3, gt=0)

    @model_validator(mode="after")
    def destination(self):
        if self.enabled and self.base_url is None:
            raise ValueError("enabled compute requires base_url")
        if self.base_url:
            validate_service_url(self.base_url, "compute.base_url", root_only=True)
        if self.retry_max_s < self.poll_interval_s:
            raise ValueError("retry_max_s must be at least poll_interval_s")
        return self

    @property
    def origin(self):
        return str(self.base_url).rstrip("/") if self.base_url else None

    def token(self):
        return bearer_token(self.token_env, usage="compute worker") if self.enabled else None


def load_compute_config(path):
    with Path(path).open("rb") as stream:
        return ComputeConfig.model_validate(tomllib.load(stream))
