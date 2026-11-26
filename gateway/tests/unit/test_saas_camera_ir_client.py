"""SaaS session boundary tests; no real network, broker or physical IR output."""
import json

import httpx
import pytest

from habitat.saas.camera_ir import CameraIRClient, CameraIRError


KEY = "test-camera-key-" + "k" * 32
CSRF = "a" * 64
SESSION = "80c84781-0ff9-4d0c-b532-c0eb062c7c35"
TS = bytes([0x47]) + bytes(187)
PLAYLIST = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n"
            "#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:12\n"
            "#EXT-X-PROGRAM-DATE-TIME:2026-11-10T10:00:00+00:00\n"
            f"#EXTINF:2.000000,\n{SESSION}/12.ts\n")


def state(**overrides):
    return {"cage_id": "CAGE-001", "configured": True, "status": "off",
            "online": True, "outputs_locked": False, "gpio_requested_on": False,
            "actual_ir_on": None, "active": False, "mode": None,
            "remaining_s": 0, "max_on_seconds": 900, "error": None, **overrides}


def camera(camera_id="RGB-001", cage_id="CAGE-001"):
    return {"id": camera_id, "cage_id": cage_id, "source_type": "http_mjpeg",
            "view": "top", "width": 800, "height": 640, "configured_fps": 8,
            "live_stream": True, "status": "live", "fresh": True, "age_s": 2.4,
            "last_segment_at": "2026-11-10T10:00:00+00:00"}


class Gateway:
    def __init__(self):
        self.requests = []
        self.hook = lambda request: None
        self.control = True
        self.catalogue = {"site_id": "STORE-001", "gateway_id": "PI-001",
                          "cage_ids": ["CAGE-001", "CAGE-002"],
                          "cameras": [camera(), camera("OTHER", "CAGE-002")]}

    def __call__(self, request):
        self.requests.append(request)
        override = self.hook(request)
        if override is not None:
            return override
        path = request.url.path
        if path == "/camera/session":
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Bearer " + KEY
            return httpx.Response(200, json={"expires_in": 43200}, headers=[
                ("Set-Cookie", "habitat_camera_session=viewer-test-cookie; Path=/camera; Secure; HttpOnly"),
                ("Set-Cookie", "habitat_camera_control_session=control-test-cookie; Path=/camera; Secure; HttpOnly")])
        assert "Authorization" not in request.headers
        assert "viewer-test-cookie" in request.headers["Cookie"]
        if path == "/camera/api/cameras":
            return httpx.Response(200, json=self.catalogue)
        if path == "/camera/control/session":
            return httpx.Response(200, json={"can_control": self.control,
                                           "csrf_token": CSRF if self.control else None})
        if path == "/camera/api/ir/CAGE-001":
            if request.method == "POST":
                assert request.headers["X-Habitat-CSRF"] == CSRF
                assert "Origin" not in request.headers
                command = json.loads(request.content)
                on = command["action"] == "on"
                seconds = command.get("seconds")
                return httpx.Response(202, json=state(status="starting" if on else "off", active=on,
                    mode=("continuous" if seconds is None else "timed") if on else None,
                    remaining_s=seconds if on else 0))
            return httpx.Response(200, json=state())
        if path == "/camera/hls/RGB-001/index.m3u8":
            return httpx.Response(200, text=PLAYLIST)
        if path == f"/camera/hls/RGB-001/{SESSION}/12.ts":
            return httpx.Response(200, content=TS)
        raise AssertionError("unexpected test route")

    def count(self, method, path):
        return sum(r.method == method and r.url.path == path for r in self.requests)


@pytest.fixture
def gateway():
    return Gateway()


def client(gateway, **overrides):
    config = dict(base_url="https://gateway.example", key=KEY, site_id="STORE-001",
                  gateway_id="PI-001", cage_ids=["CAGE-001"],
                  camera_ids={"RGB-001": "CAGE-001"}, transport=httpx.MockTransport(gateway))
    return CameraIRClient(**(config | overrides))


def test_login_inventory_scope_and_secret_isolation(gateway):
    with client(gateway) as api:
        inventory = api.inventory()
        assert inventory["cage_ids"] == ["CAGE-001"]
        assert [c["id"] for c in inventory["cameras"]] == ["RGB-001"]
        assert api.ir_status("CAGE-001")["actual_ir_on"] is None
        assert KEY not in repr(api)
        assert api._http.follow_redirects is False
        assert api._http.trust_env is False
    assert gateway.count("DELETE", "/camera/session") == 0
    assert gateway.count("POST", "/camera/api/ir/CAGE-001") == 0


def test_h264_camera_migration_keeps_existing_session_media_and_ir_scope(gateway):
    gateway.catalogue["cameras"][0].update(source_type="rtsp_h264", width=800, height=800,
                                         configured_fps=20)
    with client(gateway) as api:
        row = api.inventory()["cameras"][0]
        assert (row["id"], row["source_type"], row["height"]) == ("RGB-001", "rtsp_h264", 800)
        assert api.playlist("RGB-001") == PLAYLIST
        assert api.segment("RGB-001", SESSION, 12) == TS
        assert api.ir_status("CAGE-001")["status"] == "off"
    assert gateway.count("POST", "/camera/api/ir/CAGE-001") == 0


@pytest.mark.parametrize("action,seconds,mode", [("on", None, "continuous"), ("on", 10, "timed"), ("off", None, None)])
def test_command_once_with_csrf_and_no_physical_success_claim(gateway, action, seconds, mode):
    with client(gateway) as api:
        result = api.command_ir("CAGE-001", action, seconds)
        assert result["mode"] == mode
        assert result["actual_ir_on"] is None
    assert gateway.count("POST", "/camera/api/ir/CAGE-001") == 1
    assert gateway.count("POST", "/camera/session") == 1
    command = next(r for r in gateway.requests if r.url.path == "/camera/api/ir/CAGE-001")
    assert ("seconds" in json.loads(command.content)) == (seconds is not None)


def test_viewer_cannot_send_command(gateway):
    gateway.control = False
    with client(gateway) as api, pytest.raises(CameraIRError, match="camera_control_required"):
        api.command_ir("CAGE-001", "on")
    assert gateway.count("POST", "/camera/api/ir/CAGE-001") == 0


def test_safe_get_refreshes_once(gateway):
    def hook(request):
        if request.url.path == "/camera/api/ir/CAGE-001" and gateway.count("GET", request.url.path) == 1:
            return httpx.Response(401, json={"detail": "camera_login_required"})
    gateway.hook = hook
    with client(gateway) as api:
        assert api.ir_status("CAGE-001")["status"] == "off"
    assert gateway.count("POST", "/camera/session") == 2
    assert gateway.count("GET", "/camera/api/ir/CAGE-001") == 2


def test_safe_get_does_not_loop_after_second_401(gateway):
    gateway.hook = lambda r: httpx.Response(401) if r.url.path == "/camera/api/ir/CAGE-001" else None
    with client(gateway) as api, pytest.raises(CameraIRError):
        api.ir_status("CAGE-001")
    assert gateway.count("POST", "/camera/session") == 2
    assert gateway.count("GET", "/camera/api/ir/CAGE-001") == 2


@pytest.mark.parametrize("failure,unknown", [(401, False), (403, False), (422, False), (500, True), ("timeout", True), ("bad_json", True)])
def test_command_never_replayed_and_error_has_no_secrets(gateway, failure, unknown):
    def hook(request):
        if request.method == "POST" and request.url.path == "/camera/api/ir/CAGE-001":
            if failure == "timeout":
                raise httpx.ReadTimeout(KEY + CSRF, request=request)
            if failure == "bad_json":
                return httpx.Response(202, content=(KEY + CSRF).encode())
            return httpx.Response(failure, json={"detail": KEY + CSRF})
    gateway.hook = hook
    with client(gateway) as api, pytest.raises(CameraIRError) as caught:
        api.command_ir("CAGE-001", "on")
    error = caught.value
    assert error.outcome_unknown is unknown
    assert KEY not in str(error) + repr(error) + repr(vars(error))
    assert CSRF not in str(error) + repr(error) + repr(vars(error))
    assert gateway.count("POST", "/camera/api/ir/CAGE-001") == 1
    assert gateway.count("POST", "/camera/session") == 1


@pytest.mark.parametrize("field,value", [("site_id", "OTHER"), ("gateway_id", "OTHER"), ("cage_ids", []), ("cameras", [])])
def test_login_rejects_wrong_gateway_or_missing_scope(gateway, field, value):
    gateway.catalogue[field] = value
    api = client(gateway)
    with pytest.raises(CameraIRError):
        api.login()
    assert not api._authenticated
    assert not list(api._http.cookies.jar)
    api.close()


def test_login_rejects_camera_moved_to_another_cage(gateway):
    gateway.catalogue["cameras"][0]["cage_id"] = "CAGE-002"
    with pytest.raises(CameraIRError, match="camera_mapping_mismatch"):
        with client(gateway):
            pass


@pytest.mark.parametrize("url", ["http://gateway.example", "http://192.168.1.2", "https://user:pass@host", "https://host/path", "https://host?x=y", "https://host/#secret", "https://host:0", "file:///tmp/a", "https://host/\n", "https://[", None])
def test_origin_restrictions(gateway, url):
    with pytest.raises(ValueError):
        client(gateway, base_url=url, allow_loopback_http=True)
    assert not gateway.requests


def test_http_loopback_requires_explicit_opt_in(gateway):
    with pytest.raises(ValueError):
        client(gateway, base_url="http://127.0.0.1:8000")
    api = client(gateway, base_url="http://127.0.0.1:8000", allow_loopback_http=True)
    api.close()


@pytest.mark.parametrize("identifier", ["CAGE-002", "../other", "x/y", "x?secret", "x%2fy", "", "x\\y", "x\n"])
def test_scope_and_path_injection_rejected_before_login(gateway, identifier):
    api = client(gateway)
    with pytest.raises(ValueError):
        api.ir_status(identifier)
    with pytest.raises(ValueError):
        api.playlist(identifier)
    assert not gateway.requests
    api.close()


@pytest.mark.parametrize("action,seconds", [("bad", None), ("on", True), ("on", 0), ("on", 901), ("on", 1.1), ("on", "10"), ("off", 10)])
def test_invalid_command_fails_before_login(gateway, action, seconds):
    api = client(gateway)
    with pytest.raises(ValueError):
        api.command_ir("CAGE-001", action, seconds)
    assert not gateway.requests
    api.close()


def test_hls_relative_paths_and_mpeg_ts(gateway):
    with client(gateway) as api:
        assert api.playlist("RGB-001") == PLAYLIST
        assert api.segment("RGB-001", SESSION, 12) == TS


@pytest.mark.parametrize("line", ["https://attacker.example/x.ts", "//attacker/x.ts", "../x.ts", f"{SESSION}/012.ts", f"{SESSION}/9007199254740992.ts", '#EXT-X-KEY:METHOD=AES-128,URI="https://attacker/key"', '#EXT-X-MAP:URI="private"'])
def test_playlist_rejects_arbitrary_urls_and_unsupported_uri_tags(gateway, line):
    gateway.hook = lambda r: httpx.Response(200, text=PLAYLIST + line + "\n") if r.url.path.endswith("index.m3u8") else None
    with client(gateway) as api, pytest.raises(CameraIRError, match="invalid_playlist"):
        api.playlist("RGB-001")


@pytest.mark.parametrize("session,sequence", [("../a", 1), (SESSION, -1), (SESSION, True), (SESSION, "12"), (SESSION, 9007199254740992)])
def test_segment_ids_are_validated_before_request(gateway, session, sequence):
    api = client(gateway)
    with pytest.raises(ValueError):
        api.segment("RGB-001", session, sequence)
    assert not gateway.requests
    api.close()


def test_redirect_never_followed(gateway):
    with client(gateway) as api:
        gateway.hook = lambda r: httpx.Response(302, headers={"Location": "https://attacker.example/"})
        before = len(gateway.requests)
        with pytest.raises(CameraIRError, match="unexpected_redirect"):
            api.inventory()
        assert len(gateway.requests) == before + 1


def test_redirect_login_raises_and_closes_context(gateway):
    gateway.hook = lambda r: httpx.Response(302, headers={"Location": "https://attacker.example/"})
    api = client(gateway)
    with pytest.raises(CameraIRError, match="unexpected_redirect"):
        with api:
            pass
    assert api._closed and len(gateway.requests) == 1


def test_bounded_playlist_and_segment_responses(gateway):
    with client(gateway) as api:
        gateway.hook = lambda r: httpx.Response(200, content=b"x" * 16385) if r.url.path.endswith("index.m3u8") else None
        with pytest.raises(CameraIRError, match="response_too_large"):
            api.playlist("RGB-001")
        gateway.hook = lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)) if r.url.path.endswith(".ts") else None
        with pytest.raises(CameraIRError, match="response_too_large"):
            api.segment("RGB-001", SESSION, 12)


def test_unexpected_inventory_fields_and_error_details_are_filtered(gateway):
    gateway.catalogue["private_key"] = KEY
    gateway.catalogue["cameras"][0].update(private_key=KEY, status=KEY)
    with client(gateway) as api:
        assert KEY not in json.dumps(api.inventory())
        gateway.hook = lambda r: httpx.Response(200, json=state(error=KEY, csrf_token=CSRF)) if r.url.path.endswith("/ir/CAGE-001") else None
        result = api.ir_status("CAGE-001")
        assert result["error"] == "controller_error"
        assert KEY not in json.dumps(result) and CSRF not in json.dumps(result)


def test_status_cannot_report_another_cage_or_actual_light(gateway):
    with client(gateway) as api:
        for overrides in ({"cage_id": "CAGE-002"}, {"actual_ir_on": True}, {"remaining_s": float("nan")}):
            gateway.hook = lambda r: httpx.Response(200, json=state(**overrides)) if r.url.path.endswith("/ir/CAGE-001") else None
            if "remaining_s" in overrides:
                gateway.hook = lambda r: httpx.Response(200, content=json.dumps(state(**overrides))) if r.url.path.endswith("/ir/CAGE-001") else None
            with pytest.raises(CameraIRError, match="invalid_response"):
                api.ir_status("CAGE-001")


def test_closed_client_cannot_login_and_does_not_send_off(gateway):
    api = client(gateway)
    api.login()
    api.command_ir("CAGE-001", "on")
    before = len(gateway.requests)
    api.close()
    api.close()
    with pytest.raises(CameraIRError, match="client_closed"):
        api.inventory()
    assert len(gateway.requests) == before
