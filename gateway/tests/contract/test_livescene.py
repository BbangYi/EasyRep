"""Synthetic HTTP contract checks, not reconstruction quality measurements."""
import base64
import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

import httpx
from PIL import Image
from pydantic import ValidationError

from habitat.compute.config import ComputeConfig
from habitat.compute.errors import ComputeFailure
from habitat.compute.http_client import HTTPComputeClient
from habitat.compute.livescene import RenderRequest, SceneCatalog, render, render_result


class LiveSceneContract(unittest.TestCase):
    def setUp(self):
        image = io.BytesIO()
        Image.new('RGB', (8, 8)).save(image, format='PNG')
        png = image.getvalue()
        request = {'schema_version': 1, 'request_id': 'request-test', 'site_id': 'STORE-001',
                   'gateway_id': 'PI-001', 'cage_id': 'CAGE-001', 'model_id': 'reference-door',
                   'camera_index': 0, 'state': None, 'max_width': 320}
        result = {k: v for k, v in request.items() if k != 'max_width'}
        result.update(source_kind='reference_dataset', quality_status='experimental',
            field_validated=False, hardware_execution_allowed=False, checkpoint_sha256='a'*64,
            step=30000, width=8, height=8, device='cuda', gpu_name='SYNTHETIC TEST',
            elapsed_seconds=1., media_type='image/png', size_bytes=len(png),
            sha256=hashlib.sha256(png).hexdigest(), image_base64=base64.b64encode(png).decode())
        config = ComputeConfig(enabled=True, base_url='http://127.0.0.1:8100', timeout_s=60)
        self.png, self.request, self.result = png, request, result
        self.client = HTTPComputeClient(config, 'test-only', transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=self.result)))
        self.addCleanup(self.client.close)

    def test_png_integrity_identity_and_existing_files(self):
        png, request, result, client = self.png, self.request, self.result, self.client
        self.assertFalse(RenderRequest.model_validate(request).include_interaction)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'render.png'
            for key, value in [('sha256', 'b'*64), ('request_id', 'wrong'), ('width', 9),
                               ('device', 'cpu'), ('image_base64', '!')]:
                original = result[key]
                result[key] = value
                with self.assertRaises(ComputeFailure):
                    render(client, request, destination)
                self.assertFalse(destination.exists())
                result[key] = original
            receipt = render(client, request, destination)
            self.assertEqual(destination.read_bytes(), png)
            self.assertNotIn('image_base64', receipt)
            self.assertNotIn('interaction', receipt)
            with self.assertRaises(FileExistsError):
                render(client, request, destination)
            self.assertEqual(destination.read_bytes(), png)

    def test_selection_map_integrity_labels_and_request_agreement(self):
        request = {**self.request, 'include_interaction': True}

        def selection(mode='L', size=(8, 8), label=1):
            stream = io.BytesIO()
            Image.new(mode, size, label).save(stream, format='PNG')
            data = stream.getvalue()
            return {'encoding': 'object_id_png', 'objects': [{'object_id': 1, 'label': 'Door'}],
                    'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                    'image_base64': base64.b64encode(data).decode()}

        valid = selection()
        cases = [None, {**valid, 'image_base64': '!'}, {**valid, 'sha256': 'b'*64},
                 {**valid, 'size_bytes': valid['size_bytes'] + 1}, selection(size=(7, 8)),
                 selection(mode='RGB'), selection(label=2),
                 {**valid, 'objects': [{'object_id': 2, 'label': 'Unregistered'}]}]
        for index, invalid in enumerate(cases):
            with self.subTest(case=index):
                self.result['interaction'] = invalid
                with self.assertRaises(ComputeFailure):
                    render_result(self.client, request)
        self.result['interaction'] = valid
        result = render_result(self.client, request)
        self.assertEqual(result.interaction.objects[0].object_id, 1)
        self.assertFalse(result.hardware_execution_allowed)
        with self.assertRaises(ComputeFailure):
            render_result(self.client, self.request)

    def test_catalog_rejects_duplicate_identity_and_unknown_metadata(self):
        model = {'model_id': 'reference-door', 'site_id': 'STORE-001', 'gateway_id': 'PI-001',
                 'cage_id': 'CAGE-001', 'source_kind': 'reference_dataset', 'camera_count': 35,
                 'quality_status': 'experimental', 'checkpoint_sha256': 'a'*64,
                 'objects': [{'object_id': 1, 'label': 'Door'}]}
        catalog = SceneCatalog.model_validate({'models': [model]})
        self.assertFalse(catalog.field_validated)
        self.assertIsNone(catalog.models[0].geometry_revision)
        for invalid in ([model, copy.deepcopy(model)], [{**model, 'config': '/private/model.yml'}],
                        [{**model, 'objects': [{'object_id': 2, 'label': 'Unknown'}]}]):
            with self.subTest(models=invalid), self.assertRaises(ValidationError):
                SceneCatalog.model_validate({'models': invalid})


if __name__ == '__main__':
    unittest.main()
