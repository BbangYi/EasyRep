"""Single background GPU worker; API requests never wait for training."""

import hashlib
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from uuid import uuid4

from habitat.gpu.backend import BackendError, job_experiment
from habitat.digital_twin.ply import validate_ply
from habitat.persistence.gpu import sync_directory

logger = logging.getLogger(__name__)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Worker:
    def __init__(self, store, backend, *, lock_path=None):
        self.store, self.backend = store, backend
        self.lock_path = Path(lock_path) if lock_path is not None else store.root / "reconstruction.lock"
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="gpu-worker", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.cancel.set()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise RuntimeError("worker_shutdown_timeout")

    def loop(self):
        while not self.cancel.is_set():
            try:
                if self.backend.health()["gpu"]["reconstruction_ready"]:
                    import fcntl  # CUDA jobs and the existing LiveScene renderer run on Linux/WSL.
                    with self.lock_path.open("a") as lock:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            pass  # Leave jobs queued; cancel.wait below also makes shutdown responsive.
                        else:
                            if self.cancel.is_set():
                                break
                            job = self.store.next_job()
                            if job:
                                # ponytail: serialize COLMAP through export; split stages only if throughput requires it.
                                self.execute(job)
                                continue
            except (OSError, sqlite3.Error):
                logger.error("worker_storage_unavailable")
            except Exception:
                logger.error("worker_unavailable")
            self.cancel.wait(0.2)

    def execute(self, job):
        job_id = job["job_id"]
        work_dir = self.store.root / "jobs" / job_id
        try:
            if self.cancel.is_set():
                raise BackendError("interrupted", "Worker stopped before execution")
            experiment = job_experiment(getattr(self.backend, "config", {}), job_id)
            if experiment:
                source = self.store.job(experiment["source_job_id"])
                if (source is None or source["status"] != "succeeded"
                        or any(source.get(key) != job.get(key)
                               for key in ("capture_id", "site_id", "gateway_id", "cage_id"))):
                    raise BackendError("invalid_experiment", "Frozen reconstruction source does not match this job")
            manifest = self.store.capture(job["capture_id"])
            for item in manifest["files"]:
                path = self.store.file_path(job["capture_id"], item)
                if path.stat().st_size != item["size_bytes"] or digest(path) != item["sha256"]:
                    raise BackendError("input_corrupt", "Stored capture failed integrity validation")
            work_dir.mkdir(parents=True, exist_ok=True)

            def stage(value):
                if value not in {"colmap", "training", "exporting"}:
                    raise BackendError("invalid_backend_stage", "Backend reported an invalid stage")
                self.store.update_job(job_id, stage=value)

            if self.cancel.is_set():
                raise BackendError("interrupted", "Worker stopped before execution")
            output, metadata = self.backend.run(self.store.root / "captures" / job["capture_id"],
                                                work_dir, stage, self.cancel)
            if self.cancel.is_set():
                raise BackendError("process_interrupted", "Worker stopped before completion")
            output = Path(output).resolve()
            if not output.is_relative_to(work_dir.resolve()):
                raise BackendError("invalid_artifact", "Backend output is outside its job directory")
            summary = validate_ply(output)
            artifact_id = str(uuid4())
            artifact_path = work_dir / (artifact_id + ".ply")
            with output.open("rb") as src, artifact_path.with_suffix(".part").open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(artifact_path.with_suffix(".part"), artifact_path)
            for directory in (work_dir, work_dir.parent, self.store.root):
                sync_directory(directory)
            artifact = {"artifact_id": artifact_id, "format": "gaussian_splat_ply",
                        "size_bytes": artifact_path.stat().st_size, "sha256": digest(artifact_path),
                        "download_path": f"/v1/gpu/jobs/{job_id}/artifacts/{artifact_id}",
                        "metric_scale_verified": False, "metadata": {**metadata, "ply": summary}}
            self.store.update_job(job_id, status="succeeded", stage="complete", artifacts=[artifact], error=None)
        except Exception as exc:
            if self.cancel.is_set():
                status, code, message = "interrupted", "process_interrupted", "Worker stopped before completion"
            elif isinstance(exc, BackendError):
                status, code, message = "failed", exc.code, exc.message
            elif isinstance(exc, (OSError, sqlite3.Error)):
                status, code, message = "failed", "storage_unavailable", "Job storage is unavailable"
            else:
                status, code, message = "failed", "invalid_artifact", "Backend result did not pass validation"
            try:
                self.store.update_job(job_id, status=status, stage=status, artifacts=[],
                                      error={"code": code, "message": message})
            except (OSError, sqlite3.Error):
                # A failed disk cannot durably record failure. Restart changes remaining running jobs to interrupted.
                logger.error("job_state_storage_unavailable")
