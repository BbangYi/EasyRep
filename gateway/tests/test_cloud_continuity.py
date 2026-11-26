"""Unverified history permits delivery; conflicts preserve originals and isolate failures."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import httpx
import pytest

from habitat_gateway import __main__ as cli
from habitat_gateway.cloud import CloudSync
from habitat_gateway.config import CloudConfig
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import CommandRequest
from habitat_gateway.saas_reference import Registration, create_receiver
from habitat_gateway.store import Store
from habitat_gateway.transport import NoDeviceTransport
from tests.conftest import confirm_empty_cloud


def evidence(store, high=0, **updates):
    return dict(site_id=store.event_identity[0], gateway_id=store.event_identity[1],
                server_high_watermark=high, verified_at=store.now().isoformat(),
                method="isolated_test_receiver", evidence_ref="test receiver event inventory",
                exclusive_writer=True) | updates


def queue_rejected(gateway):
    return gateway.send_command("CAGE-001", CommandRequest(request_id=uuid4(), actuator_id="mister",
                                                          action="on", duration_s=2))


def send(sync, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sync.send_once(client)
    return asyncio.run(run())


def heartbeat_receipt(request):
    payload = json.loads(request.content)
    assert payload["events"] == []
    return httpx.Response(200, json=dict(schema_version=1, site_id=payload["site_id"],
        gateway_id=payload["gateway_id"], accepted_event_ids=[]))


def event_receipt(request):
    payload = json.loads(request.content)
    return httpx.Response(200, json=dict(schema_version=1, site_id=payload["site_id"],
        gateway_id=payload["gateway_id"], accepted_event_ids=[e["event_id"] for e in payload["events"]]))


def conflict_receipt():
    return httpx.Response(409, json={"detail": {"code": "event_conflict", "message": "stored content differs"}})


def outbox_rows(store):
    """Include isolated events and compare their original serialized bytes."""
    return [tuple(row) for row in store.db.execute(
        "SELECT sequence,event_id,created_at,body FROM cloud_outbox ORDER BY sequence")]


@pytest.fixture
def unconfirmed(settings, tmp_path):
    settings = settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3"),
        "hardware_outputs_enabled": False, "cloud": CloudConfig(enabled=True, endpoint="https://saas.example.test/sync")})
    gateway = Gateway(settings, NoDeviceTransport())
    yield gateway, CloudSync(gateway, "test-only-token"), settings
    gateway.store.close()


def test_unverified_database_sends_original_events_without_claiming_confirmed_history(unconfirmed):
    gateway, sync, _ = unconfirmed
    assert queue_rejected(gateway)["status"] == "rejected"
    before = gateway.store.cloud_batch(100)
    snapshot = sync._prepare()["gateway"]
    calls = []

    def receive(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["gateway"] == snapshot  # No synthetic NoDeviceTransport snapshot replaces this gateway.
        assert payload["events"] == before
        return event_receipt(request)

    assert send(sync, receive)
    state = sync.status()
    assert len(calls) == 1 and state["pending_events"] == 0
    assert state["last_error"] is None
    assert state["last_event_success_at"] is not None and state["last_success_at"] is not None
    assert state["last_heartbeat_success_at"] is None
    assert state["continuity"]["status"] == "unverified"
    assert state["continuity"]["blocked_reason"] is None
    assert state["continuity"]["confirmation_provenance"] is None
    assert state["continuity"]["verified_at"] is state["continuity"]["server_high_watermark"] is None
    assert state["continuity"]["acknowledged_high_watermark"] == 1


def test_ack_watermark_and_sequence_survive_empty_queue_restart_and_delete_failure(unconfirmed):
    gateway, sync, settings = unconfirmed
    confirm_empty_cloud(gateway.store)
    for _ in range(3):
        queue_rejected(gateway)
    events = gateway.store.cloud_batch(100)
    gateway.store.cloud_ack([events[1]["event_id"]])  # Partial ACK may leave a lower unacknowledged sequence.
    assert gateway.store.cloud_continuity()["acknowledged_high_watermark"] == 2
    assert gateway.store.cloud_batch(100) == [events[0], events[2]]
    gateway.store.db.execute("""CREATE TRIGGER fail_ack BEFORE DELETE ON cloud_outbox
        BEGIN SELECT RAISE(ABORT, 'test durable ACK failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        gateway.store.cloud_ack([events[2]["event_id"]])
    assert gateway.store.cloud_continuity()["acknowledged_high_watermark"] == 2
    assert gateway.store.cloud_batch(100) == [events[0], events[2]]
    gateway.store.db.execute("DROP TRIGGER fail_ack")
    gateway.store.cloud_ack(e["event_id"] for e in events)
    assert gateway.store.cloud_batch(100) == []
    gateway.store.close()
    gateway.store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id))
    state = gateway.store.cloud_continuity()
    assert state["acknowledged_high_watermark"] == state["allocated_high_watermark"] == 3
    assert state["status"] == "confirmed" and state["confirmation_provenance"] == "operator_declared"
    queue_rejected(gateway)
    assert gateway.store.cloud_batch(100)[0]["event_sequence"] == 4
    # Restoring a new/legacy DB with no confirmation does not inherit trust from this registration.
    gateway.store.db.execute("DROP TABLE cloud_delivery_state")
    gateway.store.close()
    gateway.store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id))
    assert send(sync, event_receipt)
    state = gateway.store.cloud_continuity()
    assert state["status"] == "unverified" and state["blocked_reason"] is None
    assert state["verified_at"] is None and state["acknowledged_high_watermark"] == 4


@pytest.mark.parametrize("high,updates,error", [
    (8, {}, "cloud_continuity_migration_required"),
    (1, {}, "cloud_pending_reconciliation_required"),
    (0, {"gateway_id": "OTHER"}, "cloud_continuity_identity_mismatch"),
    (0, {"exclusive_writer": False}, "invalid_cloud_continuity_evidence"),
])
def test_operator_cannot_approve_conflicting_or_wrong_registration(unconfirmed, high, updates, error):
    gateway, _, _ = unconfirmed
    queue_rejected(gateway)
    before = gateway.store.cloud_batch(100)
    with pytest.raises(ValueError, match=error):
        gateway.store.confirm_cloud_continuity(evidence(gateway.store, high, **updates))
    assert gateway.store.cloud_batch(100) == before
    assert gateway.store.cloud_continuity()["status"] == "unverified"


def test_legacy_global_conflict_reprobes_events_without_erasing_recorded_evidence(unconfirmed):
    gateway, sync, _ = unconfirmed
    proof = evidence(gateway.store)
    queue_rejected(gateway)
    with gateway.store.db:
        gateway.store.db.execute(
            "UPDATE cloud_delivery_state SET blocked_reason='cloud_event_conflict', blocked_at=? WHERE singleton=1",
            (gateway.now().isoformat(),))
    recorded = tuple(gateway.store.db.execute("SELECT blocked_reason,blocked_at FROM cloud_delivery_state").fetchone())
    state = gateway.store.cloud_continuity()
    assert state["status"] == "unverified" and state["blocked_reason"] is None
    assert state["recorded_blocked_reason"] == "cloud_event_conflict"
    with pytest.raises(ValueError, match="cloud_verification_predates_conflict"):
        gateway.store.confirm_cloud_continuity(proof)
    assert send(sync, event_receipt)
    assert sync.status()["pending_events"] == 0
    assert tuple(gateway.store.db.execute("SELECT blocked_reason,blocked_at FROM cloud_delivery_state").fetchone()) == recorded


def test_legacy_conflict_invalidates_current_confirmation_until_new_evidence(unconfirmed):
    gateway, sync, _ = unconfirmed
    confirmed = gateway.store.confirm_cloud_continuity(evidence(gateway.store))
    assert confirmed["status"] == "confirmed"
    gateway.store.block_cloud_continuity()
    state = gateway.store.cloud_continuity()
    assert state["status"] == "unverified" and state["blocked_reason"] is None
    assert state["recorded_blocked_reason"] == "cloud_event_conflict"
    assert state["verified_at"] == confirmed["verified_at"]
    assert state["confirmation_provenance"] == "operator_declared"
    assert send(sync, heartbeat_receipt)
    assert gateway.store.cloud_continuity()["status"] == "unverified"
    refreshed = gateway.store.confirm_cloud_continuity(evidence(gateway.store))
    assert refreshed["status"] == "confirmed"
    assert refreshed["recorded_blocked_reason"] is None


def test_allocator_regression_still_withholds_events_and_sends_actual_heartbeat(unconfirmed):
    gateway, sync, _ = unconfirmed
    queue_rejected(gateway)
    assert send(sync, event_receipt)
    queue_rejected(gateway)
    before = outbox_rows(gateway.store)
    gateway.store.db.execute("UPDATE sqlite_sequence SET seq=0 WHERE name='cloud_outbox'")
    assert gateway.store.cloud_continuity()["blocked_reason"] == "cloud_sequence_regressed"
    previous_success = sync.last_event_success_at
    assert send(sync, heartbeat_receipt)
    assert sync.status()["last_error"] == "cloud_sequence_regressed"
    assert sync.last_heartbeat_success_at is not None
    assert sync.last_event_success_at == previous_success
    assert outbox_rows(gateway.store) == before


def test_empty_queue_allocator_regression_does_not_report_overall_success(unconfirmed):
    gateway, sync, _ = unconfirmed
    queue_rejected(gateway)
    assert send(sync, event_receipt)
    assert gateway.store.cloud_backlog()["pending_events"] == 0
    gateway.store.db.execute("UPDATE sqlite_sequence SET seq=0 WHERE name='cloud_outbox'")
    sync = CloudSync(gateway, sync.token)
    assert send(sync, heartbeat_receipt)
    state = sync.status()
    assert state["last_heartbeat_success_at"] is not None
    assert state["last_success_at"] is state["last_event_success_at"] is None
    assert state["last_error"] == "cloud_sequence_regressed"
    assert state["continuity"]["status"] == "blocked"
    assert state["pending_events"] == state["eligible_events"] == 0


@pytest.mark.parametrize("failure,code", [("scope", "ack_mismatch"), ("unsent_id", "ack_mismatch"),
    ("unauthorized", "http_401"), ("network", "network_error")])
def test_unverified_delivery_failure_never_acknowledges_or_quarantines_events(unconfirmed, failure, code):
    gateway, sync, _ = unconfirmed
    queue_rejected(gateway)
    before = gateway.store.cloud_batch(100)

    def fail(request):
        payload = json.loads(request.content)
        assert payload["events"] == before
        if failure == "network":
            raise httpx.ConnectError("test network unavailable", request=request)
        if failure == "unauthorized":
            return httpx.Response(401)
        return httpx.Response(200, json=dict(schema_version=1, site_id=payload["site_id"],
            gateway_id="OTHER" if failure == "scope" else payload["gateway_id"],
            accepted_event_ids=[str(uuid4())] if failure == "unsent_id" else []))

    assert not send(sync, fail)
    state = sync.status()
    assert state["last_error"] == code and state["last_heartbeat_error"] is None
    assert state["last_heartbeat_success_at"] is None and state["consecutive_failures"] == 1
    assert state["last_success_at"] is state["last_event_success_at"] is None
    assert gateway.store.cloud_batch(100) == before
    assert state["continuity"]["acknowledged_high_watermark"] == 0
    assert state["conflicted_events"] == 0 and state["eligible_events"] == 1


@pytest.mark.parametrize("body", [
    b"", b"not json", b"[]", b"null", b'{"detail": "event_conflict"}',
    b'{"detail": {"code": "temporarily_busy"}}', b"x" * 65537,
])
def test_generic_or_malformed_409_does_not_isolate_any_event(unconfirmed, body):
    gateway, sync, _ = unconfirmed
    queue_rejected(gateway)
    queue_rejected(gateway)
    before = outbox_rows(gateway.store)
    calls = []

    def receive(request):
        calls.append(json.loads(request.content)["events"])
        return httpx.Response(409, content=body)

    assert not send(sync, receive)
    assert not send(sync, receive)
    assert len(calls) == 2 and len(calls[0]) == len(calls[1]) == 2
    assert sync.status()["last_error"] != "event_conflict"
    assert sync.status()["conflicted_events"] == 0
    assert sync.status()["eligible_events"] == 2
    assert outbox_rows(gateway.store) == before


def test_single_conflict_retains_original_bytes_across_restart_and_heartbeat(unconfirmed):
    gateway, sync, settings = unconfirmed
    queue_rejected(gateway)
    original = outbox_rows(gateway.store)
    assert not send(sync, lambda _: conflict_receipt())
    assert sync.status()["last_error"] == "event_conflict"
    assert gateway.store.cloud_batch(100) == []
    assert outbox_rows(gateway.store) == original
    assert sync.status()["pending_events"] == sync.status()["conflicted_events"] == 1
    assert sync.status()["eligible_events"] == 0
    gateway.store.close()
    gateway.store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id))
    sync = CloudSync(gateway, sync.token)
    assert send(sync, heartbeat_receipt)
    assert sync.status()["last_error"] == "cloud_event_conflicts"
    assert sync.status()["last_event_success_at"] is None
    assert sync.status()["continuity"]["acknowledged_high_watermark"] == 0
    assert sync.status()["continuity"]["verified_at"] is None
    assert gateway.store.cloud_batch(100) == []
    assert outbox_rows(gateway.store) == original
    queue_rejected(gateway)
    assert gateway.store.cloud_batch(100)[0]["event_sequence"] == 2
    assert send(sync, event_receipt)
    assert outbox_rows(gateway.store) == original
    assert sync.status()["last_error"] == "cloud_event_conflicts"
    assert sync.status()["continuity"]["acknowledged_high_watermark"] == 2


def test_conflict_later_in_batch_is_split_without_resequencing_or_losing_healthy_events(unconfirmed):
    gateway, sync, _ = unconfirmed
    for _ in range(4):
        queue_rejected(gateway)
    original = outbox_rows(gateway.store)
    offered = gateway.store.cloud_batch(100)
    conflicted_id = offered[1]["event_id"]
    requests = []
    accepted = []

    def receive(request):
        events = json.loads(request.content)["events"]
        requests.append(events)
        if any(e["event_id"] == conflicted_id for e in events):
            return conflict_receipt()
        accepted.extend(events)
        return event_receipt(request)

    for index in range(12):
        count = len(requests)
        send(sync, receive)
        assert len(requests) == count + 1, "each send_once must have one bounded HTTP exchange"
        if sync.status()["eligible_events"] == 0:
            break
    else:
        pytest.fail("healthy events did not progress past a conflict")
    assert [[e["event_sequence"] for e in batch] for batch in requests] == [
        [1, 2, 3, 4], [1, 2], [1], [2, 3, 4], [2], [3], [4]]
    assert accepted == [offered[0], offered[2], offered[3]]
    assert outbox_rows(gateway.store) == [original[1]]
    assert sync.status()["pending_events"] == sync.status()["conflicted_events"] == 1
    assert sync.status()["last_event_success_at"] is not None
    assert sync.status()["last_error"] == "cloud_event_conflicts"
    assert sync.status()["continuity"]["acknowledged_high_watermark"] == 4
    assert sync.status()["continuity"]["allocated_high_watermark"] == 4
    assert sync.status()["continuity"]["verified_at"] is None


def test_reference_receiver_collision_preserves_originals_and_accepts_healthy_events(unconfirmed, tmp_path):
    gateway, _, _ = unconfirmed
    for _ in range(5):
        queue_rejected(gateway)
    token = "test-reference-cloud-credential-at-least-32"
    gateway.settings = gateway.settings.model_copy(update={"cloud": gateway.settings.cloud.model_copy(
        update={"endpoint": "https://receiver.example.test/v1/edge/sync"})})
    sync = CloudSync(gateway, token)
    original = outbox_rows(gateway.store)
    events = gateway.store.cloud_batch(100)
    seed = deepcopy(sync._prepare())
    seed["events"] = [deepcopy(events[0]), deepcopy(events[2])]
    for event in seed["events"]:
        event["event_id"] = str(uuid4())
    app = create_receiver(str(tmp_path / "receiver.sqlite3"), [Registration(
        site_id=gateway.settings.site_id, gateway_id=gateway.settings.gateway_id,
        cage_ids=list(gateway.cages), token_env="TEST_TOKEN", allow_simulation=True)],
        environ={"TEST_TOKEN": token})

    async def run():
        calls = []

        async def record(request):
            calls.append(json.loads(request.content))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     event_hooks={"request": [record]}) as client:
            response = await client.post(str(sync.config.endpoint), json=seed,
                                         headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            for _ in range(20):
                count = len(calls)
                await sync.send_once(client)
                assert len(calls) == count + 1
                if sync.status()["eligible_events"] == 0:
                    break
            else:
                pytest.fail("reference receiver conflicts prevented healthy event delivery")
        stored = [dict(row) for row in app.state.db.execute(
            "SELECT event_sequence,event_id FROM edge_events ORDER BY event_sequence")]
        assert [(r["event_sequence"], r["event_id"]) for r in stored] == [
            (1, seed["events"][0]["event_id"]), (2, events[1]["event_id"]),
            (3, seed["events"][1]["event_id"]), (4, events[3]["event_id"]), (5, events[4]["event_id"])]

    try:
        asyncio.run(run())
    finally:
        app.state.db.close()
    assert outbox_rows(gateway.store) == [original[0], original[2]]
    state = sync.status()
    assert state["pending_events"] == state["conflicted_events"] == 2 and state["eligible_events"] == 0
    assert state["continuity"]["acknowledged_high_watermark"] == 5
    assert state["continuity"]["status"] == "unverified" and state["continuity"]["verified_at"] is None


@pytest.mark.parametrize("network_failure", [False, True])
def test_all_conflicted_worker_uses_heartbeat_interval_or_failure_backoff_without_fast_drain(unconfirmed, monkeypatch, network_failure):
    gateway, sync, _ = unconfirmed
    queue_rejected(gateway)
    assert not send(sync, lambda _: conflict_receipt())
    sync = CloudSync(gateway, sync.token)
    intervals, calls = [], []

    def receive(request):
        calls.append(json.loads(request.content))
        assert calls[-1]["events"] == []
        if network_failure:
            return httpx.Response(401)
        return heartbeat_receipt(request)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
        monkeypatch.setattr("habitat_gateway.cloud.httpx.AsyncClient", lambda **kwargs: client)

        async def sleep(delay):
            intervals.append(delay)
            if len(intervals) == 3:
                raise asyncio.CancelledError

        monkeypatch.setattr("habitat_gateway.cloud.asyncio.sleep", sleep)
        monkeypatch.setattr("habitat_gateway.cloud.random.uniform", lambda low, high: high)
        with pytest.raises(asyncio.CancelledError):
            await sync.run()

    asyncio.run(run())
    expected = ([min(sync.config.retry_max_s, sync.config.interval_s * 2**attempt) for attempt in (1, 2, 3)]
                if network_failure else [sync.config.interval_s] * 3)
    assert len(calls) == 3 and intervals == expected
    assert sync.status()["pending_events"] == 1 and sync.status()["last_event_success_at"] is None


def test_conflict_worker_makes_bounded_progress_without_exponential_conflict_backoff(unconfirmed, monkeypatch):
    gateway, sync, _ = unconfirmed
    for _ in range(4):
        queue_rejected(gateway)
    conflicted_ids = {event["event_id"] for event in gateway.store.cloud_batch(2)}
    intervals, calls = [], []

    def receive(request):
        events = json.loads(request.content)["events"]
        calls.append(events)
        if any(event["event_id"] in conflicted_ids for event in events):
            return conflict_receipt()
        return event_receipt(request)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
        monkeypatch.setattr("habitat_gateway.cloud.httpx.AsyncClient", lambda **kwargs: client)

        async def sleep(delay):
            intervals.append(delay)
            if len(intervals) == 6:
                raise asyncio.CancelledError

        monkeypatch.setattr("habitat_gateway.cloud.asyncio.sleep", sleep)
        monkeypatch.setattr("habitat_gateway.cloud.random.uniform", lambda low, high: high)
        with pytest.raises(asyncio.CancelledError):
            await sync.run()

    asyncio.run(run())
    assert len(calls) == 6
    assert intervals == [sync.config.interval_s] * 4 + [0.05, sync.config.interval_s]
    state = sync.status()
    assert state["pending_events"] == state["conflicted_events"] == 2
    assert state["eligible_events"] == 0 and state["last_event_success_at"] is not None


def test_confirmation_cli_is_offline_locked_and_never_resequences(unconfirmed, tmp_path, monkeypatch, capsys):
    gateway, _, settings = unconfirmed
    config = tmp_path / "gateway.toml"
    contents = Path("config/simulation.toml").read_text().replace('database = "var/data/simulation.sqlite3"',
        f'database = "{settings.database}"')
    contents = contents.replace("[[cages]]", '[cloud]\nenabled=true\nendpoint="https://saas.example.test/sync"\n\n[[cages]]', 1)
    config.write_text(contents)
    proof = tmp_path / "evidence.json"
    proof.write_text(json.dumps(evidence(gateway.store)))
    monkeypatch.setattr("sys.argv", ["habitat_gateway", "--config", str(config), "--confirm-cloud-continuity", str(proof)])
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: pytest.fail("confirmation must not start devices or API"))
    with pytest.raises(SystemExit) as locked:
        cli.main()
    assert locked.value.code == 2 and "cloud_continuity_database_in_use" in capsys.readouterr().err
    queue_rejected(gateway)
    before = gateway.store.cloud_batch(100)
    gateway.store.close()
    try:
        cli.main()
        reply = json.loads(capsys.readouterr().out)
        assert reply["events_resequenced"] == reply["events_deleted"] == 0
        assert reply["continuity"]["status"] == "confirmed"
    finally:
        gateway.store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id))
    assert gateway.store.cloud_batch(100) == before
