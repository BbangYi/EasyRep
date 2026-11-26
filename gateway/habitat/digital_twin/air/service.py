"""Receive-only air-view state and a local HTTP view; never publishes MQTT."""
from collections.abc import Mapping
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
import numpy as np
from habitat.common.models import aware_timestamp, utcnow
from habitat.saas.air_contract import MODEL_ID, MODEL_VERSION

from .model import AirModel, load_config

ASSUMPTIONS = [
    '점은 센서 실측, 부피 색은 추정 온도입니다.',
    '20 × 20 × 30 cm 사육장과 센서 좌표는 설정값이며, 기본 좌표는 설치 전 가정입니다.',
    '0.004 m/s 순환과 벽 열교환은 가정이며, 실제 공기 흐름 측정값은 아닙니다.',
    '경계 온도는 직전 센서 3개 평균이며 국소 바닥 열원은 사용하지 않습니다.',
    '단위가 없는 기존 BB6 온도 payload는 설정의 degC 계약을 따릅니다.',
]


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def parse_stamp(value):
    if not isinstance(value, str):
        raise ValueError('sampled_at_must_be_string')
    try:
        return aware_timestamp(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except ValueError:
        raise ValueError('sampled_at_must_have_valid_timezone') from None


def iso(value):
    return aware_timestamp(value).isoformat(timespec='milliseconds')


class AirState:
    """Validate Observer envelopes and hold the last accepted temperature field.

    MQTT transport and the canonical telemetry contract belong to the gateway
    adapter. This state never writes telemetry, publishes MQTT, or controls devices.
    """

    def __init__(self, config, source_mode='live', max_sample_age=None, max_future_skew=5.):
        if source_mode not in ('live', 'replay'):
            raise ValueError('Unknown source mode')
        self.cfg = load_config(config)
        self.source_mode = source_mode
        if max_sample_age is None:
            max_sample_age = self.cfg['stale_after_s']
        if not finite_number(max_sample_age) or max_sample_age <= 0:
            raise ValueError('max_sample_age_must_be_positive_finite')
        if not finite_number(max_future_skew) or max_future_skew < 0:
            raise ValueError('max_future_skew_must_be_nonnegative_finite')
        self.max_sample_age, self.max_future_skew = max_sample_age, max_future_skew
        self.model = AirModel(self.cfg)
        self.lock = threading.Lock()
        self.status, self.reason = 'waiting', 'waiting_for_three_valid_temperatures'
        self.accepted = self.rejected = 0
        self.history_samples = self.live_samples = 0
        self.last_rejection = self.stamp = self.received = self.received_mono = None
        self.generated = self.loaded = self.data_origin = self.latest_payload = None
        self.field = self.baseline = self.color_range = None
        self.values = {key: None for key in ('T1', 'T2', 'T3')}
        self.latest_id = None

    def _reject(self, reason, *, mark=True):
        self.rejected += 1
        self.last_rejection = reason
        if mark:
            self.status, self.reason = 'held', reason

    def mark(self, status, reason):
        with self.lock:
            self.status, self.reason = status, reason

    def ingest(self, event, now=None, monotonic=None):
        return self._ingest(event, now, monotonic, history=False)

    def restore(self, event, now=None):
        """Restore a stored measurement without claiming a new sensor receipt."""
        return self._ingest(event, now, history=True)

    def _ingest(self, event, now=None, monotonic=None, *, history=False):
        now = aware_timestamp(now or utcnow())
        monotonic = time.monotonic() if monotonic is None else monotonic
        with self.lock:
            if not isinstance(event, dict):
                self._reject('invalid_observer_envelope', mark=not history or self.field is None)
                return False
            kind = event.get('event')
            if history and kind != 'telemetry':
                return False
            if kind == 'status':
                if event.get('retained'):
                    self._reject('retained_status_ignored')
                elif event.get('online') is False:
                    self.status, self.reason = 'offline', 'bb6_status_offline'
                elif event.get('online') is True:
                    # Status alone must not make an old temperature volume fresh.
                    self.status, self.reason = 'held', 'online_waiting_for_new_temperature'
                else:
                    self._reject('invalid_status')
                return False
            if kind in ('subscriber_process_exited', 'subscriber_restart_scheduled', 'recorder_error', 'observation_finished'):
                self.status, self.reason = 'offline', kind
                return False
            if kind in ('wrapper_error', 'payload_error', 'non_json_subscriber_output', 'oversized_output_line'):
                self._reject(kind)
                return False
            if kind != 'telemetry':
                return False
            if event.get('retained') or event.get('fresh_unique') is not True:
                issues = event.get('validation_issues', [])
                detail = ','.join(x for x in issues if isinstance(x, str)) if isinstance(issues, list) else ''
                self._reject('retained_telemetry' if event.get('retained') else detail or 'not_fresh_unique',
                             mark=not history or self.field is None)
                return False
            try:
                if not isinstance(event.get('message_id'), str) or not event['message_id']:
                    raise ValueError('missing_message_id')
                stamp = parse_stamp(event.get('sampled_at'))
                # A slow history fetch must never roll back or grey a newer live
                # result. Re-reading already restored rows is harmless as well.
                if history and self.stamp is not None and (
                        stamp <= self.stamp or event['message_id'] == self.latest_id):
                    return False
                age = (now-stamp).total_seconds()
                if (history or self.source_mode == 'live') and age < -self.max_future_skew:
                    raise ValueError('stale_or_clock_mismatch')
                readings = event.get('readings', {})
                payload = event.get('payload', {})
                if not isinstance(payload, dict):
                    raise ValueError('invalid_observer_payload')
                original = payload.get('readings', {})
                if not isinstance(readings, dict) or not isinstance(original, dict):
                    raise ValueError('missing_temperature_readings')
                values = {}
                low, high = self.cfg['temperature_limits_c']
                for key in ('T1', 'T2', 'T3'):
                    reading = readings.get(key, {})
                    if not isinstance(reading, dict):
                        raise ValueError(key+':missing_invalid_or_nonfinite')
                    value = reading.get('value')
                    if reading.get('quality') != 'valid' or not finite_number(value):
                        raise ValueError(key+':missing_invalid_or_nonfinite')
                    if not low <= value <= high:
                        raise ValueError(key+':outside_configured_temperature_range')
                    raw = original.get(key, {})
                    if not isinstance(raw, dict) or raw.get('unit', self.cfg['payload_temperature_unit']) != 'degC':
                        raise ValueError(key+':unit_not_degC')
                    if raw.get('value') != value or raw.get('quality') != reading.get('quality'):
                        raise ValueError(key+':payload_reading_mismatch')
                    values[key] = float(value)
                signature = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
                if self.stamp is not None and stamp <= self.stamp:
                    if (not history and self.source_mode == 'live' and self.data_origin == 'history'
                            and stamp == self.stamp and event['message_id'] == self.latest_id
                            and signature == self.latest_payload and values == self.values):
                        # The same immutable record can arrive from history and
                        # MQTT concurrently. Only provenance/receipt changes;
                        # the model and distinct-measurement total stay fixed.
                        self.received, self.received_mono = now, monotonic
                        self.data_origin = 'mqtt'
                        self.live_samples += 1
                        self.status, self.reason = 'live', 'accepted_temperature_triplet'
                        return True
                    raise ValueError('non_increasing_source_timestamp')
                if self.latest_id is not None and event['message_id'] == self.latest_id:
                    raise ValueError('duplicate_message_id')
                field, baseline = self.model.update(values, stamp)
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
                self._reject(str(exc), mark=not history or self.field is None)
                return False
            self.stamp, self.generated = stamp, now
            self.received = None if history else now
            self.received_mono = None if history else monotonic
            self.data_origin = 'history' if history else 'mqtt' if self.source_mode == 'live' else 'replay'
            self.latest_payload = signature
            if history:
                self.loaded = now
                self.history_samples += 1
            elif self.source_mode == 'live':
                self.live_samples += 1
            self.values, self.latest_id = values, event.get('message_id')
            self.field = np.round(field.astype(float), 4).ravel().tolist()
            self.baseline = np.round(baseline.astype(float), 4).ravel().tolist()
            low = math.floor(min(field.min(), baseline.min(), *values.values())*2)/2
            high = math.ceil(max(field.max(), baseline.max(), *values.values())*2)/2
            if high-low < 1:
                low -= .5
                high += .5
            self.color_range = [low, high] if self.color_range is None else [min(low, self.color_range[0]), max(high, self.color_range[1])]
            self.accepted += 1
            if not history:
                self.status, self.reason = self.source_mode, 'accepted_temperature_triplet'
            elif self.status != 'offline':
                # Stored measurements do not establish current connectivity.
                # Preserve an offline signal received before or during replay.
                self.status, self.reason = 'history', 'stored_measurement_restored'
            return True

    def snapshot(self, now=None, monotonic=None):
        now = now or utcnow()
        monotonic = time.monotonic() if monotonic is None else monotonic
        with self.lock:
            age = None if self.received_mono is None else max(0., monotonic-self.received_mono)
            source_age = None if self.stamp is None else (now-self.stamp).total_seconds()
            status, reason = self.status, self.reason
            expired = age is not None and age > self.cfg['stale_after_s']
            if self.source_mode == 'live' and source_age is not None:
                expired = expired or source_age > self.max_sample_age or source_age < -self.max_future_skew
            if self.data_origin == 'history':
                if (status in ('waiting', 'history', 'live', 'replay') or reason in (
                        'online_waiting_for_new_temperature', 'mqtt_connected_waiting_for_telemetry')):
                    status, reason = 'history', 'stored_measurement_restored'
            elif expired and status not in ('offline', 'replay_complete'):
                status, reason = 'stale', 'temperature_update_timeout'
            fresh = (self.field is not None and self.data_origin != 'history'
                     and status in ('live', 'replay') and not expired)
            return dict(schema_version=1, source_mode=self.source_mode, cage_id=self.cfg['cage_id'],
                model_id=MODEL_ID, model_version=MODEL_VERSION,
                message_id=self.latest_id,
                status=status, status_reason=reason, fresh=fresh, held=self.field is not None and not fresh,
                received_at_utc=None if self.received is None else iso(self.received),
                generated_at=None if self.generated is None else iso(self.generated),
                loaded_at=None if self.loaded is None else iso(self.loaded),
                data_origin=self.data_origin,
                sampled_at=None if self.stamp is None else iso(self.stamp),
                age_seconds=None if age is None else round(age, 3),
                source_age_seconds=None if source_age is None else round(source_age, 3),
                stale_after_s=self.cfg['stale_after_s'],
                accepted_samples=self.accepted, rejected_samples=self.rejected,
                history_samples=self.history_samples, live_samples=self.live_samples,
                last_rejection=self.last_rejection, gap_resets=self.model.gap_resets,
                dimensions_m=self.cfg['dimensions_m'],
                grid=dict(shape_zyx=[30, 20, 20], spacing_m=.01, origin_m=[.005, .005, .005], order='zyx'),
                sensors=[dict(id=key, label=self.cfg['sensors'][key]['label'], xyz_m=self.cfg['sensors'][key]['xyz_m'],
                    value_c=self.values[key], sampled_at=None if self.stamp is None else iso(self.stamp)) for key in ('T1', 'T2', 'T3')],
                field=None if self.field is None else dict(method='flow_sensor', values_c=self.field),
                baseline=None if self.baseline is None else dict(method='idw', values_c=self.baseline),
                color_range_c=self.color_range, field_precision_c=.0001, assumptions=ASSUMPTIONS)


def start_server(state, bind='127.0.0.1', port=8765, web_root=None):
    ipaddress.ip_address(bind)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid HTTP port')
    states = dict(state) if isinstance(state, Mapping) else {state.cfg['cage_id']: state}
    if not states or any(not isinstance(key, str) or not key or
                         not isinstance(value, AirState) or value.cfg['cage_id'] != key
                         for key, value in states.items()):
        raise ValueError('Air state registry must contain matching cage IDs')
    default_cage = next(iter(states))
    root = (Path(web_root) if web_root else Path(__file__).resolve().parent/'web').resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlsplit(self.path)
            route = unquote(target.path)
            if '\x00' in route:
                self.send_error(404)
                return
            if route == '/api/air':
                cages = parse_qs(target.query, keep_blank_values=True).get('cage_id', [default_cage])
                if len(cages) != 1 or cages[0] not in states:
                    self.send_error(404, 'Unknown cage')
                    return
                body = json.dumps(states[cages[0]].snapshot(), ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif route == '/api/cages':
                body = json.dumps(dict(cage_ids=list(states), default_cage_id=default_cage),
                                  ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            else:
                path = (root/('index.html' if route == '/' else route.lstrip('/'))).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.suffix not in ('.html', '.js', '.css', '.svg', '.png', '.ico'):
                    self.send_error(404)
                    return
                body = path.read_bytes()
                content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                if path.suffix in ('.html', '.js', '.css', '.svg'):
                    content_type += '; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name='air-view-http', daemon=True)
    thread.start()
    return server
