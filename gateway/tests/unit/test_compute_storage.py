from datetime import datetime, timezone
import sqlite3

from PIL import Image
import pytest

from habitat.compute.errors import ComputeFailure
from habitat.compute.files import file_digest
from habitat.persistence.compute import ComputeRepository


def photos(folder):
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (8, 8), (i * 40, 0, 0)).save(folder / f"{i}.png")
    return folder


def test_capture_is_immutable_and_ids_survive_restart(settings, tmp_path):
    source = photos(tmp_path / "photos")
    root = tmp_path / "compute"
    repo = ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3)
    task = repo.enqueue(source, settings.cages[0], datetime.now(timezone.utc))
    for p in source.iterdir():
        p.write_bytes(b"the user's source folder changed")
    repo.close()
    reopened = ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3)
    try:
        assert reopened.task(task["job_id"])["manifest"] == task["manifest"]
        for entry in task["manifest"]["files"]:
            assert file_digest(reopened.input_path(task["capture_id"], entry["file_id"])) == (entry["size_bytes"], entry["sha256"])
        with pytest.raises(ComputeFailure, match="identity_mismatch"):
            ComputeRepository(root, "OTHER", settings.gateway_id, max_storage_bytes=1024**3)
    finally:
        reopened.close()


def test_one_worker_allows_concurrent_enqueue_and_read(settings, tmp_path):
    root = tmp_path / "compute"
    worker = ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3, worker=True)
    try:
        with pytest.raises(ComputeFailure, match="worker_busy"):
            ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3, worker=True)
        cli = ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3)
        try:
            task = cli.enqueue(photos(tmp_path / "photos"), settings.cages[0], datetime.now(timezone.utc))
            assert worker.task(task["job_id"])["state"] == "queued"
        finally:
            cli.close()
    finally:
        worker.close()


@pytest.mark.parametrize("invalid", ["not_image", "symlink", "too_few", "naive_time", "quota"])
def test_invalid_capture_does_not_leave_a_task_or_staged_files(settings, tmp_path, invalid):
    source = photos(tmp_path / "photos")
    stamp = datetime.now(timezone.utc)
    if invalid == "not_image":
        (source / "0.png").write_bytes(b"not an image")
    elif invalid == "symlink":
        (source / "0.png").unlink()
        (source / "0.png").symlink_to(source / "1.png")
    elif invalid == "too_few":
        (source / "0.png").unlink()
    elif invalid == "naive_time":
        stamp = datetime.now()
    repo = ComputeRepository(tmp_path / "compute", settings.site_id, settings.gateway_id,
                             max_storage_bytes=10 if invalid == "quota" else 1024**3)
    try:
        with pytest.raises((ComputeFailure, ValueError)):
            repo.enqueue(source, settings.cages[0], stamp)
        assert repo.tasks() == []
        assert not list((repo.root / "captures").glob("*"))
    finally:
        repo.close()


def test_unknown_storage_schema_is_not_overwritten(settings, tmp_path):
    root = tmp_path / "compute"
    root.mkdir()
    with sqlite3.connect(root / "compute.sqlite3") as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(ComputeFailure, match="unsupported_compute_storage_schema"):
        ComputeRepository(root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3)
    with sqlite3.connect(root / "compute.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
