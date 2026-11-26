"""Local, explicit IR lease control. Requires paho-mqtt>=2.1,<3; no web API.

status only subscribes. on/off require a private per-Pi sequence file and lock.
No reconnect/retry of ON after any disconnect, stale hello or changed session.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import ssl
import threading
import time
from uuid import UUID, uuid4

HELLO_TTL_S = 5.0
REFRESH_S = 1.0
MAX_LEASE_MS = 5000
UINT32_MAX = 2**32 - 1
TOPIC_RE = re.compile(r"habitat/v1/[A-Za-z0-9_-]{1,64}/cages/[A-Za-z0-9_-]{1,64}/nodes/[A-Za-z0-9_-]{1,64}\Z")
ENV_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class ControlError(Exception):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ControlError("Duplicate JSON field")
        result[key] = value
    return result


def canonical_uuid(value):
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ControlError("Invalid session UUID") from None
    if str(parsed) != value:
        raise ControlError("Session UUID must be canonical lowercase")
    return value


@dataclass(frozen=True)
class Config:
    broker_host: str
    broker_port: int
    ca_file: str
    topic_base: str
    username_env: str
    password_env: str


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, ValueError):
        raise ControlError("Cannot read JSON config") from None
    required = {"broker_host", "broker_port", "ca_file", "topic_base", "username_env", "password_env"}
    if not isinstance(data, dict) or set(data) != required:
        raise ControlError("Config requires host, TLS port, CA, topic_base and credential environment names only")
    if not isinstance(data["broker_host"], str) or not data["broker_host"] or any(c.isspace() for c in data["broker_host"]) or "/" in data["broker_host"]:
        raise ControlError("Invalid broker host; use the hostname matching the certificate")
    if type(data["broker_port"]) is not int or data["broker_port"] != 8883:
        raise ControlError("This profile requires TLS port 8883")
    if not isinstance(data["ca_file"], str) or not Path(data["ca_file"]).is_file():
        raise ControlError("CA certificate file is missing")
    if not isinstance(data["topic_base"], str) or not TOPIC_RE.fullmatch(data["topic_base"]):
        raise ControlError("Invalid registered cage topic")
    if any(not isinstance(data[k], str) or not ENV_RE.fullmatch(data[k]) for k in ("username_env", "password_env")):
        raise ControlError("Credentials must refer to environment variable names")
    return Config(**data)


def credentials(config, environ=os.environ):
    user, password = environ.get(config.username_env), environ.get(config.password_env)
    if not user or not password:
        raise ControlError("Required MQTT credential environment variables are not set")
    return user, password


def tls_context(config):
    context = ssl.create_default_context(cafile=config.ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def parse_hello(payload, base):
    if not isinstance(payload, bytes) or len(payload) > 2048:
        raise ControlError("Invalid hello size")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise ControlError("Invalid hello JSON") from None
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ControlError("Unsupported hello schema")
    session = canonical_uuid(value.get("session_id"))
    if value.get("command_topic") != f"{base}/ir/command/{session}":
        raise ControlError("Hello command topic does not match the configured cage and session")
    if any(type(value.get(k)) is not bool for k in ("outputs_locked", "gpio_requested_on")):
        raise ControlError("Invalid hello boolean")
    if "actual_ir_on" not in value or value["actual_ir_on"] is not None:
        raise ControlError("This profile reports actual_ir_on as unverified/null")
    if type(value.get("max_lease_ms")) is not int or value["max_lease_ms"] != MAX_LEASE_MS:
        raise ControlError("Unsupported IR lease limit")
    return {k: value[k] for k in ("schema_version", "session_id", "command_topic", "outputs_locked", "gpio_requested_on", "actual_ir_on", "max_lease_ms")}


class Monitor:
    def __init__(self, base, monotonic=time.monotonic):
        self.base, self.clock = base, monotonic
        self.lock = threading.RLock()
        self.connected = False
        self.hello = None
        self.received_at = 0.0
        self.fault = None
        self.pending = {}
        self.accepted_on = False

    def fail(self, message):
        with self.lock:
            self.fault = self.fault or message

    def connection(self, online):
        with self.lock:
            self.connected = online
            if not online:
                self.fault = self.fault or "MQTT disconnected; automatic resume is disabled"

    def accept(self, topic, payload, retained=False):
        if topic == self.base + "/ir/ack" and not retained:
            self.accept_ack(payload)
            return
        if topic != self.base + "/ir/hello" or retained:
            return  # Never start from a stored broker snapshot or a different cage.
        try:
            hello = parse_hello(payload, self.base)
        except ControlError:
            self.fail("Malformed current-cage hello; control stopped")
            return
        with self.lock:
            if not self.connected:
                return
            if self.hello and self.hello["session_id"] != hello["session_id"]:
                self.fault = self.fault or "MCU session changed; automatic resume is disabled"
            self.hello, self.received_at = hello, self.clock()

    def accept_ack(self, payload):
        try:
            if not isinstance(payload, bytes) or len(payload) > 2048:
                return
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
            if not isinstance(value, dict) or not isinstance(value.get("command_id"), str):
                return
        except (ValueError, UnicodeError, ControlError):
            return  # A matching valid ACK must still arrive before its deadline.
        with self.lock:
            expected = self.pending.get(value["command_id"])
            if expected is None:
                return  # Another CLI/account command cannot acknowledge ours.
            session, sequence, action, sent_at = expected
            valid = (type(value.get("schema_version")) is int and value["schema_version"] == 1
                     and value.get("session_id") == session
                     and type(value.get("sequence")) is int and value["sequence"] == sequence
                     and type(value.get("gpio_requested_on")) is bool
                     and "actual_ir_on" in value and value["actual_ir_on"] is None)
            accepted = valid and ((action == "on" and value.get("reason") == "ir_requested_on" and value["gpio_requested_on"])
                                  or (action == "off" and value.get("reason") == "off_requested" and not value["gpio_requested_on"]))
            del self.pending[value["command_id"]]
            if not accepted:
                self.fault = self.fault or "MCU rejected or mismatched the IR command; no automatic retry"
            elif action == "on":
                self.accepted_on = True

    def checked(self, require_output=False):
        with self.lock:
            if self.fault:
                raise ControlError(self.fault)
            if any(self.clock() - item[3] >= 2.0 for item in self.pending.values()):
                self.fault = "MCU acknowledgment expired; IR control stopped"
                raise ControlError(self.fault)
            if not self.connected or self.hello is None:
                raise ControlError("No live IR hello")
            if self.clock() - self.received_at >= HELLO_TTL_S:
                self.fault = "IR hello expired; automatic resume is disabled"
                raise ControlError(self.fault)
            if require_output and self.hello["outputs_locked"]:
                raise ControlError("Firmware IR output is locked")
            return dict(self.hello)


class ControlLock:
    """OS lock releases on crash. All control invocations must use the same state path."""
    def __init__(self, state_path, wait_s=0.0):
        self.path = Path(str(state_path) + ".lock")
        self.file = None
        self.wait_s = wait_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = self.path.open("a+b")
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    if self.path.stat().st_size == 0:
                        self.file.write(b"0"); self.file.flush()
                    self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    self.file.close(); self.file = None
                    raise ControlError("Another local IR control command is active; OFF cancellation remains requested") from None
                time.sleep(0.05)
        return self

    def __exit__(self, *unused):
        if self.file:
            self.file.close()


def cancellation_token(state_path):
    path = Path(str(state_path) + ".cancel")
    return path.read_bytes() if path.exists() else b""


def request_local_off(state_path):
    """Interrupt the lease owner before waiting for its sequence lock."""
    path = Path(str(state_path) + ".cancel")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(uuid4().hex.encode()); stream.flush(); os.fsync(stream.fileno())


class SequenceStore:
    """Caller holds ControlLock. Reserve durably before MQTT publish; never replay ON."""
    def __init__(self, path, base):
        self.path, self.base = Path(path), base

    def next(self, session):
        last = 0
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
                if not isinstance(state, dict) or state.get("topic_base") != self.base or type(state.get("last_sequence")) is not int or not 0 <= state["last_sequence"] <= UINT32_MAX:
                    raise ValueError
                canonical_uuid(state.get("session_id"))
                if state["session_id"] == session:
                    last = state["last_sequence"]
            except (ValueError, OSError, ControlError):
                raise ControlError("Invalid sequence state; do not reset it while the same MCU session is active") from None
        if last == UINT32_MAX:
            raise ControlError("Sequence exhausted; a fresh MCU session is required")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = self.path.with_name(self.path.name + ".tmp-" + uuid4().hex)
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"topic_base": self.base, "session_id": session, "last_sequence": last + 1}, stream)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        return last + 1


def command_frame(session, sequence, action, hold_ms=0, wall_clock=time.time, new_uuid=uuid4):
    canonical_uuid(session)
    if action not in ("on", "off", "stop") or type(sequence) is not int or not 1 <= sequence <= UINT32_MAX:
        raise ControlError("Invalid command")
    if type(hold_ms) is not int or (not 1 <= hold_ms <= MAX_LEASE_MS if action == "on" else hold_ms != 0):
        raise ControlError("Invalid IR hold time")
    now_ms = int(wall_clock() * 1000)
    if now_ms < 1700000000000 and action == "on":
        raise ControlError("System UTC clock is not synchronized")
    now_ms = max(0, now_ms)  # Current-session OFF/STOP stays possible with a bad clock.
    ttl_ms = hold_ms if action == "on" else 2000
    return f"IR/1 {session} {new_uuid()} {sequence} {0 if action == 'stop' else 1} {action} {hold_ms} {now_ms} {now_ms + ttl_ms}"


class Controller:
    def __init__(self, client, monitor, sequences, *, monotonic=time.monotonic, wall_clock=time.time, sleep=time.sleep, cancelled=lambda: False):
        self.client, self.monitor, self.sequences = client, monitor, sequences
        self.clock, self.wall_clock, self.sleep = monotonic, wall_clock, sleep
        self.cancelled = cancelled

    def check_cancel(self):
        if self.cancelled():
            raise ControlError("Local OFF requested; IR lease renewal stopped")

    def wait_hello(self, timeout=10.0):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.check_cancel()
            with self.monitor.lock:
                if self.monitor.fault:
                    raise ControlError(self.monitor.fault)
                if self.monitor.connected and self.monitor.hello:
                    return self.monitor.checked()
            self.sleep(0.05)
        raise ControlError("No fresh IR hello before timeout; firmware/ACL/topic may not be installed")

    def publish(self, action, hold_ms=0, cleanup=False):
        with self.monitor.lock:
            if cleanup:
                if not self.monitor.connected or not self.monitor.hello:
                    return None
                hello = dict(self.monitor.hello)  # OFF may target a new session; never ON it.
            else:
                hello = self.monitor.checked(require_output=action == "on")
            try:
                sequence = self.sequences.next(hello["session_id"])
            except (ControlError, OSError):
                if not cleanup:
                    raise
                sequence = 1  # Current-session OFF is accepted regardless of old sequence.
            frame = command_frame(hello["session_id"], sequence, action, hold_ms, self.wall_clock)
            command_id = frame.split()[2]
            self.monitor.pending[command_id] = (hello["session_id"], sequence, action, self.clock())
            result = self.client.publish(hello["command_topic"], frame, qos=1, retain=False)
            if result.rc != 0:
                raise ControlError("MQTT publish failed; no automatic retry")
            return result

    def run(self, action="status", seconds=10.0):
        if action not in ("status", "on", "off"):
            raise ControlError("Unsupported action")
        if action == "on" and seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 43200):
            raise ControlError("--seconds must be between 1 and 43200")
        hello = self.wait_hello()
        if action == "status":
            return {**hello, "source": "live_mqtt_hello", "physical_ir_verified": False}
        if action == "off":
            result = self.publish("off")
            result.wait_for_publish(timeout=1.0)
            return {"off_requested": True, "physical_ir_verified": False}
        try:
            self.check_cancel()
            self.monitor.checked(require_output=True)
            deadline = None if seconds is None else self.clock() + seconds
            next_send = self.clock()
            while deadline is None or self.clock() < deadline:
                self.check_cancel()
                self.monitor.checked(require_output=True)
                at = self.clock()
                if at >= next_send:
                    remaining_ms = MAX_LEASE_MS if deadline is None else max(1, int((deadline - at) * 1000))
                    self.publish("on", min(MAX_LEASE_MS, remaining_ms))
                    next_send = at + REFRESH_S
                self.sleep(0.1 if deadline is None else min(0.1, max(0.0, deadline - self.clock())))
            self.monitor.checked(require_output=True)
            if not self.monitor.accepted_on:
                raise ControlError("No MCU acknowledgment of ON received")
            return {"requested_seconds": seconds, "lease_refresh_finished": True, "mcu_on_ack_received": True, "physical_ir_verified": False}
        finally:
            try:
                result = self.publish("off", cleanup=True)
                if result is not None:
                    result.wait_for_publish(timeout=1.0)
            except (ControlError, OSError, RuntimeError):
                pass  # MCU lease expiry is the fallback; never reconnect to send cleanup.


def make_client(config, monitor, *, mqtt_module=None, environ=None):
    if mqtt_module is None:
        try:
            import paho.mqtt.client as mqtt_module
        except ImportError:
            raise ControlError("Install paho-mqtt>=2.1,<3 in the Pi environment") from None
    if not hasattr(mqtt_module, "CallbackAPIVersion"):
        raise ControlError("This CLI requires paho-mqtt>=2.1,<3 in the selected Python environment")
    user, password = credentials(config, os.environ if environ is None else environ)
    client = mqtt_module.Client(callback_api_version=mqtt_module.CallbackAPIVersion.VERSION2,
                                client_id="habitat-ir-" + uuid4().hex, clean_session=True,
                                protocol=mqtt_module.MQTTv311, reconnect_on_failure=False)
    client.username_pw_set(user, password)
    client.tls_set_context(tls_context(config))
    client.connect_timeout = 8.0
    client.max_queued_messages_set(8)
    client.max_inflight_messages_set(2)

    def connected(c, userdata, flags, reason_code, properties):
        if reason_code != 0:
            monitor.fail("MQTT connection refused")
            return
        monitor.connection(True)
        rc, _ = c.subscribe(config.topic_base + "/ir/hello", qos=0)
        if rc != 0:
            monitor.fail("IR hello subscription failed")
        rc, _ = c.subscribe(config.topic_base + "/ir/ack", qos=0)
        if rc != 0:
            monitor.fail("IR acknowledgment subscription failed")

    client.on_connect = connected
    client.on_disconnect = lambda c, u, f, r, p: monitor.connection(False)
    client.on_connect_fail = lambda c, u: monitor.fail("MQTT connection failed")
    client.on_message = lambda c, u, m: monitor.accept(m.topic, m.payload, m.retain)
    return client
