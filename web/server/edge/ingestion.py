"""Persist a Pi batch and acknowledge only after its transaction commits."""

import hashlib
import json
import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import Binding, CommandState, CurrentState, Event, Gateway, Measurement

logger = logging.getLogger(__name__)


class IngestError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def fingerprint(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_measurement(gateway, enclosure, payload, event=None):
    row, created = Measurement.objects.select_related("event").get_or_create(
        gateway=gateway, enclosure=enclosure, message_id=payload["message_id"],
        defaults={
            "sampled_at": payload["sampled_at"], "payload": payload, "event": event,
            "received_at": event.received_at if event else timezone.now(),
        },
    )
    if not created and event and (
        row.event_id is None or event.event_sequence > row.event.event_sequence
    ):
        # A late Pi event enriches the same measurement, preserving its first receipt.
        row.event, row.payload, row.sampled_at = event, payload, payload["sampled_at"]
        row.save(update_fields=["event", "payload", "sampled_at"])


def ingest(batch, credential_digest):
    with transaction.atomic():
        gateway = (
            Gateway.objects.select_for_update()
            .select_related("store")
            .filter(token_digest=credential_digest, active=True)
            .first()
        )
        if gateway is None:
            raise IngestError(
                401, "invalid_token", "A registered Pi bearer token is required"
            )
        if (batch.site_id, batch.gateway_id) != (
            gateway.store.edge_site_id,
            gateway.edge_gateway_id,
        ):
            raise IngestError(
                403, "gateway_scope_denied", "Token does not own this site/gateway"
            )
        bindings = {
            b.enclosure.edge_cage_id: b
            for b in Binding.objects.filter(gateway=gateway).select_related("enclosure")
        }
        previous_snapshot = gateway.snapshot if isinstance(gateway.snapshot, dict) else {}
        previous_cages = {
            cage["configuration"]["id"]
            for cage in previous_snapshot.get("cages", [])
            if isinstance(cage, dict)
            and isinstance(cage.get("configuration"), dict)
            and isinstance(cage["configuration"].get("id"), str)
        }
        retired_cages = {
            cage_id
            for cage_id in previous_snapshot.get("retired_cage_ids", [])
            if isinstance(cage_id, str)
        } | (previous_cages - set(bindings))
        known_snapshots = [
            snapshot
            for snapshot in batch.gateway.cages
            if snapshot.configuration.id in bindings
        ]
        known_events = [event for event in batch.events if event.cage_id in bindings]
        retired_snapshots = [
            snapshot
            for snapshot in batch.gateway.cages
            if snapshot.configuration.id in retired_cages
        ]
        retired_events = [
            event for event in batch.events if event.cage_id in retired_cages
        ]
        unbound_cages = (
            {snapshot.configuration.id for snapshot in batch.gateway.cages}
            | {event.cage_id for event in batch.events}
        ) - bindings.keys()
        unknown_cages = unbound_cages - retired_cages
        cages = {snapshot.configuration.id for snapshot in known_snapshots} | {
            event.cage_id for event in known_events
        }
        if unknown_cages or not (cages or retired_snapshots or retired_events) or any(
            bindings[c].enclosure.store_id != gateway.store_id for c in cages
        ):
            raise IngestError(
                403, "cage_scope_denied", "Token does not own every submitted cage"
            )
        if retired_events:
            logger.warning(
                "Acknowledging retired cage events from %s without storing them: %s",
                gateway.edge_gateway_id,
                ", ".join(sorted({event.cage_id for event in retired_events})),
            )
        for snapshot in known_snapshots:
            node_id = bindings[snapshot.configuration.id].node_id
            if node_id and snapshot.configuration.node_id != node_id:
                raise IngestError(
                    403, "node_scope_denied", "Node differs from registration"
                )
        for event in known_events:
            if event.kind == "command.updated":
                node_id = bindings[event.cage_id].node_id
                if node_id and event.payload.node_id != node_id:
                    raise IngestError(
                        403, "node_scope_denied", "Node differs from registration"
                    )
        simulated = (
            batch.gateway.transport == "simulated"
            or any(
                c.state.telemetry and c.state.telemetry.data_source == "simulation"
                for c in known_snapshots
            )
            or any(
                e.kind == "telemetry.recorded" and e.payload.data_source == "simulation"
                for e in known_events
            )
        )
        if simulated and not gateway.allow_simulation:
            raise IngestError(
                403,
                "simulation_disabled",
                "Simulation is not allowed for this registration",
            )

        existing = Event.objects.filter(gateway=gateway).filter(
            Q(event_id__in=[e.event_id for e in known_events])
            | Q(event_sequence__in=[e.event_sequence for e in known_events])
        )
        by_id, by_sequence = {}, {}
        for row in existing:
            by_id[row.event_id] = row
            by_sequence[row.event_sequence] = row
        pending = []
        for event in known_events:
            body = event.model_dump(mode="json")
            digest = fingerprint(body)
            old = by_id.get(event.event_id) or by_sequence.get(event.event_sequence)
            if old:
                if (
                    old.event_id != event.event_id
                    or old.event_sequence != event.event_sequence
                    or old.digest != digest
                ):
                    raise IngestError(
                        409,
                        "event_conflict",
                        "An event ID or sequence has different stored content",
                    )
                continue
            pending.append(
                Event(
                    gateway=gateway,
                    enclosure=bindings[event.cage_id].enclosure,
                    event_id=event.event_id,
                    event_sequence=event.event_sequence,
                    kind=event.kind,
                    created_at=event.created_at,
                    sampled_at=(
                        event.payload.sampled_at
                        if event.kind == "telemetry.recorded"
                        else None
                    ),
                    digest=digest,
                    body=body,
                )
            )
        Event.objects.bulk_create(pending)
        for event in pending:
            if event.kind == "telemetry.recorded":
                save_measurement(gateway, event.enclosure, event.body["payload"], event)
        for snapshot in known_snapshots:
            if snapshot.state.telemetry:
                save_measurement(gateway, bindings[snapshot.configuration.id].enclosure,
                                 snapshot.state.telemetry.model_dump(mode="json"))

        states = {
            c: CurrentState.objects.get_or_create(enclosure=bindings[c].enclosure)[0]
            for c in cages
        }
        # Snapshot time and measurement time are deliberately independent.
        for snapshot in known_snapshots:
            state = states[snapshot.configuration.id]
            if state.snapshot_sent_at is None or batch.sent_at > state.snapshot_sent_at:
                state.configuration = snapshot.configuration.model_dump(mode="json")
                state.mode = snapshot.state.mode
                state.actuators = {
                    key: value.model_dump(mode="json")
                    for key, value in snapshot.state.actuators.items()
                }
                state.snapshot_sent_at = batch.sent_at
            telemetry = snapshot.state.telemetry
            if telemetry and (
                state.sampled_at is None or telemetry.sampled_at > state.sampled_at
            ):
                state.telemetry = telemetry.model_dump(mode="json")
                state.sampled_at = telemetry.sampled_at
                state.telemetry_sequence = None
        for event in known_events:
            state = states[event.cage_id]
            if event.kind == "telemetry.recorded":
                newer = (
                    state.sampled_at is None
                    or event.payload.sampled_at > state.sampled_at
                )
                same_time_later_event = (
                    event.payload.sampled_at == state.sampled_at
                    and event.event_sequence > (state.telemetry_sequence or 0)
                )
                if newer or same_time_later_event:
                    state.telemetry = event.payload.model_dump(mode="json")
                    state.sampled_at = event.payload.sampled_at
                    state.telemetry_sequence = event.event_sequence
            else:
                command, created = CommandState.objects.get_or_create(
                    gateway=gateway,
                    command_id=event.payload.command_id,
                    defaults={
                        "enclosure": bindings[event.cage_id].enclosure,
                        "event_sequence": event.event_sequence,
                        "body": event.payload.model_dump(mode="json"),
                    },
                )
                if (
                    not created
                    and command.enclosure_id != bindings[event.cage_id].enclosure_id
                ):
                    raise IngestError(
                        409,
                        "command_conflict",
                        "Command identity belongs to another cage",
                    )
                if not created and event.event_sequence > command.event_sequence:
                    command.event_sequence, command.body = (
                        event.event_sequence,
                        event.payload.model_dump(mode="json"),
                    )
                    command.save(update_fields=["event_sequence", "body"])
        for state in states.values():
            state.save()
        if gateway.snapshot_sent_at is None or batch.sent_at > gateway.snapshot_sent_at:
            gateway.snapshot = batch.gateway.model_copy(
                update={"cages": known_snapshots}
            ).model_dump(mode="json")
            gateway.snapshot["retired_cage_ids"] = sorted(retired_cages)
            gateway.snapshot_sent_at = batch.sent_at
        gateway.last_received_at = timezone.now()
        gateway.save(update_fields=["snapshot", "snapshot_sent_at", "last_received_at"])
    return {
        "schema_version": 1,
        "site_id": batch.site_id,
        "gateway_id": batch.gateway_id,
        "accepted_event_ids": [
            str(event.event_id)
            for event in batch.events
            if event.cage_id in bindings or event.cage_id in retired_cages
        ],
    }
