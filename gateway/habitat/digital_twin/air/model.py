"""Streaming air estimate imported from HabitatOS BB6 Air Live R13.

shortcut: flow and boundary conditions remain the R11 assumptions; replace them
with measured airflow and boundary histories when those measurements exist.
"""
import json
import math
from pathlib import Path
import re
import numpy as np

DIMENSIONS = np.array([.2, .2, .3])
CHANNELS = ('T2', 'T3', 'T1')


def load_config(path):
    def invalid(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    cfg = json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=invalid)
    if not isinstance(cfg, dict):
        raise ValueError('Air config must be an object')
    if not isinstance(cfg.get('cage_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', cfg['cage_id']):
        raise ValueError('Invalid cage_id')
    if cfg.get('dimensions_m') != [.2, .2, .3]:
        raise ValueError('This model is configured for 20 x 20 x 30 cm only')
    if cfg.get('payload_temperature_unit') != 'degC':
        raise ValueError('Existing BB6 T1/T2/T3 payload contract must be degC')
    limits = cfg.get('temperature_limits_c')
    if not isinstance(limits, list) or len(limits) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in limits):
        raise ValueError('Finite temperature_limits_c pair required')
    if not -55 <= limits[0] < limits[1] <= 125:
        raise ValueError('Temperature limits must lie inside -55..125 degC')
    stale = cfg.get('stale_after_s')
    if type(stale) not in (int, float) or not math.isfinite(stale) or not 1 <= stale <= 300:
        raise ValueError('stale_after_s must be 1..300 seconds')
    positions = []
    if not isinstance(cfg.get('sensors'), dict):
        raise ValueError('sensors must be an object')
    for key in ('T1', 'T2', 'T3'):
        sensor = cfg.get('sensors', {}).get(key)
        if not isinstance(sensor, dict) or not isinstance(sensor.get('label'), str) or not 1 <= len(sensor['label']) <= 80:
            raise ValueError('Three named sensor configurations required')
        xyz = sensor.get('xyz_m')
        if not isinstance(xyz, list) or len(xyz) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in xyz):
            raise ValueError('Finite sensor xyz_m required')
        if (np.asarray(xyz) < 0).any() or (np.asarray(xyz) > DIMENSIONS).any():
            raise ValueError('Sensor is outside enclosure')
        positions.append(tuple(xyz))
    if len(set(positions)) != 3:
        raise ValueError('Sensor positions must be distinct')
    return cfg


def geometry(h):
    axes = [(np.arange(round(length/h))+.5)*h for length in DIMENSIONS]
    zz, yy, xx = np.meshgrid(axes[2], axes[1], axes[0], indexing='ij')
    return axes, np.stack([xx, yy, zz], axis=-1).reshape(-1, 3)


def weights(points, sensors):
    distance2 = ((points[:, None, :] - sensors[None, :, :]) ** 2).sum(-1)
    result = 1 / np.maximum(distance2, 1e-20)
    exact = distance2 < 1e-20
    selected = exact.any(axis=1)
    result[selected] = exact[selected]
    return (result / result.sum(axis=1, keepdims=True)).astype(np.float32)


def sampler(points, h):
    n = np.rint(DIMENSIONS/h).astype(int)
    c = np.clip(points/h-.5, 0, n-1)
    lo = np.floor(c).astype(int)
    hi = np.minimum(lo+1, n-1)
    f = c-lo
    indices, factors = [], []
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                s = np.array([dx, dy, dz])
                p = np.where(s, hi, lo)
                indices.append(p[:, 0]+n[0]*(p[:, 1]+n[1]*p[:, 2]))
                factors.append(np.where(s, f, 1-f).prod(axis=1))
    return np.array(indices), np.array(factors)


def sample(field, lookup):
    indices, factors = lookup
    flat = np.asarray(field).reshape(*field.shape[:-3], -1)
    return np.sum(flat[..., indices]*factors, axis=-2)


def operator(h=.02):
    axes, _ = geometry(h)
    nx, ny, nz = map(len, axes)
    shape = (nz, ny, nx)
    x, y, z = [np.arange(n+1)*h for n in (nx, ny, nz)]
    pxz = .004*.3/np.pi*np.sin(np.pi*z[:, None]/.3)*np.sin(np.pi*x[None, :]/.2)
    pyz = .25*.004*.3/np.pi*np.sin(np.pi*z[:, None]/.3)*np.sin(np.pi*y[None, :]/.2)
    ux = np.broadcast_to((-np.diff(pxz, axis=0)/h)[:, None, :], (nz, ny, nx+1)).copy()
    uy = np.broadcast_to((-np.diff(pyz, axis=0)/h)[:, :, None], (nz, ny+1, nx)).copy()
    uz = np.broadcast_to((np.diff(pxz, axis=1)/h)[:, None, :], (nz+1, ny, nx)).copy()
    uz += np.broadcast_to((np.diff(pyz, axis=1)/h)[:, :, None], (nz+1, ny, nx))
    ux[:, :, [0, -1]] = 0
    uy[:, [0, -1], :] = 0
    uz[[0, -1], :, :] = 0
    loss = np.zeros(shape)
    a = 1.5/1200/h
    loss[:, :, [0, -1]] += a
    loss[:, [0, -1], :] += a
    loss[[0, -1], :, :] += a
    div = np.diff(ux, axis=2)/h+np.diff(uy, axis=1)/h+np.diff(uz, axis=0)/h
    outgoing = (np.maximum(ux[:, :, 1:], 0)+np.maximum(-ux[:, :, :-1], 0)
        + np.maximum(uy[:, 1:, :], 0)+np.maximum(-uy[:, :-1, :], 0)
        + np.maximum(uz[1:, :, :], 0)+np.maximum(-uz[:-1, :, :], 0))/h
    assert np.max(abs(div)) < 1e-12
    assert .2*(outgoing+6*2.2e-5/h**2+loss).max() < 1
    return dict(h=h, shape=shape, velocity=(ux, uy, uz), loss=loss, alpha=2.2e-5, ambient=25., dt=.2)


def step(t, op):
    h, alpha = op['h'], op['alpha']
    rhs = np.zeros_like(t)
    for axis, v in zip((-1, -2, -3), op['velocity']):
        left = [slice(None)]*t.ndim
        right = left.copy()
        left[axis], right[axis] = slice(None, -1), slice(1, None)
        vi = [slice(None)]*3
        vi[axis] = slice(1, -1)
        velocity = v[tuple(vi)]
        l, r = t[tuple(left)], t[tuple(right)]
        flux = velocity*np.where(velocity >= 0, l, r)-alpha*(r-l)/h
        rhs[tuple(left)] -= flux/h
        rhs[tuple(right)] += flux/h
    rhs -= op['loss']*(t-op['ambient'])
    return t+op['dt']*rhs


class AirModel:
    def __init__(self, cfg):
        sensors = np.asarray([cfg['sensors'][key]['xyz_m'] for key in CHANNELS], float)
        axes, p = geometry(.02)
        _, q = geometry(.01)
        self.shape = tuple(reversed([len(a) for a in axes]))
        self.lookup, self.query = sampler(sensors, .02), sampler(q, .02)
        self.coarse_weights, self.fine_weights = weights(p, sensors), weights(q, sensors)
        kernel = np.exp(-((p[:, None, :]-sensors[None, :, :])**2).sum(-1)/(2*.06**2))
        hk = sample(kernel.T.reshape(3, *self.shape), self.lookup).T
        if np.linalg.cond(hk+.05*np.eye(3)) >= 100:
            raise ValueError('Sensor arrangement is numerically ill-conditioned')
        self.correction = kernel @ np.linalg.inv(hk+.05*np.eye(3))
        self.op = operator()
        self.temp = self.last_stamp = self.last_mean = None
        self.gap_resets = 0
        self.gap_reset_after_s = cfg['stale_after_s']

    def update(self, readings, stamp):
        measured = np.asarray([readings[key] for key in CHANNELS], float)
        if measured.shape != (3,) or not np.isfinite(measured).all():
            raise ValueError('Finite temperature triplet required')
        elapsed = None if self.last_stamp is None else (stamp-self.last_stamp).total_seconds()
        if elapsed is not None and elapsed <= 0:
            raise ValueError('Temperature timestamps must strictly increase')
        if self.temp is None or elapsed > self.gap_reset_after_s:
            self.temp = (self.coarse_weights @ measured).reshape(self.shape).astype(float)
            if elapsed is not None:
                self.gap_resets += 1
        else:
            self.op['ambient'] = self.last_mean
            steps = max(1, int(np.ceil(elapsed/.2)))
            self.op['dt'] = elapsed/steps
            for _ in range(steps):
                self.temp = step(self.temp, self.op)
        innovation = measured-sample(self.temp, self.lookup)
        self.temp += .35*(self.correction @ innovation).reshape(self.shape)
        self.last_stamp, self.last_mean = stamp, float(np.asarray([readings[k] for k in ('T1', 'T2', 'T3')]).mean())
        improved = sample(self.temp, self.query).reshape(30, 20, 20).astype(np.float32)
        existing = (self.fine_weights @ measured).reshape(30, 20, 20).astype(np.float32)
        if not np.isfinite(improved).all():
            raise ValueError('Model produced a nonfinite field')
        return improved, existing
