"""Synthetic-only environment learning and receding-horizon misting experiment.

GPU: python predictive_misting.py --train --device cuda
Any PC: python predictive_misting.py --evaluate --check
No network, GPIO or production HabitatOS writes. NumPy inference uses exported
weights from an actually trained PyTorch MLP, never the plant's hidden state.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np

SOURCE = Path(__file__).resolve().parent
# The standalone CUDA worker runs from this directory with Python 3.10.
sys.path.insert(0, str(SOURCE.parents[1]))
from habitat.control.r15_timing import REQUEST_CANDIDATES_MS, request_timing

ROOT = Path(os.environ.get('HABITAT_ENV_MODEL_DIR', SOURCE.parents[1] / 'var/models/environment_sim')).expanduser().resolve()
HISTORY, HORIZON = 30, 60  # one-minute samples
REPORT_HORIZONS = [5, 10, 30, 60]
CENTER = np.array([26., 65., 29., 25.])
SCALE = np.array([5., 25., 6., 5.])
DELTA = np.array([2., 12., 3., 2.])
CHANNELS = ['air_C', 'humidity_pct', 'surface_hot_C', 'surface_cool_C']


def settings():
    cfg = json.loads((SOURCE / 'simulation_config.json').read_text(encoding='utf-8'))
    validate_timing(cfg)
    return cfg


def validate_timing(cfg):
    # This standalone GPU worker also enforces the Pi's SAFE R15 3s ceiling.
    limit = cfg['max_pulse_seconds']
    values = [limit, cfg['baseline_pulse_seconds'], *cfg['candidate_pulse_seconds']]
    if (not cfg['candidate_pulse_seconds'] or any(type(v) not in (int, float) or not math.isfinite(v)
            or not 0 < v <= limit <= 3 for v in values)):
        raise ValueError('SAFE R15 RUN candidates must be positive and at most 3 seconds')


class Plant:
    """Uncalibrated first-order test chamber; coefficients are assumptions.

    ponytail: lumped air RH and two surfaces, not CFD or a biological model.
    Calibrate against empty-chamber measurements before using it for design.
    """
    def __init__(self, seed, minutes, cfg, initial_rh=None):
        rng = np.random.default_rng(seed)
        self.cfg = cfg
        phase = rng.uniform(0, 2*np.pi)
        t = np.arange(minutes + HISTORY + HORIZON + 2)
        # Independent of actions: each controller receives identical disturbances.
        self.room_t = 25 + rng.uniform(-1, 1) + 1.8*np.sin(t/100 + phase)
        self.room_h = rng.uniform(32, 46) + 7*np.sin(t/73 + phase)
        self.light = 2.5 + 2*np.sin(t/120 + phase + .8)
        self.noise = rng.normal(size=(len(t), 4)) * [0.04, .3, .06, .06]
        self.process = rng.normal(size=(len(t), 4)) * [.015, .05, .025, .02]
        self.exchange = cfg['air_exchange_per_min'] * rng.uniform(.8, 1.2)
        self.gain = cfg['mist_rh_gain_per_second'] * rng.uniform(.85, 1.15)
        self.y = np.array([self.room_t[0], initial_rh if initial_rh is not None
                           else rng.uniform(40, 90), self.room_t[0]+3, self.room_t[0]-1])
        self.wet, self.t = 0., 0

    def observe(self):
        return self.y + self.noise[self.t]

    def step(self, pulse):
        assert 0 <= pulse <= self.cfg['max_pulse_seconds']
        self.wet += pulse * self.gain
        evaporation = self.wet * self.cfg['evaporation_fraction_per_min']
        self.wet -= evaporation
        air, rh, hot, cool = self.y
        new_air = air + .065*(self.room_t[self.t]-air) + .018*(hot-air) - .055*evaporation
        new_hot = hot + .09*(self.room_t[self.t]+self.light[self.t]-hot)
        new_cool = cool + .04*(self.room_t[self.t]-.7-cool) - .035*evaporation
        new_rh = rh + self.exchange*(self.room_h[self.t]-rh) + evaporation - 2*(new_air-air)
        self.y = np.array([new_air, new_rh, new_hot, new_cool]) + self.process[self.t]
        self.y[1] = np.clip(self.y[1], 5, 99)
        self.t += 1
        return self.observe()


def anchor(obs, sensors):
    base = np.array(obs, copy=True)
    if sensors < 3: base[..., 3] = base[..., 0]
    if sensors < 2: base[..., 2] = base[..., 0]
    return base


def features(history, plans, sensors):
    h = np.asarray(history, dtype=np.float32).copy()
    if h.shape != (HISTORY, 5) or not np.isfinite(h).all():
        raise ValueError('30 fresh complete simulated rows required')
    h[:, :4] = (h[:, :4]-CENTER)/SCALE
    if sensors < 3: h[:, 3] = 0
    if sensors < 2: h[:, 2] = 0
    # Keep the original model's feature scale for existing exported weights.
    # A new 3s control ceiling must not silently change the network input scale.
    h[:, 4] /= 6
    p = np.atleast_2d(plans).astype(np.float32)
    if p.shape[1] != HORIZON or not np.isfinite(p).all() or (p < 0).any() or (p > 6).any():
        raise ValueError('invalid candidate pulse plan')
    return np.concatenate([np.broadcast_to(h.ravel(), (len(p), h.size)), p/6], axis=1)


def dataset(seeds, cfg, sensors):
    xs, ys = [], []
    for seed in seeds:
        rng = np.random.default_rng(seed + 40000)
        p = Plant(seed, 480, cfg)
        observed, truth, actions = [p.observe()], [p.y.copy()], []
        last = -100
        for t in range(480):
            pulse = float(rng.choice(cfg['candidate_pulse_seconds'])) if t-last >= cfg['cooldown_minutes'] and rng.random() < .19 else 0.
            if pulse: last = t
            actions.append(pulse)
            observed.append(p.step(pulse)); truth.append(p.y.copy())
        rows = np.column_stack([observed, [0]+actions])  # row t includes action t-1
        for t in range(HISTORY-1, 480-HORIZON, 2):
            xs.append(features(rows[t-HISTORY+1:t+1], actions[t:t+HORIZON], sensors)[0])
            ys.append(((np.array(truth[t+1:t+HORIZON+1])-anchor(observed[t], sensors))/DELTA).ravel())
    return np.asarray(xs, np.float32), np.asarray(ys, np.float32)


def train(device):
    import torch
    from torch import nn
    cfg = settings()
    if device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA requested but unavailable; training was not run')
    ROOT.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    torch.manual_seed(2741)
    details = []
    started = time.monotonic()
    for sensors in [3, 2, 1]:
        x, y = dataset(range(100, 180), cfg, sensors)
        vx, vy = dataset(range(1000, 1012), cfg, sensors)
        x, y, vx, vy = [torch.tensor(v, device=device) for v in [x, y, vx, vy]]
        model = nn.Sequential(nn.Linear(HISTORY*5+HORIZON, 128), nn.Tanh(), nn.Linear(128, 128), nn.Tanh(), nn.Linear(128, HORIZON*4)).to(device)
        opt = torch.optim.Adam(model.parameters(), lr=.002)
        best, best_state, best_epoch = float('inf'), None, None
        for epoch in range(120):
            order = torch.randperm(len(x), device=device)
            model.train()
            for idx in order.split(1024):
                opt.zero_grad(set_to_none=True)
                loss = (model(x[idx])-y[idx]).square().mean()
                loss.backward(); opt.step()
            model.eval()
            with torch.no_grad(): validation = float((model(vx)-vy).square().mean())
            if validation < best:
                best, best_state, best_epoch = validation, copy.deepcopy(model.state_dict()), epoch+1
            if epoch % 30 == 29:
                print(json.dumps({'sensors': sensors, 'epoch': epoch+1, 'validation_mse': validation}), flush=True)
        model.load_state_dict(best_state)
        weights = {}
        for i, layer in enumerate([model[0], model[2], model[4]]):
            weights['w'+str(i)] = layer.weight.detach().cpu().numpy()
            weights['b'+str(i)] = layer.bias.detach().cpu().numpy()
        file = ROOT / f'model_{sensors}sensors.npz'
        np.savez_compressed(file, **weights)
        # Export equivalence, including action-conditioned predictions.
        m = Model(sensors)
        with torch.no_grad(): ref = model(vx[:16]).cpu().numpy()
        assert np.allclose(ref, m.forward(vx[:16].cpu().numpy()), atol=2e-5)
        details.append({'sensors': sensors, 'train_windows': len(x), 'validation_windows': len(vx),
                        'selected_epoch': best_epoch, 'validation_scaled_mse': best,
                        'weights_sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    if device == 'cuda': torch.cuda.synchronize()
    report = {'source': 'SYNTHETIC_ONLY', 'trained_at': datetime.now(timezone.utc).isoformat(),
              'device': device, 'gpu': torch.cuda.get_device_name(0) if device=='cuda' else None,
              'torch': torch.__version__, 'architecture': '210-128-128-240 tanh MLP; 30-min history + 60-min candidate actions',
              'split': {'train_episode_seeds': [100,179], 'validation_episode_seeds': [1000,1011],
                        'test_episode_seeds': [2000,2011], 'closed_loop_seeds': [3000,3005]},
              'future_inputs': 'candidate actions only; no future weather, sensors or hidden plant state',
              'training_pulse_seconds': cfg['candidate_pulse_seconds'], 'action_feature_scale_seconds': 6,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'config_sha256': hashlib.sha256((SOURCE/'simulation_config.json').read_bytes()).hexdigest(),
              'selection': 'minimum validation loss, test set not used for selection',
              'duration_seconds': round(time.monotonic()-started, 2), 'models': details}
    (ROOT/'training_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


class Model:
    def __init__(self, sensors=3):
        self.sensors = sensors
        with np.load(ROOT/f'model_{sensors}sensors.npz', allow_pickle=False) as f:
            self.w = {k: f[k] for k in f.files}

    def forward(self, x):
        for i in range(3):
            x = x @ self.w['w'+str(i)].T + self.w['b'+str(i)]
            if i < 2: x = np.tanh(x)
        return x

    def predict(self, history, plans):
        y = self.forward(features(history, plans, self.sensors)).reshape(-1, HORIZON, 4)
        return y*DELTA + anchor(np.asarray(history)[-1, :4], self.sensors)


def _candidate_plans(cfg, since_pulse, candidates):
    earliest = max(0, int(cfg['cooldown_minutes']-since_pulse))
    plans = [np.zeros(HORIZON)]
    for delay in range(earliest, min(earliest+8, HORIZON), 2):
        for interval in [6,10,15,20,60]:
            for seconds in candidates:
                p = np.zeros(HORIZON); p[delay::interval] = seconds; plans.append(p)
    return np.array(plans)


def _select_plan(model, history, profile, cfg, plans):
    # Every action value passed here is pump RUN seconds, never REQ seconds.
    forecast = model.predict(history, plans)
    lo, hi = profile['humidity_band']
    rh = forecast[:, :, 1]
    band_error = np.maximum(lo-rh, 0) + np.maximum(rh-hi, 0)
    weights = np.exp(-np.arange(HORIZON)/20)
    weights /= weights.sum()
    cost = (band_error**2 + .08*(rh-(lo+hi)/2)**2) @ weights
    temp = forecast[:, :, 0]
    tlo, thi = profile['temperature_band']
    cost += cfg['temperature_penalty']*((np.maximum(tlo-temp, 0)**2 + np.maximum(temp-thi, 0)**2) @ weights)
    cost += cfg['water_cost']*(plans @ weights)
    if not np.isfinite(cost).all(): raise ValueError('non-finite model output')
    best = int(np.argmin(cost))
    return best, forecast[best]


def choose(model, history, profile, cfg, since_pulse, fresh=True, water_ok=True, leak=False):
    """Historical desired_run_ideal comparison; preserve its candidates and math."""
    validate_timing(cfg)
    if not fresh or not water_ok or leak:
        return 0., None, 'interlock'
    plans = _candidate_plans(cfg, since_pulse, cfg['candidate_pulse_seconds'])
    best, forecast = _select_plan(model, history, profile, cfg, plans)
    return float(plans[best, 0]), forecast, 'learned_forecast'


def choose_request_plan(model, history, profile, cfg, since_pulse, fresh=True, water_ok=True, leak=False):
    """Score phase-zero fixture RUN plans, preserving their original REQ plans."""
    validate_timing(cfg)
    empty = {'request_hold_ms': [0] * HORIZON, 'expected_virtual_run_s': [0.0] * HORIZON}
    if not fresh or not water_ok or leak:
        return empty, None, 'interlock'
    candidates = {hold: request_timing(hold)['expected_virtual_run_s'] for hold in REQUEST_CANDIDATES_MS}
    candidates = {hold: run for hold, run in candidates.items() if run <= cfg['max_pulse_seconds']}
    requests = _candidate_plans(cfg, since_pulse, candidates).astype(np.int64)
    plans = np.zeros_like(requests, dtype=float)
    for hold, run in candidates.items():
        plans[requests == hold] = run
    best, forecast = _select_plan(model, history, profile, cfg, plans)
    selected = {'request_hold_ms': requests[best].tolist(),
                'expected_virtual_run_s': plans[best].tolist()}
    return selected, forecast, 'learned_forecast'


def run_case(model, mode, profile, seed, cfg, minutes=360):
    p = Plant(seed, minutes, cfg, initial_rh=profile['humidity_band'][0]+2)
    history = [[*p.observe(), 0.]]
    for _ in range(HISTORY-1): history.append([*p.step(0), 0.])
    last, records = -100, []
    lo, hi = profile['humidity_band']
    for minute in range(minutes):
        obs = np.array(history[-1][:4]); forecast = None
        if mode == 'predictive':
            action, forecast, _ = choose(model, history[-HISTORY:], profile, cfg, minute-last)
        elif mode == 'threshold':
            action = cfg['baseline_pulse_seconds'] if obs[1] < lo and minute-last >= cfg['cooldown_minutes'] else 0.
        elif mode == 'scheduled_proxy':
            action = cfg['baseline_pulse_seconds'] if minute % cfg['scheduled_interval_minutes'] == 0 else 0.
        else: raise ValueError('unknown controller')
        if action: last = minute
        row = {'minute': minute, 'observed': obs.round(4).tolist(), 'truth': p.y.round(4).tolist(),
               'pulse_seconds': action, 'forecast_5': forecast[4].round(4).tolist() if forecast is not None else None,
               'forecast_10': forecast[9].round(4).tolist() if forecast is not None else None,
               'forecast_30': forecast[29].round(4).tolist() if forecast is not None else None,
               'forecast_60': forecast[59].round(4).tolist() if forecast is not None else None}
        records.append(row)
        history.append([*p.step(action), action])
    truths = np.array([r['truth'] for r in records]); rh = truths[:, 1]
    pulses = np.array([r['pulse_seconds'] for r in records])
    err = np.maximum(lo-rh, 0)+np.maximum(rh-hi, 0)
    tlo, thi = profile['temperature_band']
    metrics = {'humidity_out_minutes': int(np.count_nonzero(err)),
               'humidity_band_error_mean_pp': round(float(err.mean()), 4),
               'humidity_target_mae_pp': round(float(np.abs(rh-(lo+hi)/2).mean()), 4),
               'temperature_out_minutes': int(np.count_nonzero((truths[:,0]<tlo)|(truths[:,0]>thi))),
               'pulse_count': int(np.count_nonzero(pulses)), 'pump_on_seconds': float(pulses.sum()),
               'water_ml_assumed': round(float(pulses.sum()*cfg['assumed_nozzle_ml_per_second']), 2),
               'pump_valve_Wh_assumed': round(float(pulses.sum()*cfg['assumed_active_watts']/3600), 4),
               'human_interventions': None}
    return {'mode': mode, 'profile': profile['id'], 'seed': seed, 'minutes': minutes, 'metrics': metrics, 'records': records}


def evaluate():
    cfg = settings()
    prediction = []
    for n in [3,2,1]:
        model = Model(n)
        x, y = dataset(range(2000,2012), cfg, n)
        errors = (model.forward(x)-y).reshape(-1,HORIZON,4)*DELTA
        prediction.append({'sensors': n, 'horizons': {str(h): {
            'mae': dict(zip(CHANNELS, np.abs(errors[:,h-1]).mean(axis=0).round(4).tolist())),
            'rmse': dict(zip(CHANNELS, np.sqrt((errors[:,h-1]**2).mean(axis=0)).round(4).tolist()))}
            for h in REPORT_HORIZONS}, 'windows': len(x)})
        if n==3:
            persistence = (-y).reshape(-1,HORIZON,4)*DELTA
            baseline = {str(h): dict(zip(CHANNELS,np.abs(persistence[:,h-1]).mean(axis=0).round(4).tolist())) for h in REPORT_HORIZONS}
    model = Model(3)
    runs, traces = [], []
    for profile in cfg['profiles']:
        for seed in range(3000,3006):
            for mode in ['scheduled_proxy','threshold','predictive']:
                result = run_case(model, mode, profile, seed, cfg)
                if seed==3000: traces.append(result.copy())
                runs.append({k:v for k,v in result.items() if k!='records'})
    aggregates = []
    for profile in cfg['profiles']:
        for mode in ['scheduled_proxy','threshold','predictive']:
            ms = [r['metrics'] for r in runs if r['profile']==profile['id'] and r['mode']==mode]
            aggregates.append({'profile': profile['id'], 'mode': mode,
                               'metrics_mean': {k: round(float(np.mean([m[k] for m in ms])),4)
                                                for k in ms[0] if ms[0][k] is not None}})
    report = {'source':'SYNTHETIC_ONLY', 'field_validated':False, 'profiles':cfg['profiles'],
              'forecast_test': prediction, 'persistence_mae': baseline, 'closed_loop': aggregates,
              'runs':runs, 'traces':traces, 'minutes_per_run':360, 'repeats':6,
              'baseline_note':'scheduled_proxy is a fixed timer, not a human experiment; no intervention reduction claim',
              'water_energy_note':'uncalibrated nozzle flow and electrical assumptions; not nameplate or measured consumption',
              'thermal_rgb_note':'no synthetic camera or thermal measurements used as real sensor input',
              'shared_pump':'single-cage plant comparison only; shared R15 sequence is exercised by simulate_misting',
              'control_pulse_seconds':cfg['candidate_pulse_seconds'], 'max_run_seconds':cfg['max_pulse_seconds'],
              'action_feature_scale_seconds':6}
    (ROOT/'prediction_results.json').write_text(json.dumps(report, ensure_ascii=False, separators=(',',':')), encoding='utf-8')
    print(json.dumps({'forecast_test':prediction, 'closed_loop':aggregates}, ensure_ascii=True), flush=True)
    return report


def check():
    cfg = settings(); model = Model(3)
    a, b = Plant(55,30,cfg), Plant(55,30,cfg)
    for t in range(10): a.step(0); b.step(cfg['max_pulse_seconds'] if t==0 else 0)
    assert b.y[1] > a.y[1]  # action actually changes environmental state
    h = np.tile([26.,62.,29.,25.,0.], (HISTORY,1))
    plans = np.zeros((2,HORIZON)); plans[1,0]=cfg['max_pulse_seconds']
    out = model.predict(h,plans)
    assert out[1,4,1] > out[0,4,1]+.5  # trained response, not identical fixed curves
    for n in [1,2]:
        changed = h.copy(); changed[:,3]=70
        if n==1: changed[:,2]=70
        assert np.array_equal(features(h,plans,n), features(changed,plans,n))
        assert np.array_equal(anchor(h[-1,:4],n), anchor(changed[-1,:4],n))
    for flags in [{'fresh':False},{'water_ok':False},{'leak':True}]:
        assert choose(model,h,cfg['profiles'][1],cfg,10,**flags)[0]==0
    assert choose(model,h,cfg['profiles'][1],cfg,0)[0]==0
    bad=h.copy();bad[0,1]=np.nan
    try: model.predict(bad,plans)
    except ValueError: pass
    else: raise AssertionError('non-finite input accepted')
    # Episode ranges and trajectories are disjoint; no shuffled overlapping split.
    assert len(set(range(100,180)) & set(range(2000,2012)))==0
    results=json.loads((ROOT/'prediction_results.json').read_text(encoding='utf-8'))
    for trace in results['traces']:
        times=[r['minute'] for r in trace['records'] if r['pulse_seconds']]
        assert all(b-a >= cfg['cooldown_minutes'] for a,b in zip(times,times[1:]))
        assert all(0<=r['pulse_seconds']<=cfg['max_pulse_seconds'] for r in trace['records'])
    report={'status':'PASS','source':'SYNTHETIC_ONLY','checks':['plant action response','learned action response',
            'excluded sensors inaccessible','missing input rejection','leak/water/stale interlocks',
            'cooldown and pulse bounds','disjoint episode seeds','exported model inference'],
            'not_tested':['GPIO','physical pump/valve response','species welfare','Pi/SaaS integration']}
    (ROOT/'prediction_checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train',action='store_true');parser.add_argument('--device',choices=['cpu','cuda'],default='cuda')
    parser.add_argument('--evaluate',action='store_true');parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.train or args.evaluate or args.check: ROOT.mkdir(parents=True, exist_ok=True)
    if args.train: train(args.device)
    if args.evaluate: evaluate()
    if args.check: check()
