import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tarfile
import tomllib
from types import SimpleNamespace

import pytest

from deploy import connect as connector
from deploy import edge_tools
from habitat_gateway.config import Settings


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path("deploy") / f"{name}.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


installer = module("install")
provision = module("provision")
fleet = module("fleet")
prepare_devices = module("prepare_devices")


def test_air_extra_dependencies_remain_service_readable_with_private_caller_umask(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'install', installer)
    air = module('install_air')
    (tmp_path / 'wheels').mkdir()
    (tmp_path / 'wheels/habitat_gateway-0.4.18-py3-none-any.whl').touch()
    installed = tmp_path / 'numpy'

    def pip_install(command, *, check):
        assert '--no-index' in command and command[-1].endswith('[air]') and check
        installed.mkdir()
        (installed / '__init__.py').write_text('# public dependency')

    monkeypatch.setattr(air.subprocess, 'run', pip_install)
    previous = os.umask(0o077)
    try:
        air.install_air_dependencies(tmp_path)
        restored = os.umask(0o077)
        assert restored == 0o077
    finally:
        os.umask(previous)
    assert installed.stat().st_mode & 0o777 == 0o755
    assert (installed / '__init__.py').stat().st_mode & 0o777 == 0o644


def test_r15_acl_authorizes_only_explicit_central_node():
    config = {"site_id": "STORE-ACL", "cages": [
        {"id": f"CAGE-{n}", "node_id": f"NODE-{n}"} for n in (1, 2, 3)]}
    assert "/r15/" not in prepare_devices.mqtt_acl(config)
    config["r15_bridge"] = {"enabled": False, "central_cage_id": "CAGE-2"}
    assert "/r15/" not in prepare_devices.mqtt_acl(config)
    config["r15_bridge"]["enabled"] = True
    text = prepare_devices.mqtt_acl(config)
    sections = {part.splitlines()[0]: part.splitlines()[1:] for part in text.split("user ")[1:]}
    base = "habitat/v1/STORE-ACL/cages/CAGE-2/nodes/NODE-2/r15"
    assert set(line for line in sections["NODE-2"] if "/r15/" in line) == {
        f"topic write {base}/hello", f"topic write {base}/ack", f"topic read {base}/command/+"}
    for node in ("NODE-1", "NODE-3"):
        assert all("/r15/" not in line and not line.startswith("topic read") for line in sections[node])
    assert all("topic write " + base + "/command" not in line for line in sections["NODE-2"])
    config["r15_bridge"]["central_cage_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="central_cage_id"):
        prepare_devices.mqtt_acl(config)


def fake_release(path, version="0.2.0", heartbeat=False, setup=False):
    path.mkdir()
    (path / "wheels").mkdir()
    files = {"install.py": "# fixture", "habitat-gateway.service": "[Service]\nType=simple\n",
             "simulation.toml": "# fixture", "requirements.lock": "# fixture",
             f"wheels/habitat_gateway-{version}-py3-none-any.whl": "fixture wheel"}
    if heartbeat or setup:
        files[installer.HEARTBEAT_SERVICE] = Path("deploy/systemd/habitat-heartbeat.service").read_text()
    if setup:
        for name in ("connect.py", "connect.sh", "provision.py"):
            files[name] = Path("deploy", name).read_text()
        files["simulation.toml"] = Path("config/simulation.toml").read_text()
        files["cloud-defaults.toml"] = Path("configs/defaults/cloud.toml").read_text()
    for name, content in files.items():
        (path / name).write_text(content)
    hashes = {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]
    manifest = {"release_id": f"{version}-{digest}", "version": version, "storage_schema": 1,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "machine": platform.machine(), "files": hashes}
    (path / "release.json").write_text(json.dumps(manifest))
    return manifest


def store_config(path, site="STORE-001", gateway="PI-001"):
    path.write_text(provision.generate(Path("config/simulation.toml").read_text(), site, gateway))
    return path


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o600])
@pytest.mark.parametrize("restart_fails", [False, True])
def test_camera_binding_preserves_service_config_access_on_apply_and_rollback(
    tmp_path, monkeypatch, capsys, mode, restart_fails
):
    config = store_config(tmp_path / "gateway.toml")
    original = config.read_text() + '\n[[cameras]]\nid = "RGB-001"\ncage_id = "CAGE-001"\n'
    config.write_text(original)
    config.chmod(mode)
    owner = (config.stat().st_uid, config.stat().st_gid)
    device = "/dev/v4l/by-path/platform-usb-0:1:1.0-video-index0"
    connected_device = tmp_path / "camera"
    connected_device.touch()
    paths = {"/etc/habitat-gateway/gateway.toml": config, device: connected_device}
    monkeypatch.setattr(edge_tools, "Path", lambda value: paths.get(str(value), Path(value)))
    monkeypatch.setattr(edge_tools, "read_environment", lambda _: {})
    monkeypatch.setattr(sys, "argv", ["edge_tools.py", "bind-camera", "RGB-001", device])
    restarts = []

    def restart(command, *, check):
        assert command == ["systemctl", "restart", "habitat-gateway"]
        metadata = config.stat()
        assert metadata.st_mode & 0o777 == mode
        assert (metadata.st_uid, metadata.st_gid) == owner
        restarts.append(command)
        if len(restarts) == 1:
            assert edge_tools.load_settings(config).cameras[0].device == device
            if restart_fails:
                raise edge_tools.subprocess.CalledProcessError(1, command)
        else:
            assert config.read_text() == original

    monkeypatch.setattr(edge_tools.subprocess, "run", restart)
    if restart_fails:
        with pytest.raises(edge_tools.subprocess.CalledProcessError):
            edge_tools.main()
        assert len(restarts) == 2
        assert config.read_text() == original
    else:
        edge_tools.main()
        assert json.loads(capsys.readouterr().out)["bound"] == "RGB-001"
        before = tomllib.loads(original)
        before["cameras"][0]["device"] = device
        assert tomllib.loads(config.read_text()) == before
    backup = config.with_suffix(".before-camera.toml")
    assert backup.read_text() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert not config.with_suffix(".candidate.toml").exists()


def test_store_generation_separates_identity_and_durable_data(tmp_path):
    one = tomllib.loads(store_config(tmp_path / "one.toml").read_text())
    two = tomllib.loads(store_config(tmp_path / "two.toml", "STORE-002", "PI-002").read_text())
    assert one["site_id"] != two["site_id"]
    assert one["gateway_id"] != two["gateway_id"]
    assert one["database"] == installer.DATA_PATH
    assert one["transport"] == "simulated"
    assert one["cages"] == two["cages"]
    with pytest.raises(ValueError, match="IDs"):
        provision.generate(Path("config/simulation.toml").read_text(), "bad\"\n", "PI-001")


TOP_URL = "http://192.168.50.21:5000/video_feed"
FRONT_URL = "http://192.168.50.22:5000/video_feed"


@pytest.mark.parametrize("server_header", ["[server]", '[ "server" ]', "[ 'server' ]"])
def test_camera_pair_preserves_sensor_configuration_and_legacy_camera(server_header):
    original = Path("config/simulation.toml").read_text()
    original += '\n[[cameras]] # a legacy camera keeps its identity\nid = "RGB-001"\ncage_id = "CAGE-001"\n'
    original += '\n' + server_header + '\nport = 8123\n'
    proposed, ids = edge_tools.bind_camera_pair(original, "CAGE-001", TOP_URL, FRONT_URL)
    assert ids == ["CAGE-001-TOP", "CAGE-001-FRONT"]
    before, after = tomllib.loads(original), tomllib.loads(proposed)
    assert {key: value for key, value in after.items() if key != "cameras"} == {
        key: value for key, value in before.items() if key != "cameras"}
    assert after["cameras"][0] == before["cameras"][0]
    assert after["cameras"][1:] == [
        dict(id="CAGE-001-" + view.upper(), cage_id="CAGE-001", source_type="http_mjpeg",
             url=url, view=view, live_stream=True)
        for view, url in (("top", TOP_URL), ("front", FRONT_URL))]
    assert '\n' + server_header + '\nport = 8123\n' in proposed
    repeated, repeated_ids = edge_tools.bind_camera_pair(proposed, "CAGE-001", TOP_URL, FRONT_URL)
    assert repeated == proposed and repeated_ids == ids


def test_camera_pair_updates_labelled_camera_without_changing_its_id_or_capture_options():
    original = Path("config/simulation.toml").read_text()
    original += '\n[[cameras]]\nid = "CUSTOM-TOP"\ncage_id = "CAGE-001"\nview = "top"\nwidth = 1280\nheight = 720\nrecord_video = true\n'
    proposed, ids = edge_tools.bind_camera_pair(original, "CAGE-001", TOP_URL, FRONT_URL)
    camera = tomllib.loads(proposed)["cameras"][0]
    assert ids[0] == camera["id"] == "CUSTOM-TOP"
    assert (camera["width"], camera["height"], camera["record_video"]) == (1280, 720, True)
    assert camera["source_type"] == "http_mjpeg" and camera["url"] == TOP_URL


@pytest.mark.parametrize("cage, top, front", [
    ("MISSING", TOP_URL, FRONT_URL),
    ("CAGE-001", TOP_URL, TOP_URL),
    ("CAGE-001", "http://user:secret@192.168.50.21/video_feed", FRONT_URL),
    ("CAGE-001", "file:///tmp/camera.mjpeg", FRONT_URL),
])
def test_camera_pair_rejects_invalid_identity_or_source(cage, top, front):
    with pytest.raises(ValueError):
        edge_tools.bind_camera_pair(Path("config/simulation.toml").read_text(), cage, top, front)


def test_camera_pair_handles_long_cage_ids_and_refuses_camera_id_collision():
    original = Path("config/simulation.toml").read_text().replace('"CAGE-001"', '"' + "C" * 64 + '"')
    proposed, ids = edge_tools.bind_camera_pair(original, "C" * 64, TOP_URL, FRONT_URL)
    assert all(len(camera_id) <= 64 for camera_id in ids)
    assert Settings.model_validate(tomllib.loads(proposed)).cameras[0].cage_id == "C" * 64
    original = Path("config/simulation.toml").read_text()
    original += '\n[[cameras]]\nid = "CAGE-001-TOP"\ncage_id = "CAGE-001"\n'
    with pytest.raises(ValueError, match="conflicts"):
        edge_tools.bind_camera_pair(original, "CAGE-001", TOP_URL, FRONT_URL)


def test_new_cage_reuses_explicit_inventory_without_policies_or_output_changes():
    original = 'hardware_outputs_enabled = false\n' + Path("config/simulation.toml").read_text()
    proposed = provision.add_cage(original, "CAGE-NEW", "NODE-NEW", "CAGE-001")
    before, after = tomllib.loads(original), tomllib.loads(proposed)
    assert after["cages"][0] == before["cages"][0]
    assert after["hardware_outputs_enabled"] is False
    added = after["cages"][1]
    assert (added["id"], added["node_id"], added["policies"]) == ("CAGE-NEW", "NODE-NEW", [])
    assert added["sensors"] == before["cages"][0]["sensors"]
    assert added["actuators"] == before["cages"][0]["actuators"]
    with pytest.raises(ValueError, match="already exists"):
        provision.add_cage(original, "CAGE-001", "NODE-NEW", "CAGE-001")
    with pytest.raises(ValueError, match="already assigned"):
        provision.add_cage(original, "CAGE-NEW", "ESP32-001", "CAGE-001")
    with pytest.raises(ValueError, match="unknown template"):
        provision.add_cage(original, "CAGE-NEW", "NODE-NEW", "MISSING")


def test_camera_pair_cli_prepares_exclusive_candidate_without_credentials_or_restart(tmp_path, monkeypatch, capsys):
    config = store_config(tmp_path / "gateway.toml")
    original = config.read_text()
    output = tmp_path / "prepared.toml"
    monkeypatch.setattr(edge_tools, "read_environment", lambda _: pytest.fail("candidate needs no credentials"))
    monkeypatch.setattr(edge_tools.subprocess, "run", lambda *a, **k: pytest.fail("candidate must not restart"))
    command = ["edge_tools.py", "--config", str(config), "bind-camera-pair", "CAGE-001",
               "--top", TOP_URL, "--front", FRONT_URL]
    monkeypatch.setattr(sys, "argv", command)
    edge_tools.main()
    result = json.loads(capsys.readouterr().out)
    assert result["validated"] and not result["applied"] and result["candidate"] is None
    assert config.read_text() == original
    monkeypatch.setattr(sys, "argv", command + ["--output", str(output)])
    edge_tools.main()
    result = json.loads(capsys.readouterr().out)
    assert result["candidate"] == str(output) and not result["restarted"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert len(Settings.model_validate(tomllib.loads(output.read_text())).cameras) == 2
    with pytest.raises(SystemExit):
        edge_tools.main()
    assert config.read_text() == original


@pytest.mark.parametrize("restart_fails", [False, True])
def test_camera_pair_apply_preserves_permissions_and_rolls_back_both_views(tmp_path, monkeypatch, capsys, restart_fails):
    config = store_config(tmp_path / "gateway.toml")
    original = config.read_text()
    config.chmod(0o640)
    owner = config.stat().st_uid, config.stat().st_gid
    restarts = []

    def restart(command, *, check):
        assert command == ["systemctl", "restart", "habitat-gateway"]
        restarts.append(command)
        assert config.stat().st_mode & 0o777 == 0o640
        assert (config.stat().st_uid, config.stat().st_gid) == owner
        if len(restarts) == 1:
            state = Settings.model_validate(tomllib.loads(config.read_text()))
            assert [camera.url for camera in state.cameras] == [TOP_URL, FRONT_URL]
            if restart_fails:
                raise edge_tools.subprocess.CalledProcessError(1, command)
        else:
            assert config.read_text() == original

    monkeypatch.setattr(edge_tools.subprocess, "run", restart)
    monkeypatch.setattr(sys, "argv", ["edge_tools.py", "--config", str(config), "bind-camera-pair",
                        "CAGE-001", "--top", TOP_URL, "--front", FRONT_URL, "--apply"])
    if restart_fails:
        with pytest.raises(edge_tools.subprocess.CalledProcessError):
            edge_tools.main()
        assert len(restarts) == 2 and config.read_text() == original
    else:
        edge_tools.main()
        assert json.loads(capsys.readouterr().out)["restarted"]
        edge_tools.main()
        assert not json.loads(capsys.readouterr().out)["restarted"]
        assert len(restarts) == 1
    assert config.with_suffix(".before-camera.toml").read_text() == original
    assert not list(tmp_path.glob(".gateway-camera-*"))


def test_add_cage_cli_prepares_sensor_inventory_and_pair_without_claiming_provisioning(tmp_path, monkeypatch, capsys):
    config = store_config(tmp_path / "gateway.toml")
    output = tmp_path / "prepared.toml"
    monkeypatch.setattr(sys, "argv", ["edge_tools.py", "--config", str(config), "add-cage", "CAGE-NEW",
                        "--node-id", "NODE-NEW", "--template-cage", "CAGE-001",
                        "--top", TOP_URL, "--front", FRONT_URL, "--output", str(output)])
    edge_tools.main()
    result = json.loads(capsys.readouterr().out)
    assert not result["sensor_credentials_provisioned"] and not result["policies_enabled"]
    candidate = Settings.model_validate(tomllib.loads(output.read_text()))
    assert candidate.cages[-1].node_id == "NODE-NEW"
    assert {camera.view for camera in candidate.cameras} == {"top", "front"}
    assert all(camera.cage_id == "CAGE-NEW" for camera in candidate.cameras)


def test_store_profile_keeps_separate_saas_and_gpu_destinations():
    template = Path("configs/examples/reptile-city.toml").read_text()
    for site in ("STORE-001", "STORE-002"):
        text = provision.generate(template, site, site + "-PI", "mqtt",
                                  saas_url="https://saas.example.test/v1/edge/sync",
                                  gpu_url="https://gpu.example.test:8443")
        settings = Settings.model_validate(tomllib.loads(text))
        assert settings.site_id == site and settings.gateway_id == site + "-PI"
        assert settings.cloud.endpoint.host == "saas.example.test"
        assert settings.environment.base_url.host == "gpu.example.test"
        assert len(settings.cages) == 3 and not settings.hardware_outputs_enabled
    for unsafe in ("https://user:secret@gpu.example.test", "https://gpu.example.test/v1/predict", "http://gpu.example.test"):
        with pytest.raises(ValueError):
            provision.generate(template, "STORE-002", "PI-002", gpu_url=unsafe)


def test_release_cleanup_preserves_active_rollback_and_unmanaged_data(tmp_path):
    base = tmp_path / "gateway"
    releases = base / "releases"
    releases.mkdir(parents=True)
    installed = []
    for version in ("0.4.1", "0.4.2", "0.4.3"):
        path = releases / version
        manifest = fake_release(path, version)
        target = releases / manifest["release_id"]
        path.rename(target)
        (target / ".installed").write_text(target.name)
        installed.append(target)
    (base / "current").symlink_to(installed[2], target_is_directory=True)
    (base / "previous").symlink_to(installed[1], target_is_directory=True)
    (releases / "unmanaged").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (releases / "external").symlink_to(outside, target_is_directory=True)
    assert installer.prune_releases(base) == [installed[0].name]
    assert all(p.exists() for p in (installed[1], installed[2], releases / "unmanaged", outside))


def test_new_store_heartbeat_maps_multiple_cages_without_enabling_example_policies():
    text = provision.generate_heartbeat(Path("config/simulation.toml").read_text(),
        Path("configs/defaults/cloud.toml").read_text(), "STORE-NEW", "PI-NEW",
        ["CAGE-A", "CAGE-B"], "https://new-saas.example.test/v1/edge/sync")
    settings = Settings.model_validate(tomllib.loads(text))
    assert (settings.site_id, settings.gateway_id) == ("STORE-NEW", "PI-NEW")
    assert settings.transport == "mqtt"
    assert str(settings.cloud.endpoint) == "https://new-saas.example.test/v1/edge/sync"
    assert [c.id for c in settings.cages] == ["CAGE-A", "CAGE-B"]
    assert [c.node_id for c in settings.cages] == ["UNASSIGNED-001", "UNASSIGNED-002"]
    assert all(c.policies == [] for c in settings.cages)
    assert "STORE-001" not in text and "CAGE-001" not in text


@pytest.mark.parametrize("cages", [[], ["A", "A"], ["bad\"\n"], ["a" * 65]])
def test_new_store_configuration_rejects_invalid_cage_mapping(cages):
    with pytest.raises(ValueError):
        provision.generate_heartbeat(Path("config/simulation.toml").read_text(),
            Path("configs/defaults/cloud.toml").read_text(), "STORE-NEW", "PI-NEW", cages,
            "https://example.test/v1/edge/sync")


def test_manifest_checks_integrity_and_platform(tmp_path):
    release = tmp_path / "release"
    manifest = fake_release(release)
    assert installer.verify_release(release)["release_id"] == manifest["release_id"]
    (release / "install.py").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        installer.verify_release(release)
    manifest["machine"] = "unsupported-cpu"
    (release / "release.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CPU"):
        installer.verify_release(release)


@pytest.mark.parametrize("name,kind", [("../outside", "file"), ("/absolute", "file"), ("release/link", "link")])
def test_archive_rejects_path_escape_and_symlinks(tmp_path, name, kind):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        entry = tarfile.TarInfo(name)
        if kind == "link":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
        else:
            entry.size = 1
        tar.addfile(entry, io.BytesIO(b"x") if kind == "file" else None)
    with pytest.raises(ValueError, match="unsafe"):
        installer.unpack(archive, tmp_path / "unpack")


def test_install_preserves_keys_and_rejects_store_identity_change(tmp_path, monkeypatch):
    release = tmp_path / "release"
    fake_release(release)
    config = store_config(tmp_path / "store.toml")
    calls = []
    monkeypatch.setattr(installer, "run", lambda *args, **kwargs: calls.append(args))
    root = tmp_path / "root"
    installer.install(release, config, root, no_service=True)
    env_path = root / "etc/habitat-gateway/gateway.env"
    first = env_path.read_text()
    assert len(installer.read_environment(env_path)["HABITAT_API_TOKEN"]) >= 32
    assert env_path.stat().st_mode & 0o777 == 0o600
    assert (root / "opt/habitat-gateway/current").is_symlink()
    assert all(args[0] != "systemctl" for args in calls)
    calls.clear()
    installer.install(release, config, root, no_service=True)
    assert env_path.read_text() == first
    assert not any("pip" in args for args in calls)
    changed = store_config(tmp_path / "other.toml", "STORE-002", "PI-002")
    with pytest.raises(ValueError, match="refusing to change"):
        installer.install(release, changed, root, no_service=True)
    assert env_path.read_text() == first


def test_failed_health_restores_old_code_config_and_service(tmp_path, monkeypatch):
    root = tmp_path / "root"
    old = tmp_path / "old"
    old_manifest = fake_release(old, version="0.1.0")
    new = tmp_path / "new"
    manifest = fake_release(new)
    config_path = store_config(tmp_path / "store.toml")
    calls = []
    monkeypatch.setattr(installer, "run", lambda *args, **kwargs: calls.append(args))
    installer.install(old, config_path, root, no_service=True)
    base = root / "opt/habitat-gateway"
    etc = root / "etc/habitat-gateway"
    previous_config = (etc / "gateway.toml").read_text()
    previous_unit = (root / "etc/systemd/system/habitat-gateway.service").read_text()
    previous_secret = (etc / "gateway.env").read_text()
    database = root / installer.DATA_PATH.lstrip("/")
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('preserve-me')")
    config_text = previous_config.replace("stale_after_s = 15", "stale_after_s = 14")
    config_path.write_text(config_text)
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    def fail_health(*args, **kwargs):
        raise RuntimeError("unhealthy")
    monkeypatch.setattr(installer, "wait_healthy", fail_health)
    with pytest.raises(RuntimeError, match="unhealthy"):
        installer._install_locked(new, manifest, config_path, config_text, tomllib.loads(config_text), root, etc, base, False)
    assert (base / "current").resolve().name == old_manifest["release_id"]
    assert (etc / "gateway.toml").read_text() == previous_config
    assert (etc / "gateway.env").read_text() == previous_secret
    assert (root / "etc/systemd/system/habitat-gateway.service").read_text() == previous_unit
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM evidence").fetchone()[0] == "preserve-me"
    assert len(list((base / "backups").glob("*.sqlite3"))) == 1
    assert calls[-1] == ("systemctl", "start", "habitat-gateway.service")


def heartbeat_user_setup(tmp_path):
    user_directory = tmp_path / "user"
    etc = user_directory / ".config/habitatos"
    etc.mkdir(parents=True, mode=0o700)
    credential = etc / "gateway.env"
    credential.write_text("HABITAT_CLOUD_TOKEN=test-user-heartbeat-token-at-least-32-characters\n")
    credential.chmod(0o600)
    config = store_config(tmp_path / "heartbeat.toml")
    config.write_text(config.read_text().replace("[[cages]]", '[cloud]\nenabled = true\nendpoint = "https://example.invalid/v1/edge/sync"\n\n[[cages]]', 1))
    return user_directory, config, credential


def test_user_heartbeat_installs_release_without_copying_or_changing_credentials(tmp_path, monkeypatch, capsys):
    user_directory, config, credential = heartbeat_user_setup(tmp_path)
    secret = credential.read_bytes()
    release = tmp_path / "release"
    manifest = fake_release(release, heartbeat=True)
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="yes\n", returncode=0)
    monkeypatch.setattr(installer, "run", fake_run)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    installer.install_user_heartbeat(release, config, user_directory=user_directory)
    base = user_directory / ".local/share/habitatos/gateway"
    assert (base / "current").resolve().name == manifest["release_id"]
    assert credential.read_bytes() == secret
    assert credential.stat().st_mode & 0o777 == 0o600
    assert (credential.parent / "gateway.toml").stat().st_mode & 0o777 == 0o600
    assert not list(base.rglob("gateway.env"))
    assert not list(user_directory.rglob("*.sqlite3"))
    assert any("--heartbeat-only" in args and "--check-config" in args for args in calls)
    assert ("systemctl", "--user", "enable", installer.HEARTBEAT_SERVICE) in calls
    assert secret.decode().strip().split("=", 1)[1] not in capsys.readouterr().out


@pytest.mark.parametrize("problem", ["public_credentials", "no_linger"])
def test_user_heartbeat_rejects_unsafe_credentials_or_missing_boot_support(tmp_path, monkeypatch, problem):
    user_directory, config, credential = heartbeat_user_setup(tmp_path)
    release = tmp_path / "release"
    fake_release(release, heartbeat=True)
    monkeypatch.setattr(installer, "run", lambda *a, **k: SimpleNamespace(stdout="no\n" if problem == "no_linger" else "yes\n"))
    if problem == "public_credentials":
        credential.chmod(0o644)
    with pytest.raises(ValueError, match="lingering|0600"):
        installer.install_user_heartbeat(release, config, user_directory=user_directory)
    assert not (user_directory / ".local/share/habitatos/gateway").exists()


def test_user_heartbeat_failed_update_restores_release_config_and_service(tmp_path, monkeypatch):
    user_directory, config, credential = heartbeat_user_setup(tmp_path)
    old = tmp_path / "old"
    old_manifest = fake_release(old, heartbeat=True)
    new = tmp_path / "new"
    fake_release(new, version="0.3.1", heartbeat=True)
    monkeypatch.setattr(installer, "run", lambda *a, **k: SimpleNamespace(stdout="yes\n"))
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    installer.install_user_heartbeat(old, config, user_directory=user_directory)
    config_target = credential.parent / "gateway.toml"
    unit = user_directory / ".config/systemd/user" / installer.HEARTBEAT_SERVICE
    original = (config_target.read_bytes(), unit.read_bytes(), credential.read_bytes())
    config.write_text(config.read_text().replace("stale_after_s = 15", "stale_after_s = 14"))
    fail_once = True
    def failing_run(*args, **kwargs):
        nonlocal fail_once
        if args == ("systemctl", "--user", "start", installer.HEARTBEAT_SERVICE) and fail_once:
            fail_once = False
            raise RuntimeError("start failed")
        return SimpleNamespace(stdout="yes\n")
    monkeypatch.setattr(installer, "run", failing_run)
    with pytest.raises(RuntimeError, match="start failed"):
        installer.install_user_heartbeat(new, config, user_directory=user_directory)
    assert (config_target.read_bytes(), unit.read_bytes(), credential.read_bytes()) == original
    assert (user_directory / ".local/share/habitatos/gateway/current").resolve().name == old_manifest["release_id"]


@pytest.fixture
def new_store_setup(tmp_path, monkeypatch):
    # New-store fixtures must not depend on whether the test host is already deployed.
    system_config = Path("/etc/habitat-gateway/gateway.toml")
    for method in ("exists", "is_symlink"):
        original = getattr(Path, method)
        monkeypatch.setattr(Path, method, lambda self, _original=original:
                            False if self == system_config else _original(self))
    release = tmp_path / "release"
    fake_release(release, version="0.3.2", setup=True)
    user_directory = tmp_path / "new-user"
    token = "private-new-store-test-token-32-characters"
    monkeypatch.setattr(connector, "install", installer)
    calls = []
    monkeypatch.setattr(installer, "run", lambda *a, **k: (calls.append((a, k)) or SimpleNamespace(stdout="yes\n", returncode=0)))
    monkeypatch.setattr(connector, "enable_boot_start", lambda: calls.append((("enable_boot_start",), {})))
    monkeypatch.setattr(connector, "wait_for_service_ack", lambda: True)
    def fake_process(command, **kwargs):
        calls.append((command, kwargs))
        if "--check-connection" in command:
            assert not (user_directory / ".config/habitatos/gateway.env").exists()
            config = tomllib.loads(Path(command[command.index("--config") + 1]).read_text())
            Settings.model_validate(config)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"connected":True,
                "site_id":config["site_id"],"gateway_id":config["gateway_id"],"error":None}))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(connector.subprocess, "run", fake_process)
    def ask(default):
        assert default == "https://easyrep.kro.kr/v1/edge/sync"
        return "STORE-NEW", "PI-NEW", ["CAGE-A", "CAGE-B"], default, token
    return release, user_directory, token, ask, calls


def test_store_wizard_validates_before_saving_secret_and_enables_service(new_store_setup, capsys):
    release, user_directory, token, ask, calls = new_store_setup
    assert connector.connect_new_gateway(release, user_directory=user_directory, ask=ask)
    credential = user_directory / ".config/habitatos/gateway.env"
    assert installer.read_environment(credential) == {"HABITAT_CLOUD_TOKEN":token}
    assert credential.stat().st_mode & 0o777 == 0o600
    assert credential.parent.stat().st_mode & 0o777 == 0o700
    config = tomllib.loads((credential.parent / "gateway.toml").read_text())
    assert config["site_id"] == "STORE-NEW" and len(config["cages"]) == 2
    preflight = next(i for i,(a,k) in enumerate(calls) if "--check-connection" in a)
    boot = next(i for i,(a,k) in enumerate(calls) if a == ("enable_boot_start",))
    assert preflight < boot
    assert all(token not in str(a) for a,k in calls)
    assert token not in capsys.readouterr().out
    assert any(a == ("systemctl", "--user", "enable", installer.HEARTBEAT_SERVICE) for a,k in calls)
    assert not list(user_directory.rglob("*.sqlite3"))


def test_store_wizard_invalid_token_never_saves_credentials_or_starts_service(new_store_setup, monkeypatch, capsys):
    release, user_directory, token, ask, calls = new_store_setup
    def refused(command, **kwargs):
        assert "--check-connection" in command
        return SimpleNamespace(returncode=1,stdout=json.dumps({"connected":False,"error":"http_401"}))
    monkeypatch.setattr(connector.subprocess, "run", refused)
    with pytest.raises(connector.SetupError, match="rejected the token"):
        connector.connect_new_gateway(release, user_directory=user_directory, ask=ask)
    assert not (user_directory / ".config/habitatos/gateway.env").exists()
    assert not any(a == ("enable_boot_start",) or "start" in a for a,k in calls)
    assert token not in capsys.readouterr().out


def test_store_wizard_refuses_existing_identity_before_prompts(new_store_setup):
    release, user_directory, token, ask, calls = new_store_setup
    etc = user_directory / ".config/habitatos"
    etc.mkdir(parents=True)
    credential = etc / "gateway.env"
    original = b"existing-credential-must-not-change"
    credential.write_bytes(original)
    with pytest.raises(connector.SetupError, match="already has Gateway settings"):
        connector.connect_new_gateway(release, user_directory=user_directory,
                                      ask=lambda _: pytest.fail("must not prompt on an existing Pi"))
    assert credential.read_bytes() == original and calls == []


def test_store_wizard_failed_install_removes_only_new_credential(new_store_setup, monkeypatch):
    release, user_directory, token, ask, calls = new_store_setup
    def fail(*args, **kwargs):
        raise RuntimeError("installation failed before applying config")
    monkeypatch.setattr(installer, "install_user_heartbeat", fail)
    with pytest.raises(RuntimeError):
        connector.connect_new_gateway(release, user_directory=user_directory, ask=ask)
    assert not (user_directory / ".config/habitatos/gateway.env").exists()


def test_store_wizard_unconfirmed_background_ack_preserves_retrying_service(new_store_setup, monkeypatch, capsys):
    release, user_directory, token, ask, calls = new_store_setup
    monkeypatch.setattr(connector, "wait_for_service_ack", lambda: False)
    assert not connector.connect_new_gateway(release, user_directory=user_directory, ask=ask)
    assert (user_directory / ".config/habitatos/gateway.env").exists()
    assert (user_directory / ".config/systemd/user" / installer.HEARTBEAT_SERVICE).exists()
    output = capsys.readouterr().out
    assert "not confirmed" in output and "CONNECTED:" not in output and token not in output


def test_store_wizard_background_ack_must_belong_to_current_service(monkeypatch):
    polls = 0
    now = 0
    def fake_run(*args, **kwargs):
        nonlocal polls
        if args[0] == "systemctl":
            return SimpleNamespace(stdout="ActiveState=active\nInvocationID=current\n")
        polls += 1
        record = {"_SYSTEMD_INVOCATION_ID":"old" if polls == 1 else "current",
                  "MESSAGE":"Cloud heartbeat acknowledged: site=STORE-NEW gateway=PI-NEW"}
        assert "--user-unit=habitat-heartbeat.service" in args
        return SimpleNamespace(stdout=json.dumps(record)+"\n")
    def advance(seconds):
        nonlocal now
        now += seconds
    monkeypatch.setattr(connector.install, "run", fake_run)
    monkeypatch.setattr(connector.time, "monotonic", lambda: now)
    monkeypatch.setattr(connector.time, "sleep", advance)
    assert connector.wait_for_service_ack(timeout=3)
    assert polls == 2


def test_inventory_refuses_duplicate_identity_and_unsafe_hosts(tmp_path):
    store_config(tmp_path / "one.toml")
    inventory = tmp_path / "inventory.json"
    record = {"host": "operator@store-001.local", "site_id": "STORE-001", "gateway_id": "PI-001", "config": "one.toml"}
    inventory.write_text(json.dumps([record]))
    assert fleet.load_inventory(inventory)[0]["config"] == tmp_path / "one.toml"
    inventory.write_text(json.dumps([record, record]))
    with pytest.raises(ValueError, match="unique"):
        fleet.load_inventory(inventory)
    inventory.write_text(json.dumps([{**record, "host": "-oProxyCommand=bad"}]))
    with pytest.raises(ValueError, match="host"):
        fleet.load_inventory(inventory)


def test_inventory_refuses_wrong_store_config(tmp_path):
    store_config(tmp_path / "one.toml")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([{"host": "pi.local", "site_id": "STORE-002", "gateway_id": "PI-002", "config": "one.toml"}]))
    with pytest.raises(ValueError, match="mismatch"):
        fleet.load_inventory(inventory)

def test_native_camera_release_contains_only_allowed_public_sources(tmp_path):
    from deploy.build_release import CAMERA_NATIVE_FILES, copy_public_camera_firmware
    source, destination = tmp_path / "camera", tmp_path / "release"
    source.mkdir()
    (source / "main.py").write_text("# legacy")
    (source / "config.example.json").write_text("{}")
    native = source / "h264_node"
    native.mkdir()
    for name in CAMERA_NATIVE_FILES:
        (native / name).write_text("public fixture")
    (native / "config.json").write_text("private credentials")
    (native / "firmware.bin").write_bytes(b"not a release input")
    copy_public_camera_firmware(source, destination)
    assert {p.name for p in (destination / "h264_node").iterdir()} == set(CAMERA_NATIVE_FILES)
    assert not list(destination.rglob("config.json")) and not list(destination.rglob("*.bin"))


def test_release_firmware_excludes_private_config_and_build_artifacts(tmp_path):
    from deploy.build_release import copy_public_firmware
    source, destination = tmp_path / "firmware", tmp_path / "release"
    source.mkdir()
    (source / "cage_node.ino").write_text("// public source")
    (source / "r15_bridge.h").write_text("// public header")
    (source / "config.example.h").write_text("// placeholders")
    (source / "config.h").write_text("PRIVATE_FIXTURE_MUST_NOT_SHIP")
    (source / "sketch.bin").write_bytes(b"compiled-private-config")
    (source / "build").mkdir()
    (source / "build/config.h").write_text("private nested file")
    copy_public_firmware(source, destination)
    assert {p.name for p in destination.iterdir()} == {"cage_node.ino", "r15_bridge.h", "config.example.h"}


def test_release_is_service_readable_under_private_caller_umask(tmp_path, monkeypatch):
    import os
    release = tmp_path / "bundle"
    manifest = fake_release(release)
    base = tmp_path / "installed"
    base.mkdir()

    def fake_run(*args, **kwargs):
        if "venv" in args:
            directory = Path(args[-1])
            (directory / "bin").mkdir(parents=True)
            (directory / "module.py").write_text("# fixture")

    monkeypatch.setattr(installer, "run", fake_run)
    previous = os.umask(0o077)
    try:
        target = installer.prepare_release(release, manifest, base)
        assert target.stat().st_mode & 0o777 == 0o755
        assert (target / "venv/bin").stat().st_mode & 0o777 == 0o755
        assert (target / "venv/module.py").stat().st_mode & 0o777 == 0o644
        assert os.umask(0o077) == 0o077
    finally:
        os.umask(previous)

