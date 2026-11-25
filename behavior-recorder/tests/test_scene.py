import importlib.util
import unittest
import tempfile
from pathlib import Path

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_scene import SceneBoundary


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'requires OpenCV')
class SceneBoundaryTests(unittest.TestCase):
    def test_cut_between_sampled_frames_is_not_discarded(self):
        import numpy as np
        from unittest.mock import MagicMock, patch
        from behavior_recorder.vision_video import sampled_frames
        black = np.zeros((60, 80, 3), dtype=np.uint8)
        capture = MagicMock()
        capture.read.side_effect = [(True, black), (True, black + 255), (True, black), (False, None)]
        timeline = [dict(frame_index=i, offset_seconds=t) for i,t in enumerate((0, .1, 1))]
        with patch('cv2.VideoCapture', return_value=capture):
            rows = list(sampled_frames('fixture.avi', dict(width=80, height=60), timeline, 1, scene=SceneBoundary()))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1][1]['scene_boundary']['cut'])
        self.assertEqual([r['frame_index'] for r in rows[1][1]['scene_boundary']['native_events']], [1, 2])
        capture.release.assert_called_once()

    def test_guard_observes_native_frames_between_samples(self):
        import cv2
        import numpy as np
        from behavior_recorder.vision_video import sampled_frames
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'gradual.avi'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'FFV1'), 10, (80, 60))
            self.assertTrue(writer.isOpened())
            try:
                for value in range(0, 201, 20):
                    writer.write(np.full((60, 80, 3), value, dtype=np.uint8))
            finally:
                writer.release()
            times = [dict(frame_index=i, offset_seconds=i / 10) for i in range(11)]
            scene = SceneBoundary()
            rows = list(sampled_frames(path, dict(width=80, height=60), times, 1, scene=scene))
            self.assertEqual(len(rows), 2)
            self.assertFalse(any(row['scene_boundary']['cut'] for _, row in rows))
            sparse = SceneBoundary()
            sparse.update(rows[0][0])
            self.assertTrue(sparse.update(rows[1][0])['cut'])

    def test_static_and_small_exposure_change_do_not_reset(self):
        import numpy as np
        scene = SceneBoundary()
        first = np.full((60, 80, 3), 80, dtype=np.uint8)
        self.assertFalse(scene.update(first)['cut'])
        self.assertEqual(scene.update(first)['content_score'], 0)
        self.assertFalse(scene.update(first + 5)['cut'])

    def test_large_change_resets_on_current_frame_without_future_input(self):
        import numpy as np
        scene = SceneBoundary()
        scene.update(np.zeros((60, 80, 3), dtype=np.uint8))
        white = np.full((60, 80, 3), 255, dtype=np.uint8)
        self.assertTrue(scene.update(white)['cut'])
        self.assertFalse(scene.update(white)['cut'])
        self.assertEqual(scene.summary()['cuts_detected'], 1)

    def test_shape_change_invalidates_continuity(self):
        import numpy as np
        scene = SceneBoundary()
        scene.update(np.zeros((60, 80, 3), dtype=np.uint8))
        self.assertEqual(scene.update(np.zeros((80, 80, 3), dtype=np.uint8))['reason'], 'dimensions_changed')

    def test_invalid_frames_fail_before_replacing_previous_frame(self):
        import numpy as np
        scene = SceneBoundary()
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        scene.update(frame)
        for invalid in (None, np.zeros((10, 10)), np.zeros((10, 10, 3)), np.zeros((0, 10, 3), dtype=np.uint8)):
            with self.subTest(shape=getattr(invalid, 'shape', None)), self.assertRaises(RecorderError):
                scene.update(invalid)
        self.assertFalse(scene.update(frame)['cut'])
