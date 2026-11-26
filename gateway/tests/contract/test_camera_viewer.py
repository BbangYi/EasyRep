import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import time

from fastapi.testclient import TestClient
import pytest

from habitat_gateway.api import create_app
from habitat_gateway.camera_viewer import COOKIE
from habitat.vision.cameras import CameraConfig, CameraWorker
from habitat.saas.video_contract import MAX_SEGMENT_BYTES
from tests.contract.test_video import source, segment

KEY = "readonly-camera-fixture-with-at-least-32-characters"
API_KEY = "unrelated-control-api-fixture-at-least-32-characters"
PLAYLIST = "/camera/hls/RGB-001/index.m3u8"


@pytest.fixture
def viewer(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("HABITAT_CAMERA_VIEWER_TOKEN", KEY)
    monkeypatch.setenv("HABITAT_API_TOKEN", API_KEY)
    settings = settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3"),
        "cameras": [CameraConfig(id="RGB-001", cage_id="CAGE-001", live_stream=True,
            device="/dev/v4l/by-path/platform-usb-0:1:1.0-video-index0")]})
    item = segment()
    folder = tmp_path / "cameras/live/RGB-001"
    source(folder, item)
    with TestClient(create_app(settings, run_worker=False), base_url="https://camera.test") as client:
        yield client, folder, item


def login(client):
    return client.post("/camera/session", headers={"Authorization": "Bearer " + KEY})


def test_camera_session_is_scoped_and_cannot_control_gateway(viewer):
    client, _, _ = viewer
    assert client.get(PLAYLIST).status_code == 401
    assert client.get("/camera/api/cameras").status_code == 401
    assert client.post("/camera/session", headers={"Authorization": "Bearer " + API_KEY}).status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert all(flag in response.headers["set-cookie"] for flag in ["HttpOnly", "Secure", "SameSite=strict", "Path=/camera"])
    assert KEY not in response.text and API_KEY not in response.text
    assert client.get("/camera/api/cameras").json()["cameras"][0]["id"] == "RGB-001"
    assert client.get("/v1/cages").status_code == 401
    assert client.get("/v1/cages", headers={"Authorization": "Bearer " + KEY}).status_code == 401
    client.delete("/camera/session")
    assert client.get(PLAYLIST).status_code == 401


def test_camera_playlist_and_segment_are_fresh_and_match_actual_bytes(viewer):
    client, _, item = viewer
    login(client)
    response = client.get(PLAYLIST)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    name = [line for line in response.text.splitlines() if line and not line.startswith("#")][0]
    assert name == f"{item.session_id}/{item.sequence}.ts"
    media = client.get("/camera/hls/RGB-001/" + name)
    assert media.content == item.media_bytes()
    assert client.get("/camera/hls/OTHER/index.m3u8").status_code == 404
    assert client.get("/camera/hls/RGB-001/other-session/10.ts").status_code == 404
    assert client.get("/camera/hls/RGB-001/" + str(item.session_id) + "/999.ts").status_code == 404


def test_missing_stale_and_restarted_camera_cannot_replay_old_video(viewer):
    client, folder, old = viewer
    login(client)
    now = time.time()
    os.utime(folder / "index.m3u8", (now - 30, now - 30))
    assert client.get(PLAYLIST).status_code == 503
    new = segment()
    source(folder, new)
    assert client.get(PLAYLIST).status_code == 200
    assert client.get(f"/camera/hls/RGB-001/{old.session_id}/{old.sequence}.ts").status_code == 404
    (folder / "session.json").unlink()
    assert client.get(PLAYLIST).status_code == 503


def test_forged_and_expired_sessions_are_rejected(viewer, monkeypatch):
    client, _, _ = viewer
    login(client)
    original = client.cookies.get(COOKIE)
    client.cookies.clear()
    client.cookies.set(COOKIE, original + "x", domain="camera.test", path="/camera")
    assert client.get(PLAYLIST).status_code == 401
    client.cookies.clear()
    client.cookies.set(COOKIE, original, domain="camera.test", path="/camera")
    later = time.time() + 13 * 3600
    monkeypatch.setattr("habitat_gateway.camera_viewer.time.time", lambda: later)
    assert client.get(PLAYLIST).status_code == 401


def test_page_and_library_have_no_credentials_and_fail_closed_without_key(settings, monkeypatch):
    monkeypatch.delenv("HABITAT_CAMERA_VIEWER_TOKEN", raising=False)
    with TestClient(create_app(settings, run_worker=False)) as client:
        page = client.get("/camera")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert KEY not in page.text and API_KEY not in page.text
        assert client.get("/camera/hls.js").status_code == 200
        assert client.get("/camera/api/cameras").status_code == 503
        assert client.post("/camera/session").status_code == 503


@pytest.fixture(params=["http_mjpeg", "rtsp_h264"])
def paired_viewer(settings, tmp_path, monkeypatch, request):
    monkeypatch.setenv("HABITAT_CAMERA_VIEWER_TOKEN", KEY)
    monkeypatch.setenv("HABITAT_API_TOKEN", API_KEY)
    camera_source = request.param
    def url(host):
        return (f"rtsp://{host}:8554/stream" if camera_source == "rtsp_h264"
                else f"http://{host}:5000/video_feed")
    configurations = [
        CameraConfig(id="CAM-TOP", cage_id="CAGE-001", source_type=camera_source, view="top",
                     url=url("192.168.10.20"), live_stream=True),
        CameraConfig(id="CAM-FRONT", cage_id="CAGE-001", source_type=camera_source, view="front",
                     url=url("192.168.10.21"), live_stream=True),
        CameraConfig(id="CAM-OTHER", cage_id="CAGE-OTHER", source_type=camera_source, view="top",
                     url=url("192.168.10.22"), live_stream=True),
    ]
    other_cage = settings.cages[0].model_copy(update={"id": "CAGE-OTHER", "node_id": "NODE-OTHER"})
    settings = settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3"),
        "cages": [*settings.cages, other_cage], "cameras": configurations})
    captured = {}

    def worker_factory(configs, directory):
        captured["worker"] = CameraWorker(configs, directory)
        worker = captured["worker"]
        monkeypatch.setattr(worker, "status", lambda: {"cameras": {
            config.id: {"reader_running": True, "media_verified": True, **worker.states.get(config.id, {})}
            for config in configs}, "available_usb_ports": []})
        return captured["worker"]

    monkeypatch.setattr("habitat_gateway.api.CameraWorker", worker_factory)
    folders, items = {}, {}
    for index, config in enumerate(configurations, 1):
        data = (b"G" + bytes([index]) * 187) * 3
        item = segment().model_copy(update={"camera_id": config.id, "cage_id": config.cage_id,
            "data_base64": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()})
        folder = tmp_path / "cameras/live" / config.id
        source(folder, item)
        folders[config.id], items[config.id] = folder, item
    with TestClient(create_app(settings, run_worker=False), base_url="https://camera.test") as client:
        login(client)
        yield client, configurations, folders, items, captured["worker"]


def test_two_views_are_grouped_by_cage_and_do_not_expose_source_addresses(paired_viewer):
    client, configs, _, items, _ = paired_viewer
    response = client.get("/camera/api/cameras")
    data = response.json()
    assert data["cage_ids"] == ["CAGE-001", "CAGE-OTHER"]
    pair = [row for row in data["cameras"] if row["cage_id"] == "CAGE-001"]
    assert {row["view"] for row in pair} == {"top", "front"}
    assert all(row["source_type"] == configs[0].source_type and row["fresh"]
               and row["status"] == "live" for row in pair)
    assert all(0 <= row["age_s"] < 15 and row["last_segment_at"] for row in pair)
    assert response.headers["cache-control"] == "no-store"
    assert all(config.url not in response.text for config in configs)
    assert "url" not in pair[0] and "device" not in pair[0]
    assert KEY not in response.text and API_KEY not in response.text
    for config in configs:
        playlist = client.get(f"/camera/hls/{config.id}/index.m3u8")
        assert playlist.status_code == 200
        media_name = playlist.text.splitlines()[-1]
        assert client.get(f"/camera/hls/{config.id}/{media_name}").content == items[config.id].media_bytes()
    assert items["CAM-TOP"].media_bytes() != items["CAM-FRONT"].media_bytes()
    assert client.get("/v1/cages").status_code == 401


def test_advertised_segment_survives_playlist_rotation_within_freshness_limit(paired_viewer, monkeypatch):
    client, _, folders, items, _ = paired_viewer
    folder, original = folders["CAM-TOP"], items["CAM-TOP"]
    now = [time.time()]
    monkeypatch.setattr("habitat_gateway.camera_viewer.time.time", lambda: now[0])
    started = datetime.fromtimestamp(now[0] - 30, timezone.utc)
    rows = [original.model_copy(update={"sequence": 100 + index,
        "session_started_at": started, "captured_at": datetime.fromtimestamp(now[0] - 12 + 2 * index, timezone.utc)})
        for index in range(7)]
    (folder / "session.json").write_text(json.dumps({"session_id": str(original.session_id),
        "started_at": started.isoformat()}))
    for row in rows:
        (folder / f"seg-{row.sequence:016d}.ts").write_bytes(row.media_bytes())

    def rotate(values):
        (folder / "index.m3u8").write_text("#EXTM3U\n" + "".join(
            f"#EXTINF:2,\n#EXT-X-PROGRAM-DATE-TIME:{row.captured_at.isoformat()}\nseg-{row.sequence:016d}.ts\n"
            for row in values))

    rotate(rows[:6])
    response = client.get("/camera/hls/CAM-TOP/index.m3u8")
    assert response.status_code == 200
    path = f"/camera/hls/CAM-TOP/{original.session_id}/100.ts"
    assert f"{original.session_id}/100.ts" in response.text
    assert client.get(path).status_code == 200
    now[0] += 2
    rotate(rows[1:])
    assert "100.ts" not in client.get("/camera/hls/CAM-TOP/index.m3u8").text
    assert (folder / "seg-0000000000000100.ts").is_file()
    assert client.get(path).content == rows[0].media_bytes(), "rotation must not prematurely expire advertised media"
    now[0] += 20
    source(folder, rows[-1].model_copy(update={"sequence": 107,
        "captured_at": datetime.fromtimestamp(now[0] - 2, timezone.utc)}))
    os.utime(folder / "index.m3u8", (now[0], now[0]))
    assert client.get(path).status_code == 200, "an advertised fragment must survive proxy delay"
    now[0] += 12
    source(folder, rows[-1].model_copy(update={"sequence": 108,
        "captured_at": datetime.fromtimestamp(now[0] - 2, timezone.utc)}))
    os.utime(folder / "index.m3u8", (now[0], now[0]))
    assert client.get(path).status_code == 404, "the replay grace period remains bounded"


@pytest.mark.parametrize("failure,status", [
    ("stopped", 503), ("reader_error", 503), ("identity_lost", 503), ("stale_manifest", 503),
    ("deleted", 404), ("changed_bytes", 404), ("oversized", 404),
    ("new_session", 404), ("never_advertised", 404), ("logged_out", 401),
])
def test_retained_segment_keeps_reader_session_integrity_and_auth_gates(paired_viewer, failure, status):
    client, _, folders, items, worker = paired_viewer
    folder, old = folders["CAM-TOP"], items["CAM-TOP"]
    path = f"/camera/hls/CAM-TOP/{old.session_id}/{old.sequence}.ts"
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 200
    new = old.model_copy(update={"sequence": old.sequence + 1,
                                 "captured_at": old.captured_at + timedelta(seconds=1)})
    source(folder, new)
    assert client.get(path).status_code == 200
    retained_file = folder / f"seg-{old.sequence:016d}.ts"
    if failure == "stopped":
        worker.states["CAM-TOP"] = {"reader_running": False}
    elif failure == "reader_error":
        worker.states["CAM-TOP"] = {"status": "capture_failed_check_network_stream"}
    elif failure == "identity_lost":
        client.app.state.gateway.settings.camera_discovery.enabled = True
        worker.states["CAM-TOP"] = {"identity_verified": False}
    elif failure == "stale_manifest":
        stale = time.time() - 30
        os.utime(folder / "index.m3u8", (stale, stale))
    elif failure == "deleted":
        retained_file.unlink()
    elif failure == "changed_bytes":
        retained_file.write_bytes((b"G" + b"x" * 187) * 3)
    elif failure == "oversized":
        retained_file.write_bytes(b"G" * (MAX_SEGMENT_BYTES + 1))
    elif failure == "new_session":
        source(folder, segment().model_copy(update={"camera_id": "CAM-TOP"}))
    elif failure == "never_advertised":
        other = old.sequence - 1
        (folder / f"seg-{other:016d}.ts").write_bytes(old.media_bytes())
        path = f"/camera/hls/CAM-TOP/{old.session_id}/{other}.ts"
    elif failure == "logged_out":
        client.delete("/camera/session")
    assert client.get(path).status_code == status


def test_retained_native_segment_requires_current_media_verification(paired_viewer):
    client, configs, folders, items, worker = paired_viewer
    if configs[0].source_type != "rtsp_h264":
        pytest.skip("native media verification gate")
    old = items["CAM-TOP"]
    path = f"/camera/hls/CAM-TOP/{old.session_id}/{old.sequence}.ts"
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 200
    source(folders["CAM-TOP"], old.model_copy(update={"sequence": old.sequence + 1}))
    assert client.get(path).status_code == 200
    worker.states["CAM-TOP"] = {"media_verified": False}
    assert client.get(path).status_code == 503


def test_one_stale_camera_does_not_stop_other_views_or_other_cages(paired_viewer):
    client, _, folders, _, _ = paired_viewer
    stale = time.time() - 30
    os.utime(folders["CAM-TOP"] / "index.m3u8", (stale, stale))
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert not rows["CAM-TOP"]["fresh"] and rows["CAM-TOP"]["status"] == "waiting_fresh_video"
    assert rows["CAM-TOP"]["age_s"] is None
    assert rows["CAM-FRONT"]["fresh"] and rows["CAM-OTHER"]["fresh"]
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 200
    assert client.get("/camera/hls/CAM-OTHER/index.m3u8").status_code == 200


def test_known_reader_failure_blocks_even_recent_cached_video(paired_viewer):
    client, _, _, _, worker = paired_viewer
    worker.states["CAM-TOP"] = {"status": "capture_failed_check_network_stream"}
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert rows["CAM-TOP"]["status"] == "capture_failed_check_network_stream"
    assert not rows["CAM-TOP"]["fresh"] and rows["CAM-FRONT"]["fresh"]
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 200


def test_reconnect_backoff_cannot_replay_recent_cached_video(paired_viewer):
    client, _, _, _, worker = paired_viewer
    worker.states["CAM-TOP"] = {"status": "waiting_video_frames", "reader_running": False}
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert not rows["CAM-TOP"]["fresh"] and rows["CAM-FRONT"]["fresh"]
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 200


def test_unbound_and_disabled_cameras_remain_visible_without_playing_old_media(paired_viewer):
    client, configs, _, _, _ = paired_viewer
    configs[0].url = None
    configs[1].live_stream = False
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert rows["CAM-TOP"]["status"] == "waiting_network_camera_binding"
    assert rows["CAM-FRONT"]["status"] == "live_stream_disabled"
    assert not rows["CAM-TOP"]["fresh"] and not rows["CAM-FRONT"]["fresh"]
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 404


def test_discovered_camera_with_no_configured_url_requires_current_verified_reader(paired_viewer):
    client, configs, _, items, worker = paired_viewer
    client.app.state.gateway.settings.camera_discovery.enabled = True
    configs[0].url = None
    worker.states["CAM-TOP"] = {"identity_verified": True, "reader_running": True}
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert rows["CAM-TOP"]["status"] == "live" and rows["CAM-TOP"]["fresh"]
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 200
    # A configured old address cannot bypass identity verification either.
    assert rows["CAM-FRONT"]["status"] == "waiting_network_camera_binding"
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 503
    worker.states["CAM-TOP"]["identity_verified"] = False
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    worker.states["CAM-TOP"] = {"identity_verified": True, "reader_running": False}
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert configs[0].url is None


def test_corrupted_video_is_isolated(paired_viewer):
    client, _, folders, items, _ = paired_viewer
    (folders["CAM-TOP"] / f'seg-{items["CAM-TOP"].sequence:016d}.ts').write_bytes(b"bad-frame")
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert not rows["CAM-TOP"]["fresh"] and rows["CAM-FRONT"]["fresh"]


@pytest.mark.parametrize("bad_media", ["duration", "zero", "nan", "inf", "oversized", "short", "framing"])
def test_bad_segment_does_not_hide_newer_valid_contiguous_video(paired_viewer, bad_media):
    client, _, folders, items, _ = paired_viewer
    folder, original = folders["CAM-TOP"], items["CAM-TOP"]
    rows = [original.model_copy(update={"sequence": 100 + index}) for index in range(6)]
    for row in rows:
        (folder / f"seg-{row.sequence:016d}.ts").write_bytes(row.media_bytes())
    bad = folder / "seg-0000000000000102.ts"
    if bad_media == "oversized":
        bad.write_bytes(b"G" * (MAX_SEGMENT_BYTES + 1))
    elif bad_media == "short":
        bad.write_bytes(b"bad")
    elif bad_media == "framing":
        bad.write_bytes(b"x" * 188)
    durations = {"duration": "4.001", "zero": "0", "nan": "nan", "inf": "inf"}
    bad_duration = durations.get(bad_media, "2")
    (folder / "index.m3u8").write_text("#EXTM3U\n" + "".join(
        f"#EXTINF:{bad_duration if row.sequence == 102 else '2'},\n"
        f"#EXT-X-PROGRAM-DATE-TIME:{row.captured_at.isoformat()}\nseg-{row.sequence:016d}.ts\n"
        for row in rows))
    response = client.get("/camera/hls/CAM-TOP/index.m3u8")
    assert response.status_code == 200
    names = [line for line in response.text.splitlines() if line and not line.startswith("#")]
    assert names == [f"{original.session_id}/{sequence}.ts" for sequence in (103, 104, 105)]
    assert client.get(f"/camera/hls/CAM-TOP/{original.session_id}/102.ts").status_code == 404
    assert client.get("/camera/hls/CAM-TOP/" + names[-1]).content == original.media_bytes()
    for row in rows:
        (folder / f"seg-{row.sequence:016d}.ts").write_bytes(b"bad")
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503


@pytest.mark.parametrize("failure", ["path", "duration_syntax", "captured_syntax", "before_session", "session_syntax", "session_naive", "too_many"])
def test_bad_manifest_or_session_still_rejects_whole_camera(paired_viewer, failure):
    client, _, folders, items, _ = paired_viewer
    folder, item = folders["CAM-TOP"], items["CAM-TOP"]
    source(folder, item)
    text = (folder / "index.m3u8").read_text()
    if failure == "path":
        text += "#EXTINF:4.001,\n#EXT-X-PROGRAM-DATE-TIME:" + item.captured_at.isoformat() + "\n../outside.ts\n"
    elif failure == "duration_syntax":
        text += "#EXTINF:invalid,\n"
    elif failure == "captured_syntax":
        text += "#EXT-X-PROGRAM-DATE-TIME:invalid\n"
    elif failure == "before_session":
        text += "#EXTINF:4.001,\n#EXT-X-PROGRAM-DATE-TIME:" + (item.session_started_at - timedelta(seconds=1)).isoformat() + "\nseg-0000000000000011.ts\n"
    elif failure == "session_syntax":
        (folder / "session.json").write_text("{")
    elif failure == "session_naive":
        (folder / "session.json").write_text(json.dumps({"session_id": str(item.session_id),
            "started_at": item.session_started_at.replace(tzinfo=None).isoformat()}))
    elif failure == "too_many":
        text += ("#EXTINF:4.001,\n#EXT-X-PROGRAM-DATE-TIME:" + item.captured_at.isoformat() + "\nseg-0000000000000011.ts\n") * 6
    (folder / "index.m3u8").write_text(text)
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    assert client.get("/camera/hls/CAM-FRONT/index.m3u8").status_code == 200


def test_h264_waits_for_verified_media_even_when_cached_chunks_are_fresh(paired_viewer):
    client, configs, _, _, worker = paired_viewer
    if configs[0].source_type != "rtsp_h264":
        pytest.skip("H.264 media verification applies to the new source")
    worker.states["CAM-TOP"] = {"media_verified": False}
    rows = {row["id"]: row for row in client.get("/camera/api/cameras").json()["cameras"]}
    assert rows["CAM-TOP"]["fresh"] is False and rows["CAM-FRONT"]["fresh"] is True
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 503
    worker.states["CAM-TOP"]["media_verified"] = True
    assert client.get("/camera/hls/CAM-TOP/index.m3u8").status_code == 200


def test_legacy_camera_still_has_no_view(viewer):
    legacy, _, _ = viewer
    login(legacy)
    row = legacy.get("/camera/api/cameras").json()["cameras"][0]
    assert row["source_type"] == "uvc" and row["view"] is None and row["fresh"]
