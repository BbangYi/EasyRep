"""Isolated MQTT-fixture → real air model → uploader → scoped reference view.

Telemetry is synthetic contract-test input marked as sensor data solely to exercise
the sensor-only adapter. No physical broker, sensors, SaaS, or hardware are used.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import httpx
import pytest

from habitat.digital_twin.air import service as air_service
from habitat.digital_twin.air.mqtt import AirSubscriber
from habitat.digital_twin.air.service import AirState
from habitat.saas import air_receiver
from habitat.saas.air import AirUploader, AirUploadConfig, build_estimate
from habitat_gateway.config import MQTTConfig
from habitat_gateway.models import Telemetry
from habitat_gateway.saas_reference import Registration, create_receiver
from habitat_gateway.store import Store
from habitat_gateway.transport import node_topic


NOW = datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)
CONFIG = Path(__file__).resolve().parents[2] / 'configs/examples/air-viewer.json'
PI_TOKEN = 'integration-fixture-pi-credential-' + 'p' * 32
VIEW_TOKENS = ['integration-fixture-viewer-' + key * 32 for key in ('a', 'b')]


def sensor_fixture(cage, sampled_at, temperatures):
    """Produce canonical input in memory; never send these fixtures to a broker."""
    return Telemetry(
        message_id=uuid4(), sampled_at=sampled_at, data_source='sensor',
        geometry_revision=cage.geometry_revision, placement_revision=cage.placement_revision,
        readings={**{key: dict(value=value, quality='valid')
                     for key, value in zip(('T1', 'T2', 'T3'), temperatures)},
                  'RH1': dict(value=53.25, quality='valid')}, actuators={},
    )


def deliver(pipeline, cage, temperatures):
    sample = sensor_fixture(cage, pipeline.clock[0], temperatures)
    message = SimpleNamespace(topic=node_topic(pipeline.settings, cage, 'telemetry'),
                              payload=sample.model_dump_json().encode(), retain=False)
    # Every observer sees the same delivery; only the matching node may ingest it.
    for subscriber in pipeline.subscribers:
        subscriber._message(subscriber.client, None, message)
    return sample


def assert_gateway_untouched(pipeline):
    assert '\n'.join(pipeline.store.db.iterdump()) == pipeline.original_gateway_dump
    for client in pipeline.clients:
        client.publish.assert_not_called()
        client.will_set.assert_not_called()
    for table in ('edge_events', 'edge_gateways'):
        assert pipeline.receiver.state.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


@pytest.fixture
def pipeline(settings, tmp_path, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(air_service, 'utcnow', lambda: clock[0])
    monkeypatch.setattr(air_receiver, 'utcnow', lambda: clock[0])
    monkeypatch.setenv('AIR_PIPELINE_TEST_MQTT_PASSWORD', 'isolated-test-password')
    first = settings.cages[0].model_copy(deep=True)
    second = first.model_copy(deep=True, update={'id': 'CAGE-002', 'node_id': 'ESP32-002'})
    settings = settings.model_copy(update={
        'cages': [first, second], 'transport': 'mqtt', 'database': str(tmp_path / 'gateway.sqlite3'),
        'mqtt': MQTTConfig(host='127.0.0.1', port=8883, username='isolated-test-reader',
                           password_env='AIR_PIPELINE_TEST_MQTT_PASSWORD', tls_ca='/test/existing-ca.pem'),
    })
    states, clients, subscribers = {}, [], []
    for cage in settings.cages:
        cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
        cfg['cage_id'] = cage.id
        config_path = tmp_path / f'{cage.id}.json'
        config_path.write_text(json.dumps(cfg), encoding='utf-8')
        states[cage.id] = AirState(config_path)
        client = Mock()
        subscriber = AirSubscriber(settings, cage, states[cage.id], client=client, now=lambda: clock[0])
        subscriber.start()
        subscriber._connect(client, None, None, SimpleNamespace(is_failure=False))
        clients.append(client)
        subscribers.append(subscriber)
    enclosures = {cage.id: UUID(int=index + 101) for index, cage in enumerate(settings.cages)}
    pi = Registration(site_id=settings.site_id, gateway_id=settings.gateway_id,
        cage_ids=list(states), token_env='PI', air_cages={
            cage.id: dict(node_id=cage.node_id, enclosure_id=enclosures[cage.id],
                          geometry_revision=cage.geometry_revision, placement_revision=cage.placement_revision)
            for cage in settings.cages})
    viewers = [Registration(site_id=settings.site_id, gateway_id=settings.gateway_id,
        cage_ids=[cage.id], token_env=f'VIEW_{index}') for index, cage in enumerate(settings.cages)]
    receiver = create_receiver(tmp_path / 'receiver.sqlite3', [pi], viewers=viewers,
        environ={'PI': PI_TOKEN, **{f'VIEW_{index}': token for index, token in enumerate(VIEW_TOKENS)}})
    sender = AirUploader(AirUploadConfig(enabled=True, endpoint='https://receiver.test/v1/edge/air'),
                         settings, states, PI_TOKEN, now=lambda: clock[0])
    store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id), now=lambda: clock[0])
    original = sensor_fixture(first, NOW - timedelta(minutes=1), (20., 21., 22.))
    store.telemetry(first.id, original.model_dump(mode='json'), NOW.isoformat())
    fixture = SimpleNamespace(settings=settings, states=states, clients=clients, subscribers=subscribers,
        clock=clock, enclosures=enclosures, receiver=receiver, sender=sender, store=store,
        original_gateway_dump='\n'.join(store.db.iterdump()))
    try:
        yield fixture
    finally:
        for subscriber in subscribers:
            subscriber.close()
        receiver.state.db.close()
        store.close()


def test_two_cage_pipeline_preserves_sources_fields_and_scoped_views(pipeline):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pipeline.receiver),
                                     base_url='https://receiver.test') as client:
            sources = {}
            for step in range(2):
                pipeline.clock[0] = NOW + timedelta(seconds=step * 5)
                for index, cage in enumerate(pipeline.settings.cages):
                    base = (19.125 + step * 4) if index == 0 else (27.375 + step)
                    sources[cage.id] = deliver(pipeline, cage, (base, base + 1, base + 2))
                for cage in pipeline.settings.cages:
                    assert await pipeline.sender.cycle(client, cage.id), pipeline.sender.statuses[cage.id]
                    assert pipeline.sender.statuses[cage.id]['outcome'] == 'stored'
            seen_fields = []
            for index, cage in enumerate(pipeline.settings.cages):
                headers = {'Authorization': 'Bearer ' + VIEW_TOKENS[index]}
                path = f'/v1/enclosures/{pipeline.enclosures[cage.id]}/air'
                response = await client.get(path, headers=headers)
                assert response.status_code == 200
                assert response.headers['cache-control'] == 'no-store'
                view, local, source = response.json(), pipeline.states[cage.id].snapshot(), sources[cage.id]
                assert view['enclosure_id'] == str(pipeline.enclosures[cage.id])
                assert (view['cage_id'], view['node_id']) == (cage.id, cage.node_id)
                assert view['message_id'] == view['source_message_id'] == str(source.message_id)
                assert datetime.fromisoformat(view['sampled_at']) == source.sampled_at
                assert datetime.fromisoformat(view['generated_at']) == pipeline.clock[0]
                assert {sensor['id']: sensor['value_c'] for sensor in view['sensors']} == {
                    key: source.readings[key].value for key in ('T1', 'T2', 'T3')}
                assert view['accepted_samples'] == local['accepted_samples'] == 2
                assert view['gap_resets'] == local['gap_resets'] == 0
                assert view['color_range_c'] == local['color_range_c']
                assert len(view['field']['values_c']) == len(local['field']['values_c']) == 12000
                assert max(abs(actual - expected) for actual, expected in
                           zip(view['field']['values_c'], local['field']['values_c'])) <= 2e-6
                assert view['baseline'] is None and local['baseline'] is not None
                assert view['fresh'] and not view['held'] and view['status'] == 'live'
                assert pipeline.sender.statuses[cage.id]['source_message_id'] == str(source.message_id)
                assert pipeline.sender.statuses[cage.id]['estimate_id'] == view['estimate_id']
                other = pipeline.settings.cages[1 - index]
                denied = await client.get(f'/v1/enclosures/{pipeline.enclosures[other.id]}/air', headers=headers)
                assert denied.status_code == 403
                seen_fields.append(view['field']['values_c'])
            assert seen_fields[0] != seen_fields[1]
            assert not pipeline.sender.pending
            assert_gateway_untouched(pipeline)
    asyncio.run(run())


def test_delayed_estimate_ack_cannot_replace_newer_cage_view(pipeline):
    async def run():
        first, second = pipeline.settings.cages
        old_source = deliver(pipeline, first, (20.125, 21.25, 22.375))
        delayed = build_estimate(pipeline.settings, first, pipeline.states[first.id])
        assert str(delayed.source_message_id) == str(old_source.message_id)
        deliver(pipeline, second, (27.25, 28.375, 29.5))
        pipeline.clock[0] += timedelta(seconds=5)
        current = deliver(pipeline, first, (23.125, 24.25, 25.375))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pipeline.receiver),
                                     base_url='https://receiver.test') as client:
            for cage in pipeline.settings.cages:
                assert await pipeline.sender.cycle(client, cage.id)
            headers = {'Authorization': 'Bearer ' + VIEW_TOKENS[0]}
            path = f'/v1/enclosures/{pipeline.enclosures[first.id]}/air'
            before = (await client.get(path, headers=headers)).json()
            ack = await pipeline.sender.send(client, delayed)
            assert ack == delayed.acknowledgement('superseded')
            after = (await client.get(path, headers=headers)).json()
            assert after == before
            assert after['message_id'] == str(current.message_id)
            assert after['accepted_samples'] == 2
            assert pipeline.receiver.state.db.execute('SELECT COUNT(*) FROM air_latest').fetchone()[0] == 2
            assert_gateway_untouched(pipeline)
    asyncio.run(run())
