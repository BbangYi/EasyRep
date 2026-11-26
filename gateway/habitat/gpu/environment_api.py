"""Additional simulation prediction route for the existing authenticated GPU API."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from habitat.compute.environment import (EnvironmentResult, PredictionSchema,
                                         validate_result, validate_timing_contract)
from habitat.compute.errors import ComputeFailure
from habitat.gpu.backend import Backend, SUPERVISE


class ResidentPredictor:
    """One supervised CUDA process; requests are serialized by the route's gate."""
    timeout_seconds = 20

    def __init__(self, backend, worker):
        self.backend, self.worker, self.process = backend, worker, None

    def close(self):
        if self.process is not None:
            process, self.process = self.process, None
            try:
                Backend._stop(process)
            finally:
                process.stdin.close()
                process.stdout.close()

    def request(self, payload):
        raw = json.dumps(payload, allow_nan=False).encode() + b'\n'
        if len(raw) > 65536:
            raise ValueError('prediction input too large')
        try:
            if self.process is None or self.process.poll() is not None:
                self.close()
                # Reuse the API's parent-death watchdog and token-filtered environment.
                args = [sys.executable, '-c', SUPERVISE, str(os.getpid()),
                        self.backend.python, '-u', str(self.worker), '--serve']
                self.process = subprocess.Popen(args, cwd=self.worker.parent, env=self.backend.env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0, start_new_session=True)
                os.set_blocking(self.process.stdin.fileno(), False)
                os.set_blocking(self.process.stdout.fileno(), False)
            process = self.process
            deadline = time.monotonic() + self.timeout_seconds
            output = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdin, selectors.EVENT_WRITE)
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('prediction deadline exceeded')
                    for key, _ in selector.select(remaining):
                        if key.fileobj is process.stdin:
                            sent = os.write(key.fd, raw)
                            raw = raw[sent:]
                            if not raw:
                                selector.unregister(process.stdin)
                        else:
                            chunk = os.read(key.fd, 4096)
                            if not chunk:
                                raise OSError('prediction worker exited')
                            output.extend(chunk)
                            if len(output) > 65536:
                                raise ValueError('prediction response too large')
                            if b'\n' in output:
                                result = json.loads(output)
                                if not isinstance(result, dict) or raw:
                                    raise ValueError('invalid prediction response')
                                if 'error' not in result and (result.get('request_id') != payload['request_id']
                                        or result.get('hardware_execution_allowed') is not False):
                                    raise ValueError('mismatched prediction response')
                                return result
        except (OSError, ValueError, KeyError):
            self.close()
            raise


class PredictionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    schema_version: PredictionSchema
    timing_mode: Literal['desired_run_ideal','r15_request_fixture'] = 'desired_run_ideal'
    timing_profile: Literal['r15_esp20_pico_window1ms_phase0_v1'] | None = None
    mode: Literal['simulation','shadow']
    request_id: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    site_id: str = Field(min_length=1,max_length=80)
    gateway_id: str = Field(min_length=1,max_length=80)
    cage_id: str = Field(min_length=1,max_length=80)
    sample_times: list[float] = Field(min_length=30,max_length=30)
    history: list[Annotated[list[float], Field(min_length=5,max_length=5)]] = Field(min_length=30,max_length=30)
    humidity_band: list[float] = Field(min_length=2,max_length=2)
    temperature_band: list[float] = Field(min_length=2,max_length=2)
    water_ok: bool
    leak: bool

    @model_validator(mode='after')
    def timing_contract(self):
        validate_timing_contract(self.schema_version, self.timing_mode, self.timing_profile)
        return self


def mount_environment(app,config,credential,in_scope,error):
    root=Path(__file__).resolve().parents[2]/'experiments/environment_sim'
    worker=root/'gpu_predict.py'
    model_dir=Path(os.environ.get('HABITAT_ENV_MODEL_DIR', root.parents[1]/'var/models/environment_sim')).expanduser().resolve()
    gate=threading.Lock()
    predictor=ResidentPredictor(Backend({**config.backend, 'name':'not_configured'}),worker)

    @app.get('/v1/environment/health')
    def environment_health(_=Depends(credential)):
        ready=worker.is_file() and all((model_dir/name).is_file() for name in ('model_3sensors.npz', 'training_report.json'))
        return {'service':'environment_prediction','status':'simulation_configured' if ready else 'not_configured',
                'model_files_present':ready,'cuda_probed':False,'field_validated':False,
                'hardware_execution_allowed':False,'horizons_minutes':[5,10,30,60]}

    @app.post('/v1/environment/predict')
    def environment_predict(request:PredictionRequest,owner=Depends(credential)):
        payload=request.model_dump(mode='json')
        if not in_scope(owner,payload):
            raise error(403,'scope_denied','Prediction scope is not registered for this token')
        if not worker.is_file(): raise error(503,'prediction_unavailable','Prediction worker is unavailable')
        if not gate.acquire(blocking=False): raise error(429,'prediction_busy','Try again after the current request')
        try:
            # ponytail: one resident process and no request backlog; batch across cages only if measured load needs it.
            result=predictor.request(payload)
            if not isinstance(result, dict):
                raise ValueError('invalid prediction response')
            if result.get('error')=='invalid_prediction_input':
                raise error(422,'invalid_prediction_input','History or simulation target is invalid')
            if 'error' in result:
                predictor.close()
                raise error(503,'prediction_unavailable','GPU inference failed')
            validate_result(EnvironmentResult.model_validate(result), payload, time.time())
            # Validate the parsed contract but retain the worker's legacy JSON shape.
            return result
        except (OSError,ValueError,KeyError,ComputeFailure):
            predictor.close()
            raise error(503,'prediction_unavailable','GPU inference failed or timed out') from None
        finally: gate.release()

    def close():
        with gate:
            predictor.close()
    return close
