"""Public example builds must never consume a colocated private node config."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from deploy import build_release


SOURCE = Path(__file__).resolve().parents[2] / "firmware/cage_node"
SPEC = importlib.util.spec_from_file_location("bb6_example_build", SOURCE / "build.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
LOCK = json.loads((SOURCE / "dependencies.lock.json").read_text())


@pytest.fixture
def public_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in (*builder.SOURCE_FILES, "config.example.h"):
        shutil.copyfile(SOURCE / name, source / name)
    # An inaccessible/dangling private config must never be resolved or opened.
    (source / "config.h").symlink_to(tmp_path / "private-do-not-read")
    return source


@pytest.mark.parametrize("profile,enabled", [("sensor", 0), ("ir-locked", 1)])
def test_staging_uses_example_and_keeps_all_physical_outputs_locked(public_source, tmp_path, profile, enabled):
    sketch = tmp_path / "sketch"
    builder.stage_example(public_source, sketch, profile)
    content = (sketch / "config.h").read_text()
    assert "YOUR_WIFI_PASSWORD" in content
    assert f"#define HABITAT_IR_CONTROL {enabled}" in content
    for macro in ("HABITAT_IR_OUTPUTS", "HABITAT_R15_REQUEST_OUTPUTS",
                  "HABITAT_R11_PUMP", "HABITAT_R11_PUMP_OUTPUTS"):
        assert f"#define {macro} 0" in content
    assert set(p.name for p in sketch.iterdir()) == {*builder.SOURCE_FILES, "config.h"}


def test_staging_rejects_unlocked_or_symlinked_public_example(public_source, tmp_path):
    example = public_source / "config.example.h"
    example.write_text(example.read_text().replace("#define HABITAT_IR_OUTPUTS 0", "#define HABITAT_IR_OUTPUTS 1"))
    with pytest.raises(ValueError, match="lock physical outputs"):
        builder.stage_example(public_source, tmp_path / "unlocked", "sensor")
    example.unlink()
    example.symlink_to(SOURCE / "config.example.h")
    with pytest.raises(ValueError, match="regular public"):
        builder.stage_example(public_source, tmp_path / "symlink", "sensor")


@pytest.mark.parametrize("fault", ["cli", "core", "library", "ambiguous_library", None])
def test_toolchain_version_check_fails_before_compilation(monkeypatch, fault):
    def run(command, **kwargs):
        kind = command[1]
        assert command[-2:] == ["--format", "json"]
        assert kind in {"version", "core", "lib"}
        if kind == "version":
            value = {"VersionString": "unknown" if fault == "cli" else LOCK["arduino_cli_versions"][0]}
        elif kind == "core":
            value = {"platforms": [{"id": LOCK["core"]["id"], "installed_version":
                                   "0.0.0" if fault == "core" else LOCK["core"]["version"]}]}
        else:
            items = [{"library": {"name": name, "version": version}} for name, version in LOCK["libraries"].items()]
            if fault == "library":
                items.pop()
            if fault == "ambiguous_library":
                items.append({"library": {"name": "OneWire", "version": "0.0.0"}})
            value = {"installed_libraries": items}
        return SimpleNamespace(stdout=json.dumps(value))
    monkeypatch.setattr(builder.subprocess, "run", run)
    if fault:
        with pytest.raises(ValueError):
            builder.inspect_toolchain("arduino-cli", LOCK)
    else:
        assert builder.inspect_toolchain("arduino-cli", LOCK) == LOCK["arduino_cli_versions"][0]


def test_build_is_offline_compile_only_and_cleans_staged_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "inspect_toolchain", lambda *args: "1.5.1")
    staged = []
    output = tmp_path / "output"
    def compile_only(command, **kwargs):
        assert command[1] == "compile"
        assert "--port" not in command and "--upload" not in command
        assert command[command.index("--fqbn") + 1] == LOCK["fqbn"]
        sketch = Path(command[-1])
        staged.append(sketch)
        assert "YOUR_WIFI_PASSWORD" in (sketch / "config.h").read_text()
        (output / "cage_node.ino.bin").write_bytes(b"example-only")
    monkeypatch.setattr(builder.subprocess, "run", compile_only)
    manifest = builder.build("arduino-cli", output, "ir-locked")
    assert not manifest["deployable"] and not manifest["hardware_outputs_enabled"]
    assert manifest["files"][0]["bytes"] == 12
    assert (output / "build-manifest.json").is_file()
    assert all(not path.exists() for path in staged)
    with pytest.raises(ValueError, match="must be new"):
        builder.build("arduino-cli", output, "sensor")
    with pytest.raises(ValueError, match="outside"):
        builder.build("arduino-cli", SOURCE / "build", "sensor")


def test_failed_compile_has_no_success_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "inspect_toolchain", lambda *args: "1.5.1")
    staged = []
    def fail(command, **kwargs):
        staged.append(Path(command[-1]))
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(builder.subprocess, "run", fail)
    output = tmp_path / "output"
    with pytest.raises(subprocess.CalledProcessError):
        builder.build("arduino-cli", output, "sensor")
    assert not (output / "build-manifest.json").exists()
    assert all(not path.exists() for path in staged)


def test_release_includes_build_instructions_but_not_private_or_generated_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in (*builder.SOURCE_FILES, "config.example.h", *build_release.CAGE_BUILD_FILES):
        shutil.copyfile(SOURCE / name, source / name)
    (source / "config.h").write_text("private-fixture")
    (source / "flash.bin").write_bytes(b"private-binary")
    (source / "build-manifest.json").write_text("{}")
    exported = tmp_path / "export"
    build_release.copy_public_firmware(source, exported)
    assert set(p.name for p in exported.iterdir()) == {
        *builder.SOURCE_FILES, "config.example.h", *build_release.CAGE_BUILD_FILES}
