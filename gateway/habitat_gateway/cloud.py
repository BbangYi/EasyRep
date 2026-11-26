"""Outbound SaaS event delivery. Network I/O never holds the control lock."""
import asyncio
import json
import logging
import random
import httpx

from . import __version__
from .gateway import Gateway
from .sync_contract import SyncAck
from .transport import NoDeviceTransport

logger = logging.getLogger(__name__)


class SyncFailure(Exception):
    pass


class CloudSync:
    def __init__(self, gateway, token, *, heartbeat_only=False):
        self.gateway = gateway
        self.config = gateway.settings.cloud
        self._batch_limit = self.config.batch_size
        self.token = token
        self.heartbeat_only = heartbeat_only
        self.last_attempt_at = None
        self.last_success_at = None
        self.last_event_success_at = None
        self.last_heartbeat_success_at = None
        self.last_heartbeat_error = None
        self.last_error = None
        self.consecutive_failures = 0

    def status(self):
        with self.gateway.lock:
            return {
                "enabled": self.config.enabled,
                "last_attempt_at": self.last_attempt_at,
                "last_success_at": self.last_success_at,
                "last_event_success_at": self.last_event_success_at,
                "last_heartbeat_success_at": self.last_heartbeat_success_at,
                "last_heartbeat_error": self.last_heartbeat_error,
                "last_error": self.last_error,
                "consecutive_failures": self.consecutive_failures,
                "continuity": self.gateway.store.cloud_continuity(),
                **self.gateway.store.cloud_backlog(),
            }

    def _prepare(self):
        gateway = self.gateway
        with gateway.lock:
            self.last_attempt_at = gateway.now().isoformat()
            return {
                "schema_version": 1,
                "site_id": gateway.settings.site_id,
                "gateway_id": gateway.settings.gateway_id,
                "sent_at": self.last_attempt_at,
                "gateway": {
                    "version": __version__, "transport": gateway.settings.transport,
                    "healthy": gateway.healthy and (self.heartbeat_only or gateway.transport.connected),
                    "cages": [{"configuration": cage.model_dump(mode="json"),
                               "state": gateway.status(cage.id)} for cage in gateway.settings.cages],
                },
                "events": [] if self.heartbeat_only else gateway.store.cloud_batch(self._batch_limit),
            }

    async def _post(self, client, payload):
        # No redirects, environment proxy credentials, unbounded response, or error-body logging.
        async with client.stream(
            "POST", str(self.config.endpoint), json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.config.timeout_s, follow_redirects=False,
        ) as response:
            status_code = response.status_code
            if status_code not in (200, 409):
                raise SyncFailure(f"http_{response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise SyncFailure("ack_too_large")
        if status_code == 409:
            # Only the contract's explicit event conflict is safe to isolate.
            # A proxy/generic 409 must leave every queued event eligible for retry.
            try:
                error = json.loads(body)
            except ValueError:
                error = None
            detail = error.get("detail") if isinstance(error, dict) else None
            if isinstance(detail, dict) and detail.get("code") == "event_conflict":
                raise SyncFailure("event_conflict")
            raise SyncFailure("http_409")
        try:
            return SyncAck.model_validate_json(body)
        except ValueError:
            raise SyncFailure("invalid_ack") from None

    async def send_once(self, client):
        """True means this network payload was acknowledged, not that the outbox is empty.

        Unknown history does not block delivery. Only an actual allocator regression
        blocks the queue; explicit single-event conflicts are preserved separately.
        Empty heartbeats never mark event synchronization successful.
        """
        if not self.config.enabled:
            return True
        blocked = None
        heartbeat = False
        offered = set()
        try:
            payload = self._prepare()
            with self.gateway.lock:
                blocked = self.gateway.store.cloud_continuity()["blocked_reason"]
            if blocked:
                payload["events"] = []
            offered = {e["event_id"] for e in payload["events"]}
            heartbeat = not offered
            ack = await asyncio.wait_for(self._post(client, payload), timeout=self.config.timeout_s)
            accepted = [str(i) for i in ack.accepted_event_ids]
            if (ack.site_id != payload["site_id"] or ack.gateway_id != payload["gateway_id"]
                    or len(set(accepted)) != len(accepted) or not set(accepted) <= offered):
                raise SyncFailure("ack_mismatch")
            with self.gateway.lock:
                self.gateway.store.cloud_ack(accepted)
            if set(accepted) != offered:
                raise SyncFailure("partial_ack")
        except SyncFailure as error:
            code = str(error)
            if code == "event_conflict" and offered:
                try:
                    with self.gateway.lock:
                        if len(offered) == 1:
                            event_id = next(iter(offered))
                            self.gateway.store.quarantine_cloud_event(event_id)
                            self._batch_limit = 1
                            logger.warning("Cloud event quarantined: event_id=%s", event_id)
                        else:
                            # One request per attempt, reducing the rejected prefix
                            # until the server has identified a single conflict.
                            self._batch_limit = max(1, len(offered) // 2)
                except Exception:
                    code = "sync_internal_error"
        except (TimeoutError, httpx.TimeoutException):
            code = "timeout"
        except httpx.HTTPError:
            code = "network_error"
        except Exception:
            code = "sync_internal_error"
        else:
            with self.gateway.lock:
                now = self.gateway.now().isoformat()
                if heartbeat:
                    self.last_heartbeat_success_at = now
                    self.last_heartbeat_error = None
                else:
                    self.last_event_success_at = now
                    self._batch_limit = self.config.batch_size
                if not blocked:
                    self.last_success_at = now
                self.last_error = blocked or ("cloud_event_conflicts"
                    if self.gateway.store.cloud_backlog()["conflicted_events"] else None)
                self.consecutive_failures = 0
            if self.heartbeat_only:
                logger.info("Cloud heartbeat acknowledged: site=%s gateway=%s",
                            self.gateway.settings.site_id, self.gateway.settings.gateway_id)
            elif accepted:
                logger.info("Cloud events acknowledged: count=%s sequences=%s..%s",
                            len(accepted), payload["events"][0]["event_sequence"],
                            payload["events"][-1]["event_sequence"])
            return True
        with self.gateway.lock:
            self.last_error = blocked or code
            if heartbeat:
                self.last_heartbeat_error = code
            self.consecutive_failures += 1
        logger.warning("Cloud sync delayed: %s", code)
        return False

    async def run(self):
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                success = await self.send_once(client)
                delay = self.config.interval_s
                if success:
                    with self.gateway.lock:
                        backlog = self.gateway.store.cloud_backlog()["eligible_events"]
                        blocked = self.gateway.store.cloud_continuity()["blocked_reason"]
                    if backlog and not self.heartbeat_only and not blocked:
                        # Drain accumulated batches without imposing one polling interval per batch.
                        delay = 0.05
                elif self.last_error != "event_conflict":
                    ceiling = min(self.config.retry_max_s, delay * 2 ** min(self.consecutive_failures, 12))
                    delay = random.uniform(delay, ceiling)
                await asyncio.sleep(delay)


async def run_heartbeat(settings, token, *, once=False):
    """Report Pi liveness without opening the configured DB or starting devices.

    The transient store supplies the existing v1 snapshot's unavailable sensor
    and actuator states. It cannot reset or consume a real gateway's outbox.
    """
    if not settings.cloud.enabled:
        raise ValueError("heartbeat_only_requires_cloud")
    settings = settings.model_copy(update={"database": ":memory:"})
    gateway = Gateway(settings, NoDeviceTransport())
    try:
        sync = CloudSync(gateway, token, heartbeat_only=True)
        if once:
            async with httpx.AsyncClient(trust_env=False) as client:
                connected = await sync.send_once(client)
            return {"connected": connected, "site_id": settings.site_id, "gateway_id": settings.gateway_id,
                    "checked_at": sync.last_attempt_at, "error": sync.last_error}
        await sync.run()
    finally:
        gateway.store.close()
