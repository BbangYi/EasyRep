from datetime import datetime, timedelta, timezone
import json
import logging
import os
import time
from uuid import UUID, uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .gateway import parse_time
from .models import Acknowledgement, Reading, R15Ack, R15Hello, R15_MAX_REQUEST_HOLD_MS, Telemetry, utcnow

logger = logging.getLogger(__name__)


class NoDeviceTransport:
    """Heartbeat-only operation: no device connection, simulation, or outputs."""

    connected = False

    def publish(self, cage_id, command):
        raise ConnectionError("device_transport_disabled")


def node_topic(settings, cage, kind):
    return f"habitat/v1/{settings.site_id}/cages/{cage.id}/nodes/{cage.node_id}/{kind}"


class MQTTTransport:
    def __init__(self, settings, *, monotonic=time.monotonic):
        self.settings = settings
        self.gateway = None
        self.connected = False
        self.monotonic = monotonic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"{settings.site_id}-{settings.gateway_id}", protocol=mqtt.MQTTv5)
        password = os.environ.get(settings.mqtt.password_env)
        if not password:
            raise ValueError(f"MQTT mode requires {settings.mqtt.password_env}")
        self.client.username_pw_set(settings.mqtt.username, password)
        if settings.mqtt.tls_ca:
            self.client.tls_set(ca_certs=settings.mqtt.tls_ca)
        self.client.max_queued_messages_set(32)
        self.client.max_inflight_messages_set(16)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._connect
        self.client.on_disconnect = self._disconnect
        self.client.on_message = self._message
        self.status_topic = f"habitat/v1/{settings.site_id}/gateways/{settings.gateway_id}/status"
        self.client.will_set(self.status_topic, '{"online":false}', qos=1, retain=True)
        self.client.enable_logger(logger)
        self.routes = {
            node_topic(settings, cage, kind): (cage.id, kind)
            for cage in settings.cages for kind in ("telemetry", "ack", "status")
        }
        bridge = settings.r15_bridge
        self.r15_zones = {(z.cage_id, z.actuator_id): z.zone for z in bridge.zones} if bridge.enabled else {}
        self.r15_base = None
        self.r15_session = self.r15_candidate = None
        self.r15_hello = None
        self.r15_seen_at = float("-inf")
        self.r15_last_stamp = self.r15_sequence = self.r15_heartbeat_ms = 0
        self.r15_next_heartbeat = 0.0
        self.r15_stop_requested = False
        if bridge.enabled:
            central = next(c for c in settings.cages if c.id == bridge.central_cage_id)
            self.r15_base = node_topic(settings, central, "r15")
            for kind in ("hello", "ack"):
                self.routes[f"{self.r15_base}/{kind}"] = (central.id, f"r15_{kind}")

    def start(self, gateway):
        self.gateway = gateway
        self.client.connect_async(self.settings.mqtt.host, self.settings.mqtt.port, keepalive=20)
        self.client.loop_start()

    def _connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe([(topic, 1) for topic in self.routes])
            client.publish(self.status_topic, '{"online":true}', qos=1, retain=True)

    def _disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        # Do not resume the old session after a broker reconnect; no pending replay here.
        if self.gateway and self.r15_base:
            with self.gateway.lock:
                self.r15_session = self.r15_candidate = None
                self.r15_hello = None
                self.r15_seen_at = float("-inf")

    def _message(self, client, userdata, message):
        if message.topic not in self.routes or len(message.payload) > 65536:
            return
        cage_id, kind = self.routes[message.topic]
        try:
            payload = json.loads(message.payload)
            if kind.startswith("r15_"):
                with self.gateway.lock:
                    self._r15_message(kind, payload, message.retain)
            elif kind == "telemetry":
                self.gateway.ingest(cage_id, Telemetry.model_validate(payload), retained=message.retain)
            elif kind == "ack":
                self.gateway.acknowledge(cage_id, Acknowledgement.model_validate(payload), retained=message.retain)
            elif type(payload.get("online")) is bool:
                self.gateway.set_node_online(cage_id, payload["online"])
        except (ValueError, TypeError, AttributeError, KeyError):
            logger.warning("Rejected malformed %s message for %s", kind, cage_id)
        except Exception:
            logger.exception("Failed to persist MQTT message for %s", cage_id)

    def publish(self, cage_id, command):
        if not self.connected:
            raise ConnectionError("MQTT disconnected")
        if (cage_id, command.get("actuator_id")) in self.r15_zones:
            delivery = command.get("r15")
            if not delivery or delivery["session_id"] != self.r15_candidate or (
                    delivery["action"] == "on" and delivery["session_id"] != self.r15_session):
                raise ConnectionError("r15_fresh_session_required")
            self._r15_publish(delivery["payload"], 5, session=delivery["session_id"])
            return
        cage = next(c for c in self.settings.cages if c.id == cage_id)
        properties = Properties(PacketTypes.PUBLISH)
        properties.MessageExpiryInterval = self.settings.command_ttl_s
        result = self.client.publish(node_topic(self.settings, cage, "command"),
                                     json.dumps(command), qos=1, retain=False, properties=properties)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("MQTT publish failed")

    def _r15_publish(self, payload, ttl_s, *, session=None):
        properties = Properties(PacketTypes.PUBLISH)
        properties.MessageExpiryInterval = ttl_s
        result = self.client.publish(f"{self.r15_base}/command/{session or self.r15_session}", payload,
                                     qos=1, retain=False, properties=properties)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("r15_publish_failed")

    def _r15_frame(self, command_id, zone, action, hold_ms, issued_ms, expires_ms, *, session=None):
        if self.r15_sequence >= 4294967295:
            raise ValueError("r15_sequence_exhausted_fresh_session_required")
        self.r15_sequence += 1
        return (f"R15/1 {session or self.r15_session} {command_id} {self.r15_sequence} {zone} "
                f"{action} {hold_ms} {issued_ms} {expires_ms}")

    def unsafe_reason(self, cage_id, actuator_id):
        if (cage_id, actuator_id) not in self.r15_zones:
            return None
        if self.settings.r15_bridge.outputs_locked:
            return "r15_outputs_locked"
        if not self.connected or not self.r15_session:
            return "r15_fresh_session_required"
        hello = self.r15_hello
        if not hello or self.monotonic() - self.r15_seen_at >= 1.5:
            return "r15_status_stale"
        if hello.outputs_locked:
            return "r15_node_outputs_locked"
        if hello.stop_latched or self.r15_stop_requested:
            return "r15_stop_latched"
        if not self.r15_heartbeat_ms or not hello.gateway_lease_valid or hello.observed_at_ms < self.r15_heartbeat_ms:
            return "r15_gateway_lease_missing"
        if not hello.status_pin_levels.armed or not hello.status_pin_levels.level:
            return "r15_status_pin_low"
        return None

    def blocked_reason(self, cage_id, actuator_id):
        reason = self.unsafe_reason(cage_id, actuator_id)
        if reason or (cage_id, actuator_id) not in self.r15_zones:
            return reason
        # Busy and reserved reject another ON; they do not make an active request unsafe.
        if self.r15_hello.request_mask:
            return "r15_bridge_busy"
        for cage, actuator in self.r15_zones:
            previous = self.gateway.store.latest_on(cage, actuator)
            if previous and self.gateway.now() < self.gateway.lease_end(previous):
                return "r15_shared_cycle_reserved"
        return None

    def prepare(self, cage_id, command):
        zone = self.r15_zones.get((cage_id, command["actuator_id"]))
        if zone is None:
            return
        session = self.r15_session if command["action"] == "on" else self.r15_candidate
        if not self.connected or not session:
            raise ConnectionError("r15_fresh_session_required")
        action = "stop" if command["source"] == "stop" else command["action"]
        zone = 0 if action == "stop" else zone
        hold_ms = int(command["duration_s"] * 1000) if action == "on" else 0
        if action == "on":
            reason = self.blocked_reason(cage_id, command["actuator_id"])
            if reason:
                raise ValueError(reason)
            if not 1 <= hold_ms <= R15_MAX_REQUEST_HOLD_MS:
                raise ValueError("r15_request_hold_limit")
            if hold_ms > self.r15_hello.max_request_hold_ms:
                raise ValueError("r15_request_hold_unsupported_by_node")
        issued = int(parse_time(command["created_at"]).timestamp() * 1000)
        expires = int(parse_time(command["expires_at"]).timestamp() * 1000)
        if not 0 < expires - issued <= 5000:
            raise ValueError("r15_invalid_command_ttl")
        payload = self._r15_frame(command["command_id"], zone, action, hold_ms, issued, expires, session=session)
        if action == "stop":
            self.r15_stop_requested = True
        # Gateway commits this delivery binding before publish. It never regenerates a retry.
        command["r15"] = {"session_id": session, "sequence": self.r15_sequence,
                          "zone": zone, "action": action, "request_hold_ms": hold_ms, "payload": payload}
        command.update(execution_status="unverified", actual_state=None)

    def _r15_message(self, kind, payload, retained):
        if retained or not self.connected:
            return
        now = self.gateway.now()
        now_ms = int(now.timestamp() * 1000)
        if kind == "r15_hello":
            hello = R15Hello.model_validate(payload)
            session = str(hello.session_id)
            if (hello.command_topic != f"{self.r15_base}/command/{session}"
                    or not 0 <= now_ms - hello.observed_at_ms < 1500
                    or hello.observed_at_ms <= self.r15_last_stamp):
                return
            if bool(hello.request_mask) != bool(hello.active_command_id):
                return
            if hello.active_command_id and str(UUID(hello.active_command_id)) != hello.active_command_id:
                return
            self.r15_last_stamp = hello.observed_at_ms
            if session != self.r15_candidate:
                self.r15_candidate = session
                fresh = self.gateway.store.claim_r15_session(self.r15_base, session)
                self.r15_session = session if fresh and not hello.gateway_lease_valid and not hello.request_mask else None
                self.r15_sequence = self.r15_heartbeat_ms = 0
                self.r15_next_heartbeat = 0
                self.r15_stop_requested = False
                self.gateway.audit("r15_session_observed", session_id=session, accepted=bool(self.r15_session))
            self.r15_hello = hello
            self.r15_seen_at = self.monotonic()
            return
        ack = R15Ack.model_validate(payload)
        if str(ack.session_id) != self.r15_candidate:
            return
        command = self.gateway.store.command(str(ack.command_id))
        if not command:
            return
        delivery = command.get("r15")
        if (not delivery or delivery["session_id"] != self.r15_candidate
                or delivery["sequence"] != ack.sequence or delivery["zone"] != ack.zone
                or delivery["request_hold_ms"] != ack.request_hold_ms
                or (command["cage_id"], command["actuator_id"]) not in self.r15_zones):
            return
        expected = ack.status == "requested" and delivery["action"] == "on"
        if ack.requested_state != expected:
            return
        if ack.status == "execution_unverified" and delivery["action"] != "on":
            return
        self.gateway.acknowledge(command["cage_id"], Acknowledgement(
            command_id=ack.command_id, actuator_id=command["actuator_id"], status=ack.status,
            reason=ack.reason, occurred_at=datetime.fromtimestamp(ack.observed_at_ms / 1000, timezone.utc)), r15=True)

    def step(self):
        if not self.r15_base or not self.connected or not self.gateway:
            return
        with self.gateway.lock:
            at = self.monotonic()
            hello = self.r15_hello
            if (not self.r15_session or not hello or at - self.r15_seen_at >= 1.5
                    or hello.stop_latched or self.r15_stop_requested or not self.gateway.healthy or at < self.r15_next_heartbeat):
                return
            self.r15_next_heartbeat = at + 0.5
            issued = int(self.gateway.now().timestamp() * 1000)
            payload = self._r15_frame(str(uuid4()), 0, "heartbeat", 0, issued, issued + 1000)
            try:
                self._r15_publish(payload, 1)
            except ConnectionError:
                logger.warning("R15 heartbeat delivery failed; no retry or lease assumption")
                return
            if not self.r15_heartbeat_ms:
                self.r15_heartbeat_ms = issued

    def close(self):
        if self.connected and self.r15_candidate and self.gateway:
            with self.gateway.lock:
                issued = int(self.gateway.now().timestamp() * 1000)
                command_id = str(uuid4())
                try:
                    payload = self._r15_frame(command_id, 0, "stop", 0, issued, issued + 1000,
                                              session=self.r15_candidate)
                    self._r15_publish(payload, 1, session=self.r15_candidate)
                except (ValueError, ConnectionError):
                    logger.warning("R15 shutdown STOP delivery unconfirmed; node timeout remains required")
                self.r15_stop_requested = True
                self.gateway.audit("r15_shutdown_stop_requested", command_id=command_id, execution_status="unverified")
        if self.connected:
            self.client.publish(self.status_topic, '{"online":false}', qos=1, retain=True)
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = False


class SimulatedTransport:
    """In-process Cage Nodes. Never opens GPIO, serial ports, or network sockets."""

    def __init__(self, settings, now=utcnow, *, telemetry_interval_s=0.0):
        self.settings = settings
        self.now = now
        self.gateway = None
        self.telemetry_interval_s = telemetry_interval_s
        self.last_emitted = {}
        self.connected = True
        self.pending = []
        self.seen = {}
        self.sent = []
        self.nodes = {}
        for cage in settings.cages:
            readings = {}
            for sensor in cage.sensors:
                defaults = {"degC": 24.0, "percent_rh": 65.0, "lux": 100.0}
                value = max(sensor.min_value, min(sensor.max_value, defaults[sensor.unit]))
                readings[sensor.id] = Reading(value=value, quality="valid")
            self.nodes[cage.id] = {
                "online": True, "readings": readings,
                "states": {a.id: False for a in cage.actuators}, "deadlines": {}, "sequences": {}, "cooldowns": {},
            }

    def start(self, gateway):
        self.gateway = gateway
        self.step()

    def patch_readings(self, cage_id, readings):
        node = self.nodes[cage_id]
        if not readings.keys() <= node["readings"].keys():
            raise ValueError("unknown simulated sensor")
        cage = self.gateway.cage(cage_id)
        for sensor in cage.sensors:
            reading = readings.get(sensor.id)
            if reading and reading.quality == "valid" and not sensor.min_value <= reading.value <= sensor.max_value:
                raise ValueError(f"out-of-range simulated sensor: {sensor.id}")
        node["readings"].update(readings)
        self.step()

    def _local_guard(self, cage, actuator, node):
        for sensor_id in actuator.required_sensors:
            if node["readings"][sensor_id].quality != "valid":
                return "local_sensor_invalid"
            sensor = next(s for s in cage.sensors if s.id == sensor_id)
            if not sensor.min_value <= node["readings"][sensor_id].value <= sensor.max_value:
                return "local_sensor_out_of_range"
        for guard in actuator.guards:
            value = node["readings"][guard.sensor_id].value
            if guard.minimum is not None and value <= guard.minimum:
                return "local_guard_minimum"
            if guard.maximum is not None and value >= guard.maximum:
                return "local_guard_maximum"
        return None

    def publish(self, cage_id, command):
        if not self.connected:
            raise ConnectionError("simulation disconnected")
        self.sent.append(command)
        self.pending.append((cage_id, command))

    def _apply_state(self, cage_id, actuator_id, state, at, reason, command_id=None):
        self.nodes[cage_id]["states"][actuator_id] = state

    def step(self):
        if self.gateway is None:
            return
        with self.gateway.lock:
            now = self.now()
            for cage in self.settings.cages:
                node = self.nodes[cage.id]
                # Node-local timers/interlocks keep running even without a gateway link.
                for actuator in cage.actuators:
                    deadline = node["deadlines"].get(actuator.id)
                    guard = self._local_guard(cage, actuator, node)
                    if (deadline and now >= deadline) or guard:
                        at = deadline if deadline and now >= deadline and not guard else now
                        self._apply_state(cage.id, actuator.id, False, at, guard or "lease_finished")
                        node["deadlines"].pop(actuator.id, None)
            pending, self.pending = self.pending, []
            for cage_id, command in pending:
                node = self.nodes[cage_id]
                if not self.connected or not node["online"]:
                    continue
                if command["command_id"] in self.seen:
                    self.gateway.acknowledge(cage_id, self.seen[command["command_id"]])
                    continue
                cage = self.gateway.cage(cage_id)
                actuator = next(a for a in cage.actuators if a.id == command["actuator_id"])
                reason = None
                if now >= parse_time(command["expires_at"]):
                    reason = "local_command_expired"
                elif command["sequence"] <= node["sequences"].get(actuator.id, 0):
                    reason = "local_stale_sequence"
                elif command["action"] == "on":
                    if command["geometry_revision"] != cage.geometry_revision or command["placement_revision"] != cage.placement_revision:
                        reason = "local_revision_mismatch"
                    elif command["duration_s"] <= 0 or command["duration_s"] > actuator.max_on_s:
                        reason = "local_duration_limit"
                    elif actuator.id in node["cooldowns"] and now < node["cooldowns"][actuator.id]:
                        reason = "local_cooldown"
                    else:
                        reason = self._local_guard(cage, actuator, node)
                node["sequences"][actuator.id] = max(command["sequence"], node["sequences"].get(actuator.id, 0))
                if reason is None:
                    self._apply_state(cage_id, actuator.id, command["action"] == "on", now,
                                      command["source"], command["command_id"])
                    if command["action"] == "on":
                        node["deadlines"][actuator.id] = now + timedelta(seconds=command["duration_s"])
                        node["cooldowns"][actuator.id] = now + timedelta(seconds=command["duration_s"] + actuator.cooldown_s)
                    else:
                        node["deadlines"].pop(actuator.id, None)
                ack = Acknowledgement(command_id=command["command_id"], actuator_id=actuator.id,
                                      status="rejected" if reason else "applied",
                                      applied_state=node["states"][actuator.id], occurred_at=now, reason=reason or "")
                self.seen[command["command_id"]] = ack
                self.gateway.acknowledge(cage_id, ack)
            for cage in self.settings.cages:
                node = self.nodes[cage.id]
                if not self.connected or not node["online"]:
                    continue
                last = self.last_emitted.get(cage.id)
                if last is not None and (now-last).total_seconds() < self.telemetry_interval_s:
                    continue
                self.last_emitted[cage.id] = now
                self.gateway.ingest(cage.id, Telemetry(
                    message_id=uuid4(), data_source="simulation", sampled_at=now, geometry_revision=cage.geometry_revision,
                    placement_revision=cage.placement_revision, readings=node["readings"], actuators=node["states"],
                ))

    def close(self):
        self.connected = False
