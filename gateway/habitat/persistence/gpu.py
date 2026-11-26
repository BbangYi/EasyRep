"""Durable capture/job state; one process owns each runtime directory."""

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import sqlite3
import threading


def now():
    return datetime.now(timezone.utc).isoformat()


def sync_directory(path):
    """Persist published directory entries before acknowledging them in SQLite."""
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.path = self.root / "compute.sqlite3"
        self.lock = threading.RLock()
        self._owner = None

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        owner = (self.root / "service.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                owner.seek(0)
                if not owner.read(1):
                    owner.write(b"0")
                    owner.flush()
                owner.seek(0)
                msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            owner.close()
            raise RuntimeError("storage_already_in_use") from None
        self._owner = owner
        for temporary in self.staging_path().glob("upload-*.part"):
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
        with self.db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("unsupported_storage_version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files(
                    capture_id TEXT NOT NULL REFERENCES captures(id), file_id TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(capture_id,file_id));
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                    payload TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            for row in db.execute("SELECT id,payload FROM jobs WHERE status='running'").fetchall():
                job = json.loads(row[1])
                job.update(status="interrupted", stage="interrupted", updated_at=max(now(), job["updated_at"]), artifacts=[],
                           error={"code": "process_interrupted", "message": "Worker stopped before completion"})
                self._save_job(db, job)
            for row in db.execute("SELECT id,payload FROM captures").fetchall():
                for item in json.loads(row[1])["files"]:
                    if not self.file_path(row[0], item).is_file():
                        db.execute("UPDATE files SET verified=0 WHERE capture_id=? AND file_id=?",
                                   (row[0], item["file_id"]))

    def close(self):
        if self._owner:
            self._owner.close()
            self._owner = None

    @contextmanager
    def db(self):
        # ponytail: short SQLite transactions serialized; revisit for multiple GPU workers.
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=10)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def file_path(self, capture_id, item):
        return self.root / "captures" / str(capture_id) / (item["file_id"] + Path(item["name"]).suffix.lower())

    def staging_path(self):
        staging = self.root / "staging"
        if staging.is_symlink() or staging.resolve().parent != self.root:
            raise OSError(errno.EACCES, "Invalid upload staging directory")
        staging.mkdir(exist_ok=True)
        return staging

    def capture(self, capture_id):
        with self.db() as db:
            row = db.execute("SELECT payload FROM captures WHERE id=?", (str(capture_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def add_capture(self, manifest):
        with self.db() as db:
            db.execute("INSERT INTO captures VALUES(?,?)", (manifest["capture_id"], json.dumps(manifest)))
            db.executemany("INSERT INTO files(capture_id,file_id) VALUES(?,?)",
                           [(manifest["capture_id"], item["file_id"]) for item in manifest["files"]])

    def capture_status(self, manifest):
        with self.db() as db:
            verified = {row[0] for row in db.execute(
                "SELECT file_id FROM files WHERE capture_id=? AND verified=1", (manifest["capture_id"],))}
        received, missing = [], []
        for item in manifest["files"]:
            present = item["file_id"] in verified and self.file_path(manifest["capture_id"], item).is_file()
            (received if present else missing).append(item["file_id"])
        return {**{key: manifest[key] for key in ("schema_version", "site_id", "gateway_id", "cage_id", "capture_id")},
                "status": "uploading" if missing else "ready", "verified_file_ids": received, "missing_file_ids": missing}

    def verify_file(self, capture_id, file_id):
        with self.db() as db:
            db.execute("UPDATE files SET verified=1 WHERE capture_id=? AND file_id=?", (capture_id, file_id))

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def job_request(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT request FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def add_job(self, request, capture):
        timestamp = now()
        job = {**request, "status": "queued", "stage": "queued", "created_at": timestamp,
               "updated_at": timestamp, "geometry_revision": capture["geometry_revision"],
               "placement_revision": capture["placement_revision"], "artifacts": [], "error": None}
        with self.db() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?)",
                       (job["job_id"], json.dumps(request), "queued", json.dumps(job)))
        return job

    @staticmethod
    def _save_job(db, job):
        db.execute("UPDATE jobs SET status=?,payload=? WHERE id=?",
                   (job["status"], json.dumps(job), job["job_id"]))

    def update_job(self, job_id, **fields):
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            job = json.loads(row[0])
            # Generated timestamps are UTC ISO strings. Keep ordering across host/NTP clock rollback.
            job.update(fields, updated_at=max(now(), job["updated_at"]))
            self._save_job(db, job)
        return job

    def next_job(self):
        with self.db() as db:
            row = db.execute("SELECT payload FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return None
            job = json.loads(row[0])
            job.update(status="running", stage="colmap", updated_at=max(now(), job["updated_at"]))
            self._save_job(db, job)
        return job
