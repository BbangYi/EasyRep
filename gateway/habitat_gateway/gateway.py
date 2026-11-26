from datetime import datetime, timedelta
import threading
from uuid import uuid4

from .config import Settings
from .models import Acknowledgement, CommandRequest, R15_MAX_REQUEST_HOLD_MS, Telemetry, utcnow
from .store import Store


class Conflict(ValueError):
    pass


def parse_time(value):
    return datetime.fromisoformat(value)


class Gateway:
    def __init__(self, settings: Settings, transport, now=utcnow):
        self.settings = settings
        self.transport = transport
        self.now = now
        self.lock = threading.RLock()
        identity = (settings.site_id, settings.gateway_id) if settings.cloud.enabled else None
        self.store = Store(settings.database, event_identity=identity, now=now)
        self.cages = {c.id: c for c in settings.cages}
        self.node_online = {}
        self.healthy = True
        self.policy_demand = {}
        with self.lock:
            # Never replay ambiguous commands or resume automatic control after restart.
            for command in self.store.pending():
                command.update(status="interrupted", reason="gateway_restarted_state_unknown")
                self.store.save_command(command)
            for cage_id in self.cages:
                self.store.set_mode(cage_id, "manual")
            self.audit("gateway_started", transport=settings.transport)

    def audit(self, kind, cage_id=None, **body):
        self.store.audit(self.now().isoformat(), kind, cage_id, **body)

    def cage(self, cage_id):
        if cage_id not in self.cages:
            raise KeyError("unknown cage")
        return self.cages[cage_id]

    def r15_target(self, cage_id, actuator_id):
        return self.settings.r15_bridge.enabled and any(
            z.cage_id == cage_id and z.actuator_id == actuator_id for z in self.settings.r15_bridge.zones)

    def ingest(self, cage_id, sample: Telemetry, retained=False):
        with self.lock:
            cage = self.cage(cage_id)
            if retained:
                return False
            if self.settings.transport == "mqtt" and sample.data_source != "sensor":
                raise ValueError("simulation samples are forbidden in MQTT mode")
            if (sample.sampled_at - self.now()).total_seconds() > self.settings.clock_tolerance_s:
                raise ValueError("sample timestamp is in the future")
            sensors = {s.id: s for s in cage.sensors}
            if not sample.readings.keys() <= sensors.keys():
                raise ValueError("unknown sensor ID")
            if not sample.actuators.keys() <= {a.id for a in cage.actuators}:
                raise ValueError("unknown actuator ID")
            if any(self.r15_target(cage_id, actuator_id) for actuator_id in sample.actuators):
                raise ValueError("R15 request bridge has no physical actuator telemetry")
            for sensor_id, reading in sample.readings.items():
                sensor = sensors[sensor_id]
                if reading.quality == "valid" and not sensor.min_value <= reading.value <= sensor.max_value:
                    raise ValueError(f"out-of-range reading: {sensor_id}")
            body = sample.model_dump(mode="json")
            body["sampled_at"] = sample.sampled_at.isoformat()
            inserted = self.store.telemetry(cage_id, body, self.now().isoformat())
            if inserted:
                for actuator_id, state in sample.actuators.items():
                    self.store.observe(cage_id, actuator_id, state, sample.sampled_at.isoformat(), "telemetry")
            return inserted

    def set_node_online(self, cage_id, online):
        with self.lock:
            self.cage(cage_id)
            self.node_online[cage_id] = online
            self.audit("node_availability", cage_id, online=online)

    def unsafe_reason(self, cage_id, actuator, *, new_request=False):
        cage = self.cage(cage_id)
        if not self.settings.hardware_outputs_enabled:
            return "hardware_not_commissioned"
        check = getattr(self.transport, "blocked_reason" if new_request else "unsafe_reason", None)
        if check:
            reason = check(cage_id, actuator.id)
            if reason:
                return reason
        if self.node_online.get(cage_id) is False:
            return "node_offline"
        sample = self.store.latest_telemetry(cage_id)
        if sample is None:
            return "missing_telemetry"
        age = (self.now() - parse_time(sample["sampled_at"])).total_seconds()
        received_age = (self.now() - parse_time(sample["received_at"])).total_seconds()
        if age > cage.stale_after_s or received_age > cage.stale_after_s:
            return "stale_telemetry"
        if age < -self.settings.clock_tolerance_s or received_age < -self.settings.clock_tolerance_s:
            return "clock_error"
        if sample["geometry_revision"] != cage.geometry_revision or sample["placement_revision"] != cage.placement_revision:
            return "revision_mismatch"
        for sensor_id in actuator.required_sensors:
            reading = sample["readings"].get(sensor_id)
            if reading is None or reading["quality"] != "valid":
                return f"sensor_unavailable:{sensor_id}"
            sensor = next(s for s in cage.sensors if s.id == sensor_id)
            if not sensor.min_value <= reading["value"] <= sensor.max_value:
                return f"sensor_out_of_range:{sensor_id}"
        for guard in actuator.guards:
            value = sample["readings"][guard.sensor_id]["value"]
            if guard.minimum is not None and value <= guard.minimum:
                return f"guard_minimum:{guard.sensor_id}"
            if guard.maximum is not None and value >= guard.maximum:
                return f"guard_maximum:{guard.sensor_id}"
        return None

    def lease_end(self, command):
        # A node may apply just before expires_at. Reserve the worst-case lease.
        if command.get("r15"):
            # Request hold is not measured RUN time; preserve the full bridge cycle guard.
            return parse_time(command["expires_at"]) + timedelta(seconds=7)
        start = command.get("applied_at") or command["expires_at"]
        return parse_time(start) + timedelta(seconds=command["duration_s"])

    def send_command(self, cage_id, request: CommandRequest, source="manual"):
        with self.lock:
            cage = self.cage(cage_id)
            actuator = next((a for a in cage.actuators if a.id == request.actuator_id), None)
            if actuator is None:
                raise KeyError("unknown actuator")
            previous = self.store.command(str(request.request_id))
            fingerprint = {"cage_id": cage_id, "source": source, **request.model_dump(mode="json")}
            if previous:
                if previous["request"] != fingerprint:
                    raise Conflict("request_id already used with a different command")
                return previous
            now = self.now()
            command = {
                "schema_version": 1, "command_id": str(request.request_id),
                "site_id": self.settings.site_id, "gateway_id": self.settings.gateway_id,
                "cage_id": cage_id, "node_id": cage.node_id,
                "actuator_id": actuator.id, "action": request.action, "duration_s": request.duration_s,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=min(self.settings.command_ttl_s, 5)
                    if self.r15_target(cage_id, actuator.id) else self.settings.command_ttl_s)).isoformat(),
                "geometry_revision": cage.geometry_revision, "placement_revision": cage.placement_revision,
                "source": source, "request": fingerprint, "status": "publishing", "reason": None,
                "sequence": self.store.next_sequence(),
            }
            reason = None
            if source == "manual" and self.store.mode(cage_id) == "auto":
                reason = "automatic_mode_use_stop_or_switch_to_manual"
            if request.action == "on" and reason is None:
                if not self.healthy:
                    reason = "gateway_unhealthy"
                elif self.r15_target(cage_id, actuator.id) and not 0.001 <= request.duration_s <= R15_MAX_REQUEST_HOLD_MS / 1000:
                    reason = "r15_request_hold_limit"
                elif request.duration_s > actuator.max_on_s:
                    reason = "duration_exceeds_limit"
                else:
                    reason = self.unsafe_reason(cage_id, actuator, new_request=True)
                last = self.store.latest_on(cage_id, actuator.id)
                if reason is None and last and now < self.lease_end(last) + timedelta(seconds=actuator.cooldown_s):
                    reason = "previous_lease_or_cooldown_active"
            if reason is None and not self.transport.connected:
                reason = "transport_offline"
            if reason is None and hasattr(self.transport, "prepare"):
                try:
                    self.transport.prepare(cage_id, command)
                except (ValueError, ConnectionError) as error:
                    reason = str(error)
            if reason:
                command.update(status="rejected", reason=reason)
                self.store.save_command(command)
                self.audit("command_rejected", cage_id, command_id=command["command_id"], reason=reason)
                return command
            # Commit before publishing; a process crash is not allowed to replay this command.
            self.store.save_command(command)
            wire = {k: v for k, v in command.items() if k not in ("request", "status", "reason")}
            try:
                self.transport.publish(cage_id, wire)
            except Exception:
                # Delivery can be ambiguous: reserve the lease even if publish raised.
                command.update(status="interrupted", reason="publish_failed_delivery_unknown")
            else:
                command["status"] = "published"
            self.store.save_command(command)
            self.audit("command_dispatched", cage_id, command_id=command["command_id"], status=command["status"])
            return command

    def acknowledge(self, cage_id, ack: Acknowledgement, retained=False, *, r15=False):
        with self.lock:
            self.cage(cage_id)
            command = self.store.command(str(ack.command_id))
            if retained or not command or command["cage_id"] != cage_id or command["actuator_id"] != ack.actuator_id:
                return False
            if self.r15_target(cage_id, ack.actuator_id):
                if not r15 or not command.get("r15") or ack.status == "applied" or ack.applied_state is not None:
                    return False
            elif r15 or ack.status in ("requested", "execution_unverified"):
                return False
            now = self.now()
            if ack.occurred_at > now + timedelta(seconds=self.settings.clock_tolerance_s):
                return False
            if ack.occurred_at < parse_time(command["created_at"]) - timedelta(seconds=self.settings.clock_tolerance_s):
                return False
            terminal = r15 and ack.status == "execution_unverified"
            allowed = ("publishing", "published", "requested", "expired", "interrupted") if terminal else ("publishing", "published")
            deadline = self.lease_end(command) if terminal else parse_time(command["expires_at"])
            if command["status"] not in allowed or now >= deadline:
                self.audit("late_or_duplicate_ack", cage_id, command_id=command["command_id"])
                return False
            if ack.status == "applied" and ack.applied_state != (command["action"] == "on"):
                self.audit("ack_state_mismatch", cage_id, command_id=command["command_id"])
                return False
            command.update(status=ack.status, reason=ack.reason, acknowledged_at=now.isoformat())
            if r15:
                command.update(execution_status="unverified", actual_state=None)
            if ack.status == "applied":
                # Use receipt time conservatively for cooldown (node lease started earlier).
                command["applied_at"] = now.isoformat()
                self.store.observe(cage_id, ack.actuator_id, ack.applied_state, ack.occurred_at.isoformat(), "node_ack")
            self.store.save_command(command)
            self.audit("command_acknowledged", cage_id, command_id=command["command_id"], status=ack.status)
            return True

    def _off(self, cage_id, actuator_id, source):
        return self.send_command(cage_id, CommandRequest(
            request_id=uuid4(), actuator_id=actuator_id, action="off"), source=source)

    def set_mode(self, cage_id, mode):
        with self.lock:
            cage = self.cage(cage_id)
            if mode == "auto" and not self.settings.hardware_outputs_enabled:
                raise Conflict("hardware_not_commissioned")
            if mode == "auto" and not cage.policies:
                raise Conflict("no policies configured")
            self.store.set_mode(cage_id, mode)
            for actuator in cage.actuators:
                self.policy_demand.pop((cage_id, actuator.id), None)
            self.audit("mode_changed", cage_id, mode=mode)
            return {"cage_id": cage_id, "mode": mode}

    def stop_all(self, cage_id):
        with self.lock:
            self.set_mode(cage_id, "manual")
            if any(self.r15_target(cage_id, actuator.id) for actuator in self.cage(cage_id).actuators):
                # A station STOP affects every mapped enclosure; none may resume an auto policy.
                for target in {zone.cage_id for zone in self.settings.r15_bridge.zones} - {cage_id}:
                    self.set_mode(target, "manual")
            return [self._off(cage_id, a.id, "stop") for a in self.cage(cage_id).actuators]

    def tick(self):
        with self.lock:
            now = self.now()
            for command in self.store.pending():
                if now >= parse_time(command["expires_at"]):
                    command.update(status="expired", reason="ack_timeout_state_unknown")
                    self.store.save_command(command)
                    self.audit("command_expired", command["cage_id"], command_id=command["command_id"])
            for cage in self.cages.values():
                for actuator in cage.actuators:
                    last = self.store.latest_command(cage.id, actuator.id)
                    on = self.store.latest_on(cage.id, actuator.id)
                    observation = self.store.observation(cage.id, actuator.id)
                    potentially_on = bool(observation and observation["state"]) or bool(on and now < self.lease_end(on))
                    if observation and not observation["state"] and on and parse_time(observation["occurred_at"]) >= parse_time(on["created_at"]):
                        # An OFF observation supersedes a lease only after ON has been acknowledged.
                        # Otherwise an in-flight ON could still arrive at the node.
                        if on["status"] == "applied":
                            potentially_on = False
                    unsafe = self.unsafe_reason(cage.id, actuator)
                    # Rate-limit repeated OFF attempts when communication has failed.
                    recent = last and (now - parse_time(last["created_at"])).total_seconds() < 5
                    if potentially_on and unsafe:
                        self.policy_demand.pop((cage.id, actuator.id), None)
                        if not (recent and last["action"] == "off"):
                            self._off(cage.id, actuator.id, "safety")
                        continue
                    if self.store.mode(cage.id) != "auto" or unsafe or not self.transport.connected or not self.healthy:
                        continue
                    policy = next((p for p in cage.policies if p.actuator_id == actuator.id), None)
                    if policy is None:
                        continue
                    value = self.store.latest_telemetry(cage.id)["readings"][policy.sensor_id]["value"]
                    turn_on = value < policy.on_threshold if policy.direction == "below" else value > policy.on_threshold
                    turn_off = value >= policy.off_threshold if policy.direction == "below" else value <= policy.off_threshold
                    key = (cage.id, actuator.id)
                    if turn_on:
                        self.policy_demand[key] = True
                    elif turn_off:
                        self.policy_demand[key] = False
                    if potentially_on and turn_off:
                        if not (recent and last["action"] == "off"):
                            self._off(cage.id, actuator.id, "policy")
                    elif not potentially_on and self.policy_demand.get(key, False) and not recent:
                        if on and now < self.lease_end(on) + timedelta(seconds=actuator.cooldown_s):
                            continue
                        self.send_command(cage.id, CommandRequest(
                            request_id=uuid4(), actuator_id=actuator.id, action="on", duration_s=policy.duration_s,
                        ), source="policy")

    def status(self, cage_id):
        with self.lock:
            cage = self.cage(cage_id)
            return {
                "cage_id": cage_id, "node_id": cage.node_id, "mode": self.store.mode(cage_id),
                "transport": self.settings.transport, "transport_connected": self.transport.connected,
                "telemetry": self.store.latest_telemetry(cage_id),
                "actuators": {
                    a.id: {"observed": None if self.r15_target(cage_id, a.id) else self.store.observation(cage_id, a.id),
                           "on_blocked_reason": self.unsafe_reason(cage_id, a, new_request=True) or
                               ("transport_offline" if not self.transport.connected else None) or
                               ("gateway_unhealthy" if not self.healthy else None),
                           "max_on_s": a.max_on_s, "cooldown_s": a.cooldown_s}
                    for a in cage.actuators
                },
            }
