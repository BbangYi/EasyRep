"""Render registered LiveScene checkpoints without changing the Gaussian job contract."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading

from fastapi import Depends
from PIL import Image

from habitat.gpu.worker import digest
from habitat.gpu.backend import Backend, BackendError
from habitat.compute.livescene import RenderRequest, SceneCatalog, SceneModel


def mount_livescene(app, config, credential, in_scope, error):
    settings = config.backend.get('livescene', {})
    script = Path(__file__).resolve().parents[2] / 'scripts/render_livescene_sample.py'
    runner_config = {**config.backend, 'name': 'not_configured', 'stage_timeout_seconds': {'render': 55}}
    if settings.get('python'):
        runner_config['python'] = settings['python']
    runner = Backend(runner_config)

    def models(owner):
        if not settings.get('manifest'):
            return []
        try:
            items = json.loads(Path(settings['manifest']).read_text())['models']
            return [item for item in items if in_scope(owner, item)]
        except (OSError, ValueError, KeyError, TypeError):
            raise error(503, 'livescene_unavailable', 'Model registry is unavailable') from None

    def public_model(model):
        return SceneModel.model_validate({key: model[key] for key in SceneModel.model_fields if key in model})

    @app.get('/v1/livescene/models', response_model=SceneCatalog)
    def catalog(owner=Depends(credential)):
        try:
            return SceneCatalog(models=[public_model(model) for model in models(owner)])
        except (ValueError, KeyError, TypeError):
            raise error(503, 'livescene_unavailable', 'Model registry is unavailable') from None

    @app.get('/v1/livescene/health')
    def health(owner=Depends(credential)):
        items = models(owner)
        return {'schema_version': 1, 'service': 'livescene',
                'status': 'configured' if items else 'not_configured',
                'capabilities': ['render_registered_model'] if items else [],
                'rgb_training_configured': False, 'cuda_probed': False,
                'field_validated': False, 'hardware_execution_allowed': False,
                'models': [{k: item[k] for k in ('model_id', 'source_kind', 'camera_count', 'quality_status')}
                           for item in items]}

    @app.post('/v1/livescene/render')
    def render(request: RenderRequest, owner=Depends(credential)):
        import fcntl  # The CUDA renderer runs on the Linux/WSL GPU host.
        payload = request.model_dump(mode='json')
        if not in_scope(owner, payload):
            raise error(403, 'scope_denied', 'Render scope is not registered for this token')
        model = next((m for m in models(owner) if m['model_id'] == request.model_id
                      and all(m[k] == payload[k] for k in ('site_id', 'gateway_id', 'cage_id'))), None)
        if model is None:
            raise error(404, 'model_not_found', 'Registered model not found')
        if request.camera_index >= model['camera_count']:
            raise error(422, 'invalid_camera', 'Camera index is outside the registered model')
        try:
            metadata = public_model(model)
            if request.include_interaction and not metadata.objects:
                raise error(422, 'interaction_unavailable', 'Object labels are not registered for this model')
            model_config = Path(model['config'])
            if digest(model_config) != model['config_sha256']:
                raise ValueError('config changed')
            lock_path = Path(settings['lock_file'])
            with lock_path.open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise error(429, 'reconstruction_busy', 'GPU reconstruction is in use') from None
                # ponytail: a cold process bounds GPU memory lifetime; retain a worker only if measured latency requires it.
                with tempfile.TemporaryDirectory(prefix='livescene-', dir=config.storage_dir) as folder:
                    output = Path(folder)
                    worker_input = {**payload, 'checkpoint_sha256': model['checkpoint_sha256'],
                                    'checkpoint_step': model['checkpoint_step']}
                    request_file = output / 'request.json'
                    request_file.write_text(json.dumps(worker_input))
                    try:
                        # Reuse the existing parent-death watchdog, deadline and process-group cleanup.
                        runner._command([settings['python'], str(script), str(model_config), folder,
                            '--api-request', '--request-file', str(request_file)], output, 'render',
                            threading.Event(), {'stage_seconds': {}, 'peak_device_vram_bytes': 0})
                    except BackendError:
                        log = output / 'render.log'
                        if log.exists():
                            (config.storage_dir / 'livescene-render-error.log').write_text(
                                log.read_text(errors='replace')[-32768:])
                        raise
                    result = json.loads((output / 'render.json').read_text())
                    png = (output / 'render.png').read_bytes()
                    if (len(png) > 2*1024*1024 or result['checkpoint_sha256'] != model['checkpoint_sha256']
                            or result['request_id'] != request.request_id or result['device'] != 'cuda'):
                        raise ValueError('invalid renderer output')
                    with Image.open(output / 'render.png') as image:
                        if (image.format != 'PNG' or image.width > request.max_width or image.height > 1280
                                or image.size != (result['width'], result['height'])):
                            raise ValueError('invalid render image')
                        image.verify()
                    interaction = {}
                    if request.include_interaction:
                        mask = (output / 'objects.png').read_bytes()
                        if len(mask) > 2*1024*1024:
                            raise ValueError('invalid object image size')
                        with Image.open(output / 'objects.png') as image:
                            if (image.format != 'PNG' or image.mode != 'L'
                                    or image.size != (result['width'], result['height'])
                                    or image.getextrema()[1] > 1):
                                raise ValueError('invalid object map')
                        interaction = {'interaction': {'encoding': 'object_id_png',
                            'objects': [item.model_dump() for item in metadata.objects],
                            'size_bytes': len(mask), 'sha256': hashlib.sha256(mask).hexdigest(),
                            'image_base64': base64.b64encode(mask).decode('ascii')}}
                    return {**result, **interaction, 'schema_version': 1, 'model_id': request.model_id,
                            'site_id': request.site_id, 'gateway_id': request.gateway_id, 'cage_id': request.cage_id,
                            'source_kind': model['source_kind'], 'quality_status': model['quality_status'],
                            'field_validated': False, 'hardware_execution_allowed': False,
                            'media_type': 'image/png', 'size_bytes': len(png),
                            'sha256': hashlib.sha256(png).hexdigest(),
                            'image_base64': base64.b64encode(png).decode('ascii')}
        except (OSError, ValueError, KeyError, BackendError, subprocess.TimeoutExpired):
            raise error(503, 'livescene_unavailable', 'GPU render failed validation or timed out') from None
