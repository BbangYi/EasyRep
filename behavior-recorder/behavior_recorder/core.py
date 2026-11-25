"""Immutable data entries; one atomically replaced manifest is the commit point."""
from contextlib import contextmanager
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:  # The separate vision worker also runs on Windows.
    fcntl = None
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from uuid import UUID, uuid4


class RecorderError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise RecorderError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def read_json(path, limit=4 * 1024**2):
    require(path.stat().st_size <= limit, "JSON size limit exceeded")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, parse_constant=lambda x: (_ for _ in ()).throw(RecorderError(f"invalid number: {x}")))


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value), "invalid identifier")
    return value


def number(value, minimum=0, maximum=1e12):
    require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum, "invalid numeric value")
    return value


def timestamp(value):
    if value is None:
        return None
    require(isinstance(value, str), "timestamp must be ISO 8601 or null")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecorderError("invalid timestamp") from exc
    require(result.utcoffset() is not None, "timestamp requires timezone")
    return result


def clock(value):
    require(isinstance(value, dict), "clock object required")
    require(set(value) == {"source", "accuracy_ms"}, "clock requires source and accuracy_ms")
    require(value["source"] in {"unknown", "device", "host_ntp", "host_unsynced", "operator"}, "invalid clock source")
    if value["accuracy_ms"] is not None:
        number(value["accuracy_ms"])
        require(value["source"] != "unknown", "unknown clock cannot have known accuracy")


def relative(root, value):
    root = root.resolve()
    require(isinstance(value, str) and value and "\\" not in value, "relative POSIX path required")
    parts = PurePosixPath(value)
    require(not parts.is_absolute() and ".." not in parts.parts and parts.as_posix() == value, "unsafe relative path")
    path = root / value
    require(path.resolve().is_relative_to(root.resolve()), "path escapes data root")
    current = root
    for part in parts.parts:
        current = current / part
        require(not current.is_symlink(), "symlinks are not supported inside data root")
    return path


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def sync_dir(path):
    if os.name == "nt":
        return  # Windows does not provide POSIX directory fsync through os.open.
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.partial")
    with temporary.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


@contextmanager
def lock(path):
    require(fcntl is not None, "recording writes require POSIX flock; use Linux/WSL on Windows")
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecorderError("another writer is active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate_config(config):
    require(isinstance(config, dict), "config must be an object")
    require(set(config) == {"schema_version", "dataset_kind", "animals", "cameras", "storage", "input"}, "unexpected/missing config fields")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1, "unsupported schema")
    require(config["dataset_kind"] in {"test", "real"}, "dataset_kind must be test or real")
    require(isinstance(config["animals"], list), "animals must be a list")
    animals = []
    for animal in config["animals"]:
        require(set(animal) == {"animal_id", "species"}, "invalid animal fields")
        animals.append(identifier(animal["animal_id"]))
        require(animal["species"] in {"unknown", "crested_gecko", "leopard_gecko"}, "invalid species")
    require(len(set(animals)) == len(animals), "duplicate animal ID")
    require(isinstance(config["cameras"], list) and config["cameras"], "at least one camera slot required")
    ids = []
    for camera in config["cameras"]:
        require(set(camera) == {"camera_id", "kind", "enclosure_id", "placement_revision", "calibration_revision", "model", "connection", "expected_fps"}, "invalid camera fields")
        ids.append(identifier(camera["camera_id"]))
        identifier(camera["enclosure_id"])
        require(camera["kind"] in {"rgb", "thermal_color", "thermal_numeric"}, "invalid camera kind")
        for key in ("placement_revision", "calibration_revision"):
            if camera[key] is not None:
                identifier(camera[key])
        require(camera["model"] is None or isinstance(camera["model"], str), "invalid model")
        require(camera["connection"] in {"unconfigured", "finalized_file"}, "hardware driver is not configured; use finalized_file")
        if camera["expected_fps"] is not None:
            number(camera["expected_fps"], 0.01, 240)
    require(len(ids) == len(set(ids)), "duplicate camera ID")
    storage = config["storage"]
    require(set(storage) == {"max_session_bytes", "min_free_bytes", "max_clip_bytes", "max_clip_seconds", "max_frames", "probe_timeout_seconds"}, "invalid storage fields")
    for key in storage:
        number(storage[key], 0 if key == "min_free_bytes" else 1)
    for key in ("max_session_bytes", "min_free_bytes", "max_clip_bytes", "max_frames"):
        require(type(storage[key]) is int, f"{key} must be an integer")
    require(storage["max_clip_seconds"] <= 600 and storage["max_frames"] <= 36000, "MVP accepts clips up to 600 seconds / 36000 frames")
    require(storage["max_clip_bytes"] <= storage["max_session_bytes"], "clip limit exceeds session limit")
    incoming = config["input"]
    require(set(incoming) == {"adapter", "inbox", "poll_seconds", "idle_warning_seconds"}, "invalid input fields")
    require(incoming["adapter"] == "finalized_file", "only finalized_file adapter implemented")
    require(isinstance(incoming["inbox"], str) and incoming["inbox"], "inbox path required")
    number(incoming["poll_seconds"], 0.1, 60)
    number(incoming["idle_warning_seconds"], 1, 86400)
    return config


def create_session(root, config):
    config = validate_config(config)
    require(not root.exists(), "session destination already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    for name in ("entries", ".partial", "quarantine"):
        (root / name).mkdir()
    # Device/inbox locations belong to local config, never the portable manifest.
    portable = {k: v for k, v in config.items() if k != "input"}
    manifest = {"schema_version": 1, "session_id": str(uuid4()), "started_at": now(),
                "ended_at": None, "state": "active", "config": portable, "entries": [],
                "hardware_synchronized": False, "host_clock": {"source": "host_unsynced", "accuracy_ms": None}}
    atomic_json(root / "manifest.json", manifest)
    with Session(root) as session:
        session.event("session_started")
    return manifest["session_id"]


class Session:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest = read_json(self.root / "manifest.json", 32 * 1024**2)
        self.validate_manifest()

    def validate_manifest(self):
        manifest = self.manifest
        require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "unsupported manifest schema")
        UUID(manifest["session_id"])
        require(manifest["state"] in {"active", "stopped", "interrupted", "failed"}, "invalid session state")
        validate_config({**manifest["config"], "input": {"adapter": "finalized_file", "inbox": "unused", "poll_seconds": 1, "idle_warning_seconds": 1}})
        require(isinstance(manifest["entries"], list), "manifest entries must be a list")
        for entry in manifest["entries"]:
            require(entry["kind"] in {"clip", "sensors", "thermal", "labels", "event"}, "invalid entry kind")
            require(re.fullmatch(r"entries/[a-f0-9]{32}", entry["path"]), "invalid entry path")
            names = []
            for item in entry["files"]:
                relative(self.root / entry["path"], item["path"])
                names.append(item["path"])
                number(item["bytes"])
                require(type(item["bytes"]) is int and re.fullmatch(r"[a-f0-9]{64}", item["sha256"]), "invalid file checksum/size")
            require(len(names) == len(set(names)) and "record.json" in names, "invalid file inventory")

    def __enter__(self):
        self._lock = lock(self.root / ".writer.lock")
        self._lock.__enter__()
        try:
            self.manifest = read_json(self.root / "manifest.json", 32 * 1024**2)
            self.validate_manifest()
        except BaseException:
            self._lock.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        self._lock.__exit__(*args)

    def items(self, kind):
        for entry in self.manifest["entries"]:
            if entry["kind"] == kind:
                yield read_json(relative(self.root, entry["path"]) / "record.json")

    def unresolved(self):
        known = {entry["path"] for entry in self.manifest["entries"]}
        paths = list((self.root / ".partial").iterdir())
        paths += [p for p in (self.root / "entries").iterdir() if p.relative_to(self.root).as_posix() not in known]
        paths += list(self.root.glob(".manifest.json-*.partial"))
        return paths

    def ready(self, active=False):
        require(not self.unresolved(), "incomplete transaction found; run recover")
        if active:
            require(self.manifest["state"] == "active", "session is not active")

    def used(self):
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink())

    def space(self, incoming):
        policy = self.manifest["config"]["storage"]
        require(self.used() + incoming <= policy["max_session_bytes"], "storage_limit: session byte limit reached")
        require(shutil.disk_usage(self.root).free >= incoming + policy["min_free_bytes"], "storage_limit: insufficient free disk space")

    def begin(self):
        folder = self.root / ".partial" / uuid4().hex
        folder.mkdir()
        sync_dir(folder.parent)
        return folder

    def commit(self, folder, kind, record, updates=None, control=False):
        with (folder / "record.json").open("xb") as stream:
            stream.write(encode(record))
            stream.flush()
            os.fsync(stream.fileno())
        files = []
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(folder).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
        entry = {"kind": kind, "path": f"entries/{folder.name}", "files": files}
        updated = {**self.manifest, **(updates or {}), "entries": [*self.manifest["entries"], entry]}
        if not control:
            self.space(len(encode(updated)))
        sync_dir(folder)
        os.replace(folder, self.root / entry["path"])
        sync_dir(self.root / "entries")
        sync_dir(self.root / ".partial")
        atomic_json(self.root / "manifest.json", updated)
        self.manifest = updated

    def add(self, kind, record, updates=None, control=False):
        if not control:
            self.space(len(encode(record)) + len(encode(self.manifest)) + 2048)
        folder = self.begin()
        self.commit(folder, kind, record, updates, control)

    def event(self, code, details=None, updates=None, control=False):
        self.add("event", {"event_id": str(uuid4()), "code": code, "received_at": now(),
                           "observed_at": None, "details": details or {}}, updates, control)

    def verify(self):
        failures = []
        seen = set()
        for entry in self.manifest["entries"]:
            if entry["path"] in seen:
                failures.append(f"duplicate entry: {entry['path']}")
            seen.add(entry["path"])
            base = relative(self.root, entry["path"])
            for item in entry["files"]:
                path = relative(base, item["path"])
                if not path.is_file() or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
                    failures.append(f"checksum/missing: {entry['path']}/{item['path']}")
            listed = {item["path"] for item in entry["files"]}
            actual = {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}
            if listed != actual or "record.json" not in listed:
                failures.append(f"file inventory mismatch: {entry['path']}")
            if (base / "record.json").is_file():
                record = read_json(base / "record.json")
                references = [record[key] for key in ("media_path", "frames_path", "events_path", "rows_path") if key in record]
                allowed = {f"{entry['path']}/{name}" for name in listed}
                if not set(references) <= allowed:
                    failures.append(f"record references unlisted files: {entry['path']}")
        failures.extend(f"uncommitted: {p.relative_to(self.root)}" for p in self.unresolved())
        return failures

    def recover(self):
        moved = []
        for path in self.unresolved():
            name = f"{uuid4().hex}-{path.name}"
            os.replace(path, self.root / "quarantine" / name)
            moved.append(name)
        sync_dir(self.root / "quarantine")
        self.event("recovery", {"quarantined": moved},
                   {"state": "interrupted", "ended_at": now()} if self.manifest["state"] == "active" else None, control=True)
        return moved

    def clip(self, clip_id):
        for item in self.items("clip"):
            if item["clip_id"] == clip_id:
                return item
        raise RecorderError("unknown clip ID")
