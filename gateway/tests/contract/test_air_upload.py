"""Air upload retries and exact acknowledgements, without MQTT or SaaS access."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from habitat.saas.air import AirUploader, AirUploadConfig, build_estimate
from habitat.saas.air_contract import AirEstimate

NOW = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)


class Source:
    def __init__(self, cage):
        self.cfg = json.loads(Path('configs/examples/air-viewer.json').read_text())
        self.cfg['cage_id'] = cage.id
        self.frame = dict(source_mode='live', status='live', fresh=True, cage_id=cage.id,
            message_id=str(uuid4()), sampled_at=(NOW-timedelta(seconds=1)).isoformat(),
            generated_at=NOW.isoformat(timespec='milliseconds'), dimensions_m=[.2, .2, .3],
            grid=dict(shape_zyx=[30,20,20], spacing_m=.01, origin_m=[.005,.005,.005], order='zyx'),
            sensors=[dict(id=key, **self.cfg['sensors'][key], value_c=23.) for key in ('T1','T2','T3')],
            field={'values_c': [23.1234] * 12000}, color_range_c=[22.,24.], accepted_samples=5, gap_resets=0)

    def snapshot(self):
        return deepcopy(self.frame)


def uploader(settings, *, enabled=True):
    states = {c.id: Source(c) for c in settings.cages}
    config = AirUploadConfig(enabled=enabled, endpoint='http://127.0.0.1:9000/v1/edge/air')
    return AirUploader(config, settings, states, 'development-only-token-'+'x'*32, now=lambda: NOW)


def run_cycle(sender, handler, cage_id):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sender.cycle(client, cage_id)
    return asyncio.run(run())


def ack(request, outcome='stored'):
    frame = AirEstimate.model_validate_json(request.content)
    return httpx.Response(200, json=frame.acknowledgement(outcome).model_dump(mode='json'))


def test_frame_preserves_source_identity_and_float32_precision(settings):
    cage = settings.cages[0]
    state = Source(cage)
    first = build_estimate(settings, cage, state)
    second = build_estimate(settings, cage, state)
    assert first == second
    assert str(first.source_message_id) == state.frame['message_id']
    assert first.field_values() == pytest.approx(state.frame['field']['values_c'], abs=2e-6)
    assert first.color_range_c == (22., 24.)
    assert first.source_accepted_samples == 5
    state.frame['generated_at'] = (NOW+timedelta(seconds=1)).isoformat()
    assert build_estimate(settings, cage, state).estimate_id != first.estimate_id


@pytest.mark.parametrize('field,value', [('source_mode','replay'), ('fresh',False), ('status','offline')])
def test_replay_and_held_frames_never_upload(settings, field, value):
    sender = uploader(settings)
    cage = settings.cages[0].id
    sender.states[cage].frame[field] = value
    calls=[]
    assert run_cycle(sender, lambda r: calls.append(r), cage)
    assert not calls and not sender.pending


def test_disabled_uploader_does_not_access_network(settings):
    sender = uploader(settings, enabled=False)
    assert run_cycle(sender, lambda r: pytest.fail('unexpected request'), settings.cages[0].id)


def test_failed_retry_uses_same_frame_and_exact_ack_is_required(settings):
    sender = uploader(settings)
    cage = settings.cages[0].id
    bodies=[]
    def handler(request):
        bodies.append(request.content)
        return httpx.Response(503) if len(bodies)==1 else ack(request)
    assert not run_cycle(sender, handler, cage)
    assert cage in sender.pending and cage not in sender.acknowledged
    assert run_cycle(sender, handler, cage)
    assert bodies[0] == bodies[1]
    assert not sender.pending and sender.statuses[cage]['last_error'] is None
    assert run_cycle(sender, handler, cage)
    assert len(bodies)==2


@pytest.mark.parametrize('kind', ['html','wrong_source','wrong_cage','oversized','redirect'])
def test_http_success_without_matching_ack_never_clears_pending(settings, kind):
    sender=uploader(settings);cage=settings.cages[0].id
    def handler(request):
        if kind=='html':return httpx.Response(200,text='<html>OK</html>')
        if kind=='oversized':return httpx.Response(200,content=b' '*17000)
        if kind=='redirect':return httpx.Response(302,headers={'Location':'https://elsewhere.invalid/'})
        data=AirEstimate.model_validate_json(request.content).acknowledgement().model_dump(mode='json')
        if kind=='wrong_source':data['source_message_id']=str(uuid4())
        else:data['cage_id']='WRONG-CAGE'
        return httpx.Response(200,json=data)
    assert not run_cycle(sender,handler,cage)
    assert cage in sender.pending and cage not in sender.acknowledged


def test_new_frame_replaces_failed_frame_without_growing_queue(settings):
    sender=uploader(settings);cage=settings.cages[0].id
    assert not run_cycle(sender,lambda r:httpx.Response(503),cage)
    first=sender.pending[cage].source_message_id
    sender.states[cage].frame['message_id']=str(uuid4())
    sender.states[cage].frame['sampled_at']=NOW.isoformat()
    assert not run_cycle(sender,lambda r:httpx.Response(503),cage)
    assert len(sender.pending)==1 and sender.pending[cage].source_message_id!=first
    sender.states[cage].frame['fresh']=False
    assert run_cycle(sender,lambda r:pytest.fail('stale pending was sent'),cage)
    assert not sender.pending


def test_failure_for_one_cage_does_not_stop_another(settings):
    first=settings.cages[0]
    second=first.model_copy(update={'id':'CAGE-SECOND','node_id':'NODE-SECOND'})
    settings=settings.model_copy(update={'cages':[first,second]})
    sender=uploader(settings)
    def handler(request):
        data=json.loads(request.content)
        return httpx.Response(503) if data['cage_id']==first.id else ack(request)
    assert not run_cycle(sender,handler,first.id)
    assert run_cycle(sender,handler,second.id)
    assert list(sender.pending)==[first.id]
    assert list(sender.acknowledged)==[second.id]


def test_old_or_future_sources_do_not_bypass_live_flag(settings):
    for age in [31,-6]:
        sender=uploader(settings);cage=settings.cages[0].id
        sender.states[cage].frame['sampled_at']=(NOW-timedelta(seconds=age)).isoformat()
        sender.states[cage].frame['generated_at']=sender.states[cage].frame['sampled_at']
        assert run_cycle(sender,lambda r:pytest.fail('invalid source age sent'),cage)
        assert not sender.pending


def test_url_refuses_plaintext_remote_and_embedded_credentials():
    for endpoint in ['http://example.com/v1/edge/air','https://user:password@example.com/air',
                     'https://example.com/air?token=unsafe']:
        with pytest.raises(ValueError):AirUploadConfig(enabled=True,endpoint=endpoint)
