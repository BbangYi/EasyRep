"""Portable ZIP_STORED snapshots with checksum and extraction limits."""
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4
import zipfile

from .core import Session, digest, encode, read_json, relative, require, sync_dir


def export_bundle(session, destination):
    session.ready()
    require(session.manifest["state"] != "active", "stop the session before export")
    require(not session.verify(), "integrity check failed; run verify")
    destination = Path(destination).resolve()
    require(not destination.exists() and not destination.is_relative_to(session.root), "export requires a new path outside session")
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = ["manifest.json"]
    for entry in session.manifest["entries"]:
        paths.extend(f"{entry['path']}/{f['path']}" for f in entry["files"])
    total = sum(relative(session.root, p).stat().st_size for p in paths)
    require(shutil.disk_usage(destination.parent).free >= total + len(paths) * 512 + 64 * 1024**2, "insufficient space for bundle")
    temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.partial")
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("bundle.json", encode({"schema_version": 1, "manifest_sha256": digest(session.root / "manifest.json")}))
        for name in paths:
            archive.write(relative(session.root, name), name)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    sync_dir(destination.parent)
    return {"bundle": str(destination), "bytes": destination.stat().st_size, "sha256": digest(destination)}


def import_bundle(source, destination, max_bytes=10 * 1024**3):
    destination = Path(destination).resolve()
    require(not destination.exists(), "import destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}-{uuid4().hex}.import.partial")
    temporary.mkdir(mode=0o700)
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        require(len(names) == len(set(names)) and len(names) <= 100000, "duplicate or excessive ZIP entries")
        require("bundle.json" in names and "manifest.json" in names, "bundle manifest missing")
        total = sum(i.file_size for i in infos)
        require(total <= max_bytes, "bundle exceeds extraction byte limit")
        require(shutil.disk_usage(destination.parent).free >= total + 64 * 1024**2, "insufficient extraction space")
        for info in infos:
            path = relative(temporary, info.filename)
            require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), "ZIP directories/symlinks are not supported")
            require(info.compress_type == zipfile.ZIP_STORED, "only uncompressed recorder bundles supported")
            path.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as incoming, path.open("xb") as outgoing:
                for chunk in iter(lambda: incoming.read(1024**2), b""):
                    written += len(chunk)
                    require(written <= info.file_size, "ZIP entry size mismatch")
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            require(written == info.file_size, "truncated ZIP entry")
    bundle = read_json(temporary / "bundle.json")
    require(bundle.get("schema_version") == 1 and digest(temporary / "manifest.json") == bundle.get("manifest_sha256"), "bundle manifest checksum mismatch")
    for name in ("entries", ".partial", "quarantine"):
        (temporary / name).mkdir(exist_ok=True)
    session = Session(temporary)
    expected = {"bundle.json", "manifest.json"}
    for entry in session.manifest["entries"]:
        expected.update(f"{entry['path']}/{f['path']}" for f in entry["files"])
    require(set(names) == expected, "bundle contains missing/unlisted files")
    require(not session.verify(), "bundle data checksum mismatch")
    sync_dir(temporary)
    os.replace(temporary, destination)
    sync_dir(destination.parent)
    return {"session": str(destination), "session_id": session.manifest["session_id"]}
