"""Exercise the deployed API with real photos; preserve UUIDs for safe retries.

This desktop verification client is not the Pi worker. A successful run must
never be reported as pi_to_gpu success. Configuration/token values stay private.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from habitat.gpu.contracts import CaptureStatus, ComputeHealth, FileReceipt, JobStatus
from habitat.digital_twin.ply import validate_ply


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--token-env", default="HABITAT_GPU_TOKEN")
    parser.add_argument("--health-only", action="store_true")
    parser.add_argument("--images", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--captured-at")
    parser.add_argument("--site-id", default="STORE-001")
    parser.add_argument("--gateway-id", default="PI-001")
    parser.add_argument("--cage-id", default="CAGE-001")
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=7200)
    parser.add_argument("--max-artifact-bytes", type=int, default=1024**3)
    args = parser.parse_args()
    origin = urlsplit(args.base_url)
    if not origin.hostname or (origin.scheme != "https" and not (origin.scheme == "http" and origin.hostname in {"127.0.0.1", "localhost", "::1"})) or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ("", "/"):
        parser.error("base-url must be an HTTPS origin (loopback HTTP allowed)")
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(args.token_env + "="):
                os.environ[args.token_env] = line.split("=", 1)[1]
    token = os.environ[args.token_env]
    require(len(token) >= 32 and all(33 <= ord(character) <= 126 for character in token),
            "GPU token must contain at least 32 printable ASCII characters without spaces")
    with httpx.Client(base_url=args.base_url.rstrip("/"), headers={"Authorization": "Bearer " + token,
                      "Accept-Encoding": "identity"}, trust_env=False, follow_redirects=False, timeout=300) as client:
        def checked(method, path, model, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code not in (200, 202):
                raise RuntimeError(f"API rejected {method} {path}: HTTP {response.status_code}")
            return model.model_validate(response.json()).model_dump(mode="json")

        health = checked("GET", "/v1/gpu/health", ComputeHealth)
        require(client.get("/v1/gpu/health", headers={"Authorization": ""}).status_code == 401,
                "Server accepted an unauthenticated request")
        print(json.dumps({"desktop_api_health": health, "tls_verified": origin.scheme == "https",
                          "unauthenticated_rejected": True, "pi_to_gpu": "not_run"}), flush=True)
        if args.health_only:
            return
        if not health["gpu"]["reconstruction_ready"] or health["backend"] != "splatfacto":
            raise RuntimeError("Real reconstruction backend is not ready")
        if not args.images or not args.record or not args.captured_at:
            parser.error("--images, --record, --captured-at are required for reconstruction")
        images = sorted(path.resolve() for path in args.images.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if args.record.exists():
            record = json.loads(args.record.read_text(encoding="utf-8"))
            if record["base_url"] != args.base_url:
                raise RuntimeError("Saved job is bound to a different API origin")
        else:
            manifest = {"schema_version": 1, "capture_id": str(uuid4()), "site_id": args.site_id,
                        "gateway_id": args.gateway_id, "cage_id": args.cage_id, "geometry_revision": 1,
                        "placement_revision": 1, "captured_at": args.captured_at, "capture_method": "multiview_rgb",
                        "files": [{"file_id": str(uuid4()), "name": path.name, "size_bytes": path.stat().st_size,
                                   "sha256": file_hash(path), "captured_at": args.captured_at} for path in images]}
            job = {key: manifest[key] for key in ("schema_version", "capture_id", "site_id", "gateway_id", "cage_id")}
            job.update(job_id=str(uuid4()), kind="3dgs", preset="preview")
            record = {"base_url": args.base_url, "manifest": manifest, "job": job,
                      "started_at": datetime.now(timezone.utc).isoformat(), "verification_location": "desktop"}
            save(args.record, record)
        manifest, job = record["manifest"], record["job"]
        by_name = {path.name: path for path in images}
        status = checked("POST", "/v1/gpu/captures", CaptureStatus, json=manifest)
        require(all(status[key] == manifest[key] for key in ("site_id", "gateway_id", "cage_id", "capture_id")),
                "Capture response identity differs from request")
        require(set(status["verified_file_ids"] + status["missing_file_ids"]) == {item["file_id"] for item in manifest["files"]},
                "Capture response file partition differs from manifest")
        for item in manifest["files"]:
            path = by_name[item["name"]]
            if path.stat().st_size != item["size_bytes"] or file_hash(path) != item["sha256"]:
                raise RuntimeError("Input changed after UUIDs were saved")
            if item["file_id"] in status["missing_file_ids"]:
                with path.open("rb") as stream:
                    receipt = checked("PUT", f"/v1/gpu/captures/{manifest['capture_id']}/files/{item['file_id']}",
                                      FileReceipt, content=stream, headers={"Content-Type": "application/octet-stream"})
                require(receipt["capture_id"] == manifest["capture_id"] and all(
                    receipt[key] == item[key] for key in ("file_id", "size_bytes", "sha256")), "File receipt differs from manifest")
        status = checked("POST", "/v1/gpu/jobs", JobStatus, json=job)

        def verify_job(value):
            require(all(value[key] == item for key, item in job.items()), "Job response differs from request")
            require(all(value[key] == manifest[key] for key in ("geometry_revision", "placement_revision")),
                    "Job response revision differs from manifest")

        verify_job(status)
        record["last_status"] = status
        save(args.record, record)
        if args.submit_only:
            print(json.dumps({"job_id": job["job_id"], "status": status["status"]}), flush=True)
            return
        previous = None
        deadline = time.monotonic() + args.wait_seconds
        while status["status"] in {"queued", "running"}:
            require(time.monotonic() < deadline, "Polling deadline exceeded; UUID record preserved for retry")
            if status["stage"] != previous:
                print(json.dumps({"job_id": job["job_id"], "stage": status["stage"]}), flush=True)
                previous = status["stage"]
            time.sleep(5)
            status = checked("GET", f"/v1/gpu/jobs/{job['job_id']}", JobStatus)
            verify_job(status)
            record["last_status"] = status
            save(args.record, record)
        if status["status"] != "succeeded":
            raise RuntimeError("Reconstruction ended: " + status["status"] + "/" + status["error"]["code"])
        artifact = status["artifacts"][0]
        require(artifact["size_bytes"] <= args.max_artifact_bytes, "Artifact exceeds configured download limit")
        destination = args.record.parent / (artifact["artifact_id"] + ".ply")
        checksum, size = hashlib.sha256(), 0
        with client.stream("GET", artifact["download_path"]) as response:
            require(response.status_code == 200, "Artifact download was not HTTP 200")
            require(response.headers.get("Content-Encoding", "identity") == "identity", "Artifact encoding changed")
            require(int(response.headers["Content-Length"]) == artifact["size_bytes"], "Artifact length header changed")
            require(response.headers["X-Content-SHA256"] == artifact["sha256"], "Artifact hash header changed")
            with destination.with_suffix(".part").open("wb") as output:
                for block in response.iter_raw():
                    size += len(block)
                    if size > artifact["size_bytes"]:
                        raise RuntimeError("Artifact exceeds declared size")
                    checksum.update(block)
                    output.write(block)
        require(size == artifact["size_bytes"] and checksum.hexdigest() == artifact["sha256"], "Artifact content differs from metadata")
        summary = validate_ply(destination.with_suffix(".part"))
        os.replace(destination.with_suffix(".part"), destination)
        record.update(download_verified=True, ply=summary, downloaded_artifact=str(destination),
                      completed_at=datetime.now(timezone.utc).isoformat(), pi_to_gpu="not_run")
        save(args.record, record)
        print(json.dumps({"job_id": job["job_id"], "status": "succeeded", "sha256": artifact["sha256"],
                          "size_bytes": size, "vertices": summary["vertex_count"], "pi_to_gpu": "not_run"}), flush=True)


if __name__ == "__main__":
    main()
