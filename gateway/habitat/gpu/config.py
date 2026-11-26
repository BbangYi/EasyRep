"""Server-only configuration; ComputeConfig.schema.json describes the Pi client."""

import os
from pathlib import Path
import tomllib
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, StrictStr, model_validator

from habitat.gpu.contracts import ComputeLimits, Identifier


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    site_id: Identifier
    gateway_id: Identifier
    cage_ids: Annotated[list[Identifier], Field(min_length=1)]
    token_env: Annotated[StrictStr, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")] = "HABITAT_GPU_TOKEN"
    token: SecretStr | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def credentials(self) -> Self:
        value = self.token.get_secret_value() if self.token is not None else os.environ.get(self.token_env, "")
        if len(value) < 32 or not all(33 <= ord(c) <= 126 for c in value):
            raise ValueError("GPU token must contain at least 32 printable ASCII characters without spaces")
        self.token = SecretStr(value)
        if len(set(self.cage_ids)) != len(self.cage_ids):
            raise ValueError("cage_ids must be unique")
        return self


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    storage_dir: Path = Path("var/data/gpu")
    host: StrictStr = "127.0.0.1"
    port: Annotated[StrictInt, Field(ge=1, le=65535)] = 8100
    credentials: Annotated[list[Credential], Field(min_length=1)]
    limits: ComputeLimits = Field(default_factory=ComputeLimits)
    backend: dict[str, Any] = Field(default_factory=lambda: {"name": "not_configured"})

    @model_validator(mode="after")
    def service_constraints(self) -> Self:
        if self.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("bind to loopback and expose HTTPS through Tailscale Serve")
        if self.limits.max_concurrent_jobs != 1:
            raise ValueError("this release supports one GPU job at a time")
        tokens = [c.token.get_secret_value() for c in self.credentials]
        if len(tokens) != len(set(tokens)):
            raise ValueError("each credential scope requires its own token")
        return self


def load_config(path: str | Path) -> Config:
    with Path(path).open("rb") as source:
        data = tomllib.load(source)
    credentials = data.get("credentials", [])
    for credential in credentials if isinstance(credentials, list) else []:
        if isinstance(credential, dict) and "token" in credential:
            raise ValueError("store credentials in environment variables, not TOML")
    config = Config.model_validate(data)
    config.storage_dir = config.storage_dir.expanduser().resolve()
    return config
