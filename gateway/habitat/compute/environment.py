"""Sensor history -> remote GPU forecasts. This worker cannot dispatch actuators."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BeforeValidator, Field, model_validator

from habitat.common.models import Identifier, Model
from habitat.control.r15_timing import REQ_MAX_MS, RUN_MAX_S, TIMING_MODE, TIMING_PROFILE, request_timing
from .config import ComputeConfig
from .errors import ComputeFailure
from .http_client import HTTPComputeClient


MIST_MAX_RUN_SECONDS = RUN_MAX_S  # SAFE R15 Pico run_max_ms; not a measured water dose.


def strict_schema_version(value):
    if type(value) is not int:
        raise ValueError("prediction schema version must be an integer")
    return value


PredictionSchema = Annotated[Literal[1, 2], BeforeValidator(strict_schema_version)]


def validate_timing_contract(schema_version, timing_mode, timing_profile):
    if schema_version == 1 and timing_mode == "desired_run_ideal" and timing_profile is None:
        return
    if schema_version == 2 and timing_mode == TIMING_MODE and timing_profile == TIMING_PROFILE:
        return
    raise ValueError("prediction schema and timing contract differ")


class EnvironmentTarget(Model):
    cage_id: Identifier
    sensor_ids: list[Identifier] = Field(min_length=4, max_length=4)
    humidity_band: list[float] = Field(min_length=2, max_length=2)
    temperature_band: list[float] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def bounds(self):
        lo, hi = self.humidity_band
        tlo, thi = self.temperature_band
        if not (40 <= lo < hi <= 90 and hi-lo >= 5 and 20 <= tlo < thi <= 35):
            raise ValueError("target outside synthetic model domain")
        if len(set(self.sensor_ids)) != 4:
            raise ValueError("four distinct sensor channels required")
        return self


class EnvironmentConfig(ComputeConfig):
    storage_dir: str = "var/data/environment"
    targets: list[EnvironmentTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_targets(self):
        if len({t.cage_id for t in self.targets}) != len(self.targets):
            raise ValueError("duplicate environment target")
        return self


class Forecast(Model):
    horizon_minutes: Literal[5, 10, 30, 60]
    air_C: float
    humidity_pct: float
    surface_hot_C: float
    surface_cool_C: float


class MistingProposal(Model):
    pulse_seconds: float = Field(ge=0, le=MIST_MAX_RUN_SECONDS)
    decision: str
    cooldown_minutes: float = Field(ge=3)
    max_pulse_seconds: float = Field(gt=0, le=MIST_MAX_RUN_SECONDS)
    request_hold_ms: int | None = Field(default=None, strict=True, ge=0, le=REQ_MAX_MS)
    expected_virtual_run_s: float | None = Field(default=None, strict=True, ge=0, le=MIST_MAX_RUN_SECONDS)

    @model_validator(mode="after")
    def pulse_within_declared_limit(self):
        if self.pulse_seconds > self.max_pulse_seconds:
            raise ValueError("pulse exceeds declared RUN limit")
        return self


class SelectedMistingPlan(Model):
    request_hold_ms: list[Annotated[int, Field(strict=True, ge=0, le=REQ_MAX_MS)]] = Field(min_length=60, max_length=60)
    expected_virtual_run_s: list[Annotated[float, Field(strict=True, ge=0, le=MIST_MAX_RUN_SECONDS)]] = Field(min_length=60, max_length=60)

    @model_validator(mode="after")
    def forward_timing(self):
        for hold, run in zip(self.request_hold_ms, self.expected_virtual_run_s):
            if not math.isclose(run, request_timing(hold)["expected_virtual_run_s"], rel_tol=0, abs_tol=1e-9):
                raise ValueError("selected plan differs from the declared virtual timing profile")
        return self


class EnvironmentResult(Model):
    schema_version: PredictionSchema
    timing_mode: Literal["desired_run_ideal", "r15_request_fixture"] = "desired_run_ideal"
    timing_profile: Literal["r15_esp20_pico_window1ms_phase0_v1"] | None = None
    selected_plan: SelectedMistingPlan | None = None
    request_id: str
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    mode: Literal["SIMULATION_ONLY", "SHADOW_ONLY"]
    training_source: Literal["SYNTHETIC_ONLY"]
    field_validated: Literal[False]
    hardware_execution_allowed: Literal[False]
    model_id: str
    device: Literal["cuda"]
    gpu: str
    measurement_end_epoch: float
    generated_at_epoch: float
    expires_at_epoch: float
    prediction_condition: str
    predictions: list[Forecast] = Field(min_length=4, max_length=4)
    misting_proposal: MistingProposal
    inference_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def timing_contract(self):
        validate_timing_contract(self.schema_version, self.timing_mode, self.timing_profile)
        proposal = self.misting_proposal
        if self.schema_version == 1:
            if (self.selected_plan is not None or proposal.request_hold_ms is not None
                    or proposal.expected_virtual_run_s is not None):
                raise ValueError("legacy RUN predictions cannot include a request timing plan")
        else:
            if self.selected_plan is None or proposal.request_hold_ms is None or proposal.expected_virtual_run_s is None:
                raise ValueError("request-aware predictions require the selected plan and first request outcome")
            hold, run = self.selected_plan.request_hold_ms[0], self.selected_plan.expected_virtual_run_s[0]
            if any(value > proposal.max_pulse_seconds for value in self.selected_plan.expected_virtual_run_s):
                raise ValueError("selected plan exceeds the declared RUN limit")
            if (proposal.request_hold_ms != hold
                    or not math.isclose(proposal.expected_virtual_run_s, run, rel_tol=0, abs_tol=1e-9)
                    or not math.isclose(proposal.pulse_seconds, run, rel_tol=0, abs_tol=1e-9)):
                raise ValueError("first misting proposal differs from the selected request plan")
        return self


class EnvironmentHealth(Model):
    service: Literal["environment_prediction"]
    status: str
    model_files_present: bool
    cuda_probed: bool
    field_validated: Literal[False]
    hardware_execution_allowed: Literal[False]
    horizons_minutes: list[int]


def validate_result(result, request, now):
    if any(getattr(result, k) != request[k] for k in ("request_id", "site_id", "gateway_id", "cage_id")):
        raise ComputeFailure("prediction_identity_mismatch")
    if (result.schema_version != request.get("schema_version", 1)
            or result.timing_mode != request.get("timing_mode", "desired_run_ideal")
            or result.timing_profile != request.get("timing_profile")):
        raise ComputeFailure("prediction_timing_mismatch")
    expected = "SIMULATION_ONLY" if request["mode"] == "simulation" else "SHADOW_ONLY"
    if (result.mode != expected or result.measurement_end_epoch != request["sample_times"][-1]
            or result.generated_at_epoch > now+5 or result.generated_at_epoch < now-60
            or not now < result.expires_at_epoch <= min(result.generated_at_epoch+30.01, result.measurement_end_epoch+90.01)
            or [p.horizon_minutes for p in result.predictions] != [5, 10, 30, 60]):
        raise ComputeFailure("invalid_or_expired_prediction")
    return result


def predict(client, request):
    result = client.json("POST", "/v1/environment/predict", EnvironmentResult, json=request)
    return validate_result(result, request, time.time())


def minute_history(samples, sensor_ids, now, *, data_source="sensor", executions=()):
    """Take the last valid sample within 15s of each minute boundary; never fill gaps."""
    end = int(now // 60) * 60
    selected = {}
    for sample in samples:
        stamp = datetime.fromisoformat(sample["sampled_at"]).timestamp()
        boundary = int((stamp+14.999999) // 60) * 60
        if not end-29*60 <= boundary <= end or not 0 <= boundary-stamp < 15:
            continue
        if sample["data_source"] != data_source:
            continue
        readings = sample["readings"]
        if not all(readings.get(s, {}).get("quality") == "valid" for s in sensor_ids):
            continue
        if boundary not in selected or stamp > selected[boundary][0]:
            selected[boundary] = (stamp, [readings[s]["value"] for s in sensor_ids] + [0.0])
    times = [float(end-(29-i)*60) for i in range(30)]
    if not all(t in selected for t in times):
        raise ComputeFailure(f"waiting_history_{len(selected)}_of_30")
    history = [selected[t][1] for t in times]
    previous_finish = float("-inf")
    seen = set()
    executions = sorted(executions, key=lambda e: e["started_at"])
    for event in executions:
        if event["data_source"] != data_source:
            raise ComputeFailure("mist_history_source_mismatch")
        start = datetime.fromisoformat(event["started_at"]).timestamp()
        finish = datetime.fromisoformat(event["ended_at"]).timestamp()
        if (not math.isfinite(event["duration_s"]) or finish < start or finish > now
                or start < previous_finish or event["command_id"] in seen
                or abs(finish-start-event["duration_s"]) > 1e-6):
            raise ComputeFailure("invalid_mist_execution")
        previous_finish = finish
        seen.add(event["command_id"])
        for i, stamp in enumerate(times):
            history[i][4] += max(0., min(finish, stamp)-max(start, stamp-60))
    if any(row[4] > 6.000001 for row in history):
        raise ComputeFailure("mist_history_outside_model_domain")
    return times, history


def write_status(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class EnvironmentWorker:
    def __init__(self, gateway, *, client=None):
        self.gateway = gateway
        self.config = gateway.settings.environment
        self.client = client or HTTPComputeClient(self.config, self.config.token())
        self.last_minute = {}
        self.state = {"enabled": True, "mode": "shadow", "hardware_execution_allowed": False,
                      "training_source": "SYNTHETIC_ONLY", "cages": {}}

    def cycle(self):
        now = time.time()
        for target in self.config.targets:
            cage_id = target.cage_id
            state = {"status": "waiting_sensors", "checked_at_epoch": now,
                     "hardware_execution_allowed": False}
            try:
                with self.gateway.lock:
                    cage = self.gateway.cage(cage_id)
                    latest = self.gateway.store.latest_telemetry(cage_id)
                    if not latest:
                        raise ComputeFailure("waiting_sensors")
                    if (latest["geometry_revision"] != cage.geometry_revision
                            or latest["placement_revision"] != cage.placement_revision):
                        raise ComputeFailure("sensor_revision_mismatch")
                    if not -2 <= now-datetime.fromisoformat(latest["sampled_at"]).timestamp() <= cage.stale_after_s:
                        raise ComputeFailure("stale_sensors")
                    if (not -2 <= now-datetime.fromisoformat(latest["received_at"]).timestamp() <= cage.stale_after_s
                            or any(latest["readings"].get(s, {}).get("quality") != "valid" for s in target.sensor_ids)):
                        raise ComputeFailure("sensor_unavailable")
                    # Sensor commissioning assumes no external/manual water input. Real mist
                    # operation requires measured pulse history, not command intent.
                    if self.gateway.settings.hardware_outputs_enabled or any(latest["actuators"].values()):
                        raise ComputeFailure("waiting_measured_mist_history")
                    samples = [s for s in self.gateway.store.history(cage_id, 2200)
                               if s["geometry_revision"] == cage.geometry_revision
                               and s["placement_revision"] == cage.placement_revision]
                times, history = minute_history(samples, target.sensor_ids, now)
                if self.last_minute.get(cage_id) == times[-1]:
                    previous = self.state["cages"].get(cage_id, {})
                    previous["result_is_current"] = now < previous.get("result", {}).get("expires_at_epoch", 0)
                    previous["checked_at_epoch"] = now
                    continue
                self.last_minute[cage_id] = times[-1]
                request = {"schema_version": 2, "mode": "shadow", "request_id": str(uuid4()),
                    "timing_mode": TIMING_MODE, "timing_profile": TIMING_PROFILE,
                    "site_id": self.gateway.settings.site_id, "gateway_id": self.gateway.settings.gateway_id,
                    "cage_id": cage_id, "sample_times": times, "history": history,
                    "humidity_band": target.humidity_band, "temperature_band": target.temperature_band,
                    "water_ok": False, "leak": False}
                result = predict(self.client, request)
                state.update(status="shadow_forecast", result=result.model_dump(mode="json"), result_is_current=True,
                             mist_history="assumed_zero_during_sensor_commissioning_no_external_water",
                             interlocks="not_commissioned; proposals_vetoed")
            except ComputeFailure as error:
                state["status"] = error.code
            self.state["cages"][cage_id] = state
        self.state["checked_at_epoch"] = now
        write_status(Path(self.config.storage_dir) / "status.json", self.state)

    def close(self):
        self.client.close()
