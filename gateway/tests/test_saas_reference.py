import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from habitat_gateway.cloud import CloudSync, run_heartbeat
from habitat_gateway.config import CloudConfig
from habitat_gateway.gateway import Gateway
from habitat_gateway.models import CommandRequest
from habitat_gateway.saas_reference import Registration, create_receiver
from habitat_gateway.sync_contract import SYNC_PATH, SyncRequest
from habitat_gateway.transport import SimulatedTransport
from habitat_gateway import saas_reference
from tests.conftest import confirm_empty_cloud

TOKEN = "test-only-reference-token-at-least-32-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def registration(**updates):
    return Registration.model_validate({"site_id": "STORE-001", "gateway_id": "PI-001",
        "cage_ids": ["CAGE-001"], "token_env": "TEST_TOKEN", "allow_simulation": True, **updates})


@pytest.fixture
def wire(settings):
    settings = settings.model_copy(update={"cloud": CloudConfig(enabled=True,
        endpoint=f"https://habitatos.kro.kr{SYNC_PATH}")})
    transport = SimulatedTransport(settings)
    gateway = Gateway(settings, transport)
    transport.start(gateway)
    gateway.send_command("CAGE-001", CommandRequest(
        request_id=uuid4(), actuator_id="light", action="on", duration_s=5,
    ))
    transport.step()
    confirm_empty_cloud(gateway.store)
    sync = CloudSync(gateway, TOKEN)
    yield sync._prepare(), sync
    gateway.store.close()


def receiver(database=":memory:", **kwargs):
    return create_receiver(database, [registration()], environ={"TEST_TOKEN": TOKEN}, **kwargs)


def test_real_sender_contract_and_receiver_roundtrip(wire, tmp_path):
    payload, sync = wire
    SyncRequest.model_validate(payload)
    app = receiver(tmp_path / "receiver.sqlite3")
    before = sync.gateway.store.cloud_backlog()["pending_events"]

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            assert await sync.send_once(client)

    with TestClient(app):
        asyncio.run(send())
        assert sync.gateway.store.cloud_backlog()["pending_events"] == 0
        assert app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == before


@pytest.mark.parametrize("transport", ["simulated", "mqtt"])
def test_heartbeat_preserves_v1_contract_without_opening_device_database(settings, tmp_path, monkeypatch, transport):
    database = tmp_path / "existing-gateway.sqlite3"
    sentinel = b"Existing runtime data must not be opened, reset, or changed."
    database.write_bytes(sentinel)
    settings = settings.model_copy(update={"transport": transport, "database": str(database),
        "cloud": CloudConfig(enabled=True, endpoint="https://saas.example.test/v1/edge/sync")})
    app = create_receiver(
        ":memory:", [registration(allow_simulation=transport == "simulated")], environ={"TEST_TOKEN": TOKEN})

    async def one_heartbeat(sync):
        payload = sync._prepare()
        SyncRequest.model_validate(payload)
        assert payload["events"] == []
        assert payload["gateway"]["healthy"] is True
        assert payload["gateway"]["transport"] == transport
        for cage in payload["gateway"]["cages"]:
            assert cage["state"]["telemetry"] is None
            assert cage["state"]["transport_connected"] is False
            assert all(a["observed"] is None and a["on_blocked_reason"] == "missing_telemetry"
                       for a in cage["state"]["actuators"].values())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            assert await sync.send_once(client)
        assert sync.status()["pending_events"] == 0

    monkeypatch.setattr(CloudSync, "run", one_heartbeat)
    with TestClient(app):
        asyncio.run(run_heartbeat(settings, TOKEN))
        assert app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0
        assert app.state.db.execute("SELECT COUNT(*) FROM edge_gateways").fetchone()[0] == 1
    assert database.read_bytes() == sentinel
    assert not database.with_name(database.name + ".lock").exists()


def test_duplicate_reordered_json_and_restart_preserve_ack(wire, tmp_path):
    payload, _ = wire
    database = tmp_path / "receiver.sqlite3"
    with TestClient(receiver(database)) as client:
        first = client.post(SYNC_PATH, json=payload, headers=HEADERS)
        assert first.status_code == 200
    with TestClient(receiver(database)) as client:
        again = client.post(SYNC_PATH, content=json.dumps(payload, sort_keys=True),
                            headers={**HEADERS, "Content-Type": "application/json"})
        assert again.json() == first.json()
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == len(payload["events"])
        for row in client.app.state.db.execute("SELECT body FROM edge_events WHERE kind='command.updated'"):
            assert not {"r15", "execution_status", "actual_state"} & json.loads(row[0])["payload"].keys()


@pytest.mark.parametrize("status", ["requested", "execution_unverified"])
@pytest.mark.parametrize("hold_ms", [2000, 5000])
def test_r15_request_metadata_roundtrip_preserves_unknown_physical_state(wire, status, hold_ms):
    payload, _ = wire
    event = deepcopy(next(e for e in payload["events"] if e["kind"] == "command.updated"))
    command = event["payload"]
    command.update(status=status, actuator_id="mister", duration_s=hold_ms / 1000,
                   execution_status="unverified", actual_state=None)
    command["request"].update(actuator_id="mister", duration_s=hold_ms / 1000)
    command.pop("applied_at", None)
    session = str(uuid4())
    issued = int(SyncRequest.model_validate(payload).sent_at.timestamp() * 1000)
    command["r15"] = {"session_id": session, "sequence": 1, "zone": 1, "action": "on",
        "request_hold_ms": hold_ms,
        "payload": f"R15/1 {session} {command['command_id']} 1 1 on {hold_ms} {issued} {issued + 5000}"}
    payload["events"] = [event]
    payload["gateway"]["cages"][0]["state"]["actuators"]["mister"]["observed"] = None
    with TestClient(receiver()) as client:
        response = client.post(SYNC_PATH, json=payload, headers=HEADERS)
        assert response.status_code == 200
        stored = json.loads(client.app.state.db.execute("SELECT body FROM edge_events").fetchone()[0])["payload"]
        assert stored["status"] == status and stored["r15"] == command["r15"]
        assert stored["execution_status"] == "unverified" and stored["actual_state"] is None
        assert stored["applied_at"] is None
        snapshot = json.loads(client.app.state.db.execute("SELECT body FROM edge_gateways").fetchone()[0])
        assert snapshot["cages"][0]["state"]["actuators"]["mister"]["observed"] is None
        assert client.post(SYNC_PATH, json=payload, headers=HEADERS).json() == response.json()

        # An unknown GPIO execution cannot be upgraded to a measured state or applied ACK.
        for update in ({"actual_state": True}, {"actual_state": False}, {"status": "applied"},
                       {"applied_at": payload["sent_at"]}):
            invalid = deepcopy(payload)
            invalid["events"][0]["payload"].update(update)
            assert client.post(SYNC_PATH, json=invalid, headers=HEADERS).status_code == 422
        for invalid_hold in (5001, "5000"):
            invalid = deepcopy(payload)
            invalid["events"][0]["payload"]["r15"]["request_hold_ms"] = invalid_hold
            assert client.post(SYNC_PATH, json=invalid, headers=HEADERS).status_code == 422
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["missing_token", "wrong_token", "other_site", "other_gateway", "other_cage"])
def test_auth_and_scope_do_not_persist(wire, mutation):
    payload, _ = wire
    headers = HEADERS
    if mutation == "missing_token":
        headers = {}
    elif mutation == "wrong_token":
        headers = {"Authorization": "Bearer incorrect"}
    elif mutation in ("other_site", "other_gateway"):
        key = "site_id" if mutation == "other_site" else "gateway_id"
        payload[key] = "OTHER"
        for event in payload["events"]:
            event[key] = "OTHER"
            if event["kind"] == "command.updated":
                event["payload"][key] = "OTHER"
    else:
        payload = json.loads(json.dumps(payload).replace("CAGE-001", "CAGE-OTHER"))
    with TestClient(receiver()) as client:
        result = client.post(SYNC_PATH, json=payload, headers=headers)
        assert result.status_code == (401 if "token" in mutation else 403)
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["missing_timestamp_zone", "mixed_event_site", "mixed_command_cage", "wrong_kind", "duplicate_id", "reversed_sequence", "bad_sensor_value"])
def test_invalid_contract_returns_422_without_ack(wire, mutation):
    payload, _ = wire
    if mutation == "missing_timestamp_zone":
        payload["sent_at"] = "2026-09-18T12:00:00"
    elif mutation == "mixed_event_site":
        payload["events"][0]["site_id"] = "OTHER"
    elif mutation == "mixed_command_cage":
        next(e for e in payload["events"] if e["kind"] == "command.updated")["payload"]["cage_id"] = "OTHER"
    elif mutation == "wrong_kind":
        payload["events"][0]["kind"] = "camera.frame"
    elif mutation == "duplicate_id":
        payload["events"][1]["event_id"] = payload["events"][0]["event_id"]
    elif mutation == "reversed_sequence":
        payload["events"].reverse()
    else:
        payload["events"][0]["payload"]["readings"]["T1"] = {"quality": "valid", "value": None}
    with TestClient(receiver()) as client:
        assert client.post(SYNC_PATH, json=payload, headers=HEADERS).status_code == 422
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0


@pytest.mark.parametrize("conflict", ["event_id", "sequence"])
def test_conflicting_batch_rolls_back_new_events(wire, conflict):
    payload, _ = wire
    with TestClient(receiver()) as client:
        old = {**payload, "events": [payload["events"][-1]]}
        assert client.post(SYNC_PATH, json=old, headers=HEADERS).status_code == 200
        if conflict == "event_id":
            payload["events"][-1]["payload"]["readings"]["T1"]["value"] = 25
        else:
            payload["events"][-1]["event_id"] = str(uuid4())
        response = client.post(SYNC_PATH, json=payload, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "event_conflict"
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 1


def test_database_failure_returns_no_ack_and_rolls_back(wire):
    payload, _ = wire
    with TestClient(receiver()) as client:
        client.app.state.db.execute("""CREATE TRIGGER storage_error BEFORE INSERT ON edge_gateways
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        response = client.post(SYNC_PATH, json=payload, headers=HEADERS)
        assert response.status_code == 503
        assert "accepted_event_ids" not in response.json()
        assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0


def test_empty_heartbeat_does_not_regress_snapshot(wire):
    payload, _ = wire
    with TestClient(receiver()) as client:
        latest = SyncRequest.model_validate(payload)
        latest.sent_at += timedelta(seconds=1)
        assert client.post(SYNC_PATH, json=latest.model_dump(mode="json"), headers=HEADERS).status_code == 200
        payload["events"] = []
        payload["gateway"]["healthy"] = False
        result = client.post(SYNC_PATH, json=payload, headers=HEADERS)
        assert result.status_code == 200 and result.json()["accepted_event_ids"] == []
        snapshot = client.app.state.db.execute("SELECT body FROM edge_gateways").fetchone()[0]
        assert json.loads(snapshot)["healthy"] is True


def test_simulation_is_explicitly_gated(wire):
    payload, _ = wire
    app = create_receiver(":memory:", [registration(allow_simulation=False)], environ={"TEST_TOKEN": TOKEN})
    with TestClient(app) as client:
        assert client.post(SYNC_PATH, json=payload, headers=HEADERS).status_code == 403


def test_oversized_chunked_body_rejected():
    with TestClient(receiver(body_limit=16)) as client:
        result = client.post(SYNC_PATH, content=iter([b"x" * 10, b"x" * 10]),
                             headers={**HEADERS, "Content-Type": "application/json"})
        assert result.status_code == 413


def test_same_cage_cannot_belong_to_two_pis():
    with pytest.raises(ValueError, match="ownership"):
        create_receiver(":memory:", [registration(), registration(gateway_id="PI-002", token_env="OTHER")],
                        environ={"TEST_TOKEN": TOKEN, "OTHER": "another-test-only-token-at-least-32-characters"})


def test_exported_openapi_and_examples_match_runtime_contract():
    app = receiver()
    try:
        exported = json.loads(Path("docs/api/edge-sync.openapi.json").read_text())
        assert exported == app.openapi()
        for name in ("sync-request.json", "heartbeat-request.json"):
            example = SyncRequest.model_validate_json(Path(f"docs/api/{name}").read_text())
            assert example.site_id == "STORE-001"
        assert exported["paths"][SYNC_PATH]["post"]["security"] == [{"PiBearerToken": []}]
    finally:
        app.state.db.close()


@pytest.mark.parametrize("failure,code", [
    ("extra_token", "invalid_reference_configuration"),
    ("malformed_toml", "invalid_reference_configuration"),
    ("invalid_utf8", "invalid_reference_configuration"),
    ("missing_database", "invalid_reference_configuration"),
    ("empty_gateways", "invalid_reference_configuration"),
    ("invalid_port", "invalid_reference_configuration"),
    ("out_of_range_port", "invalid_reference_configuration"),
    ("missing_token", "invalid_reference_credentials"),
    ("invalid_token", "invalid_reference_credentials"),
    ("missing_file", "reference_configuration_unreadable"),
])
def test_reference_cli_rejects_bad_configuration_without_disclosing_secrets(tmp_path, failure, code):
    secret = "synthetic-reference-private-value-never-print"
    database = tmp_path / "receiver.sqlite3"
    config_path = tmp_path / f"{secret}.toml"
    contents = (
        f"database = {json.dumps(str(database))}\n"
        "[[gateways]]\n"
        'site_id = "STORE-001"\ngateway_id = "PI-001"\ncage_ids = ["CAGE-001"]\n'
        f"token_env = {json.dumps(secret)}\n"
    )
    environment = {**os.environ, secret: TOKEN}
    args = []
    if failure == "extra_token":
        contents += f"token = {json.dumps(secret)}\n"
    elif failure == "malformed_toml":
        contents += f"{secret} = 1\n{secret} = 2\n"
    elif failure == "missing_database":
        contents = contents.split("\n", 1)[1]
    elif failure == "empty_gateways":
        contents = f"database = {json.dumps(str(database))}\ngateways = []\n"
    elif failure == "invalid_port":
        args = ["--port", secret]
    elif failure == "out_of_range_port":
        args = ["--port", "65536"]
    elif failure == "missing_token":
        environment.pop(secret)
    elif failure == "invalid_token":
        environment[secret] = f"{secret} with whitespace"
    if failure != "missing_file":
        config_path.write_bytes(contents.encode() + (b"\xff" if failure == "invalid_utf8" else b""))
    result = subprocess.run(
        [sys.executable, "-m", "habitat_gateway.saas_reference", "--config", str(config_path), *args],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 2
    assert code in result.stderr
    assert result.stdout == ""
    assert secret not in result.stderr
    assert TOKEN not in result.stderr
    assert "Traceback" not in result.stderr
    assert not database.exists()


def test_reference_cli_starts_with_valid_configuration(tmp_path, monkeypatch):
    database = tmp_path / "receiver.sqlite3"
    config_path = tmp_path / "receiver.toml"
    config_path.write_text(
        f"database = {json.dumps(str(database))}\n"
        "[[gateways]]\n"
        'site_id = "STORE-001"\ngateway_id = "PI-001"\ncage_ids = ["CAGE-001"]\n'
        'token_env = "TEST_REFERENCE_CLI_TOKEN"\n'
    )
    monkeypatch.setenv("TEST_REFERENCE_CLI_TOKEN", TOKEN)
    monkeypatch.setattr(sys, "argv", ["saas_reference", "--config", str(config_path), "--port", "9100"])
    started = []

    def run(app, **options):
        started.append(options)
        with TestClient(app) as client:
            assert client.get("/v1/edge/health").json() == {"status": "ok"}
            assert app.state.db.execute("SELECT COUNT(*) FROM edge_gateways").fetchone()[0] == 0

    monkeypatch.setattr(saas_reference.uvicorn, "run", run)
    saas_reference.main()
    assert started == [{"host": "127.0.0.1", "port": 9100, "workers": 1}]
    assert database.is_file()
