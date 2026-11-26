"""Provision the local camera IR worker, without changing firmware or broker ACLs.

Dry-run is the default. Apply starts only habitat-ir-web.service. Gateway config
and its restart remain part of the versioned Gateway deployment. Credentials
are generated once and never returned in command output or command arguments.
"""
import argparse
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import time
import tomllib
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

try:
    from .provision_ir import Snapshot, atomic_write, encode_json, identifier, no_symlinks, private_directory
except ImportError:  # Executed directly from a verified release's deploy directory.
    from provision_ir import Snapshot, atomic_write, encode_json, identifier, no_symlinks, private_directory


SERVICE = "habitat-ir-web.service"
BRIDGE_KEY = "HABITAT_IR_BRIDGE_TOKEN"
CONTROL_KEY = "HABITAT_CAMERA_CONTROL_TOKEN"
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,256}\Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_file(snapshot, uid):
    if snapshot.data is None or snapshot.uid != uid or snapshot.mode != 0o600:
        raise ValueError("IR provisioning files must have the expected owner and mode 0600")


def tokens_from_env(data):
    """Only interpret our two keys; preserve all unrelated bytes verbatim."""
    result = {}
    for row in data.decode().splitlines():
        stripped = row.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if key.strip() not in (BRIDGE_KEY, CONTROL_KEY):
            continue
        key = key.strip()
        if not separator or key in result or not TOKEN.fullmatch(value):
            raise ValueError("invalid or duplicate camera IR credential in environment")
        result[key] = value
    return result


def quoted(value):
    value = str(value)
    if any(c in value for c in ('\n', '\r', '\0', '%', '$', '\\', '"')):
        raise ValueError("unsupported character in systemd path")
    return '"' + value + '"'


def absolute_unit_path(value):
    """EnvironmentFile uses a literal path, unlike ExecStart's word parser."""
    value = str(value)
    if not Path(value).is_absolute() or any(c.isspace() or c in '\0%$\\"' for c in value):
        raise ValueError("unsupported absolute systemd environment path")
    return value


def service_text(user, current, config, env, state, port):
    # The same user and HOME keep the firmware sequence/lock shared with the CLI.
    identifier(user.pw_name)
    if user.pw_uid == 0:
        raise ValueError("IR web worker must run as the existing non-root IR operator")
    return ("[Unit]\nDescription=HabitatOS camera IR control worker\n"
            "After=network.target mosquitto.service\n\n[Service]\nType=simple\n"
            f"User={user.pw_name}\nGroup={user.pw_gid}\n"
            "WorkingDirectory=/\n"
            f"EnvironmentFile={absolute_unit_path(env)}\n"
            f"Environment={quoted('HOME=' + user.pw_dir)}\n"
            "Environment=PYTHONDONTWRITEBYTECODE=1\n"
            f"ExecStart={quoted(current / 'venv/bin/python')} -m apps.worker.ir_web "
            f"--config {quoted(config)} --port {port}\n"
            "Restart=on-failure\nRestartSec=5\nTimeoutStopSec=15\nUMask=0077\n"
            "NoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\n"
            "ProtectHome=read-only\nRestrictSUIDSGID=true\n"
            f"ReadWritePaths={quoted(state)}\n\n[Install]\nWantedBy=multi-user.target\n").encode()


def viewer_address(value):
    if not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/camera"):
        raise ValueError("viewer URL must be an HTTPS /camera address without credentials, query or fragment")
    if any(ord(c) < 33 for c in value):
        raise ValueError("invalid viewer URL")
    return value.rstrip("/")


def control_page(url, token):
    link = html.escape(url + "#control_key=" + token, quote=True)
    return ("<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\">"
            "<meta name=\"referrer\" content=\"no-referrer\"><title>HabitatOS IR 제어</title>"
            "<h1>카메라 · IR 제어</h1><p>이 파일은 IR 제어 권한을 포함합니다.</p>"
            f"<a href=\"{link}\" rel=\"noreferrer\">카메라와 IR 제어 열기</a></html>\n").encode()


def plan(profile, cages, user, *, gateway_env, receipt_root, runtime_dir, unit_file,
         viewer_url=None, max_on_seconds=900, port=8093):
    identifier(user.pw_name)
    if user.pw_uid == 0:
        raise ValueError("IR web worker must run as the existing non-root IR operator")
    if not cages or len(set(cages)) != len(cages):
        raise ValueError("select each cage exactly once")
    cages = sorted(identifier(c) for c in cages)
    if type(max_on_seconds) is not int or not 1 <= max_on_seconds <= 900:
        raise ValueError("max_on_seconds must be between 1 and 900")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("worker port must be between 1024 and 65535")
    viewer_url = viewer_address(viewer_url)
    home = no_symlinks(Path(user.pw_dir))
    ir_root = no_symlinks(home / ".config/habitatos/ir")
    current = home / ".local/share/habitatos/ir/current"
    # The installer's versioned 'current' link is intentional; all output and
    # private configuration paths still reject symlinks, including parents.
    no_symlinks(current.parent)
    releases = no_symlinks(current.parent / "releases")
    resolved = current.resolve(strict=True)
    if resolved.parent != releases or not resolved.is_dir() or not (current / "venv/bin/python").is_file():
        raise ValueError("install a versioned IR runtime before provisioning the worker")
    runtime_dir = no_symlinks(runtime_dir)
    unit_file = no_symlinks(unit_file)
    if unit_file.name != SERVICE:
        raise ValueError("worker unit filename must be habitat-ir-web.service")
    s = {"profile": Snapshot.read(profile), "gateway_env": Snapshot.read(gateway_env)}
    if s["gateway_env"].mode != 0o600:
        raise ValueError("Gateway environment must remain private mode 0600")
    config = tomllib.loads(s["profile"].data.decode())
    site, gateway = identifier(config.get("site_id")), identifier(config.get("gateway_id"))
    nodes = []
    for cage in cages:
        registered = [c for c in config.get("cages", []) if c.get("id") == cage]
        if len(registered) != 1:
            raise ValueError("cage must be registered exactly once in the gateway profile")
        node = identifier(registered[0].get("node_id"))
        if any(c.get("node_id") == node and c.get("id") != cage for c in config.get("cages", [])):
            raise ValueError("node is registered to more than one cage")
        base = f"habitat/v1/{site}/cages/{cage}/nodes/{node}"
        receipt = Snapshot.read(Path(receipt_root) / (site + "--" + cage + ".json"))
        private_file(receipt, 0)
        owned = json.loads(receipt.data)
        expected = {"schema_version": 1, "site_id": site, "cage_id": cage, "node_id": node,
                    "user": user.pw_name, "topic_base": base}
        if any(owned.get(k) != v for k, v in expected.items()):
            raise ValueError("existing IR provisioning receipt identity changed")
        account = identifier(owned.get("account"))
        node_config = Snapshot.read(ir_root / cage / "ir.json")
        node_env = Snapshot.read(ir_root / cage / "ir.env")
        private_file(node_config, user.pw_uid); private_file(node_env, user.pw_uid)
        mqtt = config.get("mqtt", {})
        expected_config = {"broker_host": mqtt.get("host"), "broker_port": mqtt.get("port"),
                           "ca_file": mqtt.get("tls_ca"), "topic_base": base,
                           "username_env": "HABITAT_IR_MQTT_USER", "password_env": "HABITAT_IR_MQTT_PASSWORD"}
        if (mqtt.get("host") not in ("localhost", "127.0.0.1", "::1") or mqtt.get("port") != 8883
                or json.loads(node_config.data) != expected_config):
            raise ValueError("IR private configuration must match the registered local TLS broker and node")
        env_lines = node_env.data.decode().splitlines()
        if (digest(node_env.data) != owned.get("env_sha256")
                or env_lines.count("HABITAT_IR_MQTT_USER=" + account) != 1):
            raise ValueError("existing IR credentials changed")
        for name, snap in (("receipt", receipt), ("config", node_config), ("env", node_env)):
            s[cage + ":" + name] = snap
        nodes.append({"cage_id": cage, "node_id": node,
                      "config_path": str(node_config.path), "env_path": str(node_env.path)})
    outputs = {"config": runtime_dir / "web.json", "env": runtime_dir / "web.env",
               "receipt": runtime_dir / "provisioned.json", "unit": unit_file,
               "launcher": ir_root / "camera-control.html"}
    for name, path in outputs.items():
        s[name] = Snapshot.read(path, optional=True)
    identity = {"schema_version": 1, "site_id": site, "gateway_id": gateway, "user": user.pw_name}
    reuse = s["receipt"].data is not None
    tokens = tokens_from_env(s["gateway_env"].data)
    owned = None
    if reuse:
        private_file(s["receipt"], 0)
        owned = json.loads(s["receipt"].data)
        if any(owned.get(k) != v for k, v in identity.items()):
            raise ValueError("IR web provisioning receipt identity changed")
        if set(tokens) != {BRIDGE_KEY, CONTROL_KEY} or any(
                digest(tokens[key].encode()) != owned.get("token_sha256", {}).get(key) for key in tokens):
            raise ValueError("managed IR web credentials changed")
        for name in ("config", "env", "unit", "launcher"):
            saved = owned.get("files", {}).get(name)
            if saved is None:
                if s[name].data is not None:
                    raise ValueError("unowned IR web output conflicts with provisioning")
                continue
            expected = {"path": str(s[name].path), "sha256": digest(s[name].data or b""),
                        "uid": s[name].uid, "gid": s[name].gid, "mode": s[name].mode}
            if saved != expected:
                raise ValueError("managed IR web files changed")
        viewer_url = viewer_url or owned.get("viewer_url")
    elif tokens or any(s[name].data is not None for name in ("config", "env", "unit", "launcher")):
        raise ValueError("existing IR web credentials or files have no owned provisioning receipt")
    state_dir = no_symlinks(home / ".local/state/habitat-ir")
    output_config = encode_json({"site_id": site, "gateway_id": gateway,
                                "max_on_seconds": max_on_seconds, "nodes": nodes})
    unit = service_text(user, current, outputs["config"], outputs["env"], state_dir, port)
    state = digest(encode_json({"inputs": {name: {"path": str(v.path), "sha256": digest(v.data) if v.data is not None else None,
                        "uid": v.uid, "gid": v.gid, "mode": v.mode} for name, v in s.items()},
                        "config": digest(output_config), "unit": digest(unit), "viewer_url": viewer_url,
                        "runtime_release": str(resolved)}))
    return {"snapshots": s, "state": state, "reuse": reuse, "identity": identity, "user": user,
            "cages": cages, "config": output_config, "unit": unit, "tokens": tokens,
            "runtime_dir": runtime_dir, "state_dir": state_dir, "ir_root": ir_root,
            "viewer_url": viewer_url, "port": port, "max_on_seconds": max_on_seconds,
            "current": current, "release": resolved}


def summary(prepared, *, applied=False):
    return {**prepared["identity"], "cage_ids": prepared["cages"], "state_sha256": prepared["state"],
            "applied": applied, "already_provisioned": prepared["reuse"], "worker_service": SERVICE,
            "config": str(prepared["snapshots"]["config"].path),
            "control_link_file": str(prepared["snapshots"]["launcher"].path) if prepared["viewer_url"] else None,
            "camera_ir": {"enabled": True, "endpoint": f"http://127.0.0.1:{prepared['port']}",
                          "cage_ids": prepared["cages"], "token_env": BRIDGE_KEY},
            "gateway_config_changed": False, "gateway_restarted": False, "physical_outputs_requested": False}


def systemctl(*args, check=True):
    result = subprocess.run(["systemctl", *args], capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError("IR worker service operation failed: " + args[0])
    return result.returncode == 0


def health(prepared):
    opener = build_opener(ProxyHandler({}))
    expected = {"status": "ok", "site_id": prepared["identity"]["site_id"],
                "gateway_id": prepared["identity"]["gateway_id"], "configured_cages": prepared["cages"]}
    for attempt in range(15):
        try:
            with opener.open(f"http://127.0.0.1:{prepared['port']}/health", timeout=1) as response:
                result = json.loads(response.read(8192))
            if result == expected:
                return
        except (OSError, ValueError):
            pass
        if attempt < 14:
            time.sleep(0.3)
    raise RuntimeError("IR worker health verification failed")


def ensure_runtime_directory(path):
    no_symlinks(path)
    if not path.exists():
        path.mkdir(mode=0o755)
        os.chown(path, 0, 0)
        return [path]
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o755:
        raise ValueError("IR runtime directory must be root-owned mode 0755")
    return []


def apply(prepared, expected_state, *, backup_root):
    if expected_state != prepared["state"]:
        raise ValueError("configuration changed after review; run dry-run again")
    path = no_symlinks(prepared["snapshots"]["gateway_env"].path.parent / ".habitat-ir-web-provision.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another IR web provisioning operation is active") from None
        return apply_locked(prepared, backup_root=backup_root)
    finally:
        os.close(fd)


def apply_locked(p, *, backup_root):
    s, user = p["snapshots"], p["user"]
    if not all(snap.unchanged() for snap in s.values()) or p["current"].resolve(strict=True) != p["release"]:
        raise ValueError("configuration changed after review; run dry-run again")
    tokens = p["tokens"] or {key: secrets.token_urlsafe(32) for key in (BRIDGE_KEY, CONTROL_KEY)}
    gateway_env = s["gateway_env"].data
    if not p["reuse"]:
        gateway_env += b"\n" if gateway_env and not gateway_env.endswith(b"\n") else b""
        gateway_env += "".join(f"{key}={tokens[key]}\n" for key in (BRIDGE_KEY, CONTROL_KEY)).encode()
    payloads = {"config": p["config"], "env": f"{BRIDGE_KEY}={tokens[BRIDGE_KEY]}\n".encode(),
                "unit": p["unit"], "gateway_env": gateway_env}
    if p["viewer_url"]:
        payloads["launcher"] = control_page(p["viewer_url"], tokens[CONTROL_KEY])
    modes = {"unit": 0o644, "gateway_env": s["gateway_env"].mode}
    owners = {name: ((user.pw_uid, user.pw_gid) if name in ("config", "launcher") else
                    ((s[name].uid, s[name].gid) if name == "gateway_env" else (0, 0))) for name in payloads}
    receipt = {**p["identity"], "viewer_url": p["viewer_url"], "runtime_release": str(p["release"]),
               "token_sha256": {key: digest(value.encode()) for key, value in tokens.items()},
               "files": {name: {"path": str(s[name].path), "sha256": digest(data),
                         "mode": modes.get(name, 0o600), "uid": owners[name][0], "gid": owners[name][1]}
                         for name, data in payloads.items() if name != "gateway_env"}}
    payloads["receipt"] = encode_json(receipt); owners["receipt"] = (0, 0)
    changed = [name for name, data in payloads.items() if s[name].data != data]
    old_active = systemctl("is-active", "--quiet", SERVICE, check=False)
    old_enabled = systemctl("is-enabled", "--quiet", SERVICE, check=False)
    if not p["reuse"] and (old_active or old_enabled):
        raise ValueError("an unowned IR worker service is already installed")
    created = []
    written = []
    backup = None
    service_touched = False
    enable_attempted = False
    try:
        created += ensure_runtime_directory(p["runtime_dir"])
        created += private_directory(p["state_dir"], user.pw_uid, user.pw_gid)
        created += private_directory(p["ir_root"], user.pw_uid, user.pw_gid)
        if changed:
            backup = no_symlinks(Path(backup_root) / str(time.time_ns()))
            private_directory(backup, 0, 0)
            for name in changed:
                if s[name].data is not None:
                    atomic_write(Snapshot(backup / name, None), s[name].data, owner=(0, 0), mode=0o600)
            atomic_write(Snapshot(backup / "metadata.json", None), encode_json({name: {
                "path": str(s[name].path), "mode": s[name].mode, "uid": s[name].uid, "gid": s[name].gid,
                "existed": s[name].data is not None} for name in changed}), owner=(0, 0), mode=0o600)
            if not all(snap.unchanged() for snap in s.values()) or p["current"].resolve(strict=True) != p["release"]:
                raise ValueError("configuration changed during preparation")
            for name in changed:
                written.append(name)
                atomic_write(s[name], payloads[name], owner=owners[name], mode=modes.get(name, 0o600))
        if "unit" in changed:
            systemctl("daemon-reload")
        if not old_enabled:
            enable_attempted = True
            systemctl("enable", SERVICE)
        if changed and old_active:
            service_touched = True
            systemctl("restart", SERVICE)
        elif not old_active:
            service_touched = True
            systemctl("start", SERVICE)
        health(p)
    except Exception:
        errors = []
        # Stop before restoring a previous config/credential set. This service
        # owns only IR leases; the Gateway, broker and Air units are untouched.
        if service_touched:
            try:
                systemctl("stop", SERVICE)
            except Exception:
                errors.append("stop")
        if enable_attempted:
            try:
                systemctl("disable", SERVICE)
            except Exception:
                errors.append("disable")
        for name in reversed(written):
            try:
                if s[name].data is None:
                    no_symlinks(s[name].path).unlink(missing_ok=True)
                else:
                    atomic_write(s[name], s[name].data)
            except Exception:
                errors.append(name)
        try:
            if "unit" in written:
                systemctl("daemon-reload")
            if old_active and service_touched:
                systemctl("start", SERVICE)
        except Exception:
            errors.append("service_restore")
        for directory in sorted(created, key=lambda x: len(x.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        if errors:
            raise RuntimeError("IR web provisioning failed; rollback needs review: " + ",".join(errors)) from None
        raise RuntimeError("IR web provisioning failed; original files and worker state restored") from None
    result = summary(p, applied=True)
    result["worker_healthy"] = True
    if backup:
        result["backup"] = str(backup)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--cage", action="append", required=True)
    parser.add_argument("--profile", type=Path, default=Path("/etc/habitat-gateway/gateway.toml"))
    parser.add_argument("--gateway-env", type=Path, default=Path("/etc/habitat-gateway/gateway.env"))
    parser.add_argument("--receipt-root", type=Path, default=Path("/etc/habitat-gateway/ir-provisioning"))
    parser.add_argument("--runtime-dir", type=Path, default=Path("/etc/habitat-ir"))
    parser.add_argument("--unit-file", type=Path, default=Path("/etc/systemd/system") / SERVICE)
    parser.add_argument("--backup-root", type=Path, default=Path("/var/backups/habitatos-ir-web"))
    parser.add_argument("--viewer-url")
    parser.add_argument("--max-on-seconds", type=int, default=900)
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-state")
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != 0:
        parser.error("--apply requires root")
    try:
        p = plan(args.profile, args.cage, pwd.getpwnam(args.user), gateway_env=args.gateway_env,
                 receipt_root=args.receipt_root, runtime_dir=args.runtime_dir, unit_file=args.unit_file,
                 viewer_url=args.viewer_url, max_on_seconds=args.max_on_seconds, port=args.port)
        result = apply(p, args.expect_state or p["state"], backup_root=args.backup_root) if args.apply else summary(p)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, "IR web provisioning stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
