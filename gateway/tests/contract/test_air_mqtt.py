"""Receive-only air viewer contracts; fake broker client, no network or device outputs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from habitat.digital_twin.air import mqtt as air_mqtt
from habitat_gateway.config import MQTTConfig
from habitat_gateway.transport import node_topic


NOW = datetime(2026, 10, 24, 10, 20, 0, tzinfo=timezone.utc)


class RecordingState:
    max_sample_age = 30.0
    max_future_skew = 5.0

    def __init__(self):
        self.cfg = {"cage_id": "CAGE-001", "sensors": [{"id": key} for key in ("T1", "T2", "T3")]}
        self.events = []
        self.marks = []
        self.accept = True

    def ingest(self, event, *, now):
        self.events.append((deepcopy(event), now))
        return self.accept

    def mark(self, status, reason):
        self.marks.append((status, reason))


@pytest.fixture
def air_settings(settings, monkeypatch):
    monkeypatch.setenv("TEST_AIR_MQTT_PASSWORD", "test-only-mqtt-password")
    return settings.model_copy(update={"transport": "mqtt", "mqtt": MQTTConfig(
        host="127.0.0.1", port=8883, username="test-air-user",
        password_env="TEST_AIR_MQTT_PASSWORD", tls_ca="/test/certs/existing-ca.pem")})


@pytest.fixture
def subscriber(air_settings):
    state, client = RecordingState(), Mock()
    cage = air_settings.cages[0]
    receiver = air_mqtt.AirSubscriber(air_settings, cage, state, client=client, now=lambda: NOW)
    return receiver, state, client, air_settings, cage


def payload(cage, *, sampled_at=NOW, message_id=None):
    return {"schema_version": 1, "data_source": "sensor", "message_id": message_id or str(uuid4()),
            "sampled_at": sampled_at.isoformat(), "geometry_revision": cage.geometry_revision,
            "placement_revision": cage.placement_revision,
            "readings": {"T1": {"value": 22.44, "quality": "valid"},
                         "RH1": {"value": 56.26, "quality": "valid"},
                         "T2": {"value": 22.25, "quality": "valid"},
                         "T3": {"value": 22.437, "quality": "valid"}}, "actuators": {}}


def deliver(rig, data, *, retained=False, kind="telemetry", topic=None):
    receiver, _, client, settings, cage = rig
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    message = SimpleNamespace(topic=topic or node_topic(settings, cage, kind), payload=raw, retain=retained)
    receiver._message(client, None, message)


def test_reuses_configured_credentials_and_ca_without_device_publications(subscriber):
    receiver, _, client, settings, cage = subscriber
    client.username_pw_set.assert_called_once_with(settings.mqtt.username, "test-only-mqtt-password")
    client.tls_set.assert_called_once_with(ca_certs=settings.mqtt.tls_ca)
    assert client.on_connect == receiver._connect
    assert client.on_disconnect == receiver._disconnect
    assert client.on_message == receiver._message
    receiver.start()
    client.connect_async.assert_called_once_with(settings.mqtt.host, settings.mqtt.port, keepalive=30)
    client.loop_start.assert_called_once()
    receiver._connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert set(client.subscribe.call_args.args[0]) == {
        (node_topic(settings, cage, "telemetry"), 1), (node_topic(settings, cage, "status"), 1)}
    receiver.close()
    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()
    client.publish.assert_not_called()
    client.will_set.assert_not_called()
    client.tls_insecure_set.assert_not_called()


def test_new_subscriber_ids_are_unique_and_do_not_take_over_gateway_session(air_settings, monkeypatch):
    clients = [Mock(), Mock()]
    factory = Mock(side_effect=clients)
    monkeypatch.setattr(air_mqtt.mqtt, "Client", factory)
    for _ in clients:
        air_mqtt.AirSubscriber(air_settings, air_settings.cages[0], RecordingState(), now=lambda: NOW)
    ids = [call.kwargs["client_id"] for call in factory.call_args_list]
    assert len(set(ids)) == 2
    assert all(identity.startswith("air-") for identity in ids)
    assert all(identity != f"{air_settings.site_id}-{air_settings.gateway_id}" for identity in ids)


def test_missing_password_fails_before_connecting(air_settings, monkeypatch):
    monkeypatch.delenv(air_settings.mqtt.password_env)
    client = Mock()
    with pytest.raises(ValueError):
        air_mqtt.AirSubscriber(air_settings, air_settings.cages[0], RecordingState(), client=client)
    client.connect_async.assert_not_called()
    client.publish.assert_not_called()


def test_live_gateway_compatible_temperature_triplet_reaches_viewer(subscriber):
    _, state, client, _, cage = subscriber
    data = payload(cage, message_id="92b67bb3-e418-4712-a117-8768b02ab922")
    deliver(subscriber, data)
    assert len(state.events) == 1
    event, now = state.events[0]
    assert now == NOW
    assert event["message_id"] == data["message_id"]
    assert datetime.fromisoformat(event["sampled_at"].replace("Z", "+00:00")) == NOW
    assert {key: event["readings"][key] for key in ("T1", "T2", "T3")} == {
        key: data["readings"][key] for key in ("T1", "T2", "T3")}
    client.publish.assert_not_called()


@pytest.mark.parametrize("mutation", [
    "simulation", "missing_source", "missing_schema", "boolean_schema", "geometry", "placement", "missing_temperature", "invalid_temperature",
    "out_of_range", "future", "bad_uuid", "bad_timestamp", "nan", "infinity",
])
def test_invalid_input_holds_display_without_ingesting(subscriber, mutation):
    _, state, client, _, cage = subscriber
    data = payload(cage)
    if mutation == "simulation":
        data["data_source"] = "simulation"
    elif mutation == "missing_source":
        del data["data_source"]
    elif mutation == "missing_schema":
        del data["schema_version"]
    elif mutation == "boolean_schema":
        data["schema_version"] = True
    elif mutation == "geometry":
        data["geometry_revision"] += 1
    elif mutation == "placement":
        data["placement_revision"] += 1
    elif mutation == "missing_temperature":
        del data["readings"]["T2"]
    elif mutation == "invalid_temperature":
        data["readings"]["T2"] = {"value": None, "quality": "disconnected"}
    elif mutation == "out_of_range":
        data["readings"]["T3"]["value"] = next(s.max_value for s in cage.sensors if s.id == "T3") + 1
    elif mutation == "future":
        data["sampled_at"] = (NOW + timedelta(seconds=state.max_future_skew + 1)).isoformat()
    elif mutation == "bad_uuid":
        data["message_id"] = "not-a-uuid"
    elif mutation == "bad_timestamp":
        data["sampled_at"] = "2026-10-24T10:20:00"  # Missing timezone.
    elif mutation == "nan":
        data["readings"]["T1"]["value"] = float("nan")
    elif mutation == "infinity":
        data["readings"]["T1"]["value"] = float("inf")
    deliver(subscriber, data)
    assert state.events == []
    assert state.marks and state.marks[-1][0] == "held"
    client.publish.assert_not_called()


def test_delayed_measurement_reaches_display_with_original_time_and_id(subscriber):
    _, state, client, _, cage = subscriber
    data = payload(cage, sampled_at=NOW - timedelta(seconds=55))
    deliver(subscriber, data)
    assert len(state.events) == 1
    event, received = state.events[0]
    assert event['message_id'] == data['message_id']
    assert datetime.fromisoformat(event['sampled_at'].replace('Z', '+00:00')) == NOW - timedelta(seconds=55)
    assert received == NOW
    assert state.marks == []
    client.publish.assert_not_called()


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"{}", b"x" * 65537,
                                 b'{"nested":' + b'[' * 10000 + b'0' + b']' * 10000 + b'}'],
                         ids=["bad_json", "array", "missing_fields", "oversized", "excessive_nesting"])
def test_malformed_and_oversized_packets_do_not_escape_callback(subscriber, raw):
    _, state, _, _, _ = subscriber
    deliver(subscriber, raw)
    assert state.events == []


def test_invalid_humidity_does_not_discard_valid_air_temperatures(subscriber):
    _, state, _, _, cage = subscriber
    data = payload(cage)
    data["readings"]["RH1"] = {"value": None, "quality": "invalid"}
    deliver(subscriber, data)
    assert len(state.events) == 1


def test_retained_and_duplicate_telemetry_cannot_be_counted_as_new_measurements(subscriber):
    _, state, _, _, cage = subscriber
    data = payload(cage)
    deliver(subscriber, data, retained=True)
    assert state.events == []
    deliver(subscriber, data)
    deliver(subscriber, data)
    assert len(state.events) == 1


def test_state_rejected_sample_does_not_poison_duplicate_cache(subscriber):
    _, state, _, _, cage = subscriber
    data = payload(cage)
    state.accept = False
    deliver(subscriber, data)
    state.accept = True
    deliver(subscriber, data)
    assert len(state.events) == 2
    deliver(subscriber, data)
    assert len(state.events) == 2


def test_model_exception_holds_display_without_stopping_receipt_or_leaking_input(subscriber, monkeypatch, caplog):
    receiver, state, client, _, cage = subscriber
    data = payload(cage)
    ingest = state.ingest
    failure_detail = "test-only-private-model-input"
    monkeypatch.setattr(state, "ingest", Mock(side_effect=RuntimeError(failure_detail)))
    deliver(subscriber, data)
    assert state.events == []
    assert state.marks[-1] == ("held", "air_model_update_failed")
    assert data["message_id"] not in receiver.seen
    assert failure_detail not in caplog.text
    monkeypatch.setattr(state, "ingest", ingest)
    deliver(subscriber, data)
    assert len(state.events) == 1
    assert data["message_id"] in receiver.seen
    client.publish.assert_not_called()


def test_duplicate_cache_stays_bounded_and_evicted_packets_still_reach_state_validation(air_settings):
    state, client, clock = RecordingState(), Mock(), [NOW]
    cage = air_settings.cages[0]
    receiver = air_mqtt.AirSubscriber(air_settings, cage, state, client=client, now=lambda: clock[0])
    rig = receiver, state, client, air_settings, cage
    first = payload(cage, message_id=str(UUID(int=1)))
    for index in range(4097):
        clock[0] = NOW + timedelta(seconds=index)
        deliver(rig, payload(cage, sampled_at=clock[0], message_id=str(UUID(int=index + 1))))
    assert len(state.events) == 4097
    assert len(receiver.seen) == 4096
    assert first["message_id"] not in receiver.seen
    state.accept = False  # AirState's timestamp/identity guards own this rejection.
    deliver(rig, first)
    assert len(state.events) == 4098
    assert len(receiver.seen) == 4096
    assert first['message_id'] not in receiver.seen


def test_restored_record_live_promotion_and_new_equal_values(air_settings):
    from pathlib import Path
    from habitat.digital_twin.air.service import AirState

    state = AirState(Path(__file__).resolve().parents[2] / 'configs/examples/air-viewer.json')
    clock = [NOW]
    client, cage = Mock(), air_settings.cages[0]
    receiver = air_mqtt.AirSubscriber(air_settings, cage, state, client=client, now=lambda: clock[0])
    rig = receiver, state, client, air_settings, cage
    raw = payload(cage)
    sample = air_mqtt.validate_telemetry(raw, cage, NOW)
    canonical = sample.model_dump(mode='json')
    state.restore(dict(event='telemetry', retained=False, fresh_unique=True,
        message_id=str(sample.message_id), sampled_at=canonical['sampled_at'],
        readings=canonical['readings'], payload=canonical), now=NOW)
    previous_field = state.snapshot(NOW)['field']
    deliver(rig, raw)
    promoted = state.snapshot(NOW)
    assert promoted['data_origin'] == 'mqtt' and promoted['fresh']
    assert (promoted['accepted_samples'], promoted['history_samples'], promoted['live_samples']) == (1, 1, 1)
    assert promoted['field'] == previous_field
    deliver(rig, raw)
    assert state.snapshot(NOW)['fresh']
    assert state.snapshot(NOW)['accepted_samples'] == 1
    clock[0] += timedelta(seconds=5)
    newer = payload(cage, sampled_at=clock[0])
    assert newer['readings'] == raw['readings']
    deliver(rig, newer)
    current = state.snapshot(clock[0])
    assert current['fresh'] and current['message_id'] == newer['message_id']
    assert (current['accepted_samples'], current['history_samples'], current['live_samples']) == (2, 1, 2)
    # Even after eviction, a delayed duplicate cannot replace a newer field.
    receiver.seen.clear()
    deliver(rig, raw)
    assert state.snapshot(clock[0])['message_id'] == newer['message_id']
    assert state.snapshot(clock[0])['accepted_samples'] == 2
    client.publish.assert_not_called()


def test_other_cage_and_command_topics_cannot_update_viewer(subscriber):
    _, state, _, settings, cage = subscriber
    data = payload(cage)
    deliver(subscriber, data, topic=node_topic(settings, cage, "telemetry").replace("CAGE-001", "CAGE-OTHER"))
    deliver(subscriber, data, kind="command")
    assert state.events == [] and state.marks == []


def test_failed_connection_and_reconnection_remain_receive_only(subscriber):
    receiver, state, client, _, cage = subscriber
    receiver._connect(client, None, None, SimpleNamespace(is_failure=True), None)
    client.subscribe.assert_not_called()
    receiver._connect(client, None, None, SimpleNamespace(is_failure=False), None)
    data = payload(cage)
    deliver(subscriber, data)
    assert len(state.events) == 1
    receiver._disconnect(client, None, None, SimpleNamespace(is_failure=False), None)
    receiver._connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert client.subscribe.call_count == 2
    deliver(subscriber, data)
    assert len(state.events) == 1, "reconnection must not forget an already accepted message ID"
    deliver(subscriber, payload(cage, sampled_at=NOW + timedelta(seconds=1)))
    assert len(state.events) == 2
    client.publish.assert_not_called()
    client.will_set.assert_not_called()


def test_retained_status_cannot_set_live_online_state(subscriber):
    _, state, _, _, _ = subscriber
    deliver(subscriber, {"online": True}, retained=True, kind="status")
    assert state.events == [] and state.marks == []
    deliver(subscriber, {"online": False}, kind="status")
    assert state.events or state.marks
    assert all(mark[0] != "live" for mark in state.marks)
