import asyncio
import base64
from datetime import timedelta
import hashlib
import json
import time
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

from habitat.common.models import utcnow
from habitat.saas.video import AdvertisedSegments, VideoUploader, VideoUploadConfig, read_live_segments
from habitat.saas.video_contract import VIDEO_PATH, MAX_VIDEO_BODY, HLS_RETAIN_SEGMENTS, VideoSegment
from habitat.vision.cameras import CameraConfig
from habitat_gateway.saas_reference import Registration, create_receiver
from habitat_gateway.api import create_app
from habitat_gateway.config import Settings, video_token

PI_TOKEN = "test-pi-video-token-with-at-least-32-characters"
VIEW_TOKEN = "test-view-video-token-with-at-least-32-characters"
PI_HEADERS = {"Authorization": "Bearer " + PI_TOKEN}
VIEW_HEADERS = {"Authorization": "Bearer " + VIEW_TOKEN}
PLAYLIST = "/v1/video/STORE-001/PI-001/RGB-001/index.m3u8"
CAMERA = CameraConfig(id="RGB-001", cage_id="CAGE-001", live_stream=True)


def app(database=":memory:"):
    scope = dict(site_id="STORE-001", gateway_id="PI-001", cage_ids=["CAGE-001"],
                 camera_cages={"RGB-001": "CAGE-001"})
    return create_receiver(database, [Registration(**scope, token_env="PI")],
        viewers=[Registration(**scope, token_env="VIEW")], environ={"PI": PI_TOKEN, "VIEW": VIEW_TOKEN})


def segment(**updates):
    # Framing fixture only. Real H.264 decoding is tested with FFmpeg separately.
    data = (b"G" + bytes(187)) * 3
    now = utcnow()
    return VideoSegment.model_validate(dict(site_id="STORE-001", gateway_id="PI-001",
        cage_id="CAGE-001", camera_id="RGB-001", session_id=str(uuid4()), sequence=10,
        session_started_at=now-timedelta(seconds=10), captured_at=now-timedelta(seconds=2),
        duration_s=2, sha256=hashlib.sha256(data).hexdigest(),
        data_base64=base64.b64encode(data).decode(), **updates))


def source(directory, item):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.json").write_text(json.dumps({"session_id": str(item.session_id),
        "started_at": item.session_started_at.isoformat()}))
    (directory / f"seg-{item.sequence:016d}.ts").write_bytes(item.media_bytes())
    (directory / "index.m3u8").write_text("#EXTM3U\n#EXTINF:2,\n#EXT-X-PROGRAM-DATE-TIME:" +
        item.captured_at.isoformat() + f"\nseg-{item.sequence:016d}.ts\n")


def test_upload_ack_viewer_isolation_and_restart(tmp_path):
    item = segment()
    database = tmp_path / "receiver.sqlite3"
    for _ in range(2):
        with TestClient(app(database)) as client:
            assert client.post(VIDEO_PATH, json=item.model_dump(mode="json")).status_code == 401
            assert client.post(VIDEO_PATH, json=item.model_dump(mode="json"), headers=VIEW_HEADERS).status_code == 401
            result = client.post(VIDEO_PATH, json=item.model_dump(mode="json"), headers=PI_HEADERS)
            assert result.json() == item.acknowledgement().model_dump(mode="json")
            assert client.get(PLAYLIST, headers=PI_HEADERS).status_code == 401
            response = client.get(PLAYLIST, headers=VIEW_HEADERS)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            media = response.text.splitlines()[-1]
            assert client.get(PLAYLIST.rsplit("/", 1)[0] + "/" + media, headers=VIEW_HEADERS).content == item.media_bytes()
            assert client.app.state.db.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0] == 1
            assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0


@pytest.mark.parametrize("changes,status", [
    ({"site_id": "OTHER"}, 403), ({"cage_id": "OTHER"}, 403), ({"camera_id": "OTHER"}, 403),
    ({"sha256": "0" * 64}, 422), ({"data_base64": "!"}, 422),
    ({"captured_at": -timedelta(minutes=1)}, 422),
    ({"captured_at": timedelta(seconds=60)}, 409),
])
def test_scope_digest_and_clock_rejections(changes, status):
    with TestClient(app()) as client:
        payload = segment().model_dump(mode="json") | changes
        # Resolve clock offsets when this case runs, after any slow prior tests.
        if isinstance(payload.get("captured_at"), timedelta):
            payload["captured_at"] = (utcnow() + payload["captured_at"]).isoformat()
        assert client.post(VIDEO_PATH, json=payload, headers=PI_HEADERS).status_code == status
        assert client.app.state.db.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0] == 0


def test_conflict_expiry_session_switch_retention_and_missing_segments(tmp_path):
    item = segment()
    with TestClient(app()) as client:
        def send(value):
            return client.post(VIDEO_PATH, json=value.model_dump(mode="json"), headers=PI_HEADERS)
        assert send(item).status_code == 200
        assert send(item.model_copy(update={"duration_s": 1.5})).status_code == 409
        for seq in range(11, 31):
            assert send(item.model_copy(update={"sequence": seq})).status_code == 200
        assert client.app.state.db.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0] == 12
        # Gaps do not create an invalid playlist with incorrect implied sequence IDs.
        assert send(item.model_copy(update={"sequence": 35})).status_code == 200
        assert client.get(PLAYLIST, headers=VIEW_HEADERS).text.count("#EXTINF") == 1
        newer = item.model_copy(update={"session_id": uuid4(), "sequence": 100,
            "session_started_at": item.session_started_at + timedelta(seconds=1)})
        assert send(newer).status_code == 200
        assert send(item).status_code == 409
        assert client.app.state.db.execute("SELECT COUNT(*) FROM video_segments").fetchone()[0] == 1
        db = client.app.state.db
        db.execute("UPDATE video_segments SET captured_at=?", ((utcnow()-timedelta(seconds=20)).isoformat(),))
        db.commit()
        assert client.get(PLAYLIST, headers=VIEW_HEADERS).status_code == 503
        assert client.get(PLAYLIST.replace("STORE-001", "OTHER"), headers=VIEW_HEADERS).status_code == 403


def test_video_body_limit_covers_chunked_input():
    with TestClient(app()) as client:
        response = client.post(VIDEO_PATH, content=(b"x"*1024 for _ in range(MAX_VIDEO_BODY//1024 + 1)), headers=PI_HEADERS)
        assert response.status_code == 413


def test_sender_retries_validates_ack_drops_stale_and_resumes_latest(tmp_path):
    item = segment()
    source(tmp_path / CAMERA.id, item)
    uploader = VideoUploader(VideoUploadConfig(enabled=True, endpoint="https://saas.test/v1/edge/video"),
        [CAMERA], tmp_path, "STORE-001", "PI-001", PI_TOKEN)
    requests, fail = [], [True]

    async def handler(request):
        sent = VideoSegment.model_validate_json(request.content)
        requests.append(sent)
        if fail[0]:
            return httpx.Response(200, json=sent.acknowledgement().model_copy(update={"camera_id":"OTHER"}).model_dump(mode="json"))
        return httpx.Response(200, json=sent.acknowledgement().model_dump(mode="json"))

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert not await uploader.cycle(client, CAMERA)
            assert uploader.status()["cameras"][CAMERA.id]["last_error"] == "ack_mismatch"
            assert not uploader.acknowledged[CAMERA.id]
            fail[0] = False
            assert await uploader.cycle(client, CAMERA)
            assert await uploader.cycle(client, CAMERA)
            assert len(requests) == 2  # Already acknowledged segments are not sent again.
            old = item.model_copy(update={"captured_at": utcnow()-timedelta(seconds=30),
                                         "session_started_at": utcnow()-timedelta(seconds=40)})
            source(tmp_path / CAMERA.id, old)
            assert await uploader.cycle(client, CAMERA)
            assert len(requests) == 2
            fresh = item.model_copy(update={"sequence": 25, "captured_at": utcnow()-timedelta(seconds=2)})
            source(tmp_path / CAMERA.id, fresh)
            assert await uploader.cycle(client, CAMERA)
            assert requests[-1].sequence == 25
    asyncio.run(check())
    assert PI_TOKEN not in json.dumps(uploader.status())


def test_manifest_rejects_traversal_and_ignores_incomplete_files(tmp_path):
    item = segment()
    source(tmp_path, item)
    (tmp_path / "seg-0000000000000011.ts.tmp").write_bytes(item.media_bytes())
    assert len(read_live_segments(tmp_path, "STORE-001", "PI-001", CAMERA)) == 1
    manifest = tmp_path / "index.m3u8"
    manifest.write_text(manifest.read_text().replace(f"seg-{item.sequence:016d}.ts", "../secret"))
    with pytest.raises(ValueError, match="manifest"):
        read_live_segments(tmp_path, "STORE-001", "PI-001", CAMERA)


def test_advertised_segment_retention_has_a_fixed_count_bound(tmp_path):
    original = segment()
    rows = [original.model_copy(update={"sequence": sequence}) for sequence in range(HLS_RETAIN_SEGMENTS + 1)]
    retained = AdvertisedSegments()
    for row in rows:
        source(tmp_path, row)
        retained.remember(CAMERA.id, [row])
    current = rows[-1]
    assert (tmp_path / "seg-0000000000000000.ts").is_file()
    assert retained.read(tmp_path, CAMERA.id, str(current.session_id), 0, current) is None
    assert retained.read(tmp_path, CAMERA.id, str(current.session_id), 1, current).media_bytes() == original.media_bytes()


@pytest.mark.parametrize("duration", [0, 4.001, float("nan"), float("inf")])
def test_media_fault_isolation_does_not_relax_wire_duration_limits(duration):
    item = segment()
    assert VideoSegment.model_validate({**item.model_dump(), "duration_s": 4}).duration_s == 4
    with pytest.raises(ValueError):
        VideoSegment.model_validate({**item.model_dump(), "duration_s": duration})


@pytest.mark.parametrize("url", ["http://saas.test/v1/edge/video", "https://user:secret@saas.test/video", "https://saas.test/video?token=secret"])
def test_upload_endpoint_rejects_insecure_or_embedded_credentials(url):
    with pytest.raises(ValueError):
        VideoUploadConfig(enabled=True, endpoint=url)


def test_upload_network_failure_and_cancellation_leave_source_intact(tmp_path):
    item = segment()
    source(tmp_path / CAMERA.id, item)
    uploader = VideoUploader(VideoUploadConfig(enabled=True, endpoint="https://saas.test/v1/edge/video"),
        [CAMERA], tmp_path, "STORE-001", "PI-001", PI_TOKEN)
    async def check():
        async def failed(request):
            raise httpx.ConnectError(PI_TOKEN)  # Transport messages must never reach status/logs.
        async with httpx.AsyncClient(transport=httpx.MockTransport(failed)) as client:
            assert not await uploader.cycle(client, CAMERA)
        entered = asyncio.Event()
        async def blocked(request):
            entered.set()
            await asyncio.sleep(60)
        async with httpx.AsyncClient(transport=httpx.MockTransport(blocked)) as client:
            task = asyncio.create_task(uploader.cycle(client, CAMERA))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(check())
    assert uploader.status()["cameras"][CAMERA.id]["last_error"] == "network_error"
    assert not uploader.acknowledged[CAMERA.id]
    assert PI_TOKEN not in json.dumps(uploader.status())
    assert list((tmp_path / CAMERA.id).glob("*.ts"))


def test_video_configuration_and_credentials_are_checked(settings, monkeypatch):
    raw = settings.model_dump()
    raw["video_upload"] = {"enabled": True, "endpoint": "https://saas.test/v1/edge/video"}
    with pytest.raises(ValueError, match="at least one camera"):
        Settings.model_validate(raw)
    raw["cameras"] = [CAMERA.model_dump()]
    configured = Settings.model_validate(raw)
    monkeypatch.delenv("HABITAT_CLOUD_TOKEN", raising=False)
    with pytest.raises(ValueError):
        video_token(configured)
    monkeypatch.setenv("HABITAT_CLOUD_TOKEN", PI_TOKEN)
    assert video_token(configured) == PI_TOKEN
    assert video_token(settings) is None


@pytest.mark.parametrize("problem,code", [("http", "http_503"), ("redirect", "http_302"),
    ("missing_version", "invalid_ack"), ("html", "invalid_ack"), ("large", "ack_too_large"),
    ("timeout", "timeout")])
def test_sender_never_acknowledges_failed_or_invalid_responses(tmp_path, problem, code):
    item = segment()
    source(tmp_path / CAMERA.id, item)
    uploader = VideoUploader(VideoUploadConfig(enabled=True, endpoint="https://saas.test/v1/edge/video"),
        [CAMERA], tmp_path, "STORE-001", "PI-001", PI_TOKEN)
    def response(request):
        if problem == "http":
            return httpx.Response(503)
        if problem == "redirect":
            return httpx.Response(302, headers={"Location": "https://unrelated.test/"})
        if problem == "missing_version":
            return httpx.Response(200, json=item.acknowledgement().model_dump(mode="json", exclude={"schema_version"}))
        if problem == "html":
            return httpx.Response(200, text="<html>Login</html>")
        if problem == "large":
            return httpx.Response(200, content=b"x" * 16385)
        raise httpx.ReadTimeout(PI_TOKEN)
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            assert not await uploader.cycle(client, CAMERA)
    asyncio.run(check())
    assert uploader.status()["cameras"][CAMERA.id]["last_error"] == code
    assert not uploader.acknowledged[CAMERA.id]
    assert PI_TOKEN not in json.dumps(uploader.status())


def test_slow_video_upload_does_not_block_gateway_or_shutdown(settings, tmp_path, monkeypatch):
    entered = threading.Event()
    monkeypatch.setenv("HABITAT_CLOUD_TOKEN", PI_TOKEN)
    monkeypatch.delenv("HABITAT_API_TOKEN", raising=False)
    item = segment()
    monkeypatch.setattr("habitat.saas.video.read_live_segments", lambda *a: [item])

    async def stalled(self, client, value):
        entered.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(VideoUploader, "send", stalled)
    configured = settings.model_copy(update={"database": str(tmp_path / "local.sqlite3"),
        "cameras": [CAMERA], "video_upload": VideoUploadConfig(enabled=True,
            endpoint="https://saas.test/v1/edge/video")})
    with TestClient(create_app(configured)) as client:
        assert entered.wait(2)
        started = time.monotonic()
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/v1/cages").status_code == 200
        assert time.monotonic()-started < 1
        closing = time.monotonic()
    assert time.monotonic()-closing < 3
