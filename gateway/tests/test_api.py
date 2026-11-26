from uuid import uuid4
from habitat_gateway import __version__

from fastapi.testclient import TestClient
import pytest

from habitat_gateway.api import create_app


def test_camera_pair_configuration_is_scoped_and_legacy_compatible(settings):
    from habitat_gateway.config import Settings
    from pydantic import ValidationError

    base = settings.model_dump()
    second = {**base["cages"][0], "id": "CAGE-002", "node_id": "NODE-002"}
    base["cages"].append(second)
    base["cameras"] = [
        {"id": "CAGE-001-TOP", "cage_id": "CAGE-001", "source_type": "http_mjpeg",
         "view": "top", "url": "http://192.168.10.41:5000/video_feed"},
        {"id": "CAGE-001-FRONT", "cage_id": "CAGE-001", "source_type": "http_mjpeg",
         "view": "front", "url": "http://192.168.10.42:5000/video_feed"},
        {"id": "CAGE-002-TOP", "cage_id": "CAGE-002", "source_type": "http_mjpeg", "view": "top"},
        {"id": "LEGACY", "cage_id": "CAGE-001"},
    ]
    configured = Settings.model_validate(base)
    assert len(configured.cameras) == 4
    assert configured.cameras[-1].source_type == "uvc"
    assert configured.cameras[-1].view is None
    base["cameras"][1]["view"] = "top"
    with pytest.raises(ValidationError, match="views must be unique"):
        Settings.model_validate(base)
    base["cameras"][1]["view"] = "front"
    base["cameras"][1]["url"] = base["cameras"][0]["url"]
    with pytest.raises(ValidationError, match="unique network sources"):
        Settings.model_validate(base)
    base["cameras"][0]["url"] = "http://192.168.10.41/"
    base["cameras"][1]["url"] = "http://192.168.10.41:80"
    with pytest.raises(ValidationError, match="unique network sources"):
        Settings.model_validate(base)


def test_camera_discovery_is_opt_in_and_requires_registered_views(settings):
    from habitat_gateway.config import Settings
    from pydantic import ValidationError

    assert settings.camera_discovery.enabled is False
    base = settings.model_dump()
    base["camera_discovery"] = {"enabled": True, "networks": ["192.168.10.0/24"]}
    base["cameras"] = [{"id": "TOP", "cage_id": "CAGE-001", "source_type": "http_mjpeg"}]
    with pytest.raises(ValidationError, match="explicit top/front"):
        Settings.model_validate(base)
    base["cameras"][0]["view"] = "top"
    configured = Settings.model_validate(base)
    assert configured.camera_discovery.enabled
    assert configured.cameras[0].url is None


def test_h264_camera_configuration_requires_identity_discovery(settings):
    from habitat_gateway.config import Settings
    from pydantic import ValidationError

    base = settings.model_dump()
    base["cameras"] = [{"id": "TOP", "cage_id": "CAGE-001", "source_type": "rtsp_h264",
                        "view": "top", "width": 800, "height": 800, "fps": 20}]
    with pytest.raises(ValidationError, match="requires camera_discovery"):
        Settings.model_validate(base)
    base["camera_discovery"] = {"enabled": True, "networks": ["192.168.10.0/24"]}
    configured = Settings.model_validate(base)
    assert configured.cameras[0].source_type == "rtsp_h264"
    assert configured.cameras[0].url is None
    base["video_upload"] = {"enabled": True, "endpoint": "https://saas.test/v1/edge/video"}
    with pytest.raises(ValidationError, match="not video_upload"):
        Settings.model_validate(base)


def test_camera_discovery_wiring_uses_gateway_identity_and_closes_with_app(settings, monkeypatch, tmp_path):
    import habitat_gateway.api as api
    from habitat.vision.cameras import CameraConfig
    from habitat.vision.camera_discovery import CameraDiscoveryConfig

    captured = {}

    class Discovery:
        def __init__(self, config, site_id, gateway_id, directory):
            captured.update(config=config, site_id=site_id, gateway_id=gateway_id, directory=directory, closed=False)

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(api, "CameraDiscovery", Discovery)
    settings = settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3"),
        "camera_discovery": CameraDiscoveryConfig(enabled=True, networks=["192.168.10.0/24"]),
        "cameras": [CameraConfig(id="TOP", cage_id="CAGE-001", source_type="http_mjpeg", view="top")]})
    with TestClient(api.create_app(settings, run_worker=False)) as client:
        assert client.get("/health").status_code == 200
        assert captured["site_id"] == settings.site_id and captured["gateway_id"] == settings.gateway_id
        assert captured["directory"] == tmp_path / "cameras"
        assert not captured["closed"]
    assert captured["closed"]


def test_snapshot_rechecks_worker_freshness_before_serving_cached_frame(settings, monkeypatch, tmp_path):
    import habitat_gateway.api as api
    from habitat.vision.cameras import CameraConfig, CameraWorker

    camera = CameraConfig(id="TOP", cage_id="CAGE-001", source_type="http_mjpeg", view="top")
    settings = settings.model_copy(update={"cameras": [camera], "database": str(tmp_path / "gateway.sqlite3")})

    class StaleWorker(CameraWorker):
        def __init__(self, configs, directory):
            super().__init__(configs, directory)
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / "TOP.jpg").write_bytes(b"old-private-frame")
            self.states["TOP"] = {"status": "preview_ready", "captured_at_epoch": 1}

        def status(self):
            return {"cameras": {"TOP": {"status": "camera_frame_stale"}}}

    monkeypatch.setattr(api, "CameraWorker", StaleWorker)
    with TestClient(api.create_app(settings, run_worker=False)) as client:
        response = client.get("/v1/cameras/TOP/snapshot")
        assert response.status_code == 503
        assert b"old-private-frame" not in response.content


def test_api_command_roundtrip_validation_and_simulation(settings):
    app = create_app(settings, run_worker=False)
    with TestClient(app) as client:
        assert client.get("/health").json()["transport"] == "simulated"
        cage = client.get("/v1/cages/CAGE-001").json()
        assert cage["telemetry"]["data_source"] == "simulation"
        assert client.get("/v1/cages/unknown").status_code == 404
        request = {"request_id": str(uuid4()), "actuator_id": "fan", "action": "on", "duration_s": 5}
        response = client.post("/v1/cages/CAGE-001/commands", json=request)
        assert response.status_code == 202
        assert response.json()["status"] == "published"
        app.state.gateway.transport.step()
        assert client.get(f"/v1/commands/{request['request_id']}").json()["status"] == "applied"
        assert client.post("/v1/cages/CAGE-001/commands", json=request).json()["status"] == "applied"
        assert client.post("/v1/cages/CAGE-001/commands", json={**request, "duration_s": 6}).status_code == 409
        request = {**request, "request_id": str(uuid4()), "duration_s": 0}
        assert client.post("/v1/cages/CAGE-001/commands", json=request).status_code == 422
        response = client.patch("/v1/simulation/cages/CAGE-001/readings", json={"T1": {"value": 29, "quality": "valid"}})
        assert response.status_code == 200
        request = {**request, "request_id": str(uuid4()), "actuator_id": "heater", "duration_s": 5}
        assert client.post("/v1/cages/CAGE-001/commands", json=request).status_code == 409
        assert client.put("/v1/cages/CAGE-001/mode", json={"mode": "auto"}).status_code == 200
        assert client.post("/v1/cages/CAGE-001/stop").json()["mode"] == "manual"
        assert client.get("/v1/audit").json()
        assert client.get("/v1/cages/CAGE-001/telemetry?limit=0").status_code == 422


def test_auth_protects_reads_and_mutations(settings, monkeypatch):
    import io
    from PIL import Image

    monkeypatch.setenv("HABITAT_API_TOKEN", "test-token-for-gateway-at-least-32-characters")
    with TestClient(create_app(settings, run_worker=False)) as client:
        assert client.get("/health").status_code == 200
        shell = client.get("/livescene")
        assert shell.status_code == 200
        assert shell.headers["cache-control"] == "no-store"
        assert "connect-src 'self'" in shell.headers["content-security-policy"]
        assert "test-token-for-gateway" not in shell.text
        for name in ("terrarium-tropical.webp", "terrarium-desert.webp", "terrarium-aquatic.webp"):
            asset = client.get(f"/livescene/assets/{name}")
            assert asset.status_code == 200, name
            assert asset.headers["content-type"] == "image/webp"
            with Image.open(io.BytesIO(asset.content)) as image:
                assert image.format == "WEBP"
                image.verify()
        for name in ("unknown.webp", "config.py", "%2e%2e%2fconfig.py"):
            assert client.get(f"/livescene/assets/{name}").status_code == 404
        assert client.get("/v1/cages").status_code == 401
        assert client.get("/v1/enclosures").status_code == 401
        assert client.post("/v1/enclosures", json={"name": "test", "species": "test", "form_factor": "vertical"}).status_code == 401
        assert client.get("/v1/gateway").status_code == 401
        assert client.post("/v1/cages/CAGE-001/stop").status_code == 401
        assert client.get("/v1/cages", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/v1/cages", headers={"Authorization": "Bearer test-token-for-gateway-at-least-32-characters"})
        assert response.status_code == 200
        identity = client.get("/v1/gateway", headers={"Authorization": "Bearer test-token-for-gateway-at-least-32-characters"}).json()
        assert identity["site_id"] == settings.site_id
        assert identity["gateway_id"] == settings.gateway_id
        assert identity["version"] == __version__
        assert client.get("/v1/environment").status_code == 401
        assert client.get("/v1/cameras").status_code == 401
        assert client.get("/v1/cameras/RGB-001/snapshot").status_code == 401
        assert client.get("/v1/livescene/models").status_code == 401
        assert client.post("/v1/livescene/render", json={}).status_code == 401
        assert client.post("/v1/livescene/commands", json={}).status_code == 401


def test_mqtt_requires_credentials_and_has_no_simulation_api(settings, monkeypatch):
    settings = settings.model_copy(update={"transport": "mqtt"})
    monkeypatch.delenv("HABITAT_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="HABITAT_API_TOKEN"):
        create_app(settings)
    monkeypatch.setenv("HABITAT_API_TOKEN", "x" * 32)
    monkeypatch.delenv("HABITAT_MQTT_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="HABITAT_MQTT_PASSWORD"):
        create_app(settings)
    monkeypatch.setenv("HABITAT_MQTT_PASSWORD", "test-only")
    app = create_app(settings, run_worker=False)
    try:
        assert all("simulation" not in route.path for route in app.routes)
    finally:
        app.state.gateway.store.close()


def test_livescene_bindings_validate_local_devices_and_revisions(settings):
    from habitat_gateway.config import Settings
    from pydantic import ValidationError

    binding = {"model_id": "enclosure", "cage_id": "CAGE-001", "object_id": 1,
               "actuator_id": "mister", "checkpoint_sha256": "a" * 64,
               "geometry_revision": 1, "placement_revision": 1}
    base = settings.model_dump()
    assert len(Settings.model_validate({**base, "livescene_bindings": [binding]}).livescene_bindings) == 1
    for change in ({"cage_id": "other"}, {"actuator_id": "other"}, {"object_id": 0},
                   {"object_id": True}, {"checkpoint_sha256": "wrong"}, {"geometry_revision": 2},
                   {"placement_revision": 2}):
        with pytest.raises(ValidationError):
            Settings.model_validate({**base, "livescene_bindings": [{**binding, **change}]})
    with pytest.raises(ValidationError):
        Settings.model_validate({**base, "livescene_bindings": [binding, binding]})


def test_livescene_commands_require_verified_binding_and_keep_safety(settings, monkeypatch):
    from habitat.compute.livescene import SceneCatalog
    from habitat_gateway.config import Settings
    import habitat_gateway.livescene as scene

    binding = {"model_id": "enclosure", "cage_id": "CAGE-001", "object_id": 1,
               "actuator_id": "mister", "checkpoint_sha256": "a" * 64,
               "geometry_revision": 1, "placement_revision": 1}
    settings = Settings.model_validate({**settings.model_dump(), "livescene_bindings": [binding],
        "environment": {"enabled": True, "base_url": "http://127.0.0.1:8100"}})
    monkeypatch.setenv("HABITAT_GPU_TOKEN", "gpu-token-server-only-at-least-32-characters")
    model = {"model_id": "enclosure", "site_id": settings.site_id, "gateway_id": settings.gateway_id,
        "cage_id": "CAGE-001", "source_kind": "camera_capture", "quality_status": "experimental",
        "camera_count": 1, "checkpoint_sha256": "a" * 64, "geometry_revision": 1, "placement_revision": 1,
        "objects": [{"object_id": 1, "label": "mister", "state_min": 0., "state_max": 1.}]}
    body = {"schema_version": 1, "models": [model]}

    class GPU:
        def __init__(self, *args, **kwargs):
            pass

        def json(self, method, path, contract, **kwargs):
            assert method == "GET" and path == "/v1/livescene/models"
            return SceneCatalog.model_validate(body)

        def close(self):
            pass

    monkeypatch.setattr(scene, "HTTPComputeClient", GPU)
    app = create_app(settings, run_worker=False)
    with TestClient(app) as client:
        request = {"request_id": str(uuid4()), "model_id": "enclosure", "cage_id": "CAGE-001",
                   "object_id": 1, "action": "on", "duration_s": 1., "checkpoint_sha256": "a" * 64,
                   "geometry_revision": 1, "placement_revision": 1}
        listing = client.get("/v1/livescene/models")
        assert listing.status_code == 200
        assert listing.json()["models"][0]["objects"][0]["actuator_id"] == "mister"
        assert "gpu-token-server-only" not in listing.text
        for field, invalid in (("source_kind", "reference_dataset"), ("checkpoint_sha256", "b" * 64),
                               ("geometry_revision", 2), ("placement_revision", 2)):
            original = model[field]
            model[field] = invalid
            assert "actuator_id" not in client.get("/v1/livescene/models").json()["models"][0]["objects"][0]
            assert client.post("/v1/livescene/commands", json=request).status_code == 409
            model[field] = original
        assert client.post("/v1/livescene/commands", json={**request, "object_id": 2}).status_code == 409
        for field, value in (("checkpoint_sha256", "b" * 64), ("geometry_revision", 2), ("placement_revision", 2)):
            assert client.post("/v1/livescene/commands", json={**request, field: value}).status_code == 409
        assert client.post("/v1/livescene/commands", json={**request, "actuator_id": "fan"}).status_code == 422
        assert client.post("/v1/livescene/commands", json={**request, "duration_s": 0}).status_code == 422
        assert client.post("/v1/livescene/commands", json={**request, "cage_id": "other"}).status_code == 403
        settings.hardware_outputs_enabled = False
        rejected = client.post("/v1/livescene/commands", json=request)
        assert rejected.status_code == 409
        assert rejected.json()["reason"] == "hardware_not_commissioned"
        settings.hardware_outputs_enabled = True
        request["request_id"] = str(uuid4())
        accepted = client.post("/v1/livescene/commands", json=request)
        assert accepted.status_code == 202
        assert accepted.json()["actuator_id"] == "mister"
        assert accepted.json()["source"] == "manual"
        assert client.post("/v1/livescene/commands", json=request).json() == accepted.json()
        assert client.post("/v1/livescene/commands", json={**request, "duration_s": 2}).status_code == 409
        # Stop during GPU lookup must win over the pending object-bound ON.
        from concurrent.futures import ThreadPoolExecutor
        import threading
        entered, release = threading.Event(), threading.Event()
        fetch = GPU.json

        def blocked_catalog(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return fetch(self, *args, **kwargs)

        monkeypatch.setattr(GPU, "json", blocked_catalog)
        delayed = {**request, "request_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, "/v1/livescene/commands", json=delayed)
            try:
                assert entered.wait(5)
                stopped = client.post("/v1/cages/CAGE-001/stop")
                assert stopped.status_code == 200
            finally:
                release.set()
            response = pending.result()
            assert response.status_code == 409
            assert response.json()["detail"] == "scene_command_superseded"
        assert app.state.gateway.store.command(delayed["request_id"]) is None
        assert app.state.gateway.store.latest_command("CAGE-001", "mister")["action"] == "off"
        # Replaying the old ID after stopping returns the original result, never another ON.
        assert client.post("/v1/livescene/commands", json=request).json() == accepted.json()
        assert app.state.gateway.store.latest_command("CAGE-001", "mister")["action"] == "off"
        # GPU absence cannot take away the independent Pi emergency stop or direct OFF control.
        settings.environment.enabled = False
        assert client.get("/v1/livescene/models").status_code == 503
        assert client.post("/v1/cages/CAGE-001/stop").status_code == 200
        assert client.post("/v1/cages/CAGE-001/commands", json={"request_id": str(uuid4()),
            "actuator_id": "mister", "action": "off", "duration_s": 0}).status_code == 202


def test_livescene_render_scope_concurrency_and_sanitized_errors(settings, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from types import SimpleNamespace
    from habitat.compute.errors import ComputeFailure
    import habitat_gateway.livescene as scene

    settings.environment = settings.environment.model_copy(update={"enabled": True,
        "base_url": "http://127.0.0.1:8100"})
    monkeypatch.setenv("HABITAT_GPU_TOKEN", "gpu-token-server-only-at-least-32-characters")
    monkeypatch.setattr(scene, "HTTPComputeClient", lambda *a, **k: SimpleNamespace(close=lambda: None))
    entered, release = threading.Event(), threading.Event()

    def rendering(client, request):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(model_dump=lambda **kwargs: {"request_id": request["request_id"]})

    monkeypatch.setattr(scene, "render_result", rendering)
    request = {"schema_version": 1, "request_id": str(uuid4()), "site_id": settings.site_id,
        "gateway_id": settings.gateway_id, "cage_id": "CAGE-001", "model_id": "enclosure",
        "camera_index": 0, "state": None, "max_width": 320}
    with TestClient(create_app(settings, run_worker=False)) as client:
        assert client.get("/v1/gateway").json()["hardware_outputs_enabled"] is True
        for key in ("site_id", "gateway_id", "cage_id"):
            assert client.post("/v1/livescene/render", json={**request, key: "other"}).status_code == 403
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/v1/livescene/render", json=request)
            try:
                assert entered.wait(5)
                assert client.post("/v1/livescene/render", json=request).status_code == 429
            finally:
                release.set()
            assert first.result().status_code == 200

        def failed(client, request):
            raise ComputeFailure("secret-token-and-path-must-not-leak", status_code=500)

        monkeypatch.setattr(scene, "render_result", failed)
        response = client.post("/v1/livescene/render", json=request)
        assert response.status_code == 503
        assert "secret-token" not in response.text
        monkeypatch.setattr(scene, "render_result", rendering)
        assert client.post("/v1/livescene/render", json=request).status_code == 200


def test_enclosure_registration_validates_and_never_changes_device_or_cloud_contract(settings, monkeypatch):
    from habitat_gateway.config import CloudConfig
    import habitat_gateway.api as api_module

    monkeypatch.setenv("HABITAT_CLOUD_TOKEN", "test-only-cloud-token-at-least-32-characters")
    settings = settings.model_copy(update={"cloud": CloudConfig(
        enabled=True, endpoint="https://saas.example.test/v1/edge/sync")})
    app = create_app(settings, run_worker=False)
    with TestClient(app) as client:
        devices_before = client.get("/v1/cages").json()
        wire_before = app.state.cloud._prepare()
        configured = client.get("/v1/enclosures").json()
        assert configured == [{"cage_id": "CAGE-001", "name": "CAGE-001", "species": "",
            "form_factor": None, "configuration_status": "configured",
            "sensors": [{"id": sensor.id, "unit": sensor.unit} for sensor in settings.cages[0].sensors]}]
        request = {"name": "  Gecko   Home  ", "species": "  크레스티드   게코  ", "form_factor": "vertical"}
        for change in ({"name": "   "}, {"name": "x" * 81}, {"name": "hidden\u200b"},
                       {"species": "\t\n"}, {"species": "x" * 121}, {"form_factor": "guess"},
                       {"site_id": "OTHER"}, {"gateway_id": "OTHER"}, {"cage_id": "CAGE-001"},
                       {"node_id": "ESP32-NEW"}, {"hardware_outputs_enabled": True},
                       {"actuators": ["mister"]}):
            assert client.post("/v1/enclosures", json={**request, **change}).status_code == 422
        response = client.post("/v1/enclosures", json=request)
        assert response.status_code == 201
        created = response.json()
        assert created == {"cage_id": created["cage_id"], "name": "Gecko Home", "species": "크레스티드 게코",
                           "form_factor": "vertical", "configuration_status": "pending_setup", "sensors": []}
        assert created["cage_id"].startswith("CAGE-") and len(created["cage_id"]) == 37
        assert client.post("/v1/enclosures", json={**request, "name": "gecko home"}).status_code == 409
        assert client.post("/v1/enclosures", json={**request, "name": "cage-001"}).status_code == 409
        monkeypatch.setattr(api_module, "MAX_ENCLOSURES", 2)
        assert client.post("/v1/enclosures", json={**request, "name": "another"}).json()["detail"] == "enclosure_limit_reached"
        assert client.get("/v1/cages").json() == devices_before
        assert client.get("/v1/cages/" + created["cage_id"]).status_code == 404
        assert client.post(f"/v1/cages/{created['cage_id']}/commands", json={"request_id": str(uuid4()),
            "actuator_id": "mister", "action": "on", "duration_s": 1}).status_code == 404
        wire_after = app.state.cloud._prepare()
        assert wire_after["gateway"] == wire_before["gateway"]
        assert wire_after["events"] == wire_before["events"]
        audit = [item for item in client.get("/v1/audit").json() if item["kind"] == "enclosure_registered"]
        assert len(audit) == 1 and audit[0]["cage_id"] == created["cage_id"]


def test_enclosure_profiles_survive_restart_stay_scoped_and_follow_real_configuration(settings, tmp_path):
    settings = settings.model_copy(update={"database": str(tmp_path / "gateway.sqlite3")})
    with TestClient(create_app(settings, run_worker=False)) as client:
        created = client.post("/v1/enclosures", json={"name": "사육장", "species": "크레스티드 게코",
            "form_factor": "vertical"}).json()
    with TestClient(create_app(settings, run_worker=False)) as client:
        assert created in client.get("/v1/enclosures").json()
    other = settings.model_copy(update={"site_id": "OTHER-STORE", "gateway_id": "OTHER-PI"})
    with TestClient(create_app(other, run_worker=False)) as client:
        assert [row["cage_id"] for row in client.get("/v1/enclosures").json()] == ["CAGE-001"]
        assert client.post("/v1/enclosures", json={"name": "사육장", "species": "다른 종",
            "form_factor": "horizontal"}).status_code == 201
    # Only an actual operator-supplied device configuration promotes a profile.
    real_cage = settings.cages[0].model_copy(update={"id": created["cage_id"], "node_id": "ESP32-NEW"})
    configured = settings.model_copy(update={"cages": [*settings.cages, real_cage]})
    with TestClient(create_app(configured, run_worker=False)) as client:
        rows = client.get("/v1/enclosures").json()
        assert len(rows) == 2
        promoted = next(row for row in rows if row["cage_id"] == created["cage_id"])
        assert promoted == {**created, "configuration_status": "configured",
            "sensors": [{"id": sensor.id, "unit": sensor.unit} for sensor in real_cage.sensors]}


def test_enclosure_audit_failure_rolls_back_registration(settings):
    app = create_app(settings, run_worker=False)
    with TestClient(app) as client:
        app.state.gateway.store.db.execute("""CREATE TRIGGER fail_registration_audit BEFORE INSERT ON audit
            WHEN NEW.kind='enclosure_registered' BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END""")
        response = client.post("/v1/enclosures", json={"name": "test", "species": "test", "form_factor": "aquatic"})
        assert response.status_code == 503
        assert len(client.get("/v1/enclosures").json()) == 1
        assert app.state.gateway.store.enclosure_profiles(settings.site_id, settings.gateway_id) == []
