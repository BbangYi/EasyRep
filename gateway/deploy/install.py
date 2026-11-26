"""Install an offline HabitatOS release, preserving per-Pi identity and secrets.

Run with system Python 3.11+. --root /tmp/... --no-service supports staging tests.
No package indexes, shell expansion, or device outputs are used by this installer.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

SERVICE = "habitat-gateway.service"
HEARTBEAT_SERVICE = "habitat-heartbeat.service"
DATA_PATH = "/var/lib/habitat-gateway/gateway.sqlite3"


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def verify_release(directory):
    manifest = json.loads((directory / "release.json").read_text())
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{12}", manifest["release_id"]):
        raise ValueError("invalid release ID")
    if manifest["python"] != f"{sys.version_info.major}.{sys.version_info.minor}" or manifest["machine"] != platform.machine():
        raise ValueError("release Python/CPU does not match this Pi; rebuild on a matching platform")
    if manifest["storage_schema"] != 1:
        raise ValueError("unsupported database schema")
    for name, expected in manifest["files"].items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("unsafe release path")
        source = directory / name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"missing or unsafe release file: {name}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError(f"checksum mismatch: {name}")
    required = {"install.py", "habitat-gateway.service", "requirements.lock", "simulation.toml"}
    if not required <= manifest["files"].keys() or not any(name.startswith("wheels/habitat_gateway-") for name in manifest["files"]):
        raise ValueError("incomplete release")
    digest = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()[:12]
    if manifest["release_id"] != f"{manifest['version']}-{digest}":
        raise ValueError("release ID does not match manifest")
    return manifest


def unpack(archive, destination):
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if sum(member.size for member in members) > 512 * 1024 * 1024 or len(members) > 1000:
            raise ValueError("release archive too large")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe archive member")
        tar.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError("archive must contain exactly one release directory")
    return children[0]


def read_environment(path):
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c.isspace() or c in "\"'\\" for c in value):
            raise ValueError("environment file must use unquoted KEY=value lines")
        result[key] = value
    return result


def write_atomic(path, content, mode=0o644):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def point_link(path, target):
    temporary = path.with_name(f".{path.name}-{secrets.token_hex(4)}")
    temporary.symlink_to(target)
    os.replace(temporary, path)


def check_identity(old, new):
    for key in ("site_id", "gateway_id"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", new.get(key, "")):
            raise ValueError(f"invalid {key}")
        if old and old[key] != new[key]:
            raise ValueError(f"refusing to change existing {key}; migrate identity and data explicitly")
    if new.get("database") != DATA_PATH:
        raise ValueError(f"deployment database must be {DATA_PATH}")


def wait_healthy(config, token, release_id, timeout=30):
    server = config.get("server", {})
    host = server.get("host", "127.0.0.1")
    host = "127.0.0.1" if host == "0.0.0.0" else ("::1" if host == "::" else host)
    host = f"[{host}]" if ":" in host else host
    base = f"http://{host}:{server.get('port', 8000)}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(base + "/health", timeout=2) as response:
                health = json.load(response)
            request = urllib.request.Request(base + "/v1/gateway", headers={"Authorization": f"Bearer {token}"})
            with opener.open(request, timeout=2) as response:
                identity = json.load(response)
            if health["status"] == "ok" and all(identity[key] == config[key] for key in ("site_id", "gateway_id")) and identity["release_id"] == release_id:
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)
    raise RuntimeError("new release failed health/identity verification")


def install(release, config_path, root=Path("/"), no_service=False):
    root = root.resolve()
    if root == Path("/") and (os.geteuid() != 0 or no_service):
        raise ValueError("system installation requires sudo and service management")
    if root != Path("/") and not no_service:
        raise ValueError("staging installation requires --no-service")
    manifest = verify_release(release)
    config_text = config_path.read_text()
    config = tomllib.loads(config_text)
    etc = root / "etc/habitat-gateway"
    base = root / "opt/habitat-gateway"
    config_target = etc / "gateway.toml"
    check_identity(None, config)
    etc.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    with (base / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_config = tomllib.loads(config_target.read_text()) if config_target.exists() else None
        check_identity(old_config, config)
        _install_locked(release, manifest, config_path, config_text, config, root, etc, base, no_service)


def prepare_release(release, manifest, base):
    """Install one verified, immutable release using its bundled wheels only."""
    # Only this public, credential-free release tree needs to be readable by the
    # DynamicUser service. Preserve the caller's private umask everywhere else.
    previous_umask = os.umask(0o022)
    try:
        return _prepare_release(release, manifest, base)
    finally:
        os.umask(previous_umask)


def _prepare_release(release, manifest, base):
    target = base / "releases" / manifest["release_id"]
    if not target.exists():
        target.mkdir(parents=True, mode=0o755)
        # Copy only manifest-listed files; never copy secrets, working trees or local DBs.
        for name in [*manifest["files"], "release.json"]:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            shutil.copyfile(release / name, destination)
            destination.chmod(0o644)
        run(sys.executable, "-m", "venv", target / "venv")
        wheel = next((target / "wheels").glob("habitat_gateway-*.whl"))
        run(target / "venv/bin/python", "-m", "pip", "install", "--no-cache-dir", "--no-index",
            "--find-links", target / "wheels", "--constraint", target / "requirements.lock", wheel)
        write_atomic(target / "release.env", f"HABITAT_RELEASE_ID={manifest['release_id']}\n")
        write_atomic(target / ".installed", manifest["release_id"] + "\n")
    else:
        verify_release(target)
        if not (target / ".installed").exists():
            raise ValueError(f"incomplete prior installation: {target}; inspect it before retrying")
    return target


def prune_releases(base):
    """Remove completed installer releases except current and previous."""
    releases = (base / "releases").resolve()
    keep = set()
    for name in ("current", "previous"):
        link = base / name
        if link.is_symlink():
            target = link.resolve(strict=True)
            if target.parent != releases:
                raise ValueError("release link points outside managed releases")
            keep.add(target)
    if not (base / "current").is_symlink():
        return []
    removed = []
    for path in releases.iterdir():
        if path.is_symlink() or not path.is_dir() or path.resolve() in keep:
            continue
        marker = path / ".installed"
        if marker.is_file() and not marker.is_symlink() and marker.read_text().strip() == path.name:
            verify_release(path)
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


def _install_locked(release, manifest, config_path, config_text, config, root, etc, base, no_service):
    environment_path = etc / "gateway.env"
    environment = read_environment(environment_path)
    environment.setdefault("HABITAT_API_TOKEN", secrets.token_urlsafe(32))
    if len(environment["HABITAT_API_TOKEN"]) < 32:
        raise ValueError("existing API token is too short")
    if config["transport"] == "mqtt" and not environment.get(config.get("mqtt", {}).get("password_env", "HABITAT_MQTT_PASSWORD")):
        raise ValueError("configure MQTT credentials in /etc/habitat-gateway/gateway.env before installing MQTT mode")
    target = prepare_release(release, manifest, base)
    process_env = {**os.environ, **environment, "PYTHONDONTWRITEBYTECODE": "1"}
    run(target / "venv/bin/python", "-m", "habitat_gateway", "--config", config_path.resolve(),
        "--check-config", env=process_env, cwd=target)
    config_target = etc / "gateway.toml"
    old_config_bytes = config_target.read_text() if config_target.exists() else None
    old_target = (base / "current").resolve() if (base / "current").is_symlink() else None
    if (base / "current").exists() and old_target is None:
        raise ValueError("current must be an installer-managed symlink")
    unit = root / "etc/systemd/system" / SERVICE
    unit.parent.mkdir(parents=True, exist_ok=True)
    old_unit = unit.read_text() if unit.exists() else None
    was_active = False
    if not no_service:
        was_active = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0
    try:
        if not no_service:
            run("systemctl", "stop", SERVICE) if old_unit else None
            database = root / DATA_PATH.lstrip("/")
            if database.exists():
                backups = base / "backups"
                backups.mkdir(mode=0o700, exist_ok=True)
                backup = backups / f"{time.time_ns()}.sqlite3"
                with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source, sqlite3.connect(backup) as destination:
                    source.backup(destination)
                backup.chmod(0o600)
        write_atomic(environment_path, "".join(f"{key}={value}\n" for key, value in sorted(environment.items())), 0o600)
        write_atomic(config_target, config_text)
        write_atomic(unit, (target / "habitat-gateway.service").read_text())
        point_link(base / "current", target)
        if not no_service:
            run("systemctl", "daemon-reload")
            run("systemctl", "start", SERVICE)
            wait_healthy(config, environment["HABITAT_API_TOKEN"], manifest["release_id"])
            run("systemctl", "enable", SERVICE)
        if old_target and old_target != target:
            point_link(base / "previous", old_target)
    except Exception:
        if not no_service:
            subprocess.run(["systemctl", "stop", SERVICE], check=False)
        if old_target:
            point_link(base / "current", old_target)
        elif (base / "current").is_symlink():
            (base / "current").unlink()
        if old_config_bytes is not None:
            write_atomic(config_target, old_config_bytes)
        if old_unit is not None:
            write_atomic(unit, old_unit)
        elif unit.exists():
            unit.unlink()
        if not no_service:
            run("systemctl", "daemon-reload")
            if was_active and old_target:
                run("systemctl", "start", SERVICE)
        raise
    print(json.dumps({"installed": manifest["release_id"], "site_id": config["site_id"],
                      "gateway_id": config["gateway_id"], "service_started": not no_service,
                      "credentials_file": str(environment_path)}))
    try:
        prune_releases(base)
    except (OSError, ValueError):
        print("warning: release cleanup deferred; installation remains healthy", file=sys.stderr)


def install_user_heartbeat(release, config_path, *, user_directory=None):
    """Install an outbound-only user service; keep existing credentials private."""
    user_directory = Path.home() if user_directory is None else Path(user_directory)
    manifest = verify_release(release)
    if HEARTBEAT_SERVICE not in manifest["files"]:
        raise ValueError("release does not support the heartbeat user service")
    linger = run("loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value",
                 capture_output=True, text=True).stdout.strip()
    if linger != "yes":
        raise ValueError("user lingering must be enabled before installing a boot-persistent heartbeat service")
    etc = user_directory / ".config/habitatos"
    environment_path = etc / "gateway.env"
    info = environment_path.lstat()
    if environment_path.is_symlink() or not environment_path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
        raise ValueError("credentials must be an owner-only regular file with mode 0600")
    if etc.is_symlink() or etc.stat().st_uid != os.getuid() or etc.stat().st_mode & 0o777 != 0o700:
        raise ValueError("credentials directory must be owner-only with mode 0700")
    environment = read_environment(environment_path)
    config_text = config_path.read_text()
    config = tomllib.loads(config_text)
    if not config.get("cloud", {}).get("enabled"):
        raise ValueError("heartbeat service requires cloud.enabled")
    base = user_directory / ".local/share/habitatos/gateway"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_target = etc / "gateway.toml"
    unit = user_directory / ".config/systemd/user" / HEARTBEAT_SERVICE
    with (base / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_config = config_target.read_text() if config_target.exists() else None
        check_identity(tomllib.loads(old_config) if old_config else None, config)
        target = prepare_release(release, manifest, base)
        run(target / "venv/bin/python", "-m", "habitat_gateway", "--config", config_path.resolve(),
            "--heartbeat-only", "--check-config", cwd=target,
            env={**os.environ, **environment, "PYTHONDONTWRITEBYTECODE": "1"})
        old_target = (base / "current").resolve() if (base / "current").is_symlink() else None
        if (base / "current").exists() and old_target is None:
            raise ValueError("current must be an installer-managed symlink")
        old_unit = unit.read_text() if unit.exists() else None
        unit.parent.mkdir(parents=True, exist_ok=True)
        was_active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", HEARTBEAT_SERVICE]).returncode == 0
        try:
            if was_active:
                run("systemctl", "--user", "stop", HEARTBEAT_SERVICE)
            write_atomic(config_target, config_text, 0o600)
            write_atomic(unit, (target / HEARTBEAT_SERVICE).read_text(), 0o600)
            point_link(base / "current", target)
            run("systemctl", "--user", "daemon-reload")
            run("systemctl", "--user", "start", HEARTBEAT_SERVICE)
            run("systemctl", "--user", "is-active", "--quiet", HEARTBEAT_SERVICE)
            run("systemctl", "--user", "enable", HEARTBEAT_SERVICE)
            if old_target and old_target != target:
                point_link(base / "previous", old_target)
        except Exception:
            subprocess.run(["systemctl", "--user", "stop", HEARTBEAT_SERVICE], check=False)
            if old_target:
                point_link(base / "current", old_target)
            elif (base / "current").is_symlink():
                (base / "current").unlink()
            for path, previous in ((config_target, old_config), (unit, old_unit)):
                if previous is not None:
                    write_atomic(path, previous, 0o600)
                elif path.exists():
                    path.unlink()
            run("systemctl", "--user", "daemon-reload")
            if was_active:
                run("systemctl", "--user", "start", HEARTBEAT_SERVICE)
            raise
    print(json.dumps({"installed": manifest["release_id"], "site_id": config["site_id"],
                      "gateway_id": config["gateway_id"], "service": HEARTBEAT_SERVICE,
                      "mode": "heartbeat_only", "credentials_file": str(environment_path)}))
    try:
        prune_releases(base)
    except (OSError, ValueError):
        print("warning: release cleanup deferred; installation remains healthy", file=sys.stderr)


def install_user_ir(release, *, user_directory=None):
    """Install only the manual IR CLI; never read credentials or manage services."""
    user_directory = Path.home() if user_directory is None else Path(user_directory)
    manifest = verify_release(release)
    base = user_directory / ".local/share/habitatos/ir"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (base / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_links = {}
        for name in ("current", "previous"):
            link = base / name
            if link.is_symlink():
                target = link.resolve(strict=True)
                if target.parent != (base / "releases").resolve():
                    raise ValueError("IR release link points outside managed releases")
                old_links[name] = target
            elif link.exists():
                raise ValueError(f"{name} must be an installer-managed symlink")
            else:
                old_links[name] = None
        target = prepare_release(release, manifest, base)
        # --help imports the installed entrypoint but cannot connect or publish.
        run(target / "venv/bin/habitat-ir", "--help", cwd=target,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=15)
        try:
            if old_links["current"] and old_links["current"] != target:
                point_link(base / "previous", old_links["current"])
            point_link(base / "current", target)
        except Exception:
            for name, previous in old_links.items():
                link = base / name
                if previous is not None:
                    point_link(link, previous)
                elif link.is_symlink():
                    link.unlink()
            raise
        try:
            prune_releases(base)
        except (OSError, ValueError):
            print("warning: IR release cleanup deferred; CLI installation remains valid", file=sys.stderr)
    print(json.dumps({"installed": manifest["release_id"], "mode": "ir_cli",
        "command": str(base / "current/venv/bin/habitat-ir"),
        "service_started": False, "hardware_verified": False}))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--release", type=Path)
    source.add_argument("--archive", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--no-service", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--user-heartbeat", action="store_true",
                      help="Install a heartbeat-only user service using ~/.config/habitatos/gateway.env")
    mode.add_argument("--user-ir", action="store_true",
                      help="Install the manual IR CLI for this user without changing any service")
    args = parser.parse_args()
    if not args.user_ir and args.config is None:
        parser.error("--config is required for Gateway and heartbeat installation")
    if args.user_heartbeat and (args.no_service or args.root != Path("/")):
        parser.error("--user-heartbeat cannot be combined with --root or --no-service")
    if args.user_ir and (args.config is not None or args.no_service or args.root != Path("/")):
        parser.error("--user-ir cannot be combined with --config, --root or --no-service")

    def apply(directory):
        if args.user_ir:
            install_user_ir(directory)
        elif args.user_heartbeat:
            install_user_heartbeat(directory, args.config)
        else:
            install(directory, args.config, args.root, args.no_service)

    if args.archive:
        with tempfile.TemporaryDirectory(prefix="habitat-release-") as temporary:
            apply(unpack(args.archive, Path(temporary)))
    else:
        apply(args.release.resolve())


if __name__ == "__main__":
    main()
