from datetime import datetime, timezone
import copy
from types import SimpleNamespace
import threading
import time

import httpx
import pytest
from pydantic import ValidationError

from habitat.compute.config import ComputeConfig
from habitat.compute.environment import EnvironmentResult, EnvironmentWorker, MIST_MAX_RUN_SECONDS, minute_history, predict, validate_result
from habitat.compute.errors import ComputeFailure
from habitat.compute.http_client import HTTPComputeClient
from habitat.control.r15_timing import REQ_MAX_MS, TIMING_MODE, TIMING_PROFILE
from habitat.gpu.environment_api import PredictionRequest
from habitat_gateway.config import load_settings


def test_sensor_only_profile_and_minute_history_reject_gaps_invalid_or_simulated_data():
    settings = load_settings("configs/examples/reptile-city.toml")
    assert len(settings.cages) == len(settings.environment.targets) == 3
    assert len(settings.cameras) == 2 * len(settings.cages)
    assert {camera.cage_id for camera in settings.cameras} == {cage.id for cage in settings.cages}
    for cage in settings.cages:
        cameras = [camera for camera in settings.cameras if camera.cage_id == cage.id]
        assert len(cameras) == 2 and {camera.view for camera in cameras} == {"top", "front"}
    assert settings.hardware_outputs_enabled is False
    assert all(a.max_on_s == REQ_MAX_MS / 1000 for c in settings.cages for a in c.actuators)
    assert MIST_MAX_RUN_SECONDS == 3  # The request limit does not extend pump RUN.
    assert all([a.id for a in c.actuators] == ["mister"] and not c.policies for c in settings.cages)
    target = settings.environment.targets[0]
    now = 1800001800.
    samples = [{"sampled_at": datetime.fromtimestamp(now-(29-i)*60-2, timezone.utc).isoformat(),
        "data_source": "sensor", "readings": {k: {"value": v, "quality": "valid"}
        for k,v in zip(target.sensor_ids, [25., 50., 26., 24.])}} for i in range(30)]
    stamps, rows = minute_history(list(reversed(samples)), target.sensor_ids, now+3)
    assert len(stamps) == len(rows) == 30 and rows[-1] == [25., 50., 26., 24., 0.]
    assert stamps[-1] == now and all(b-a == 60 for a,b in zip(stamps, stamps[1:]))
    for broken in (samples[:-1], [{**s, "data_source": "simulation"} for s in samples]):
        with pytest.raises(ComputeFailure, match="waiting_history"):
            minute_history(broken, target.sensor_ids, now+3)
    bad = copy.deepcopy(samples); bad[5]["readings"]["T1"] = {"value": None, "quality": "invalid"}
    with pytest.raises(ComputeFailure, match="waiting_history"):
        minute_history(bad, target.sensor_ids, now+3)


def prediction_pair(now, schema_version=1):
    request = {"schema_version": schema_version, "request_id": "probe-1", "site_id": "STORE-001", "gateway_id": "PI-001",
        "cage_id": "CAGE-001", "mode": "simulation", "sample_times": [now - (29-i)*60 for i in range(30)],
        "history": [[25., 60., 26., 24., 0.] for _ in range(30)], "humidity_band": [55., 65.],
        "temperature_band": [23., 29.], "water_ok": True, "leak": False}
    response = {"schema_version": 1, **{k:request[k] for k in ("request_id","site_id","gateway_id","cage_id")},
        "mode": "SIMULATION_ONLY", "training_source": "SYNTHETIC_ONLY", "field_validated": False,
        "hardware_execution_allowed": False, "model_id": "synthetic-mlp-test", "device": "cuda", "gpu": "test",
        "measurement_end_epoch": now, "generated_at_epoch": now, "expires_at_epoch": now+30,
        "prediction_condition": "test", "predictions": [{"horizon_minutes": h, "air_C": 25.,
            "humidity_pct": 60., "surface_hot_C": 26., "surface_cool_C": 24.} for h in (5,10,30,60)],
        "misting_proposal": {"pulse_seconds": 0., "decision": "interlock", "cooldown_minutes": 3., "max_pulse_seconds": 3.},
        "inference_ms": 10.}
    if schema_version == 2:
        timing = {"timing_mode": TIMING_MODE, "timing_profile": TIMING_PROFILE}
        request.update(timing)
        holds, runs = [0]*60, [0.]*60
        holds[0], runs[0] = 2000, .959
        holds[6], runs[6] = 4500, 3.
        response.update(schema_version=2, **timing,
            selected_plan={"request_hold_ms": holds, "expected_virtual_run_s": runs})
        response["misting_proposal"].update(pulse_seconds=.959, decision="learned_forecast",
            request_hold_ms=2000, expected_virtual_run_s=.959)
    return request, response


def test_gpu_contract_binds_identity_expiry_mode_and_forbids_hardware_authority():
    now = time.time()
    request, response = prediction_pair(now)
    request.pop("schema_version")  # Old callers default to schema 1 / ideal RUN.
    body = response.copy()
    def handle(req):
        assert str(req.url) == "https://gpu.test/v1/environment/predict"
        assert req.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json=body)
    client = HTTPComputeClient(ComputeConfig(enabled=True, base_url="https://gpu.test"), "test-token",
                               transport=httpx.MockTransport(handle))
    try:
        assert predict(client, request).hardware_execution_allowed is False
        for change in ({"cage_id":"OTHER"}, {"expires_at_epoch":now-1}, {"mode":"SHADOW_ONLY"},
                       {"hardware_execution_allowed":True}, {"inference_ms":float("nan")}):
            body = {**response, **change}
            if "inference_ms" in change:
                with pytest.raises(ValidationError): EnvironmentResult.model_validate(body)
            else:
                with pytest.raises(ComputeFailure): predict(client, request)
    finally:
        client.close()


def test_prediction_versions_preserve_legacy_and_bind_forward_request_plan():
    now = time.time()
    request, body = prediction_pair(now)
    legacy = EnvironmentResult.model_validate(body)
    assert legacy.timing_mode == "desired_run_ideal" and legacy.timing_profile is None
    assert legacy.selected_plan is None and legacy.misting_proposal.request_hold_ms is None
    assert legacy.misting_proposal.expected_virtual_run_s is None
    assert PredictionRequest.model_validate(request).timing_mode == "desired_run_ideal"
    request, body = prediction_pair(now, 2)
    result = EnvironmentResult.model_validate(body)
    assert validate_result(result, request, now) is result
    assert PredictionRequest.model_validate(request).timing_profile == TIMING_PROFILE
    assert result.selected_plan.expected_virtual_run_s[6] == 3.
    assert result.misting_proposal.pulse_seconds == .959
    for changes in ({"schema_version": 1}, {"timing_mode": "desired_run_ideal"}, {"timing_profile": None}):
        with pytest.raises(ComputeFailure, match="prediction_timing_mismatch"):
            validate_result(result, request | changes, now)
    with pytest.raises(ComputeFailure, match="prediction_timing_mismatch"):
        validate_result(legacy, request, now)


@pytest.mark.parametrize("version,updates", [
    (1, {"timing_mode": TIMING_MODE}), (1, {"timing_profile": TIMING_PROFILE}),
    (2, {"timing_mode": "desired_run_ideal"}), (2, {"timing_profile": None}),
    (2, {"timing_profile": "unknown"}), (2, {"timing_mode": "unknown"}),
])
def test_prediction_request_and_result_reject_mixed_timing_contract(version, updates):
    request, body = prediction_pair(time.time(), version)
    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(request | updates)
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body | updates)


@pytest.mark.parametrize("version", [True, 1.0, 2.0, "2"])
def test_prediction_schema_version_is_not_coerced(version):
    request, body = prediction_pair(time.time())
    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(request | {"schema_version": version})
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body | {"schema_version": version})


@pytest.mark.parametrize("changes", [
    {"request_hold_ms": None}, {"expected_virtual_run_s": None}, {"request_hold_ms": 3000},
    {"expected_virtual_run_s": 1.959}, {"pulse_seconds": 2.}, {"max_pulse_seconds": 2.},
])
def test_prediction_first_action_must_match_complete_selected_plan(changes):
    _, body = prediction_pair(time.time(), 2)
    body["misting_proposal"].update(changes)
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body)


@pytest.mark.parametrize("field,value", [
    ("request_hold_ms", -1), ("request_hold_ms", 5001), ("request_hold_ms", 2000.0),
    ("request_hold_ms", "2000"), ("request_hold_ms", True),
    ("expected_virtual_run_s", 2.), ("expected_virtual_run_s", 3.001),
    ("expected_virtual_run_s", float("nan")), ("expected_virtual_run_s", ".959"),
    ("expected_virtual_run_s", True),
])
def test_prediction_full_plan_rejects_invalid_or_nonforward_values(field, value):
    _, body = prediction_pair(time.time(), 2)
    body["selected_plan"][field][6] = value  # Validate future actions, not only the first.
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body)


@pytest.mark.parametrize("length", [59, 61])
def test_prediction_requires_exactly_sixty_future_minutes(length):
    _, body = prediction_pair(time.time(), 2)
    body["selected_plan"] = {"request_hold_ms": [0]*length, "expected_virtual_run_s": [0.]*length}
    body["misting_proposal"].update(pulse_seconds=0., request_hold_ms=0, expected_virtual_run_s=0.)
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body)


def test_missing_plan_or_legacy_request_fields_are_rejected():
    _, body = prediction_pair(time.time(), 2)
    body.pop("selected_plan")
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body)
    _, body = prediction_pair(time.time())
    body["misting_proposal"].update(request_hold_ms=0, expected_virtual_run_s=0.)
    with pytest.raises(ValidationError):
        EnvironmentResult.model_validate(body)


def test_shadow_worker_requests_fixture_contract_without_enabling_control(tmp_path, monkeypatch):
    now = 1800001800.
    monkeypatch.setattr("habitat.compute.environment.time.time", lambda: now)
    settings = load_settings("configs/examples/reptile-city.toml")
    settings.environment.storage_dir = str(tmp_path)
    settings.environment.targets = settings.environment.targets[:1]
    cage, target = settings.cages[0], settings.environment.targets[0]
    samples = [{"sampled_at": datetime.fromtimestamp(now-(29-i)*60, timezone.utc).isoformat(),
        "received_at": datetime.fromtimestamp(now-(29-i)*60, timezone.utc).isoformat(),
        "data_source": "sensor", "geometry_revision": cage.geometry_revision,
        "placement_revision": cage.placement_revision, "actuators": {},
        "readings": {k: {"value": v, "quality": "valid"} for k, v in zip(target.sensor_ids, [25., 60., 26., 24.])}}
        for i in range(30)]
    calls = []
    def respond(method, path, model, *, json):
        calls.append(json)
        assert json["schema_version"] == 2 and json["mode"] == "shadow"
        assert json["timing_mode"] == TIMING_MODE and json["timing_profile"] == TIMING_PROFILE
        assert json["water_ok"] is False and json["leak"] is False
        assert all(row[4] == 0 for row in json["history"])
        _, body = prediction_pair(now, 2)
        body.update({key: json[key] for key in ("request_id", "site_id", "gateway_id", "cage_id")})
        body.update(mode="SHADOW_ONLY", selected_plan={"request_hold_ms": [0]*60, "expected_virtual_run_s": [0.]*60})
        body["misting_proposal"].update(pulse_seconds=0., decision="interlock", request_hold_ms=0, expected_virtual_run_s=0.)
        return model.model_validate(body)
    # No dispatch method exists on this fixture: the worker must only request and save forecasts.
    gateway = SimpleNamespace(settings=settings, lock=threading.RLock(), cage=lambda _: cage,
        store=SimpleNamespace(latest_telemetry=lambda _: samples[-1], history=lambda *_: samples))
    worker = EnvironmentWorker(gateway, client=SimpleNamespace(json=respond))
    worker.cycle()
    state = worker.state["cages"][cage.id]
    assert len(calls) == 1 and state["status"] == "shadow_forecast"
    assert state["result"]["hardware_execution_allowed"] is False
    assert state["interlocks"] == "not_commissioned; proposals_vetoed"
