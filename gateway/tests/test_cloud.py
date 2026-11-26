import asyncio
import json
import sqlite3
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from habitat_gateway.api import create_app
from habitat_gateway.cloud import CloudSync
from habitat_gateway.config import CloudConfig, cloud_token
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import CommandRequest, Telemetry
from habitat_gateway.transport import SimulatedTransport
from tests.conftest import confirm_empty_cloud


@pytest.fixture
def cloud_rig(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_CLOUD_TOKEN", "test-only-cloud-token-32-characters")
    settings = settings.model_copy(update={"cloud": CloudConfig(
        enabled=True, endpoint="https://saas.example.test/v1/edge/sync", batch_size=2,
    )})
    transport = SimulatedTransport(settings)
    gateway = Gateway(settings, transport)
    transport.start(gateway)
    confirm_empty_cloud(gateway.store)
    yield gateway, CloudSync(gateway, cloud_token(settings))
    gateway.store.close()


def receipt(payload, ids=None, **overrides):
    return {"schema_version": 1, "site_id": payload["site_id"], "gateway_id": payload["gateway_id"],
            "accepted_event_ids": ids if ids is not None else [e["event_id"] for e in payload["events"]],
            **overrides}


def deliver(sync, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sync.send_once(client)
    return asyncio.run(run())


def test_telemetry_duplicate_and_command_transitions_are_durable(cloud_rig):
    gateway, sync = cloud_rig
    initial = gateway.store.cloud_batch(100)
    assert len(initial) == 1
    sample = gateway.store.history("CAGE-001", 1)[0]
    assert not gateway.ingest("CAGE-001", Telemetry.model_validate(sample))
    command = gateway.send_command("CAGE-001", CommandRequest(
        request_id=uuid4(), actuator_id="fan", action="on", duration_s=5,
    ))
    gateway.transport.step()
    events = gateway.store.cloud_batch(100)
    transitions = [e["payload"]["status"] for e in events if e["kind"] == "command.updated"]
    assert transitions == ["publishing", "published", "applied"]
    assert gateway.store.command(command["command_id"])["status"] == "applied"
    assert len({e["event_id"] for e in events}) == len(events)
    assert events[0]["payload"]["data_source"] == "simulation"
    assert all(e["site_id"] == "STORE-001" and e["gateway_id"] == "PI-001" for e in events)


@pytest.mark.parametrize("source", ["telemetry", "command"])
def test_outbox_failure_rolls_back_source_record(cloud_rig, source):
    gateway, sync = cloud_rig
    gateway.store.db.execute("""CREATE TRIGGER fail_queue BEFORE INSERT ON cloud_outbox
        BEGIN SELECT RAISE(ABORT, 'test outbox failure'); END""")
    identity = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError, match="outbox failure"):
        if source == "telemetry":
            body = {**gateway.store.history("CAGE-001", 1)[0], "message_id": identity}
            gateway.ingest("CAGE-001", Telemetry.model_validate(body))
        else:
            gateway.send_command("CAGE-001", CommandRequest(
                request_id=identity, actuator_id="fan", action="off",
            ))
    assert gateway.store.command(identity) is None
    assert all(row["message_id"] != identity for row in gateway.store.history("CAGE-001", 100))


def test_partial_ack_only_removes_accepted_batch_events(cloud_rig):
    gateway, sync = cloud_rig
    gateway.transport.step()
    gateway.transport.step()
    offered = gateway.store.cloud_batch(100)

    def handler(request):
        payload = json.loads(request.content)
        assert len(payload["events"]) == 2
        assert request.headers["Authorization"].startswith("Bearer test-only")
        return httpx.Response(200, json=receipt(payload, [offered[0]["event_id"]]))

    assert deliver(sync, handler) is False
    assert sync.status()["last_error"] == "partial_ack"
    assert gateway.store.cloud_batch(100) == offered[1:]
    assert deliver(sync, lambda r: httpx.Response(200, json=receipt(json.loads(r.content))))
    assert sync.status()["pending_events"] == 0


@pytest.mark.parametrize("case", ["timeout", "unauthorized", "redirect", "html", "empty", "wrong_gateway", "unknown_id", "duplicate_id", "oversized"])
def test_invalid_delivery_never_discards_pending_events(cloud_rig, case):
    gateway, sync = cloud_rig
    before = gateway.store.cloud_batch(100)

    def handler(request):
        payload = json.loads(request.content)
        if case == "timeout":
            raise httpx.ReadTimeout("secret response must not appear in status")
        if case == "unauthorized":
            return httpx.Response(401)
        if case == "redirect":
            return httpx.Response(307, headers={"Location": "https://elsewhere.example.test"})
        if case == "html":
            return httpx.Response(200, text="<html>demo page</html>")
        if case == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        if case == "empty":
            return httpx.Response(200, json={})
        body = receipt(payload)
        if case == "wrong_gateway":
            body["gateway_id"] = "PI-OTHER"
        elif case == "unknown_id":
            body["accepted_event_ids"] = [str(uuid4())]
        elif case == "duplicate_id":
            body["accepted_event_ids"] *= 2
        return httpx.Response(200, json=body)

    assert deliver(sync, handler) is False
    assert gateway.store.cloud_batch(100) == before
    assert gateway.healthy
    assert "secret" not in sync.status()["last_error"]


def test_restart_preserves_ids_order_and_rejects_other_gateway(settings, tmp_path):
    settings = settings.model_copy(update={"database": str(tmp_path / "events.sqlite3"),
        "cloud": CloudConfig(enabled=True, endpoint="https://saas.example.test/sync")})
    transport = SimulatedTransport(settings)
    first = Gateway(settings, transport)
    transport.start(first)
    before = first.store.cloud_batch(100)
    first.store.close()
    restarted = Gateway(settings, SimulatedTransport(settings))
    assert restarted.store.cloud_batch(100) == before
    restarted.store.close()
    with pytest.raises(ValueError, match="different site/gateway"):
        Gateway(settings.model_copy(update={"gateway_id": "PI-002"}), SimulatedTransport(settings))


def test_network_wait_does_not_block_local_commands(cloud_rig):
    gateway, sync = cloud_rig

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=receipt(json.loads(request.content)))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(sync.send_once(client))
            await entered.wait()
            completed = threading.Event()

            def command():
                result = gateway.send_command("CAGE-001", CommandRequest(
                    request_id=uuid4(), actuator_id="fan", action="off",
                ))
                assert result["status"] == "published"
                completed.set()

            thread = threading.Thread(target=command, daemon=True)
            thread.start()
            try:
                assert await asyncio.to_thread(completed.wait, 1), "cloud upload held the control lock"
            finally:
                release.set()
                await task
                thread.join(timeout=1)
            # Newly produced command events were not in the in-flight batch and survive its ACK.
            assert all(e["kind"] == "command.updated" for e in gateway.store.cloud_batch(100))

    asyncio.run(run())


def test_disabled_sync_and_authenticated_status(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_API_TOKEN", "local-only-token-32-characters-long")
    with TestClient(create_app(settings, run_worker=False)) as client:
        assert client.get("/v1/cloud").status_code == 401
        status = client.get("/v1/cloud", headers={"Authorization": "Bearer local-only-token-32-characters-long"}).json()
        assert status["enabled"] is False and status["pending_events"] == 0


def test_cloud_configuration_rejects_cleartext_and_missing_credentials(settings, monkeypatch):
    for endpoint in ["http://habitatos.kro.kr/sync", "https://user:password@example.test/sync",
                     "https://example.test/sync?token=secret", "https://example.test/sync#fragment"]:
        with pytest.raises(ValueError):
            CloudConfig(enabled=True, endpoint=endpoint)
    cloud = CloudConfig(enabled=True, endpoint="http://127.0.0.1:9000/v1/edge/sync")
    monkeypatch.delenv("HABITAT_CLOUD_TOKEN", raising=False)
    with pytest.raises(ValueError, match="HABITAT_CLOUD_TOKEN"):
        cloud_token(settings.model_copy(update={"cloud": cloud}))


def test_cancelled_request_keeps_queue_for_next_start(cloud_rig):
    gateway, sync = cloud_rig
    before = gateway.store.cloud_batch(100)

    async def run():
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(sync.send_once(client))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    assert gateway.store.cloud_batch(100) == before


def test_worker_drains_multiple_batches_then_sends_heartbeat(cloud_rig, monkeypatch):
    gateway, sync = cloud_rig
    gateway.transport.step()
    gateway.transport.step()
    calls = []
    intervals = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(200, json=receipt(payload))

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr("habitat_gateway.cloud.httpx.AsyncClient", lambda **kwargs: client)

        async def sleep(delay):
            intervals.append(delay)
            if len(intervals) == 3:
                raise asyncio.CancelledError

        monkeypatch.setattr("habitat_gateway.cloud.asyncio.sleep", sleep)
        with pytest.raises(asyncio.CancelledError):
            await sync.run()

    asyncio.run(run())
    assert [len(p["events"]) for p in calls] == [2, 1, 0]
    assert intervals == [0.05, sync.config.interval_s, sync.config.interval_s]
    assert calls[-1]["gateway"]["cages"][0]["state"]["telemetry"]["data_source"] == "simulation"
