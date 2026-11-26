import json
import tempfile
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from edge.models import Binding, Gateway
from .models import Enclosure, Store, User
from . import camera_ir


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CameraIntegrationTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="카메라 검증", edge_site_id="STORE-001")
        self.gateway = Gateway.objects.create(
            store=self.store, edge_gateway_id="PI-001", token_digest="camera-test-only"
        )
        self.cage = Enclosure.objects.create(
            id="camera-test", store=self.store, name="검증 사육장", edge_cage_id="CAGE-001"
        )
        Binding.objects.create(enclosure=self.cage, gateway=self.gateway)
        self.owner = User.objects.create_user(username="camera-owner", display_name="관리자", role="owner")
        self.client.force_login(self.owner)
        self.file = tempfile.TemporaryDirectory()
        self.config = Path(self.file.name) / "camera.json"
        self.config.write_text(json.dumps({
            "gateway": {"base_url": "https://pi.example", "site_id": "STORE-001", "gateway_id": "PI-001", "cage_ids": ["CAGE-001"]},
            "camera_roles": {"CAGE-001": {"top": "RGB-001", "front": "CAGE-001-FRONT"}},
            "credentials": {"viewer_key": "test-view", "control_key": "test-control"},
        }))
        self.environment = patch.dict("os.environ", {"HABITAT_CAMERA_IR_CONFIG": str(self.config)})
        self.environment.start()
        self.cache = camera_ir.InventoryCache()
        self.cache_patch = patch("habitat.camera_ir._inventory_cache", self.cache)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.environment.stop()
        self.file.cleanup()

    def inventory(self):
        return {
            camera: {"id": camera, "cage_id": "CAGE-001", "fresh": True, "status": "live"}
            for camera in ("RGB-001", "CAGE-001-FRONT")
        }

    def pi(self, *, fresh=True):
        self.pi_inventory = {"site_id": "STORE-001", "gateway_id": "PI-001",
            "cage_ids": ["CAGE-001"], "cameras": [
                {**row, "fresh": fresh} for row in self.inventory().values()]}

        def request(path, **kwargs):
            if path == "/camera/api/cameras":
                return 200, json.dumps(self.pi_inventory).encode()
            if path.endswith(".m3u8"):
                return 200, b"#EXTM3U\n#EXTINF:2,\nb2274a89-8f2a-4e2b-a1be-309f3ba80d44/12.ts\n"
            return 200, b"bounded-media-fixture"

        return Mock(request=Mock(side_effect=request))

    def media_url(self):
        return "/api/enclosures/camera-test/camera/hls/RGB-001/b2274a89-8f2a-4e2b-a1be-309f3ba80d44/12.ts"

    def inventory_requests(self, client):
        return sum(call.args[0] == "/camera/api/cameras" for call in client.request.call_args_list)

    def test_camera_list_requires_matching_cage_and_user_scope(self):
        with patch("habitat.camera_ir._inventory", return_value=self.inventory()):
            response = self.client.get("/api/enclosures/camera-test/camera/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["cameras"]), 2)
            self.cage.edge_cage_id = "CAGE-002"
            self.cage.save()
            self.assertEqual(self.client.get("/api/enclosures/camera-test/camera/").status_code, 404)
            self.cage.edge_cage_id = "CAGE-001"
            self.cage.save()
            other_store = Store.objects.create(name="다른 매장", edge_site_id="STORE-002")
            outsider = User.objects.create_user(username="camera-outsider", display_name="외부", role="user", store=other_store)
            self.client.force_login(outsider)
            self.assertEqual(self.client.get("/api/enclosures/camera-test/camera/").status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get("/api/enclosures/camera-test/camera/").status_code, 401)

    def test_unbound_gateway_camera_is_owner_only_and_stays_cage001(self):
        with patch("habitat.camera_ir._inventory", return_value=self.inventory()):
            response = self.client.get("/api/camera/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["cageId"], "CAGE-001")
            self.assertEqual(response.json()["cameras"][0]["playlist"], "/api/camera/hls/RGB-001/index.m3u8")
            manager = User.objects.create_user(username="camera-manager", display_name="매장", role="manager", store=self.store)
            self.client.force_login(manager)
            self.assertEqual(self.client.get("/api/camera/").status_code, 403)

    def test_playlist_rejects_external_segment_uri(self):
        playlist = b"#EXTM3U\n#EXTINF:4,\nhttps://other.example/video.ts\n"
        with patch("habitat.camera_ir._inventory", return_value=self.inventory()), patch("habitat.camera_ir._client") as client:
            client.return_value.request.return_value = (200, playlist)
            response = self.client.get("/api/enclosures/camera-test/camera/hls/RGB-001/index.m3u8")
            self.assertEqual(response.status_code, 502)
            self.assertEqual(client.return_value.request.call_count, 1)

    def test_playlist_preserves_relative_segments(self):
        playlist = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:4,\nb2274a89-8f2a-4e2b-a1be-309f3ba80d44/12.ts\n"
        with patch("habitat.camera_ir._inventory", return_value=self.inventory()), patch("habitat.camera_ir._client") as client:
            client.return_value.request.return_value = (200, playlist)
            response = self.client.get("/api/camera/hls/RGB-001/index.m3u8")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"b2274a89-8f2a-4e2b-a1be-309f3ba80d44/12.ts", response.content)
            self.assertEqual(self.client.get("/api/camera/hls/OTHER/index.m3u8").status_code, 404)

    def test_ir_command_is_bounded_and_requires_role(self):
        with patch("habitat.camera_ir._inventory", return_value=self.inventory()), patch("habitat.camera_ir._client") as client:
            client.return_value.request.return_value = (202, b'{"cage_id":"CAGE-001","status":"starting"}')
            with patch("habitat.camera_ir._json", return_value={"can_control": True, "csrf_token": "test-csrf"}):
                url = "/api/enclosures/camera-test/camera/ir/command/"
                invalid = self.client.post(url, data=json.dumps({"action": "on", "seconds": 900}), content_type="application/json")
                self.assertEqual(invalid.status_code, 400)
                accepted = self.client.post(url, data=json.dumps({"action": "on"}), content_type="application/json")
                self.assertEqual(accepted.status_code, 202)
                args = client.return_value.request.call_args
                self.assertEqual(json.loads(args.kwargs["data"]), {"action": "on", "seconds": 300})
            user = User.objects.create_user(username="camera-user", display_name="사용자", role="user", store=self.store)
            user.enclosures.add(self.cage)
            self.client.force_login(user)
            self.assertEqual(self.client.post(url, data='{"action":"off"}', content_type="application/json").status_code, 403)

    def test_media_reuses_binding_but_camera_status_stays_live(self):
        pi = self.pi()
        with patch("habitat.camera_ir._client", return_value=pi):
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            self.assertEqual(self.inventory_requests(pi), 1)
            self.assertEqual(pi.request.call_count, 3)
            self.pi_inventory["cameras"][0]["fresh"] = False
            listing = self.client.get("/api/enclosures/camera-test/camera/")
            self.assertFalse(listing.json()["cameras"][0]["fresh"])
            self.assertEqual(self.inventory_requests(pi), 2)

    def test_warm_cache_never_bypasses_scope_or_gateway_binding(self):
        pi = self.pi()
        with patch("habitat.camera_ir._client", return_value=pi):
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            calls = pi.request.call_count
            other = Store.objects.create(name="외부 매장", edge_site_id="STORE-OTHER")
            outsider = User.objects.create_user(username="media-outsider", role="manager", store=other)
            self.client.force_login(outsider)
            self.assertEqual(self.client.get(self.media_url()).status_code, 404)
            self.client.force_login(self.owner)
            self.gateway.active = False
            self.gateway.save()
            self.assertEqual(self.client.get(self.media_url()).status_code, 404)
            self.assertEqual(pi.request.call_count, calls)

    def test_config_key_rotation_cannot_reuse_old_inventory(self):
        pi = self.pi()
        with patch("habitat.camera_ir._client", return_value=pi):
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            config = json.loads(self.config.read_text())
            config["credentials"]["viewer_key"] = "rotated-viewer-test-key"
            self.config.write_text(json.dumps(config))
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            self.assertEqual(self.inventory_requests(pi), 2)
            config["camera_roles"]["CAGE-001"]["top"] = "RGB-OTHER"
            self.config.write_text(json.dumps(config))
            self.assertEqual(self.client.get(self.media_url()).status_code, 404)
            self.assertEqual(self.inventory_requests(pi), 2)

    def test_identity_mismatch_invalidates_previously_valid_binding(self):
        pi = self.pi()
        with patch("habitat.camera_ir._client", return_value=pi):
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            self.pi_inventory["site_id"] = "STORE-OTHER"
            self.assertEqual(self.client.get("/api/enclosures/camera-test/camera/").status_code, 503)
            self.pi_inventory["site_id"] = "STORE-001"
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            self.assertEqual(self.inventory_requests(pi), 3)

    def test_duplicate_or_wrong_cage_inventory_never_authorizes_media(self):
        for variant in ("duplicate", "wrong_cage", "malformed_id"):
            pi = self.pi()
            if variant == "duplicate":
                self.pi_inventory["cameras"].append(dict(self.pi_inventory["cameras"][0]))
            elif variant == "wrong_cage":
                self.pi_inventory["cameras"][0]["cage_id"] = "CAGE-OTHER"
            else:
                self.pi_inventory["cameras"][0]["id"] = []
            with self.subTest(variant=variant), patch("habitat.camera_ir._client", return_value=pi):
                response = self.client.get(self.media_url())
                self.assertEqual(response.status_code, 503)
                self.assertEqual(pi.request.call_count, 1)
                self.assertEqual(response.json()["error"], "camera_identity_mismatch")

    def test_cached_binding_does_not_hide_media_failure_or_assert_freshness(self):
        pi = self.pi(fresh=False)
        with patch("habitat.camera_ir._client", return_value=pi):
            self.assertEqual(self.client.get(self.media_url()).status_code, 200)
            for status in (404, 503):
                pi.request.side_effect = camera_ir.CameraError("camera_upstream_unavailable", status)
                response = self.client.get(self.media_url())
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"], "camera_upstream_unavailable")
                self.assertEqual(response["X-Accel-Buffering"], "no")

    def test_hls_headers_request_id_and_logs_do_not_include_secrets(self):
        pi = self.pi()
        with patch("habitat.camera_ir._client", return_value=pi), self.assertLogs("habitat.camera_ir", level="INFO") as logs:
            response = self.client.get(self.media_url() + "?token=never-log-query",
                HTTP_X_REQUEST_ID="request-123")
            invalid = self.client.get(self.media_url(), HTTP_X_REQUEST_ID="invalid/token=never-log-header")
        self.assertEqual(response["X-Request-ID"], "request-123")
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertRegex(invalid["X-Request-ID"], r"^[0-9a-f]{32}$")
        combined = "\n".join(logs.output)
        for secret in ("never-log-query", "never-log-header", "test-view", "test-control", "pi.example"):
            self.assertNotIn(secret, combined)
        self.assertIn('"response_status":200', combined)
        self.assertIn('"inventory_cache":"hit"', combined)
        self.assertIn('"session_id":"b2274a89-8f2a-4e2b-a1be-309f3ba80d44"', combined)
        self.assertIn('"sequence":12', combined)

    def test_media_authentication_and_ir_csrf_are_still_required(self):
        self.client.logout()
        with patch("habitat.camera_ir._client") as client:
            self.assertEqual(self.client.get(self.media_url()).status_code, 401)
            client.assert_not_called()
            csrf_client = Client(enforce_csrf_checks=True)
            csrf_client.force_login(self.owner)
            response = csrf_client.post("/api/enclosures/camera-test/camera/ir/command/",
                data='{"action":"off"}', content_type="application/json")
            self.assertEqual(response.status_code, 403)
            client.assert_not_called()


class InventoryCacheTests(SimpleTestCase):
    def trace(self):
        return camera_ir.HlsRequest(RequestFactory().get("/hls"), "segment", "RGB-001")

    def test_expiry_and_bounded_capacity(self):
        clock = [0.0]
        cache = camera_ir.InventoryCache(ttl=3, max_entries=2, clock=lambda: clock[0])
        load = Mock(return_value={"RGB-001": {"fresh": False}})
        self.assertEqual(cache.get("a", load, self.trace()), frozenset({"RGB-001"}))
        cache.get("a", load, self.trace())
        self.assertEqual(load.call_count, 1)
        clock[0] = 3.01
        cache.get("a", load, self.trace())
        self.assertEqual(load.call_count, 2)
        cache.get("b", load, self.trace())
        cache.get("c", load, self.trace())
        self.assertEqual(list(cache.entries), ["b", "c"])

    def test_single_flight_and_waiting_request_budget(self):
        cache = camera_ir.InventoryCache()
        started, release = threading.Event(), threading.Event()
        calls = []

        def load():
            calls.append(True)
            started.set()
            self.assertTrue(release.wait(2))
            return {"RGB-001": {}}

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, "same", load, self.trace())
            self.assertTrue(started.wait(1))
            waiting = self.trace()
            second = pool.submit(cache.get, "same", load, waiting)
            deadline = time.monotonic() + 1
            while waiting.inventory_cache != "wait" and time.monotonic() < deadline:
                time.sleep(.001)
            try:
                self.assertEqual(waiting.inventory_cache, "wait")
                expired = self.trace()
                expired.deadline = time.monotonic() + .01
                with self.assertRaises(camera_ir.CameraError):
                    cache.get("same", load, expired)
            finally:
                release.set()
            self.assertEqual(first.result(), second.result())
        self.assertEqual(len(calls), 1)

    def test_expired_value_not_served_when_refresh_fails(self):
        clock = [0.0]
        cache = camera_ir.InventoryCache(clock=lambda: clock[0])
        cache.get("key", lambda: {"RGB-001": {}}, self.trace())
        clock[0] = 4
        with self.assertRaises(camera_ir.CameraError):
            cache.get("key", Mock(side_effect=camera_ir.CameraError("camera_identity_mismatch")), self.trace())
        self.assertNotIn("key", cache.entries)

    def test_concurrent_fill_failure_is_shared_and_pending_capacity_is_bounded(self):
        cache = camera_ir.InventoryCache(max_entries=1)
        started, release = threading.Event(), threading.Event()
        calls = []

        def fail():
            calls.append(True)
            started.set()
            self.assertTrue(release.wait(2))
            raise camera_ir.CameraError("camera_identity_mismatch")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, "same", fail, self.trace())
            self.assertTrue(started.wait(1))
            waiting = self.trace()
            second = pool.submit(cache.get, "same", fail, waiting)
            deadline = time.monotonic() + 1
            while waiting.inventory_cache != "wait" and time.monotonic() < deadline:
                time.sleep(.001)
            blocked_load = Mock(return_value={"OTHER": {}})
            try:
                self.assertEqual(waiting.inventory_cache, "wait")
                with self.assertRaises(camera_ir.CameraError):
                    cache.get("other", blocked_load, self.trace())
                blocked_load.assert_not_called()
                self.assertEqual(len(cache.entries), 1)
            finally:
                release.set()
            for future in (first, second):
                with self.assertRaises(camera_ir.CameraError) as error:
                    future.result()
                self.assertEqual(error.exception.code, "camera_identity_mismatch")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(cache.entries), 0)

    def test_invalidation_cannot_be_undone_by_an_inflight_fill(self):
        cache = camera_ir.InventoryCache()
        started, release = threading.Event(), threading.Event()

        def load():
            started.set()
            self.assertTrue(release.wait(2))
            return {"RGB-001": {}}

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, "key", load, self.trace())
            self.assertTrue(started.wait(1))
            waiting = self.trace()
            second = pool.submit(cache.get, "key", load, waiting)
            deadline = time.monotonic() + 1
            while waiting.inventory_cache != "wait" and time.monotonic() < deadline:
                time.sleep(.001)
            try:
                self.assertEqual(waiting.inventory_cache, "wait")
                cache.invalidate("key")
            finally:
                release.set()
            for future in (first, second):
                with self.assertRaises(camera_ir.CameraError):
                    future.result()
        self.assertNotIn("key", cache.entries)

    def test_completed_fill_invalidated_or_expired_before_waiter_resumes(self):
        for change in ("invalidate", "expire"):
            with self.subTest(change=change):
                clock = [0.0]
                cache = camera_ir.InventoryCache(clock=lambda: clock[0])
                loading, finish_load = threading.Event(), threading.Event()
                waiting, filled, resume_waiter = threading.Event(), threading.Event(), threading.Event()

                class GatedReady:
                    """Pause only the waiter after it observes a completed fill."""
                    def __init__(self):
                        self.event = threading.Event()

                    def is_set(self):
                        return self.event.is_set()

                    def set(self):
                        self.event.set()

                    def wait(self, timeout):
                        waiting.set()
                        if not self.event.wait(timeout):
                            return False
                        filled.set()
                        return resume_waiter.wait(2)

                def load():
                    loading.set()
                    self.assertTrue(finish_load.wait(2))
                    return {"RGB-001": {}}

                with ThreadPoolExecutor(max_workers=2) as pool:
                    owner = pool.submit(cache.get, "key", load, self.trace())
                    try:
                        self.assertTrue(loading.wait(1))
                        with cache.lock:
                            cache.entries["key"]["ready"] = GatedReady()
                        waiter = pool.submit(cache.get, "key", load, self.trace())
                        self.assertTrue(waiting.wait(1))
                        finish_load.set()
                        self.assertEqual(owner.result(timeout=1), frozenset({"RGB-001"}))
                        self.assertTrue(filled.wait(1))
                        if change == "invalidate":
                            cache.invalidate("key")
                        else:
                            clock[0] = 3.01
                        resume_waiter.set()
                        with self.assertRaises(camera_ir.CameraError):
                            waiter.result(timeout=1)
                    finally:
                        finish_load.set()
                        resume_waiter.set()


class PiClientDiagnosticsTests(SimpleTestCase):
    class Response:
        status = 200

        def __init__(self, body=b"ok"):
            self.body = body

        def read(self, amount):
            return self.body[:amount]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def test_remaining_budget_shared_by_login_inventory_and_media(self):
        clock, timeouts = [100.0], []
        client = camera_ir.PiClient("https://pi.example", "private-viewer-key")

        def opened(request, timeout):
            timeouts.append(timeout)
            self.assertEqual(request.get_header("X-request-id"), "trace-456")
            clock[0] += 2 if len(timeouts) == 1 else 3
            return self.Response()

        client.opener = Mock(open=Mock(side_effect=opened))
        with patch("habitat.camera_ir.time.monotonic", side_effect=lambda: clock[0]):
            trace = camera_ir.HlsRequest(RequestFactory().get("/", HTTP_X_REQUEST_ID="trace-456"), "segment", "RGB-001")
            client.request("/camera/api/cameras", trace=trace)
            client.request("/camera/hls/RGB-001/segment.ts", trace=trace)
            with self.assertRaises(camera_ir.CameraError):
                client.request("/camera/hls/RGB-001/other.ts", trace=trace)
        self.assertEqual(timeouts, [6, 6, 3])
        self.assertEqual([call["kind"] for call in trace.upstream[:3]], ["login", "inventory", "segment"])

    def test_upstream_failure_logs_status_not_exception_or_key(self):
        client = camera_ir.PiClient("https://pi.example", "never-log-credential")
        client.logged_in = True
        client.opener = Mock(open=Mock(side_effect=urllib.error.HTTPError(
            "https://pi.example/secret-query", 404, "never-log-error", {}, None)))
        trace = camera_ir.HlsRequest(RequestFactory().get("/"), "segment", "RGB-001")
        with self.assertRaises(camera_ir.CameraError) as error:
            client.request("/camera/hls/RGB-001/segment.ts", trace=trace)
        self.assertEqual(error.exception.status, 404)
        with self.assertLogs("habitat.camera_ir", level="INFO") as logs:
            trace.finish(404)
        self.assertEqual(trace.upstream[0]["status"], 404)
        self.assertNotIn("never-log", "\n".join(logs.output))
        self.assertNotIn("pi.example", "\n".join(logs.output))

    def test_untraced_ir_post_does_not_gain_retry_or_request_headers(self):
        client = camera_ir.PiClient("https://pi.example", "control-test-key")
        client.logged_in = True
        client.opener = Mock(open=Mock(side_effect=urllib.error.HTTPError(
            "https://pi.example", 503, "unavailable", {}, None)))
        with self.assertRaises(camera_ir.CameraError):
            client.request("/camera/api/ir/CAGE-001", data=b'{"action":"on"}')
        self.assertEqual(client.opener.open.call_count, 1)
        self.assertIsNone(client.opener.open.call_args.args[0].get_header("X-request-id"))

    def test_media_response_size_remains_bounded(self):
        client = camera_ir.PiClient("https://pi.example", "viewer-test-key")
        client.logged_in = True
        client.opener = Mock(open=Mock(return_value=self.Response(b"oversized")))
        with self.assertRaises(camera_ir.CameraError) as error:
            client.request("/camera/hls/RGB-001/segment.ts", max_bytes=4)
        self.assertEqual(error.exception.status, 502)

    def test_hls_reauthentication_does_not_reset_request_budget(self):
        clock, calls = [100.0], []
        client = camera_ir.PiClient("https://pi.example", "viewer-test-key")
        client.logged_in = True

        def opened(request, timeout):
            calls.append(timeout)
            clock[0] += 3
            if len(calls) == 1:
                raise urllib.error.HTTPError("https://pi.example", 401, "expired", {}, None)
            return self.Response()

        client.opener = Mock(open=Mock(side_effect=opened))
        with patch("habitat.camera_ir.time.monotonic", side_effect=lambda: clock[0]):
            trace = camera_ir.HlsRequest(RequestFactory().get("/"), "segment", "RGB-001")
            client.request("/camera/hls/RGB-001/segment.ts", trace=trace)
        self.assertEqual(calls, [8, 5, 2])
        self.assertEqual([item["status"] for item in trace.upstream], [401, 200, 200])

    def test_trace_does_not_log_untyped_or_unbounded_media_identifiers(self):
        trace = camera_ir.HlsRequest(RequestFactory().get("/"), "segment",
            "invalid/private-camera", session_id="never-log-session", sequence=2**63)
        with self.assertLogs("habitat.camera_ir", level="INFO") as logs:
            trace.finish(404)
        payload = json.loads(logs.records[0].getMessage().removeprefix("camera_hls "))
        self.assertIsNone(payload["camera_id"])
        self.assertIsNone(payload["session_id"])
        self.assertIsNone(payload["sequence"])
