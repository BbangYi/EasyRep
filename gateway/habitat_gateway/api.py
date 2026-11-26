import asyncio
from contextlib import asynccontextmanager
import logging
import secrets
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .cloud import CloudSync
from .config import Settings, api_token, cloud_token, video_token
from .gateway import Conflict, Gateway
from .models import CommandRequest, EnclosureRequest, ModeRequest, Reading
from .transport import MQTTTransport, SimulatedTransport
from . import __version__
from habitat.compute.environment import EnvironmentWorker
from habitat.vision.cameras import CameraWorker
from habitat.vision.camera_discovery import CameraDiscovery
from habitat.saas.video import VideoUploader
from .livescene import mount_livescene
from .camera_viewer import mount_camera_viewer

logger = logging.getLogger(__name__)
MAX_ENCLOSURES = 1000


def create_app(settings: Settings, *, run_worker=True, transport=None):
    token = api_token(settings)
    sync_token = cloud_token(settings)
    transport = transport or (SimulatedTransport(settings) if settings.transport == "simulated" else MQTTTransport(settings))
    gateway = Gateway(settings, transport)
    cloud = CloudSync(gateway, sync_token)
    security = HTTPBearer(auto_error=False)
    worker_error = None
    environment = EnvironmentWorker(gateway) if settings.environment.enabled else None
    camera_directory = Path(settings.database).parent / "cameras"
    discovery = (CameraDiscovery(settings.camera_discovery, settings.site_id, settings.gateway_id,
                                 camera_directory) if settings.camera_discovery.enabled else None)
    cameras = CameraWorker(settings.cameras, camera_directory,
                           **({"discovery": discovery} if discovery is not None else {}))
    video = VideoUploader(settings.video_upload, settings.cameras, cameras.directory / "live",
        settings.site_id, settings.gateway_id,
        video_token(settings))
    stop_background = asyncio.Event()

    async def background(action, delay, label):
        while not stop_background.is_set():
            try:
                await asyncio.to_thread(action)
            except Exception:
                logger.error("%s cycle failed; local control continues", label)
            try:
                await asyncio.wait_for(stop_background.wait(), timeout=delay)
            except TimeoutError:
                pass

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if token is not None and (credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(), token.encode()
        )):
            raise HTTPException(status_code=401, detail="invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def cycle():
        with gateway.lock:
            transport.step()
            gateway.tick()

    async def worker():
        nonlocal worker_error
        while True:
            try:
                await asyncio.to_thread(cycle)
            except Exception:
                logger.exception("Control worker stopped")
                gateway.healthy = False
                worker_error = "control_worker_failed"
                return
            await asyncio.sleep(0.25 if settings.r15_bridge.enabled else 1)

    @asynccontextmanager
    async def lifespan(app):
        transport.start(gateway)
        task = asyncio.create_task(worker()) if run_worker else None
        cloud_task = asyncio.create_task(cloud.run()) if run_worker and settings.cloud.enabled else None
        video_task = asyncio.create_task(video.run()) if run_worker and settings.video_upload.enabled else None
        extra_tasks = []
        if run_worker and environment:
            extra_tasks.append(asyncio.create_task(background(environment.cycle, 5, "environment")))
        if run_worker and settings.cameras:
            extra_tasks.append(asyncio.create_task(background(cameras.cycle, 5, "camera")))
        try:
            yield
        finally:
            stop_background.set()
            if video_task:
                video_task.cancel()
                await asyncio.gather(video_task, return_exceptions=True)
            await asyncio.gather(*extra_tasks)
            await asyncio.to_thread(cameras.close)
            if camera_ir:
                await asyncio.to_thread(camera_ir.close)
            if environment:
                environment.close()
            if cloud_task:
                cloud_task.cancel()
                try:
                    await cloud_task
                except asyncio.CancelledError:
                    pass
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            # Shutting down cannot guarantee delivery of OFF; node leases remain mandatory.
            transport.close()
            with gateway.lock:
                gateway.store.close()

    app = FastAPI(title="HabitatOS Store Edge Control", version=__version__, lifespan=lifespan)
    app.state.gateway = gateway
    app.state.cloud = cloud
    app.state.environment = environment

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.get("/health")
    def health():
        healthy = worker_error is None and transport.connected
        return JSONResponse(status_code=200 if healthy else 503, content={
            "status": "ok" if healthy else "degraded", "transport": settings.transport,
            "transport_connected": transport.connected, "worker_error": worker_error,
            "version": __version__, "release_id": os.environ.get("HABITAT_RELEASE_ID", "development"),
        })

    @app.get("/v1/gateway", dependencies=[Depends(authorize)])
    def gateway_identity():
        return {"site_id": settings.site_id, "gateway_id": settings.gateway_id,
                "version": __version__, "release_id": os.environ.get("HABITAT_RELEASE_ID", "development"),
                "transport": settings.transport, "cage_ids": list(gateway.cages),
                "hardware_outputs_enabled": settings.hardware_outputs_enabled}

    @app.get("/v1/cages", dependencies=[Depends(authorize)])
    def cages():
        return [gateway.status(cage.id) for cage in settings.cages]

    def enclosure_records():
        profiles = {profile["cage_id"]: profile for profile in
                    gateway.store.enclosure_profiles(settings.site_id, settings.gateway_id)}
        result = []
        for cage_id in dict.fromkeys([*gateway.cages, *profiles]):
            cage = gateway.cages.get(cage_id)
            result.append({**profiles.get(cage_id, {"cage_id": cage_id, "name": cage_id,
                "species": "", "form_factor": None}),
                "configuration_status": "configured" if cage else "pending_setup",
                "sensors": [{"id": sensor.id, "unit": sensor.unit} for sensor in cage.sensors] if cage else []})
        return result

    @app.get("/v1/enclosures", dependencies=[Depends(authorize)])
    def enclosures():
        with gateway.lock:
            return enclosure_records()

    @app.post("/v1/enclosures", status_code=201, dependencies=[Depends(authorize)])
    def register_enclosure(request: EnclosureRequest):
        with gateway.lock:
            existing = enclosure_records()
            if len(existing) >= MAX_ENCLOSURES:
                raise HTTPException(409, "enclosure_limit_reached")
            if any(row["name"].casefold() == request.name.casefold() for row in existing):
                raise HTTPException(409, "enclosure_name_exists")
            profile = {"cage_id": "CAGE-" + uuid4().hex, **request.model_dump()}
            try:
                gateway.store.register_enclosure(settings.site_id, settings.gateway_id, profile)
            except sqlite3.Error as error:
                if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    raise HTTPException(409, "enclosure_name_exists") from None
                raise HTTPException(503, "enclosure_storage_unavailable") from None
            return {**profile, "configuration_status": "pending_setup", "sensors": []}

    @app.get("/v1/cloud", dependencies=[Depends(authorize)])
    def cloud_status():
        return cloud.status()

    @app.get("/v1/environment", dependencies=[Depends(authorize)])
    def environment_status():
        return environment.state if environment else {"enabled": False}

    @app.get("/v1/cameras", dependencies=[Depends(authorize)])
    def camera_status():
        return {**cameras.status(), "video_upload": video.status()}

    @app.get("/v1/cameras/{camera_id}/snapshot", dependencies=[Depends(authorize)])
    def camera_snapshot(camera_id: str):
        state = cameras.status()["cameras"].get(camera_id)
        if not state:
            raise HTTPException(404, "unknown camera")
        if state.get("status") != "preview_ready":
            raise HTTPException(503, "camera frame unavailable")
        return FileResponse(cameras.directory / f"{camera_id}.jpg", media_type="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Captured-At": str(state["captured_at_epoch"])})

    @app.get("/v1/cages/{cage_id}", dependencies=[Depends(authorize)])
    def cage_status(cage_id: str):
        return gateway.status(cage_id)

    @app.get("/v1/cages/{cage_id}/telemetry", dependencies=[Depends(authorize)])
    def telemetry(cage_id: str, limit: int = Query(default=100, ge=1, le=1000)):
        with gateway.lock:
            gateway.cage(cage_id)
            return gateway.store.history(cage_id, limit)

    @app.post("/v1/cages/{cage_id}/commands", dependencies=[Depends(authorize)])
    def send_command(cage_id: str, request: CommandRequest):
        command = gateway.send_command(cage_id, request)
        return JSONResponse(status_code=409 if command["status"] == "rejected" else 202, content=command)

    @app.get("/v1/cages/{cage_id}/commands", dependencies=[Depends(authorize)])
    def commands(cage_id: str, limit: int = Query(default=100, ge=1, le=1000)):
        with gateway.lock:
            gateway.cage(cage_id)
            return gateway.store.commands(cage_id, limit)

    @app.get("/v1/commands/{command_id}", dependencies=[Depends(authorize)])
    def command_status(command_id: str):
        with gateway.lock:
            command = gateway.store.command(command_id)
            if command is None:
                raise KeyError("unknown command")
            return command

    @app.put("/v1/cages/{cage_id}/mode", dependencies=[Depends(authorize)])
    def set_mode(cage_id: str, request: ModeRequest):
        return gateway.set_mode(cage_id, request.mode)

    @app.post("/v1/cages/{cage_id}/stop", dependencies=[Depends(authorize)])
    def stop(cage_id: str):
        return {"mode": "manual", "commands": gateway.stop_all(cage_id)}

    @app.get("/v1/audit", dependencies=[Depends(authorize)])
    def audit(limit: int = Query(default=100, ge=1, le=1000)):
        with gateway.lock:
            return gateway.store.audit_events(limit)

    if settings.transport == "simulated":
        @app.patch("/v1/simulation/cages/{cage_id}/readings", dependencies=[Depends(authorize)])
        def simulated_readings(cage_id: str, readings: dict[str, Reading]):
            with gateway.lock:
                gateway.cage(cage_id)
                try:
                    transport.patch_readings(cage_id, readings)
                except ValueError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
                gateway.tick()
                return gateway.status(cage_id)

    camera_ir = mount_camera_viewer(app, settings, cameras)
    mount_livescene(app, settings, gateway, authorize)
    return app
