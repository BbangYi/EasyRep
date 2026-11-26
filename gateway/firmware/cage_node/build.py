#!/usr/bin/env python3
"""Compile public BB6 examples offline; no device access or private configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


SOURCE_FILES = ("cage_node.ino", "ir_controller.h", "ir_runtime.h", "r15_bridge.h")
PROFILES = {"sensor": False, "ir-locked": True}


def inspect_toolchain(cli, lock):
    def query(*args):
        result = subprocess.run([cli, *args, "--format", "json"], check=True,
                                capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    version = query("version").get("VersionString")
    if version not in lock["arduino_cli_versions"]:
        raise ValueError("Use an Arduino CLI version listed in dependencies.lock.json")
    platforms = query("core", "list")
    if isinstance(platforms, dict):
        platforms = platforms.get("platforms", [])
    if not any(item.get("id") == lock["core"]["id"] and
               item.get("installed_version") == lock["core"]["version"] for item in platforms):
        raise ValueError("Pinned ESP32 core is not installed")
    libraries = query("lib", "list")
    if isinstance(libraries, dict):
        libraries = libraries.get("installed_libraries", [])
    installed = {}
    for item in libraries:
        library = item.get("library", item)
        installed.setdefault(library.get("name"), set()).add(library.get("version"))
    for name, required in lock["libraries"].items():
        if installed.get(name) != {required}:
            raise ValueError("Missing, ambiguous, or wrong library version: " + name)
    return version


def stage_example(source, sketch, profile):
    """Read only the public allowlist, even if a real config.h is beside it."""
    sketch.mkdir()
    for name in (*SOURCE_FILES, "config.example.h"):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Expected a regular public firmware file: " + name)
        if name == "config.example.h":
            content = path.read_text(encoding="utf-8")
            for macro in ("HABITAT_IR_OUTPUTS", "HABITAT_R15_REQUEST_OUTPUTS",
                          "HABITAT_R11_PUMP", "HABITAT_R11_PUMP_OUTPUTS"):
                if f"#define {macro} 0" not in content:
                    raise ValueError("Public example must lock physical outputs: " + macro)
            marker = "#define HABITAT_IR_CONTROL 0"
            if marker not in content:
                raise ValueError("Public example IR configuration changed; review build profiles")
            if PROFILES[profile]:
                content = content.replace(marker, "#define HABITAT_IR_CONTROL 1")
            (sketch / "config.h").write_text(content, encoding="utf-8")
        else:
            shutil.copyfile(path, sketch / name)


def build(cli, output, profile):
    source = Path(__file__).resolve().parent
    if profile not in PROFILES:
        raise ValueError("Unknown public example profile")
    output = Path(output).resolve()
    if output.is_relative_to(source.parents[1]):
        raise ValueError("Build output must be outside the source directory")
    if output.exists():
        raise ValueError("Output directory must be new; existing builds are preserved")
    lock = json.loads((source / "dependencies.lock.json").read_text(encoding="utf-8"))
    version = inspect_toolchain(cli, lock)
    output.mkdir(parents=True)
    # On failure retain diagnostic output, but do not write a success manifest.
    with tempfile.TemporaryDirectory(prefix="habitatos-bb6-example-") as temporary:
        sketch = Path(temporary) / "cage_node"
        stage_example(source, sketch, profile)
        subprocess.run([cli, "compile", "--jobs", "1", "--fqbn", lock["fqbn"],
                        "--build-path", str(Path(temporary) / "build"),
                        "--output-dir", str(output), str(sketch)], check=True)
    files = [{"path": path.name, "bytes": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(output.iterdir()) if path.is_file()]
    if not any(item["path"] == "cage_node.ino.bin" for item in files):
        raise ValueError("Compiler did not produce the expected application")
    manifest = {"schema_version": 1, "profile": profile, "arduino_cli": version,
                "toolchain": lock, "configuration": "public-example-only",
                "deployable": False, "hardware_verified": False,
                "hardware_outputs_enabled": False, "files": files}
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arduino-cli", default=shutil.which("arduino-cli"))
    parser.add_argument("--output", type=Path, required=True, help="New directory outside source")
    parser.add_argument("--profile", choices=PROFILES, default="sensor")
    args = parser.parse_args()
    if not args.arduino_cli:
        parser.error("arduino-cli is not on PATH; supply --arduino-cli")
    project = Path(__file__).resolve().parents[2]
    if args.output.resolve().is_relative_to(project):
        parser.error("Build output must be outside the source directory")
    try:
        manifest = build(args.arduino_cli, args.output, args.profile)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"BB6 example build failed: {error}\n")
    print(json.dumps({"output": str(args.output.resolve()), "profile": manifest["profile"],
                      "deployable": False, "hardware_verified": False}))


if __name__ == "__main__":
    main()
