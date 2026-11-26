from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from habitat.compute.environment import EnvironmentResult, minute_history
from habitat.compute.errors import ComputeFailure
from habitat.control.misting import MistingCoordinator, VirtualMistingTransport
from habitat.control.r15_timing import REQ_MAX_MS, TIMING_MODE, TIMING_PROFILE, request_timing
from habitat_gateway.config import load_settings, CloudConfig
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import CommandRequest, Reading
from habitat_gateway.transport import SimulatedTransport
from tests.conftest import Clock


def result_for(cage_id, wall, pulse=3.):
    request = {"mode": "simulation", "request_id": str(uuid4()), "site_id": "STORE-001",
               "gateway_id": "PI-001", "cage_id": cage_id, "sample_times": [wall-60*(29-i) for i in range(30)],
               "water_ok": True, "leak": False}
    result = EnvironmentResult(schema_version=1, request_id=request["request_id"], site_id="STORE-001",
        gateway_id="PI-001", cage_id=cage_id, mode="SIMULATION_ONLY", training_source="SYNTHETIC_ONLY",
        field_validated=False, hardware_execution_allowed=False, model_id="test-fixture-not-a-GPU-run",
        device="cuda", gpu="test-fixture", measurement_end_epoch=wall, generated_at_epoch=wall,
        expires_at_epoch=wall+30., prediction_condition="fixture", inference_ms=0.,
        predictions=[{"horizon_minutes": h, "air_C": 25., "humidity_pct": 65.,
                      "surface_hot_C": 27., "surface_cool_C": 24.} for h in (5, 10, 30, 60)],
        misting_proposal={"pulse_seconds": pulse, "decision": "learned_forecast",
                         "cooldown_minutes": 3., "max_pulse_seconds": 3.})
    return result, request


def request_result_for(cage_id, wall, hold=3.):
    result, request = result_for(cage_id, wall)
    hold_ms = int(hold * 1000)
    run = request_timing(hold_ms)["expected_virtual_run_s"]
    request.update(schema_version=2, timing_mode=TIMING_MODE, timing_profile=TIMING_PROFILE)
    body = result.model_dump(mode="json")
    body.update(schema_version=2, timing_mode=TIMING_MODE, timing_profile=TIMING_PROFILE,
                selected_plan={"request_hold_ms": [hold_ms]+[0]*59,
                               "expected_virtual_run_s": [run]+[0.]*59})
    body["misting_proposal"].update(pulse_seconds=run, request_hold_ms=hold_ms, expected_virtual_run_s=run)
    return EnvironmentResult.model_validate(body), request


@pytest.fixture
def shared(tmp_path, request):
    timing_mode = getattr(request, "param", "desired_run_ideal")
    config = load_settings("configs/examples/reptile-city.toml").model_copy(deep=True, update={
        "transport": "simulated", "hardware_outputs_enabled": True,
        "database": str(tmp_path/"simulation.sqlite3"), "cloud": CloudConfig(enabled=False)})
    for cage in config.cages:
        for actuator in cage.actuators:
            if actuator.id == "mister":
                actuator.max_on_s = REQ_MAX_MS / 1000 if timing_mode == TIMING_MODE else 3
    clock = Clock()
    transport = VirtualMistingTransport(config, clock, timing_mode=timing_mode)
    gateway = Gateway(config, transport, now=clock)
    transport.start(gateway)
    transport.interlocks(water_ok=True, leak=False, stop=False)
    transport.arm()
    wall = [1_800_000_000.]
    controller = MistingCoordinator(gateway, wall_time=lambda: wall[0])
    yield gateway, transport, clock, controller, wall
    gateway.store.close()


def advance(shared, seconds):
    gateway, transport, clock, controller, _ = shared
    for _ in range(round(seconds*4)):
        clock.advance(.25)
        transport.step()
        gateway.tick()
        controller.cycle()
        transport.step()


def start(shared, cage="CAGE-001"):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*result_for(cage, wall[0]))
    controller.cycle()
    transport.step()
    assert not transport.pump_on and transport.phase == "preopen"
    advance(shared, 1.)
    assert transport.pump_on


def test_three_cages_use_one_pump_fifo_and_record_only_executed_seconds(shared):
    gateway, transport, clock, controller, wall = shared
    for cage in gateway.cages:
        controller.submit(*result_for(cage, wall[0]))
    advance(shared, 25)
    assert [e["cage_id"] for e in transport.executions] == list(gateway.cages)
    assert [e["duration_s"] for e in transport.executions] == [3., 3., 3.]
    assert all(e["volume_ml"] is None for e in transport.executions)
    assert not transport.pump_on and transport.valve is None
    assert len([a for a in gateway.store.audit_events() if a["kind"] == "mist_execution"]) == 3
    assert gateway.store.cloud_backlog()["pending_events"] == 0
    pattern = [("valve", True), ("pump", True), ("pump", False), ("valve", False)]
    assert [(e["output"], e["on"]) for e in transport.transitions] == pattern*3
    for i in range(0, len(transport.transitions), 4):
        times = [datetime.fromisoformat(e["at"]) for e in transport.transitions[i:i+4]]
        assert [(b-a).total_seconds() for a,b in zip(times, times[1:])] == [1., 3., 1.]
        if i:
            prior_trigger = datetime.fromisoformat(transport.transitions[i-3]["at"])
            assert (times[0]-prior_trigger).total_seconds() >= transport.window_max_s


def test_stop_during_preopen_never_runs_pump_and_timing_config_cannot_expand(shared):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*result_for("CAGE-001", wall[0]))
    controller.cycle()
    transport.step()
    assert transport.phase == "preopen" and not transport.pump_on
    advance(shared, .5)
    transport.interlocks(water_ok=True, leak=False, stop=True)
    advance(shared, 5)
    assert not transport.pump_on and transport.valve is None
    assert transport.executions == []
    assert [(e["output"], e["on"]) for e in transport.transitions] == [("valve", True), ("valve", False)]
    unsafe = gateway.settings.model_copy(deep=True)
    unsafe.cages[0].actuators[0].max_on_s = 3.001
    with pytest.raises(ValueError, match="RUN limit"):
        VirtualMistingTransport(unsafe, clock)
    with pytest.raises(ValueError, match="watchdog"):
        VirtualMistingTransport(gateway.settings, clock, watchdog_s=1.001)


def test_watchdog_trips_at_one_second_and_late_tick_cannot_extend_run(shared):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    transport.connected = False
    clock.advance(1.)
    transport.step()
    assert transport.fault() == "controller_watchdog"
    assert transport.executions[-1]["duration_s"] == 1.
    transport.connected = True
    transport.arm()
    advance(shared, 6.)
    start(shared, "CAGE-002")
    clock.advance(10.)
    transport.step()
    assert transport.executions[-1]["duration_s"] == 3.
    assert not transport.pump_on and transport.valve is None


@pytest.mark.parametrize("disconnect_after_s, expected_run", [(None, 3.), (0., 0.), (.25, .25)])
def test_delayed_tick_during_preopen_preserves_sequence_and_watchdog(shared, disconnect_after_s, expected_run):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*result_for("CAGE-001", wall[0]))
    controller.cycle()
    transport.step()
    if disconnect_after_s is not None:
        advance(shared, disconnect_after_s)
        transport.connected = False
    clock.advance(10.)
    transport.step()
    assert sum(e["duration_s"] for e in transport.executions) == expected_run
    assert not transport.pump_on and transport.valve is None
    if disconnect_after_s is None:
        assert not transport.busy
        times = [datetime.fromisoformat(e["at"]) for e in transport.transitions]
        assert [(b-a).total_seconds() for a,b in zip(times, times[1:])] == [1., 3., 1.]
    else:
        assert transport.fault() == "controller_watchdog"


@pytest.mark.parametrize("fault", ["leak", "low_water", "stop", "link_loss", "invalid_sensor"])
def test_interruption_stops_output_and_does_not_record_requested_duration(shared, fault):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    advance(shared, .25 if fault == "link_loss" else 1.25)
    if fault == "link_loss":
        transport.connected = False
        advance(shared, 2.25)
    elif fault == "invalid_sensor":
        transport.patch_readings("CAGE-001", {"RH1": Reading(quality="disconnected")})
    else:
        transport.interlocks(water_ok=fault != "low_water", leak=fault == "leak", stop=fault == "stop")
    assert not transport.pump_on
    assert 0 < transport.executions[-1]["duration_s"] < 3.
    if fault != "invalid_sensor":
        transport.connected = True
        transport.interlocks(water_ok=True, leak=False, stop=False)
        transport.step()
        assert transport.fault() is not None  # explicit ARM required
        transport.arm()
        assert transport.fault() is None


def test_local_controller_rejects_simultaneous_manual_commands(shared):
    gateway, transport, *_ = shared
    for cage in gateway.cages:
        gateway.send_command(cage, CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=3.))
    transport.step()
    assert transport.valve == "CAGE-001"
    assert sum(c["status"] == "applied" for c in gateway.store.commands()) == 1
    assert sum(c["reason"] == "shared_pump_busy" for c in gateway.store.commands()) == 2


def test_duplicate_prediction_is_not_replayed(shared):
    gateway, transport, clock, controller, wall = shared
    r, q = result_for("CAGE-001", wall[0])
    controller.submit(r, q)
    advance(shared, 8)
    controller.submit(r, q)
    advance(shared, 8)
    assert len(transport.executions) == 1


def test_expired_pending_predictions_are_discarded(shared):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    controller.submit(*result_for("CAGE-002", wall[0]))
    wall[0] += 31
    advance(shared, 10)
    assert len(transport.executions) == 1
    assert controller.outcomes[-1]["reason"] == "invalid_or_expired_prediction"


def test_gateway_restart_does_not_resume_and_preserves_interruption_log(shared):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    controller.submit(*result_for("CAGE-002", wall[0]))
    advance(shared, 1.)
    gateway.store.close()
    restarted = Gateway(gateway.settings, transport, now=clock)
    transport.start(restarted)
    shared_gateway = gateway
    # Keep fixture cleanup on the newly opened store.
    shared_gateway.store = restarted.store
    new_controller = MistingCoordinator(restarted, wall_time=lambda: wall[0])
    assert not transport.pump_on and transport.fault() == "gateway_restarted"
    assert not new_controller.queue
    assert transport.executions[-1]["duration_s"] == 1.
    assert any(a["kind"] == "mist_execution" for a in restarted.store.audit_events())


def test_failed_gpu_request_cancels_pending_work_and_stops_active(shared):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    controller.submit(*result_for("CAGE-002", wall[0]))
    advance(shared, 1.)
    controller.cancel("compute_network_error")
    transport.step()
    assert not transport.pump_on and not controller.queue
    assert transport.executions[-1]["duration_s"] == 1.


def test_cooldown_invalid_sensor_and_overlong_commands_are_rejected(shared):
    gateway, transport, clock, controller, wall = shared
    start(shared)
    advance(shared, 8.)
    controller.submit(*result_for("CAGE-001", wall[0]))
    controller.cycle()
    assert controller.outcomes[-1]["reason"] == "previous_lease_or_cooldown_active"
    transport.patch_readings("CAGE-002", {"RH1": Reading(quality="crc_error")})
    controller.submit(*result_for("CAGE-002", wall[0]))
    controller.cycle()
    assert controller.outcomes[-1]["reason"] == "sensor_unavailable:RH1"
    over = gateway.send_command("CAGE-003", CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=3.01))
    assert over["reason"] == "duration_exceeds_limit"


def test_hardware_and_cloud_cannot_be_activated_by_the_simulator(shared):
    gateway, transport, clock, *_ = shared
    for changes in ({"transport": "mqtt"}, {"cloud": CloudConfig(enabled=True, endpoint="https://example.test/v1/edge/sync")}):
        with pytest.raises(ValueError):
            VirtualMistingTransport(gateway.settings.model_copy(update=changes), clock)
    other = Gateway(gateway.settings.model_copy(update={"database": ":memory:"}), SimulatedTransport(gateway.settings))
    try:
        with pytest.raises(ValueError):
            MistingCoordinator(other)
    finally:
        other.store.close()


def test_minute_history_uses_interrupted_execution_not_command_intent(shared):
    gateway, transport, clock, controller, wall = shared
    for _ in range(30):
        clock.advance(60.)
        transport.step()
    start(shared)
    advance(shared, 1.25)
    transport.interlocks(water_ok=True, leak=True, stop=False)
    clock.advance(57.75)
    transport.step()
    times, history = minute_history(gateway.store.history("CAGE-001", 2200), ["T1", "RH1", "T2", "T3"],
        clock().timestamp(), data_source="simulation", executions=transport.executions)
    assert history[-1][4] == 1.25
    assert sum(row[4] for row in history) == 1.25
    with pytest.raises(ComputeFailure, match="invalid_mist_execution"):
        minute_history(gateway.store.history("CAGE-001", 2200), ["T1", "RH1", "T2", "T3"],
            clock().timestamp(), data_source="simulation", executions=transport.executions*2)


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
@pytest.mark.parametrize("hold, run_s", [(1., 0.), (2., .959), (3., 1.959)])
@pytest.mark.parametrize("delayed_tick", [False, True])
def test_request_fixture_matches_native_esp_pico_oracle(shared, hold, run_s, delayed_tick):
    """Oracle: check_cage_node.py --r15-archive, original source, accepted at 400ms.

    The original C produced REQ HIGH420, qualify440, TRIG1440, WINDOW/RUN1441,
    then REQ LOW1400/2400/3400. These are virtual fixture times, not calibration.
    """
    gateway, transport, clock, controller, wall = shared
    origin = clock()
    clock.advance(.4)
    gateway.send_command("CAGE-001", CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=hold))
    transport.step()
    assert transport.phase == "request_wait" and transport.valve is None
    if delayed_tick:
        clock.advance(10.)
        transport.step()
    else:
        advance(shared, 10.)
    assert sum(e["duration_s"] for e in transport.executions) == run_s
    outcome, = transport.request_outcomes
    assert outcome["desired_run_s"] is None and outcome["request_hold_ms"] == hold * 1000
    assert outcome["virtual_run_s"] == run_s and not outcome["desired_run_matches_virtual_run"]
    assert outcome["physical_execution_verified"] is False
    assert (datetime.fromisoformat(outcome["completed_at"]) - origin).total_seconds() == .4 + hold
    assert (datetime.fromisoformat(outcome["request_on_at"]) - origin).total_seconds() == .420
    events = [(e["output"], e["on"], (datetime.fromisoformat(e["at"])-origin).total_seconds())
              for e in transport.transitions]
    expected = [("valve", True, .440)]
    if run_s:
        expected += [("pump", True, 1.441), ("pump", False, .4 + hold)]
    expected += [("valve", False, 1.4 + hold)]
    assert events == expected
    assert not transport.busy and not transport.pump_on and transport.valve is None
    assert not gateway.store.pending()


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
def test_request_fixture_zero_run_cancellation_is_recorded_without_phantom_history(shared):
    gateway, transport, clock, controller, wall = shared
    for _ in range(30):
        clock.advance(60.)
        transport.step()
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    clock.advance(.5)
    transport.step()
    assert transport.valve == "CAGE-001" and not transport.pump_on
    controller.cancel("operator_stop")
    transport.step()
    clock.advance(59.5)
    transport.step()
    assert not transport.executions
    outcome, = transport.request_outcomes
    assert outcome["virtual_run_s"] == 0. and outcome["completed_at"] is not None
    assert not outcome["desired_run_matches_virtual_run"]
    _, history = minute_history(gateway.store.history("CAGE-001", 2500), ["T1", "RH1", "T2", "T3"],
        clock().timestamp(), data_source="simulation", executions=transport.executions)
    assert sum(row[4] for row in history) == 0.


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
def test_request_fixture_cancel_before_first_gpio_tick_never_claims_request_high(shared):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    clock.advance(.010)
    controller.cancel("operator_stop")
    transport.step()
    clock.advance(10.)
    transport.step()
    outcome, = transport.request_outcomes
    assert outcome["planned_request_on_at"] is not None and outcome["request_on_at"] is None
    assert outcome["completed_at"] is not None and outcome["virtual_run_s"] == 0.
    assert not transport.executions and not transport.transitions


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
def test_request_fixture_watchdog_at_run_boundary_does_not_create_zero_length_pump_event(shared):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    clock.advance(.041)
    transport.step()
    transport.connected = False  # Existing virtual heartbeat model expires at t=1.041s.
    clock.advance(10.)
    transport.step()
    outcome, = transport.request_outcomes
    assert outcome["virtual_run_s"] == 0. and outcome["reason"] == "controller_watchdog"
    assert not transport.executions
    assert all(e["output"] != "pump" for e in transport.transitions)


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
@pytest.mark.parametrize("fault", ["leak", "low_water", "stop"])
def test_request_fixture_direct_interlock_precedes_run_at_same_instant(shared, fault):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    clock.advance(1.041)  # First possible RUN tick in this native-source fixture.
    transport.interlocks(water_ok=fault != "low_water", leak=fault == "leak", stop=fault == "stop")
    outcome, = transport.request_outcomes
    assert outcome["virtual_run_s"] == 0.
    assert outcome["reason"] == ("emergency_stop" if fault == "stop" else fault)
    assert not transport.executions and not transport.pump_on and transport.valve is None
    assert all(e["output"] != "pump" for e in transport.transitions)


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
def test_request_fixture_late_fault_preserves_earlier_completed_drain(shared):
    gateway, transport, clock, controller, wall = shared
    origin = clock()
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    clock.advance(10.)  # No host steps between acceptance and this later fault.
    transport.interlocks(water_ok=True, leak=True, stop=False)
    execution, = transport.executions
    assert execution["duration_s"] == 1.959
    assert [(e["output"], e["on"], (datetime.fromisoformat(e["at"])-origin).total_seconds())
            for e in transport.transitions] == [
                ("valve", True, .040), ("pump", True, 1.041),
                ("pump", False, 3.), ("valve", False, 4.)]
    assert transport.request_outcomes[0]["reason"] == "request_hold_finished"
    assert transport.fault() == "leak" and not transport.pump_on and transport.valve is None


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
@pytest.mark.parametrize("fault", ["leak", "low_water", "stop", "link_loss", "invalid_sensor"])
def test_request_fixture_safety_interruption_records_only_virtual_run(shared, fault):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 3.))
    controller.cycle()
    transport.step()
    advance(shared, 1.5)
    assert transport.pump_on
    if fault == "link_loss":
        transport.connected = False
        clock.advance(10.)
        transport.step()
    elif fault == "invalid_sensor":
        transport.patch_readings("CAGE-001", {"RH1": Reading(quality="disconnected")})
    else:
        transport.interlocks(water_ok=fault != "low_water", leak=fault == "leak", stop=fault == "stop")
    outcome, = transport.request_outcomes
    execution, = transport.executions
    assert 0 < execution["duration_s"] < 1.959
    assert outcome["virtual_run_s"] == execution["duration_s"]
    assert not outcome["desired_run_matches_virtual_run"]
    assert not transport.pump_on and transport.active is None


@pytest.mark.parametrize("shared", ["r15_request_fixture"], indirect=True)
def test_request_fixture_seven_second_shared_gate_survives_zero_run(shared):
    gateway, transport, clock, controller, wall = shared
    origin = clock()
    first, second, third = gateway.cages
    gateway.send_command(first, CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=1.))
    transport.step()
    advance(shared, 6.75)
    assert len(transport.request_outcomes) == 1 and transport.busy
    advance(shared, .25)
    gateway.send_command(second, CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=1.))
    transport.step()
    advance(shared, 7.)
    gateway.send_command(third, CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=1.))
    transport.step()
    advance(shared, 11.)
    assert [r["cage_id"] for r in transport.request_outcomes] == list(gateway.cages)
    assert [(datetime.fromisoformat(r["accepted_at"])-origin).total_seconds()
            for r in transport.request_outcomes] == [0., 7., 14.]
    assert all(r["virtual_run_s"] == 0. for r in transport.request_outcomes)
    assert not transport.executions and not transport.pump_on and not transport.busy


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_request_fixture_rejects_legacy_prediction_before_publishing(shared):
    gateway, transport, clock, controller, wall = shared
    with pytest.raises(ComputeFailure, match="prediction_timing_mode_mismatch"):
        controller.submit(*result_for("CAGE-001", wall[0]))
    assert not transport.sent and not controller.queue and not transport.request_outcomes


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
@pytest.mark.parametrize("hold, phase, expected", [
    (2., 0, .959), (2., 19, .979), (3., 0, 1.959), (3., 19, 1.979),
    (4., 0, 2.959), (4., 19, 2.979), (4.5, 0, 3.), (4.5, 19, 3.), (5., 0, 3.), (5., 19, 3.)])
def test_request_aware_plan_reproduces_native_phase_observations(shared, hold, phase, expected):
    gateway, transport, clock, controller, wall = shared
    clock.advance(.4 + phase / 1000)
    result, request = request_result_for("CAGE-001", wall[0], hold)
    controller.submit(result, request)
    controller.cycle()
    transport.step()
    clock.advance(10.)
    transport.step()
    execution, = transport.executions
    outcome, = transport.request_outcomes
    assert execution["duration_s"] == expected
    assert outcome["accepted_phase_expected_virtual_run_s"] == expected
    assert outcome["planning_expected_virtual_run_s"] == result.misting_proposal.expected_virtual_run_s
    assert outcome["request_hold_ms"] == int(hold * 1000)
    assert outcome["selected_plan"] == result.selected_plan.model_dump(mode="json")
    assert execution["physical_execution_verified"] is False and execution["volume_ml"] is None
    assert not transport.busy and not transport.active and not transport.pump_on


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_run_limit_keeps_wire_request_and_original_drain_then_recycle(shared):
    gateway, transport, clock, controller, wall = shared
    origin = clock()
    controller.submit(*request_result_for("CAGE-001", wall[0], 5.))
    controller.cycle()
    transport.step()
    advance(shared, 4.25)
    assert not transport.pump_on and transport.phase == "drain"
    assert transport.active is not None and transport.nodes["CAGE-001"]["states"]["mister"]
    assert transport.executions[0]["duration_s"] == 3.
    assert transport.request_outcomes[0]["completed_at"] is None
    advance(shared, 1.)
    assert transport.active is None and transport.valve is None and transport.busy
    assert not transport.nodes["CAGE-001"]["states"]["mister"]
    command = gateway.send_command("CAGE-002", CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=5.))
    assert command["status"] == "rejected" and command["reason"] == "shared_pump_busy"
    assert [(e["output"], e["on"], (datetime.fromisoformat(e["at"])-origin).total_seconds())
            for e in transport.transitions] == [
        ("valve", True, .040), ("pump", True, 1.041), ("pump", False, 4.041), ("valve", False, 5.041)]
    advance(shared, 1.75)
    assert not transport.busy


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_request_aware_three_cages_reach_full_run_fifo(shared):
    gateway, transport, clock, controller, wall = shared
    for cage in gateway.cages:
        controller.submit(*request_result_for(cage, wall[0], 4.5))
    advance(shared, 25.)
    assert [e["cage_id"] for e in transport.executions] == list(gateway.cages)
    assert [e["duration_s"] for e in transport.executions] == [3., 3., 3.]
    assert [e["request_hold_ms"] for e in transport.executions] == [4500]*3
    assert all(e["volume_ml"] is None for e in transport.executions)
    assert not transport.busy and not controller.queue and not transport.proposal_metadata


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_sensor_fault_at_run_entry_has_no_phantom_pump_event(shared):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 5.))
    controller.cycle()
    transport.step()
    clock.advance(1.041)
    transport.patch_readings("CAGE-001", {"RH1": Reading(quality="disconnected")})
    assert transport.request_outcomes[0]["virtual_run_s"] == 0.
    assert transport.request_outcomes[0]["reason"] == "local_sensor_invalid"
    assert not transport.executions and not any(e["output"] == "pump" for e in transport.transitions)


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_late_sensor_fault_preserves_completed_run_and_drain_times(shared):
    gateway, transport, clock, controller, wall = shared
    origin = clock()
    controller.submit(*request_result_for("CAGE-001", wall[0], 5.))
    controller.cycle()
    transport.step()
    clock.advance(10.)
    transport.patch_readings("CAGE-001", {"RH1": Reading(quality="disconnected")})
    assert transport.executions[0]["duration_s"] == 3.
    assert [(e["output"], e["on"], (datetime.fromisoformat(e["at"])-origin).total_seconds())
            for e in transport.transitions] == [
        ("valve", True, .040), ("pump", True, 1.041), ("pump", False, 4.041), ("valve", False, 5.041)]
    assert not transport.busy and not transport.pump_on and transport.valve is None


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
@pytest.mark.parametrize("hold", [.001, .020])
def test_request_expiring_before_first_gpio_tick_has_no_edges(shared, hold):
    gateway, transport, clock, controller, wall = shared
    gateway.send_command("CAGE-001", CommandRequest(request_id=uuid4(), actuator_id="mister", action="on", duration_s=hold))
    transport.step()
    advance(shared, 10.)
    outcome, = transport.request_outcomes
    assert outcome["virtual_run_s"] == 0. and outcome["request_on_at"] is None
    assert not transport.transitions and not transport.executions and not transport.busy


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_request_aware_duplicate_prediction_keeps_one_lease_and_one_plan(shared):
    gateway, transport, clock, controller, wall = shared
    result, request = request_result_for("CAGE-001", wall[0], 5.)
    controller.submit(result, request)
    controller.cycle()
    assert len(transport.proposal_metadata) == 1
    controller.submit(result, request)
    advance(shared, 8.)
    controller.submit(result, request)
    advance(shared, 8.)
    assert len(transport.request_outcomes) == len(transport.executions) == 1
    assert transport.executions[0]["duration_s"] == 3.
    assert len(gateway.store.commands()) == 1
    assert not controller.queue and not transport.proposal_metadata


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
def test_request_aware_expired_queued_plan_never_publishes(shared):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 5.))
    controller.cycle()
    transport.step()
    controller.submit(*request_result_for("CAGE-002", wall[0], 5.))
    wall[0] += 31.
    advance(shared, 10.)
    assert [e["cage_id"] for e in transport.executions] == ["CAGE-001"]
    assert len(gateway.store.commands()) == 1
    assert controller.outcomes[-1]["reason"] == "invalid_or_expired_prediction"
    assert not controller.queue and not transport.proposal_metadata


@pytest.mark.parametrize("shared", [TIMING_MODE], indirect=True)
@pytest.mark.parametrize("restart_at, expected_run", [(None, 0.), (1.25, .209), (4.25, 3.)])
def test_request_aware_restart_drops_unaccepted_plan_and_never_resumes(shared, restart_at, expected_run):
    gateway, transport, clock, controller, wall = shared
    controller.submit(*request_result_for("CAGE-001", wall[0], 5.))
    controller.cycle()
    if restart_at is not None:
        transport.step()
        clock.advance(restart_at)
        transport.step()
        assert transport.active is not None
    else:
        assert transport.proposal_metadata and transport.pending
    gateway.store.close()
    restarted = Gateway(gateway.settings, transport, now=clock)
    gateway.store = restarted.store  # Fixture closes the reopened store.
    transport.start(restarted)
    new_controller = MistingCoordinator(restarted, wall_time=lambda: wall[0])
    clock.advance(10.)
    transport.step()
    new_controller.cycle()
    assert sum(e["duration_s"] for e in transport.executions) == expected_run
    assert len(transport.executions) == int(expected_run > 0)
    assert not transport.active and not transport.pending and not transport.proposal_metadata
    assert not transport.pump_on and transport.valve is None and not new_controller.queue
    assert transport.fault() == "gateway_restarted"
    if restart_at is None:
        assert not transport.request_outcomes
        assert gateway.store.commands()[0]["reason"] == "gateway_restarted_state_unknown"
    else:
        assert transport.request_outcomes[0]["reason"] == "gateway_restarted"
        assert any(e["kind"] == "mist_execution" for e in gateway.store.audit_events())
