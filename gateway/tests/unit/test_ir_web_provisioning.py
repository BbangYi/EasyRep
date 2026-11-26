"""Root/service actions are simulated; all files are isolated temporary fixtures."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from deploy import provision_ir_web as provision


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home = tmp_path / "home"
    user = SimpleNamespace(pw_name="operator", pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(home))
    ir_root = home / ".config/habitatos/ir"
    ir_root.mkdir(parents=True, mode=0o700)
    current = home / ".local/share/habitatos/ir/current"
    release = current.parent / "releases/test-release"
    (release / "venv/bin").mkdir(parents=True)
    (release / "venv/bin/python").touch()
    current.symlink_to(release, target_is_directory=True)
    receipts = tmp_path / "receipts"; receipts.mkdir()
    profile = tmp_path / "gateway.toml"
    profile.write_text('site_id="TEST-SITE"\ngateway_id="TEST-GATEWAY"\n[mqtt]\n'
                       'host="127.0.0.1"\nport=8883\ntls_ca="/test-ca.crt"\n'
                       '[[cages]]\nid="CAGE-A"\nnode_id="NODE-A"\n'
                       '[[cages]]\nid="CAGE-B"\nnode_id="NODE-B"\n')
    for cage, node in (("CAGE-A", "NODE-A"), ("CAGE-B", "NODE-B")):
        directory = ir_root / cage; directory.mkdir(mode=0o700)
        base = f"habitat/v1/TEST-SITE/cages/{cage}/nodes/{node}"
        config = {"broker_host": "127.0.0.1", "broker_port": 8883, "ca_file": "/test-ca.crt",
                  "topic_base": base, "username_env": "HABITAT_IR_MQTT_USER", "password_env": "HABITAT_IR_MQTT_PASSWORD"}
        env = f"HABITAT_IR_MQTT_USER=IR-{cage}\nHABITAT_IR_MQTT_PASSWORD=PRIVATE_MQTT_FIXTURE\n".encode()
        receipt = {"schema_version": 1, "site_id": "TEST-SITE", "cage_id": cage,
                   "node_id": node, "user": "operator", "topic_base": base, "account": "IR-" + cage,
                   "env_sha256": provision.digest(env)}
        for path, data in ((directory / "ir.json", provision.encode_json(config)), (directory / "ir.env", env),
                           (receipts / ("TEST-SITE--" + cage + ".json"), provision.encode_json(receipt))):
            path.write_bytes(data); path.chmod(0o600)
    gateway_env = tmp_path / "gateway.env"
    gateway_env.write_bytes(b'# retain CRLF/comment and unrelated syntax\r\nSENSOR_TOKEN="UNCHANGED SECRET"\r\nMQTT_PASSWORD=existing')
    gateway_env.chmod(0o600)
    runtime = tmp_path / "runtime"
    unit = tmp_path / provision.SERVICE
    options = dict(gateway_env=gateway_env, receipt_root=receipts, runtime_dir=runtime,
                   unit_file=unit, viewer_url="https://gateway.example/camera")
    real_read = provision.Snapshot.read
    def read(cls, path, **kwargs):
        snapshot = real_read(path, **kwargs)
        if snapshot.data is not None and snapshot.path == runtime / "web.json":
            return replace(snapshot, uid=user.pw_uid, gid=user.pw_gid)
        if snapshot.data is not None and not snapshot.path.is_relative_to(home):
            return replace(snapshot, uid=0, gid=0)
        return snapshot
    monkeypatch.setattr(provision.Snapshot, "read", classmethod(read))
    monkeypatch.setattr(provision.os, "fchown", lambda *args: None)
    monkeypatch.setattr(provision.os, "chown", lambda *args: None)
    private = provision.private_directory
    monkeypatch.setattr(provision, "private_directory", lambda path, uid, gid: private(path, os.getuid(), os.getgid()))
    def runtime_directory(path):
        if path.exists():
            return []
        path.mkdir(mode=0o755)
        return [path]
    monkeypatch.setattr(provision, "ensure_runtime_directory", runtime_directory)
    calls = []
    status = {"active": False, "enabled": False}
    def service(*args, check=True):
        calls.append(args)
        if args[0] == "is-active":
            return status["active"]
        if args[0] == "is-enabled":
            return status["enabled"]
        if args[0] in ("start", "restart", "stop"):
            status["active"] = args[0] != "stop"
        if args[0] in ("enable", "disable"):
            status["enabled"] = args[0] == "enable"
        return True
    monkeypatch.setattr(provision, "systemctl", service)
    monkeypatch.setattr(provision, "health", lambda _: None)
    def planned(cages=None, **kwargs):
        return provision.plan(profile, cages or ["CAGE-A"], user, **(options | kwargs))
    return SimpleNamespace(root=tmp_path, home=home, user=user, profile=profile, env=gateway_env,
                           options=options, plan=planned, calls=calls, status=status)


def applied(fixture, **kwargs):
    plan = fixture.plan(**kwargs)
    return provision.apply(plan, plan["state"], backup_root=fixture.root / "backups")


def test_dry_run_keeps_inputs_and_does_not_generate_tokens(fixture, monkeypatch):
    before = fixture.env.read_bytes()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("no secret generation in dry-run"))
    p = fixture.plan()
    result = provision.summary(p)
    assert result["cage_ids"] == ["CAGE-A"]
    assert not result["applied"] and not result["physical_outputs_requested"]
    assert result["camera_ir"]["endpoint"] == "http://127.0.0.1:8093"
    assert fixture.env.read_bytes() == before and not fixture.calls
    assert not fixture.options["runtime_dir"].exists()
    assert json.loads(p["config"])["nodes"][0]["node_id"] == "NODE-A"


@pytest.mark.parametrize("cages", [["UNKNOWN"], ["CAGE-A", "CAGE-A"]])
def test_only_unique_registered_cages_can_be_selected(fixture, cages):
    with pytest.raises(ValueError, match="exactly once"):
        fixture.plan(cages)


def test_cage_scope_can_be_expanded_without_credential_rotation(fixture, monkeypatch):
    applied(fixture)
    first = fixture.env.read_bytes()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("credentials must be reused"))
    result = applied(fixture, cages=["CAGE-B", "CAGE-A"])
    assert result["cage_ids"] == ["CAGE-A", "CAGE-B"]
    assert fixture.env.read_bytes() == first
    config = json.loads((fixture.options["runtime_dir"] / "web.json").read_bytes())
    assert [(n["cage_id"], n["node_id"]) for n in config["nodes"]] == [("CAGE-A", "NODE-A"), ("CAGE-B", "NODE-B")]
    assert ("restart", provision.SERVICE) in fixture.calls


@pytest.mark.parametrize("field,value", [("node_id", "OTHER-NODE"), ("site_id", "OTHER-SITE"), ("user", "other")])
def test_receipt_identity_must_match_registered_node(fixture, field, value):
    receipt = fixture.options["receipt_root"] / "TEST-SITE--CAGE-A.json"
    obj = json.loads(receipt.read_bytes()); obj[field] = value; receipt.write_bytes(provision.encode_json(obj))
    with pytest.raises(ValueError, match="receipt identity"):
        fixture.plan()


def test_private_config_and_credentials_cannot_drift(fixture):
    config = fixture.home / ".config/habitatos/ir/CAGE-A/ir.json"
    original = config.read_bytes()
    obj = json.loads(original); obj["topic_base"] = "unregistered/topic"
    config.write_bytes(provision.encode_json(obj))
    with pytest.raises(ValueError, match="private configuration"):
        fixture.plan()
    config.write_bytes(original)
    env = config.with_name("ir.env"); env.write_bytes(env.read_bytes() + b"OTHER=value\n")
    with pytest.raises(ValueError, match="credentials changed"):
        fixture.plan()


def test_apply_preserves_gateway_environment_and_secrets_stay_private(fixture):
    original = fixture.env.read_bytes()
    result = applied(fixture)
    assert fixture.env.read_bytes().startswith(original + b"\n")
    tokens = provision.tokens_from_env(fixture.env.read_bytes())
    assert set(tokens) == {provision.BRIDGE_KEY, provision.CONTROL_KEY}
    assert all(len(token) >= 32 for token in tokens.values())
    assert all(token not in json.dumps(result) for token in tokens.values())
    assert "PRIVATE_MQTT_FIXTURE" not in json.dumps(result)
    runtime = fixture.options["runtime_dir"]
    for path in (fixture.env, runtime / "web.env", runtime / "web.json", runtime / "provisioned.json"):
        assert path.stat().st_mode & 0o777 == 0o600
    launcher = fixture.home / ".config/habitatos/ir/camera-control.html"
    assert launcher.stat().st_mode & 0o777 == 0o600
    assert "https://gateway.example/camera#control_key=" + tokens[provision.CONTROL_KEY] in launcher.read_text()
    unit = fixture.options["unit_file"].read_text()
    assert "User=operator" in unit and "ProtectHome=read-only" in unit
    assert "WorkingDirectory=/\n" in unit
    assert "EnvironmentFile=" + str(runtime / "web.env") + "\n" in unit
    assert "ReadWritePaths=\"" + str(fixture.home / ".local/state/habitat-ir") in unit
    assert "NoNewPrivileges=true" in unit and "UMask=0077" in unit
    assert all(call[0] == "daemon-reload" or call[-1] == provision.SERVICE for call in fixture.calls)
    assert result["worker_healthy"] and not result["gateway_restarted"]
    backup = Path(result["backup"])
    assert (backup / "gateway_env").read_bytes() == original


def test_repeat_apply_reuses_tokens_and_does_not_restart_healthy_worker(fixture, monkeypatch):
    applied(fixture)
    env = fixture.env.read_bytes()
    fixture.calls.clear()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("credentials must not rotate"))
    result = applied(fixture)
    assert result["already_provisioned"] and fixture.env.read_bytes() == env
    assert [c[0] for c in fixture.calls] == ["is-active", "is-enabled"]
    assert "backup" not in result


def test_failed_start_rolls_back_files_credentials_and_service_state(fixture, monkeypatch):
    original = fixture.env.read_bytes()
    def fail(_):
        raise RuntimeError("simulated health failure")
    monkeypatch.setattr(provision, "health", fail)
    with pytest.raises(RuntimeError, match="original files and worker state restored"):
        applied(fixture)
    assert fixture.env.read_bytes() == original
    assert not fixture.options["unit_file"].exists()
    assert not fixture.options["runtime_dir"].exists()
    assert fixture.status == {"active": False, "enabled": False}


def test_failed_update_restores_previous_worker_and_private_files(fixture, monkeypatch):
    applied(fixture)
    p = fixture.plan()
    before = {name: snap.data for name, snap in p["snapshots"].items()}
    monkeypatch.setattr(provision, "health", lambda _: (_ for _ in ()).throw(RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="restored"):
        applied(fixture, max_on_seconds=300)
    assert fixture.status == {"active": True, "enabled": True}
    for name, snap in p["snapshots"].items():
        assert snap.path.read_bytes() == before[name]


def test_concurrent_input_change_is_rejected_before_generation(fixture, monkeypatch):
    p = fixture.plan()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("must recheck first"))
    fixture.env.write_bytes(fixture.env.read_bytes() + b"\nCHANGED=true\n")
    with pytest.raises(ValueError, match="changed after review"):
        provision.apply(p, p["state"], backup_root=fixture.root / "backups")
    assert not fixture.calls


def test_review_hash_and_runtime_upgrade_must_be_replanned(fixture, monkeypatch):
    p = fixture.plan()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("must recheck first"))
    with pytest.raises(ValueError, match="changed after review"):
        provision.apply(p, "other-reviewed-state", backup_root=fixture.root / "backups")
    new_release = p["release"].with_name("next-release")
    new_release.mkdir()
    p["current"].unlink(); p["current"].symlink_to(new_release)
    with pytest.raises(ValueError, match="changed after review"):
        provision.apply(p, p["state"], backup_root=fixture.root / "backups")


def test_versioned_runtime_upgrade_restarts_worker_even_when_config_is_unchanged(fixture):
    applied(fixture)
    old = fixture.plan()
    new_release = old["release"].with_name("next-release")
    (new_release / "venv/bin").mkdir(parents=True)
    (new_release / "venv/bin/python").touch()
    old["current"].unlink(); old["current"].symlink_to(new_release)
    updated = fixture.plan()
    assert old["state"] != updated["state"]
    fixture.calls.clear()
    provision.apply(updated, updated["state"], backup_root=fixture.root / "backups")
    assert ("restart", provision.SERVICE) in fixture.calls


def test_failure_before_service_activation_does_not_interrupt_existing_worker(fixture, monkeypatch):
    applied(fixture)
    fixture.calls.clear()
    real_write = provision.atomic_write
    config_path = fixture.options["runtime_dir"] / "web.json"
    failed = []
    def write(snapshot, data, **kwargs):
        if snapshot.path == config_path and not failed:
            failed.append(True)
            raise OSError("simulated atomic write failure")
        return real_write(snapshot, data, **kwargs)
    monkeypatch.setattr(provision, "atomic_write", write)
    with pytest.raises(RuntimeError, match="restored"):
        applied(fixture, max_on_seconds=300)
    assert fixture.status["active"]
    assert not any(call[0] in ("start", "stop", "restart") for call in fixture.calls)


def test_concurrent_provisioner_is_refused(fixture, monkeypatch):
    p = fixture.plan()
    def locked(*args):
        raise BlockingIOError
    monkeypatch.setattr(provision.fcntl, "flock", locked)
    with pytest.raises(ValueError, match="another IR web provisioning"):
        provision.apply(p, p["state"], backup_root=fixture.root / "backups")


def test_owned_output_and_token_tampering_are_rejected(fixture):
    applied(fixture)
    env = fixture.env.read_bytes()
    fixture.env.write_bytes(env.replace(b"HABITAT_IR_BRIDGE_TOKEN=", b"HABITAT_IR_BRIDGE_TOKEN=corrupt"))
    with pytest.raises(ValueError, match="credentials changed"):
        fixture.plan()
    fixture.env.write_bytes(env)
    fixture.options["unit_file"].write_text("[Service]\nUser=root\n")
    with pytest.raises(ValueError, match="managed IR web files changed"):
        fixture.plan()


def test_unowned_files_and_symlink_outputs_are_rejected(fixture):
    unit = fixture.options["unit_file"]
    unit.write_text("unowned unit")
    with pytest.raises(ValueError, match="no owned provisioning receipt"):
        fixture.plan()
    unit.unlink(); unit.symlink_to(fixture.env)
    with pytest.raises(ValueError, match="symlinks"):
        fixture.plan()


@pytest.mark.parametrize("url", ["http://gateway.example/camera", "https://user:pass@gateway.example/camera",
                                "https://gateway.example/camera?token=value", "https://gateway.example/camera#key=value"])
def test_control_link_requires_clean_https_address(fixture, url):
    with pytest.raises(ValueError, match="viewer URL"):
        fixture.plan(viewer_url=url)


def test_health_is_read_only_loopback_and_ignores_proxy_environment(monkeypatch):
    calls = []
    payload = {"status": "ok", "site_id": "SITE", "gateway_id": "GW", "configured_cages": ["CAGE"]}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps(payload).encode()
    class Opener:
        def open(self, url, timeout):
            calls.append(url); return Response()
    monkeypatch.setattr(provision, "build_opener", lambda handler: Opener())
    provision.health({"port": 8093, "identity": {"site_id": "SITE", "gateway_id": "GW"}, "cages": ["CAGE"]})
    assert calls == ["http://127.0.0.1:8093/health"]


def test_nonroot_apply_is_rejected_before_reading_private_inputs(monkeypatch):
    monkeypatch.setattr(provision.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(provision, "plan", lambda *a, **k: pytest.fail("must stop before reading"))
    with pytest.raises(SystemExit):
        provision.main(["--user", "operator", "--cage", "CAGE-A", "--apply"])


def test_generated_unit_passes_actual_systemd_parser_without_ignored_directives(tmp_path):
    analyzer = shutil.which("systemd-analyze")
    if not analyzer:
        pytest.skip("systemd-analyze is not available")
    # Verify actual parser grammar without installing or starting any service.
    user = SimpleNamespace(pw_name="habitat-test", pw_uid=1000, pw_gid=1000, pw_dir="/tmp")
    current = tmp_path / "runtime"
    (current / "venv/bin").mkdir(parents=True)
    (current / "venv/bin/python").symlink_to(shutil.which("python3"))
    unit = tmp_path / provision.SERVICE
    unit.write_bytes(provision.service_text(user, current, tmp_path / "web.json", tmp_path / "web.env", tmp_path, 8093))
    result = subprocess.run([analyzer, "verify", str(unit)], capture_output=True, text=True, timeout=15)
    if "SO_PASSCRED failed: Operation not permitted" in result.stderr:
        pytest.skip("sandbox blocks systemd's parser IPC; run this test outside sandbox")
    assert result.returncode == 0, result.stderr
    # systemd can exit successfully while silently ignoring a bad directive.
    assert not result.stderr.strip(), result.stderr
