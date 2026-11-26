"""Real lease controller with in-memory MQTT only; never contacts hardware."""
import hashlib
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from habitat.control.ir import Config, ControlLock, cancellation_token, request_local_off
from habitat.control.ir_web import IRNode, NodeConfig, RequestError, state_path

BASE = "habitat/v1/SITE-TEST/cages/CAGE-TEST/nodes/NODE-TEST"
SESSION = "11111111-1111-4111-8111-111111111111"
SESSION2 = "22222222-2222-4222-8222-222222222222"
MQTT = Config("mqtt.test", 8883, "/unused-test-ca", BASE, "TEST_USER", "TEST_PASSWORD")


def until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Timed out waiting for fake MQTT/controller"


class Broker:
    def __init__(self):
        self.clients, self.frames = [], []
        self.session, self.gpio, self.locked = SESSION, False, False
        self.send_hello = True
        self.lock = threading.RLock()

    def factory(self, config, monitor, **kwargs):
        client = Client(self, monitor)
        with self.lock:
            self.clients.append(client)
        return client

    def hello(self, monitor):
        if self.send_hello:
            monitor.accept(BASE + "/ir/hello", json.dumps({"schema_version": 1,
                "session_id": self.session, "command_topic": f"{BASE}/ir/command/{self.session}",
                "outputs_locked": self.locked, "gpio_requested_on": self.gpio,
                "actual_ir_on": None, "max_lease_ms": 5000}).encode())

    def broadcast(self):
        with self.lock:
            for client in self.clients:
                if client.connected:
                    self.hello(client.monitor)

    def disconnect_all(self):
        with self.lock:
            for client in self.clients:
                client.disconnect()


class Client:
    def __init__(self, broker, monitor):
        self.broker, self.monitor = broker, monitor
        self.connected = False
        self.stopped = threading.Event()
        self.thread = None

    def connect(self, *args, **kwargs):
        self.connected = True
        self.monitor.connection(True)
        self.broker.hello(self.monitor)

    def loop_start(self):
        def pump():
            while not self.stopped.wait(0.03):
                if self.connected:
                    self.broker.hello(self.monitor)
        self.thread = threading.Thread(target=pump, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.connected = False
        self.monitor.connection(False)

    def loop_stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(1)

    def publish(self, topic, payload, **kwargs):
        fields = payload.split()
        self.broker.frames.append(fields)
        self.broker.gpio = fields[5] == "on"
        self.monitor.accept(BASE + "/ir/ack", json.dumps({"schema_version": 1,
            "session_id": fields[1], "command_id": fields[2], "sequence": int(fields[3]),
            "reason": "ir_requested_on" if fields[5] == "on" else "off_requested",
            "gpio_requested_on": self.broker.gpio, "actual_ir_on": None}).encode())
        self.broker.broadcast()
        return SimpleNamespace(rc=0, wait_for_publish=lambda **kwargs: None)


@pytest.fixture
def node(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    broker = Broker()
    node = IRNode(NodeConfig("CAGE-TEST", "NODE-TEST", MQTT, {"TEST_USER": "test", "TEST_PASSWORD": "fake"}),
                  client_factory=broker.factory, reconnect_s=0.03)
    node.start()
    until(lambda: node.status()["online"])
    yield node, broker
    node.close()


def test_state_path_is_identical_to_cli_and_no_store_specific_value(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state_path(MQTT) == tmp_path / "habitat-ir" / (hashlib.sha256(BASE.encode()).hexdigest()[:24] + ".json")


def test_observer_is_read_only_and_reports_unverified_physical_state(node):
    control, broker = node
    assert control.status() == {"cage_id": "CAGE-TEST", "configured": True, "status": "off", "online": True,
        "outputs_locked": False, "gpio_requested_on": False, "actual_ir_on": None,
        "active": False, "mode": None, "remaining_s": 0, "max_on_seconds": 900, "error": None}
    assert broker.frames == []
    assert not control.path.exists()


def test_on_expires_sends_off_and_uses_shared_sequence_store(node):
    control, broker = node
    assert control.request("on", 1)["active"] is True
    until(lambda: control.status()["status"] == "on")
    assert control.status()["mode"] == "timed"
    assert control.status()["remaining_s"] <= 1
    until(lambda: not control.status()["active"])
    assert [frame[5] for frame in broker.frames] == ["on", "off"]
    assert control.status()["gpio_requested_on"] is False
    assert json.loads(control.path.read_text())["last_sequence"] == 2
    assert control.status()["mode"] is None


@pytest.mark.parametrize("seconds", [900, None])
def test_off_cancels_lease_without_waiting_for_requested_duration(node, seconds):
    control, broker = node
    control.request("on", seconds)
    until(lambda: broker.gpio)
    assert control.status()["mode"] == ("continuous" if seconds is None else "timed")
    if seconds is None:
        assert control.status()["remaining_s"] is None
    before = time.monotonic()
    control.request("off")
    assert time.monotonic() - before < 0.5
    until(lambda: not control.status()["active"] and not control._running(control._off_thread))
    assert broker.frames[-1][5] == "off"
    assert sum(frame[5] == "on" for frame in broker.frames) == 1
    assert control.status()["error"] is None
    assert control.status()["mode"] is None
    assert control.status()["remaining_s"] == 0


def test_cli_and_web_are_mutually_exclusive_and_off_cancels_cli(node):
    control, broker = node
    initial = cancellation_token(control.path)
    with ControlLock(control.path):
        with pytest.raises(RequestError, match="control_busy") as error:
            control.request("on", 10)
        assert error.value.http_status == 409
        control.request("off")
        assert cancellation_token(control.path) != initial
        assert broker.frames == []
    until(lambda: not control._running(control._off_thread))
    assert [frame[5] for frame in broker.frames] == ["off"]


@pytest.mark.parametrize("seconds", [900, None])
def test_cli_off_cancels_web_owner_before_next_renewal(node, seconds):
    control, broker = node
    control.request("on", seconds)
    until(lambda: broker.gpio)
    request_local_off(control.path)
    until(lambda: not control.status()["active"])
    assert [frame[5] for frame in broker.frames] == ["on", "off"]
    assert control.status()["error"] is None


@pytest.mark.parametrize("seconds", [900, None])
def test_off_during_startup_prevents_first_on_and_rejects_restart_until_stopped(node, seconds):
    control, broker = node
    entered, release = threading.Event(), threading.Event()
    factory = control.client_factory

    def gated_factory(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return factory(*args, **kwargs)

    control.client_factory = gated_factory
    try:
        status = control.request("on", seconds)
        assert status["mode"] == ("continuous" if seconds is None else "timed")
        assert entered.wait(1)
        control.request("off")
        with pytest.raises(RequestError, match="control_busy"):
            control.request("on", 1)
    finally:
        release.set()
    until(lambda: not control.status()["active"] and not control._running(control._off_thread))
    assert [frame[5] for frame in broker.frames] == ["off"]
    assert control.status()["remaining_s"] == 0
    assert control.status()["error"] is None


@pytest.mark.parametrize("failure", ["disconnect", "session", "malformed"])
@pytest.mark.parametrize("seconds", [900, None])
def test_fault_stops_and_monitoring_reconnect_never_replays_on(node, failure, seconds):
    control, broker = node
    control.request("on", seconds)
    until(lambda: broker.gpio)
    if failure == "disconnect":
        broker.disconnect_all()
    elif failure == "session":
        broker.session = SESSION2
        broker.broadcast()
    else:
        for client in list(broker.clients):
            client.monitor.accept(BASE + "/ir/hello", b"{}")
    until(lambda: not control.status()["active"])
    until(lambda: control.status()["online"])
    time.sleep(0.15)
    assert sum(frame[5] == "on" for frame in broker.frames) == 1
    assert control.status()["active"] is False


def test_locked_missing_and_stale_hello_reject_on_without_publish(node):
    control, broker = node
    broker.locked = True
    broker.broadcast()
    with pytest.raises(RequestError, match="outputs_locked"):
        control.request("on", 1)
    broker.send_hello = False
    with control._monitor.lock:
        control._monitor.received_at -= 6
    with pytest.raises(RequestError, match="no_live_hello"):
        control.request("on", 1)
    assert control.status()["online"] is False
    assert broker.frames == []


@pytest.mark.parametrize("seconds", [900, None])
def test_stale_during_on_stops_and_attempts_off(node, seconds):
    control, broker = node
    control.request("on", seconds)
    until(lambda: broker.gpio)
    broker.send_hello = False
    for client in list(broker.clients):
        with client.monitor.lock:
            client.monitor.received_at -= 6
    until(lambda: not control.status()["active"])
    assert [frame[5] for frame in broker.frames] == ["on", "off"]


@pytest.mark.parametrize("seconds", [900, None])
def test_shutdown_attempts_off_and_cannot_restart(node, seconds):
    control, broker = node
    control.request("on", seconds)
    until(lambda: broker.gpio)
    control.close()
    assert broker.frames[-1][5] == "off"
    assert not control.status()["active"]
    with pytest.raises(RequestError, match="worker_stopping"):
        control.request("on", 1)


@pytest.mark.parametrize("seconds", [0, 901, True, 1.5, "10"])
def test_invalid_duration_never_publishes(node, seconds):
    control, broker = node
    with pytest.raises(RequestError, match="invalid_command"):
        control.request("on", seconds)
    assert broker.frames == []
