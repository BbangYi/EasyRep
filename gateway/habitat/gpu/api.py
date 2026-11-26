"""Authenticated Pi upload API, contract 1.0.0."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import UUID
import warnings

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from PIL import Image
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect

from habitat.gpu.backend import Backend
from habitat.gpu.contracts import CaptureManifest, CaptureStatus, ComputeHealth, FileReceipt, JobRequest, JobStatus
from habitat.gpu.worker import Worker, digest
from habitat.persistence.gpu import Store, sync_directory


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


def error(status, code, message):
    return HTTPException(status, detail={"code": code, "message": message})


def in_scope(credential, payload):
    return (payload["site_id"] == credential.site_id and payload["gateway_id"] == credential.gateway_id
            and payload["cage_id"] in credential.cage_ids)


def inspect_image(path, name):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            expected = "PNG" if Path(name).suffix.lower() == ".png" else "JPEG"
            if image.format != expected or image.width * image.height > 20_000_000:
                raise ValueError("invalid_image")
            image.verify()
        with Image.open(path) as image:
            image.load()


class RequestBoundary:
    """Authenticate before reading bodies and cap both declared and chunked payloads."""

    JSON_BODY_TIMEOUT_SECONDS = 30

    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        supplied = headers.get("authorization", "")
        credential = None
        if supplied.startswith("Bearer ") and supplied.isascii():
            for candidate in self.config.credentials:
                if hmac.compare_digest(supplied[7:], candidate.token.get_secret_value()):
                    credential = candidate
        if credential is None:
            return await JSONResponse({"detail": {"code": "unauthorized", "message": "Valid GPU token required"}},
                                      status_code=401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        scope["credential"] = credential
        limit = self.config.limits.max_file_bytes if scope["method"] == "PUT" else 1024 * 1024
        try:
            length = int(headers.get("content-length", "0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": {"code": "invalid_length", "message": "Invalid content length"}},
                                      status_code=422)(scope, receive, send)
        if length > limit:
            return await JSONResponse({"detail": {"code": "payload_too_large", "message": "Request exceeds size limit"}},
                                      status_code=413)(scope, receive, send)
        total = 0
        deadline = (asyncio.get_running_loop().time() + self.JSON_BODY_TIMEOUT_SECONDS
                    if scope["method"] == "POST" else None)

        async def bounded_receive():
            nonlocal total
            try:
                async with asyncio.timeout_at(deadline):
                    message = await receive()
            except TimeoutError:
                raise error(503, "request_timeout", "Request body deadline exceeded") from None
            total += len(message.get("body", b""))
            if total > limit:
                raise error(413, "payload_too_large", "Request exceeds size limit")
            return message

        await self.app(scope, bounded_receive, send)


def create_app(config, backend=None):
    store = Store(config.storage_dir)
    backend = backend if backend is not None else Backend(config.backend)
    worker = Worker(store, backend, lock_path=config.backend.get("livescene", {}).get("lock_file"))

    @asynccontextmanager
    async def lifespan(app):
        try:
            store.start()
            worker.start()
            yield
        finally:
            await run_in_threadpool(close_environment)
            if worker.thread.is_alive():
                await run_in_threadpool(worker.stop)
            store.close()

    app = FastAPI(title="HabitatOS GPU API", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False,
                  responses={status: {"model": ErrorResponse} for status in (400, 401, 403, 404, 409, 413, 422, 429, 503)})
    app.state.store, app.state.worker, app.state.backend = store, worker, backend
    app.add_middleware(RequestBoundary, config=config)
    bearer = HTTPBearer(auto_error=False)

    def credential(request: Request, _=Depends(bearer)):
        return request.scope["credential"]

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": "Request rejected"}
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": {"code": "invalid_request", "message": "Request does not match GPU contract"}},
                            status_code=422)

    async def storage_error(request, exc):
        return JSONResponse({"detail": {"code": "storage_unavailable", "message": "Storage is unavailable"}}, status_code=503)

    app.add_exception_handler(OSError, storage_error)
    app.add_exception_handler(sqlite3.Error, storage_error)

    def owned_capture(capture_id, owner):
        manifest = store.capture(capture_id)
        if manifest is None or not in_scope(owner, manifest):
            raise error(404, "capture_not_found", "Capture not found")
        return manifest

    def owned_job(job_id, owner):
        job = store.job(job_id)
        if job is None or not in_scope(owner, job):
            raise error(404, "job_not_found", "Job not found")
        return job

    @app.get("/openapi.json", include_in_schema=False)
    def openapi(_=Depends(credential)):
        return app.openapi()

    @app.get("/v1/gpu/health", response_model=ComputeHealth)
    def health(_=Depends(credential)):
        value = backend.health()
        ready = value["backend"] == "splatfacto" and value["gpu"]["cuda_available"] and value["gpu"]["reconstruction_ready"]
        return {"schema_version": 1, "service": "habitat-gpu", "api_version": "1.0.0",
                "status": "ok" if ready else "degraded", **value, "limits": config.limits.model_dump()}

    @app.post("/v1/gpu/captures", response_model=CaptureStatus)
    def register_capture(request: CaptureManifest, owner=Depends(credential)):
        manifest = request.model_dump(mode="json")
        if not in_scope(owner, manifest):
            raise error(403, "scope_denied", "Capture scope is not registered for this token")
        limits = config.limits
        if (len(manifest["files"]) > limits.max_files_per_capture
                or any(item["size_bytes"] > limits.max_file_bytes for item in manifest["files"])
                or sum(item["size_bytes"] for item in manifest["files"]) > limits.max_capture_bytes):
            raise error(413, "capture_too_large", "Capture exceeds configured limits")
        with store.lock:
            existing = store.capture(manifest["capture_id"])
            if existing:
                if not in_scope(owner, existing):
                    raise error(404, "capture_not_found", "Capture not found")
                if existing != manifest:
                    raise error(409, "id_conflict", "Capture ID already has a different manifest")
            else:
                store.add_capture(manifest)
        return store.capture_status(manifest)

    @app.get("/v1/gpu/captures/{capture_id}", response_model=CaptureStatus)
    def capture_status(capture_id: UUID, owner=Depends(credential)):
        return store.capture_status(owned_capture(capture_id, owner))

    uploads = asyncio.Semaphore(4)

    @app.put("/v1/gpu/captures/{capture_id}/files/{file_id}", response_model=FileReceipt,
             openapi_extra={"requestBody": {"required": True, "content": {"application/octet-stream": {
                 "schema": {"type": "string", "format": "binary"}}}}})
    async def upload(capture_id: UUID, file_id: UUID, request: Request, owner=Depends(credential)):
        manifest = owned_capture(capture_id, owner)
        item = next((item for item in manifest["files"] if item["file_id"] == str(file_id)), None)
        if item is None:
            raise error(404, "file_not_found", "File is not in capture manifest")
        if (request.headers.get("content-type", "").split(";")[0] != "application/octet-stream"
                or request.headers.get("content-encoding", "identity") != "identity"):
            raise error(422, "invalid_file_encoding", "Send uncompressed application/octet-stream bytes")
        temp_path = None
        try:
            async with asyncio.timeout(300), uploads:
                staging = store.staging_path()
                checksum, size = hashlib.sha256(), 0
                with tempfile.NamedTemporaryFile(dir=staging, prefix="upload-", suffix=".part", delete=False) as stream:
                    temp_path = Path(stream.name)
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > item["size_bytes"]:
                            raise error(422, "size_mismatch", "File does not match manifest size")
                        checksum.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if size != item["size_bytes"] or checksum.hexdigest() != item["sha256"]:
                    raise error(422, "file_mismatch", "File size or SHA-256 does not match manifest")
                try:
                    await run_in_threadpool(inspect_image, temp_path, item["name"])
                except (ValueError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    raise error(422, "invalid_image", "File is not a valid supported image") from None
                destination = store.file_path(str(capture_id), item)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with store.lock:
                    if not destination.exists():
                        os.replace(temp_path, destination)
                    elif destination.stat().st_size != size or digest(destination) != item["sha256"]:
                        raise error(409, "stored_file_corrupt", "Existing file failed integrity validation")
                    for directory in (destination.parent, destination.parent.parent, store.root):
                        sync_directory(directory)
                    store.verify_file(str(capture_id), str(file_id))
                return {"schema_version": 1, "capture_id": capture_id, "file_id": file_id,
                        "size_bytes": size, "sha256": item["sha256"], "status": "verified"}
        except TimeoutError:
            raise error(503, "upload_timeout", "Upload deadline exceeded") from None
        except ClientDisconnect:
            raise error(400, "upload_interrupted", "Upload disconnected before completion") from None
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    @app.post("/v1/gpu/jobs", response_model=JobStatus, status_code=202)
    def submit_job(request: JobRequest, owner=Depends(credential)):
        payload = request.model_dump(mode="json")
        if not in_scope(owner, payload):
            raise error(403, "scope_denied", "Job scope is not registered for this token")
        with store.lock:
            existing = store.job(payload["job_id"])
            if existing:
                if not in_scope(owner, existing):
                    raise error(404, "job_not_found", "Job not found")
                if store.job_request(payload["job_id"]) != payload:
                    raise error(409, "id_conflict", "Job ID already has a different request")
                return existing
            capture = owned_capture(payload["capture_id"], owner)
            if any(capture[key] != payload[key] for key in ("site_id", "gateway_id", "cage_id")):
                raise error(403, "scope_denied", "Job and capture scope differ")
            if store.capture_status(capture)["status"] != "ready":
                raise error(409, "capture_not_ready", "Some files have not been verified")
            state = backend.health()
            if (state["backend"] != "splatfacto" or not state["gpu"]["cuda_available"]
                    or not state["gpu"]["reconstruction_ready"]):
                raise error(503, "backend_not_ready", "GPU reconstruction backend is not ready")
            return store.add_job(payload, capture)

    @app.get("/v1/gpu/jobs/{job_id}", response_model=JobStatus)
    def job_status(job_id: UUID, owner=Depends(credential)):
        return owned_job(job_id, owner)

    @app.get("/v1/gpu/jobs/{job_id}/artifacts/{artifact_id}", response_class=FileResponse,
             responses={200: {"content": {"application/octet-stream": {}}, "headers": {
                 "X-Content-SHA256": {"schema": {"type": "string"}},
                 "Content-Length": {"schema": {"type": "integer"}}}}})
    def download(job_id: UUID, artifact_id: UUID, owner=Depends(credential)):
        job = owned_job(job_id, owner)
        artifact = next((item for item in job["artifacts"] if item["artifact_id"] == str(artifact_id)), None)
        if job["status"] != "succeeded" or artifact is None:
            raise error(404, "artifact_not_found", "Artifact not found")
        path = store.root / "jobs" / str(job_id) / (str(artifact_id) + ".ply")
        if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or digest(path) != artifact["sha256"]:
            raise error(503, "artifact_unavailable", "Artifact failed integrity validation")
        return FileResponse(path, media_type="application/octet-stream",
                            headers={"X-Content-SHA256": artifact["sha256"], "Content-Encoding": "identity",
                                     "Cache-Control": "private, no-transform"})

    from habitat.gpu.environment_api import mount_environment
    close_environment = mount_environment(app, config, credential, in_scope, error)
    from habitat.gpu.livescene_api import mount_livescene
    mount_livescene(app, config, credential, in_scope, error)
    return app
