"""Local Gateway history contracts; no real broker, database, or SaaS calls."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import signal
import threading
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from apps.air import __main__ as entrypoint
from habitat.digital_twin.air import history
from habitat.digital_twin.air.service import AirState
from habitat.digital_twin.air.telemetry import validate_telemetry
from habitat.saas.air import build_estimate


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
CONFIG = Path('configs/examples/air-viewer.json')
TOKEN = 'isolated-history-test-credential-' + 'x' * 32


def payload(cage, index=0, stamp=None):
    return dict(schema_version=1, data_source='sensor', message_id=str(UUID(int=index + 1)),
                sampled_at=(stamp or NOW - timedelta(hours=1) + timedelta(seconds=index * 5)).isoformat(),
                geometry_revision=cage.geometry_revision, placement_revision=cage.placement_revision,
                readings={key: dict(value=value, quality='valid') for key, value in
                          {'T1': 22.5, 'RH1': 60., 'T2': 22.25, 'T3': 22.125}.items()}, actuators={})


def envelope(raw, cage):
    sample = validate_telemetry(raw, cage, NOW)
    normalized = sample.model_dump(mode='json')
    return dict(event='telemetry', retained=False, fresh_unique=True,
                message_id=str(sample.message_id), sampled_at=normalized['sampled_at'],
                readings=normalized['readings'], payload=normalized)


def restore(settings, state, rows, *, limit=300):
    loader = history.HistoryBootstrap(settings, {settings.cages[0].id: state}, TOKEN,
                                      limit=limit, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))) as client:
        return loader.load(client, settings.cages[0].id)


def test_authenticated_cage_history_is_sorted_and_equal_values_all_restore(settings):
    cage, state = settings.cages[0], AirState(CONFIG)
    rows = [payload(cage, index) for index in (2, 1, 0)]
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url == 'http://127.0.0.1:8000/v1/cages/CAGE-001/telemetry?limit=300'
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert not request.content
        return httpx.Response(200, json=rows)

    loader = history.HistoryBootstrap(settings, {cage.id: state}, TOKEN, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = loader.load(client, cage.id)
    snapshot = state.snapshot(NOW)
    assert result == dict(restored=3, rejected=0, rows=3)
    assert snapshot['history_samples'] == snapshot['accepted_samples'] == 3
    assert snapshot['live_samples'] == 0
    assert snapshot['data_origin'] == 'history'
    assert snapshot['message_id'] == rows[0]['message_id']
    assert datetime.fromisoformat(snapshot['sampled_at']) == datetime.fromisoformat(rows[0]['sampled_at'])
    assert snapshot['received_at_utc'] is None and snapshot['age_seconds'] is None
    assert not snapshot['fresh'] and snapshot['held']
    assert len(snapshot['field']['values_c']) == 12000
    assert [sensor['value_c'] for sensor in snapshot['sensors']] == [22.5, 22.25, 22.125]
    assert build_estimate(settings, cage, state, snapshot) is None
    assert TOKEN not in json.dumps(snapshot) and len(requests) == 1


def test_history_revisions_future_timestamps_and_invalid_readings_are_not_restored(settings):
    cage, state = settings.cages[0], AirState(CONFIG)
    good = payload(cage)
    revision = payload(cage, 1)
    revision['geometry_revision'] += 1
    future = payload(cage, 2, NOW + timedelta(seconds=6))
    invalid = payload(cage, 3)
    invalid['readings']['T2'] = dict(value=None, quality='invalid')
    assert restore(settings, state, [future, invalid, revision, good]) == dict(restored=1, rejected=3, rows=4)
    assert state.snapshot(NOW)['message_id'] == good['message_id']


def test_history_response_cannot_roll_back_a_newer_mqtt_measurement(settings):
    cage, state = settings.cages[0], AirState(CONFIG)
    live = payload(cage, 99, NOW)
    live['readings']['T1']['value'] = 25.
    prior = {}

    def handle(_):
        assert state.ingest(envelope(live, cage), now=NOW)
        prior.update(state.snapshot(NOW))
        return httpx.Response(200, json=[payload(cage, 1), payload(cage, 0)])

    loader = history.HistoryBootstrap(settings, {cage.id: state}, TOKEN, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert loader.load(client, cage.id)['restored'] == 0
    current = state.snapshot(NOW)
    for name in ('field', 'message_id', 'sampled_at', 'data_origin', 'fresh', 'status', 'accepted_samples'):
        assert current[name] == prior[name]


def test_repeated_history_load_is_idempotent_and_does_not_forge_receipt_time(settings):
    state, rows = AirState(CONFIG), [payload(settings.cages[0], index) for index in (1, 0)]
    assert restore(settings, state, rows)['restored'] == 2
    before = state.snapshot(NOW)
    assert restore(settings, state, rows)['restored'] == 0
    current = state.snapshot(NOW)
    for key in ('message_id', 'loaded_at', 'generated_at', 'history_samples', 'live_samples', 'received_at_utc'):
        assert current[key] == before[key]


@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 500])
def test_http_failures_and_redirects_never_follow_or_restore(settings, status):
    state, requests = AirState(CONFIG), []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, text='private-response-must-not-be-logged',
                              headers={'Location': 'https://different.invalid/receive-credential'})

    loader = history.HistoryBootstrap(settings, {settings.cages[0].id: state}, TOKEN, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(history.HistoryFailure, match='^http_' + str(status) + '$'):
            loader.load(client, settings.cages[0].id)
    assert len(requests) == 1
    assert state.snapshot(NOW)['field'] is None


@pytest.mark.parametrize('body,code', [
    (b'<html>invalid response</html>', 'invalid_json'),
    (b'{}', 'invalid_history_list'),
    (b'[{},{}]', 'invalid_history_list'),
    (b'x' * (history.MAX_RESPONSE_BYTES + 1), 'response_too_large'),
])
def test_response_shape_and_size_are_bounded(settings, body, code):
    state = AirState(CONFIG)
    loader = history.HistoryBootstrap(settings, {settings.cages[0].id: state}, TOKEN, limit=1, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
        with pytest.raises(history.HistoryFailure, match='^' + code + '$'):
            loader.load(client, settings.cages[0].id)
    assert state.snapshot(NOW)['field'] is None


@pytest.mark.parametrize('host,result', [('127.0.0.1', '127.0.0.1'), ('localhost', 'localhost'),
                                       ('0.0.0.0', '127.0.0.1'), ('::', '[::1]'), ('::1', '[::1]')])
def test_gateway_listener_maps_only_to_local_origin(settings, host, result):
    changed = settings.model_copy(update={'server': settings.server.model_copy(update={'host': host, 'port': 8123})})
    assert history.local_origin(changed) == 'http://' + result + ':8123'


def test_lan_listener_never_sends_plain_api_credentials(settings):
    changed = settings.model_copy(update={'server': settings.server.model_copy(update={'host': '192.168.1.10'})})
    with pytest.raises(ValueError, match='loopback'):
        history.HistoryBootstrap(changed, {changed.cages[0].id: AirState(CONFIG)}, TOKEN)


@pytest.mark.parametrize('limit', [0, -1, 1001, True, 1.5])
def test_unsafe_history_limit_rejected(settings, limit):
    with pytest.raises(ValueError, match='limit'):
        history.HistoryBootstrap(settings, {settings.cages[0].id: AirState(CONFIG)}, TOKEN, limit=limit)


def test_failed_cage_retries_while_other_cage_completes_and_environment_proxy_is_disabled(settings, tmp_path, monkeypatch, caplog):
    cage = settings.cages[0]
    second = cage.model_copy(update={'id': 'CAGE-002', 'node_id': 'ESP32-002'})
    settings = settings.model_copy(update={'cages': [cage, second]})
    cfg = json.loads(CONFIG.read_text())
    cfg['cage_id'] = second.id
    second_path = tmp_path / 'second.json'
    second_path.write_text(json.dumps(cfg))
    states = {cage.id: AirState(CONFIG), second.id: AirState(second_path)}
    calls, factory_arguments, clock = [], {}, [0.]

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            clock[0] += seconds

    def handle(request):
        name = request.url.path.split('/')[3]
        calls.append(name)
        if name == cage.id and calls.count(name) == 1:
            return httpx.Response(503, text='private_failure_contents')
        return httpx.Response(200, json=[payload(cage if name == cage.id else second)])

    def factory(**kwargs):
        factory_arguments.update(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(history.time, 'monotonic', lambda: clock[0])
    loader = history.HistoryBootstrap(settings, states, TOKEN, now=lambda: NOW, client_factory=factory)
    loader.run(Stop())
    assert calls == [cage.id, second.id, cage.id]
    assert factory_arguments['trust_env'] is False and factory_arguments['follow_redirects'] is False
    assert factory_arguments['timeout'].read <= history.REQUEST_TIMEOUT_S
    assert all(state.snapshot(NOW)['history_samples'] == 1 for state in states.values())
    assert TOKEN not in caplog.text and 'private_failure_contents' not in caplog.text


def test_stop_cancels_before_restoring_rows(settings):
    state, stop = AirState(CONFIG), threading.Event()

    def handle(_):
        stop.set()
        return httpx.Response(200, json=[payload(settings.cages[0])])

    loader = history.HistoryBootstrap(settings, {settings.cages[0].id: state}, TOKEN, now=lambda: NOW)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert loader.load(client, settings.cages[0].id, stop) is None
    assert state.snapshot(NOW)['field'] is None


def test_missing_history_credential_disables_only_history(settings, monkeypatch, caplog):
    monkeypatch.delenv('HABITAT_API_TOKEN', raising=False)
    configured = settings.model_copy(update={'transport': 'mqtt'})
    assert entrypoint.history_bootstrap(configured, {settings.cages[0].id: AirState(CONFIG)}, 300) is None
    assert 'MQTT remains active' in caplog.text
    assert entrypoint.history_bootstrap(configured, {}, 0) is None


def test_history_worker_does_not_block_mqtt_start_or_shutdown(settings, monkeypatch):
    started, history_started, closed = threading.Event(), threading.Event(), threading.Event()
    handlers = {}
    errors = []
    configured = settings.model_copy(update={'transport': 'mqtt'})

    class Subscriber:
        def __init__(self, *args):
            pass

        def start(self):
            started.set()

        def close(self):
            closed.set()

    class Loader:
        def run(self, stop):
            history_started.set()
            stop.wait()

    class Uploader:
        def __init__(self, *args):
            pass

        async def run(self, stop):
            while not stop.is_set():
                await asyncio.sleep(.01)

    server = SimpleNamespace(server_address=('127.0.0.1', 8765), shutdown=lambda: None, server_close=lambda: None)
    monkeypatch.setattr(entrypoint, 'load_settings', lambda _: configured)
    monkeypatch.setattr(entrypoint, 'AirSubscriber', Subscriber)
    monkeypatch.setattr(entrypoint, 'history_bootstrap', lambda *args: Loader())
    monkeypatch.setattr(entrypoint, 'AirUploader', Uploader)
    monkeypatch.setattr(entrypoint, 'start_server', lambda *args, **kwargs: server)
    monkeypatch.setattr(entrypoint.signal, 'signal', lambda number, handler: handlers.setdefault(number, handler))
    monkeypatch.setattr('sys.argv', ['air', '--config', 'unused', '--air-config', str(CONFIG)])

    def run():
        try:
            entrypoint.main()
        except Exception as error:
            errors.append(type(error).__name__)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert started.wait(3) and history_started.wait(3)
        assert worker.is_alive()
    finally:
        if signal.SIGTERM in handlers:
            handlers[signal.SIGTERM](None, None)
        worker.join(timeout=5)
    assert not worker.is_alive() and closed.is_set() and not errors
