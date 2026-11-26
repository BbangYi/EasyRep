from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest

from habitat.compute.config import ComputeConfig
from habitat.compute.contracts import (CaptureManifest, CaptureStatus, ComputeHealth, FileReceipt,
                                      JobRequest, JobStatus)
from habitat.compute.http_client import HTTPComputeClient
from habitat.compute.service import ComputeWorker
from habitat.persistence.compute import ComputeRepository
from tests.contract.compute_stub import ComputeStub, TEST_TOKEN


@pytest.fixture
def compute(settings, tmp_path):
    config = ComputeConfig(enabled=True, base_url="https://gpu.example.test", storage_dir=str(tmp_path / "compute"))
    repo = ComputeRepository(config.storage_dir, settings.site_id, settings.gateway_id,
                             max_storage_bytes=config.max_storage_bytes)
    folder = tmp_path / "photos"
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (8, 8), (i, i, i)).save(folder / f"view-{i}.png")
    task = repo.enqueue(folder, settings.cages[0], datetime.now(timezone.utc))
    server = ComputeStub()
    client = HTTPComputeClient(config, TEST_TOKEN, transport=httpx.MockTransport(server))
    worker = ComputeWorker(repo, client, config, settings.cages)
    yield repo, worker, server, task["job_id"]
    client.close()
    repo.close()


def test_contract_examples_remain_compatible():
    models = {"capture-manifest": CaptureManifest, "capture-uploading": CaptureStatus,
              "capture-ready": CaptureStatus, "file-receipt": FileReceipt,
              "job-request": JobRequest, "job-queued": JobStatus, "health-not-configured": ComputeHealth}
    for name, model in models.items():
        model.model_validate_json(Path(f"docs/gpu/examples/{name}.json").read_text())


def test_exported_compute_schemas_match_runtime_models():
    from scripts.export_compute_contract import artifacts
    for name, body in artifacts().items():
        assert json.loads(Path("configs/schemas/compute-v1", name).read_text()) == body


def test_upload_submit_poll_download_synthetic_protocol_fixture(compute):
    repo, worker, server, job_id = compute
    assert worker.advance(job_id)["state"] == "waiting"
    assert len(server.jobs) == 1 and len(server.files) == 3
    assert worker.advance(job_id)["state"] == "complete"
    output = repo.artifact_path(job_id, server.artifact_id)
    assert output.read_bytes() == server.artifact
    assert worker.advance(job_id)["state"] == "complete"
    assert len(server.jobs) == 1


def test_partial_upload_resume_does_not_upload_verified_files_again(compute):
    repo, worker, server, job_id = compute
    server.fail_upload_once = True
    assert worker.advance(job_id)["state"] == "retry"
    assert len(server.files) == 1
    assert repo.task(job_id)["next_attempt_at"] is not None
    assert worker.advance(job_id)["state"] == "waiting"
    assert set(server.upload_count.values()) == {1}


def test_ambiguous_submit_retry_preserves_request_id_across_restart(compute, settings):
    repo, worker, server, job_id = compute
    server.lose_job_response_once = True
    assert worker.advance(job_id)["state"] == "retry"
    assert list(server.jobs) == [job_id]
    reopened = ComputeRepository(repo.root, settings.site_id, settings.gateway_id, max_storage_bytes=1024**3)
    try:
        restarted = ComputeWorker(reopened, worker.client, worker.config, settings.cages)
        assert restarted.advance(job_id)["state"] == "waiting"
        assert list(server.jobs) == [job_id]
    finally:
        reopened.close()


def test_auth_scope_mismatch_and_disabled_backend(compute):
    repo, worker, server, job_id = compute
    server.forbidden_scope = True
    result = worker.advance(job_id)
    assert result["state"] == "blocked" and result["error"] == "capture_scope_mismatch"
    assert not server.files and not server.jobs
    repo.retry(job_id)
    server.forbidden_scope = False
    server.backend_ready = False
    result = worker.advance(job_id)
    assert result["state"] == "retry" and result["error"] == "backend_not_ready"
    assert not server.jobs


@pytest.mark.parametrize("attack", ["html", "redirect", "wrong_receipt", "wrong_revision", "foreign_artifact", "traversal_artifact", "bad_hash"])
def test_untrusted_responses_cannot_complete_or_redirect_tokens(compute, attack):
    repo, worker, server, job_id = compute
    if attack in ("html", "redirect"):
        server.override = lambda r: httpx.Response(200, text="<html>demo</html>") if attack == "html" else httpx.Response(
            307, headers={"Location": "https://other-host.example.test/token-theft"})
    elif attack == "wrong_receipt":
        def bad_receipt(request):
            if request.method == "PUT":
                entry = repo.task(job_id)["manifest"]["files"][0]
                return httpx.Response(200, json={"schema_version": 1, "capture_id": repo.task(job_id)["capture_id"],
                    "file_id": entry["file_id"], "size_bytes": entry["size_bytes"], "sha256": "0" * 64, "status": "verified"})
        server.override = bad_receipt
    else:
        assert worker.advance(job_id)["state"] == "waiting"
        if attack == "bad_hash":
            server.corrupt_download = True
        else:
            def bad_job(request):
                if request.method == "GET" and request.url.path.endswith(job_id):
                    server.override = None
                    response = server(request)
                    server.override = bad_job
                    body = response.json()
                    if attack == "wrong_revision":
                        body["geometry_revision"] += 1
                    else:
                        body["artifacts"][0]["download_path"] = (
                            "https://other-host.example.test/file" if attack == "foreign_artifact" else "/v1/gpu/../private-key")
                    return httpx.Response(200, json=body)
            server.override = bad_job
    result = worker.advance(job_id)
    assert result["state"] == "blocked"
    assert not list((repo.root / "artifacts").rglob("*.ply"))
    assert not list((repo.root / "artifacts").rglob("*.part"))


def test_backend_change_and_local_file_corruption_are_detected(compute):
    repo, worker, server, job_id = compute
    task = repo.task(job_id)
    entry = task["manifest"]["files"][0]
    repo.input_path(task["capture_id"], entry["file_id"]).write_bytes(b"changed")
    assert worker.advance(job_id)["error"] == "local_capture_file_changed"
    repo.retry(job_id)
    worker.client.origin = "https://a-different-gpu.example.test"
    assert worker.advance(job_id)["error"] == "compute_backend_changed"


def test_disabled_worker_never_connects(compute):
    repo, worker, server, job_id = compute
    worker.config.enabled = False
    assert worker.cycle() == []
    assert worker.advance(job_id)["state"] == "queued"
    assert server.requests == []


def test_same_client_code_serves_distinct_store_configs(settings, tmp_path):
    from tests.unit.test_compute_storage import photos
    peer = ComputeStub()
    source = photos(tmp_path / "photos")
    for site, gateway, cage_id in (("STORE-A", "PI-2", "CAGE-7"), ("STORE-B", "PI-9", "CAGE-3")):
        config = ComputeConfig(enabled=True, base_url="https://gpu.example.test", storage_dir=str(tmp_path / site))
        cage = settings.cages[0].model_copy(update={"id": cage_id})
        repo = ComputeRepository(config.storage_dir, site, gateway, max_storage_bytes=config.max_storage_bytes)
        client = HTTPComputeClient(config, TEST_TOKEN, transport=httpx.MockTransport(peer))
        try:
            task = repo.enqueue(source, cage, datetime.now(timezone.utc))
            worker = ComputeWorker(repo, client, config, [cage])
            assert worker.advance(task["job_id"])["state"] == "waiting"
            assert worker.advance(task["job_id"])["state"] == "complete"
            sent = peer.jobs[task["job_id"]]
            assert (sent["site_id"], sent["gateway_id"], sent["cage_id"]) == (site, gateway, cage_id)
        finally:
            client.close()
            repo.close()


@pytest.mark.parametrize("url", ["http://100.100.211.20:8100", "https://user:password@gpu.example.test",
                                 "https://gpu.example.test?token=secret", "https://gpu.example.test/v1/gpu"])
def test_gpu_url_rejects_cleartext_credentials_and_path(url):
    with pytest.raises(ValueError):
        ComputeConfig(enabled=True, base_url=url)


@pytest.mark.parametrize("status", [401, 403, 404, 409, 413, 422, 429, 503])
def test_http_failures_preserve_input_and_bound_retries(compute, status):
    repo, worker, server, job_id = compute
    server.override = lambda _: httpx.Response(status, text="remote error may contain a token")
    result = worker.advance(job_id)
    retryable = status in (429, 503)
    assert result["state"] == ("retry" if retryable else "blocked")
    assert result["error"] == f"http_{status}"
    assert bool(result["next_attempt_at"]) == retryable
    assert len(list((repo.root / "captures" / result["capture_id"]).iterdir())) == 3
    assert not server.jobs


@pytest.mark.parametrize("state", ["failed", "interrupted"])
def test_remote_terminal_failure_does_not_restart_training(compute, state):
    repo, worker, server, job_id = compute
    assert worker.advance(job_id)["state"] == "waiting"
    def terminal(request):
        if request.url.path.endswith(job_id):
            return httpx.Response(200, json={**server.jobs[job_id], "status": state, "stage": state,
                "error": {"code": "backend_failure", "message": "do not persist remote secret"}})
    server.override = terminal
    assert worker.advance(job_id)["state"] == state
    assert "remote secret" not in json.dumps(repo.task(job_id))
    requests = len(server.requests)
    assert worker.cycle() == []
    assert worker.advance(job_id)["state"] == state
    assert len(server.requests) == requests
