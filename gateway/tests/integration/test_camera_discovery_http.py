"""Real HTTP identity discovery on loopback; never contacts a store network."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest

from habitat.vision.camera_discovery import CameraDiscovery, CameraDiscoveryConfig
from habitat.vision.cameras import CameraConfig


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self):
        self.now += 31


def identity(camera_id="TOP", view="top", **changes):
    return {
        "schema_version": 1,
        "device_type": "dfr1172_camera",
        "site_id": "SITE-TEST",
        "gateway_id": "PI-TEST",
        "cage_id": "CAGE-TEST",
        "camera_id": camera_id,
        "view": view,
        "stream_path": "/video_feed",
        **changes,
    }


@pytest.fixture
def identity_network():
    """Two loopback addresses share a port, like cameras on the same LAN."""
    lock = threading.Lock()
    done = threading.Event()
    replies = {"127.0.0.1": None, "127.0.0.2": None}
    requests = []
    servers, threads = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            host = self.server.server_address[0]
            with lock:
                requests.append((host, self.path, self.headers.get("Authorization"),
                                 self.headers.get("Cookie")))
                reply = replies[host]
            if self.path != "/identity" or reply is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if reply == "redirect":
                self.send_response(302)
                self.send_header("Location", "/video_feed")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            slow = reply == "trickle"
            payload = json.dumps(identity() if slow else reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                if slow:
                    # Every byte arrives inside a socket read timeout; only a
                    # total request deadline bounds this response.
                    for byte in payload:
                        if done.wait(.08):
                            break
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    class Network:
        port = None

        def set(self, host, reply):
            with lock:
                replies[host] = reply

        def seen(self):
            with lock:
                return list(requests)

        def url(self, host):
            return f"http://{host}:{self.port}/video_feed"

    network = Network()
    try:
        for host in replies:
            server = ThreadingHTTPServer((host, network.port or 0), Handler)
            server.daemon_threads = True
            network.port = server.server_port
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": .02}, daemon=True)
            servers.append(server)
            threads.append(thread)
            thread.start()
        yield network
    finally:
        done.set()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)


def camera(network, camera_id="TOP", view="top", host="127.0.0.1"):
    return CameraConfig(id=camera_id, cage_id="CAGE-TEST", source_type="http_mjpeg",
                        view=view, url=network.url(host), live_stream=True)


def discovery(network, directory, clock, *, timeout=.4):
    settings = CameraDiscoveryConfig(enabled=True, networks=["127.0.0.0/30"],
                                     port=network.port, interval_s=30,
                                     timeout_s=timeout, max_workers=2)
    return CameraDiscovery(settings, "SITE-TEST", "PI-TEST", directory, monotonic=clock)


def wait_binding(service, cameras, *, idle=None, occupied=(), seconds=4):
    idle = {c.id for c in cameras} if idle is None else idle
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        started = time.monotonic()
        result = service.poll(cameras, idle, occupied)
        assert time.monotonic() - started < .2, "HTTP discovery blocked the camera cycle"
        if result:
            return result
        time.sleep(.01)
    pytest.fail("identity discovery did not resolve a camera")


def wait_rejection(service, cameras, *, occupied=(), seconds=4):
    """Wait for an observable completed round, not an arbitrary sleep."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert service.poll(cameras, {c.id for c in cameras}, occupied) == {}
        states = [service.status(c.id) for c in cameras]
        if all(state in {"identity_not_found", "identity_ambiguous"}
               for state in states):
            return states
        time.sleep(.01)
    pytest.fail("identity discovery did not finish rejection: " + repr(states))


def assert_identity_only(network):
    assert network.seen()
    assert all(path == "/identity" and authorization is None and cookie is None
               for _, path, authorization, cookie in network.seen())


def test_http_identity_v2_resolves_rtsp_without_opening_a_stream(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", identity(schema_version=2, codec="h264", stream_transport="rtsp_tcp",
        stream_port=8554, stream_path="/stream", width=800, height=800, fps=20,
        bitrate_bps=2000000, gop_frames=20, profile="baseline", sps_pps_at_idr=True,
        color_range="limited", color_matrix="bt601",
        stream_url="rtsp://8.8.8.8:8554/stream"))
    configured = CameraConfig(id="TOP", cage_id="CAGE-TEST", source_type="rtsp_h264", view="top",
                             width=800, height=800, fps=20, live_stream=True)
    service = discovery(network, tmp_path, clock)
    try:
        assert wait_binding(service, [configured]) == {"TOP": "rtsp://127.0.0.1:8554/stream"}
        assert_identity_only(network)
        before = len(network.seen())
        service.invalidate("TOP")
        clock.advance()
        assert service.poll([configured], {"TOP"}, {("127.0.0.1", 8554)}) == {}
        wait_rejection(service, [configured], occupied={("127.0.0.1", 8554)})
        assert all(host != "127.0.0.1" for host, *_ in network.seen()[before:])
    finally:
        service.close()


def test_http_identity_moves_without_following_reused_old_address(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", identity())
    config = camera(network)
    service = discovery(network, tmp_path, clock)
    try:
        assert wait_binding(service, [config]) == {"TOP": network.url("127.0.0.1")}
        cache = tmp_path / "camera-bindings.json"
        deadline = time.monotonic() + 2
        while not cache.is_file() and time.monotonic() < deadline:
            time.sleep(.01)
        assert cache.is_file()
        # DHCP gives the old address to a different camera. It must never be
        # accepted merely because its port opens or because it was cached.
        network.set("127.0.0.1", identity("OTHER", "front"))
        network.set("127.0.0.2", identity())
        service.invalidate("TOP")
        clock.advance()
        assert wait_binding(service, [config]) == {"TOP": network.url("127.0.0.2")}
        assert config.url == network.url("127.0.0.1"), "discovery must not mutate store configuration"
        assert_identity_only(network)
    finally:
        service.close()


def test_restart_rechecks_cached_identity_before_returning_binding(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", identity())
    config = camera(network)
    first = discovery(network, tmp_path, clock)
    try:
        assert wait_binding(first, [config]) == {"TOP": network.url("127.0.0.1")}
    finally:
        first.close()
    before = len(network.seen())
    network.set("127.0.0.1", identity(site_id="UNRELATED-SITE"))
    network.set("127.0.0.2", identity())
    restarted = discovery(network, tmp_path, clock)
    try:
        assert wait_binding(restarted, [config]) == {"TOP": network.url("127.0.0.2")}
        assert len(network.seen()) > before, "restart trusted a persisted URL without an HTTP identity check"
        assert_identity_only(network)
    finally:
        restarted.close()


def test_duplicate_http_identities_are_not_bound(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", identity())
    network.set("127.0.0.2", identity())
    service = discovery(network, tmp_path, clock)
    try:
        assert wait_rejection(service, [camera(network)]) == ["identity_ambiguous"]
        assert {host for host, *_ in network.seen()} == {"127.0.0.1", "127.0.0.2"}
        assert_identity_only(network)
    finally:
        service.close()


@pytest.mark.parametrize("reply", [identity(camera_id="UNREGISTERED"),
                                       identity(view="front"), "redirect"])
def test_http_wrong_identity_and_redirect_cannot_bind(identity_network, tmp_path, reply):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", reply)
    service = discovery(network, tmp_path, clock)
    try:
        assert wait_rejection(service, [camera(network)]) == ["identity_not_found"]
        assert_identity_only(network)
    finally:
        service.close()


def test_healthy_camera_host_is_not_probed_for_another_camera(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", identity())
    network.set("127.0.0.2", identity("FRONT", "front"))
    cameras = [camera(network), camera(network, "FRONT", "front", "127.0.0.2")]
    service = discovery(network, tmp_path, clock)
    try:
        assert wait_binding(service, cameras, idle={"TOP"},
                            occupied={("127.0.0.2", network.port)}) == {
                                "TOP": network.url("127.0.0.1")}
        counts = Counter(host for host, *_ in network.seen())
        assert counts["127.0.0.1"] >= 1 and counts["127.0.0.2"] == 0
        assert_identity_only(network)
    finally:
        service.close()


def test_slow_http_body_has_total_deadline_and_bounded_shutdown(identity_network, tmp_path):
    network, clock = identity_network, Clock()
    network.set("127.0.0.1", "trickle")
    service = discovery(network, tmp_path, clock, timeout=.3)
    started = time.monotonic()
    try:
        assert wait_rejection(service, [camera(network)], seconds=2) == ["identity_not_found"]
        assert time.monotonic() - started < 1.5
    finally:
        closing = time.monotonic()
        service.close()
        assert time.monotonic() - closing < 1.5
    assert_identity_only(network)
