"""IR provisioning checks use private temporary fixtures, never a real broker."""
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import provision_ir as provision


BASE = "habitat/v1/TEST-SITE/cages/CAGE-A/nodes/NODE-A"
ACL = ("# existing rules\nuser gateway\ntopic readwrite habitat/v1/TEST-SITE/#\n\n"
       "user NODE-A\ntopic write " + BASE + "/telemetry\ntopic write " + BASE + "/status\n\n"
       "user NODE-B\ntopic write habitat/v1/TEST-SITE/cages/CAGE-B/nodes/NODE-B/telemetry\n")


@pytest.fixture
def fixture(tmp_path):
    user = SimpleNamespace(pw_name="operator", pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(tmp_path / "home"))
    ca = tmp_path / "ca.crt"; ca.write_text("test certificate fixture")
    profile = tmp_path / "gateway.toml"
    profile.write_text('site_id="TEST-SITE"\n[mqtt]\nhost="127.0.0.1"\nport=8883\n'
                       f'tls_ca="{ca}"\n[[cages]]\nid="CAGE-A"\nnode_id="NODE-A"\n')
    acl = tmp_path / "mqtt.acl"; acl.write_text(ACL); acl.chmod(0o644)
    passwords = tmp_path / "mqtt.passwd"
    passwords.write_text("gateway:$7$preserved-one\nNODE-A:$7$preserved-two\nNODE-B:$7$preserved-three\n")
    passwords.chmod(0o640)
    broker = tmp_path / "broker.conf"
    broker.write_text(f"listener 8883\nacl_file {acl}\npassword_file {passwords}\n")
    options = dict(acl_file=acl, password_file=passwords, broker_config=broker, receipt_root=tmp_path / "receipts")
    return SimpleNamespace(root=tmp_path, user=user, profile=profile, acl=acl, passwords=passwords,
        broker=broker, options=options,
        plan=lambda: provision.plan(profile, "CAGE-A", "IR-OPERATOR", user, **options))


def test_acl_adds_only_registered_node_and_restricted_controller_rules():
    result = provision.extend_acl(ACL, "NODE-A", "IR-OPERATOR", BASE)
    node_rules, controller_rules = provision.acl_rules(BASE)
    before_account, account = result.split("\nuser IR-OPERATOR\n")
    for rule in node_rules:
        before_account = before_account.replace(rule + "\n", "", 1)
    assert before_account == ACL
    assert account.splitlines() == controller_rules
    assert provision.extend_acl(result, "NODE-A", "IR-OPERATOR", BASE, reuse=True) == result


@pytest.mark.parametrize("text,node,account", [
    (ACL, "MISSING", "IR-OPERATOR"),
    (ACL + "user NODE-A\n", "NODE-A", "IR-OPERATOR"),
    (ACL, "NODE-A", "NODE-B"),
    (ACL, "NODE-A", "NODE-A"),
    ("pattern readwrite #\n" + ACL, "NODE-A", "IR-OPERATOR"),
])
def test_ambiguous_or_preexisting_acl_identity_is_refused(text, node, account):
    with pytest.raises(ValueError):
        provision.extend_acl(text, node, account, BASE)


def test_existing_controller_cannot_acquire_additional_permissions():
    result = provision.extend_acl(ACL, "NODE-A", "IR-OPERATOR", BASE)
    result += "topic write habitat/v1/TEST-SITE/#\n"
    with pytest.raises(ValueError, match="permissions changed"):
        provision.extend_acl(result, "NODE-A", "IR-OPERATOR", BASE, reuse=True)


def test_dry_plan_uses_registered_config_and_never_generates_credentials(fixture, monkeypatch):
    original = {p: p.read_bytes() for p in fixture.root.iterdir() if p.is_file()}
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("dry-run must not generate a password"))
    planned = fixture.plan()
    summary = provision.summary(planned)
    assert summary["node_id"] == "NODE-A" and summary["site_id"] == "TEST-SITE"
    assert not summary["applied"] and not summary["physical_outputs_requested"]
    assert json.loads(planned["config"])["topic_base"] == BASE
    assert len(summary["state_sha256"]) == 64
    assert not Path(fixture.user.pw_dir).exists()
    assert original == {p: p.read_bytes() for p in original}


def test_broker_paths_and_existing_password_accounts_must_match(fixture):
    fixture.broker.write_text(f"acl_file {fixture.acl}\npassword_file /some/other/passwd\n")
    with pytest.raises(ValueError, match="broker configuration"):
        fixture.plan()
    fixture.broker.write_text(f"acl_file {fixture.acl}\npassword_file {fixture.passwords}\n")
    fixture.passwords.write_text(fixture.passwords.read_text() + "IR-OPERATOR:$7$existing\n")
    with pytest.raises(ValueError, match="no owned provisioning receipt"):
        fixture.plan()


def test_duplicate_password_accounts_and_nonlocal_tls_profiles_are_refused(fixture):
    with pytest.raises(ValueError, match="duplicate"):
        provision.password_rows(b"user:$7$one\nuser:$7$two\n")
    fixture.profile.write_text(fixture.profile.read_text().replace('port=8883', 'port=1883'))
    with pytest.raises(ValueError, match="local TLS"):
        fixture.plan()


def test_symlink_files_and_parent_directories_are_refused(fixture):
    alias = fixture.root / "alias"
    alias.symlink_to(fixture.root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        provision.Snapshot.read(alias / "gateway.toml")
    fixture.acl.unlink(); fixture.acl.symlink_to(fixture.passwords)
    with pytest.raises(ValueError, match="symlinks"):
        fixture.plan()


def test_password_hashing_never_places_plaintext_in_argv_and_cleans_files(monkeypatch):
    seen = []
    def fake_hasher(command, **kwargs):
        seen.append(Path(command[-1]))
        assert command[:2] == ["mosquitto_passwd", "-U"]
        assert "TOP_SECRET_FIXTURE" not in repr(command)
        path = Path(command[-1])
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.read_text() == "IR-OPERATOR:TOP_SECRET_FIXTURE\n"
        path.write_text("IR-OPERATOR:$7$hashed-fixture\n")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(provision.subprocess, "run", fake_hasher)
    assert provision.password_hash("IR-OPERATOR", "TOP_SECRET_FIXTURE") == "IR-OPERATOR:$7$hashed-fixture"
    assert seen and not seen[0].exists() and not seen[0].parent.exists()


def emulate_root_owned_outputs(monkeypatch):
    """Root metadata is emulated; all actual files stay under pytest tmp_path."""
    uid, gid = os.getuid(), os.getgid()
    directory = provision.private_directory
    monkeypatch.setattr(provision, "private_directory", lambda path, owner, group: directory(path, uid, gid))
    monkeypatch.setattr(provision.os, "fchown", lambda *args: None)
    monkeypatch.setattr(provision.os, "chown", lambda *args: None)
    monkeypatch.setattr(provision, "password_hash", lambda account, password: account + ":$7$hash-fixture")


def test_apply_preserves_accounts_modes_and_rolls_back_on_reload_failure(fixture, monkeypatch):
    emulate_root_owned_outputs(monkeypatch)
    plan = fixture.plan()
    original_acl, original_passwd = fixture.acl.read_bytes(), fixture.passwords.read_bytes()
    modes = fixture.acl.stat().st_mode, fixture.passwords.stat().st_mode
    calls = []
    def reload():
        calls.append(1)
        if len(calls) == 1:
            assert fixture.passwords.read_bytes().startswith(original_passwd)
            raise RuntimeError("fixture failure")
        assert fixture.acl.read_bytes() == original_acl
        assert fixture.passwords.read_bytes() == original_passwd
    monkeypatch.setattr(provision, "reload_broker", reload)
    with pytest.raises(RuntimeError, match="original broker files restored"):
        provision.apply(plan, plan["state"], backup_root=fixture.root / "backups")
    assert len(calls) == 2
    assert (fixture.acl.stat().st_mode, fixture.passwords.stat().st_mode) == modes
    assert all(not plan["snapshots"][name].path.exists() for name in ("env", "config", "receipt"))
    backup = next((fixture.root / "backups").iterdir())
    assert (backup / "acl").read_bytes() == original_acl
    assert (backup / "passwords").read_bytes() == original_passwd


def test_apply_success_is_idempotent_and_keeps_credentials_private(fixture, monkeypatch):
    emulate_root_owned_outputs(monkeypatch)
    reloads = []
    monkeypatch.setattr(provision, "reload_broker", lambda: reloads.append(1))
    plan = fixture.plan()
    before = fixture.passwords.read_bytes()
    result = provision.apply(plan, plan["state"], backup_root=fixture.root / "backups")
    assert result["applied"] and reloads == [1]
    assert fixture.passwords.read_bytes() == before + b"IR-OPERATOR:$7$hash-fixture\n"
    for name in ("env", "config", "receipt"):
        assert plan["snapshots"][name].path.stat().st_mode & 0o777 == 0o600
    env = plan["snapshots"]["env"].path.read_text()
    password = env.split("HABITAT_IR_MQTT_PASSWORD=", 1)[1].strip()
    assert password not in json.dumps(result)
    read = provision.Snapshot.read
    receipt_path = plan["snapshots"]["receipt"].path
    def root_receipt(cls, path, **kwargs):
        snap = read(path, **kwargs)
        return replace(snap, uid=0) if snap.path == receipt_path else snap
    monkeypatch.setattr(provision.Snapshot, "read", classmethod(root_receipt))
    second = fixture.plan()
    assert second["reuse"]
    again = provision.apply(second, second["state"], backup_root=fixture.root / "backups")
    assert again["already_provisioned"] and reloads == [1]
    assert plan["snapshots"]["env"].path.read_text() == env
    plan["snapshots"]["env"].path.write_text(env + "CHANGED=1\n")
    with pytest.raises(ValueError, match="credentials changed"):
        fixture.plan()


def test_review_hash_and_concurrent_file_changes_block_apply_before_password_generation(fixture, monkeypatch):
    plan = fixture.plan()
    monkeypatch.setattr(provision.secrets, "token_urlsafe", lambda _: pytest.fail("must refuse before generating password"))
    with pytest.raises(ValueError, match="changed after review"):
        provision.apply(plan, "wrong", backup_root=fixture.root / "backups")
    fixture.acl.write_text(fixture.acl.read_text() + "# changed\n")
    with pytest.raises(ValueError, match="changed after review"):
        provision.apply(plan, plan["state"], backup_root=fixture.root / "backups")
    assert not (fixture.root / "backups").exists()


def test_single_command_apply_plans_first_and_pins_that_state(monkeypatch, capsys):
    calls = []
    prepared = {"state": "fixture-plan-state"}
    def planned(*args, **kwargs):
        calls.append("plan")
        return prepared
    def applied(value, expected, **kwargs):
        assert calls == ["plan"] and value is prepared
        assert expected == prepared["state"]
        calls.append("apply")
        return {"applied": True}
    monkeypatch.setattr(provision.os, "geteuid", lambda: 0)
    monkeypatch.setattr(provision.pwd, "getpwnam", lambda _: object())
    monkeypatch.setattr(provision, "plan", planned)
    monkeypatch.setattr(provision, "apply", applied)
    provision.main(["--user", "operator", "--cage", "CAGE-A", "--account", "IR-OPERATOR", "--apply"])
    assert calls == ["plan", "apply"]
    assert json.loads(capsys.readouterr().out) == {"applied": True}


def test_nonroot_apply_is_rejected_before_planning(monkeypatch):
    monkeypatch.setattr(provision.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(provision, "plan", lambda *a, **k: pytest.fail("must not read private inputs"))
    with pytest.raises(SystemExit):
        provision.main(["--user", "operator", "--cage", "CAGE-A", "--account", "IR-OPERATOR", "--apply"])


def test_concurrent_provisioner_is_refused(fixture, monkeypatch):
    plan = fixture.plan()
    def held(*args):
        raise BlockingIOError
    monkeypatch.setattr(provision.fcntl, "flock", held)
    monkeypatch.setattr(provision, "password_hash", lambda *a: pytest.fail("must not generate credentials"))
    with pytest.raises(ValueError, match="another IR provisioning"):
        provision.apply(plan, plan["state"], backup_root=fixture.root / "backups")
