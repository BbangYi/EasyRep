import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from edge.models import Binding, Gateway
from .models import Enclosure, Store, User


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

    def tearDown(self):
        self.environment.stop()
        self.file.cleanup()

    def inventory(self):
        return {
            camera: {"id": camera, "cage_id": "CAGE-001", "fresh": True, "status": "live"}
            for camera in ("RGB-001", "CAGE-001-FRONT")
        }

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
            outsider = User.objects.create_user(username="camera-outsider", display_name="외부", role="user")
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
