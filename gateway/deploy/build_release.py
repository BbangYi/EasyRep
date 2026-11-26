"""Build a self-contained wheel bundle for Pis matching the build host's Python/CPU."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile


CAMERA_NATIVE_FILES = ("h264_node.ino", "camera_contract.h", "build.py",
                       "prepare_dependencies.py", "dependencies.lock.json", "README.md")
CAGE_BUILD_FILES = ("build.py", "dependencies.lock.json", "README.md")


def copy_public_firmware(source, destination):
    """Release only firmware source/examples; never local credentials or binaries."""
    destination.mkdir(parents=True)
    for path in source.iterdir():
        if path.name == "config.h" or (path.suffix not in {".ino", ".h", ".cpp"}
                                       and path.name not in CAGE_BUILD_FILES):
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("public firmware source must be a regular file")
        shutil.copyfile(path, destination / path.name)


def copy_public_camera_firmware(source, destination):
    """Only the shared program and credential-free example belong in a release."""
    destination.mkdir(parents=True)
    for name in ("main.py", "config.example.json"):
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("public camera firmware must be a regular file")
        shutil.copyfile(path, destination / name)
    native = source / "h264_node"
    if native.exists():
        (destination / "h264_node").mkdir()
        for name in CAMERA_NATIVE_FILES:
            path = native / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("public native camera firmware must be a regular file")
            shutil.copyfile(path, destination / "h264_node" / name)


def build_source_handoff(project, output, version):
    """Small portable source handoff; the existing Pi builds its own offline wheels."""
    selected = [project / name for name in (
        "pyproject.toml", "requirements.lock", "README.md", "config/simulation.toml",
        "docs/operations/new-store-setup.md", "docs/operations/compute-client.md",
        "docs/operations/hardware-arrival.md", "docs/operations/livescene-sample.md",
        "docs/operations/pi-update.md", "docs/operations/project-layout.md",
        "firmware/cage_node/cage_node.ino", "firmware/cage_node/config.example.h",
        "firmware/cage_node/r15_bridge.h", "firmware/cage_node/ir_controller.h",
        "firmware/cage_node/ir_runtime.h", "docs/protocols/r15-bridge.md",
        "docs/protocols/ir-control.md",
        "firmware/camera_node/main.py", "firmware/camera_node/config.example.json",
        "docs/saas-integration.md",
        "experiments/environment_sim/gpu_predict.py",
        "experiments/environment_sim/predictive_misting.py",
        "experiments/environment_sim/simulation_config.json",
        "habitat_gateway/assets/terrarium-tropical.webp",
        "habitat_gateway/assets/terrarium-desert.webp",
        "habitat_gateway/assets/terrarium-aquatic.webp",
    )]
    for directory, extensions in (
        ("habitat", {".py", ".html", ".js"}), ("habitat_gateway", {".py", ".html"}),
        ("apps", {".py"}), ("deploy", {".py", ".sh", ".service"}),
        ("configs/defaults", {".toml"}), ("configs/examples", {".toml", ".json"}),
        ("configs/schemas", {".json"}),
    ):
        selected.extend(path for path in (project / directory).rglob("*")
                        if path.suffix in extensions and path.is_file())
    selected.extend((project / "habitat_gateway/assets").glob("*.js"))
    selected.extend((project / "habitat_gateway/assets").glob("*LICENSE.txt"))
    native = project / "firmware/camera_node/h264_node"
    if native.exists():
        selected.extend(native / name for name in CAMERA_NATIVE_FILES)
    selected.extend(project / "firmware/cage_node" / name for name in CAGE_BUILD_FILES)
    content = {"__main__.py": (project / "deploy/pi_handoff.py").read_bytes()}
    for path in sorted(set(selected)):
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
            raise ValueError("handoff source must remain inside the project")
        content["source/" + path.relative_to(project).as_posix()] = path.read_bytes()
    manifest = {"version": version, "files": {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(content.items())}}
    content["handoff.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    archive = output / f"HabitatOS-Pi-{version}.pyz"
    with tempfile.TemporaryDirectory(prefix="handoff-", dir=output) as temporary:
        pending = Path(temporary) / archive.name
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, data in sorted(content.items()):
                item = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o100644 << 16
                bundle.writestr(item, data)
        # Public source artifact: new outputs inherit the directory ACL, not the temp ACL.
        shutil.copyfile(pending, archive)
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "version": version, "source_files": len(selected),
                      "installed": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "dist")
    parser.add_argument("--wheel-cache", type=Path, help="Existing matching-platform wheels for an offline dependency bundle")
    parser.add_argument("--with-air", action="store_true", help="Include the optional local air viewer's NumPy dependency")
    parser.add_argument("--source-handoff", action="store_true",
                        help="Build one portable .pyz for an existing Pi, using that Pi's cached wheels")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    version = tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.source_handoff:
        build_source_handoff(project, output, version)
        return
    with tempfile.TemporaryDirectory(prefix="bundle-", dir=output) as temporary:
        bundle = Path(temporary)
        wheels = bundle / "wheels"
        wheels.mkdir()
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-cache-dir", "--no-deps",
                        "--no-build-isolation",
                        "--wheel-dir", str(wheels), str(project)], check=True)
        wheel = next(wheels.glob("habitat_gateway-*.whl"))
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-cache-dir", "--only-binary=:all:",
                        *(["--no-index", "--find-links", str(args.wheel_cache.resolve())] if args.wheel_cache else []),
                        "--dest", str(wheels), "--constraint", str(project / "requirements.lock"),
                        str(wheel) + ("[air]" if args.with_air else "")], check=True)
        for source, name in ((project / "deploy/install.py", "install.py"),
                             (project / "deploy/connect.py", "connect.py"),
                             (project / "deploy/connect.sh", "connect.sh"),
                             (project / "deploy/provision.py", "provision.py"),
                             (project / "configs/defaults/cloud.toml", "cloud-defaults.toml"),
                             (project / "docs/operations/new-store-setup.md", "CONNECT.md"),
                             (project / "deploy/habitat-gateway.service", "habitat-gateway.service"),
                             (project / "deploy/systemd/habitat-compute.service", "habitat-compute.service"),
                             (project / "deploy/systemd/habitat-heartbeat.service", "habitat-heartbeat.service"),
                             (project / "config/simulation.toml", "simulation.toml"),
                             (project / "requirements.lock", "requirements.lock")):
            shutil.copyfile(source, bundle / name)
        (bundle / "compute.toml").write_text((project / "configs/examples/compute.toml").read_text().replace(
            'storage_dir = "var/data/compute"', 'storage_dir = "/var/lib/habitat-compute"'))
        shutil.copytree(project / "configs/schemas/compute-v1", bundle / "compute-schemas-v1")
        shutil.copyfile(project / "docs/operations/compute-client.md", bundle / "compute-client.md")
        shutil.copyfile(project / "docs/operations/hardware-arrival.md", bundle / "hardware-arrival.md")
        shutil.copyfile(project / "configs/examples/reptile-city.toml", bundle / "reptile-city.toml")
        shutil.copyfile(project / "deploy/prepare_devices.py", bundle / "prepare_devices.py")
        shutil.copyfile(project / "deploy/edge_tools.py", bundle / "edge_tools.py")
        shutil.copyfile(project / "deploy/camera_node.py", bundle / "camera_node.py")
        shutil.copyfile(project / "deploy/provision_ir.py", bundle / "provision_ir.py")
        shutil.copyfile(project / "deploy/provision_ir_web.py", bundle / "provision_ir_web.py")
        shutil.copyfile(project / "configs/examples/ir.json", bundle / "ir.example.json")
        shutil.copyfile(project / "docs/protocols/ir-control.md", bundle / "ir-control.md")
        if args.with_air:
            shutil.copyfile(project / "deploy/install_air.py", bundle / "install_air.py")
            shutil.copyfile(project / "deploy/install_air_remote.py", bundle / "install_air_remote.py")
            shutil.copyfile(project / "deploy/systemd/habitat-air-viewer.service", bundle / "habitat-air-viewer.service")
            shutil.copyfile(project / "deploy/systemd/habitat-air-remote.service", bundle / "habitat-air-remote.service")
            shutil.copyfile(project / "configs/examples/air-viewer.json", bundle / "air-viewer.json")
            shutil.copyfile(project / "configs/examples/air-upload.json", bundle / "air-upload.json")
            shutil.copyfile(project / "configs/examples/air-remote.Caddyfile", bundle / "air-remote.Caddyfile")
        copy_public_firmware(project / "firmware/cage_node", bundle / "firmware/cage_node")
        copy_public_camera_firmware(project / "firmware/camera_node", bundle / "firmware/camera_node")
        hashes = {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in sorted(bundle.rglob("*")) if path.is_file()}
        digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]
        release_id = f"{version}-{digest}"
        manifest = {"release_id": release_id, "version": version, "storage_schema": 1,
                    "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                    "machine": platform.machine(), "files": hashes}
        (bundle / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
        archive = output / f"habitat-gateway-{release_id}.tar.gz"
        with tarfile.open(archive, "x:gz") as tar:
            tar.add(bundle, arcname=release_id)
        (output / f"{archive.name}.sha256").write_text(
            f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    print(json.dumps({"archive": str(archive), **manifest}, indent=2))


if __name__ == "__main__":
    main()
