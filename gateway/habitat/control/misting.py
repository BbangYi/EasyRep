"""Shared pump coordination and an explicitly virtual central controller.

No GPIO/serial driver is present. Physical commissioning needs the confirmed
SAFE board pin contract and independent protection tests.
"""
from collections import OrderedDict
from datetime import datetime, timedelta
import math
import time
from uuid import UUID

from habitat.compute.environment import MIST_MAX_RUN_SECONDS, validate_result
from habitat.compute.errors import ComputeFailure
from habitat_gateway.models import CommandRequest
from habitat_gateway.transport import SimulatedTransport
from .r15_timing import REQ_MAX_MS, RUN_MAX_S, TIMING_MODE, TIMING_PROFILE, request_timing


class VirtualMistingTransport(SimulatedTransport):
    """One virtual pump and one normally-closed valve per configured cage.

    R15 sequence timings are software/design limits, not measured response times.
    The inherited actuator state means a request is accepted (including preopen);
    only executions/transitions describe virtual pump-on time.
    The order log describes commanded outputs, not proof of mechanical movement.
    desired_run_ideal retains the original full-RUN comparison. The explicitly
    selected r15_request_fixture schedules REQ and RUN separately using the
    native source's healthy timing fixture. Neither mode proves a physical dose.
    """
    preopen_s = 1.0
    drain_s = 1.0
    window_min_s = 4.78108758
    window_max_s = 5.20534892

    def __init__(self, settings, now, *, actuator_id="mister", watchdog_s=1.0, telemetry_interval_s=0.0,
                 timing_mode="desired_run_ideal"):
        if settings.transport != "simulated" or settings.cloud.enabled:
            raise ValueError("virtual misting requires simulated transport and cloud disabled")
        if not math.isfinite(watchdog_s) or not 0 < watchdog_s <= 1:
            raise ValueError("SAFE R15 remote watchdog must be positive and at most 1 second")
        if timing_mode not in ("desired_run_ideal", "r15_request_fixture"):
            raise ValueError("unknown virtual misting timing mode")
        super().__init__(settings, now, telemetry_interval_s=telemetry_interval_s)
        self.timing_mode = timing_mode
        self.tick_origin = now()
        self.recycle_until = None
        self.request_outcomes = []
        self.proposal_metadata = {}
        self.request_low_at = None
        self.actuator_id = actuator_id
        if any(actuator_id not in n["states"] for n in self.nodes.values()):
            raise ValueError("each cage needs the shared mist actuator")
        limit = REQ_MAX_MS / 1000 if timing_mode == TIMING_MODE else MIST_MAX_RUN_SECONDS
        if any(a.max_on_s > limit for c in settings.cages
               for a in c.actuators if a.id == actuator_id):
            raise ValueError("misting REQ limit exceeds 5 seconds" if timing_mode == TIMING_MODE else
                             "misting RUN limit exceeds SAFE R15 3 seconds")
        self.watchdog_s = watchdog_s
        self.heartbeat_at = now()
        self.water_ok = False
        self.leak = True
        self.stop = True
        self.armed = False
        self.latched = "not_armed"
        self.pump_on = False
        self.valve = None
        self.active = None
        self.phase = "idle"
        self.drain_until = None
        self.window_until = None
        self.transitions = []
        self.executions = []

    @property
    def busy(self):
        return self.phase != "idle"

    def blocked_reason(self, cage_id, actuator_id):
        if actuator_id == self.actuator_id and self.busy:
            return "shared_pump_busy"
        return None

    def interlocks(self, *, water_ok, leak, stop):
        if any(type(v) is not bool for v in (water_ok, leak, stop)):
            raise ValueError("explicit boolean interlocks required")
        self.water_ok, self.leak, self.stop = water_ok, leak, stop
        self._enforce()

    def fault(self):
        if self.stop:
            return "emergency_stop"
        if self.leak:
            return "leak"
        if not self.water_ok:
            return "low_water"
        if (self.now()-self.heartbeat_at).total_seconds() >= self.watchdog_s:
            return "controller_watchdog"
        return self.latched if not self.armed else None

    def arm(self):
        if not self.connected or self.stop or self.leak or not self.water_ok:
            raise ValueError("interlocks and controller link must be healthy before ARM")
        self.heartbeat_at = self.now()
        self.armed, self.latched = True, None

    def _enforce(self):
        reason = self.fault()
        if reason:
            self.armed, self.latched = False, reason
            at = self.now()
            if reason == "controller_watchdog":
                at = min(at, self.heartbeat_at + timedelta(seconds=self.watchdog_s))
            if self.timing_mode == "r15_request_fixture":
                # Native health checks precede phase transitions at the same tick.
                self._advance_request(at, fault_reason=reason)
                self._advance_release(at)
            for cage_id in self.nodes:
                self._apply_state(cage_id, self.actuator_id, False, at, reason)
                self.nodes[cage_id]["deadlines"].pop(self.actuator_id, None)

    def start(self, gateway):
        restarted = self.gateway is not None
        self.gateway = gateway
        if restarted:
            self.armed, self.latched = False, "gateway_restarted"
            self.pending.clear()
            self.proposal_metadata.clear()
            self._enforce()
        self.step()

    def _local_guard(self, cage, actuator, node):
        reason = super()._local_guard(cage, actuator, node)
        if actuator.id != self.actuator_id:
            return reason
        if reason:
            return reason
        if self.fault():
            return self.fault()
        if self.busy and (self.active or {}).get("cage_id", self.valve) != cage.id:
            return "shared_pump_busy"
        return None

    def _apply_state(self, cage_id, actuator_id, state, at, reason, command_id=None):
        if actuator_id != self.actuator_id:
            return super()._apply_state(cage_id, actuator_id, state, at, reason, command_id)
        if self.timing_mode == "r15_request_fixture":
            if state:
                self._start_request(cage_id, command_id, at)
            elif self.active and self.active["cage_id"] == cage_id:
                if reason in ("manual", "prediction", "stop", "safety", "auto"):
                    # OFF received after a task tick reaches the wire on its next tick.
                    self.active["cancel_at"] = self._esp_tick(at, strictly_after=True)
                    self.active["cancel_reason"] = reason
                else:
                    self._finish_request(at, reason)
            elif self.valve == cage_id:
                self._close_valve(at)
                self.phase = "release_wait"
            return super()._apply_state(cage_id, actuator_id, state, at, reason, command_id)
        if state:
            if self.busy:
                raise RuntimeError("shared pump invariant violated")
            command = next(c for c in reversed(self.sent) if c["command_id"] == command_id)
            self.valve = cage_id
            self.transitions.append({"at": at.isoformat(), "output": "valve", "cage_id": cage_id, "on": True})
            self.phase = "preopen"
            self.active = {"command_id": command_id, "cage_id": cage_id,
                           "run_at": at + timedelta(seconds=self.preopen_s),
                           "duration_s": command["duration_s"], "started_at": None}
        elif self.valve == cage_id:
            if self.pump_on:
                end = self.active["run_at"] + timedelta(seconds=self.active["duration_s"])
                pump_at = min(at, end)  # local RUN deadline survives a delayed gateway tick
                self.pump_on = False
                self.transitions.append({"at": pump_at.isoformat(), "output": "pump", "cage_id": cage_id, "on": False})
                execution = {k: self.active[k] for k in ("command_id", "cage_id", "started_at")}
                execution.update(ended_at=pump_at.isoformat(), reason=reason if at <= end else "lease_finished",
                    data_source="simulation", volume_ml=None,
                    duration_s=(pump_at-datetime.fromisoformat(execution["started_at"])).total_seconds())
                assert 0 <= execution["duration_s"] <= MIST_MAX_RUN_SECONDS
                self.executions.append(execution)
                if self.gateway is not None:
                    self.gateway.audit("mist_execution", **execution)
            self.active = None
            if reason in ("lease_finished", "manual", "prediction"):
                self.phase = "drain"
                self.drain_until = at + timedelta(seconds=self.drain_s)
            else:
                self._close_valve(at)
                self.phase = "release_wait" if self.window_until else "idle"
        super()._apply_state(cage_id, actuator_id, state, at, reason, command_id)

    def _esp_tick(self, at, *, strictly_after=False):
        """The native-source fixture's 20ms grid, not a real scheduling guarantee."""
        elapsed = at - self.tick_origin
        micros = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
        ticks = micros // 20_000 + 1 if strictly_after else (micros + 19_999) // 20_000
        return self.tick_origin + timedelta(microseconds=ticks * 20_000)

    def _start_request(self, cage_id, command_id, at):
        if self.busy:
            raise RuntimeError("shared pump invariant violated")
        command = next(c for c in reversed(self.sent) if c["command_id"] == command_id)
        # duration_s is wire REQ hold, never a desired physical pump duration.
        hold_ms = int(command["duration_s"] * 1000)
        if not 1 <= hold_ms <= REQ_MAX_MS:
            raise ValueError("R15 request hold must be 1..5000 milliseconds")
        receipt_ms = (at - self.tick_origin) // timedelta(milliseconds=1)
        timing = request_timing(hold_ms, receipt_ms=receipt_ms)
        event = lambda key: (self.tick_origin + timedelta(milliseconds=timing[key])
                             if timing[key] is not None else None)
        request_on, valve_at = event("request_rise_ms"), event("qualified_ms")
        trigger_at, run_at = event("trigger_ms"), event("run_start_ms")
        request_off = event("request_fall_ms") or self._esp_tick(at + timedelta(milliseconds=hold_ms))
        planned = self.proposal_metadata.pop(command_id, {})
        expected = planned.get("expected_virtual_run_s")
        outcome = {"command_id": command_id, "cage_id": cage_id, "accepted_at": at.isoformat(),
                   "desired_run_s": expected, "planning_expected_virtual_run_s": expected,
                   "accepted_phase_expected_virtual_run_s": timing["expected_virtual_run_s"],
                   "timing_profile": TIMING_PROFILE, "receipt_phase_ms": receipt_ms % 20,
                   "selected_plan": planned.get("selected_plan"),
                   "request_hold_ms": hold_ms,
                   "planned_request_on_at": request_on.isoformat() if request_on else None,
                   "request_on_at": None,
                   "planned_request_off_at": request_off.isoformat(), "completed_at": None,
                   "pump_ended_at": None, "virtual_run_s": None, "data_source": "simulation",
                   "physical_execution_verified": False,
                   "mapping": "request_hold_forward_mapped_to_fixture_RUN" if planned else
                              "direct_request_hold_not_desired_RUN"}
        self.request_outcomes.append(outcome)
        self.active = {"command_id": command_id, "cage_id": cage_id, "duration_s": hold_ms / 1000,
                       "request_on_at": request_on, "valve_at": valve_at, "trigger_at": trigger_at,
                       "run_at": run_at, "request_off_at": request_off,
                       "run_limit_at": run_at + timedelta(seconds=RUN_MAX_S) if run_at else None,
                       "run_finished": False, "started_at": None, "outcome": outcome}
        self.recycle_until = at + timedelta(seconds=7)
        self.phase = "request_wait"

    def _advance_request(self, until, *, fault_reason=None):
        """Event schedule derived from native C under healthy ideal external pins.

        It reproduces the coupled-source oracle's qualification/PREOPEN/WINDOW
        schedule. Fault inputs remain explicit virtual interlocks, not analogue
        circuits, packet transport or a GPIO execution-feedback implementation.
        """
        active = self.active
        if not active:
            return
        end = min(active["request_off_at"], active.get("cancel_at", active["request_off_at"]))
        reason = active.get("cancel_reason", "request_hold_finished")
        if not self.connected and self.heartbeat_at + timedelta(seconds=self.watchdog_s) <= end:
            end = self.heartbeat_at + timedelta(seconds=self.watchdog_s)
            reason = "controller_watchdog"
        if fault_reason is not None and until <= end:
            end, reason = until, fault_reason
        if active["request_on_at"] is not None and active["request_on_at"] <= until and active["request_on_at"] < end:
            active["outcome"]["request_on_at"] = active["request_on_at"].isoformat()
        if (self.phase == "request_wait" and active["valve_at"] is not None
                and active["valve_at"] <= until and active["valve_at"] < end):
            self.valve, self.phase = active["cage_id"], "preopen"
            self.transitions.append({"at": active["valve_at"].isoformat(), "output": "valve",
                                     "cage_id": self.valve, "on": True})
        if (self.phase == "preopen" and active["trigger_at"] is not None
                and active["trigger_at"] <= until and active["trigger_at"] < end):
            self.window_until = active["trigger_at"] + timedelta(milliseconds=1, seconds=5)
            self.phase = "window_wait"
        if (self.phase == "window_wait" and active["run_at"] is not None
                and active["run_at"] <= until and active["run_at"] < end):
            self.phase, self.pump_on = "run", True
            active["started_at"] = active["run_at"].isoformat()
            self.transitions.append({"at": active["started_at"], "output": "pump",
                                     "cage_id": self.valve, "on": True})
        if self.pump_on:
            run_end = min(end, active["run_limit_at"], self.window_until)
            if until >= run_end:
                self._finish_run(run_end, reason if run_end == end else "run_limit")
        if until >= end:
            self._finish_request(end, reason)

    def _finish_run(self, end, reason):
        """RUN can finish while the ESP's REQ remains HIGH; keep that lease."""
        active = self.active
        if not active or active["run_finished"]:
            return
        duration = 0.0
        if self.pump_on:
            duration = (end - datetime.fromisoformat(active["started_at"])).total_seconds()
            assert 0 <= duration <= RUN_MAX_S
            self.transitions.append({"at": end.isoformat(), "output": "pump",
                                     "cage_id": active["cage_id"], "on": False})
            execution = {k: active[k] for k in ("command_id", "cage_id", "started_at")}
            execution.update(ended_at=end.isoformat(), duration_s=duration, reason=reason,
                             data_source="simulation", volume_ml=None, timing_mode=self.timing_mode,
                             physical_execution_verified=False,
                             expected_virtual_run_s=active["outcome"]["planning_expected_virtual_run_s"],
                             request_hold_ms=active["outcome"]["request_hold_ms"])
            self.executions.append(execution)
            if self.gateway is not None:
                self.gateway.audit("mist_execution", **execution)
            active["outcome"]["pump_ended_at"] = end.isoformat()
        self.pump_on = False
        active["run_finished"] = True
        active["outcome"].update(virtual_run_s=duration, run_reason=reason)
        if self.valve is not None and reason in (
                "run_limit", "request_hold_finished", "manual", "prediction", "lease_finished", "stop", "safety", "auto"):
            self.phase, self.drain_until = "drain", end + timedelta(seconds=self.drain_s)
        else:
            if self.valve is not None:
                self._close_valve(end)
            self.phase = "release_wait"

    def _finish_request(self, at, reason):
        active = self.active
        if not active:
            return
        end = min(at, active["request_off_at"], active.get("cancel_at", at))
        self._finish_run(end, reason)
        outcome = active["outcome"]
        duration = outcome["virtual_run_s"]
        outcome.update(completed_at=end.isoformat(), reason=reason,
                       desired_run_matches_virtual_run=(outcome["desired_run_s"] is not None and
                           abs(outcome["desired_run_s"]-duration) <= 1e-6))
        node = self.nodes[active["cage_id"]]
        node["states"][self.actuator_id] = False
        node["deadlines"].pop(self.actuator_id, None)
        self.active, self.pump_on = None, False
        self.request_low_at = end
        if reason not in ("request_hold_finished", "manual", "prediction", "lease_finished", "stop", "safety", "auto"):
            if self.valve is not None:
                self._close_valve(end)
            self.phase = "release_wait"

    def _close_valve(self, at):
        self.transitions.append({"at": at.isoformat(), "output": "valve", "cage_id": self.valve, "on": False})
        self.valve = None
        self.drain_until = None

    def _advance_release(self, until):
        if self.phase == "drain" and until >= self.drain_until:
            self._close_valve(self.drain_until)
            self.phase = "release_wait"
        if (self.phase == "release_wait" and self.active is None
                and (self.request_low_at is None or until >= self.request_low_at + timedelta(milliseconds=20))
                and (self.window_until is None or until >= self.window_until)
                and (self.recycle_until is None or until >= self.recycle_until)):
            self.phase, self.window_until = "idle", None

    def step(self):
        now = self.now()
        if self.connected:
            self.heartbeat_at = now
        # Advance the independent virtual sequencer before expiring its lease.
        # Otherwise a delayed host tick could erase a completed RUN entirely.
        if self.timing_mode == "r15_request_fixture":
            until = now if self.connected else min(now, self.heartbeat_at + timedelta(seconds=self.watchdog_s))
            sensor_fault = None
            if self.active and until == now:
                cage = self.gateway.cage(self.active["cage_id"])
                actuator = next(a for a in cage.actuators if a.id == self.actuator_id)
                sensor_fault = super()._local_guard(cage, actuator, self.nodes[cage.id])
            # Veto phase entry at an equal-time sensor fault. Restore earlier
            # DRAIN completion before the inherited guard sees today's state.
            self._advance_request(until, fault_reason=sensor_fault)
            self._advance_release(now)
        elif self.active and self.phase == "preopen" and now >= self.active["run_at"]:
            fault = self.fault()
            before_fault = not fault or (fault == "controller_watchdog" and
                self.active["run_at"] < self.heartbeat_at + timedelta(seconds=self.watchdog_s))
            cage = self.gateway.cage(self.active["cage_id"])
            actuator = next(a for a in cage.actuators if a.id == self.actuator_id)
            if before_fault and not super()._local_guard(cage, actuator, self.nodes[cage.id]):
                # Ideal zero-delay WINDOW acknowledgement, not analogue emulation.
                at = self.active["run_at"]
                self.window_until = at + timedelta(seconds=self.window_max_s)
                self.phase, self.pump_on = "run", True
                self.active["started_at"] = at.isoformat()
                self.transitions.append({"at": at.isoformat(), "output": "pump", "cage_id": self.valve, "on": True})
        self._enforce()
        super().step()
        if self.active:
            node = self.nodes[self.active["cage_id"]]
            # The legacy comparison preserves full desired RUN. The native
            # request fixture expires its wire hold from acceptance instead.
            end = (min(self.active["request_off_at"], self.active.get("cancel_at", self.active["request_off_at"]))
                   if self.timing_mode == "r15_request_fixture" else
                   self.active["run_at"] + timedelta(seconds=self.active["duration_s"]))
            node["deadlines"][self.actuator_id] = end
            actuator = next(a for a in self.gateway.cage(self.active["cage_id"]).actuators if a.id == self.actuator_id)
            node["cooldowns"][self.actuator_id] = end + timedelta(seconds=actuator.cooldown_s)
        self._advance_release(now)
        for command_id in tuple(self.proposal_metadata):
            if command_id in self.seen:
                self.proposal_metadata.pop(command_id)
        assert not self.pump_on or self.valve is not None
        request_active = self.active is not None and "cancel_at" not in self.active
        assert sum(n["states"][self.actuator_id] for n in self.nodes.values()) == int(request_active)


class MistingCoordinator:
    """FIFO between cages; newest prediction replaces a cage's pending request.

    Only virtual outputs are implemented. Synthetic GPU results can never be
    passed through this path to MQTT/physical devices.
    """
    def __init__(self, gateway, *, wall_time=time.time):
        if not isinstance(gateway.transport, VirtualMistingTransport):
            raise ValueError("physical predictive control is not commissioned")
        self.gateway = gateway
        self.transport = gateway.transport
        self.wall_time = wall_time
        self.queue = OrderedDict()
        self.outcomes = []

    def submit(self, result, request):
        validate_result(result, request, self.wall_time())
        if request["mode"] != "simulation" or result.hardware_execution_allowed is not False:
            raise ComputeFailure("simulation_only_controller")
        try:
            UUID(result.request_id)
        except ValueError:
            raise ComputeFailure("invalid_prediction_command_id") from None
        proposal = result.misting_proposal
        expected_schema = 2 if self.transport.timing_mode == TIMING_MODE else 1
        if result.schema_version != expected_schema or result.timing_mode != self.transport.timing_mode:
            raise ComputeFailure("prediction_timing_mode_mismatch")
        if proposal.pulse_seconds and (not request["water_ok"] or request["leak"]
                or proposal.decision != "learned_forecast" or proposal.pulse_seconds > proposal.max_pulse_seconds):
            raise ComputeFailure("inconsistent_misting_proposal")
        cage_id = result.cage_id
        self.gateway.cage(cage_id)
        self.queue.pop(cage_id, None)
        if result.misting_proposal.pulse_seconds:
            self.queue[cage_id] = (result, request)

    def cancel(self, reason):
        self.queue.clear()
        for cage in self.gateway.cages:
            self.gateway.stop_all(cage)
        self.gateway.audit("prediction_queue_cancelled", reason=reason)

    def cycle(self):
        if self.transport.fault() or not self.transport.connected:
            self.queue.clear()
            return
        if self.transport.busy or self.gateway.store.pending():
            return
        for cage_id, (result, request) in list(self.queue.items()):
            try:
                validate_result(result, request, self.wall_time())
            except ComputeFailure as error:
                self.outcomes.append({"cage_id": cage_id, "status": "discarded", "reason": error.code})
                del self.queue[cage_id]
                continue
            proposal = result.misting_proposal
            duration = proposal.request_hold_ms / 1000 if result.schema_version == 2 else proposal.pulse_seconds
            command = self.gateway.send_command(cage_id, CommandRequest(
                request_id=UUID(result.request_id), actuator_id=self.transport.actuator_id,
                action="on", duration_s=duration), source="prediction")
            if command["status"] == "published" and result.schema_version == 2:
                self.transport.proposal_metadata[command["command_id"]] = {
                    "expected_virtual_run_s": proposal.expected_virtual_run_s,
                    "selected_plan": result.selected_plan.model_dump(mode="json")}
            del self.queue[cage_id]
            self.outcomes.append({"cage_id": cage_id, "status": command["status"],
                                  "reason": command["reason"], "command_id": command["command_id"]})
            if command["status"] != "rejected":
                return
