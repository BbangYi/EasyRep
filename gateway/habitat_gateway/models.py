from datetime import datetime
from typing import Literal
from uuid import UUID
import unicodedata

from pydantic import Field, model_validator, field_validator
from habitat.common.models import Identifier, Model, aware_timestamp, utcnow


# ESP request-signal hold limit; the original Pico's separate RUN limit stays 3s.
R15_MAX_REQUEST_HOLD_MS = 5000


class Reading(Model):
    value: float | None = None
    quality: Literal["valid", "invalid", "crc_error", "disconnected"]

    @model_validator(mode="after")
    def valid_value(self):
        if self.quality == "valid" and self.value is None:
            raise ValueError("valid samples require a value")
        if self.quality != "valid" and self.value is not None:
            raise ValueError("invalid samples must have value=null")
        return self


class Telemetry(Model):
    schema_version: Literal[1] = 1
    data_source: Literal["sensor", "simulation"] = "sensor"
    message_id: UUID
    sampled_at: datetime
    geometry_revision: int = Field(ge=1)
    placement_revision: int = Field(ge=1)
    readings: dict[Identifier, Reading] = Field(max_length=64)
    actuators: dict[Identifier, bool] = Field(default_factory=dict, max_length=32)

    @field_validator("sampled_at")
    @classmethod
    def aware_timestamp(cls, value):
        return aware_timestamp(value)


class CommandRequest(Model):
    request_id: UUID
    actuator_id: Identifier
    action: Literal["on", "off"]
    duration_s: float = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def duration_matches_action(self):
        if self.action == "on" and self.duration_s <= 0:
            raise ValueError("ON requires a positive node-enforced duration_s")
        if self.action == "off" and self.duration_s != 0:
            raise ValueError("OFF requires duration_s=0")
        return self


class Acknowledgement(Model):
    command_id: UUID
    actuator_id: Identifier
    status: Literal["applied", "rejected", "requested", "execution_unverified"]
    applied_state: bool | None = None
    occurred_at: datetime
    reason: str = Field(default="", max_length=256)

    @field_validator("occurred_at")
    @classmethod
    def aware_timestamp(cls, value):
        return Telemetry.aware_timestamp(value)

    @model_validator(mode="after")
    def applied_requires_state(self):
        if self.status == "applied" and self.applied_state is None:
            raise ValueError("applied acknowledgement requires applied_state")
        if self.status in ("requested", "execution_unverified") and self.applied_state is not None:
            raise ValueError("unverified acknowledgements cannot claim applied_state")
        return self


class R15PinLevels(Model):
    armed: bool = Field(strict=True)
    level: bool = Field(strict=True)


class R15Hello(Model):
    schema_version: Literal[1]
    session_id: UUID
    command_topic: str = Field(max_length=255)
    # Legacy R15/1 firmware omits this capability and only accepts up to 3000ms.
    max_request_hold_ms: int = Field(default=3000, strict=True, ge=1, le=R15_MAX_REQUEST_HOLD_MS)
    outputs_locked: bool = Field(strict=True)
    request_mask: Literal[0, 1, 2, 4]
    active_command_id: str = Field(max_length=36)
    gateway_lease_valid: bool = Field(strict=True)
    stop_latched: bool = Field(strict=True)
    heartbeat_output: bool = Field(strict=True)
    status_pin_levels: R15PinLevels
    execution_status: Literal["unverified"]
    actual_state: None
    observed_at_ms: int = Field(strict=True, ge=1700000000000, le=9007199254740991)


class R15Ack(Model):
    schema_version: Literal[1]
    session_id: UUID
    command_id: UUID
    sequence: int = Field(strict=True, ge=1, le=4294967295)
    zone: int = Field(strict=True, ge=0, le=3)
    status: Literal["requested", "rejected", "execution_unverified"]
    reason: str = Field(max_length=256)
    requested_state: bool = Field(strict=True)
    duplicate: bool = Field(strict=True)
    request_hold_ms: int = Field(strict=True, ge=0, le=R15_MAX_REQUEST_HOLD_MS)
    execution_status: Literal["unverified"]
    actual_state: None
    observed_at_ms: int = Field(strict=True, ge=1700000000000, le=9007199254740991)


class ModeRequest(Model):
    mode: Literal["manual", "auto"]


class EnclosureRequest(Model):
    name: str = Field(min_length=1, max_length=80)
    species: str = Field(min_length=1, max_length=120)
    form_factor: Literal["vertical", "horizontal", "aquatic"]

    @field_validator("name", "species")
    @classmethod
    def readable_text(cls, value):
        value = unicodedata.normalize("NFC", " ".join(value.split()))
        if not value or not value.isprintable():
            raise ValueError("name and species must contain readable text")
        return value
