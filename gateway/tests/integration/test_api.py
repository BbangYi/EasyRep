"""Real loopback HTTP contract tests; all images and backend results are SYNTHETIC.

These tests prove API behavior, not CUDA, COLMAP, reconstruction quality or Pi
connectivity. Run: python -m unittest discover -s tests/integration -v
"""

import copy
import base64
import errno
import hashlib
from http.client import HTTPResponse
import io
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image
import uvicorn

from habitat.gpu.api import create_app
from habitat.gpu.backend import BackendError
from habitat.gpu.config import Config


API = "/v1/gpu"
SCHEMAS = Path(__file__).resolve().parents[2] / "configs/schemas/compute-v1"
PROPERTIES = "x y z f_dc_0 f_dc_1 f_dc_2 opacity scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3".split()
SYNTHETIC_PLY = (
    "ply\nformat ascii 1.0\ncomment SYNTHETIC API TEST ONLY\nelement vertex 1\n"
    + "".join(f"property float {name}\n" for name in PROPERTIES)
    + "end_header\n0 0 0 0 0 0 0 -2 -2 -2 1 0 0 0\n"
).encode("ascii")


class SyntheticBackend:
    """Test-only injection; the ready flag deliberately bypasses real GPU probing."""

    def __init__(self, mode="success", backend="splatfacto", ready=True):
        self.mode, self.backend, self.ready = mode, backend, ready
        self.calls = 0

    def health(self):
        return {
            "backend": self.backend,
            "gpu": {"name": "SYNTHETIC TEST ONLY", "cuda_available": self.ready,
                    "vram_total_bytes": 0, "reconstruction_ready": self.ready},
        }

    def run(self, images_dir, work_dir, stage, cancel):
        self.calls += 1
        stage("colmap")
        stage("training")
        if self.mode == "block":
            cancel.wait(30)
            raise BackendError("interrupted", "Synthetic test interrupted.")
        if self.mode in {"gpu_out_of_memory", "gpu_unavailable", "timeout", "subprocess_failed"}:
            raise BackendError(self.mode, "Injected synthetic backend failure.")
        stage("exporting")
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / "synthetic-api-test.ply"
        path.write_bytes(b"not a Gaussian PLY" if self.mode == "invalid_ply" else SYNTHETIC_PLY)
        return path, {"backend": "synthetic_test_only", "backend_version": "test",
                      "preset": {"name": "preview", "iterations": 0},
                      "input_image_count": len(list(images_dir.iterdir())),
                      "coordinate_system": "synthetic; no physical scale"}


def bound_socket():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock


def crash_server(config, connection):
    """Child process killed by the persistence test, with no graceful shutdown."""
    sock = bound_socket()
    connection.send(sock.getsockname()[1])
    connection.close()
    server = uvicorn.Server(uvicorn.Config(create_app(config, backend=SyntheticBackend("block")),
                                           log_level="critical", access_log=False))
    server.run(sockets=[sock])


def hold_reconstruction_lock(path, connection):
    """Independent process/FD, like a native viewer holding the shared GPU slot."""
    import fcntl
    try:
        with open(path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            connection.send("locked")
            connection.recv()
    finally:
        connection.close()


class LiveServer:
    def __init__(self, config, backend):
        self.app = create_app(config, backend=backend)
        self.sock = bound_socket()
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="error", access_log=False,
                                                   timeout_graceful_shutdown=3))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.close()
                raise RuntimeError("Test HTTP server did not start")
            time.sleep(0.01)

    def close(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()
        if self.thread.is_alive():
            raise RuntimeError("Test HTTP server did not stop")


class APIHarness(unittest.TestCase):
    def livescene_fixture(self):
        root = Path(self.directory.name)
        model_config = root / 'trusted.yml'
        model_config.write_text('synthetic API test; never loaded by torch')
        checkpoint_hash = 'a'*64
        model = {'model_id': 'reference-door', 'site_id': 'STORE-001', 'gateway_id': 'PI-001',
                 'cage_id': 'CAGE-001', 'config': str(model_config),
                 'config_sha256': hashlib.sha256(model_config.read_bytes()).hexdigest(),
                 'checkpoint_sha256': checkpoint_hash, 'checkpoint_step': 30000, 'camera_count': 35,
                 'source_kind': 'reference_dataset', 'quality_status': 'experimental'}
        registry = root / 'models.json'
        registry.write_text(json.dumps({'models': [model]}))
        lock = root / 'reconstruction.lock'
        self.config.backend['livescene'] = {'manifest': str(registry), 'lock_file': str(lock), 'python': 'test-only'}
        request = {'schema_version': 1, 'request_id': 'test', 'site_id': 'STORE-001',
                   'gateway_id': 'PI-001', 'cage_id': 'CAGE-001', 'model_id': 'reference-door',
                   'camera_index': 0, 'state': None, 'max_width': 320}
        return model_config, model, registry, lock, request

    def test_livescene_scope_lock_and_verified_render(self):
        import fcntl
        model_config, model, registry, lock, request = self.livescene_fixture()
        checkpoint_hash = model['checkpoint_sha256']
        backend = SyntheticBackend()
        backend.env = {}
        live, client = self.start(backend)
        health = self.checked(client.get('/v1/livescene/health'), 200)
        self.assertEqual(health['models'][0]['model_id'], 'reference-door')
        self.assertFalse(health['rgb_training_configured'])
        for change, status in [({'cage_id': 'CAGE-OTHER'}, 403), ({'model_id': '../bad'}, 422),
                               ({'model_id': 'unknown'}, 404), ({'camera_index': 35}, 422),
                               ({'max_width': 4000}, 422), ({'state': 1.5}, 422)]:
            self.checked(client.post('/v1/livescene/render', json={**request, **change}), status)
        with lock.open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.checked(client.post('/v1/livescene/render', json=request), 429)

        def fake_worker(args, work, phase, cancel, measurements):
            output = Path(args[3])
            (output / 'render.png').write_bytes(self.image)
            (output / 'render.json').write_text(json.dumps({'request_id': 'test',
                'checkpoint_sha256': checkpoint_hash, 'device': 'cuda', 'width': 8, 'height': 8}))
        with patch('habitat.gpu.livescene_api.Backend._command', side_effect=BackendError('timeout', 'test only')):
            self.checked(client.post('/v1/livescene/render', json=request), 503)
        with patch('habitat.gpu.livescene_api.Backend._command', side_effect=fake_worker):
            result = self.checked(client.post('/v1/livescene/render', json=request), 200)
        self.assertEqual(result['sha256'], hashlib.sha256(self.image).hexdigest())
        self.assertFalse(result['field_validated'])
        self.assertEqual(result['source_kind'], 'reference_dataset')
        self.assertNotIn('interaction', result)
        interactive = {**request, 'include_interaction': True}
        self.checked(client.post('/v1/livescene/render', json=interactive), 422)
        model['objects'] = [{'object_id': 1, 'label': 'Door'}]
        registry.write_text(json.dumps({'models': [model]}))

        def interaction_worker(*args):
            fake_worker(*args)
            if mask is not None:
                (Path(args[0][3]) / 'objects.png').write_bytes(mask)

        masks = [None, b'not a PNG']
        for mode, size, label in [('L', (7, 8), 1), ('RGB', (8, 8), 1),
                                  ('L', (8, 8), 2), ('L', (8, 8), 1)]:
            stream = io.BytesIO()
            Image.new(mode, size, label).save(stream, format='PNG')
            masks.append(stream.getvalue())
        with patch('habitat.gpu.livescene_api.Backend._command', side_effect=interaction_worker):
            for index, mask in enumerate(masks):
                with self.subTest(mask=index):
                    result = self.checked(client.post('/v1/livescene/render', json=interactive),
                                          200 if index == len(masks) - 1 else 503)
        self.assertEqual(base64.b64decode(result['interaction']['image_base64']), masks[-1])
        self.assertEqual(result['interaction']['sha256'], hashlib.sha256(masks[-1]).hexdigest())
        self.assertEqual(result['interaction']['objects'][0]['object_id'], 1)
        self.assertFalse(result['hardware_execution_allowed'])
        model_config.write_text('changed')
        self.checked(client.post('/v1/livescene/render', json=request), 503)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="habitatos-api-test-")
        self.addCleanup(self.directory.cleanup)
        self.token, self.other_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.config = Config(storage_dir=Path(self.directory.name), credentials=[
            {"site_id": "STORE-001", "gateway_id": "PI-001", "cage_ids": ["CAGE-001"],
             "token_env": "HABITAT_TEST_TOKEN", "token": self.token},
            {"site_id": "STORE-002", "gateway_id": "PI-002", "cage_ids": ["CAGE-002"],
             "token_env": "HABITAT_OTHER_TEST_TOKEN", "token": self.other_token},
        ])
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (120, 80, 40)).save(image, format="PNG")
        self.image = image.getvalue()

    def start(self, backend=None):
        live = LiveServer(self.config, backend or SyntheticBackend())
        self.addCleanup(live.close)
        client = httpx.Client(base_url=f"http://127.0.0.1:{live.port}", trust_env=False,
                             timeout=10, follow_redirects=False,
                             headers={"Authorization": f"Bearer {self.token}"})
        self.addCleanup(client.close)
        return live, client

    def checked(self, response, status, schema=None):
        self.assertEqual(response.status_code, status, response.text[:500])
        body = response.json()
        if schema:
            definition = json.loads((SCHEMAS / f"{schema}.schema.json").read_text(encoding="utf-8"))
            Draft202012Validator(definition, format_checker=FormatChecker()).validate(body)
        return body

    def error(self, response, status, code=None):
        body = self.checked(response, status)
        self.assertIsInstance(body["detail"]["code"], str)
        self.assertIsInstance(body["detail"]["message"], str)
        if code:
            self.assertEqual(body["detail"]["code"], code)
        self.assertNotIn(self.token, response.text)
        self.assertNotIn(self.directory.name, response.text)
        return body

    def manifest(self, content=None):
        content = self.image if content is None else content
        return {"schema_version": 1, "capture_id": str(uuid4()), "site_id": "STORE-001",
                "gateway_id": "PI-001", "cage_id": "CAGE-001", "geometry_revision": 7,
                "placement_revision": 3, "captured_at": "2026-09-20T00:00:00+00:00",
                "capture_method": "multiview_rgb", "files": [
                    {"file_id": str(uuid4()), "name": f"synthetic-{n}.png", "size_bytes": len(content),
                     "sha256": hashlib.sha256(content).hexdigest(), "captured_at": "2026-09-20T00:00:00+00:00"}
                    for n in range(3)]}

    def request(self, manifest):
        return {"schema_version": 1, "job_id": str(uuid4()), "capture_id": manifest["capture_id"],
                "site_id": manifest["site_id"], "gateway_id": manifest["gateway_id"],
                "cage_id": manifest["cage_id"], "kind": "3dgs", "preset": "preview"}

    def capture_path(self, manifest):
        return f"{API}/captures/{manifest['capture_id']}"

    def file_path(self, manifest, index=0):
        return f"{self.capture_path(manifest)}/files/{manifest['files'][index]['file_id']}"

    def partition(self, body, manifest):
        verified, missing = body["verified_file_ids"], body["missing_file_ids"]
        self.assertEqual(len(verified), len(set(verified)))
        self.assertEqual(len(missing), len(set(missing)))
        self.assertFalse(set(verified) & set(missing))
        self.assertEqual(set(verified) | set(missing), {f["file_id"] for f in manifest["files"]})
        self.assertEqual(body["status"], "uploading" if missing else "ready")

    def upload(self, client, manifest=None):
        manifest = manifest or self.manifest()
        body = self.checked(client.post(f"{API}/captures", json=manifest), 200, "CaptureStatus")
        self.partition(body, manifest)
        for index, file in enumerate(manifest["files"]):
            receipt = self.checked(client.put(self.file_path(manifest, index), content=self.image,
                                   headers={"Content-Type": "application/octet-stream"}), 200, "FileReceipt")
            self.assertEqual(receipt["file_id"], file["file_id"])
            self.assertEqual(receipt["sha256"], file["sha256"])
            body = self.checked(client.get(self.capture_path(manifest)), 200, "CaptureStatus")
            self.partition(body, manifest)
        return manifest

    def wait_job(self, client, job_id, states=("succeeded", "failed", "interrupted")):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            body = self.checked(client.get(f"{API}/jobs/{job_id}"), 200, "JobStatus")
            if body["status"] in states:
                return body
            time.sleep(0.03)
        self.fail(f"Job did not reach {states}; last status={body['status']}/{body['stage']}")


class APIIntegrationTests(APIHarness):
    @unittest.skipUnless(os.name == 'posix', 'GPU shared flock is a Linux/WSL contract')
    def test_worker_waits_for_external_lock_without_claiming_and_stops_while_waiting(self):
        for stop_waiting in (False, True):
            with self.subTest(stop_waiting=stop_waiting):
                # A non-default location proves API config and worker share the same path.
                lock_path = Path(self.directory.name) / 'native-viewer-resource.lock'
                self.config.backend['livescene'] = {'lock_file': str(lock_path)}
                context = multiprocessing.get_context('spawn')
                parent, child = context.Pipe()
                holder = context.Process(target=hold_reconstruction_lock, args=(str(lock_path), child))
                holder.start()
                child.close()
                live = None
                try:
                    self.assertTrue(parent.poll(10))
                    self.assertEqual(parent.recv(), 'locked')
                    backend = SyntheticBackend()
                    live, client = self.start(backend)
                    manifest = self.upload(client)
                    request = self.request(manifest)
                    store, worker = live.app.state.store, live.app.state.worker
                    originals = {str(store.file_path(manifest['capture_id'], item)): item['sha256']
                                 for item in manifest['files']}
                    with patch.object(store, 'next_job', wraps=store.next_job) as claim:
                        self.checked(client.post(f'{API}/jobs', json=request), 202)
                        threading.Event().wait(.35)
                        claim.assert_not_called()
                        self.assertEqual(backend.calls, 0)
                        self.assertEqual(store.job(request['job_id'])['status'], 'queued')
                        if stop_waiting:
                            started = time.monotonic()
                            worker.stop()
                            self.assertLess(time.monotonic() - started, 2)
                        parent.send('release')
                        holder.join(5)
                        self.assertEqual(holder.exitcode, 0)
                        if stop_waiting:
                            threading.Event().wait(.25)
                            claim.assert_not_called()
                            self.assertEqual(backend.calls, 0)
                            self.assertEqual(store.job(request['job_id'])['status'], 'queued')
                        else:
                            self.assertEqual(self.wait_job(client, request['job_id'])['status'], 'succeeded')
                            self.assertEqual(backend.calls, 1)
                    self.assertEqual({name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                                      for name in originals}, originals)
                finally:
                    parent.close()
                    if holder.is_alive():
                        holder.terminate()
                    holder.join(5)
                    if live is not None:
                        live.close()

    @unittest.skipUnless(os.name == 'posix', 'GPU shared flock is a Linux/WSL contract')
    def test_job_excludes_livescene_and_unlocks_on_success_failure_or_cancel(self):
        for outcome in ('success', 'timeout', 'cancel'):
            with self.subTest(outcome=outcome):
                _, model, _, _, request = self.livescene_fixture()
                backend = SyntheticBackend('success' if outcome == 'cancel' else outcome)
                entered, release = threading.Event(), threading.Event()
                original_run = backend.run

                def controlled(*args):
                    entered.set()
                    while not release.wait(.02):
                        if args[-1].is_set():
                            raise BackendError('interrupted', 'Synthetic worker cancelled')
                    return original_run(*args)

                with patch.object(backend, 'run', side_effect=controlled):
                    live, client = self.start(backend)
                    try:
                        manifest = self.upload(client)
                        job_request = self.request(manifest)
                        self.checked(client.post(f'{API}/jobs', json=job_request), 202)
                        self.assertTrue(entered.wait(5))
                        self.error(client.post('/v1/livescene/render', json=request), 429, 'reconstruction_busy')
                        self.checked(client.get('/v1/environment/health'), 200)
                        if outcome == 'cancel':
                            live.app.state.worker.stop()
                        else:
                            release.set()
                        status = self.wait_job(client, job_request['job_id'])
                        self.assertEqual(status['status'], {'success':'succeeded', 'timeout':'failed', 'cancel':'interrupted'}[outcome])
                        # Stop the idle worker before checking that no FD remains locked.
                        live.app.state.worker.stop()

                        def fake_renderer(args, work, phase, cancel, measurements):
                            output = Path(args[3])
                            (output / 'render.png').write_bytes(self.image)
                            (output / 'render.json').write_text(json.dumps({'request_id':'test',
                                'checkpoint_sha256':model['checkpoint_sha256'], 'device':'cuda', 'width':8, 'height':8}))

                        with patch('habitat.gpu.livescene_api.Backend._command', side_effect=fake_renderer):
                            self.checked(client.post('/v1/livescene/render', json=request), 200)
                        store = live.app.state.store
                        for item in manifest['files']:
                            self.assertEqual(hashlib.sha256(store.file_path(manifest['capture_id'], item).read_bytes()).hexdigest(), item['sha256'])
                    finally:
                        release.set()
                        live.close()

    def test_livescene_catalog_scope_privacy_and_invalid_registry(self):
        root = Path(self.directory.name)
        model = {'model_id': 'reference-door', 'site_id': 'STORE-001', 'gateway_id': 'PI-001',
                 'cage_id': 'CAGE-001', 'source_kind': 'reference_dataset', 'camera_count': 35,
                 'quality_status': 'experimental', 'checkpoint_sha256': 'a'*64,
                 'config': str(root / 'private.yml'), 'unknown_private_metadata': 'not public',
                 'objects': [{'object_id': 1, 'label': 'Door'}]}
        other = {**model, 'model_id': 'other-store', 'site_id': 'STORE-002',
                 'gateway_id': 'PI-002', 'cage_id': 'CAGE-002'}
        registry = root / 'models.json'
        registry.write_text(json.dumps({'models': [model, other]}))
        self.config.backend['livescene'] = {'manifest': str(registry)}
        _, client = self.start()
        path = '/v1/livescene/models'
        for authorization in ('', 'Bearer invalid-test-credential'):
            self.error(client.get(path, headers={'Authorization': authorization}), 401)
        response = client.get(path)
        catalog = self.checked(response, 200)
        self.assertEqual([item['model_id'] for item in catalog['models']], ['reference-door'])
        self.assertEqual(catalog['models'][0]['cage_id'], 'CAGE-001')
        self.assertIsNone(catalog['models'][0]['geometry_revision'])
        self.assertFalse(catalog['hardware_execution_allowed'])
        for private in (self.directory.name, 'config', 'unknown_private_metadata', 'not public'):
            self.assertNotIn(private, response.text)
        other_catalog = self.checked(client.get(path, headers={
            'Authorization': f'Bearer {self.other_token}'}), 200)
        self.assertEqual([item['model_id'] for item in other_catalog['models']], ['other-store'])
        for invalid in ([model, model], [{**model, 'camera_count': 0}],
                        [{**model, 'objects': [{'object_id': 2, 'label': 'Unknown'}]}]):
            with self.subTest(registry=invalid):
                registry.write_text(json.dumps({'models': invalid}))
                self.error(client.get(path), 503, 'livescene_unavailable')
        registry.write_text('not json')
        self.error(client.get(path), 503, 'livescene_unavailable')
        registry.unlink()
        self.error(client.get(path), 503, 'livescene_unavailable')

    def environment_fixture(self, schema=1, mode='simulation'):
        now = time.time()
        request = {'schema_version':schema, 'request_id':'environment-test', 'mode':mode,
                   'site_id':'STORE-001', 'gateway_id':'PI-001', 'cage_id':'CAGE-001',
                   'sample_times':[now-(29-i)*60 for i in range(30)],
                   'history':[[25.,50.,26.,24.,0.] for _ in range(30)],
                   'humidity_band':[60.,70.], 'temperature_band':[23.,29.],
                   'water_ok':True, 'leak':False}
        result = {'schema_version':schema,
                  **{key:request[key] for key in ('request_id','site_id','gateway_id','cage_id')},
                  'mode':'SIMULATION_ONLY' if mode == 'simulation' else 'SHADOW_ONLY',
                  'training_source':'SYNTHETIC_ONLY', 'field_validated':False,
                  'hardware_execution_allowed':False, 'model_id':'synthetic-test',
                  'device':'cuda', 'gpu':'SYNTHETIC TEST ONLY',
                  'measurement_end_epoch':now, 'generated_at_epoch':now, 'expires_at_epoch':now+30,
                  'prediction_condition':'synthetic API fixture; not CUDA execution',
                  'predictions':[{'horizon_minutes':h, 'air_C':25., 'humidity_pct':60.,
                                  'surface_hot_C':26., 'surface_cool_C':24.} for h in (5,10,30,60)],
                  'misting_proposal':{'pulse_seconds':0., 'decision':'interlock',
                                      'cooldown_minutes':3., 'max_pulse_seconds':3.},
                  'inference_ms':1.}
        if schema == 2:
            timing = {'timing_mode':'r15_request_fixture',
                      'timing_profile':'r15_esp20_pico_window1ms_phase0_v1'}
            request.update(timing)
            holds, runs = [0]*60, [0.]*60
            holds[0], runs[0], holds[6], runs[6] = 2000, .959, 4500, 3.
            result.update(**timing, selected_plan={'request_hold_ms':holds, 'expected_virtual_run_s':runs})
            result['misting_proposal'].update(pulse_seconds=.959, decision='learned_forecast',
                                             request_hold_ms=2000, expected_virtual_run_s=.959)
        return request, result

    def test_environment_contract_and_shutdown(self):
        request, result = self.environment_fixture()
        with patch('habitat.gpu.environment_api.ResidentPredictor') as factory:
            predictor = factory.return_value
            predictor.request.return_value = result
            live, client = self.start()
            self.checked(client.post('/v1/environment/predict', json={**request,'cage_id':'OTHER'}), 403)
            self.checked(client.post('/v1/environment/predict', json={**request,'mode':'real'}), 422)
            self.checked(client.post('/v1/environment/predict', json={**request,'history':[[0.]*6]*30}), 422)
            predictor.request.assert_not_called()
            self.checked(client.post('/v1/environment/predict', json=request), 200)
            predictor.request.return_value = {'error':'invalid_prediction_input'}
            self.checked(client.post('/v1/environment/predict', json=request), 422)
            predictor.close.assert_not_called()
            predictor.request.side_effect = TimeoutError('synthetic timeout')
            self.checked(client.post('/v1/environment/predict', json=request), 503)
            predictor.close.assert_called_once()
            predictor.request.side_effect = None
            predictor.request.return_value = result
            self.checked(client.post('/v1/environment/predict', json=request), 200)
            live.close()
            self.assertEqual(predictor.close.call_count, 2)

    def test_environment_response_preserves_raw_schema1_and_schema2_contracts(self):
        with patch('habitat.gpu.environment_api.ResidentPredictor') as factory:
            predictor = factory.return_value
            _, client = self.start()
            for schema in (1, 2):
                for mode in ('simulation', 'shadow'):
                    with self.subTest(schema=schema, mode=mode):
                        request, result = self.environment_fixture(schema, mode)
                        predictor.request.return_value = result
                        response = self.checked(client.post('/v1/environment/predict', json=request), 200)
                        self.assertEqual(response, result)
                        if schema == 1:
                            self.assertNotIn('timing_mode', response)
                            self.assertNotIn('timing_profile', response)
                            self.assertNotIn('selected_plan', response)
                            self.assertNotIn('request_hold_ms', response['misting_proposal'])
            predictor.close.assert_not_called()

    def test_environment_api_rejects_invalid_worker_contract_and_closes_predictor(self):
        missing = object()
        cases = [
            (('selected_plan',), missing),
            (('selected_plan','request_hold_ms'), [0]*59),
            (('selected_plan','expected_virtual_run_s'), [0.]*59),
            (('selected_plan','request_hold_ms',0), 2000.),
            (('selected_plan','request_hold_ms',0), True),
            (('selected_plan','request_hold_ms',6), 6000),
            (('selected_plan','expected_virtual_run_s',6), 2.959),
            (('selected_plan','expected_virtual_run_s',6), 3.1),
            (('selected_plan','expected_virtual_run_s',6), float('nan')),
            (('misting_proposal','request_hold_ms'), missing),
            (('misting_proposal','request_hold_ms'), 3000),
            (('misting_proposal','expected_virtual_run_s'), 1.959),
            (('misting_proposal','pulse_seconds'), 2.),
            (('misting_proposal','max_pulse_seconds'), 2.),
            (('timing_profile',), 'unknown'),
            (('schema_version',), True),
            (('schema_version',), 2.),
            (('request_id',), 'other-request'),
            (('site_id',), 'STORE-002'),
            (('gateway_id',), 'PI-002'),
            (('cage_id',), 'CAGE-002'),
            (('hardware_execution_allowed',), missing),
            (('field_validated',), missing),
            (('hardware_execution_allowed',), True),
            (('field_validated',), True),
            (('training_source',), 'FIELD_VALIDATED'),
            (('mode',), 'SHADOW_ONLY'),
            (('device',), 'cpu'),
            (('expires_at_epoch',), time.time()-1),
            (('measurement_end_epoch',), 0.),
            (('predictions',0,'horizon_minutes'), 10),
        ]
        with patch('habitat.gpu.environment_api.ResidentPredictor') as factory:
            predictor = factory.return_value
            _, client = self.start()
            for path, value in cases:
                with self.subTest(path=path, value=value):
                    request, result = self.environment_fixture(2)
                    target = result
                    for key in path[:-1]:
                        target = target[key]
                    if value is missing:
                        target.pop(path[-1])
                    else:
                        target[path[-1]] = value
                    predictor.request.return_value = result
                    before = predictor.close.call_count
                    self.error(client.post('/v1/environment/predict', json=request), 503, 'prediction_unavailable')
                    self.assertEqual(predictor.close.call_count, before+1)
            request, _ = self.environment_fixture(2)
            _, legacy = self.environment_fixture(1)
            for result in (legacy, None, {'error':'prediction_unavailable'}):
                with self.subTest(result=result):
                    predictor.request.return_value = result
                    before = predictor.close.call_count
                    self.error(client.post('/v1/environment/predict', json=request), 503, 'prediction_unavailable')
                    self.assertEqual(predictor.close.call_count, before+1)
            # Every rejection releases the route gate, and the next valid response can recover.
            request, result = self.environment_fixture(2)
            predictor.request.return_value = result
            self.assertEqual(self.checked(client.post('/v1/environment/predict', json=request), 200), result)

    def test_complete_http_lifecycle_and_idempotency(self):
        backend = SyntheticBackend()
        _, client = self.start(backend)
        health = self.checked(client.get(f"{API}/health"), 200, "ComputeHealth")
        self.assertEqual(health["limits"]["max_concurrent_jobs"], 1)
        manifest = self.upload(client)
        self.checked(client.post(f"{API}/captures", json=manifest), 200, "CaptureStatus")
        self.checked(client.put(self.file_path(manifest), content=self.image,
                                headers={"Content-Type": "application/octet-stream"}), 200, "FileReceipt")
        job = self.request(manifest)
        queued = self.checked(client.post(f"{API}/jobs", json=job), 202, "JobStatus")
        self.assertEqual((queued["status"], queued["stage"], queued["artifacts"], queued["error"]),
                         ("queued", "queued", [], None))
        result = self.wait_job(client, job["job_id"])
        self.assertEqual((result["status"], result["stage"]), ("succeeded", "complete"))
        for key, value in job.items():
            self.assertEqual(result[key], value)
        self.assertEqual((result["geometry_revision"], result["placement_revision"]), (7, 3))
        again = self.checked(client.post(f"{API}/jobs", json=job), 202, "JobStatus")
        self.assertEqual(again, result)
        self.assertEqual(backend.calls, 1)
        artifact = result["artifacts"][0]
        self.assertFalse(artifact["metric_scale_verified"])
        self.assertEqual(artifact["format"], "gaussian_splat_ply")
        self.assertEqual(artifact["download_path"],
                         f"{API}/jobs/{job['job_id']}/artifacts/{artifact['artifact_id']}")
        download = client.get(artifact["download_path"], headers={"Accept-Encoding": "gzip, br"})
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, SYNTHETIC_PLY)
        self.assertEqual(int(download.headers["Content-Length"]), artifact["size_bytes"])
        self.assertEqual(hashlib.sha256(download.content).hexdigest(), artifact["sha256"])
        self.assertEqual(download.headers["X-Content-SHA256"], artifact["sha256"])
        self.assertIn(download.headers.get("Content-Encoding", "identity"), ("identity",))
        conflicting = copy.deepcopy(manifest)
        conflicting["geometry_revision"] += 1
        self.error(client.post(f"{API}/captures", json=conflicting), 409, "id_conflict")
        other_capture = self.upload(client)
        self.error(client.post(f"{API}/jobs", json={**job, "capture_id": other_capture["capture_id"]}),
                   409, "id_conflict")

    def test_authentication_and_scope_on_every_endpoint(self):
        _, client = self.start()
        manifest = self.upload(client)
        job = self.request(manifest)
        self.checked(client.post(f"{API}/jobs", json=job), 202)
        result = self.wait_job(client, job["job_id"])
        artifact_path = result["artifacts"][0]["download_path"]
        requests = [("GET", f"{API}/health", {}), ("POST", f"{API}/captures", {"json": manifest}),
                    ("GET", self.capture_path(manifest), {}),
                    ("PUT", self.file_path(manifest), {"content": self.image}),
                    ("POST", f"{API}/jobs", {"json": job}),
                    ("GET", f"{API}/jobs/{job['job_id']}", {}), ("GET", artifact_path, {})]
        for method, path, kwargs in requests:
            for authorization in ("", "Bearer invalid-test-credential"):
                with self.subTest(method=method, path=path, missing=not authorization):
                    self.error(client.request(method, path, headers={"Authorization": authorization}, **kwargs), 401)
        for key, value in (("site_id", "STORE-OTHER"), ("gateway_id", "PI-OTHER"), ("cage_id", "CAGE-OTHER")):
            with self.subTest(scope=key):
                self.error(client.post(f"{API}/captures", json={**manifest, "capture_id": str(uuid4()), key: value}), 403)
                self.error(client.post(f"{API}/jobs", json={**job, "job_id": str(uuid4()), key: value}), 403)
        other = {"Authorization": f"Bearer {self.other_token}"}
        for path in (self.capture_path(manifest), f"{API}/jobs/{job['job_id']}", artifact_path):
            self.error(client.get(path, headers=other), 404)
        self.error(client.put(self.file_path(manifest), content=self.image, headers=other), 404)

    def test_missing_corrupt_and_invalid_images_remain_missing(self):
        _, client = self.start()
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        self.error(client.post(f"{API}/jobs", json=self.request(manifest)), 409, "capture_not_ready")
        wrong_hash = bytes([self.image[0] ^ 1]) + self.image[1:]
        for data in (wrong_hash, self.image[:-1]):
            self.error(client.put(self.file_path(manifest), content=data,
                                  headers={"Content-Type": "application/octet-stream"}), 422)
        body = self.checked(client.get(self.capture_path(manifest)), 200, "CaptureStatus")
        self.partition(body, manifest)
        self.assertEqual(body["verified_file_ids"], [])
        invalid = b"synthetic bytes are not a PNG"
        bad = self.manifest(invalid)
        self.checked(client.post(f"{API}/captures", json=bad), 200)
        self.error(client.put(self.file_path(bad), content=invalid,
                              headers={"Content-Type": "application/octet-stream"}), 422)
        self.error(client.put(f"{self.capture_path(manifest)}/files/{uuid4()}", content=self.image), 404)
        self.upload(client, manifest)

    def test_jpeg_upload_and_format_extension_mismatch(self):
        _, client = self.start()
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (30, 60, 90)).save(image, format="JPEG")
        self.image = image.getvalue()
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        self.error(client.put(self.file_path(manifest), content=self.image,
                              headers={"Content-Type": "application/octet-stream"}), 422)
        jpeg = self.manifest()
        for item in jpeg["files"]:
            item["name"] = item["name"].replace(".png", ".jpg")
        self.upload(client, jpeg)

    def test_truncated_tcp_upload_is_not_verified_and_can_be_retried(self):
        live, client = self.start()
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        with socket.create_connection(("127.0.0.1", live.port), timeout=3) as sock:
            request = (f"PUT {self.file_path(manifest)} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"Authorization: Bearer {self.token}\r\nContent-Type: application/octet-stream\r\n"
                       f"Content-Length: {len(self.image)}\r\nConnection: close\r\n\r\n")
            sock.sendall(request.encode("ascii") + self.image[:10])
            sock.shutdown(socket.SHUT_WR)
            sock.recv(1024)
        body = self.checked(client.get(self.capture_path(manifest)), 200, "CaptureStatus")
        self.partition(body, manifest)
        self.assertEqual(body["verified_file_ids"], [])
        self.assertEqual(list((self.config.storage_dir / "staging").iterdir()), [])
        self.upload(client, manifest)

    def test_strict_manifest_and_job_validation(self):
        _, client = self.start()
        base = self.manifest()
        changes = [{"files": base["files"][:2]}, {"files": [base["files"][0]] * 3},
                   {"captured_at": "2026-09-20T00:00:00"}, {"geometry_revision": 0},
                   {"geometry_revision": True}, {"schema_version": 2}, {"shell": "never execute"}]
        for filename in ("../escape.png", "C:\\escape.png", "sub/image.png", "image.exe"):
            files = copy.deepcopy(base["files"])
            files[0]["name"] = filename
            changes.append({"files": files})
        for change in changes:
            with self.subTest(change=next(iter(change))):
                self.error(client.post(f"{API}/captures", json={**base, **change}), 422)
        manifest = self.upload(client)
        job = self.request(manifest)
        for change in ({"preset": "arbitrary"}, {"kind": "shell"}, {"command": "never execute"}):
            self.error(client.post(f"{API}/jobs", json={**job, **change}), 422)

    def test_actual_configured_limits_are_enforced(self):
        self.config.limits.max_file_bytes = len(self.image) + 1
        self.config.limits.max_capture_bytes = len(self.image) * 3
        self.config.limits.max_files_per_capture = 3
        _, client = self.start()
        health = self.checked(client.get(f"{API}/health"), 200, "ComputeHealth")
        self.assertEqual(health["limits"], self.config.limits.model_dump())
        manifest = self.manifest()
        oversized = copy.deepcopy(manifest)
        oversized["files"][0]["size_bytes"] += 2
        self.error(client.post(f"{API}/captures", json=oversized), 413)
        too_many = copy.deepcopy(manifest)
        too_many["files"].append({**manifest["files"][0], "file_id": str(uuid4()), "name": "fourth.png"})
        self.error(client.post(f"{API}/captures", json=too_many), 413)
        aggregate = copy.deepcopy(manifest)
        aggregate["files"][0]["size_bytes"] += 1
        self.error(client.post(f"{API}/captures", json=aggregate), 413)
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        self.error(client.put(self.file_path(manifest), content=self.image + b"extra",
                              headers={"Content-Type": "application/octet-stream"}), 413)

    def test_chunked_bodies_cannot_bypass_upload_or_json_limits(self):
        self.config.limits.max_file_bytes = len(self.image) + 1
        _, client = self.start()
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        self.error(client.put(self.file_path(manifest), content=iter((self.image, b"extra")),
                              headers={"Content-Type": "application/octet-stream"}), 413)
        body = self.checked(client.get(self.capture_path(manifest)), 200, "CaptureStatus")
        self.partition(body, manifest)
        self.assertEqual(body["verified_file_ids"], [])
        self.assertEqual(list((self.config.storage_dir / "staging").iterdir()), [])
        self.error(client.post(f"{API}/captures", content=iter((b" " * (1024 * 1024), b"{}")),
                               headers={"Content-Type": "application/json"}), 413)
        self.upload(client, manifest)

    def test_stalled_json_post_reaches_receive_deadline(self):
        with patch("habitat.gpu.api.RequestBoundary.JSON_BODY_TIMEOUT_SECONDS", 0.1):
            live, client = self.start()
            with socket.create_connection(("127.0.0.1", live.port), timeout=3) as sock:
                request = (f"POST {API}/captures HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                           f"Authorization: Bearer {self.token}\r\nContent-Type: application/json\r\n"
                           "Content-Length: 100\r\nConnection: close\r\n\r\n{")
                sock.sendall(request.encode("ascii"))
                with HTTPResponse(sock) as response:
                    response.begin()
                    self.assertEqual(response.status, 503)
                    body = response.read().decode("utf-8")
                    self.assertEqual(json.loads(body)["detail"]["code"], "request_timeout")
                    self.assertTrue(self.token not in body, "Timeout response disclosed a credential")
            self.checked(client.get(f"{API}/health"), 200, "ComputeHealth")

    def test_mock_and_unconfigured_backends_never_accept_jobs(self):
        backend = SyntheticBackend(backend="mock", ready=False)
        _, client = self.start(backend)
        for backend_name in ("mock", "not_configured"):
            with self.subTest(backend=backend_name):
                backend.backend = backend_name
                health = self.checked(client.get(f"{API}/health"), 200, "ComputeHealth")
                self.assertEqual((health["status"], health["backend"]), ("degraded", backend_name))
                self.assertFalse(health["gpu"]["reconstruction_ready"])
                manifest = self.upload(client)
                self.error(client.post(f"{API}/jobs", json=self.request(manifest)), 503, "backend_not_ready")

    def test_backend_failures_and_invalid_artifacts_never_succeed(self):
        backend = SyntheticBackend()
        _, client = self.start(backend)
        manifest = self.upload(client)
        for mode in ("gpu_out_of_memory", "gpu_unavailable", "timeout", "subprocess_failed", "invalid_ply"):
            with self.subTest(mode=mode):
                backend.mode = mode
                job = self.request(manifest)
                self.checked(client.post(f"{API}/jobs", json=job), 202, "JobStatus")
                body = self.wait_job(client, job["job_id"])
                self.assertEqual((body["status"], body["stage"], body["artifacts"]), ("failed", "failed", []))
                self.assertTrue(body["error"]["code"])
                if mode != "invalid_ply":
                    self.assertEqual(body["error"]["code"], mode)

    def test_storage_failure_is_retryable_without_verified_receipt(self):
        _, client = self.start()
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        with patch("habitat.gpu.api.os.fsync", side_effect=OSError(errno.ENOSPC, "Injected disk full")):
            self.error(client.put(self.file_path(manifest), content=self.image,
                                  headers={"Content-Type": "application/octet-stream"}), 503)
        body = self.checked(client.get(self.capture_path(manifest)), 200, "CaptureStatus")
        self.assertEqual(body["verified_file_ids"], [])
        self.upload(client, manifest)
        if os.name == "posix":
            staging = self.config.storage_dir / "staging"
            staging.rmdir()
            with tempfile.TemporaryDirectory(prefix="habitatos-outside-test-") as outside:
                marker = Path(outside) / "preserve.txt"
                marker.write_text("unrelated file", encoding="utf-8")
                staging.symlink_to(outside, target_is_directory=True)
                try:
                    self.error(client.put(self.file_path(manifest), content=self.image,
                                          headers={"Content-Type": "application/octet-stream"}), 503)
                    self.assertEqual(list(Path(outside).iterdir()), [marker])
                    self.assertEqual(marker.read_text(), "unrelated file")
                finally:
                    staging.unlink()

    def test_wall_clock_rollback_does_not_break_job_status_response(self):
        live, client = self.start(SyntheticBackend("block"))
        manifest = self.upload(client)
        job = self.request(manifest)
        self.checked(client.post(f"{API}/jobs", json=job), 202)
        before = self.wait_job(client, job["job_id"], ("running",))
        with patch("habitat.persistence.gpu.now", return_value="2000-01-01T00:00:00+00:00"):
            live.app.state.store.update_job(job["job_id"], stage="training")
        after = self.checked(client.get(f"{API}/jobs/{job['job_id']}"), 200, "JobStatus")
        self.assertGreaterEqual(after["updated_at"], before["updated_at"])

    def test_process_crash_preserves_queue_and_interrupts_running_job(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(target=crash_server, args=(self.config, child), daemon=True)
        process.start()
        child.close()

        def stop_child():
            if process.is_alive():
                process.kill()
            process.join(10)

        self.addCleanup(stop_child)
        self.addCleanup(parent.close)
        self.assertTrue(parent.poll(15), "Child HTTP server failed before publishing its port")
        port = parent.recv()
        parent.close()
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10,
                          headers={"Authorization": f"Bearer {self.token}"}) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    self.checked(client.get(f"{API}/health"), 200)
                    break
                except httpx.TransportError:
                    if time.monotonic() > deadline:
                        self.fail("Child HTTP server did not become ready")
                    time.sleep(0.03)
            manifest = self.upload(client)
            running, queued = self.request(manifest), self.request(manifest)
            self.checked(client.post(f"{API}/jobs", json=running), 202)
            self.wait_job(client, running["job_id"], ("running",))
            body = self.checked(client.post(f"{API}/jobs", json=queued), 202, "JobStatus")
            self.assertEqual((body["status"], body["stage"]), ("queued", "queued"))
            time.sleep(0.15)
            self.assertEqual(client.get(f"{API}/jobs/{queued['job_id']}").json()["status"], "queued")
            partial = self.manifest()
            self.checked(client.post(f"{API}/captures", json=partial), 200)
            stalled = socket.create_connection(("127.0.0.1", port), timeout=3)
            self.addCleanup(stalled.close)
            request = (f"PUT {self.file_path(partial)} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"Authorization: Bearer {self.token}\r\nContent-Type: application/octet-stream\r\n"
                       f"Content-Length: {len(self.image)}\r\n\r\n")
            stalled.sendall(request.encode("ascii") + self.image[:10])
            staging = self.config.storage_dir / "staging"
            deadline = time.monotonic() + 3
            while not list(staging.glob("upload-*.part")) and time.monotonic() < deadline:
                time.sleep(0.01)
            unfinished = list(staging.glob("upload-*.part"))
            self.assertEqual(len(unfinished), 1)
            (staging / "operator-note.txt").write_text("keep", encoding="utf-8")
            (staging / "unrelated.part").write_text("keep", encoding="utf-8")
            (staging / "upload-directory.part").mkdir()
            (staging / "upload-directory.part/keep.txt").write_text("keep", encoding="utf-8")
            if os.name == "posix":
                (staging / "upload-reference.part").symlink_to(staging / "operator-note.txt")
        process.kill()
        process.join(10)
        stalled.close()
        self.assertFalse(process.is_alive())
        self.assertTrue(unfinished[0].is_file(), "Killed upload unexpectedly ran its finally cleanup")
        backend = SyntheticBackend()
        _, restarted = self.start(backend)
        self.assertFalse(unfinished[0].exists())
        for preserved in ("operator-note.txt", "unrelated.part", "upload-directory.part/keep.txt"):
            self.assertEqual((staging / preserved).read_text(), "keep")
        if os.name == "posix":
            self.assertTrue((staging / "upload-reference.part").is_symlink())
        partial_status = self.checked(restarted.get(self.capture_path(partial)), 200, "CaptureStatus")
        self.partition(partial_status, partial)
        self.assertEqual(partial_status["verified_file_ids"], [])
        interrupted = self.wait_job(restarted, running["job_id"])
        self.assertEqual((interrupted["status"], interrupted["stage"]), ("interrupted", "interrupted"))
        self.assertEqual(interrupted["artifacts"], [])
        self.assertTrue(interrupted["error"]["code"])
        finished = self.wait_job(restarted, queued["job_id"])
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(backend.calls, 1)
        capture = self.checked(restarted.get(self.capture_path(manifest)), 200, "CaptureStatus")
        self.partition(capture, manifest)
        self.assertEqual(capture["status"], "ready")
        for item in manifest["files"]:
            path = self.config.storage_dir / "captures" / manifest["capture_id"] / (item["file_id"] + ".png")
            self.assertEqual(path.read_bytes(), self.image)
        replay = self.checked(restarted.post(f"{API}/jobs", json=running), 202, "JobStatus")
        self.assertEqual(replay["status"], "interrupted")
        self.assertEqual(backend.calls, 1)


if __name__ == "__main__":
    unittest.main()
