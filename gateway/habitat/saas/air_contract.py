"""Versioned, bounded air estimate transport; independent of sensor events."""
import base64
import hashlib
import math
import struct
from typing import Annotated, Literal
from uuid import UUID
import zlib

from pydantic import BeforeValidator, Field, model_validator

from habitat.common.models import Identifier, Model, Timestamp

AIR_PATH = "/v1/edge/air"
MODEL_ID = "bb6-air-r13"
MODEL_VERSION = "1"
MAX_AIR_BODY = 96 * 1024
MAX_AGE_SECONDS = 30
MAX_FUTURE_SECONDS = 5
FIELD_VALUES = 30 * 20 * 20
FIELD_BYTES = FIELD_VALUES * 4
MAX_COMPRESSED_BYTES = FIELD_BYTES + 1024
RETAIN_RECEIPTS = 256
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Number = Annotated[float, Field(strict=True)]


def _schema(value):
    if type(value) is not int:
        raise ValueError("air schema version must be an integer")
    return value


def _checked_values(values):
    values = list(values)
    if len(values) != FIELD_VALUES:
        raise ValueError("air field must contain 12000 values")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or not -55 <= v <= 125 for v in values):
        raise ValueError("air field must contain finite temperatures in -55..125 degC")
    return values


def encode_field(values):
    """Return (base64 zlib stream, SHA-256 of the uncompressed float32 bytes)."""
    data = struct.pack(f"<{FIELD_VALUES}f", *_checked_values(values))
    return base64.b64encode(zlib.compress(data)).decode("ascii"), hashlib.sha256(data).hexdigest()


def decode_field(field_base64, field_sha256):
    """Decode one exact, bounded zlib stream without accepting trailing data."""
    if not isinstance(field_base64, str) or len(field_base64) > 4 * ((MAX_COMPRESSED_BYTES + 2) // 3):
        raise ValueError("invalid air field encoding length")
    try:
        compressed = base64.b64decode(field_base64, validate=True)
        if not compressed or len(compressed) > MAX_COMPRESSED_BYTES:
            raise ValueError("invalid compressed air field length")
        stream = zlib.decompressobj()
        data = stream.decompress(compressed, FIELD_BYTES + 1)
        if (len(data) != FIELD_BYTES or not stream.eof
                or stream.unused_data or stream.unconsumed_tail):
            raise ValueError("invalid uncompressed air field length or framing")
    except (ValueError, zlib.error):
        raise ValueError("invalid compressed air field") from None
    if hashlib.sha256(data).hexdigest() != field_sha256:
        raise ValueError("air field digest mismatch")
    return _checked_values([value[0] for value in struct.iter_unpack("<f", data)])


class AirRegistrationBinding(Model):
    node_id: Identifier
    enclosure_id: UUID
    geometry_revision: int = Field(strict=True, ge=1)
    placement_revision: int = Field(strict=True, ge=1)


class AirSensor(Model):
    id: Literal["T1", "T2", "T3"]
    label: str = Field(min_length=1, max_length=80)
    xyz_m: tuple[Number, Number, Number]
    value_c: float = Field(strict=True, ge=-55, le=125)

    @model_validator(mode="after")
    def coordinates(self):
        if any(not 0 <= value <= limit for value, limit in zip(self.xyz_m, (.2, .2, .3))):
            raise ValueError("air sensor outside enclosure")
        return self


class AirGrid(Model):
    shape_zyx: tuple[Literal[30], Literal[20], Literal[20]] = (30, 20, 20)
    spacing_m: Literal[.01] = .01
    origin_m: tuple[Literal[.005], Literal[.005], Literal[.005]] = (.005, .005, .005)
    order: Literal["zyx"] = "zyx"


class AirAck(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(_schema)] = 1
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    node_id: Identifier
    estimate_id: UUID
    source_message_id: UUID
    field_sha256: Digest
    outcome: Literal["stored", "duplicate", "superseded"]


class AirEstimate(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(_schema)] = 1
    estimate_id: UUID
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    node_id: Identifier
    source_message_id: UUID
    sampled_at: Timestamp
    generated_at: Timestamp
    geometry_revision: int = Field(strict=True, ge=1)
    placement_revision: int = Field(strict=True, ge=1)
    model_id: Literal["bb6-air-r13"] = MODEL_ID
    model_version: Literal["1"] = MODEL_VERSION
    config_sha256: Digest
    dimensions_m: tuple[Literal[.2], Literal[.2], Literal[.3]] = (.2, .2, .3)
    sensors: list[AirSensor] = Field(min_length=3, max_length=3)
    grid: AirGrid = Field(default_factory=AirGrid)
    encoding: Literal["zlib-f32le-base64"] = "zlib-f32le-base64"
    field_base64: str = Field(min_length=1, max_length=4 * ((MAX_COMPRESSED_BYTES + 2) // 3))
    field_sha256: Digest
    color_range_c: tuple[Number, Number] | None = None
    source_accepted_samples: int | None = Field(default=None, strict=True, ge=0)
    source_gap_resets: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def field_and_provenance(self):
        if {sensor.id for sensor in self.sensors} != {"T1", "T2", "T3"}:
            raise ValueError("three distinct temperature sensors required")
        if len({sensor.xyz_m for sensor in self.sensors}) != 3:
            raise ValueError("distinct sensor coordinates required")
        if (self.sampled_at - self.generated_at).total_seconds() > MAX_FUTURE_SECONDS:
            raise ValueError("estimate precedes source measurement")
        values = self.field_values()
        if self.color_range_c is not None:
            low, high = self.color_range_c
            measured = [sensor.value_c for sensor in self.sensors]
            if not low < high or low > min(*values, *measured) or high < max(*values, *measured):
                raise ValueError("air color scale must contain field and measured temperatures")
        return self

    def field_values(self):
        return decode_field(self.field_base64, self.field_sha256)

    def acknowledgement(self, outcome="stored"):
        fields = set(AirAck.model_fields) - {"outcome"}
        return AirAck.model_validate(dict(self.model_dump(include=fields), outcome=outcome))
