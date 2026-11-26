"""Version 1 of the Pi-to-SaaS wire contract, shared by the client and reference API."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from .config import CageConfig
from .models import CommandRequest, Identifier, Model, R15_MAX_REQUEST_HOLD_MS, Telemetry

SYNC_PATH = "/v1/edge/sync"
Timestamp = Annotated[datetime, AfterValidator(Telemetry.aware_timestamp)]


class StoredTelemetry(Telemetry):
    received_at: Timestamp


class Observation(Model):
    state: bool
    occurred_at: Timestamp
    source: Literal["telemetry", "node_ack"]


class ActuatorState(Model):
    observed: Observation | None
    on_blocked_reason: str | None
    max_on_s: float = Field(gt=0, le=3600)
    cooldown_s: float = Field(ge=0, le=86400)


class CageState(Model):
    cage_id: Identifier
    node_id: Identifier
    mode: Literal["manual", "auto"]
    transport: Literal["simulated", "mqtt"]
    transport_connected: bool
    telemetry: StoredTelemetry | None
    actuators: dict[Identifier, ActuatorState] = Field(max_length=32)


class CageSnapshot(Model):
    configuration: CageConfig
    state: CageState

    @model_validator(mode="after")
    def references(self):
        if self.configuration.id != self.state.cage_id or self.configuration.node_id != self.state.node_id:
            raise ValueError("configuration and state must identify the same cage/node")
        if set(self.state.actuators) != {a.id for a in self.configuration.actuators}:
            raise ValueError("actuator state must match the cage configuration")
        if self.state.telemetry:
            if not self.state.telemetry.readings.keys() <= {s.id for s in self.configuration.sensors}:
                raise ValueError("snapshot contains an unknown sensor")
            if not self.state.telemetry.actuators.keys() <= self.state.actuators.keys():
                raise ValueError("snapshot contains an unknown actuator")
        return self


class GatewaySnapshot(Model):
    version: str
    transport: Literal["simulated", "mqtt"]
    healthy: bool
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


class R15Delivery(Model):
    """GPIO request delivery binding; not evidence of pump or valve operation."""
    session_id: UUID
    sequence: int = Field(strict=True, ge=1, le=4294967295)
    zone: int = Field(strict=True, ge=0, le=3)
    action: Literal["on", "off", "stop"]
    request_hold_ms: int = Field(strict=True, ge=0, le=R15_MAX_REQUEST_HOLD_MS)
    payload: str = Field(max_length=256)


class CommandRecord(Model):
    schema_version: Literal[1]
    command_id: UUID
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    node_id: Identifier
    actuator_id: Identifier
    action: Literal["on", "off"]
    duration_s: float = Field(ge=0, le=3600)
    created_at: Timestamp
    expires_at: Timestamp
    geometry_revision: int = Field(ge=1)
    placement_revision: int = Field(ge=1)
    source: str
    request: CommandFingerprint
    status: Literal["publishing", "published", "applied", "rejected", "expired", "interrupted",
                    "requested", "execution_unverified"]
    reason: str | None
    sequence: int = Field(ge=1)
    acknowledged_at: Timestamp | None = None
    applied_at: Timestamp | None = None
    r15: R15Delivery | None = None
    execution_status: Literal["unverified"] | None = None
    actual_state: None = Field(default=None, description="Unknown physical state; never inferred from an R15 request ACK.")

    @model_validator(mode="after")
    def references(self):
        if (self.command_id != self.request.request_id or self.cage_id != self.request.cage_id
                or self.source != self.request.source or self.actuator_id != self.request.actuator_id
                or self.action != self.request.action or self.duration_s != self.request.duration_s):
            raise ValueError("command and original request differ")
        if self.expires_at <= self.created_at:
            raise ValueError("command expiry must follow creation")
        if self.status in ("requested", "execution_unverified") and self.r15 is None:
            raise ValueError("R15 request status requires its delivery binding")
        if self.r15 is not None:
            if self.execution_status != "unverified" or self.status == "applied" or self.applied_at is not None:
                raise ValueError("R15 delivery does not prove physical execution")
        elif self.execution_status is not None:
            raise ValueError("R15 execution metadata requires its delivery binding")
        return self


class EventEnvelope(Model):
    schema_version: Literal[1]
    event_id: UUID
    event_sequence: int = Field(ge=1)
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
                self.payload.site_id, self.payload.gateway_id, self.payload.cage_id):
            raise ValueError("command identity differs from event identity")
        return self


SyncEvent = Annotated[TelemetryEvent | CommandEvent, Field(discriminator="kind")]


class SyncRequest(Model):
    schema_version: Literal[1]
    site_id: Identifier
    gateway_id: Identifier
    sent_at: Timestamp
    gateway: GatewaySnapshot
    events: list[SyncEvent] = Field(max_length=1000)

    @model_validator(mode="after")
    def identity_and_order(self):
        if any((e.site_id, e.gateway_id) != (self.site_id, self.gateway_id) for e in self.events):
            raise ValueError("event identity differs from batch identity")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("duplicate event IDs in batch")
        sequences = [e.event_sequence for e in self.events]
        if sequences != sorted(set(sequences)):
            raise ValueError("events must have distinct, increasing sequence numbers")
        return self


class SyncAck(Model):
    schema_version: Literal[1]
    site_id: Identifier
    gateway_id: Identifier
    accepted_event_ids: list[UUID] = Field(max_length=1000)
