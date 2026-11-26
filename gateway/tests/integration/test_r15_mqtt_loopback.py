"""Real loopback MQTT/API transport only: packet fixtures are not ESP/Pico or GPIO simulation."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import paho.mqtt.client as mqtt
import pytest

from habitat_gateway.api import create_app
from habitat_gateway.config import Settings
from habitat_gateway.models import Reading, Telemetry, utcnow
from habitat_gateway.transport import MQTTTransport, node_topic


def wait_until(predicate, label):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"Loopback MQTT timed out: {label}")


@pytest.fixture
def loopback_broker(tmp_path):
    executable = shutil.which("mosquitto")
    if executable is None and Path("/usr/sbin/mosquitto").is_file():
        executable = "/usr/sbin/mosquitto"
    if executable is None:
        pytest.skip("Loopback MQTT requires an existing mosquitto executable; none was installed")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with TemporaryDirectory(prefix="r15-loopback-", dir=tmp_path) as directory:
        config = Path(directory) / "mosquitto.conf"
        config.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\nlog_type error\n")
        process = subprocess.Popen([executable, "-c", str(config)], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True)
        try:
            def ready():
                if process.poll() is not None:
                    raise AssertionError(f"Temporary Mosquitto failed: {process.stderr.read(1024)}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                        return True
                except OSError:
                    return False
            wait_until(ready, "temporary broker startup")
            yield port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stderr.close()


@pytest.mark.parametrize("hold_ms, advertised_limit", [(2000, None), (5000, 5000)],
                         ids=["legacy-hello-2s", "extended-hello-5s"])
def test_r15_mqtt_api_delivery_unknown_state_and_reconnect(loopback_broker, settings, monkeypatch,
                                                          hold_ms, advertised_limit):
    # Only a disposable broker and synthetic packets exist behind these test-only unlocks.
    body = settings.model_dump()
    body.update(site_id=f"TEST-R15-{uuid4().hex}", gateway_id="TEST-PI", transport="mqtt",
                database=":memory:", hardware_outputs_enabled=True)
    second = deepcopy(body["cages"][0])
    second.update(id="CAGE-002", node_id="TEST-NODE-002")
    body["cages"].append(second)
    for cage in body["cages"]:
        next(a for a in cage["actuators"] if a["id"] == "mister")["max_on_s"] = 5
    body["mqtt"].update(host="127.0.0.1", port=loopback_broker, tls_ca=None,
                        password_env="HABITAT_TEST_LOOPBACK_MQTT_PASSWORD")
    body["r15_bridge"] = dict(enabled=True, outputs_locked=False, central_cage_id="CAGE-001",
        zones=[dict(zone=i, cage_id=cage, actuator_id="mister")
               for i, cage in enumerate(("CAGE-001", "CAGE-002"), 1)])
    settings = Settings.model_validate(body)
    assert not settings.cloud.enabled and not settings.environment.enabled and not settings.cameras
    monkeypatch.setenv(settings.mqtt.password_env, "test-only-local-broker")
    token = "loopback-test-only-api-token-over-32-characters"
    monkeypatch.setenv("HABITAT_API_TOKEN", token)
    transport = MQTTTransport(settings)
    subscribed, unsubscribed = threading.Event(), threading.Event()
    transport.client.on_subscribe = lambda *args: subscribed.set()
    transport.client.on_unsubscribe = lambda *args: unsubscribed.set()
    processed = []
    original_message = transport.client.on_message

    def observe(client, userdata, message):
        original_message(client, userdata, message)
        processed.append((message.topic, bytes(message.payload), message.retain))

    transport.client.on_message = observe
    packets, peer_ready = [], threading.Event()
    peer = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fixture-{uuid4().hex}", protocol=mqtt.MQTTv5)
    peer.on_subscribe = lambda *args: peer_ready.set()
    peer.on_message = lambda client, userdata, message: packets.append(message)
    peer.connect("127.0.0.1", loopback_broker, keepalive=20)
    peer.loop_start()

    def publish(topic, value, *, retain=False):
        encoded = json.dumps(value).encode()
        delivery = peer.publish(topic, encoded, qos=1, retain=retain)
        delivery.wait_for_publish(timeout=2)
        assert delivery.is_published()
        return encoded

    def command_frames(action):
        return [m for m in list(packets) if m.payload.startswith(b"R15/1 ")
                and m.payload.decode().split()[5] == action]

    try:
        wait_until(peer.is_connected, "packet fixture connection")
        # Retain-as-published also detects an erroneous retained live command.
        peer.subscribe(f"{transport.r15_base}/#", options=mqtt.SubscribeOptions(qos=1, retainAsPublished=True))
        wait_until(peer_ready.is_set, "packet fixture subscription")
        with TestClient(create_app(settings, run_worker=False, transport=transport),
                        headers={"Authorization": f"Bearer {token}"}) as api:
            gateway = api.app.state.gateway
            wait_until(subscribed.is_set, "gateway subscriptions")
            for cage in settings.cages:
                sample = Telemetry(message_id=uuid4(), sampled_at=utcnow(), geometry_revision=1,
                    placement_revision=1, readings={s.id: Reading(value={"degC": 24, "percent_rh": 65, "lux": 100}[s.unit],
                    quality="valid") for s in cage.sensors})
                publish(node_topic(settings, cage, "telemetry"), sample.model_dump(mode="json"))
            wait_until(lambda: all(gateway.store.latest_telemetry(c.id) for c in settings.cages), "fixture telemetry")
            session = str(uuid4())

            def hello(lease=False, **updates):
                return dict(schema_version=1, session_id=session,
                    command_topic=f"{transport.r15_base}/command/{session}", outputs_locked=False,
                    request_mask=0, active_command_id="", gateway_lease_valid=lease,
                    stop_latched=False, heartbeat_output=False, status_pin_levels={"armed": True, "level": True},
                    execution_status="unverified", actual_state=None, observed_at_ms=int(time.time()*1000)) | (
                        {} if advertised_limit is None else {"max_request_hold_ms": advertised_limit}) | updates

            publish(f"{transport.r15_base}/hello", hello())
            wait_until(lambda: transport.r15_session == session, "fresh session")
            transport.step()
            wait_until(lambda: command_frames("heartbeat"), "gateway heartbeat")
            heartbeat = command_frames("heartbeat")[0]
            fields = heartbeat.payload.decode().split()
            assert not heartbeat.retain and heartbeat.properties.MessageExpiryInterval == 1
            assert fields[4:7] == ["0", "heartbeat", "0"] and int(fields[8])-int(fields[7]) == 1000
            endpoint = "/v1/cages/CAGE-001/commands"
            if advertised_limit == 5000:
                # A legacy peer lacks this optional field and defaults to REQ 3s.
                # A locally configured 5s limit must not silently shorten/replay ON.
                legacy = hello(True)
                legacy.pop("max_request_hold_ms")
                received = publish(f"{transport.r15_base}/hello", legacy)
                wait_until(lambda: (f"{transport.r15_base}/hello", received, False) in processed,
                           "legacy capability hello processed")
                assert transport.r15_hello.max_request_hold_ms == 3000
                rejected = api.post(endpoint, json=dict(request_id=str(uuid4()), actuator_id="mister",
                                                       action="on", duration_s=5))
                assert rejected.status_code == 409, rejected.text
                assert rejected.json()["reason"] == "r15_request_hold_unsupported_by_node"
                assert "r15" not in rejected.json() and not command_frames("on")
            publish(f"{transport.r15_base}/hello", hello(True))
            wait_until(lambda: transport.r15_hello.gateway_lease_valid, "declared fixture lease")
            wait_until(lambda: transport.r15_hello.max_request_hold_ms == (advertised_limit or 3000),
                       "declared request hold capability")
            request = dict(request_id=str(uuid4()), actuator_id="mister", action="on", duration_s=hold_ms / 1000)
            response = api.post(endpoint, json=request)
            assert response.status_code == 202, response.text
            command = response.json()
            wait_until(lambda: command_frames("on"), "ON request")
            frame = command_frames("on")[0]
            assert frame.topic == f"{transport.r15_base}/command/{session}"
            assert not frame.retain and 0 < frame.properties.MessageExpiryInterval <= 5
            assert frame.payload.decode() == command["r15"]["payload"]
            assert frame.payload.decode().split()[6] == str(hold_ms)
            assert command["r15"]["request_hold_ms"] == hold_ms
            assert command["actual_state"] is None and command["execution_status"] == "unverified"
            assert api.post(endpoint, json=request).json() == command
            transport.step()
            gateway.tick()  # The worker must not cancel an ON because of its own reservation.
            assert gateway.store.latest_command("CAGE-001", "mister")["command_id"] == command["command_id"]
            assert api.get(f"/v1/commands/{command['command_id']}").json()["status"] == "published"

            def ack(status="requested", **updates):
                return dict(schema_version=1, session_id=session, command_id=command["command_id"],
                    sequence=command["r15"]["sequence"], zone=1, status=status, reason="fixture_only",
                    requested_state=status == "requested", duplicate=False, request_hold_ms=hold_ms,
                    execution_status="unverified", actual_state=None, observed_at_ms=int(time.time()*1000)) | updates

            ack_topic = f"{transport.r15_base}/ack"
            bad = publish(ack_topic, ack(session_id=str(uuid4())))
            wait_until(lambda: (ack_topic, bad, False) in processed, "wrong-session ACK processed")
            assert api.get(f"/v1/commands/{command['command_id']}").json()["status"] == "published"
            # Force an actual broker retained delivery, rather than calling the adapter directly.
            transport.client.unsubscribe(ack_topic)
            wait_until(unsubscribed.is_set, "ACK unsubscribe")
            retained = publish(ack_topic, ack(), retain=True)
            transport.client.subscribe(ack_topic, qos=1)
            wait_until(lambda: (ack_topic, retained, True) in processed, "retained ACK processed")
            assert api.get(f"/v1/commands/{command['command_id']}").json()["status"] == "published"
            for status in ("requested", "execution_unverified"):
                publish(ack_topic, ack(status))
                wait_until(lambda: api.get(f"/v1/commands/{command['command_id']}").json()["status"] == status, status)
                stored = api.get(f"/v1/commands/{command['command_id']}").json()
                assert stored["actual_state"] is None and stored["execution_status"] == "unverified"
                assert "applied_at" not in stored
                assert api.get("/v1/cages/CAGE-001").json()["actuators"]["mister"]["observed"] is None
                if status == "requested":
                    duplicate = publish(ack_topic, ack(duplicate=True))
                    wait_until(lambda: (ack_topic, duplicate, False) in processed, "duplicate ACK processed")
                    assert api.get(f"/v1/commands/{command['command_id']}").json() == stored
                    assert api.post(endpoint, json=request).json() == stored
                    active = publish(f"{transport.r15_base}/hello", hello(True,
                        request_mask=1, active_command_id=command["command_id"]))
                    wait_until(lambda: (f"{transport.r15_base}/hello", active, False) in processed,
                               "active request hello processed")
                    assert transport.r15_hello.active_command_id == command["command_id"]
                    transport.step()
                    gateway.tick()  # A node reporting that same request active is not a safety fault either.
                    assert gateway.store.latest_command("CAGE-001", "mister")["command_id"] == command["command_id"]
                    assert api.get(f"/v1/commands/{command['command_id']}").json()["status"] == "requested"

                    invalid = gateway.store.latest_telemetry("CAGE-001")
                    invalid.pop("received_at")
                    invalid.update(message_id=str(uuid4()), sampled_at=utcnow().isoformat())
                    invalid["readings"]["RH1"] = {"value": None, "quality": "invalid"}
                    publish(node_topic(settings, settings.cages[0], "telemetry"), invalid)
                    wait_until(lambda: gateway.store.latest_telemetry("CAGE-001")["message_id"] == invalid["message_id"],
                               "invalid sensor telemetry processed")
                    mister = next(a for a in settings.cages[0].actuators if a.id == "mister")
                    assert gateway.unsafe_reason("CAGE-001", mister) == "sensor_unavailable:RH1"
                    transport.step()
                    gateway.tick()
                    wait_until(lambda: command_frames("off"), "sensor fault safety OFF")
                    safety = gateway.store.latest_command("CAGE-001", "mister")
                    assert safety["source"] == "safety" and safety["action"] == "off" and safety["status"] == "published"
                    assert command_frames("off")[0].payload.decode() == safety["r15"]["payload"]
                    assert not command_frames("off")[0].retain
            assert len(command_frames("on")) == 1  # Includes a complete broker/ACK roundtrip after duplicate API.
            assert len(command_frames("off")) == 1 and not command_frames("stop")

            transport.client.disconnect()
            wait_until(lambda: not transport.connected, "gateway disconnect")
            transport.client.loop_stop()
            assert transport.r15_session is None
            subscribed.clear()
            transport.client.reconnect()
            transport.client.loop_start()
            wait_until(subscribed.is_set, "gateway reconnect subscription")
            old_session = publish(f"{transport.r15_base}/hello", hello())
            wait_until(lambda: (f"{transport.r15_base}/hello", old_session, False) in processed, "old session after reconnect")
            assert transport.r15_session is None
            before = len(command_frames("heartbeat"))
            transport.step()
            blocked = api.post("/v1/cages/CAGE-002/commands", json={**request, "request_id": str(uuid4())})
            assert blocked.status_code == 409 and blocked.json()["reason"] == "r15_fresh_session_required"
            # Same gateway socket FIFO: observe this barrier before claiming no delayed replay.
            barrier_topic = f"{transport.r15_base}/fixture_barrier"
            transport.client.publish(barrier_topic, "reconnect_checked", qos=1).wait_for_publish(timeout=2)
            wait_until(lambda: any(m.topic == barrier_topic for m in list(packets)), "reconnect delivery barrier")
            assert len(command_frames("on")) == 1 and len(command_frames("heartbeat")) == before
    finally:
        peer.disconnect()
        peer.loop_stop()
