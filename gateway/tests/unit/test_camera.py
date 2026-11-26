import subprocess
import os
import time
import threading
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from habitat.vision.cameras import CameraConfig, CameraWorker, video_command


@pytest.mark.parametrize("expected_model", [None, "SMG-A USB-OV5628-A (OV5693, Auto Focus/120deg)"])
def test_camera_waits_without_fabricating_frames_and_rejects_unstable_paths(tmp_path, monkeypatch, expected_model):
    camera = CameraConfig(id="RGB-001", cage_id="CAGE-001", expected_model=expected_model)
    worker = CameraWorker([camera], tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("no hardware must not capture"))
    worker.cycle()
    assert worker.status()["cameras"][camera.id]["status"] == "waiting_usb_port_binding"
    assert worker.status()["cameras"][camera.id]["expected_model"] == expected_model
    assert not list(tmp_path.glob("*.jpg"))
    with pytest.raises(ValidationError):
        CameraConfig(id="RGB-001", cage_id="CAGE-001", device="/dev/video0")
    with pytest.raises(ValidationError):
        CameraConfig(id="RGB-001", cage_id="CAGE-001", device="/dev/v4l/by-path/platform-codec-video-index0")


@pytest.mark.parametrize("url", [
    "https://192.168.1.10/video_feed", "http://camera.local/video_feed",
    "http://8.8.8.8/video_feed", "http://0.0.0.0/video_feed", "http://224.0.0.1/video_feed",
    "http://[::ffff:0.0.0.0]/video_feed", "http://192.168.1.10:0/video_feed",
    "http://192.168.1.10:65536/video_feed", "http://user:password@192.168.1.10/video_feed",
    "http://192.168.1.10/video_feed?token=secret", "http://192.168.1.10/video_feed#secret",
    " http://192.168.1.10/video_feed", "file:///tmp/camera.jpg",
])
def test_network_camera_rejects_nonlocal_or_credential_urls(url):
    with pytest.raises(ValidationError):
        CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", url=url)


def test_camera_source_validation_and_canonical_urls():
    legacy = CameraConfig(id="RGB-001", cage_id="CAGE-001")
    assert (legacy.source_type, legacy.url, legacy.view) == ("uvc", None, None)
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top",
                          url="http://[::ffff:c0a8:010a]:80")
    assert config.url == "http://192.168.1.10/"
    assert CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg",
                        url="http://[fd00:0000::1]:5000/video_feed").url == "http://[fd00::1]:5000/video_feed"
    for fields in ({"url": "http://192.168.1.10/video_feed"},
                   {"source_type": "http_mjpeg", "device": "/dev/v4l/by-id/usb-camera-video-index0"},
                   {"source_type": "rtsp"}, {"view": "side"}):
        with pytest.raises(ValidationError):
            CameraConfig(id="TOP", cage_id="CAGE-A", **fields)


def test_unbound_network_camera_never_opens_a_process(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("unbound source must not open"))
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top", url="")
    worker = CameraWorker([config], tmp_path)
    worker.cycle()
    state = worker.status()["cameras"][config.id]
    assert state["status"] == "waiting_network_camera_binding"
    assert (state["source_type"], state["view"]) == ("http_mjpeg", "top")
    assert state["reader_running"] is False
    assert "url" not in state


def test_http_reader_has_one_timed_input_and_shares_all_outputs(tmp_path):
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg",
                          url="http://192.168.1.10:5000/video_feed", record_video=True, live_stream=True)
    command = video_command(config, tmp_path, tmp_path / "preview.jpg", live=tmp_path / "live")
    assert command.count("-i") == 1
    assert command[command.index("-i")+1] == config.url
    assert command[command.index("-rw_timeout")+1] == "10000000"
    assert command[command.index("-max_redirects")+1] == "0"
    assert "v4l2" not in command
    assert "segment" in command and "hls" in command and "image2" in command


@pytest.mark.parametrize("url", [
    "rtsp://192.168.1.10:8554/stream", "rtsp://127.0.0.1:8554/stream",
    "rtsp://[::ffff:c0a8:010a]:8554/stream",
])
def test_h264_url_is_local_fixed_transport_and_has_explicit_role(url):
    camera = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="rtsp_h264", view="top", url=url)
    assert camera.is_network
    assert camera.url in ("rtsp://192.168.1.10:8554/stream", "rtsp://127.0.0.1:8554/stream")


@pytest.mark.parametrize("fields", [
    {"url": "http://192.168.1.10:8554/stream"}, {"url": "rtsp://192.168.1.10/stream"},
    {"url": "rtsp://192.168.1.10:554/stream"}, {"url": "rtsp://192.168.1.10:8554/other"},
    {"url": "rtsp://8.8.8.8:8554/stream"}, {"url": "rtsp://169.254.1.1:8554/stream"},
    {"url": "rtsp://192.0.2.1:8554/stream"}, {"url": "rtsp://[fd00::1]:8554/stream"},
    {"url": "rtsp://camera.local:8554/stream"}, {"url": "rtsp://u:p@192.168.1.10:8554/stream"},
    {"url": "rtsp://192.168.1.10:8554/stream?url=http://8.8.8.8"},
    {"url": "rtsp://192.168.1.10:8554/stream#fragment"},
    {"width": 801}, {"height": 801}, {"view": None},
    {"device": "/dev/v4l/by-id/usb-camera-video-index0"},
])
def test_h264_url_and_configuration_reject_unregistered_input(fields):
    with pytest.raises(ValidationError):
        CameraConfig(**{**dict(id="TOP", cage_id="CAGE-A", source_type="rtsp_h264", view="top"), **fields})


def test_h264_copy_outputs_share_one_tcp_input_and_only_preview_decodes(tmp_path):
    camera = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="rtsp_h264", view="top",
                          url="rtsp://192.168.1.10:8554/stream", record_video=True, live_stream=True)
    command = video_command(camera, tmp_path, tmp_path / "preview.jpg", live=tmp_path / "live")
    assert command.count("-i") == 1
    assert command[command.index("-rtsp_transport") + 1] == "tcp"
    assert command[command.index("-timeout") + 1] == "10000000"
    assert command[command.index("-protocol_whitelist") + 1] == "tcp"
    assert command[command.index("-fflags") + 1] == "+nobuffer"
    assert command.index("-fflags") < command.index("-i")
    assert command.count("copy") == 2
    assert command.count("-bsf:v") == 2
    metadata = ("h264_metadata=video_full_range_flag=0:colour_primaries=6:"
                "transfer_characteristics=6:matrix_coefficients=6")
    assert command.count(metadata) == 2
    assert "libx264" not in command and "-g" not in command and "-b:v" not in command
    assert command.count("-vf") == 1
    assert command[command.index("-vf") + 1] == "fps=1/30"
    assert "-video_size" not in command and "-framerate" not in command


@pytest.mark.parametrize("source_type", ["uvc", "http_mjpeg"])
def test_legacy_sources_do_not_receive_native_color_metadata(tmp_path, source_type):
    camera = CameraConfig(id="CAM", cage_id="CAGE-A", source_type=source_type,
                          record_video=True, live_stream=True)
    command = video_command(camera, tmp_path, tmp_path / "preview.jpg", live=tmp_path / "live")
    assert "-bsf:v" not in command
    assert "-fflags" not in command


def test_network_stop_does_not_wait_or_start_duplicate_reader(tmp_path, monkeypatch):
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg",
                          url="http://192.168.1.10:5000/video_feed")
    worker = CameraWorker([config], tmp_path)
    signalled = []
    process = SimpleNamespace(poll=lambda: None, send_signal=signalled.append,
                              wait=lambda **k: pytest.fail("network stop must not block shared cycle"))
    worker.recorders[config.id] = (process, None, time.monotonic())
    worker.archive_enabled[config.id] = False
    worker._stop(config.id, wait=False)
    assert signalled and config.id in worker.stopping and config.id not in worker.recorders
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("old reader still stopping"))
    worker.cycle()
    assert worker.status()["cameras"][config.id]["status"] == "waiting_video_frames"


def test_status_rejects_stale_or_exited_network_frames_between_cycles(tmp_path):
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg",
                          url="http://192.168.1.10:5000/video_feed", interval_s=10)
    worker = CameraWorker([config], tmp_path)
    preview = tmp_path / "TOP.jpg"
    preview.write_bytes(b"cached JPEG")
    process = SimpleNamespace(returncode=None)
    process.poll = lambda: process.returncode
    worker.recorders[config.id] = (process, None, time.monotonic())
    worker.states[config.id] = {"status": "preview_ready", "captured_at_epoch": time.time()}
    assert worker.status()["cameras"][config.id]["status"] == "preview_ready"
    assert worker.status()["cameras"][config.id]["reader_running"] is True
    process.returncode = 1
    assert worker.status()["cameras"][config.id]["status"] == "camera_frame_stale"
    assert worker.status()["cameras"][config.id]["reader_running"] is False
    assert worker.status()["cameras"][config.id]["captured_at_epoch"] is None
    process.returncode = None
    old = time.time() - 31
    os.utime(preview, (old, old))
    assert worker.status()["cameras"][config.id]["status"] == "camera_frame_stale"


class DiscoveryStub:
    def __init__(self):
        self.ready, self.calls, self.invalidated = {}, [], []
        self.closed = False

    def poll(self, cameras, idle_ids, occupied_hosts):
        self.calls.append((set(idle_ids), set(occupied_hosts)))
        result, self.ready = self.ready, {}
        return result

    def invalidate(self, camera_id):
        self.invalidated.append(camera_id)

    def status(self, camera_id):
        return "waiting_identity"

    def close(self):
        self.closed = True


class ReaderStub:
    def __init__(self):
        self.returncode, self.signals = None, []

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout):
        self.returncode = 0

    def kill(self):
        self.returncode = -9


@pytest.mark.parametrize("valid", [True, False])
def test_h264_media_check_is_nonblocking_and_never_serves_unverified_media(tmp_path, monkeypatch, valid):
    from habitat.vision import cameras as module

    camera = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="rtsp_h264", view="top",
                          width=800, height=800, fps=20, live_stream=True)
    discovery = DiscoveryStub()
    discovery.ready = {"TOP": "rtsp://192.168.1.10:8554/stream"}
    worker = CameraWorker([camera], tmp_path, discovery=discovery)
    entered, release = threading.Event(), threading.Event()
    reader = ReaderStub()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: reader)

    def verify(path, config):
        assert config.source_type == "rtsp_h264"
        entered.set()
        assert release.wait(2)
        return valid

    monkeypatch.setattr(module, "verify_h264_segment", verify)
    try:
        worker.cycle()
        assert not worker.status()["cameras"]["TOP"]["media_verified"]
        (tmp_path / "live/TOP/seg-0000000000000001.ts").write_bytes(b"local-test-fixture")
        (tmp_path / "TOP.jpg").write_bytes(b"fresh-preview-does-not-prove-h264")
        worker.cycle()
        assert entered.wait(1)
        before = time.monotonic()
        worker.cycle()
        assert time.monotonic() - before < .2
        assert not worker.status()["cameras"]["TOP"]["media_verified"]
        release.set()
        deadline = time.monotonic() + 2
        while worker.h264_checks and time.monotonic() < deadline:
            worker.cycle()
            time.sleep(.005)
        state = worker.status()["cameras"]["TOP"]
        assert state["media_verified"] is valid
        if valid:
            worker._stop("TOP", wait=False)
            assert not worker.status()["cameras"]["TOP"]["media_verified"]
        else:
            assert state["status"] == "capture_failed_check_network_stream"
            assert "TOP" not in worker.recorders
            assert worker.next_capture["TOP"] > time.time()
    finally:
        release.set()
        worker.close()


def test_discovery_requires_identity_before_using_configured_or_changed_address(tmp_path, monkeypatch):
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top",
                          url="http://192.168.1.10:5000/video_feed", live_stream=True)
    discovery = DiscoveryStub()
    worker = CameraWorker([config], tmp_path, discovery=discovery)
    inputs = []

    def launch(command, **kwargs):
        inputs.append(command[command.index("-i") + 1])
        return ReaderStub()

    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.cycle()
    worker.cycle()
    assert inputs == []
    # Waiting must not invalidate an in-flight discovery round every cycle.
    assert discovery.invalidated == []
    discovery.ready = {"TOP": "http://192.168.1.20:5000/video_feed"}
    worker.cycle()
    assert inputs == ["http://192.168.1.20:5000/video_feed"]
    assert config.url == "http://192.168.1.10:5000/video_feed"
    state = worker.status()["cameras"]["TOP"]
    assert state["identity_verified"] and state["network_bound"] and state["reader_running"]
    assert "192.168" not in str(state)
    # A delayed result cannot replace or add a reader for an active camera.
    discovery.ready = {"TOP": "http://192.168.1.99:5000/video_feed"}
    worker.cycle()
    assert len(inputs) == 1
    assert discovery.calls[-1] == (set(), {("192.168.1.20", 5000)})
    worker.close()
    assert discovery.closed


def test_discovery_reader_exit_requires_new_identity_without_blocking_other_camera(tmp_path, monkeypatch):
    configs = [CameraConfig(id=name, cage_id="CAGE-A", source_type="http_mjpeg", view=view, live_stream=True)
               for name, view in (("TOP", "top"), ("FRONT", "front"))]
    discovery = DiscoveryStub()
    discovery.ready = {"TOP": "http://192.168.1.10:5000/video_feed", "FRONT": "http://192.168.1.11:5000/video_feed"}
    worker = CameraWorker(configs, tmp_path, discovery=discovery)
    processes, inputs = [], []

    def launch(command, **kwargs):
        process = ReaderStub()
        processes.append(process)
        inputs.append(command[command.index("-i") + 1])
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    worker.cycle()
    processes[0].returncode = 1
    worker.cycle()
    assert "TOP" in discovery.invalidated
    assert not worker.status()["cameras"]["TOP"]["identity_verified"]
    worker.cycle()
    assert discovery.calls[-1] == (set(), {("192.168.1.11", 5000)})
    worker.next_capture["TOP"] = 0
    worker.cycle()
    assert discovery.calls[-1] == ({"TOP"}, {("192.168.1.11", 5000)})
    assert len(processes) == 2  # No restart using the old verified address.
    assert worker.recorders["FRONT"][0] is processes[1]
    discovery.ready = {"TOP": "http://192.168.1.30:5000/video_feed"}
    worker.cycle()
    assert inputs[-1] == "http://192.168.1.30:5000/video_feed"
    assert len(processes) == 3
    assert configs[0].url is None and configs[1].url is None
    worker.close()


def test_discovery_reserves_stopping_hosts_and_rejects_duplicate_ready_binding(tmp_path, monkeypatch):
    configs = [CameraConfig(id=name, cage_id="CAGE-A", source_type="http_mjpeg", view=view)
               for name, view in (("TOP", "top"), ("FRONT", "front"))]
    discovery = DiscoveryStub()
    discovery.ready = {"TOP": "http://192.168.1.10:5000/video_feed"}
    worker = CameraWorker(configs, tmp_path, discovery=discovery)
    processes = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: processes.append(ReaderStub()) or processes[-1])
    worker.cycle()
    worker._stop("TOP", wait=False)
    discovery.ready = {"FRONT": "http://192.168.1.10:5000/video_feed"}
    worker.cycle()
    assert discovery.calls[-1] == ({"FRONT"}, {("192.168.1.10", 5000)})
    assert len(processes) == 1
    assert "FRONT" in discovery.invalidated
    assert not worker.status()["cameras"]["TOP"]["identity_verified"]
    processes[0].returncode = 0
    worker.cycle()
    discovery.ready = {"FRONT": "http://192.168.1.10:5000/video_feed"}
    worker.cycle()
    assert len(processes) == 2
    worker.close()


def test_discovery_disabled_preserves_legacy_different_paths_on_same_server(tmp_path, monkeypatch):
    configs = [CameraConfig(id=name, cage_id="CAGE-A", source_type="http_mjpeg",
                           url=f"http://192.168.1.10:5000/{name}") for name in ("TOP", "FRONT")]
    worker = CameraWorker(configs, tmp_path)
    processes = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: processes.append(ReaderStub()) or processes[-1])
    worker.cycle()
    assert len(processes) == 2
    assert all(worker.status()["cameras"][camera.id]["reader_running"] for camera in configs)
    worker.close()


def test_failed_reader_launch_cannot_reuse_consumed_identity_result(tmp_path, monkeypatch):
    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top")
    discovery = DiscoveryStub()
    discovery.ready = {"TOP": "http://192.168.1.10:5000/video_feed"}
    worker = CameraWorker([config], tmp_path, discovery=discovery)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise OSError("ffmpeg unavailable")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    worker.cycle()
    assert discovery.invalidated and not worker.network_sources
    assert worker.status()["cameras"]["TOP"]["status"] == "capture_failed_check_ffmpeg"
    worker.next_capture["TOP"] = 0
    worker.cycle()
    assert len(calls) == 1
    assert not worker.status()["cameras"]["TOP"]["identity_verified"]
    worker.close()


def test_prelaunch_filesystem_failure_discards_orphaned_identity(tmp_path, monkeypatch):
    import shutil

    config = CameraConfig(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg", view="top")
    discovery = DiscoveryStub()
    discovery.ready = {"TOP": "http://192.168.1.10:5000/video_feed"}
    worker = CameraWorker([config], tmp_path, discovery=discovery)
    disk_usage = shutil.disk_usage

    def unavailable(path):
        raise OSError("temporary filesystem failure")

    monkeypatch.setattr(shutil, "disk_usage", unavailable)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("fresh identity is required after failure"))
    with pytest.raises(OSError):
        worker.cycle()
    monkeypatch.setattr(shutil, "disk_usage", disk_usage)
    worker.cycle()
    assert not worker.network_sources and not worker.verified_sources
    assert "TOP" in discovery.invalidated
    assert worker.status()["cameras"]["TOP"]["status"] == "waiting_network_camera_binding"
    worker.close()
