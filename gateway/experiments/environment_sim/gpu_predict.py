"""GPU-side inference worker. Bounded JSON requests, one result per request.

Run with the existing habitat-gpu Python. This simulation model cannot authorize
hardware operation. The existing authenticated GPU API invokes this worker.
"""
from functools import lru_cache
import hashlib
import json
import sys
import time

import numpy as np
import torch
from predictive_misting import (Model, ROOT, HISTORY, HORIZON, REPORT_HORIZONS, CHANNELS,
                               choose, choose_request_plan, settings)
from habitat.control.r15_timing import TIMING_MODE, TIMING_PROFILE


class CUDAForecast(Model):
    def __init__(self):
        super().__init__(3)
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable')
        self.gpu_weights = {k: torch.tensor(v, device='cuda') for k, v in self.w.items()}

    def forward(self, x):
        with torch.inference_mode():
            y = torch.tensor(x, dtype=torch.float32, device='cuda')
            for i in range(3):
                y = y @ self.gpu_weights['w'+str(i)].T + self.gpu_weights['b'+str(i)]
                if i < 2: y = torch.tanh(y)
            return y.cpu().numpy()


@lru_cache(maxsize=1)
def loaded_model(weights_sha256):
    model = CUDAForecast()
    if hashlib.sha256((ROOT/'model_3sensors.npz').read_bytes()).hexdigest() != weights_sha256:
        raise RuntimeError('model changed during loading')
    return model


def predict(request):
    schema = request['schema_version']
    if type(schema) is not int or schema not in (1, 2):
        raise ValueError('unsupported prediction schema')
    if schema == 1:
        if request.get('timing_mode', 'desired_run_ideal') != 'desired_run_ideal' or request.get('timing_profile') is not None:
            raise ValueError('schema1 requires historical desired_run_ideal timing')
    elif request.get('timing_mode') != TIMING_MODE or request.get('timing_profile') != TIMING_PROFILE:
        raise ValueError('schema2 requires the known R15 request fixture timing profile')
    now = time.time()
    history = np.asarray(request['history'], dtype=float)
    timestamps = np.asarray(request['sample_times'], dtype=float)
    if request['mode'] not in ('simulation','shadow') or history.shape != (HISTORY,5) or timestamps.shape != (HISTORY,):
        raise ValueError('simulation request with 30 one-minute rows required')
    if not np.isfinite(history).all() or not np.isfinite(timestamps).all():
        raise ValueError('non-finite input')
    if not np.all(np.abs(np.diff(timestamps)-60) <= 2) or not -5 <= now-timestamps[-1] <= 90:
        raise ValueError('stale, future or irregular sensor history')
    if not ((history[:,:4] >= [15,5,10,10]).all() and (history[:,:4] <= [40,99,45,45]).all()):
        raise ValueError('outside synthetic input domain')
    # Interrupted virtual pulses must retain their executed duration. The model
    # interpolates inside its synthetic 0..6s action domain; this is not field validation.
    if not ((history[:,4] >= 0).all() and (history[:,4] <= 6).all()):
        raise ValueError('invalid simulated pulse history')
    lo, hi = request['humidity_band']; tlo, thi = request['temperature_band']
    if not 40 <= lo < hi <= 90 or hi-lo < 5 or not 20 <= tlo < thi <= 35:
        raise ValueError('invalid simulation target')
    cfg = settings()
    training = json.loads((ROOT/'training_report.json').read_text(encoding='utf-8'))
    model_hash = hashlib.sha256((ROOT/'model_3sensors.npz').read_bytes()).hexdigest()
    if model_hash != training['models'][0]['weights_sha256']:
        raise RuntimeError('model checksum mismatch')
    model = loaded_model(model_hash)
    nonzero = np.flatnonzero(history[:,4])
    since_pulse = HISTORY-int(nonzero[-1]) if len(nonzero) else HISTORY
    profile = {'humidity_band':[lo,hi], 'temperature_band':[tlo,thi]}
    started = time.monotonic()
    selected = None
    if schema == 2:
        selected, forecast, reason = choose_request_plan(model,history,profile,cfg,since_pulse,
                                                       water_ok=request['water_ok'],leak=request['leak'])
        pulse = selected['expected_virtual_run_s'][0]
    else:
        pulse, forecast, reason = choose(model,history,profile,cfg,since_pulse,
                                        water_ok=request['water_ok'],leak=request['leak'])
    if forecast is None: forecast=model.predict(history,np.zeros((1,HORIZON)))[0]
    torch.cuda.synchronize()
    generated = time.time()
    if generated-timestamps[-1] > 90: raise ValueError('sensor history expired during inference')
    response = {'schema_version':schema,'request_id':request['request_id'],
            **{k:request[k] for k in ['site_id','gateway_id','cage_id']},
            'mode':'SIMULATION_ONLY' if request['mode']=='simulation' else 'SHADOW_ONLY','training_source':'SYNTHETIC_ONLY',
            'field_validated':False,'hardware_execution_allowed':False,
            'model_id':'synthetic-mlp-'+model_hash[:12],
            'device':'cuda','gpu':torch.cuda.get_device_name(0),
            'measurement_end_epoch':float(timestamps[-1]),'generated_at_epoch':generated,
            'expires_at_epoch':min(generated+30,float(timestamps[-1])+90),
            'prediction_condition':'selected candidate future mist schedule; replan on next observation',
            'predictions':[{'horizon_minutes':h,**dict(zip(CHANNELS,forecast[h-1].round(4).tolist()))}
                           for h in REPORT_HORIZONS],
            'misting_proposal':{'pulse_seconds':pulse,'decision':reason,
                                'cooldown_minutes':cfg['cooldown_minutes'],
                                'max_pulse_seconds':cfg['max_pulse_seconds']},
            'inference_ms':round((time.monotonic()-started)*1000,3)}
    if schema == 2:
        response.update(timing_mode=TIMING_MODE, timing_profile=TIMING_PROFILE, selected_plan=selected,
                        prediction_condition='selected request schedule mapped to phase-zero fixture RUN; '
                        'ideal WINDOW acknowledgement; replan on next observation; not physical execution')
        response['misting_proposal'].update(request_hold_ms=selected['request_hold_ms'][0],
                                           expected_virtual_run_s=pulse)
    return response


if __name__=='__main__':
    torch.set_num_threads(2)
    serve = sys.argv[1:] == ['--serve']
    while True:
        raw = sys.stdin.buffer.readline(65537) if serve else sys.stdin.buffer.read(65537)
        if serve and not raw:
            break
        try:
            if len(raw)>65536: raise ValueError('request too large')
            print(json.dumps(predict(json.loads(raw)),allow_nan=False),flush=True)
        except (ValueError,KeyError,TypeError):
            print(json.dumps({'error':'invalid_prediction_input'}),flush=True)
            if not serve or len(raw)>65536:
                raise SystemExit(2)
        except Exception:
            print(json.dumps({'error':'prediction_unavailable'}),flush=True)
            raise SystemExit(3)
        if not serve:
            break
