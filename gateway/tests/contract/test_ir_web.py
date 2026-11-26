"""Loopback bridge HTTP/configuration contract; no MQTT or physical outputs."""
import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from apps.worker import ir_web
from habitat.control.ir import ControlError
from habitat.control.ir_web import IRService, RequestError

TOKEN = "loopback-test-token-with-at-least-32-characters"
STATE = {"cage_id": "CAGE-TEST", "configured": True, "status": "off", "online": True,
         "outputs_locked": False, "gpio_requested_on": False, "actual_ir_on": None,
         "active": False, "mode": None, "remaining_s": 0, "max_on_seconds": 900, "error": None}


@pytest.fixture
def client():
    node = Mock()
    node.config.cage_id = "CAGE-TEST"
    node.status.return_value = STATE.copy()
    node.request.return_value = {**STATE, "status": "starting", "active": True, "mode": "continuous", "remaining_s": None}
    service = IRService("SITE-TEST", "GATEWAY-TEST", [node])
    with TestClient(ir_web.create_app(service, TOKEN, run_worker=False)) as http:
        yield http, node


def headers():
    return {"Authorization": "Bearer " + TOKEN}


def test_bridge_bearer_required_and_never_returned(client):
    http, node = client
    health = http.get("/health")
    assert health.json() == {"status": "ok", "site_id": "SITE-TEST", "gateway_id": "GATEWAY-TEST",
                             "configured_cages": ["CAGE-TEST"]}
    for supplied in ({}, {"Authorization": "Bearer wrong"}, {"Cookie": "token=" + TOKEN},
                     {"Authorization": "Basic " + TOKEN}):
        assert http.get("/v1/ir/CAGE-TEST", headers=supplied).status_code == 401
        assert http.post("/v1/ir/CAGE-TEST", headers=supplied, json={"action": "on"}).status_code == 401
    assert http.get("/v1/ir/CAGE-TEST?token=" + TOKEN).status_code == 401
    node.request.assert_not_called()
    response = http.get("/v1/ir/CAGE-TEST", headers=headers())
    assert response.json() == STATE
    assert response.headers["Cache-Control"] == "no-store"
    assert TOKEN not in response.text + health.text
    assert http.get("/docs").status_code == 404


def test_commands_are_accepted_without_claiming_light_is_on(client):
    http, node = client
    response = http.post("/v1/ir/CAGE-TEST", headers=headers(), json={"action": "on"})
    assert response.status_code == 202
    assert response.json()["actual_ir_on"] is None
    assert response.json()["mode"] == "continuous"
    assert response.json()["remaining_s"] is None
    node.request.assert_called_with("on", None)
    response = http.post("/v1/ir/CAGE-TEST", headers=headers(), json={"action": "on", "seconds": None})
    assert response.status_code == 202
    node.request.assert_called_with("on", None)
    response = http.post("/v1/ir/CAGE-TEST", headers=headers(), json={"action": "on", "seconds": 300})
    assert response.status_code == 202
    node.request.assert_called_with("on", 300)
    response = http.post("/v1/ir/CAGE-TEST", headers=headers(), json={"action": "off"})
    assert response.status_code == 202
    node.request.assert_called_with("off", None)


@pytest.mark.parametrize("payload", [
    {"action": "toggle"}, {"action": "on", "seconds": 0}, {"action": "on", "seconds": 901},
    {"action": "on", "seconds": True}, {"action": "on", "seconds": "3"},
    {"action": "on", "seconds": 1.1}, {"action": "on", "topic": "another/cage"},
    {},
])
def test_invalid_command_has_no_side_effect(client, payload):
    http, node = client
    assert http.post("/v1/ir/CAGE-TEST", headers=headers(), json=payload).status_code == 422
    node.request.assert_not_called()


def test_only_configured_cages_and_machine_error_codes_are_exposed(client):
    http, node = client
    assert http.get("/v1/ir/OTHER", headers=headers()).status_code == 404
    assert http.post("/v1/ir/OTHER", headers=headers(), json={"action": "off"}).status_code == 404
    node.request.side_effect = RequestError("outputs_locked", 409)
    response = http.post("/v1/ir/CAGE-TEST", headers=headers(), json={"action": "on"})
    assert response.status_code == 409
    assert response.json() == {"detail": "outputs_locked"}


@pytest.fixture
def settings_file(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("mock CA path validated only; no network")
    config = tmp_path / "ir.json"
    config.write_text(json.dumps({"broker_host": "mqtt.test", "broker_port": 8883, "ca_file": str(ca),
        "topic_base": "habitat/v1/SITE-TEST/cages/CAGE-TEST/nodes/NODE-TEST",
        "username_env": "TEST_IR_USER", "password_env": "TEST_IR_PASSWORD"}))
    env = tmp_path / "ir.env"
    env.write_text("TEST_IR_USER=test\nTEST_IR_PASSWORD=fake-password-not-for-network\n")
    env.chmod(0o600)
    path = tmp_path / "web.json"
    data = {"site_id": "SITE-TEST", "gateway_id": "GATEWAY-TEST", "max_on_seconds": 900,
            "nodes": [{"cage_id": "CAGE-TEST", "node_id": "NODE-TEST", "config_path": str(config), "env_path": str(env)}]}
    path.write_text(json.dumps(data))
    return path, data


def test_service_load_validates_private_config_and_keeps_secrets_out_of_repr(settings_file):
    path, data = settings_file
    service = ir_web.load_service(path, environ={})
    node = service.node("CAGE-TEST")
    assert node.config.environment["TEST_IR_USER"] == "test"
    assert "fake-password" not in repr(node.config)
    assert node._observer is None  # Loading/checking configuration opens no connections.


@pytest.mark.parametrize("mutation", ["topic", "duplicate", "maximum", "relative", "unexpected", "boolean"])
def test_bad_config_cannot_target_different_cage_or_bypass_limit(settings_file, mutation):
    path, data = settings_file
    if mutation == "topic":
        data["site_id"] = "OTHER-SITE"
    elif mutation == "duplicate":
        data["nodes"] *= 2
    elif mutation == "maximum":
        data["max_on_seconds"] = 901
    elif mutation == "boolean":
        data["max_on_seconds"] = True
    elif mutation == "relative":
        data["nodes"][0]["env_path"] = "secrets.env"
    else:
        data["nodes"][0]["topic_base"] = "other"
    path.write_text(json.dumps(data))
    with pytest.raises(ControlError):
        ir_web.load_service(path, environ={})


def test_public_credential_file_is_rejected(settings_file):
    path, data = settings_file
    from pathlib import Path
    Path(data["nodes"][0]["env_path"]).chmod(0o644)
    with pytest.raises(ControlError, match="private"):
        ir_web.load_service(path, environ={})


@pytest.mark.parametrize("token", ["", "x" * 31, "x" * 32 + "\n"])
def test_short_or_whitespace_bridge_key_fails_closed(token):
    with pytest.raises(ControlError):
        ir_web.create_app(IRService("SITE", "GW", []), token)


def test_entrypoint_cannot_bind_non_loopback_and_check_does_not_start_worker(settings_file, monkeypatch, capsys):
    path, _ = settings_file
    monkeypatch.setenv("HABITAT_IR_BRIDGE_TOKEN", TOKEN)
    assert ir_web.main(["--config", str(path), "--check-config"]) == 0
    assert "configured_cages" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        ir_web.main(["--config", str(path), "--host", "0.0.0.0"])
    assert error.value.code == 2
    import uvicorn
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    assert ir_web.main(["--config", str(path), "--port", "18193"]) == 0
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 18193
    assert run.call_args.kwargs["workers"] == 1
