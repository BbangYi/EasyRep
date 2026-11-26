"""Browser access to GPU scene views; physical commands retain the Pi safety boundary."""
from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, model_validator

from habitat.common.models import Identifier, Model
from habitat.compute.errors import ComputeFailure
from habitat.compute.http_client import HTTPComputeClient
from habitat.compute.livescene import RenderRequest, SceneCatalog, render_result
from .models import CommandRequest


class SceneCommand(Model):
    request_id: UUID
    model_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    cage_id: Identifier
    object_id: int = Field(strict=True, ge=1, le=65535)
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    geometry_revision: int = Field(strict=True, ge=1)
    placement_revision: int = Field(strict=True, ge=1)
    action: Literal["on", "off"]
    duration_s: float = Field(default=0, ge=0, le=3600)

    def command(self, actuator_id):
        return CommandRequest(request_id=self.request_id, actuator_id=actuator_id,
                              action=self.action, duration_s=self.duration_s)

    @model_validator(mode="after")
    def duration_matches_action(self):
        self.command("validated-binding")
        return self


def mount_livescene(app, settings, gateway, authorize):
    render_gate = threading.Lock()

    @contextmanager
    def gpu_client():
        config = settings.environment
        if not config.enabled or config.origin is None:
            raise HTTPException(503, "livescene_not_configured")
        try:
            client = HTTPComputeClient(config.model_copy(update={"timeout_s": 60., "transfer_timeout_s": 60.}),
                                       config.token())
        except (ValueError, OSError):
            raise HTTPException(503, "livescene_credentials_unavailable") from None
        try:
            yield client
        except ComputeFailure as error:
            status = 429 if error.status_code == 429 else 503
            raise HTTPException(status, "livescene_busy" if status == 429 else "livescene_unavailable") from None
        finally:
            client.close()

    def scoped(model):
        return (model.site_id == settings.site_id and model.gateway_id == settings.gateway_id
                and model.cage_id in gateway.cages)

    def binding_for(model, object_id):
        if model.source_kind != "camera_capture":
            return None
        cage = gateway.cages[model.cage_id]
        return next((binding for binding in settings.livescene_bindings
            if binding.model_id == model.model_id and binding.cage_id == model.cage_id
            and binding.object_id == object_id and binding.checkpoint_sha256 == model.checkpoint_sha256
            and binding.geometry_revision == model.geometry_revision == cage.geometry_revision
            and binding.placement_revision == model.placement_revision == cage.placement_revision), None)

    def catalog(client):
        result = client.json("GET", "/v1/livescene/models", SceneCatalog)
        return result.model_copy(update={"models": [model for model in result.models if scoped(model)]})

    @app.get("/livescene", include_in_schema=False)
    def viewer():
        return FileResponse(Path(__file__).with_name("livescene.html"), media_type="text/html", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})

    @app.get("/livescene/assets/{filename}", include_in_schema=False)
    def viewer_asset(filename: str):
        if filename not in {"terrarium-tropical.webp", "terrarium-desert.webp", "terrarium-aquatic.webp"}:
            raise HTTPException(404, "asset_not_found")
        return FileResponse(Path(__file__).with_name("assets") / filename, media_type="image/webp", headers={
            "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})

    @app.get("/v1/livescene/models", dependencies=[Depends(authorize)])
    def scene_models():
        with gpu_client() as client:
            result = catalog(client)
        body = result.model_dump(mode="json")
        for model, item in zip(result.models, body["models"]):
            for obj in item["objects"]:
                binding = binding_for(model, obj["object_id"])
                if binding:
                    obj["actuator_id"] = binding.actuator_id
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.post("/v1/livescene/render", dependencies=[Depends(authorize)])
    def scene_render(request: RenderRequest):
        if not scoped(request):
            raise HTTPException(403, "scene_scope_denied")
        if not render_gate.acquire(blocking=False):
            raise HTTPException(429, "livescene_busy")
        try:
            with gpu_client() as client:
                result = render_result(client, request.model_dump(mode="json"))
            return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
        finally:
            render_gate.release()

    @app.post("/v1/livescene/commands", dependencies=[Depends(authorize)])
    def scene_command(request: SceneCommand):
        if request.cage_id not in gateway.cages:
            raise HTTPException(403, "scene_scope_denied")
        preliminary = next((binding for binding in settings.livescene_bindings
            if binding.model_id == request.model_id and binding.cage_id == request.cage_id
            and binding.object_id == request.object_id
            and binding.checkpoint_sha256 == request.checkpoint_sha256
            and binding.geometry_revision == request.geometry_revision
            and binding.placement_revision == request.placement_revision), None)
        if preliminary is None:
            raise HTTPException(409, "scene_object_not_bound")
        with gateway.lock:
            prior_command_id = (gateway.store.latest_command(request.cage_id, preliminary.actuator_id) or {}).get("command_id")
        with gpu_client() as client:
            model = next((model for model in catalog(client).models if model.model_id == request.model_id
                          and model.cage_id == request.cage_id), None)
        if model is None:
            raise HTTPException(404, "scene_model_not_found")
        binding = binding_for(model, request.object_id)
        if binding != preliminary or not any(obj.object_id == request.object_id for obj in model.objects):
            raise HTTPException(409, "scene_object_not_bound")
        with gateway.lock:
            latest_command_id = (gateway.store.latest_command(request.cage_id, binding.actuator_id) or {}).get("command_id")
            # An intervening stop must invalidate a delayed GPU-dependent ON. Existing IDs
            # still use the gateway's idempotency check and can never dispatch again.
            if (request.action == "on" and latest_command_id != prior_command_id
                    and gateway.store.command(str(request.request_id)) is None):
                raise HTTPException(409, "scene_command_superseded")
            command = gateway.send_command(request.cage_id, request.command(binding.actuator_id))
        return JSONResponse(status_code=409 if command["status"] == "rejected" else 202, content=command)
