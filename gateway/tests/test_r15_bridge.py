"""Offline MQTT contract tests. No broker, GPIO, ESP or physical output is used."""
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import paho.mqtt.client as mqtt
from pydantic import ValidationError
import pytest

from habitat_gateway.config import Settings
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import Acknowledgement, CommandRequest, Reading, Telemetry
from habitat_gateway.transport import MQTTTransport
from tests.conftest import Clock


SESSION = "11111111-1111-4111-8111-111111111111"
FRESH = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def bridge_settings(settings):
    body = settings.model_dump()
    body.update(transport="mqtt", hardware_outputs_enabled=True)
    for number in (2, 3):
        cage = settings.cages[0].model_dump()
        cage.update(id=f"CAGE-00{number}", node_id=f"ESP32-00{number}")
        body["cages"].append(cage)
    body["r15_bridge"] = {"enabled": True, "outputs_locked": False, "central_cage_id": "CAGE-001",
        "zones": [{"zone": zone, "cage_id": cage, "actuator_id": "mister"}
                  for zone, cage in ((3, "CAGE-001"), (1, "CAGE-002"), (2, "CAGE-003"))]}
    return Settings.model_validate(body)


def connect(settings, clock, monkeypatch):
    monkeypatch.setenv("HABITAT_MQTT_PASSWORD", "offline-test-only")
    transport = MQTTTransport(settings, monotonic=lambda: clock().timestamp())
    transport.client = Mock()
    transport.client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    gateway = Gateway(settings, transport, now=clock)
    transport.gateway = gateway
    transport._connect(transport.client, None, None, SimpleNamespace(is_failure=False), None)
    for cage in settings.cages:
        gateway.ingest(cage.id, Telemetry(message_id=uuid4(), sampled_at=clock(),
            geometry_revision=1, placement_revision=1,
            readings={s.id: Reading(value={"degC": 24, "percent_rh": 65, "lux": 100}[s.unit], quality="valid")
                      for s in cage.sensors}))
    return gateway, transport


@pytest.fixture
def bridge(bridge_settings, monkeypatch):
    clock = Clock()
    gateway, transport = connect(bridge_settings, clock, monkeypatch)
    yield gateway, transport, clock
    gateway.store.close()


def message(transport, kind, payload, retained=False, topic=None):
    transport._message(None, None, SimpleNamespace(topic=topic or f"{transport.r15_base}/{kind}",
        payload=json.dumps(payload).encode(), retain=retained))


def hello(transport, clock, *, session=SESSION, **updates):
    body = dict(schema_version=1, session_id=session,
        command_topic=f"{transport.r15_base}/command/{session}", outputs_locked=False,
        request_mask=0, active_command_id="", gateway_lease_valid=False,
        stop_latched=False, heartbeat_output=False, status_pin_levels={"armed": True, "level": True},
        execution_status="unverified", actual_state=None, observed_at_ms=int(clock().timestamp()*1000))
    body.update(updates)
    return body


def ready(transport, clock, session=SESSION, **updates):
    message(transport, "hello", hello(transport, clock, session=session, **updates))
    transport.step()
    clock.advance(0.01)
    message(transport, "hello", hello(transport, clock, session=session, gateway_lease_valid=True, **updates))


def request(*, action="on", duration=2, request_id=None):
    return CommandRequest(request_id=request_id or uuid4(), actuator_id="mister", action=action,
                          duration_s=duration if action == "on" else 0)


def ack(command, clock, *, status="requested", **updates):
    delivery = command["r15"]
    body = dict(schema_version=1, session_id=delivery["session_id"], command_id=command["command_id"],
        sequence=delivery["sequence"], zone=delivery["zone"], status=status,
        reason="physical_execution_unverified", requested_state=status == "requested" and delivery["action"] == "on",
        duplicate=False, request_hold_ms=delivery["request_hold_ms"], execution_status="unverified",
        actual_state=None, observed_at_ms=int(clock().timestamp()*1000))
    body.update(updates)
    return body


def frames(transport):
    return [call for call in transport.client.publish.call_args_list
            if isinstance(call.args[1], str) and call.args[1].startswith("R15/1 ")]


def test_disabled_by_default_and_explicit_mapping(bridge, settings):
    gateway, transport, clock = bridge
    assert not settings.r15_bridge.enabled and settings.r15_bridge.outputs_locked
    ready(transport, clock)
    def publish(topic, payload, **kwargs):
        fields = payload.split()
        if fields[5] == "on":
            assert gateway.store.command(fields[2])["r15"]["payload"] == payload
        return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    transport.client.publish.side_effect = publish
    command = gateway.send_command("CAGE-001", request(duration=3))
    assert command["status"] == "published"
    fields = frames(transport)[-1].args[1].split(" ")
    assert fields[4:7] == ["3", "on", "3000"]  # Explicit zone, not cage array position.
    assert int(fields[8]) - int(fields[7]) == 5000
    assert command["r15"]["payload"] == frames(transport)[-1].args[1]
    assert command["actual_state"] is None
    call = frames(transport)[-1]
    assert call.kwargs["retain"] is False and call.kwargs["qos"] == 1
    assert call.kwargs["properties"].MessageExpiryInterval == 5
    assert gateway.store.command(command["command_id"])["r15"] == command["r15"]


@pytest.mark.parametrize("change", ["central", "zone", "target", "duplicate_zone", "duplicate_target", "transport"])
def test_invalid_mapping_rejected(bridge_settings, change):
    body = bridge_settings.model_dump()
    config = body["r15_bridge"]
    if change == "central": config["central_cage_id"] = "UNKNOWN"
    if change == "zone": config["zones"][0]["zone"] = 0
    if change == "target": config["zones"][0]["actuator_id"] = "UNKNOWN"
    if change == "duplicate_zone": config["zones"][0]["zone"] = config["zones"][1]["zone"]
    if change == "duplicate_target": config["zones"][0]["cage_id"] = config["zones"][1]["cage_id"]
    if change == "transport": body["transport"] = "simulated"
    with pytest.raises(ValidationError): Settings.model_validate(body)


def test_heartbeat_half_second_nonretained_short_ttl_and_no_repeated_snapshot(bridge):
    _, transport, clock = bridge
    ready(transport, clock)
    first = frames(transport)[0]
    fields = first.args[1].split()
    assert fields[4:7] == ["0", "heartbeat", "0"]
    assert int(fields[8]) - int(fields[7]) == 1000
    assert first.kwargs["retain"] is False and first.kwargs["properties"].MessageExpiryInterval == 1
    transport.step()
    assert len(frames(transport)) == 1
    clock.advance(0.5)
    transport.step()
    assert len(frames(transport)) == 2
    assert int(frames(transport)[1].args[1].split()[3]) > int(fields[3])
    clock.advance(1.5)
    transport.step()
    assert len(frames(transport)) == 2  # Stale hello does not keep a gateway lease alive.


@pytest.mark.parametrize("bad", ["retained", "future", "old", "wrong_topic", "arbitrary_command_topic", "active_mismatch"])
def test_untrusted_hello_cannot_establish_session(bridge, bad):
    _, transport, clock = bridge
    body = hello(transport, clock)
    if bad == "future": body["observed_at_ms"] += 1
    if bad == "old": body["observed_at_ms"] -= 1500
    if bad == "arbitrary_command_topic": body["command_topic"] = "other-store/command"
    if bad == "active_mismatch": body["request_mask"] = 1
    message(transport, "hello", body, retained=bad == "retained", topic="other-store/r15/hello" if bad == "wrong_topic" else None)
    transport.step()
    assert transport.r15_session is None and not frames(transport)


def test_existing_live_lease_requires_new_esp_session(bridge):
    _, transport, clock = bridge
    message(transport, "hello", hello(transport, clock, gateway_lease_valid=True))
    clock.advance(1)
    message(transport, "hello", hello(transport, clock))
    transport.step()
    assert transport.r15_session is None and not frames(transport)
    clock.advance(0.01)
    ready(transport, clock, FRESH)
    assert transport.r15_session == FRESH


@pytest.mark.parametrize("update,reason", [({"outputs_locked": True}, "r15_node_outputs_locked"),
    ({"stop_latched": True}, "r15_stop_latched"),
    ({"status_pin_levels": {"armed": False, "level": True}}, "r15_status_pin_low"),
    ({"gateway_lease_valid": False}, "r15_gateway_lease_missing")])
def test_node_inhibits_on_but_not_off(bridge, update, reason):
    gateway, transport, clock = bridge
    ready(transport, clock)
    clock.advance(0.01)
    message(transport, "hello", hello(transport, clock, gateway_lease_valid=True) | update)
    assert gateway.send_command("CAGE-001", request())["reason"] == reason
    assert gateway.send_command("CAGE-001", request(action="off"))["status"] == "published"


def test_config_locks_and_five_second_request_limit(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    gateway.settings.r15_bridge.outputs_locked = True
    assert gateway.send_command("CAGE-001", request())["reason"] == "r15_outputs_locked"
    gateway.settings.r15_bridge.outputs_locked = False
    gateway.settings.hardware_outputs_enabled = False
    assert gateway.send_command("CAGE-001", request())["reason"] == "hardware_not_commissioned"
    gateway.settings.hardware_outputs_enabled = True
    for duration in (0.0001, 5.001, 6):
        assert gateway.send_command("CAGE-001", request(duration=duration))["reason"] == "r15_request_hold_limit"


@pytest.mark.parametrize("hold_ms", [3001, 5000])
def test_extended_request_ack_and_completion_keep_run_unknown(bridge, hold_ms):
    gateway, transport, clock = bridge
    ready(transport, clock, max_request_hold_ms=5000)
    command = gateway.send_command("CAGE-001", request(duration=hold_ms / 1000))
    assert command["status"] == "published"
    assert frames(transport)[-1].args[1].split()[6] == str(hold_ms)
    assert command["r15"]["request_hold_ms"] == hold_ms
    assert gateway.lease_end(command) == clock() + timedelta(seconds=12)  # TTL 5s + recycle 7s.
    for status in ("requested", "execution_unverified"):
        message(transport, "ack", ack(command, clock, status=status))
        saved = gateway.store.command(command["command_id"])
        assert saved["status"] == status
        assert saved["execution_status"] == "unverified" and saved["actual_state"] is None
        assert gateway.store.observation("CAGE-001", "mister") is None


@pytest.mark.parametrize("capability", [None, 3000])
def test_legacy_capability_rejects_long_request_before_publish_but_allows_off(bridge, capability):
    gateway, transport, clock = bridge
    ready(transport, clock, **({} if capability is None else {"max_request_hold_ms": capability}))
    assert transport.r15_hello.max_request_hold_ms == 3000
    command = gateway.send_command("CAGE-001", request(duration=3.001))
    assert (command["status"], command["reason"]) == ("rejected", "r15_request_hold_unsupported_by_node")
    assert "r15" not in command
    assert not any(call.args[1].split()[5] == "on" for call in frames(transport))
    assert gateway.send_command("CAGE-001", request(action="off"))["status"] == "published"
    assert gateway.send_command("CAGE-001", request(duration=3))["status"] == "published"


@pytest.mark.parametrize("capability", [0, 5001, 5000.0, "5000", True])
def test_invalid_request_capability_cannot_establish_session(bridge, capability):
    _, transport, clock = bridge
    message(transport, "hello", hello(transport, clock, max_request_hold_ms=capability))
    transport.step()
    assert transport.r15_session is None and not frames(transport)


def test_request_capability_never_raises_configured_actuator_limit(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock, max_request_hold_ms=5000)
    next(a for a in gateway.cage("CAGE-001").actuators if a.id == "mister").max_on_s = 3
    command = gateway.send_command("CAGE-001", request(duration=4))
    assert (command["status"], command["reason"]) == ("rejected", "duration_exceeds_limit")
    assert not any(call.args[1].split()[5] == "on" for call in frames(transport))


def test_receipt_completion_and_expiry_keep_actual_unknown_and_shared_lease(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request())
    message(transport, "ack", ack(command, clock))
    assert gateway.store.command(command["command_id"])["status"] == "requested"
    assert gateway.store.observation("CAGE-001", "mister") is None
    assert gateway.send_command("CAGE-002", request())["reason"] == "r15_shared_cycle_reserved"
    message(transport, "ack", ack(command, clock, status="execution_unverified", reason="request_hold_finished"))
    saved = gateway.store.command(command["command_id"])
    assert saved["status"] == "execution_unverified" and saved["actual_state"] is None
    assert gateway.store.latest_on("CAGE-001", "mister")["command_id"] == command["command_id"]
    assert gateway.send_command("CAGE-003", request())["reason"] == "r15_shared_cycle_reserved"
    assert gateway.store.observation("CAGE-001", "mister") is None


@pytest.mark.parametrize("reports_active", [False, True], ids=["hello_pending", "hello_active"])
@pytest.mark.parametrize("duration", [3, 5])
def test_tick_preserves_healthy_r15_request_and_shared_reservation(bridge, reports_active, duration):
    gateway, transport, clock = bridge
    ready(transport, clock, max_request_hold_ms=5000)
    command = gateway.send_command("CAGE-001", request(duration=duration))
    message(transport, "ack", ack(command, clock))
    for _ in range(int((duration - 0.5) * 4)):
        clock.advance(0.25)
        message(transport, "hello", hello(transport, clock, gateway_lease_valid=True, max_request_hold_ms=5000,
            request_mask=(1 << (command["r15"]["zone"] - 1)) if reports_active else 0,
            active_command_id=command["command_id"] if reports_active else ""))
        transport.step()
        gateway.tick()  # Production worker order; its own reservation is not a fault.
        assert [call.args[1].split()[5] for call in frames(transport)
                if call.args[1].split()[5] != "heartbeat"] == ["on"]
        assert gateway.store.command(command["command_id"])["status"] == "requested"
    blocked = gateway.send_command("CAGE-002", request())
    assert blocked["status"] == "rejected"
    assert blocked["reason"] == ("r15_bridge_busy" if reports_active else "r15_shared_cycle_reserved")
    assert gateway.store.latest_on("CAGE-001", "mister")["command_id"] == command["command_id"]
    assert gateway.store.observation("CAGE-001", "mister") is None
    assert gateway.store.command(command["command_id"])["actual_state"] is None


@pytest.mark.parametrize("fault", ["sensor_invalid", "sensor_stale", "level_low", "hello_stale", "node_offline"])
def test_tick_cancels_active_r15_request_on_actual_safety_fault(bridge, fault):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request(duration=3))
    message(transport, "ack", ack(command, clock))
    active = dict(gateway_lease_valid=True, request_mask=1 << (command["r15"]["zone"] - 1),
                  active_command_id=command["command_id"])
    clock.advance(0.25)
    message(transport, "hello", hello(transport, clock, **active))
    transport.step()
    gateway.tick()
    assert not any(call.args[1].split()[5] == "off" for call in frames(transport))

    clock.advance(1.5 if fault == "hello_stale" else 0.5)
    if fault == "sensor_invalid":
        sample = gateway.store.latest_telemetry("CAGE-001")
        sample.pop("received_at")
        sample.update(message_id=str(uuid4()), sampled_at=clock().isoformat())
        sample["readings"]["RH1"] = {"value": None, "quality": "invalid"}
        gateway.ingest("CAGE-001", Telemetry.model_validate(sample))
    elif fault == "sensor_stale":
        gateway.cage("CAGE-001").stale_after_s = 0.5
    elif fault == "level_low":
        active["status_pin_levels"] = {"armed": True, "level": False}
    elif fault == "node_offline":
        gateway.set_node_online("CAGE-001", False)
    if fault != "hello_stale":
        message(transport, "hello", hello(transport, clock, **active))
    transport.step()
    gateway.tick()
    off = gateway.store.latest_command("CAGE-001", "mister")
    assert (off["action"], off["source"], off["status"]) == ("off", "safety", "published")
    assert off["r15"]["zone"] == command["r15"]["zone"]
    assert sum(call.args[1].split()[5] == "off" for call in frames(transport)) == 1
    assert gateway.store.latest_on("CAGE-001", "mister")["command_id"] == command["command_id"]
    assert gateway.store.observation("CAGE-001", "mister") is None
    assert gateway.store.command(command["command_id"])["actual_state"] is None


@pytest.mark.parametrize("fault", ["disconnect", "station_stop"])
def test_active_r15_disconnect_or_stop_never_resumes_or_claims_physical_off(bridge, fault):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request(duration=3))
    message(transport, "ack", ack(command, clock))
    clock.advance(0.25)
    message(transport, "hello", hello(transport, clock, gateway_lease_valid=True,
        request_mask=1 << (command["r15"]["zone"] - 1), active_command_id=command["command_id"]))
    transport.step()
    gateway.tick()
    assert not any(call.args[1].split()[5] == "off" for call in frames(transport))
    if fault == "disconnect":
        transport._disconnect(None, None, None, None, None)
    else:
        commands = gateway.stop_all("CAGE-002")
        stop = next(c for c in commands if c.get("r15"))
        assert (stop["r15"]["action"], stop["r15"]["zone"], stop["status"]) == ("stop", 0, "published")
    heartbeats = sum(call.args[1].split()[5] == "heartbeat" for call in frames(transport))
    clock.advance(0.5)
    transport.step()
    gateway.tick()
    if fault == "disconnect":
        off = gateway.store.latest_command("CAGE-001", "mister")
        assert (off["action"], off["source"], off["status"], off["reason"]) == (
            "off", "safety", "rejected", "transport_offline")
    assert sum(call.args[1].split()[5] == "heartbeat" for call in frames(transport)) == heartbeats
    assert sum(call.args[1].split()[5] == "on" for call in frames(transport)) == 1
    assert gateway.send_command("CAGE-003", request())["status"] == "rejected"
    assert gateway.store.latest_on("CAGE-001", "mister")["command_id"] == command["command_id"]
    assert gateway.store.observation("CAGE-001", "mister") is None
    assert gateway.store.command(command["command_id"])["actual_state"] is None


@pytest.mark.parametrize("changes", [{"session_id": FRESH}, {"sequence": 999}, {"zone": 1},
    {"request_hold_ms": 1}, {"request_hold_ms": 5001}, {"request_hold_ms": "2000"},
    {"command_id": str(uuid4())}, {"actual_state": True},
    {"requested_state": False}, {"status": "applied"}, {"observed_at_ms": 1800000000000}])
def test_ack_scope_fingerprint_and_no_fake_physical_confirmation(bridge, changes):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request())
    message(transport, "ack", ack(command, clock, **changes))
    assert gateway.store.command(command["command_id"])["status"] == "published"
    assert gateway.store.observation("CAGE-001", "mister") is None


def test_standard_ack_and_sensor_telemetry_cannot_claim_r15_state(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request())
    ordinary = Acknowledgement(command_id=command["command_id"], actuator_id="mister", status="applied",
                               applied_state=True, occurred_at=clock())
    assert not gateway.acknowledge("CAGE-001", ordinary)
    body = gateway.store.latest_telemetry("CAGE-001")
    body.pop("received_at")
    body.update(message_id=str(uuid4()), actuators={"mister": True})
    with pytest.raises(ValueError, match="no physical actuator telemetry"):
        gateway.ingest("CAGE-001", Telemetry.model_validate(body))
    with pytest.raises(ValidationError):
        Acknowledgement(command_id=command["command_id"], actuator_id="mister", status="requested",
                        applied_state=True, occurred_at=clock())


def test_stop_sequence_barrier_no_heartbeat_or_new_on_after_stop(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    on = gateway.send_command("CAGE-001", request())
    stopped = gateway.send_command("CAGE-002", request(action="off"), source="stop")
    assert stopped["r15"]["zone"] == 0 and stopped["r15"]["action"] == "stop"
    assert stopped["r15"]["sequence"] > on["r15"]["sequence"]
    assert gateway.send_command("CAGE-003", request())["reason"] == "r15_stop_latched"
    count = len(frames(transport))
    clock.advance(0.5)
    transport.step()
    assert len(frames(transport)) == count
    assert gateway.store.observation("CAGE-001", "mister") is None


def test_station_stop_clears_all_mapped_automatic_modes(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    for cage in gateway.cages:
        gateway.set_mode(cage, "auto")
    commands = gateway.stop_all("CAGE-002")
    assert all(gateway.store.mode(cage) == "manual" for cage in gateway.cages)
    assert [c["r15"]["action"] for c in commands if c.get("r15")] == ["stop"]


def test_retained_ack_and_ambiguous_publish_never_replay(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    req = request()
    transport.client.publish.side_effect = ConnectionError("test network loss")
    command = gateway.send_command("CAGE-001", req)
    assert command["status"] == "interrupted"
    calls = transport.client.publish.call_count
    assert gateway.send_command("CAGE-001", req)["status"] == "interrupted"
    assert transport.client.publish.call_count == calls
    assert gateway.send_command("CAGE-002", request())["reason"] == "r15_shared_cycle_reserved"
    message(transport, "ack", ack(command, clock), retained=True)
    assert gateway.store.command(command["command_id"])["status"] == "interrupted"


def test_requested_timeout_remains_reserved(bridge):
    gateway, transport, clock = bridge
    ready(transport, clock)
    command = gateway.send_command("CAGE-001", request())
    message(transport, "ack", ack(command, clock))
    clock.advance(5)
    gateway.tick()
    assert gateway.store.command(command["command_id"])["status"] == "expired"
    assert gateway.store.latest_on("CAGE-001", "mister")["command_id"] == command["command_id"]


def test_restart_and_broker_reconnect_retire_session_off_still_works(bridge_settings, tmp_path, monkeypatch):
    settings = bridge_settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3")})
    clock = Clock()
    first, old = connect(settings, clock, monkeypatch)
    ready(old, clock)
    command = first.send_command("CAGE-001", request())
    message(old, "ack", ack(command, clock))
    first.store.close()
    second, transport = connect(settings, clock, monkeypatch)
    try:
        assert second.store.command(command["command_id"])["status"] == "interrupted"
        clock.advance(0.01)
        message(transport, "hello", hello(transport, clock))
        transport.step()
        assert transport.r15_session is None and not frames(transport)
        assert second.send_command("CAGE-003", request())["reason"] == "r15_fresh_session_required"
        assert second.send_command("CAGE-003", request(action="off"), source="stop")["status"] == "published"
        clock.advance(0.01)
        ready(transport, clock, FRESH)
        assert transport.r15_session == FRESH
        transport._disconnect(None, None, None, None, None)
        transport._connect(transport.client, None, None, SimpleNamespace(is_failure=False), None)
        clock.advance(0.01)
        message(transport, "hello", hello(transport, clock, session=FRESH))
        assert transport.r15_session is None
    finally:
        second.store.close()
