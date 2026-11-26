"""GPU-rendered views; weights stay on the GPU and cannot operate hardware."""
import base64
import binascii
import hashlib
import io
import os
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import ConfigDict, Field, model_validator

from habitat.common.models import Model
from .errors import ComputeFailure


class RegisteredModel(Model):
    model_id: str
    source_kind: Literal['reference_dataset', 'camera_capture']
    camera_count: int = Field(gt=0)
    quality_status: str


class LiveSceneHealth(Model):
    schema_version: Literal[1]
    service: Literal['livescene']
    status: Literal['configured', 'not_configured']
    capabilities: list[str]
    rgb_training_configured: bool
    cuda_probed: bool
    field_validated: Literal[False]
    hardware_execution_allowed: Literal[False]
    models: list[RegisteredModel]


class SceneObject(Model):
    object_id: int = Field(ge=1, le=254)
    label: str = Field(min_length=1, max_length=80)
    state_min: Literal[0.0] = 0.0
    state_max: Literal[1.0] = 1.0


class SceneModel(RegisteredModel):
    site_id: str
    gateway_id: str
    cage_id: str
    checkpoint_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    geometry_revision: int | None = Field(default=None, ge=1)
    placement_revision: int | None = Field(default=None, ge=1)
    objects: list[SceneObject] = Field(default_factory=list, max_length=1)

    @model_validator(mode='after')
    def known_attribute(self):
        # The registered renderer currently supports one learned state attribute.
        if self.objects and self.objects[0].object_id != 1:
            raise ValueError('one-object renderer requires object_id=1')
        return self


class SceneCatalog(Model):
    schema_version: Literal[1] = 1
    field_validated: Literal[False] = False
    hardware_execution_allowed: Literal[False] = False
    models: list[SceneModel]

    @model_validator(mode='after')
    def unique_models(self):
        keys = [(m.site_id, m.gateway_id, m.cage_id, m.model_id) for m in self.models]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate scene registration')
        return self


class RenderRequest(Model):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    schema_version: Literal[1]
    request_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    site_id: str = Field(min_length=1, max_length=80)
    gateway_id: str = Field(min_length=1, max_length=80)
    cage_id: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    camera_index: int = Field(ge=0, le=9999)
    state: float | None = Field(default=None, ge=0, le=1)
    max_width: int = Field(default=320, ge=128, le=640)
    include_interaction: bool = False


class InteractionMap(Model):
    encoding: Literal['object_id_png']
    image_base64: str = Field(max_length=3*1024*1024)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(gt=0, le=2*1024*1024)
    objects: list[SceneObject] = Field(min_length=1, max_length=1)


class RenderResult(Model):
    schema_version: Literal[1]
    request_id: str
    model_id: str
    site_id: str
    gateway_id: str
    cage_id: str
    source_kind: Literal['reference_dataset', 'camera_capture']
    quality_status: str
    field_validated: Literal[False]
    hardware_execution_allowed: Literal[False]
    checkpoint_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    step: int = Field(ge=0)
    camera_index: int = Field(ge=0)
    state: float | None = Field(ge=0, le=1)
    width: int = Field(gt=0, le=640)
    height: int = Field(gt=0, le=1280)
    device: Literal['cuda']
    gpu_name: str
    elapsed_seconds: float = Field(ge=0, le=60)
    media_type: Literal['image/png']
    size_bytes: int = Field(gt=0, le=2*1024*1024)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    image_base64: str = Field(max_length=3*1024*1024)
    interaction: InteractionMap | None = None


def render_result(client, request):
    """Validate both images in memory; browser viewing creates no render archive."""
    result = client.json('POST', '/v1/livescene/render', RenderResult, json=request, transfer=True)
    if any(getattr(result, key) != request[key] for key in
           ('request_id', 'model_id', 'site_id', 'gateway_id', 'cage_id', 'camera_index', 'state')):
        raise ComputeFailure('livescene_result_mismatch')
    try:
        png = base64.b64decode(result.image_base64, validate=True)
        if len(png) != result.size_bytes or hashlib.sha256(png).hexdigest() != result.sha256:
            raise ValueError('checksum')
        with Image.open(io.BytesIO(png)) as image:
            if (image.format != 'PNG' or image.size != (result.width, result.height)
                    or image.width > request['max_width']):
                raise ValueError('image')
            image.verify()
        if bool(request.get('include_interaction', False)) != (result.interaction is not None):
            raise ValueError('missing or unexpected interaction map')
        if result.interaction:
            selection = result.interaction
            mask = base64.b64decode(selection.image_base64, validate=True)
            if len(mask) != selection.size_bytes or hashlib.sha256(mask).hexdigest() != selection.sha256:
                raise ValueError('mask checksum')
            with Image.open(io.BytesIO(mask)) as image:
                if image.format != 'PNG' or image.mode != 'L' or image.size != (result.width, result.height):
                    raise ValueError('mask dimensions')
                if selection.objects[0].object_id != 1 or image.getextrema()[1] > 1:
                    raise ValueError('unknown mask object')
    except (ValueError, binascii.Error, OSError):
        raise ComputeFailure('invalid_livescene_image') from None
    return result


def render(client, request, destination):
    result = render_result(client, request)
    png = base64.b64decode(result.image_base64)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves existing results and rejects symlink destinations.
    with destination.open('xb') as output:
        output.write(png)
        output.flush()
        os.fsync(output.fileno())
    return result.model_dump(mode='json', exclude={'image_base64', 'interaction'})
