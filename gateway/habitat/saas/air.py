"""Latest-only air estimate upload, isolated from durable sensor event delivery."""
import asyncio
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import AnyHttpUrl, Field, model_validator

from habitat.common.http import validate_service_url
from habitat.common.models import Model, utcnow
from .air_contract import AirAck, AirEstimate, MAX_AGE_SECONDS, MAX_FUTURE_SECONDS, MODEL_ID, MODEL_VERSION, encode_field

logger = logging.getLogger(__name__)


class AirUploadConfig(Model):
    enabled: bool = False
    endpoint: AnyHttpUrl | None = None
    token_env: str = 'HABITAT_CLOUD_TOKEN'
    interval_s: float = Field(default=5, ge=1, le=30)
    timeout_s: float = Field(default=5, ge=1, le=10)
    retry_max_s: float = Field(default=60, ge=1, le=300)

    @model_validator(mode='after')
    def destination(self):
        if self.enabled and self.endpoint is None:
            raise ValueError('air upload endpoint required')
        if self.endpoint:
            validate_service_url(self.endpoint, 'air_upload.endpoint')
        if self.retry_max_s < self.interval_s:
            raise ValueError('retry maximum must be at least the normal interval')
        return self


def load_upload_config(path=None):
    return AirUploadConfig.model_validate_json(Path(path).read_bytes()) if path else AirUploadConfig()


def build_estimate(settings, cage, state, snapshot=None):
    """Bind one accepted model result to its exact source and immutable configuration."""
    snapshot = state.snapshot() if snapshot is None else snapshot
    if (snapshot.get('source_mode') != 'live' or not snapshot.get('fresh')
            or snapshot.get('status') != 'live' or not snapshot.get('field')):
        return None
    if snapshot.get('cage_id') != cage.id or state.cfg['cage_id'] != cage.id:
        raise ValueError('air source cage mismatch')
    config = {key: state.cfg[key] for key in ('cage_id', 'dimensions_m', 'payload_temperature_unit',
        'temperature_limits_c', 'stale_after_s', 'sensors')}
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    encoded, digest = encode_field(snapshot['field']['values_c'])
    identity = [settings.site_id, settings.gateway_id, cage.id, cage.node_id,
        cage.geometry_revision, cage.placement_revision, snapshot['message_id'],
        snapshot['generated_at'], MODEL_ID, MODEL_VERSION, config_sha, digest,
        snapshot['color_range_c'], snapshot['accepted_samples'], snapshot['gap_resets']]
    estimate_id = uuid5(NAMESPACE_URL, 'habitat-air-v1:' + json.dumps(identity, separators=(',', ':')))
    return AirEstimate(estimate_id=estimate_id, site_id=settings.site_id, gateway_id=settings.gateway_id,
        cage_id=cage.id, node_id=cage.node_id, source_message_id=snapshot['message_id'],
        sampled_at=snapshot['sampled_at'], generated_at=snapshot['generated_at'],
        geometry_revision=cage.geometry_revision, placement_revision=cage.placement_revision,
        config_sha256=config_sha, dimensions_m=snapshot['dimensions_m'], grid=snapshot['grid'],
        sensors=[{key: sensor[key] for key in ('id', 'label', 'xyz_m', 'value_c')}
                 for sensor in snapshot['sensors']], field_base64=encoded, field_sha256=digest,
        color_range_c=snapshot['color_range_c'], source_accepted_samples=snapshot['accepted_samples'],
        source_gap_resets=snapshot['gap_resets'])


class AirUploadFailure(Exception):
    pass


class AirUploader:
    def __init__(self, config, settings, states, token=None, *, now=utcnow):
        self.config, self.settings, self.states, self.token = config, settings, dict(states), token
        self.now = now
        self.cages = {c.id: c for c in settings.cages}
        if not self.states.keys() <= self.cages.keys():
            raise ValueError('air upload references an unknown cage')
        if config.enabled and (not token or len(token) < 32 or not token.isascii()
                               or any(ch.isspace() for ch in token)):
            raise ValueError('air upload credential required')
        self.pending = {}
        self.acknowledged = {}
        self.statuses = {key: {'last_success_at': None, 'last_error': None, 'consecutive_failures': 0}
                         for key in self.states}

    async def send(self, client, estimate):
        async with client.stream('POST', str(self.config.endpoint), json=estimate.model_dump(mode='json'),
                headers={'Authorization': f'Bearer {self.token}'}, follow_redirects=False,
                timeout=self.config.timeout_s) as response:
            if response.status_code != 200:
                raise AirUploadFailure(f'http_{response.status_code}')
            body = bytearray()
            async for block in response.aiter_bytes():
                body.extend(block)
                if len(body) > 16384:
                    raise AirUploadFailure('ack_too_large')
        try:
            ack = AirAck.model_validate_json(body)
        except ValueError:
            raise AirUploadFailure('invalid_ack') from None
        if ack != estimate.acknowledgement(ack.outcome):
            raise AirUploadFailure('ack_mismatch')
        return ack

    async def cycle(self, client, cage_id):
        if not self.config.enabled:
            return True
        status = self.statuses[cage_id]
        try:
            state = self.states[cage_id]
            snapshot = await asyncio.to_thread(state.snapshot)
            key = (snapshot.get('message_id'), snapshot.get('generated_at'))
            if self.acknowledged.get(cage_id) == key:
                self.pending.pop(cage_id, None)
                return True
            previous = self.pending.get(cage_id)
            same_frame = (previous is not None and str(previous.source_message_id) == key[0]
                          and previous.generated_at == datetime.fromisoformat(key[1].replace('Z', '+00:00')))
            if not same_frame:
                estimate = await asyncio.to_thread(build_estimate, self.settings, self.cages[cage_id], state, snapshot)
                if estimate is None:
                    self.pending.pop(cage_id, None)
                    status['source'] = 'waiting_fresh_measurement'
                    return True
                self.pending[cage_id] = estimate
            else:
                estimate = previous
            age = (self.now() - estimate.sampled_at).total_seconds()
            if not snapshot.get('fresh') or not -MAX_FUTURE_SECONDS <= age <= MAX_AGE_SECONDS:
                self.pending.pop(cage_id, None)
                status['source'] = 'waiting_fresh_measurement'
                return True
            ack = await asyncio.wait_for(self.send(client, estimate), timeout=self.config.timeout_s)
            self.acknowledged[cage_id] = key
            self.pending.pop(cage_id, None)
            status.update(last_success_at=self.now().isoformat(), last_error=None, consecutive_failures=0,
                source='live', source_message_id=str(estimate.source_message_id),
                estimate_id=str(estimate.estimate_id), outcome=ack.outcome)
            logger.info('Air estimate acknowledged cage=%s source_message_id=%s estimate_id=%s outcome=%s',
                        cage_id, estimate.source_message_id, estimate.estimate_id, ack.outcome)
            return True
        except AirUploadFailure as error:
            code = str(error)
        except (TimeoutError, httpx.TimeoutException):
            code = 'timeout'
        except httpx.HTTPError:
            code = 'network_error'
        except (ValueError, KeyError, TypeError):
            code = 'invalid_air_source'
        except Exception:
            code = 'air_upload_internal_error'
        # No exception text, response bodies, URLs or credentials enter logs/status.
        status.update(last_error=code, consecutive_failures=status['consecutive_failures'] + 1)
        return False

    async def _cage_loop(self, client, cage_id):
        while True:
            success = await self.cycle(client, cage_id)
            failures = self.statuses[cage_id]['consecutive_failures']
            delay = self.config.interval_s if success else min(self.config.retry_max_s,
                self.config.interval_s * 2 ** min(failures - 1, 8))
            await asyncio.sleep(delay)

    async def run(self, stop):
        if not self.config.enabled:
            return
        async with httpx.AsyncClient(trust_env=False) as client:
            tasks = [asyncio.create_task(self._cage_loop(client, key)) for key in self.states]
            try:
                while not stop.is_set():
                    await asyncio.sleep(.2)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
