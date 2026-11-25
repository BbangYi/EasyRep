import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from behavior_recorder.core import RecorderError, read_json
from behavior_recorder.vision_tracking import VideoTracker
from behavior_recorder.vision_video import observation, validate_tracking_config
from behavior_recorder.behavior_windows import window_observations

ROOT = Path(__file__).resolve().parents[1]


def box(x, width=120):
    return {'xyxy': [x, 20, x + width, 40], 'confidence': .9}


def motion(start=.2, end=.4, dx=40):
    return {'status': 'estimated', 'from_offset_seconds': start,
            'to_offset_seconds': end, 'matrix': [[1, 0, dx], [0, 1, 0]]}


class CameraTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from behavior_recorder.vision_model import runtime
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        runtime(Path(cls.directory.name), 1)

    def setUp(self):
        self.config = read_json(ROOT/'examples/vision.tracking.json')
        self.config['camera_motion'] = 'background-affine-v1'
        self.tracker = VideoTracker(self.config, 200, 100, fuse_confirmation_score=False)
        self.tracker.update([box(10)], 0)
        self.before, _, _ = self.tracker.update([box(12)], .2)

    def test_camera_pan_preserves_established_track(self):
        result, _, events = self.tracker.update([box(52)], .4, camera_motion=motion())
        self.assertEqual(result[0]['track_id'], self.before[0]['track_id'])
        self.assertEqual(result[0]['identity_status'], 'active')
        self.assertTrue(any(e['kind'] == 'camera_jump_compensated' for e in events))

    def test_stationary_background_does_not_excuse_animal_jump(self):
        result, _, _ = self.tracker.update([box(52)], .4, camera_motion=motion(dx=0))
        self.assertNotEqual(result[0]['track_id'], self.before[0]['track_id'])
        self.assertEqual(result[0]['identity_status'], 'implausible_jump')

    def test_unavailable_estimate_retains_jump_guard(self):
        evidence = {**motion(), 'status': 'unavailable', 'matrix': None}
        result, _, _ = self.tracker.update([box(52)], .4, camera_motion=evidence)
        self.assertEqual(result[0]['identity_status'], 'implausible_jump')

    def test_gap_cannot_use_a_one_frame_transform(self):
        self.tracker.update([], .4)
        result, _, _ = self.tracker.update([box(52)], .6, camera_motion=motion(.4, .6))
        self.assertFalse(result[0]['motion_allowed'])
        self.assertNotEqual(result[0]['track_id'], self.before[0]['track_id'])

    def test_overlapping_animals_remain_ambiguous_during_pan(self):
        result, _, events = self.tracker.update([box(52), box(55)], .4, camera_motion=motion())
        self.assertTrue(all(not b['motion_allowed'] for b in result))
        self.assertFalse(any(e['kind'] == 'camera_jump_compensated' for e in events))

    def test_stale_or_invalid_transform_rejected_before_state_changes(self):
        for evidence in (motion(0, .4), motion(.2, .3),
                         {**motion(), 'matrix': [[1, 0, float('nan')], [0, 1, 0]]}):
            with self.subTest(evidence=evidence), self.assertRaises(RecorderError):
                self.tracker.update([box(52)], .4, camera_motion=evidence)
        self.assertEqual(self.tracker.frame_number, 2)
        self.assertEqual(self.tracker.last_time, .2)

    def test_moving_camera_observations_cannot_create_behavior_baseline(self):
        self.config['zones'] = {'all': [0, 0, 1, 1]}
        rows = []
        previous = None
        for index in range(11):
            row = observation([{'xyxy': [12, 20, 132, 40], 'confidence': .9,
                               'track_id': 1, 'identity_status': 'active', 'motion_allowed': True}],
                              previous, index / 5, 200, 100, self.config)
            self.assertEqual(row['status'], 'observed')
            self.assertIsNone(row['step_diagonals'])
            self.assertIsNone(row['zone'])
            rows.append(row)
            previous = row
        summary = {'source': {'duration_seconds': 2, 'sha256': 'source', 'provenance': 'public_real'},
                   'model_id': 'model', 'config': self.config}
        result = window_observations(summary, rows, {}, window_seconds=2)['windows'][0]
        self.assertEqual(result['quality'], 'insufficient_observation')
        self.assertIsNone(result['features'])

    def test_unknown_camera_mode_is_rejected(self):
        with self.assertRaises(RecorderError):
            validate_tracking_config({**self.config, 'camera_motion': 'anything'})


class BackgroundMotionTests(unittest.TestCase):
    def setUp(self):
        # Missing production estimator is an explicit regression failure in the red run.
        import behavior_recorder.vision_tracking as tracking
        self.assertTrue(hasattr(tracking, 'BackgroundMotion'), 'background estimator missing')
        self.estimator = tracking.BackgroundMotion(.4, .6)
        cv2.setNumThreads(1)
        random = np.random.default_rng(824)
        gray = random.integers(0, 256, (240, 400), dtype=np.uint8)
        self.frame = cv2.cvtColor(cv2.GaussianBlur(gray, (3, 3), 0), cv2.COLOR_GRAY2BGR)

    def test_background_translation_ignores_independent_animal_patch(self):
        first = self.frame.copy()
        first[90:150, 160:240] = 0
        second = cv2.warpAffine(self.frame, np.float32([[1, 0, -45], [0, 1, 8]]), (400, 240))
        second[80:140, 180:260] = 0
        self.estimator.update(first, [{'xyxy': [160, 90, 240, 150], 'confidence': .9}], 0)
        result = self.estimator.update(second, [{'xyxy': [180, 80, 260, 140], 'confidence': .9}], .2)
        self.assertEqual(result['status'], 'estimated')
        self.assertAlmostEqual(result['matrix'][0][2], -45, delta=2)
        self.assertAlmostEqual(result['matrix'][1][2], 8, delta=2)

    def test_featureless_frames_abstain(self):
        frame = np.zeros_like(self.frame)
        self.estimator.update(frame, [], 0)
        result = self.estimator.update(frame, [], .2)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['matrix'])

    def test_fully_occluded_background_abstains(self):
        boxes = [{'xyxy': [0, 0, 400, 240], 'confidence': .9}]
        self.estimator.update(self.frame, boxes, 0)
        self.assertEqual(self.estimator.update(self.frame, boxes, .2)['status'], 'unavailable')

    def test_scene_cut_and_long_gap_never_reuse_transform(self):
        self.estimator.update(self.frame, [], 0)
        result = self.estimator.update(self.frame, [], .2, cut=True)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['matrix'])
        result = self.estimator.update(self.frame, [], 2)
        self.assertEqual(result['status'], 'unavailable')

    def test_unrelated_background_abstains(self):
        self.estimator.update(self.frame, [], 0)
        result = self.estimator.update(np.flip(self.frame, axis=1).copy(), [], .2)
        self.assertEqual(result['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
