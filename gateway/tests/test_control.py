from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from habitat_gateway.config import Settings
from habitat_gateway.gateway import Conflict, Gateway
from habitat_gateway.models import Acknowledgement, CommandRequest, Reading, Telemetry
from habitat_gateway.transport import SimulatedTransport


def request(actuator="heater", action="on", duration=5, request_id=None):
    return CommandRequest(request_id=request_id or uuid4(), actuator_id=actuator,
                          action=action, duration_s=duration if action == "on" else 0)


def test_publish_is_not_execution_and_duplicate_has_no_side_effect(rig):
    gateway, node, clock = rig
    req = request()
    command = gateway.send_command("CAGE-001", req)
    assert command["status"] == "published"
    assert node.nodes["CAGE-001"]["states"]["heater"] is False
    assert gateway.send_command("CAGE-001", req) == command
    assert len(node.sent) == 1
    node.step()
    assert gateway.store.command(command["command_id"])["status"] == "applied"
    assert node.nodes["CAGE-001"]["states"]["heater"] is True
    clock.advance(6)
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False


def test_idempotency_key_cannot_be_repurposed(rig):
    gateway, node, _ = rig
    req = request()
    gateway.send_command("CAGE-001", req)
    with pytest.raises(Conflict):
        gateway.send_command("CAGE-001", request(action="off", request_id=req.request_id))
    assert len(node.sent) == 1


@pytest.mark.parametrize("sensor", ["T1", "T2", "T3", "T4", "T5"])
def test_any_hot_probe_blocks_heater(rig, sensor):
    gateway, node, _ = rig
    node.patch_readings("CAGE-001", {sensor: Reading(value=28, quality="valid")})
    command = gateway.send_command("CAGE-001", request())
    assert command["status"] == "rejected"
    assert command["reason"] == f"guard_maximum:{sensor}"
    assert node.sent == []


@pytest.mark.parametrize("quality", ["crc_error", "disconnected", "invalid"])
def test_sensor_failure_blocks_on_but_permits_off(rig, quality):
    gateway, node, _ = rig
    node.patch_readings("CAGE-001", {"T3": Reading(quality=quality)})
    assert gateway.send_command("CAGE-001", request())["reason"] == "sensor_unavailable:T3"
    assert gateway.send_command("CAGE-001", request(action="off"))["status"] == "published"


def test_stale_telemetry_blocks_on_and_requests_off(rig):
    gateway, node, clock = rig
    gateway.send_command("CAGE-001", request(duration=30))
    node.step()
    clock.advance(16)
    assert gateway.send_command("CAGE-001", request(actuator="fan"))["reason"] == "stale_telemetry"
    gateway.tick()
    assert node.sent[-1]["action"] == "off"
    assert node.sent[-1]["source"] == "safety"


def test_offline_transport_and_offline_node_block_on(rig):
    gateway, node, _ = rig
    node.connected = False
    assert gateway.send_command("CAGE-001", request())["reason"] == "transport_offline"
    node.connected = True
    gateway.set_node_online("CAGE-001", False)
    assert gateway.send_command("CAGE-001", request())["reason"] == "node_offline"


def test_max_runtime_cooldown_and_no_concurrent_on(rig):
    gateway, node, clock = rig
    assert gateway.send_command("CAGE-001", request(duration=31))["reason"] == "duration_exceeds_limit"
    gateway.send_command("CAGE-001", request(duration=5))
    node.step()
    assert gateway.send_command("CAGE-001", request())["reason"] == "previous_lease_or_cooldown_active"
    clock.advance(7)
    node.step()
    assert gateway.send_command("CAGE-001", request())["reason"] == "previous_lease_or_cooldown_active"
    clock.advance(4)
    node.step()
    assert gateway.send_command("CAGE-001", request())["status"] == "published"


def test_node_lease_and_interlock_survive_network_loss(rig):
    gateway, node, clock = rig
    gateway.send_command("CAGE-001", request(duration=5))
    node.step()
    node.connected = False
    clock.advance(6)
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False
    node.connected = True
    clock.advance(5)
    node.step()
    gateway.send_command("CAGE-001", request(duration=30))
    node.step()
    node.connected = False
    node.nodes["CAGE-001"]["readings"]["T1"] = Reading(value=29, quality="valid")
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False


def test_expired_command_is_never_executed(rig):
    gateway, node, clock = rig
    command = gateway.send_command("CAGE-001", request())
    clock.advance(11)
    gateway.tick()
    assert gateway.store.command(command["command_id"])["status"] == "expired"
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False
    assert gateway.store.command(command["command_id"])["status"] == "expired"


def test_stop_supersedes_delayed_on_and_disables_auto(rig):
    gateway, node, _ = rig
    gateway.send_command("CAGE-001", request())
    gateway.set_mode("CAGE-001", "auto")
    assert gateway.send_command("CAGE-001", request(actuator="fan"))["status"] == "rejected"
    commands = gateway.stop_all("CAGE-001")
    assert len(commands) == 4
    node.pending.reverse()  # deliberately deliver OFF ahead of an earlier ON
    node.step()
    assert not any(node.nodes["CAGE-001"]["states"].values())
    assert gateway.store.mode("CAGE-001") == "manual"
    assert any(ack.reason == "local_stale_sequence" for ack in node.seen.values())


def test_repeated_on_delivery_does_not_extend_node_lease(rig):
    gateway, node, clock = rig
    gateway.send_command("CAGE-001", request(duration=5))
    wire = node.sent[0]
    node.step()
    clock.advance(4)
    node.publish("CAGE-001", wire)
    node.step()
    clock.advance(2)
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False


def test_hysteresis_retains_demand_between_thresholds(rig):
    gateway, node, clock = rig
    node.patch_readings("CAGE-001", {"T3": Reading(value=21, quality="valid")})
    gateway.set_mode("CAGE-001", "auto")
    gateway.tick()
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is True
    node.patch_readings("CAGE-001", {"T3": Reading(value=23, quality="valid")})
    clock.advance(26)
    node.step()
    gateway.tick()
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is True
    clock.advance(1)
    node.patch_readings("CAGE-001", {"T3": Reading(value=24, quality="valid")})
    gateway.tick()
    node.step()
    assert node.nodes["CAGE-001"]["states"]["heater"] is False


def test_ack_cannot_change_wrong_device_or_reverse_state(rig):
    gateway, node, clock = rig
    command = gateway.send_command("CAGE-001", request())
    ack = Acknowledgement(command_id=command["command_id"], actuator_id="fan", status="applied",
                          applied_state=True, occurred_at=clock())
    assert not gateway.acknowledge("CAGE-001", ack)
    ack = ack.model_copy(update={"actuator_id": "heater", "applied_state": False})
    assert not gateway.acknowledge("CAGE-001", ack)
    ack = ack.model_copy(update={"applied_state": True})
    assert not gateway.acknowledge("CAGE-001", ack, retained=True)
    ack = ack.model_copy(update={"occurred_at": clock() + timedelta(seconds=10)})
    assert not gateway.acknowledge("CAGE-001", ack)
    assert gateway.store.command(command["command_id"])["status"] == "published"


def sample(rig, **updates):
    gateway, _, clock = rig
    body = gateway.store.latest_telemetry("CAGE-001")
    body.pop("received_at")
    body.update(message_id=str(uuid4()), sampled_at=clock(), **updates)
    return Telemetry.model_validate(body)


def test_telemetry_dedup_retained_out_of_order_and_revisions(rig):
    gateway, node, clock = rig
    old = sample(rig)
    assert not gateway.ingest("CAGE-001", old, retained=True)
    clock.advance(1)
    new = sample(rig, placement_revision=2)
    assert gateway.ingest("CAGE-001", new)
    assert not gateway.ingest("CAGE-001", new)
    assert gateway.ingest("CAGE-001", old)
    assert gateway.store.latest_telemetry("CAGE-001")["message_id"] == str(new.message_id)
    assert gateway.send_command("CAGE-001", request())["reason"] == "revision_mismatch"


def test_future_nonfinite_missing_and_out_of_range_readings(rig):
    gateway, node, clock = rig
    body = sample(rig).model_copy(update={"sampled_at": clock() + timedelta(seconds=10)})
    with pytest.raises(ValueError, match="future"):
        gateway.ingest("CAGE-001", body)
    with pytest.raises(ValidationError):
        Reading(value=float("nan"), quality="valid")
    with pytest.raises(ValidationError):
        Reading(quality="valid")
    with pytest.raises(ValueError, match="out-of-range"):
        node.patch_readings("CAGE-001", {"T1": Reading(value=85, quality="valid")})
    body = sample(rig)
    body.readings.pop("T5")
    gateway.ingest("CAGE-001", body)
    assert gateway.send_command("CAGE-001", request())["reason"] == "sensor_unavailable:T5"


def test_restart_preserves_history_and_idempotency_without_replay(tmp_path, settings):
    settings = settings.model_copy(update={"database": str(tmp_path / "edge.sqlite3")})
    node = SimulatedTransport(settings)
    first = Gateway(settings, node)
    node.start(first)
    req = request()
    command = first.send_command("CAGE-001", req)
    first.set_mode("CAGE-001", "auto")
    first.store.close()
    fresh_node = SimulatedTransport(settings)
    second = Gateway(settings, fresh_node)
    try:
        assert second.store.mode("CAGE-001") == "manual"
        assert second.store.command(command["command_id"])["status"] == "interrupted"
        assert second.send_command("CAGE-001", req)["status"] == "interrupted"
        assert fresh_node.sent == []
        assert second.store.latest_telemetry("CAGE-001")
    finally:
        second.store.close()


def test_cages_and_acknowledgements_are_isolated(settings):
    second = settings.cages[0].model_copy(update={"id": "CAGE-002", "node_id": "ESP32-002"})
    settings = settings.model_copy(update={"cages": [settings.cages[0], second]})
    node = SimulatedTransport(settings)
    gateway = Gateway(settings, node)
    node.start(gateway)
    try:
        command = gateway.send_command("CAGE-001", request())
        ack = Acknowledgement(command_id=command["command_id"], actuator_id="heater", status="applied",
                              applied_state=True, occurred_at=gateway.now())
        assert not gateway.acknowledge("CAGE-002", ack)
        node.step()
        assert node.nodes["CAGE-001"]["states"]["heater"] is True
        assert node.nodes["CAGE-002"]["states"]["heater"] is False
    finally:
        gateway.store.close()


def test_config_rejects_policy_and_sensor_reference_errors(settings):
    body = settings.model_dump()
    body["cages"][0]["policies"][0]["off_threshold"] = 20
    with pytest.raises(ValidationError, match="on_threshold"):
        Settings.model_validate(body)
    body = settings.model_dump()
    body["cages"][0]["actuators"][0]["required_sensors"] = ["unknown"]
    with pytest.raises(ValidationError, match="unknown required sensor"):
        Settings.model_validate(body)
