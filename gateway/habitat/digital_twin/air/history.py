"""Restore an air display from the existing authenticated local Gateway API."""
import ipaddress
import json
import logging
import time
from urllib.parse import quote

import httpx

from habitat.common.models import utcnow
from .telemetry import validate_telemetry


logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_S = 5.0


class HistoryFailure(Exception):
    """A fixed diagnostic code, never the response body or request headers."""


def local_origin(settings):
    host = settings.server.host
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1' if host == '0.0.0.0' else '::1'
    if host != 'localhost':
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise ValueError('air history requires a loopback Gateway API')
        if address.version == 6:
            host = '[' + host + ']'
    return 'http://' + host + ':' + str(settings.server.port)


class HistoryBootstrap:
    """One bounded successful load per cage, with independent failure retries.

    MQTT starts separately. Older rows encountered after a live arrival are
    ignored by AirState.restore, so an HTTP response cannot roll the display back.
    """

    def __init__(self, settings, states, token, limit=300, *, now=utcnow, client_factory=None):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('air history limit must be 1..1000')
        if (not isinstance(token, str) or len(token) < 32 or not token.isascii()
                or any(character.isspace() for character in token)):
            raise ValueError('air history API credential required')
        self.origin = local_origin(settings)
        self.states = dict(states)
        self.cages = {cage.id: cage for cage in settings.cages}
        if not self.states or not self.states.keys() <= self.cages.keys():
            raise ValueError('air history references an unknown cage')
        self.token, self.limit, self.now = token, limit, now
        self.client_factory = client_factory or httpx.Client

    def load(self, client, cage_id, stop=None):
        cage, state = self.cages[cage_id], self.states[cage_id]
        url = self.origin + '/v1/cages/' + quote(cage_id, safe='') + '/telemetry'
        started = time.monotonic()
        with client.stream('GET', url, params={'limit': self.limit},
                           headers={'Authorization': 'Bearer ' + self.token},
                           follow_redirects=False) as response:
            if response.status_code != 200:
                raise HistoryFailure('http_' + str(response.status_code))
            body = bytearray()
            for block in response.iter_bytes(chunk_size=65536):
                if stop is not None and stop.is_set():
                    return None
                if time.monotonic() - started > REQUEST_TIMEOUT_S:
                    raise HistoryFailure('response_timeout')
                body.extend(block)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise HistoryFailure('response_too_large')
        try:
            rows = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise HistoryFailure('invalid_json') from None
        if not isinstance(rows, list) or len(rows) > self.limit:
            raise HistoryFailure('invalid_history_list')
        now, samples, rejected = self.now(), [], 0
        for raw in rows:
            if stop is not None and stop.is_set():
                return None
            try:
                samples.append(validate_telemetry(raw, cage, now, state.max_future_skew))
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
                rejected += 1
        samples.sort(key=lambda sample: sample.sampled_at)
        restored = 0
        for sample in samples:
            if stop is not None and stop.is_set():
                return None
            payload = sample.model_dump(mode='json')
            event = dict(event='telemetry', retained=False, fresh_unique=True,
                         message_id=str(sample.message_id), sampled_at=payload['sampled_at'],
                         readings=payload['readings'], payload=payload)
            if state.restore(event, now=self.now()):
                restored += 1
        return dict(restored=restored, rejected=rejected, rows=len(rows))

    def run(self, stop):
        pending = set(self.states)
        attempts = {cage_id: 0 for cage_id in pending}
        due = {cage_id: 0.0 for cage_id in pending}
        # The total response deadline also bounds slow trickles. Short read
        # timeouts ensure stopping cannot wait indefinitely on an idle socket.
        timeout = httpx.Timeout(REQUEST_TIMEOUT_S, connect=2., read=1., write=1., pool=1.)
        with self.client_factory(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            while pending and not stop.is_set():
                for cage_id in sorted(pending):
                    if stop.is_set():
                        return
                    if time.monotonic() < due[cage_id]:
                        continue
                    try:
                        result = self.load(client, cage_id, stop)
                        if result is None:
                            return
                        pending.remove(cage_id)
                        logger.info('Air history loaded cage=%s restored=%s rejected=%s rows=%s',
                                    cage_id, result['restored'], result['rejected'], result['rows'])
                        continue
                    except HistoryFailure as error:
                        code = str(error)
                    except httpx.TimeoutException:
                        code = 'request_timeout'
                    except httpx.HTTPError:
                        code = 'request_failed'
                    except Exception:
                        # Model/validation exceptions may contain input values.
                        code = 'history_restore_failed'
                    attempts[cage_id] += 1
                    due[cage_id] = time.monotonic() + min(30., 2. ** min(attempts[cage_id], 5))
                    logger.warning('Air history unavailable cage=%s reason=%s; MQTT remains active',
                                   cage_id, code)
                if pending:
                    stop.wait(min(1., max(0., min(due[cage_id] for cage_id in pending) - time.monotonic())))
