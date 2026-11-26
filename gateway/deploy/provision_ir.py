"""Provision one registered cage's local IR account without changing sensor access.

Dry-run is the default. Apply requires root; an optional dry-run hash pins review.
Credentials stay in a private env file; no password is passed as a process argument.
The broker is reloaded, never restarted. This does not upload or energize hardware.
"""
from dataclasses import dataclass
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import tempfile
import time
import tomllib


IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid configured identifier")
    return value


def no_symlinks(path):
    path = Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("symlinks are not allowed in provisioning paths")
    return path


@dataclass(frozen=True)
class Snapshot:
    path: Path
    data: bytes | None
    mode: int = 0o600
    uid: int = 0
    gid: int = 0

    @classmethod
    def read(cls, path, *, optional=False):
        path = no_symlinks(path)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            if optional:
                return cls(path, None)
            raise
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("provisioning input must be a regular file")
            return cls(path, stream.read(), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)

    def unchanged(self):
        return self == self.read(self.path, optional=True)


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def acl_rules(base):
    return ([f"topic write {base}/ir/hello", f"topic write {base}/ir/ack",
             f"topic read {base}/ir/command/+"],
            [f"topic read {base}/ir/hello", f"topic read {base}/ir/ack",
             f"topic write {base}/ir/command/+"])


def acl_sections(text):
    lines = text.splitlines(keepends=True)
    sections = []
    for index, line in enumerate(lines):
        tokens = line.strip().split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if tokens[0] == "pattern":
            raise ValueError("global pattern ACL rules require review before adding an IR account")
        if tokens[0] == "user":
            if len(tokens) != 2:
                raise ValueError("invalid ACL user declaration")
            sections.append((tokens[1], index))
    return lines, [(name, start, sections[i+1][1] if i+1 < len(sections) else len(lines))
                   for i, (name, start) in enumerate(sections)]


def extend_acl(text, node, account, base, *, reuse=False):
    """Insert into the existing node block, preserving every existing line."""
    node_rules, control_rules = acl_rules(base)
    lines, sections = acl_sections(text)
    node_blocks = [block for block in sections if block[0] == node]
    controls = [block for block in sections if block[0] == account]
    if len(node_blocks) != 1 or node == account:
        raise ValueError("expected exactly one existing node ACL block and a separate controller")
    if controls and not reuse:
        raise ValueError("controller account already has ACL rules without an owned receipt")
    if reuse:
        if len(controls) != 1:
            raise ValueError("provisioned controller ACL block changed")
        _, start, end = controls[0]
        existing = [" ".join(line.split()) for line in lines[start+1:end]
                    if line.strip() and not line.lstrip().startswith("#")]
        if sorted(existing) != sorted(control_rules):
            raise ValueError("provisioned controller permissions changed")
    _, start, end = node_blocks[0]
    existing = {" ".join(line.split()) for line in lines[start+1:end]}
    added = [rule for rule in node_rules if rule not in existing]
    prefix = "".join(lines[:end])
    if added and prefix and not prefix.endswith("\n"):
        prefix += "\n"
    result = prefix + "".join(rule + "\n" for rule in added) + "".join(lines[end:])
    if not reuse:
        if result and not result.endswith("\n"):
            result += "\n"
        result += "\nuser " + account + "\n" + "".join(rule + "\n" for rule in control_rules)
    return result


def password_rows(data):
    result = {}
    for line in data.decode().splitlines():
        if not line:
            continue
        name, separator, encoded = line.partition(":")
        if not separator or not name or not encoded or name in result:
            raise ValueError("invalid or duplicate broker password entry")
        result[name] = line
    return result


def password_hash(account, password):
    """mosquitto_passwd receives plaintext only via a private temporary file."""
    with tempfile.TemporaryDirectory(prefix="habitatos-ir-password-") as directory:
        path = Path(directory) / "passwd"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(account + ":" + password + "\n")
        result = subprocess.run(["mosquitto_passwd", "-U", str(path)],
                                capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError("MQTT password hashing failed")
        rows = password_rows(path.read_bytes())
        if set(rows) != {account} or not rows[account].split(":", 1)[1].startswith("$"):
            raise ValueError("MQTT password hasher returned an invalid entry")
        return rows[account]


def atomic_write(snapshot, data, *, owner=None, mode=None):
    """Replace one file while preserving existing broker owner and permissions."""
    no_symlinks(snapshot.path)
    fd, name = tempfile.mkstemp(prefix="." + snapshot.path.name + "-", dir=snapshot.path.parent)
    try:
        os.fchmod(fd, snapshot.mode if mode is None else mode)
        os.fchown(fd, *(owner or (snapshot.uid, snapshot.gid)))
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, snapshot.path)
        directory = os.open(snapshot.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd is not None:
            os.close(fd)
        Path(name).unlink(missing_ok=True)


def private_directory(path, uid, gid):
    path = no_symlinks(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, gid)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("existing private output directory has unexpected ownership or permissions")
    return missing


def reload_broker():
    result = subprocess.run(["systemctl", "reload", "mosquitto"], capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError("Mosquitto reload failed")
    result = subprocess.run(["systemctl", "is-active", "--quiet", "mosquitto"], capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Mosquitto is not active after reload")


def plan(profile, cage_id, account, user, *, acl_file, password_file, broker_config, receipt_root):
    identifier(cage_id); identifier(account)
    snapshots = {name: Snapshot.read(path) for name, path in {
        "profile": profile, "acl": acl_file, "passwords": password_file,
        "broker_config": broker_config}.items()}
    config = tomllib.loads(snapshots["profile"].data.decode())
    site = identifier(config.get("site_id"))
    cages = [c for c in config.get("cages", []) if c.get("id") == cage_id]
    if len(cages) != 1:
        raise ValueError("cage must be registered exactly once in the gateway profile")
    node = identifier(cages[0].get("node_id"))
    mqtt = config.get("mqtt", {})
    if mqtt.get("port") != 8883 or mqtt.get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("IR provisioning requires the configured local TLS broker on port 8883")
    ca = Snapshot.read(mqtt.get("tls_ca", ""))
    snapshots["ca"] = ca
    broker = {}
    for row in snapshots["broker_config"].data.decode().splitlines():
        fields = row.strip().split(maxsplit=1)
        if len(fields) == 2 and fields[0] in ("acl_file", "password_file"):
            if fields[0] in broker:
                raise ValueError("duplicate broker file directive")
            broker[fields[0]] = fields[1]
    if broker != {"acl_file": str(snapshots["acl"].path), "password_file": str(snapshots["passwords"].path)}:
        raise ValueError("broker configuration does not select the reviewed ACL and password files")
    base = f"habitat/v1/{site}/cages/{cage_id}/nodes/{node}"
    directory = no_symlinks(Path(user.pw_dir) / ".config/habitatos/ir" / cage_id)
    snapshots["config"] = Snapshot.read(directory / "ir.json", optional=True)
    snapshots["env"] = Snapshot.read(directory / "ir.env", optional=True)
    snapshots["receipt"] = Snapshot.read(Path(receipt_root) / (site + "--" + cage_id + ".json"), optional=True)
    output_config = encode_json({"broker_host": mqtt["host"], "broker_port": 8883, "ca_file": str(ca.path),
        "topic_base": base, "username_env": "HABITAT_IR_MQTT_USER", "password_env": "HABITAT_IR_MQTT_PASSWORD"})
    expected_identity = {"schema_version": 1, "site_id": site, "cage_id": cage_id, "node_id": node,
                         "account": account, "user": user.pw_name, "topic_base": base}
    rows = password_rows(snapshots["passwords"].data)
    reuse = snapshots["receipt"].data is not None
    if reuse:
        receipt_snapshot = snapshots["receipt"]
        if receipt_snapshot.uid != 0 or receipt_snapshot.mode & 0o077:
            raise ValueError("provisioning receipt must be root-owned and private")
        receipt = json.loads(receipt_snapshot.data)
        if any(receipt.get(key) != value for key, value in expected_identity.items()):
            raise ValueError("provisioning receipt identity changed")
        if snapshots["config"].data != output_config or snapshots["env"].data is None:
            raise ValueError("private IR configuration changed or credentials are missing")
        if hashlib.sha256(snapshots["env"].data).hexdigest() != receipt.get("env_sha256"):
            raise ValueError("private IR credentials changed")
        if account not in rows or hashlib.sha256(rows[account].encode()).hexdigest() != receipt.get("password_entry_sha256"):
            raise ValueError("provisioned MQTT account changed")
        for name in ("config", "env"):
            if snapshots[name].uid != user.pw_uid or snapshots[name].mode != 0o600:
                raise ValueError("private IR files have unexpected ownership or permissions")
    elif account in rows or snapshots["config"].data is not None or snapshots["env"].data is not None:
        raise ValueError("existing account or private IR files have no owned provisioning receipt")
    new_acl = extend_acl(snapshots["acl"].data.decode(), node, account, base, reuse=reuse).encode()
    if reuse and new_acl != snapshots["acl"].data:
        raise ValueError("provisioned node permissions changed")
    state = hashlib.sha256(encode_json({name: {
        "path": str(s.path), "sha256": hashlib.sha256(s.data).hexdigest() if s.data is not None else None,
        "mode": s.mode, "uid": s.uid, "gid": s.gid} for name, s in snapshots.items()})).hexdigest()
    return {"snapshots": snapshots, "state": state, "reuse": reuse, "acl": new_acl,
            "config": output_config, "identity": expected_identity, "directory": directory,
            "user": user, "account": account}


def summary(prepared, *, applied=False):
    return {**prepared["identity"], "state_sha256": prepared["state"], "applied": applied,
            "already_provisioned": prepared["reuse"], "config": str(prepared["snapshots"]["config"].path),
            "env_file": str(prepared["snapshots"]["env"].path),
            "node_rules": acl_rules(prepared["identity"]["topic_base"])[0],
            "controller_rules": acl_rules(prepared["identity"]["topic_base"])[1],
            "firmware_uploaded": False, "physical_outputs_requested": False}


def apply(prepared, expected_state, *, backup_root):
    """Serialize provisioners, then recheck every input immediately before writes."""
    if expected_state != prepared["state"]:
        raise ValueError("configuration changed after review; run dry-run again")
    lock_path = no_symlinks(prepared["snapshots"]["acl"].path.parent / ".habitat-ir-provision.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another IR provisioning operation is active") from None
        return apply_locked(prepared, expected_state, backup_root=backup_root)
    finally:
        os.close(fd)


def apply_locked(prepared, expected_state, *, backup_root):
    if expected_state != prepared["state"] or not all(s.unchanged() for s in prepared["snapshots"].values()):
        raise ValueError("configuration changed after review; run dry-run again")
    if prepared["reuse"]:
        return summary(prepared, applied=True)
    s = prepared["snapshots"]
    user = prepared["user"]
    password = secrets.token_urlsafe(32)
    entry = password_hash(prepared["account"], password)
    env = (f"HABITAT_IR_MQTT_USER={prepared['account']}\nHABITAT_IR_MQTT_PASSWORD={password}\n").encode()
    passwords = s["passwords"].data
    if passwords and not passwords.endswith(b"\n"):
        passwords += b"\n"
    passwords += (entry + "\n").encode()
    receipt = {**prepared["identity"], "env_sha256": hashlib.sha256(env).hexdigest(),
               "password_entry_sha256": hashlib.sha256(entry.encode()).hexdigest(),
               "reviewed_state": prepared["state"]}
    created_directories = private_directory(prepared["directory"], user.pw_uid, user.pw_gid)
    created_directories += private_directory(s["receipt"].path.parent, 0, 0)
    backup = no_symlinks(Path(backup_root) / (str(time.time_ns()) + "-" + prepared["identity"]["cage_id"]))
    private_directory(backup, 0, 0)
    for name in ("acl", "passwords"):
        atomic_write(Snapshot(backup / name, None), s[name].data, owner=(0, 0), mode=0o600)
    atomic_write(Snapshot(backup / "metadata.json", None), encode_json({name: {
        "path": str(s[name].path), "mode": s[name].mode, "uid": s[name].uid, "gid": s[name].gid,
        "sha256": hashlib.sha256(s[name].data).hexdigest()} for name in ("acl", "passwords")}), owner=(0, 0))
    if not all(item.unchanged() for item in s.values()):
        raise ValueError("configuration changed during preparation; run dry-run again")
    changed = []
    try:
        for name, data in (("config", prepared["config"]), ("env", env), ("passwords", passwords), ("acl", prepared["acl"])):
            owner = (user.pw_uid, user.pw_gid) if name in ("config", "env") else None
            changed.append(name)
            atomic_write(s[name], data, owner=owner)
        reload_broker()
        changed.append("receipt")
        atomic_write(s["receipt"], encode_json(receipt), owner=(0, 0), mode=0o600)
    except Exception:
        rollback_errors = []
        for name in reversed(changed):
            try:
                if s[name].data is None:
                    no_symlinks(s[name].path).unlink(missing_ok=True)
                else:
                    atomic_write(s[name], s[name].data)
            except Exception:
                rollback_errors.append(name)
        try:
            reload_broker()
        except Exception:
            rollback_errors.append("broker_reload")
        for directory in sorted(created_directories, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass  # Retain any directory populated by another actor.
        if rollback_errors:
            raise RuntimeError("IR provisioning failed; rollback needs review: " + ",".join(rollback_errors)) from None
        raise RuntimeError("IR provisioning failed; original broker files restored") from None
    result = summary(prepared, applied=True)
    result["backup"] = str(backup)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path("/etc/habitat-gateway/gateway.toml"))
    parser.add_argument("--cage", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--acl-file", type=Path, default=Path("/etc/mosquitto/habitat.acl"))
    parser.add_argument("--password-file", type=Path, default=Path("/etc/mosquitto/habitat.passwd"))
    parser.add_argument("--broker-config", type=Path, default=Path("/etc/mosquitto/conf.d/habitat.conf"))
    parser.add_argument("--receipt-root", type=Path, default=Path("/etc/habitat-gateway/ir-provisioning"))
    parser.add_argument("--backup-root", type=Path, default=Path("/var/backups/habitatos-ir"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-state", help="Optional state_sha256 from a prior dry-run; fail if it changed")
    args = parser.parse_args(argv)
    if args.apply and os.geteuid() != 0:
        parser.error("--apply requires root")
    try:
        prepared = plan(args.profile, args.cage, args.account, pwd.getpwnam(args.user),
            acl_file=args.acl_file, password_file=args.password_file,
            broker_config=args.broker_config, receipt_root=args.receipt_root)
        result = apply(prepared, args.expect_state or prepared["state"], backup_root=args.backup_root) if args.apply else summary(prepared)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, "IR provisioning stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
