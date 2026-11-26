import httpx
import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from habitat.control.ir_web_client import IRWebClient, IRBridgeError
from habitat_gateway.api import create_app
from habitat_gateway.config import CameraIRConfig
from habitat_gateway.camera_viewer import CONTROL_COOKIE

VIEW = "read-only-camera-key-for-contract-test-0001"
CONTROL = "separate-camera-control-key-for-test-0001"
BRIDGE = "private-loopback-bridge-key-for-test-00001"
PATH = "/camera/api/ir/CAGE-001"


def state(cage="CAGE-001"):
    return dict(cage_id=cage, configured=True, status="off", online=True,
        outputs_locked=False, gpio_requested_on=False, actual_ir_on=None,
        active=False, remaining_s=0, max_on_seconds=900, error=None)


@pytest.fixture
def camera_ir(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_CAMERA_VIEWER_TOKEN", VIEW)
    monkeypatch.setenv("HABITAT_CAMERA_CONTROL_TOKEN", CONTROL)
    monkeypatch.setenv("HABITAT_IR_BRIDGE_TOKEN", BRIDGE)
    calls = []

    def respond(request):
        assert request.headers["Authorization"] == "Bearer " + BRIDGE
        calls.append(request)
        return httpx.Response(202 if request.method == "POST" else 200, json=state())

    bridge = IRWebClient("http://127.0.0.1:8093", BRIDGE, transport=httpx.MockTransport(respond))
    monkeypatch.setattr("habitat_gateway.camera_viewer.IRWebClient", lambda *args: bridge)
    settings.camera_ir = CameraIRConfig(enabled=True, cage_ids=["CAGE-001"])
    with TestClient(create_app(settings, run_worker=False), base_url="https://camera.test") as client:
        yield client, calls


def login(client, key=CONTROL):
    assert client.post("/camera/session", headers={"Authorization": "Bearer " + key}).status_code == 200
    return client.get("/camera/control/session").json()


def test_readonly_key_never_authorizes_ir(camera_ir):
    client, calls = camera_ir
    assert client.get(PATH).status_code == 401
    assert login(client, VIEW) == {"can_control": False, "csrf_token": None}
    assert client.get(PATH).status_code == 200
    assert client.post(PATH, json={"action": "on"}).status_code == 403
    assert [call.method for call in calls] == ["GET"]


def test_control_requires_separate_cookie_and_csrf_and_same_origin(camera_ir):
    client, calls = camera_ir
    session = login(client)
    assert session["can_control"]
    cookie = client.cookies.get(CONTROL_COOKIE)
    assert CONTROL not in cookie and BRIDGE not in cookie
    assert client.post(PATH, json={"action": "on"}).status_code == 403
    headers = {"X-Habitat-CSRF": session["csrf_token"], "Origin": "https://evil.test"}
    assert client.post(PATH, json={"action": "on"}, headers=headers).status_code == 403
    headers["Origin"] = "https://camera.test"
    response = client.post(PATH, json={"action": "on", "seconds": 10}, headers=headers)
    assert response.status_code == 202
    assert response.json()["actual_ir_on"] is None
    assert client.post(PATH, json={"action": "off"}, headers=headers).status_code == 202
    assert len(calls) == 2
    for secret in (VIEW, CONTROL, BRIDGE):
        assert secret not in response.text


@pytest.mark.parametrize("seconds", [None, 10, 900])
def test_continuous_and_timed_intent_reaches_worker(camera_ir, seconds):
    client, calls = camera_ir
    session = login(client)
    response = client.post(PATH, json={"action": "on", "seconds": seconds},
        headers={"X-Habitat-CSRF": session["csrf_token"]})
    assert response.status_code == 202
    assert json.loads(calls[-1].content) == {"action": "on", "seconds": seconds}


def test_omitted_timer_defaults_to_continuous(camera_ir):
    client, calls = camera_ir
    session = login(client)
    assert client.post(PATH, json={"action": "on"},
        headers={"X-Habitat-CSRF": session["csrf_token"]}).status_code == 202
    assert json.loads(calls[-1].content)["seconds"] is None


def test_bridge_continuous_status_preserves_absent_deadline():
    data = {**state(), "status": "on", "active": True, "gpio_requested_on": True,
            "mode": "continuous", "remaining_s": None}
    bridge = IRWebClient("http://127.0.0.1:8093", BRIDGE, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=data)))
    try:
        result = bridge.request("CAGE-001")
        assert result["mode"] == "continuous" and result["remaining_s"] is None
    finally:
        bridge.close()


def test_downgrade_logout_forgery_and_old_csrf_revoke_control(camera_ir):
    client, calls = camera_ir
    old = login(client)["csrf_token"]
    login(client)
    assert client.post(PATH, json={"action": "on"}, headers={"X-Habitat-CSRF": old}).status_code == 403
    login(client, VIEW)
    assert not client.cookies.get(CONTROL_COOKIE)
    assert client.post(PATH, json={"action": "off"}, headers={"X-Habitat-CSRF": old}).status_code == 403
    login(client)
    client.cookies.set(CONTROL_COOKIE, "forged", domain="camera.test", path="/camera")
    assert not client.get("/camera/control/session").json()["can_control"]
    login(client)
    client.delete("/camera/session")
    assert not client.cookies.get(CONTROL_COOKIE)
    assert client.post(PATH, json={"action": "off"}).status_code == 401
    assert calls == []


@pytest.mark.parametrize("body", [{"action": "on", "seconds": value} for value in (0, 901, True, "10", 1.2)] +
                         [{"action": "toggle"}, {"action": "on", "topic": "other"}])
def test_invalid_commands_never_reach_bridge(camera_ir, body):
    client, calls = camera_ir
    session = login(client)
    assert client.post(PATH, json=body, headers={"X-Habitat-CSRF": session["csrf_token"]}).status_code == 422
    assert calls == []


def test_disabled_and_unknown_cages_never_control(settings, monkeypatch):
    monkeypatch.setenv("HABITAT_CAMERA_VIEWER_TOKEN", VIEW)
    monkeypatch.setenv("HABITAT_CAMERA_CONTROL_TOKEN", CONTROL)
    with TestClient(create_app(settings, run_worker=False), base_url="https://camera.test") as client:
        session = login(client)
        assert client.get(PATH).json()["configured"] is False
        assert client.post(PATH, json={"action": "on"}, headers={"X-Habitat-CSRF": session["csrf_token"]}).status_code == 409
        assert client.get("/camera/api/ir/UNKNOWN").status_code == 404


@pytest.mark.parametrize("response", [httpx.Response(200, json=state("WRONG")),
    httpx.Response(200, json={**state(), "actual_ir_on": True}),
    httpx.Response(302, headers={"Location": "http://remote.test"}),
    httpx.Response(500, json={"detail": "secret-password"})])
def test_bridge_failure_and_wrong_identity_fail_closed(response):
    with pytest.raises(IRBridgeError, match="ir_bridge_unavailable"):
        with httpx.MockTransport(lambda request: response) as transport:
            bridge = IRWebClient("http://127.0.0.1:8093", BRIDGE, transport=transport)
            try:
                bridge.request("CAGE-001")
            finally:
                bridge.close()


def test_bridge_sanitizes_unknown_fields_and_error_text():
    bridge = IRWebClient("http://127.0.0.1:8093", BRIDGE, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={**state(), "error": "private-details", "password": "secret"})))
    try:
        result = bridge.request("CAGE-001")
        assert result["error"] == "controller_error"
        assert "password" not in result
    finally:
        bridge.close()


@pytest.mark.parametrize("endpoint", ["http://10.0.0.1:8093", "https://127.0.0.1:8093",
    "http://user:pass@127.0.0.1:8093", "http://127.0.0.1:8093/other", "http://localhost:8093",
    "http://127.0.0.1:8093?token=x", "http://127.0.0.1:8093#x"])
def test_only_loopback_bridge_configuration(endpoint):
    with pytest.raises(ValidationError):
        CameraIRConfig(enabled=True, endpoint=endpoint, cage_ids=["CAGE-001"])


def test_unknown_or_duplicate_ir_cages_rejected(settings):
    for cages in (["UNKNOWN"], ["CAGE-001", "CAGE-001"], []):
        with pytest.raises(ValidationError):
            type(settings).model_validate({**settings.model_dump(), "camera_ir": {"enabled": True, "cage_ids": cages}})
