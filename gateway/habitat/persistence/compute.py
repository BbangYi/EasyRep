import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import UUID, uuid4

from habitat.common.models import aware_timestamp, utcnow
from habitat.compute.contracts import CaptureFile, CaptureManifest, JobRequest, MAX_FILE_BYTES
from habitat.compute.errors import ComputeFailure
from habitat.compute.files import CHUNK_BYTES, file_digest, fsync_directory, verify_image


class ComputeRepository:
    """One network worker; concurrent enqueue/read CLIs use SQLite. No control DB access."""
    def __init__(self, root, site_id, gateway_id, *, max_storage_bytes, now=utcnow, worker=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.now, self.site_id, self.gateway_id = now, site_id, gateway_id
        self.max_storage_bytes = max_storage_bytes
        self.lock = (self.root / "worker.lock").open("a") if worker else None
        if self.lock:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock.close()
                raise ComputeFailure("compute_worker_busy") from None
        try:
            self.db = sqlite3.connect(self.root / "compute.sqlite3")
            self.db.row_factory = sqlite3.Row
            if self.db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ComputeFailure("unsupported_compute_storage_schema")
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY, site_id TEXT, gateway_id TEXT);
                CREATE TABLE IF NOT EXISTS tasks (
                    job_id TEXT PRIMARY KEY, capture_id TEXT NOT NULL UNIQUE,
                    manifest TEXT NOT NULL, request TEXT NOT NULL,
                    state TEXT NOT NULL, endpoint TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT, error TEXT, remote TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                previous = self.db.execute("SELECT site_id, gateway_id FROM identity").fetchone()
                if previous and tuple(previous) != (site_id, gateway_id):
                    raise ComputeFailure("compute_store_identity_mismatch")
                self.db.execute("INSERT OR IGNORE INTO identity VALUES (1, ?, ?)", (site_id, gateway_id))
        except BaseException:
            if hasattr(self, "db"):
                self.db.close()
            if self.lock:
                self.lock.close()
            raise

    def close(self):
        self.db.close()
        if self.lock:
            self.lock.close()

    def used_bytes(self):
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink())

    def require_space(self, incoming):
        if self.used_bytes() + incoming > self.max_storage_bytes:
            raise ComputeFailure("compute_storage_limit")
        if shutil.disk_usage(self.root).free < incoming + 64 * 1024**2:
            raise ComputeFailure("insufficient_disk_space")

    def enqueue(self, folder, cage, captured_at):
        captured_at = aware_timestamp(captured_at)
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise ComputeFailure("input_folder_missing")
        candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if not 3 <= len(candidates) <= 500:
            raise ComputeFailure("capture_requires_3_to_500_images")
        if any(p.is_symlink() or not p.is_file() for p in candidates):
            raise ComputeFailure("input_must_be_regular_files")
        sizes = [p.stat().st_size for p in candidates]
        if any(not 0 < size <= MAX_FILE_BYTES for size in sizes) or sum(sizes) > 2 * 1024**3:
            raise ComputeFailure("capture_size_limit")
        self.require_space(sum(sizes))
        capture_id, job_id = uuid4(), uuid4()
        captures = self.root / "captures"
        captures.mkdir(exist_ok=True)
        temporary = captures / f".staging-{capture_id}"
        target = captures / str(capture_id)
        temporary.mkdir(mode=0o700)
        committed = False
        try:
            files = []
            for source in candidates:
                file_id = uuid4()
                destination = temporary / str(file_id)
                with source.open("rb") as reader, destination.open("xb") as writer:
                    size = 0
                    for chunk in iter(lambda: reader.read(CHUNK_BYTES), b""):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise ComputeFailure("input_changed_during_copy")
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                verify_image(destination, source.suffix)
                size, digest = file_digest(destination)
                files.append(CaptureFile(file_id=file_id, name=source.name, size_bytes=size,
                                         sha256=digest, captured_at=captured_at))
            manifest = CaptureManifest(site_id=self.site_id, gateway_id=self.gateway_id, cage_id=cage.id,
                capture_id=capture_id, geometry_revision=cage.geometry_revision,
                placement_revision=cage.placement_revision, captured_at=captured_at, files=files)
            self.require_space(0)
            request = JobRequest(site_id=self.site_id, gateway_id=self.gateway_id, cage_id=cage.id,
                                 job_id=job_id, capture_id=capture_id)
            fsync_directory(temporary)
            temporary.rename(target)
            fsync_directory(captures)
            now = self.now().isoformat()
            with self.db:
                self.db.execute("""INSERT INTO tasks(job_id, capture_id, manifest, request, state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'queued', ?, ?)""", (str(job_id), str(capture_id), manifest.model_dump_json(),
                    request.model_dump_json(), now, now))
            committed = True
            return self.task(job_id)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
            if not committed and target.exists():
                shutil.rmtree(target)

    def input_path(self, capture_id, file_id):
        return self.root / "captures" / str(UUID(str(capture_id))) / str(UUID(str(file_id)))

    def artifact_path(self, job_id, artifact_id):
        directory = self.root / "artifacts" / str(UUID(str(job_id)))
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{UUID(str(artifact_id))}.ply"

    def task(self, job_id):
        row = self.db.execute("SELECT * FROM tasks WHERE job_id=?", (str(UUID(str(job_id))),)).fetchone()
        if row is None:
            raise ComputeFailure("unknown_job")
        body = dict(row)
        for field in ("manifest", "request", "remote"):
            body[field] = json.loads(body[field]) if body[field] else None
        return body

    def tasks(self):
        return [self.task(row[0]) for row in self.db.execute("SELECT job_id FROM tasks ORDER BY created_at")]

    def due(self):
        return [row[0] for row in self.db.execute("""SELECT job_id FROM tasks
            WHERE state NOT IN ('complete', 'blocked', 'failed', 'interrupted')
            AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY updated_at""", (self.now().isoformat(),))]

    def update(self, job_id, *, state, error=None, next_attempt_at=None, remote=None, increment_attempt=False):
        with self.db:
            self.db.execute("""UPDATE tasks SET state=?, error=?, next_attempt_at=?, updated_at=?,
                attempts=attempts+?, remote=COALESCE(?, remote) WHERE job_id=?""",
                (state, error, next_attempt_at, self.now().isoformat(), int(increment_attempt),
                 json.dumps(remote) if remote is not None else None, str(job_id)))

    def bind(self, job_id, endpoint):
        task = self.task(job_id)
        if task["endpoint"] and task["endpoint"] != endpoint:
            raise ComputeFailure("compute_backend_changed")
        with self.db:
            self.db.execute("UPDATE tasks SET endpoint=? WHERE job_id=?", (endpoint, str(job_id)))

    def retry(self, job_id):
        if self.task(job_id)["state"] not in ("blocked", "retry"):
            raise ComputeFailure("only_blocked_or_retryable_tasks_can_retry")
        self.update(job_id, state="queued")
