import json
import os
import threading
import time

import pytest
from pydantic import ValidationError

from habitat.vision.camera_discovery import CameraDiscovery, CameraDiscoveryConfig, probe_identity
from habitat.vision.cameras import CameraConfig


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def config(**kwargs):
    return CameraDiscoveryConfig(**{**dict(enabled=True, networks=["127.0.0.0/30"],
                                          timeout_s=0.2, max_workers=1), **kwargs})


def camera(**kwargs):
    return CameraConfig(**{**dict(id="TOP", cage_id="CAGE-A", source_type="http_mjpeg",
                                 view="top"), **kwargs})


def identity(**kwargs):
    return {**dict(schema_version=1, device_type="dfr1172_camera", site_id="STORE-A",
                   gateway_id="PI-A", cage_id="CAGE-A", camera_id="TOP", view="top",
                   stream_path="/video_feed"), **kwargs}


def h264_identity(**kwargs):
    return identity(**{**dict(schema_version=2, codec="h264", stream_transport="rtsp_tcp",
        stream_port=8554, stream_path="/stream", width=800, height=800, fps=20,
        bitrate_bps=2000000, gop_frames=20, profile="baseline", sps_pps_at_idr=True,
        color_range="limited", color_matrix="bt601"), **kwargs})


def h264_camera(**kwargs):
    return camera(**{**dict(source_type="rtsp_h264", width=800, height=800, fps=20), **kwargs})


def wait_for(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.005)
    pytest.fail("discovery condition timed out")


def round_result(discovery, cameras, occupied=()):
    ids = {value.id for value in cameras}
    result = discovery.poll(cameras, ids, occupied)
    if result:
        return result
    wait_for(lambda: all(discovery.status(key) in
                         ("identity_verified", "identity_not_found", "identity_ambiguous") for key in ids))
    return discovery.poll(cameras, ids, occupied)


@pytest.mark.parametrize("networks", [
    ["8.8.8.0/24"], ["169.254.1.0/24"], ["100.64.0.0/24"], ["0.0.0.0/0"],
    ["224.0.0.0/24"], ["::1/128"], ["192.168.1.1"], ["192.168.1.1/24"],
    ["192.168.0.0/16"], ["127.0.0.0/24", "127.0.0.1/32"],
    ["192.168.1.0/24", "192.168.1.0/24"], [],
])
def test_networks_must_be_explicit_bounded_private_and_nonoverlapping(networks):
    with pytest.raises(ValidationError):
        CameraDiscoveryConfig(enabled=True, networks=networks)


def test_disabled_discovery_needs_no_networks_and_never_probes(tmp_path):
    discovery = CameraDiscovery(CameraDiscoveryConfig(), "STORE-A", "PI-A", tmp_path,
                                probe=lambda *args: pytest.fail("disabled discovery probed"))
    assert discovery.poll([camera()], {"TOP"}, set()) == {}
    assert discovery.status("TOP") == "disabled"
    discovery.close()
    assert not list(tmp_path.iterdir())


def test_usable_host_limits_and_numeric_configuration():
    assert CameraDiscoveryConfig(enabled=True, networks=["192.168.0.0/22"]).networks
    with pytest.raises(ValidationError):
        CameraDiscoveryConfig(enabled=True, networks=["192.168.0.0/22", "10.0.0.0/30", "127.0.0.1/32"])
    for kwargs in ({"port": True}, {"port": 65536}, {"interval_s": 29}, {"timeout_s": 6},
                   {"timeout_s": float("nan")}, {"max_workers": 33}, {"max_workers": True}):
        with pytest.raises(ValidationError):
            CameraDiscoveryConfig(**kwargs)


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", "1"), ("schema_version", 2),
    ("device_type", "camera"), ("site_id", "STORE-B"), ("gateway_id", "PI-B"),
    ("cage_id", "CAGE-B"), ("camera_id", "FRONT"), ("camera_id", []),
    ("view", "front"), ("stream_path", "http://127.0.0.5/video_feed"),
    ("stream_path", "/video_feed?key=secret"),
])
def test_every_identity_field_must_match_before_binding(tmp_path, field, value):
    body = identity()
    body[field] = value
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=lambda *args: body)
    try:
        assert round_result(discovery, [camera()]) == {}
        assert discovery.status("TOP") == "identity_not_found"
    finally:
        discovery.close()


def test_verified_identity_binds_probed_host_and_persists_atomically(tmp_path):
    body = identity()
    body["host"] = "8.8.8.8"  # Untrusted response metadata cannot supply the stream host.
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
                                probe=lambda host, *args: body if host == "127.0.0.2" else None)
    try:
        assert round_result(discovery, [camera()]) == {"TOP": "http://127.0.0.2:5000/video_feed"}
    finally:
        discovery.close()
    path = tmp_path / "camera-bindings.json"
    persisted = json.loads(path.read_text())
    assert persisted["schema_version"] == 1
    assert list(persisted["bindings"].values()) == ["http://127.0.0.2:5000/video_feed"]
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".camera-bindings-*"))


def test_duplicate_full_identity_is_not_bound(tmp_path):
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=lambda *args: identity())
    try:
        assert round_result(discovery, [camera()]) == {}
        assert discovery.status("TOP") == "identity_ambiguous"
    finally:
        discovery.close()
    assert json.loads((tmp_path / "camera-bindings.json").read_text())["bindings"] == {}


@pytest.mark.parametrize("change", [
    {"schema_version": 1}, {"codec": "hevc"}, {"stream_transport": "rtsp_udp"},
    {"stream_port": 554}, {"stream_port": True}, {"stream_path": "/video_feed"},
    {"stream_path": "rtsp://8.8.8.8/stream"}, {"profile": "main"},
    {"sps_pps_at_idr": False}, {"sps_pps_at_idr": 1},
    {"color_range": None}, {"color_range": True}, {"color_range": "full"}, {"color_range": "tv"},
    {"color_matrix": None}, {"color_matrix": 6}, {"color_matrix": "bt709"},
    {"width": 640}, {"height": 640}, {"fps": 10}, {"fps": 20.0},
    {"bitrate_bps": 255999}, {"bitrate_bps": 4000001}, {"bitrate_bps": 2000000.0},
    {"gop_frames": 0}, {"gop_frames": 41}, {"gop_frames": True},
    {"camera_id": "FRONT"}, {"view": "front"}, {"site_id": "OTHER"},
    {"gateway_id": "OTHER"}, {"cage_id": "OTHER"},
])
def test_h264_identity_rejects_wrong_stream_contract_and_mapping(tmp_path, change):
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
        probe=lambda *args: h264_identity(**change))
    try:
        assert round_result(discovery, [h264_camera()]) == {}
        assert discovery.status("TOP") == "identity_not_found"
    finally:
        discovery.close()


def test_h264_identity_binds_only_probed_host_and_revalidates_cache_after_move(tmp_path):
    active = ["127.0.0.1"]
    seen = []

    def probe(host, *args):
        seen.append(host)
        return h264_identity(url="rtsp://8.8.8.8:8554/stream") if host == active[0] else None

    first = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=probe)
    try:
        assert round_result(first, [h264_camera()]) == {"TOP": "rtsp://127.0.0.1:8554/stream"}
    finally:
        first.close()
    active[0] = "127.0.0.2"
    seen.clear()
    restarted = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=probe)
    try:
        assert round_result(restarted, [h264_camera()]) == {"TOP": "rtsp://127.0.0.2:8554/stream"}
        assert "127.0.0.1" in seen and "127.0.0.2" in seen
    finally:
        restarted.close()


def test_h264_and_legacy_identity_versions_cannot_cross_bind(tmp_path):
    for config_camera, peer in ((h264_camera(), identity()), (camera(), h264_identity())):
        discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=lambda *args: peer)
        try:
            assert round_result(discovery, [config_camera]) == {}
        finally:
            discovery.close()


def test_cache_is_revalidated_after_restart_and_never_replays_wrong_device(tmp_path):
    first = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
                            probe=lambda host, *args: identity() if host.endswith(".2") else None)
    assert round_result(first, [camera()])["TOP"].endswith(".2:5000/video_feed")
    first.close()
    seen = []

    def changed_network(host, *args):
        seen.append(host)
        body = identity()
        if host.endswith(".2"):
            body["cage_id"] = "CAGE-WRONG"
        return body

    second = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=changed_network)
    try:
        assert round_result(second, [camera()]) == {"TOP": "http://127.0.0.1:5000/video_feed"}
        assert seen == ["127.0.0.2", "127.0.0.1"]  # Cache only changes probe order.
    finally:
        second.close()


def test_one_shot_result_is_not_reused_and_scans_are_rate_limited(tmp_path):
    clock, seen = Clock(), []
    responses = {"127.0.0.1": identity()}

    def probe(host, *args):
        seen.append(host)
        return responses.get(host)

    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, monotonic=clock, probe=probe)
    try:
        assert round_result(discovery, [camera()]) == {"TOP": "http://127.0.0.1:5000/video_feed"}
        for _ in range(5):
            assert discovery.poll([camera()], {"TOP"}, ()) == {}
        assert len(seen) == 2
        responses.clear()
        clock.now += 60
        discovery.invalidate("TOP")
        assert round_result(discovery, [camera()]) == {}
        assert len(seen) == 4
    finally:
        discovery.close()


def test_changed_configured_seed_invalidates_persistent_candidate_priority(tmp_path):
    old = camera()
    first = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
                            probe=lambda host, *args: identity() if host.endswith(".2") else None)
    assert round_result(first, [old])
    first.close()
    seen = []

    def probe(host, *args):
        seen.append(host)
        return identity() if host.endswith(".1") else None

    new = camera(url="http://127.0.0.1:5000/video_feed")
    second = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=probe)
    try:
        assert round_result(second, [new]) == {"TOP": "http://127.0.0.1:5000/video_feed"}
        assert seen[0] == "127.0.0.1"
    finally:
        second.close()
    assert len(json.loads((tmp_path / "camera-bindings.json").read_text())["bindings"]) == 1


@pytest.mark.parametrize("occupied", [{("127.0.0.1", 5000)}, {("127.0.0.1", 8554)}, {"127.0.0.1"}])
def test_running_or_stopping_reader_hosts_are_never_probed(tmp_path, occupied):
    seen = []

    def probe(host, *args):
        seen.append(host)
        return identity()

    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=probe)
    try:
        assert round_result(discovery, [camera()], occupied) == {"TOP": "http://127.0.0.2:5000/video_feed"}
        assert seen == ["127.0.0.2"]
    finally:
        discovery.close()


def test_newly_occupied_host_invalidates_a_completed_result(tmp_path):
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
                                probe=lambda host, *args: identity() if host.endswith(".1") else None)
    try:
        assert discovery.poll([camera()], {"TOP"}, ()) == {}
        wait_for(lambda: discovery.status("TOP") == "identity_verified")
        assert discovery.poll([camera()], {"TOP"}, {("127.0.0.1", 5000)}) == {}
        assert discovery.poll([camera()], {"TOP"}, ()) == {}  # Ready result was discarded.
    finally:
        discovery.close()


def test_poll_is_nonblocking_and_invalidated_inflight_round_cannot_bind(tmp_path):
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_probe(host, *args):
        calls.append(host)
        started.set()
        assert release.wait(2)
        return identity() if host.endswith(".1") else None

    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=slow_probe)
    try:
        before = time.monotonic()
        assert discovery.poll([camera()], {"TOP"}, ()) == {}
        assert time.monotonic() - before < 0.1
        assert started.wait(1)
        for _ in range(10):
            assert discovery.poll([camera()], {"TOP"}, ()) == {}
        assert len(calls) == 1
        discovery.invalidate("TOP")
        discovery.poll([camera()], {"TOP"}, ())
        release.set()
        discovery._thread.join(2)
        assert discovery.poll([camera()], {"TOP"}, ()) == {}
        assert discovery.status("TOP") == "waiting_scan"
    finally:
        release.set()
        discovery.close()


def test_missing_role_uvc_and_no_idle_camera_do_not_schedule(tmp_path):
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path,
                                probe=lambda *args: pytest.fail("ineligible camera probed"))
    try:
        assert discovery.poll([camera()], set(), ()) == {}
        no_view = camera().model_copy(update={"view": None})
        usb = CameraConfig(id="USB", cage_id="CAGE-A", view="top")
        assert discovery.poll([no_view, usb], {"TOP", "USB"}, ()) == {}
    finally:
        discovery.close()


def test_bad_cache_does_not_fail_gateway_or_authorize_a_binding(tmp_path):
    path = tmp_path / "camera-bindings.json"
    path.write_text('{"schema_version":1,"bindings":{"bad":"http://8.8.8.8/video_feed"}}')
    discovery = CameraDiscovery(config(), "STORE-A", "PI-A", tmp_path, probe=lambda *args: None)
    try:
        assert round_result(discovery, [camera()]) == {}
    finally:
        discovery.close()


def test_public_address_probe_is_rejected_without_network(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: pytest.fail("public IP probed"))
    assert probe_identity("8.8.8.8", 5000, 0.1) is None
