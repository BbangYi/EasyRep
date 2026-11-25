import importlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from behavior_recorder.core import RecorderError


def box(x1=0, x2=100, score=.8):
    return dict(xyxy=[x1, 0, x2, 100], confidence=score)


class Sam3RoutingTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('behavior_recorder.vision_sam3')
        except ImportError:
            self.fail('SAM3 streaming backend is not implemented')

    def choose(self, primary, auxiliary, scores):
        return self.module.choose_verified(primary, auxiliary, scores)

    def test_unverified_auxiliary_never_creates_detection(self):
        result, evidence = self.choose([], [box()], [.1])
        self.assertEqual(result, [])
        self.assertEqual(evidence['selected_auxiliary_indices'], [])

    def test_verified_geometry_replaces_matching_primary(self):
        result, evidence = self.choose([box(0, 120)], [box(10, 90, .7)], [.99])
        self.assertEqual(result, [box(10, 90, .7)])
        self.assertEqual(evidence['selected_auxiliary_indices'], [0])

    def test_second_primary_animal_survives_partial_verification(self):
        second = box(300, 400, .9)
        result, _ = self.choose([box(), second], [box(10, 90, .7), second], [.99, .1])
        self.assertEqual(result, [box(10, 90, .7), second])

    def test_merged_auxiliary_does_not_collapse_two_primary_animals(self):
        primary = [box(0, 90), box(100, 190)]
        result, _ = self.choose(primary, [box(0, 190)], [.99])
        self.assertEqual(result, primary)

    def test_two_auxiliary_candidates_matching_one_primary_abstain(self):
        primary = [box(0, 190)]
        result, _ = self.choose(primary, [box(0, 90), box(100, 190)], [.99, .99])
        self.assertEqual(result, primary)

    def test_disjoint_verified_animal_can_be_added(self):
        result, _ = self.choose([box()], [box(300, 400)], [.99])
        self.assertEqual(result, [box(300, 400), box()])

    def test_weak_primary_hints_and_inputs_are_preserved(self):
        primary = [box(score=.2)]
        result, _ = self.choose(primary, [], [])
        self.assertEqual(result, primary)
        self.assertEqual(primary[0]['confidence'], .2)

    def test_bad_scores_and_geometry_are_rejected(self):
        for auxiliary, scores in [([box()], []), ([box()], [math.nan]),
                                  ([box(100, 0)], [.99]), ([box(score=math.inf)], [.99])]:
            with self.assertRaises(RecorderError):
                self.choose([], auxiliary, scores)


class Sam3RoutingRevision2Tests(Sam3RoutingTests):
    def choose(self, primary, auxiliary, scores):
        from inspect import signature
        self.assertIn('route_revision', signature(self.module.choose_verified).parameters,
                      'Weak primary hints still veto verified animals')
        return self.module.choose_verified(primary, auxiliary, scores, route_revision=2)

    def test_multiple_weak_hints_cannot_veto_a_verified_animal(self):
        primary = [box(0, 120, .39), box(10, 100, .15)]
        auxiliary = [box(10, 90, .8)]
        result, evidence = self.choose(primary, auxiliary, [.99])
        self.assertEqual(result, auxiliary + primary)
        self.assertEqual(evidence['selected_auxiliary_indices'], [0])
        self.assertEqual(evidence['replaced_primary_indices'], [])
        self.assertEqual(primary, [box(0, 120, .39), box(10, 100, .15)])

    def test_weak_hint_does_not_create_a_second_primary_animal(self):
        weak = box(10, 100, .39)
        result, evidence = self.choose([box(0, 120), weak], [box(10, 90, .8)], [.99])
        self.assertEqual(result, [box(10, 90, .8), weak])
        self.assertEqual(evidence['replaced_primary_indices'], [0])

    def test_exact_primary_acceptance_boundary_preserves_two_animal_guard(self):
        primary = [box(0, 90, .4), box(100, 190, .4)]
        result, evidence = self.choose(primary, [box(0, 190)], [.99])
        self.assertEqual(result, primary)
        self.assertEqual(evidence['selected_auxiliary_indices'], [])

    def test_unknown_or_boolean_revision_fails(self):
        self.choose([], [], [])
        for revision in (0, 3, True, '2'):
            with self.assertRaises(RecorderError):
                self.module.choose_verified([], [], [], route_revision=revision)


class WorkerLifecycleTests(unittest.TestCase):
    def worker(self, source, directory, timeout=2):
        from behavior_recorder.vision_sam3 import NeuralWorker
        path = Path(directory) / 'worker.py'
        path.write_text(source)
        return NeuralWorker([sys.executable, '-u', str(path)], environment=dict(os.environ),
                            log=Path(directory) / 'worker.log', timeout=timeout)

    def test_persistent_requests_have_matching_ids_and_close_reaps_process(self):
        source = "import json,sys\nprint(json.dumps({'id':0,'ok':True}),flush=True)\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps(dict(r,ok=True)),flush=True)\n"
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(source, directory)
            try:
                self.assertEqual(worker.request(image_sha256='frame-a')['image_sha256'], 'frame-a')
                self.assertEqual(worker.request(image_sha256='frame-b')['id'], 2)
            finally:
                worker.close()
            self.assertIsNotNone(worker.process.poll())
            self.assertEqual(worker.process.returncode, 0, 'Normal shutdown should use EOF and allow library cleanup')
            worker.close()

    def test_stale_reply_fails_and_reaps_worker(self):
        source = "import json,sys\nprint(json.dumps({'id':0,'ok':True}),flush=True)\nfor line in sys.stdin:print(json.dumps({'id':0,'ok':True}),flush=True)\n"
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(source, directory)
            with self.assertRaisesRegex(RecorderError, 'Stale'):
                worker.request(operation='detect')
            self.assertIsNotNone(worker.process.poll())

    def test_deadline_terminates_worker_without_retry(self):
        source = "import json,sys,time\nprint(json.dumps({'id':0,'ok':True}),flush=True)\nfor line in sys.stdin:time.sleep(10)\n"
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(source, directory, timeout=1)
            with self.assertRaises(TimeoutError):
                worker.request(operation='detect')
            self.assertIsNotNone(worker.process.poll())


class FrozenWeightParkingTests(unittest.TestCase):
    def park(self, model, state=None):
        from behavior_recorder import vision_sam3
        self.assertTrue(hasattr(vision_sam3, 'park_frozen_weights'), 'Frozen CPU weights are copied back every frame')
        return vision_sam3.park_frozen_weights(model, state)

    def test_restore_reuses_cpu_storage_and_preserves_inference(self):
        import torch
        model = torch.nn.Linear(2, 1).eval().requires_grad_(False)
        model.weight.fill_(2.)
        model.bias.fill_(1.)
        state = self.park(model)
        pointer = model.weight.data_ptr()
        for _ in range(2):
            model.to('meta')
            state = self.park(model, state)
            self.assertEqual(model.weight.data_ptr(), pointer)
            self.assertEqual(model(torch.tensor([[1., 3.]])).item(), 9.)
            self.assertFalse(model.weight.requires_grad)

    def test_nonpersistent_buffers_are_preserved_when_weights_are_restored(self):
        import torch
        model = torch.nn.Linear(2, 1).eval().requires_grad_(False)
        model.register_buffer('positions', torch.tensor([7, 8]), persistent=False)
        model.weight.fill_(2.)
        state = self.park(model)
        model.to(dtype=torch.float64)
        model.weight.fill_(100.)
        self.park(model, state)
        self.assertEqual(model.weight.tolist(), [[2., 2.]])
        self.assertEqual(model.positions.tolist(), [7, 8])
        self.assertEqual(model.positions.device.type, 'cpu')

    def test_training_models_and_non_cpu_snapshots_are_rejected(self):
        import torch
        for model in (torch.nn.Linear(2, 1).eval(), torch.nn.Linear(2, 1).requires_grad_(False)):
            with self.assertRaises(RecorderError):
                self.park(model)
        model = torch.nn.Linear(2, 1).eval().requires_grad_(False)
        with self.assertRaises(RecorderError):
            self.park(model, {k: v.to('meta') for k, v in model.state_dict().items()})


class MaskContractTests(unittest.TestCase):
    def select_queries(self, outputs):
        from behavior_recorder import vision_sam3
        self.assertTrue(hasattr(vision_sam3, 'select_sam3_queries'), 'Ineligible queries still expand to original-size masks')
        return vision_sam3.select_sam3_queries(outputs)

    def outputs(self, logits=(0., -.001, 5.), presence=100.):
        from types import SimpleNamespace
        import torch
        count = len(logits)
        return SimpleNamespace(pred_logits=torch.tensor([logits], dtype=torch.float32),
                               pred_boxes=torch.arange(count * 4, dtype=torch.float32).reshape(1, count, 4),
                               pred_masks=torch.arange(count * 4, dtype=torch.float32).reshape(1, count, 2, 2),
                               presence_logits=torch.tensor([[presence]], dtype=torch.float32))

    def test_score_boundary_keeps_eligible_masks_in_original_query_order(self):
        outputs = self.outputs()
        selected, evidence = self.select_queries(outputs)
        self.assertEqual(evidence['kept_query_indices'], [0, 2])
        self.assertEqual(selected.pred_boxes.tolist(), [[[0., 1., 2., 3.], [8., 9., 10., 11.]]])
        self.assertEqual(selected.pred_masks.tolist(), [[[[0., 1.], [2., 3.]], [[8., 9.], [10., 11.]]]])
        self.assertEqual(tuple(outputs.pred_masks.shape), (1, 3, 2, 2), 'Input query arrays must not be mutated')

    def test_low_presence_removes_even_high_object_logits_without_losing_batch_axis(self):
        selected, evidence = self.select_queries(self.outputs(logits=(10., 15.), presence=-10.))
        self.assertEqual(evidence['kept_query_indices'], [])
        self.assertEqual(tuple(selected.pred_masks.shape), (1, 0, 2, 2))
        self.assertEqual(tuple(selected.pred_boxes.shape), (1, 0, 4))
        self.assertEqual(selected.presence_logits.tolist(), [[-10.]])

    def test_query_shape_and_precision_mismatches_fail_before_filtering(self):
        for field in ('pred_masks', 'pred_boxes', 'pred_logits'):
            outputs = self.outputs()
            setattr(outputs, field, getattr(outputs, field)[:, :2])
            with self.assertRaises(RecorderError):
                self.select_queries(outputs)
        outputs = self.outputs()
        outputs.pred_logits = outputs.pred_logits.half()
        with self.assertRaises(RecorderError):
            self.select_queries(outputs)

    def test_position_cache_release_drops_retained_results(self):
        from functools import lru_cache, wraps
        from behavior_recorder import vision_sam3
        self.assertTrue(hasattr(vision_sam3, 'clear_position_caches'), 'SAM3 position caches remain resident')
        def pinned_runtime_cache(function):
            func_with_cache = lru_cache(maxsize=4)(function)
            @wraps(function)
            def wrapper(*args):
                return func_with_cache(*args)
            return wrapper
        class Positions:
            @staticmethod
            @pinned_runtime_cache
            def build_sine_position_embedding(key):
                return object()
            @pinned_runtime_cache
            def _get_coords(self, key):
                return object()
            def modules(self):
                return [self, BasePositions()]
        class BasePositions:
            @staticmethod
            @pinned_runtime_cache
            def build_sine_position_embedding(key):
                return object()
        model = Positions()
        first = model.build_sine_position_embedding('mps')
        coords = model._get_coords('mps')
        self.assertIs(first, model.build_sine_position_embedding('mps'))
        self.assertEqual(vision_sam3.clear_position_caches(model), 3)
        self.assertIsNot(first, model.build_sine_position_embedding('mps'))
        self.assertIsNot(coords, model._get_coords('mps'))

    def test_other_worker_residency_reduces_active_memory_allowance(self):
        from behavior_recorder import vision_sam3
        self.assertTrue(hasattr(vision_sam3, 'memory_allowance'), 'Combined allocator budget missing')
        self.assertEqual(vision_sam3.memory_allowance([100, 200]), 3 * 1024**3 - 300)
        with self.assertRaises(RecorderError):
            vision_sam3.memory_allowance([3 * 1024**3])

    def test_empty_masks_normalize_and_mismatched_populated_masks_fail(self):
        import numpy as np
        from behavior_recorder import vision_sam3
        self.assertTrue(hasattr(vision_sam3, 'normalise_masks'), 'Original-coordinate mask validation missing')
        result = vision_sam3.normalise_masks(np.zeros((0, 1008, 1008)), 0, width=100, height=50)
        self.assertEqual(result.shape, (0, 50, 100))
        with self.assertRaises(RecorderError):
            vision_sam3.normalise_masks(np.zeros((1, 1008, 1008)), 1, width=100, height=50)
        with self.assertRaises(RecorderError):
            vision_sam3.normalise_masks(np.zeros((2, 50, 100)), 1, width=100, height=50)


class StreamingCliTests(unittest.TestCase):
    def run_clip(self, fail=False):
        import cv2
        import numpy as np
        from behavior_recorder.vision import main
        from behavior_recorder import vision_sam3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 3, (100, 100))
            self.assertTrue(writer.isOpened())
            for _ in range(3):
                writer.write(np.zeros((100, 100, 3), dtype=np.uint8))
            writer.release()
            config = dict(schema_version=1, species='lizard', sample_fps=3, confidence=.4,
                          nms_iou=.5, max_step_diagonals=.15, max_gap_seconds=.6, zones={})
            (root / 'config.json').write_text(json.dumps(config))
            closed = []

            class NeuralFixture:
                def __init__(self, directory, bundle, device, artifact_directory):
                    self.index = 0

                def predict_frame(self, frame):
                    self.index += 1
                    if fail and self.index == 2:
                        raise RuntimeError('neural failure fixture')
                    return [box(10, 30)], dict(actual_device='cpu', model='synthetic_neural_fixture')

                def close(self):
                    closed.append(True)

            card = dict(species='lizard', recipe=dict(image_size=640), model_id='fixture', status='experimental')
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(vision_sam3, 'load_sam3_bundle', return_value=(card, {})), \
                    patch.object(vision_sam3, 'Sam3HybridPredictor', NeuralFixture), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    code = main(['infer', '--backend', 'sam3-hybrid', '--model', str(root), '--video', str(source),
                                 '--config', str(root / 'config.json'), '--output', str(root / 'result'),
                                 '--device', 'cpu', '--threads', '1', '--provenance', 'synthetic_test'])
                except SystemExit:
                    self.fail('Public CLI does not expose the SAM3 backend')
            self.assertEqual(closed, [True])
            if fail:
                self.assertEqual(code, 1)
                self.assertIn('neural failure fixture', stderr.getvalue())
                self.assertEqual(json.loads((root / 'result/status.json').read_text())['state'], 'failed')
            else:
                self.assertEqual(code, 0, stderr.getvalue())
                rows = [json.loads(line) for line in (root / 'result/observations.jsonl').read_text().splitlines()]
                self.assertEqual([r['frame_index'] for r in rows], [0, 1, 2])
                self.assertEqual(rows[1]['detections'][0]['track_id'], rows[2]['detections'][0]['track_id'])
                self.assertIsNotNone(rows[1]['detections'][0]['track_id'])
                summary = json.loads((root / 'result/summary.json').read_text())
                self.assertEqual(summary['detector_backend'], 'sam3-hybrid')
                self.assertFalse(summary['production_validated'])

    def test_cli_tracks_native_frames_and_closes_models(self):
        self.run_clip()

    def test_cli_marks_partial_failure_and_closes_models(self):
        self.run_clip(fail=True)


if __name__ == '__main__':
    unittest.main()
