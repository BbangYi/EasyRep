"""Run the real Pi gateway and HTTPS CUDA API with virtual sensors/pump only.

The existing uncalibrated Plant is supplied explicitly as a fixture module.
Its coefficients are declared synthetic inputs, never measured specifications.
No production DB, MQTT, GPIO, serial, camera or SaaS writer is constructed.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from uuid import uuid4

from habitat.compute.environment import minute_history, predict, write_status
from habitat.compute.http_client import HTTPComputeClient
from habitat.control.misting import MistingCoordinator, VirtualMistingTransport
from habitat.control.r15_timing import REQ_MAX_MS, RUN_MAX_S, TIMING_MODE, TIMING_PROFILE
from habitat_gateway.config import CloudConfig, load_settings
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import Reading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-config", type=Path, required=True)
    parser.add_argument("--plant-module", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minutes", type=int, default=120)
    parser.add_argument("--timing-mode", choices=("r15_request_fixture", "desired_run_ideal"),
                        default="r15_request_fixture",
                        help="Current REQ timing fixture by default; ideal desired RUN is a separate legacy comparison.")
    args = parser.parse_args()
    if not 60 <= args.minutes <= 360:
        parser.error("use 60..360 explicitly simulated minutes")
    # Fail instead of overwriting a previous experiment or selecting production storage.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    production = load_settings(args.gateway_config)
    config = production.model_copy(deep=True, update={"transport": "simulated", "hardware_outputs_enabled": True,
        "database": str(args.output_dir/"simulation.sqlite3"), "cloud": CloudConfig(enabled=False), "cameras": []})
    for cage in config.cages:
        for actuator in cage.actuators:
            if actuator.id == "mister":
                actuator.max_on_s = REQ_MAX_MS / 1000 if args.timing_mode == TIMING_MODE else RUN_MAX_S
    spec = importlib.util.spec_from_file_location("habitat_plant_fixture", args.plant_module)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    cfg = fixture.settings()
    assert cfg["mode"] == "SYNTHETIC_ONLY" and len(config.environment.targets) == 3
    virtual_now = [datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)]
    now = lambda: virtual_now[0]
    transport = VirtualMistingTransport(config, now, telemetry_interval_s=5., timing_mode=args.timing_mode)
    gateway = Gateway(config, transport, now=now)
    controller = MistingCoordinator(gateway)
    client = HTTPComputeClient(production.environment, production.environment.token())
    plants = {t.cage_id: fixture.Plant(4000+i, args.minutes+30, cfg, initial_rh=t.humidity_band[0]+2)
              for i, t in enumerate(config.environment.targets)}
    start = time.monotonic()
    latencies, model_ids, failures = [], set(), []
    traces = []
    hypotheses = {k: cfg[k] for k in ("air_exchange_per_min", "mist_rh_gain_per_second",
                                    "evaporation_fraction_per_min", "max_pulse_seconds", "cooldown_minutes")}

    def sample():
        for target in config.environment.targets:
            transport.nodes[target.cage_id]["readings"] = {
                sid: Reading(value=float(value), quality="valid")
                for sid, value in zip(target.sensor_ids, plants[target.cage_id].observe())}
        transport.last_emitted.clear()
        transport.step()

    transport.start(gateway)
    transport.interlocks(water_ok=True, leak=False, stop=False)
    transport.arm()
    sample()
    for _ in range(29):
        for plant in plants.values():
            plant.step(0.)
        virtual_now[0] += timedelta(minutes=1)
        sample()

    try:
        with (args.output_dir/"requests.jsonl").open("w", encoding="utf-8") as requests, \
             (args.output_dir/"trace.jsonl").open("w", encoding="utf-8") as output:
            for minute in range(args.minutes):
                before = len(transport.executions)
                requests_before = len(transport.request_outcomes)
                frame = {"minute": minute, "virtual_time": now().isoformat(), "cages": {}}
                for target in config.environment.targets:
                    cage_id = target.cage_id
                    executions = [e for e in transport.executions if e["cage_id"] == cage_id]
                    times, history = minute_history(gateway.store.history(cage_id, 2500), target.sensor_ids,
                        now().timestamp(), data_source="simulation", executions=executions)
                    # Accelerated fixture history retains minute spacing; this explicitly
                    # simulated request is rebased to the live API's freshness clock.
                    end = float(int(time.time()//60)*60)
                    request = {"schema_version": 1, "mode": "simulation", "request_id": str(uuid4()),
                        "site_id": config.site_id, "gateway_id": config.gateway_id, "cage_id": cage_id,
                        "sample_times": [end-60*(29-i) for i in range(30)], "history": history,
                        "humidity_band": target.humidity_band, "temperature_band": target.temperature_band,
                        "water_ok": True, "leak": False}
                    if args.timing_mode == TIMING_MODE:
                        request.update(schema_version=2, timing_mode=TIMING_MODE, timing_profile=TIMING_PROFILE)
                    started = time.monotonic()
                    result = predict(client, request)
                    elapsed = time.monotonic()-started
                    latencies.append(elapsed)
                    model_ids.add(result.model_id)
                    controller.submit(result, request)
                    requests.write(json.dumps({"simulation_minute": minute, "virtual_history_end": times[-1],
                        "timestamp_rebased_for_live_api": True, "request": request,
                        "response": result.model_dump(mode="json"), "round_trip_s": elapsed})+"\n")
                    requests.flush()
                    frame["cages"][cage_id] = {"observed": history[-1][:4],
                        "previous_executed_s": history[-1][4], "proposed_s": result.misting_proposal.pulse_seconds,
                        "proposed_request_hold_ms": result.misting_proposal.request_hold_ms,
                        "selected_plan": result.selected_plan.model_dump(mode="json") if result.selected_plan else None,
                        "proposal_semantics": "phase0_fixture_expected_virtual_RUN_seconds" if result.schema_version == 2 else
                                              "legacy_ideal_virtual_RUN_seconds",
                        "forecast": [p.model_dump() for p in result.predictions]}
                # Exercise the unchanged Gateway.send_command/ACK/lease/control tick.
                controller.cycle()
                transport.step()
                for _ in range(240):
                    virtual_now[0] += timedelta(seconds=.25)
                    transport.step()
                    gateway.tick()
                    controller.cycle()
                    transport.step()
                assert not transport.busy and not transport.pump_on and not controller.queue
                for target in config.environment.targets:
                    cage_id = target.cage_id
                    actual = sum(e["duration_s"] for e in transport.executions[before:] if e["cage_id"] == cage_id)
                    plants[cage_id].step(actual)
                    frame["cages"][cage_id]["executed_s"] = actual
                    frame["cages"][cage_id]["request_outcomes"] = [
                        r for r in transport.request_outcomes[requests_before:] if r["cage_id"] == cage_id]
                sample()
                traces.append(frame)
                output.write(json.dumps(frame)+"\n")
                output.flush()
                if minute % 10 == 9:
                    print(json.dumps({"completed_virtual_minutes": minute+1, "cuda_requests": len(latencies),
                                      "virtual_pulses": len(transport.executions)}), flush=True)
            assert len(latencies) == args.minutes*len(config.environment.targets)
            if args.timing_mode == "desired_run_ideal":
                assert all(any(e["cage_id"] == c and e["duration_s"] > 0 for e in transport.executions)
                           for c in gateway.cages)
            # A 1s REQ can finish during PREOPEN with zero RUN. Keep the outcome.
            assert all(r["completed_at"] is not None for r in transport.request_outcomes)
    except Exception as exc:
        failures.append({"type": type(exc).__name__, "code": getattr(exc, "code", "run_failed")})
        controller.cancel("simulation_failed")
        transport.step()
        raise
    finally:
        transport.interlocks(water_ok=True, leak=False, stop=True)
        record = {"status": "FAIL" if failures or len(traces) != args.minutes else "PASS",
            "scope": "ACTUAL_PI_ACTUAL_CUDA_VIRTUAL_SENSORS_AND_PUMP", "host": platform.node(),
            "architecture": platform.machine(), "python": platform.python_version(),
            "physical_hardware_tested": False, "production_database_written": False,
            "mqtt_published": False, "saas_data_sent": False, "field_validated": False,
            "hardware_execution_allowed": False, "minutes_simulated": len(traces),
            "elapsed_wall_s": time.monotonic()-start, "cuda_requests": len(latencies),
            "model_ids": sorted(model_ids), "round_trip_median_s": statistics.median(latencies) if latencies else None,
            "round_trip_max_s": max(latencies) if latencies else None,
            "virtual_pulse_count": len(transport.executions),
            "executed_seconds_by_cage": {c: sum(e["duration_s"] for e in transport.executions if e["cage_id"] == c)
                                         for c in gateway.cages},
            "plant_fixture_sha256": hashlib.sha256(args.plant_module.read_bytes()).hexdigest(),
            "plant_config_sha256": hashlib.sha256((args.plant_module.parent/"simulation_config.json").read_bytes()).hexdigest(),
            "uncalibrated_fixture_coefficients": hypotheses, "water_volume_ml": None,
            "timing_mode": args.timing_mode, "time_equivalence_validated": False,
            "simulation_pass_semantics": "software path completed; neither physical timing nor forecast accuracy validated",
            "forecast_validation": "not_scored: selected conditional plan is preserved, but later replanning changes future actions",
            "request_mapping": "request_hold_forward_mapped_to_fixture_RUN",
            "timing_profile": TIMING_PROFILE if args.timing_mode == TIMING_MODE else None,
            "request_outcomes": transport.request_outcomes,
            "completed_requests_with_zero_run": sum(r["virtual_run_s"] == 0 for r in transport.request_outcomes),
            "desired_run_mismatch_count": sum(r["desired_run_s"] is not None and r["completed_at"] is not None
                and not r["desired_run_matches_virtual_run"] for r in transport.request_outcomes),
            "timing_comparison_scope": "phase0 planning fixture versus executed fixture receipt phase; not physical timing equivalence",
            "time_semantics": "accelerated virtual device timers; live HTTPS/CUDA latency measured separately",
            "sequence_timing": {"preopen_s": transport.preopen_s, "max_run_s": cfg['max_pulse_seconds'],
                "drain_s": transport.drain_s, "window_min_s": transport.window_min_s,
                "remote_watchdog_s": transport.watchdog_s,
                "window_max_s": transport.window_max_s, "window_start": "after_preopen",
                "window_acknowledgement": "ideal_zero_delay_not_hardware_emulation",
                "release_wait": "until_computed_window_max_elapsed"},
            "actuator_state_semantics": "accepted virtual request including preopen; transitions and executions give virtual pump state",
            "history_semantics": "executed virtual pump intervals in prior minute; no requested-duration substitution",
            "temperature_humidity_scope": "synthetic fixture response only; no real enclosure accuracy claim",
            "failures": failures, "controller_outcomes": controller.outcomes,
            "final_pump_on": transport.pump_on, "final_valve": transport.valve, "final_phase": transport.phase}
        if args.timing_mode == "r15_request_fixture":
            record["sequence_timing"].update(esp_task_ms=20, qualification_ms=20,
                pico_tick_ms=1, external_window_fixture_s=5., bridge_recycle_s=7.,
                request_deadline="receive_time_plus_hold_then_next_ESP_tick",
                window_acknowledgement="ideal_1ms_response_native_source_fixture_not_analog_emulation",
                max_request_hold_ms=REQ_MAX_MS,
                independent_RUN_deadline="RUN_start_plus_3000ms_even_while_REQ_HIGH",
                release_wait="until_REQ_LOW_stable_20ms_WINDOW_low_and_7s_request_recycle_elapsed")
        else:
            record["request_mapping"] = "legacy_ideal_full_desired_RUN_not_current_R15_REQ_timing"
            record["forecast_validation"] = "not_scored: full selected future plan absent and later replanning changes actions"
        write_status(args.output_dir/"result.json", record)
        write_status(args.output_dir/"executions.json", transport.executions)
        write_status(args.output_dir/"transitions.json", transport.transitions)
        assert gateway.store.cloud_backlog()["pending_events"] == 0
        gateway.store.close()
        client.close()
    print(json.dumps({k: v for k, v in record.items() if k != "controller_outcomes"}), flush=True)


if __name__ == "__main__":
    main()
