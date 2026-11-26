"""Real FFmpeg file/localhost-MJPEG checks; no physical camera accuracy claim."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import asyncio
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import threading

from PIL import Image

import pytest
from habitat.vision import cameras
from habitat.vision.behavior_dataset import validate_manifest
from habitat.saas.video import VideoUploader, VideoUploadConfig
from tests.contract.test_video import app as video_receiver, PI_TOKEN, VIEW_HEADERS, PLAYLIST
import httpx
from fastapi.testclient import TestClient


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_three_streams_clips_preview_quota_and_shutdown(tmp_path, monkeypatch):
    fixture = tmp_path / "test-pattern.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "testsrc2=size=640x480:rate=10", "-t", "22", "-c:v", "mjpeg", "-threads", "1",
        str(fixture)], check=True, timeout=20)
    original = cameras.video_command

    def file_input(camera, directory, preview):
        command = original(camera, directory, preview)
        return command[:8] + ["-re", "-i", str(fixture)] + command[command.index("-map"):]

    monkeypatch.setattr(cameras, "video_command", file_input)
    configs = [cameras.CameraConfig(id=f"RGB-{i}", cage_id=f"CAGE-{i}", record_video=True,
               interval_s=10, segment_s=10, archive_max_mb=64) for i in range(3)]
    worker = cameras.CameraWorker(configs, tmp_path / "camera-output")
    processes = []
    try:
        for config in configs:
            worker._video_cycle(config, {})
            processes.append(worker.recorders[config.id][0])
            worker._video_cycle(config, {})
            assert worker.recorders[config.id][0] is processes[-1], "must not open camera twice"
        for process in processes:
            assert process.wait(timeout=35) == 0
        for config in configs:
            preview = worker.directory / f"{config.id}.jpg"
            assert preview.stat().st_size > 100
            session = worker.recorders[config.id][1]
            rows = list(csv.reader((session / "segments.csv").open()))
            assert len(rows) == 3
            count = 0
            last = 0.
            for name, start, end in rows:
                assert abs(float(start)-last) < .15
                last = float(end)
                result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-count_frames", "-show_entries", "stream=nb_read_frames,width,height,codec_name",
                    "-of", "json", str(session / name)], check=True, capture_output=True, text=True, timeout=5)
                stream = json.loads(result.stdout)["streams"][0]
                assert (stream["width"], stream["height"], stream["codec_name"]) == (640,480,"mjpeg")
                count += int(stream["nb_read_frames"])
            assert count == 220 and abs(last-22) < .15
        worker.close()
        assert not worker.recorders
        # Synthetic label fixtures exercise media integrity, not animal classification.
        samples = sorted((worker.directory / "recordings" / configs[0].id).rglob("clip-*.mkv"))
        manifest = {"species": "Correlophus ciliatus", "clips": [
            {"file": str(path.relative_to(tmp_path)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "subject_id": f"FIXTURE-{i}", "enclosure_id": f"FIXTURE-{i}", "capture_day": f"2026-10-0{i+1}",
             "session_id": f"FIXTURE-{i}", "split": split, "annotator": "FIXTURE-A", "reviewer": "FIXTURE-B",
             "annotations": [{"start_s": 0, "end_s": 1, "labels": ["uncertain"]}]}
            for i, (path, split) in enumerate(zip(samples, ("train", "validation", "test")))]}
        manifest_path = tmp_path / "synthetic-label-test.json"
        manifest_path.write_text(json.dumps(manifest))
        assert validate_manifest(manifest_path)["split_integrity"] == "pass"
        manifest["clips"][0]["annotations"][0]["end_s"] = 1000
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="duration"):
            validate_manifest(manifest_path)
        # A quota pause preserves recordings and refuses a new process.
        config = configs[0]
        ballast = worker.directory / "recordings" / config.id / "quota-test"
        with ballast.open("wb") as f:
            f.truncate(config.archive_max_mb*1024**2)
        before = set(worker.directory.rglob("clip-*.mkv"))
        worker._video_cycle(config, {})
        assert worker.states[config.id]["status"] == "archive_full"
        assert set(worker.directory.rglob("clip-*.mkv")) == before
        assert not worker.recorders
        # Startup failure is visible and backoff prevents a spawn loop.
        config = configs[1]
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        worker._video_cycle(config, {})
        assert worker.states[config.id]["status"] == "capture_failed_check_ffmpeg"
        assert worker.next_capture[config.id] > time.time()
    finally:
        worker.close()
    assert all(p.poll() is not None for p in processes)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_real_h264_live_upload_playback_and_archive_quota(tmp_path, monkeypatch):
    fixture = tmp_path / "camera-mjpeg.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "testsrc2=size=320x240:rate=10", "-t", "30", "-c:v", "mjpeg", "-threads", "1",
        str(fixture)], check=True, timeout=15)
    camera = cameras.CameraConfig(id="RGB-001", cage_id="CAGE-001", live_stream=True,
        record_video=True, width=320, height=240, fps=10, interval_s=10, segment_s=10, archive_max_mb=64)
    original = cameras.video_command

    def synthetic_input(camera, directory, preview, **kwargs):
        command = original(camera, directory, preview, **kwargs)
        assert command.count("-i") == 1  # Archive, preview and live share one reader.
        return command[:8] + ["-re", "-i", str(fixture)] + command[command.index("-map"):]

    monkeypatch.setattr(cameras, "video_command", synthetic_input)
    worker = cameras.CameraWorker([camera], tmp_path / "camera")
    uploader = VideoUploader(VideoUploadConfig(enabled=True, endpoint="https://saas.test/v1/edge/video"),
        [camera], worker.directory / "live", "STORE-001", "PI-001", PI_TOKEN)
    receiver = video_receiver()
    processes = []
    try:
        with TestClient(receiver) as browser:
            async def exercise():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=receiver)) as client:
                    worker._video_cycle(camera, {})
                    processes.append(worker.recorders[camera.id][0])
                    started = time.monotonic()
                    while time.monotonic()-started < 18:
                        worker._video_cycle(camera, {})
                        assert worker.recorders[camera.id][0] is processes[0]
                        assert await uploader.cycle(client, camera), uploader.status()
                        await asyncio.sleep(.5)
                    assert uploader.status()["cameras"][camera.id]["last_success_at"]
                    assert len(list((worker.directory / "live" / camera.id).glob("*.ts"))) <= 9
                    playlist = browser.get(PLAYLIST, headers=VIEW_HEADERS)
                    assert playlist.status_code == 200
                    names = [line for line in playlist.text.splitlines() if line and not line.startswith("#")]
                    assert 2 <= len(names) <= 6
                    path = tmp_path / "received.ts"
                    path.write_bytes(browser.get(PLAYLIST.rsplit("/", 1)[0] + "/" + names[-1], headers=VIEW_HEADERS).content)
                    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_name,width,height", "-of", "json", str(path)],
                        check=True, capture_output=True, text=True, timeout=5)
                    stream = json.loads(probe.stdout)["streams"][0]
                    assert (stream["codec_name"], stream["width"], stream["height"]) == ("h264", 320, 240)
                    assert (worker.directory / f"{camera.id}.jpg").stat().st_size > 100
                    clips = list((worker.directory / "recordings" / camera.id).rglob("clip-*.mkv"))
                    assert clips
                    previous_session = json.loads((worker.directory / "live" / camera.id / "session.json").read_text())["session_id"]
                    ballast = worker.directory / "recordings" / camera.id / "quota-test"
                    with ballast.open("wb") as handle:
                        handle.truncate(camera.archive_max_mb*1024**2)
                    worker._video_cycle(camera, {})
                    assert worker.states[camera.id]["recording"] == "paused_preserving_clips"
                    assert all(path.exists() for path in clips)
                    processes.append(worker.recorders[camera.id][0])
                    assert processes[1] is not processes[0]
                    new_session = json.loads((worker.directory / "live" / camera.id / "session.json").read_text())["session_id"]
                    assert new_session != previous_session
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        await asyncio.sleep(.5)
                        assert await uploader.cycle(client, camera)
                        live = browser.get(PLAYLIST, headers=VIEW_HEADERS)
                        if new_session in live.text:
                            break
                    assert new_session in live.text, "live resumes after recorder restart/quota"
                    assert previous_session not in live.text
            asyncio.run(exercise())
    finally:
        worker.close()
    assert all(process.poll() is not None for process in processes)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")
def test_http_mjpeg_readers_reconnect_without_blocking_other_camera(tmp_path):
    """Actual TCP multipart streams, one stalled source, and a reconnecting source."""
    top_online = threading.Event()
    top_online.set()
    top_initial_pause = threading.Event()
    done = threading.Event()
    requests = Counter()
    frames_during_top_pause = Counter()
    with BytesIO() as encoded:
        Image.new("RGB", (320, 240), (32, 160, 64)).save(encoded, format="JPEG")
        jpeg = encoded.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests[self.path] += 1
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            if self.path == "/stalled":
                done.wait(60)  # The reader must stop before this fixture closes its socket.
                return
            if self.path == "/top" and requests[self.path] == 1:
                # A 4s Wi-Fi pause used to exceed the reader's 3s I/O limit.
                top_initial_pause.set()
                done.wait(4)
                top_initial_pause.clear()
            try:
                while not done.is_set() and (self.path != "/top" or top_online.is_set()):
                    # DFRobot streams may omit per-frame Content-Length.
                    length = b"" if self.path == "/top" else b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n" + length + b"\r\n" + jpeg + b"\r\n")
                    self.wfile.flush()
                    if top_initial_pause.is_set():
                        frames_during_top_pause[self.path] += 1
                    done.wait(.1)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    configs = [
        cameras.CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top",
                             url=base + "/top", live_stream=True, record_video=True,
                             interval_s=10, segment_s=10, width=320, height=240),
        cameras.CameraConfig(id="FRONT", cage_id="CAGE-A", source_type="http_mjpeg", view="front",
                             url=base + "/front", interval_s=10, width=320, height=240),
        cameras.CameraConfig(id="OFFLINE", cage_id="CAGE-B", source_type="http_mjpeg",
                             url=base + "/stalled", interval_s=10),
    ]
    worker = cameras.CameraWorker(configs, tmp_path / "http-cameras")
    processes = []

    def poll_until(condition, seconds=18):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            before = time.monotonic()
            worker.cycle()
            assert time.monotonic() - before < 1, "one unavailable source blocked the shared cycle"
            if condition():
                return
            time.sleep(.1)
        pytest.fail("camera condition timed out: " + repr(worker.status()))

    try:
        worker.cycle()
        processes.extend(row[0] for row in worker.recorders.values())
        top_process = worker.recorders["TOP"][0]
        front_process = worker.recorders["FRONT"][0]
        stalled_process = worker.recorders["OFFLINE"][0]
        # rw_timeout bounds each I/O operation, not all FFmpeg probing combined.
        # The unchanged no-preview watchdog also bounds a silent reader at 30s.
        poll_until(lambda: "OFFLINE" not in worker.recorders and
                   all(worker.status()["cameras"][name]["status"] == "preview_ready"
                       for name in ("TOP", "FRONT")), seconds=35)
        poll_until(lambda: stalled_process.poll() is not None, seconds=5)
        assert requests["/top"] == requests["/front"] == 1
        assert worker.recorders["TOP"][0] is top_process, "bounded startup pause must not restart TOP"
        assert worker.recorders["FRONT"][0] is front_process
        assert frames_during_top_pause["/front"] > 1, "FRONT must keep streaming during TOP's pause"
        assert worker.states["OFFLINE"]["status"] in ("capture_failed_check_network_stream", "waiting_video_frames")
        assert "OFFLINE" not in worker.recorders, "stalled HTTP read exceeded the I/O timeout"
        assert worker.next_capture["OFFLINE"] > time.time()
        assert worker.recorders["FRONT"][1] is None, "snapshot-only HTTP needs no archive/live session"
        assert "url" not in worker.status()["cameras"]["TOP"]
        with Image.open(worker.directory / "TOP.jpg") as frame:
            frame.load()
            assert frame.size == (320, 240)
        session = json.loads((worker.directory / "live/TOP/session.json").read_text())["session_id"]
        archive = worker.recorders["TOP"][1]
        metadata = json.loads((archive / "session.json").read_text())
        assert metadata["source"] == "network_http_mjpeg" and "url" not in metadata["camera"]
        segments = sorted((worker.directory / "live/TOP").glob("*.ts"))
        assert segments
        decoded = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror",
            "-i", str(segments[-1]), "-f", "null", "-"], capture_output=True, timeout=5)
        assert decoded.returncode == 0, decoded.stderr

        old_preview = (worker.directory / "TOP.jpg").stat().st_mtime
        top_online.clear()
        poll_until(lambda: "TOP" not in worker.recorders, seconds=8)
        assert worker.status()["cameras"]["TOP"]["status"] != "preview_ready"
        assert worker.next_capture["TOP"] > time.time() + 20
        assert worker.recorders["FRONT"][0] is front_process
        assert worker.status()["cameras"]["FRONT"]["status"] == "preview_ready"
        assert requests["/top"] == 1

        # Exercise a real new connection without spending the configured 30s backoff.
        top_online.set()
        worker.next_capture["TOP"] = 0
        poll_until(lambda: "TOP" in worker.recorders)
        processes.append(worker.recorders["TOP"][0])
        poll_until(lambda: worker.status()["cameras"]["TOP"]["status"] == "preview_ready")
        assert requests["/top"] == 2 and requests["/front"] == 1
        assert (worker.directory / "TOP.jpg").stat().st_mtime > old_preview
        assert json.loads((worker.directory / "live/TOP/session.json").read_text())["session_id"] != session
        assert worker.recorders["FRONT"][0] is front_process
    finally:
        done.set()
        worker.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert all(process.poll() is not None for process in processes)
