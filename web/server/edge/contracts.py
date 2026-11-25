"""Pi → SaaS v1 contract, adapted from HabitatOS_SaaS_API_v1 (Pi 0.3.0).
Only wire models are reused. No gateway/worker runtime is imported.
Numeric/bool fields are strict; timestamps and UUIDs retain JSON string parsing.
"""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictFloat,
    StrictBool,
)

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware_timestamp(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return value.astimezone(timezone.utc)


def timestamp_input(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("timestamp must be an ISO datetime string")
    return value


Timestamp = Annotated[
    datetime, BeforeValidator(timestamp_input), AfterValidator(aware_timestamp)
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def integer_version(value):
    if type(value) is not int:
        raise ValueError("schema_version must be an integer")
    return value


from typing import Literal
from uuid import UUID
from pydantic import model_validator, field_validator


class Reading(Model):
    value: StrictFloat | None = None
    quality: Literal["valid", "invalid", "crc_error", "disconnected"]

    @model_validator(mode="after")
    def valid_value(self):
        if self.quality == "valid" and self.value is None:
            raise ValueError("valid samples require a value")
        if self.quality != "valid" and self.value is not None:
            raise ValueError("invalid samples must have value=null")
        return self


class Telemetry(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(integer_version)] = 1
    data_source: Literal["sensor", "simulation"] = "sensor"
    message_id: UUID
    sampled_at: Timestamp
    geometry_revision: StrictInt = Field(ge=1)
    placement_revision: StrictInt = Field(ge=1)
    readings: dict[Identifier, Reading] = Field(max_length=64)
    actuators: dict[Identifier, StrictBool] = Field(default_factory=dict, max_length=32)

    @field_validator("sampled_at")
    @classmethod
    def aware_timestamp(cls, value):
        return aware_timestamp(value)


class CommandRequest(Model):
    request_id: UUID
    actuator_id: Identifier
    action: Literal["on", "off"]
    duration_s: StrictFloat = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def duration_matches_action(self):
        if self.action == "on" and self.duration_s <= 0:
            raise ValueError("ON requires a positive node-enforced duration_s")
        if self.action == "off" and self.duration_s != 0:
            raise ValueError("OFF requires duration_s=0")
        return self


class SensorConfig(Model):
    id: Identifier
    unit: Literal["degC", "percent_rh", "lux"]
    min_value: StrictFloat
    max_value: StrictFloat

    @model_validator(mode="after")
    def bounds(self):
        if self.min_value >= self.max_value:
            raise ValueError("sensor min_value must be below max_value")
        return self


class Guard(Model):
    sensor_id: Identifier
    minimum: StrictFloat | None = None
    maximum: StrictFloat | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("guard needs a minimum or maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum >= self.maximum
        ):
            raise ValueError("guard minimum must be below maximum")
        return self


class ActuatorConfig(Model):
    id: Identifier
    max_on_s: StrictFloat = Field(gt=0, le=3600)
    cooldown_s: StrictFloat = Field(default=0, ge=0, le=86400)
    required_sensors: list[Identifier] = Field(min_length=1)
    guards: list[Guard] = Field(default_factory=list)


class Policy(Model):
    actuator_id: Identifier
    sensor_id: Identifier
    direction: Literal["below", "above"]
    on_threshold: StrictFloat
    off_threshold: StrictFloat
    duration_s: StrictFloat = Field(gt=0)

    @model_validator(mode="after")
    def hysteresis(self):
        if self.direction == "below" and self.on_threshold >= self.off_threshold:
            raise ValueError("below policy requires on_threshold < off_threshold")
        if self.direction == "above" and self.on_threshold <= self.off_threshold:
            raise ValueError("above policy requires on_threshold > off_threshold")
        return self


class CageConfig(Model):
    id: Identifier
    node_id: Identifier
    geometry_revision: StrictInt = Field(default=1, ge=1)
    placement_revision: StrictInt = Field(default=1, ge=1)
    stale_after_s: StrictFloat = Field(default=15, gt=0, le=300)
    sensors: list[SensorConfig] = Field(min_length=1, max_length=64)
    actuators: list[ActuatorConfig] = Field(min_length=1, max_length=32)
    policies: list[Policy] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        sensors = {s.id: s for s in self.sensors}
        actuators = {a.id: a for a in self.actuators}
        if len(sensors) != len(self.sensors) or len(actuators) != len(self.actuators):
            raise ValueError("duplicate sensor/actuator IDs")
        for actuator in self.actuators:
            if not set(actuator.required_sensors) <= sensors.keys():
                raise ValueError("unknown required sensor")
            for guard in actuator.guards:
                if guard.sensor_id not in actuator.required_sensors:
                    raise ValueError("guard sensors must also be required sensors")
        targets = set()
        for policy in self.policies:
            if policy.actuator_id not in actuators or policy.sensor_id not in sensors:
                raise ValueError("unknown policy actuator/sensor")
            if policy.sensor_id not in actuators[policy.actuator_id].required_sensors:
                raise ValueError("policy sensor must be a required sensor")
            if policy.duration_s > actuators[policy.actuator_id].max_on_s:
                raise ValueError("policy duration exceeds actuator limit")
            if policy.actuator_id in targets:
                raise ValueError("only one policy per actuator")
            targets.add(policy.actuator_id)
        return self


SYNC_PATH = "/v1/edge/sync"


class StoredTelemetry(Telemetry):
    received_at: Timestamp


class Observation(Model):
    state: StrictBool
    occurred_at: Timestamp
    source: Literal["telemetry", "node_ack"]


class ActuatorState(Model):
    observed: Observation | None
    on_blocked_reason: str | None
    max_on_s: StrictFloat = Field(gt=0, le=3600)
    cooldown_s: StrictFloat = Field(ge=0, le=86400)


class CageState(Model):
    cage_id: Identifier
    node_id: Identifier
    mode: Literal["manual", "auto"]
    transport: Literal["simulated", "mqtt"]
    transport_connected: StrictBool
    telemetry: StoredTelemetry | None
    actuators: dict[Identifier, ActuatorState] = Field(max_length=32)


class CageSnapshot(Model):
    configuration: CageConfig
    state: CageState

    @model_validator(mode="after")
    def references(self):
        if (
            self.configuration.id != self.state.cage_id
            or self.configuration.node_id != self.state.node_id
        ):
            raise ValueError("configuration and state must identify the same cage/node")
        if set(self.state.actuators) != {a.id for a in self.configuration.actuators}:
            raise ValueError("actuator state must match the cage configuration")
        if self.state.telemetry:
            if not self.state.telemetry.readings.keys() <= {
                s.id for s in self.configuration.sensors
            }:
                raise ValueError("snapshot contains an unknown sensor")
            if not self.state.telemetry.actuators.keys() <= self.state.actuators.keys():
                raise ValueError("snapshot contains an unknown actuator")
        return self


class GatewaySnapshot(Model):
    version: str
    transport: Literal["simulated", "mqtt"]
    healthy: StrictBool
    cages: list[CageSnapshot] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self):
        if len({c.configuration.id for c in self.cages}) != len(self.cages):
            raise ValueError("duplicate cage IDs")
        if len({c.configuration.node_id for c in self.cages}) != len(self.cages):
            raise ValueError("duplicate node IDs")
        if any(c.state.transport != self.transport for c in self.cages):
            raise ValueError("cage transport must match gateway transport")
        return self


class CommandFingerprint(CommandRequest):
    cage_id: Identifier
    source: str


class CommandRecord(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(integer_version)]
    command_id: UUID
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    node_id: Identifier
    actuator_id: Identifier
    action: Literal["on", "off"]
    duration_s: StrictFloat = Field(ge=0, le=3600)
    created_at: Timestamp
    expires_at: Timestamp
    geometry_revision: StrictInt = Field(ge=1)
    placement_revision: StrictInt = Field(ge=1)
    source: str
    request: CommandFingerprint
    status: Literal[
        "publishing", "published", "applied", "rejected", "expired", "interrupted"
    ]
    reason: str | None
    sequence: StrictInt = Field(ge=1)
    acknowledged_at: Timestamp | None = None
    applied_at: Timestamp | None = None

    @model_validator(mode="after")
    def references(self):
        if (
            self.command_id != self.request.request_id
            or self.cage_id != self.request.cage_id
            or self.source != self.request.source
            or self.actuator_id != self.request.actuator_id
            or self.action != self.request.action
            or self.duration_s != self.request.duration_s
        ):
            raise ValueError("command and original request differ")
        if self.expires_at <= self.created_at:
            raise ValueError("command expiry must follow creation")
        return self


class EventEnvelope(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(integer_version)]
    event_id: UUID
    event_sequence: StrictInt = Field(ge=1, le=9223372036854775807)
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    created_at: Timestamp


class TelemetryEvent(EventEnvelope):
    kind: Literal["telemetry.recorded"]
    payload: StoredTelemetry


class CommandEvent(EventEnvelope):
    kind: Literal["command.updated"]
    payload: CommandRecord

    @model_validator(mode="after")
    def identity(self):
        if (self.site_id, self.gateway_id, self.cage_id) != (
            self.payload.site_id,
            self.payload.gateway_id,
            self.payload.cage_id,
        ):
            raise ValueError("command identity differs from event identity")
        return self


SyncEvent = Annotated[TelemetryEvent | CommandEvent, Field(discriminator="kind")]


class SyncRequest(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(integer_version)]
    site_id: Identifier
    gateway_id: Identifier
    sent_at: Timestamp
    gateway: GatewaySnapshot
    events: list[SyncEvent] = Field(max_length=1000)

    @model_validator(mode="after")
    def identity_and_order(self):
        if any(
            (e.site_id, e.gateway_id) != (self.site_id, self.gateway_id)
            for e in self.events
        ):
            raise ValueError("event identity differs from batch identity")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("duplicate event IDs in batch")
        sequences = [e.event_sequence for e in self.events]
        if sequences != sorted(set(sequences)):
            raise ValueError("events must have distinct, increasing sequence numbers")
        return self


class SyncAck(Model):
    schema_version: Annotated[Literal[1], BeforeValidator(integer_version)]
    site_id: Identifier
    gateway_id: Identifier
    accepted_event_ids: list[UUID] = Field(max_length=1000)
