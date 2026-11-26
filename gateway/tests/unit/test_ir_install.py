"""IR CLI deployment uses verified releases without credentials, services or devices."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from deploy import install
from tests.test_deployment import fake_release


def offline_commands(monkeypatch, fail_help=False):
    calls = []

    def run(*args, **kwargs):
        values = [str(arg) for arg in args]
        calls.append(values)
        if values[1:3] == ["-m", "venv"]:
            binaries = Path(values[3]) / "bin"
            binaries.mkdir(parents=True)
            (binaries / "habitat-ir").write_text("# installed console entrypoint fixture")
        elif values[1:4] == ["-m", "pip", "install"]:
            assert "--no-index" in values and "--constraint" in values
        elif values[-1:] == ["--help"]:
            assert Path(values[0]).name == "habitat-ir"
            assert Path(values[0]).parent.parent.parent == kwargs["cwd"]
            assert kwargs["timeout"] == 15
            if fail_help:
                raise subprocess.CalledProcessError(1, values)
        else:
            pytest.fail(f"Unexpected command in IR installation: {values[0]}")
        return SimpleNamespace(stdout="usage: habitat-ir", returncode=0)

    monkeypatch.setattr(install, "run", run)
    return calls


def test_ir_install_is_offline_and_keeps_gateway_credentials_and_services_untouched(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    manifest = fake_release(source)
    home = tmp_path / "user"
    gateway = home / ".config/habitatos/gateway.env"
    unit = home / ".config/systemd/user/existing.service"
    for path, contents in ((gateway, "PRIVATE_FIXTURE=must-not-be-loaded\n"), (unit, "existing service\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    calls = offline_commands(monkeypatch)
    target = install.install_user_ir(source, user_directory=home)
    base = home / ".local/share/habitatos/ir"
    assert target == base / "releases" / manifest["release_id"]
    assert (base / "current").resolve() == target
    assert not (base / "previous").exists()
    assert (target / ".installed").read_text().strip() == manifest["release_id"]
    assert gateway.read_text() == "PRIVATE_FIXTURE=must-not-be-loaded\n"
    assert unit.read_text() == "existing service\n"
    assert {p.name for p in unit.parent.iterdir()} == {"existing.service"}
    assert all("systemctl" not in call and "loginctl" not in call for call in calls)
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "ir_cli" and result["service_started"] is False
    assert result["hardware_verified"] is False
    assert "PRIVATE_FIXTURE" not in json.dumps(result)


def test_ir_upgrade_retains_previous_and_reinstall_does_not_replace_it(tmp_path, monkeypatch):
    calls = offline_commands(monkeypatch)
    home = tmp_path / "user"
    targets = []
    for version in ("0.1.0", "0.2.0", "0.3.0"):
        source = tmp_path / version
        fake_release(source, version=version)
        targets.append(install.install_user_ir(source, user_directory=home))
    base = home / ".local/share/habitatos/ir"
    assert (base / "current").resolve() == targets[-1]
    assert (base / "previous").resolve() == targets[-2]
    assert not targets[0].exists()
    count = len(calls)
    install.install_user_ir(tmp_path / "0.3.0", user_directory=home)
    assert (base / "previous").resolve() == targets[-2]
    assert calls[count:] == [[str(targets[-1] / "venv/bin/habitat-ir"), "--help"]]


def test_invalid_new_cli_keeps_old_release_selected(tmp_path, monkeypatch):
    home = tmp_path / "user"
    source = tmp_path / "old"
    fake_release(source)
    offline_commands(monkeypatch)
    old = install.install_user_ir(source, user_directory=home)
    new = tmp_path / "new"
    fake_release(new, version="0.3.0")
    offline_commands(monkeypatch, fail_help=True)
    with pytest.raises(subprocess.CalledProcessError):
        install.install_user_ir(new, user_directory=home)
    base = home / ".local/share/habitatos/ir"
    assert (base / "current").resolve() == old
    assert not (base / "previous").exists()


def test_failed_current_promotion_restores_both_release_links(tmp_path, monkeypatch):
    home = tmp_path / "user"
    offline_commands(monkeypatch)
    targets = []
    for version in ("0.1.0", "0.2.0"):
        source = tmp_path / version
        fake_release(source, version=version)
        targets.append(install.install_user_ir(source, user_directory=home))
    source = tmp_path / "new"
    manifest = fake_release(source, version="0.3.0")
    point_link = install.point_link

    def fail_promotion(path, target):
        if path.name == "current" and target.name == manifest["release_id"]:
            raise OSError("promotion fixture failure")
        point_link(path, target)

    monkeypatch.setattr(install, "point_link", fail_promotion)
    with pytest.raises(OSError, match="promotion"):
        install.install_user_ir(source, user_directory=home)
    base = home / ".local/share/habitatos/ir"
    assert (base / "current").resolve() == targets[-1]
    assert (base / "previous").resolve() == targets[-2]


@pytest.mark.parametrize("unsafe", ["file", "outside_link"])
def test_ir_install_refuses_unmanaged_links(tmp_path, monkeypatch, unsafe):
    source = tmp_path / "source"
    fake_release(source)
    home = tmp_path / "user"
    base = home / ".local/share/habitatos/ir"
    base.mkdir(parents=True)
    if unsafe == "file":
        (base / "current").write_text("do not replace")
    else:
        (base / "current").symlink_to(tmp_path)
    calls = offline_commands(monkeypatch)
    with pytest.raises(ValueError, match="managed"):
        install.install_user_ir(source, user_directory=home)
    assert not calls


def test_ir_installer_requires_verified_source(tmp_path, monkeypatch):
    source = tmp_path / "source"
    fake_release(source)
    (source / "install.py").write_text("tampered")
    calls = offline_commands(monkeypatch)
    with pytest.raises(ValueError, match="checksum"):
        install.install_user_ir(source, user_directory=tmp_path / "user")
    assert not calls
    assert not (tmp_path / "user").exists()


def test_ir_cli_mode_needs_no_gateway_config(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(install, "install_user_ir", lambda release: seen.append(release))
    monkeypatch.setattr(sys, "argv", ["install.py", "--release", str(tmp_path), "--user-ir"])
    install.main()
    assert seen == [tmp_path]


@pytest.mark.parametrize("extra", [[], ["--user-heartbeat"], ["--user-ir", "--no-service"],
    ["--user-ir", "--root", "/tmp/staging"], ["--user-ir", "--config", "unused.toml"],
    ["--user-ir", "--user-heartbeat"]])
def test_install_modes_reject_missing_config_or_incompatible_flags(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(sys, "argv", ["install.py", "--release", str(tmp_path), *extra])
    with pytest.raises(SystemExit) as error:
        install.main()
    assert error.value.code == 2
