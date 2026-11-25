import copy
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

import numpy as np

from behavior_recorder import vision_video
from behavior_recorder.core import RecorderError


def result(boxes):
    tensor_boxes = MagicMock()
    tensor_boxes.data.device = 'cpu'
    rows = []
    for xyxy, score in boxes:
        box = MagicMock()
        box.xyxy.__getitem__.return_value.cpu.return_value.tolist.return_value = xyxy
        box.conf.__getitem__.return_value.cpu.return_value = score
        rows.append(box)
    tensor_boxes.__iter__.side_effect = lambda: iter(rows)
    return [SimpleNamespace(boxes=tensor_boxes)]


class SlicedDetectionTests(unittest.TestCase):
    def merge(self, full, sliced, threshold=0.8):
        function = getattr(vision_video, 'merge_sliced_boxes', None)
        self.assertTrue(callable(function), 'full-body-preserving merge is missing')
        return function(full, sliced, anchor_confidence=0.4, new_confidence=threshold, nms_iou=0.5)

    def test_partial_body_boxes_do_not_replace_whole_body(self):
        full = [{'xyxy':[0,0,100,200], 'confidence':0.5}]
        sliced = [{'xyxy':[0,0,100,200], 'confidence':0.9},
                  {'xyxy':[0,0,50,80], 'confidence':0.95},
                  {'xyxy':[-20,-20,130,250], 'confidence':0.91}]
        before = copy.deepcopy((full,sliced))
        self.assertEqual(self.merge(full,sliced),full)
        self.assertEqual((full,sliced),before)

    def test_close_animals_and_multiple_full_detections_are_preserved(self):
        full = [{'xyxy':[0,0,100,200], 'confidence':0.5},
                {'xyxy':[105,0,205,200], 'confidence':0.6}]
        new = {'xyxy':[210,0,300,180], 'confidence':0.9}
        self.assertEqual(self.merge(full,[new]),full+[new])
        nested = {'xyxy':[10,10,30,30], 'confidence':0.6}
        self.assertEqual(self.merge(full+[nested],[]),full+[nested])

    def test_strong_new_target_replaces_only_weak_overlapping_proposal(self):
        weak = {'xyxy':[5,0,100,200], 'confidence':0.2}
        strong = {'xyxy':[0,0,100,200], 'confidence':0.9}
        other = {'xyxy':[210,0,300,180], 'confidence':0.15}
        self.assertEqual(self.merge([weak,other],[strong]),[other,strong])
        self.assertEqual(self.merge([weak,other],[{**strong,'confidence':0.7}]),[weak,other])

    def test_nested_partial_tile_does_not_create_a_second_track_candidate(self):
        whole={'xyxy':[0,0,100,200], 'confidence':0.9}
        part={'xyxy':[10,10,40,80], 'confidence':0.85}
        self.assertEqual(self.merge([],[whole,part]),[whole])
        with self.assertRaises(RecorderError):
            self.merge([],[],threshold=0.3)

    def test_merge_mode_uses_full_pass_and_calibrated_new_box_threshold(self):
        detector=MagicMock()
        detector.predict.side_effect=[result([([0,0,200,300],.5)]),
            result([([0,0,80,100],.95)]),result([([450,100,530,200],.91)])]
        boxes,evidence=vision_video.predict_frame(detector,np.zeros((600,800,3),dtype=np.uint8),
            device='cpu',confidence=.1,nms_iou=.5,image_size=640,slicing='full-preserving-640-v1',
            anchor_confidence=.4,new_confidence=.9)
        self.assertEqual(boxes,[{'xyxy':[0,0,200,300],'confidence':.5},
                                {'xyxy':[610,100,690,200],'confidence':.91}])
        self.assertEqual(evidence['new_confidence'],.9)
        self.assertEqual(evidence['passes'],3)

    def test_merge_mode_requires_a_valid_threshold_in_configuration(self):
        config=dict(schema_version=1,species='lizard',sample_fps=3,confidence=.4,
                    max_step_diagonals=.15,max_gap_seconds=.6,zones={},
                    inference_slicing='full-preserving-640-v1',sliced_new_confidence=.9)
        self.assertEqual(vision_video.validate_tracking_config(config),config)
        for value in (None,True,.3,.96):
            with self.subTest(value=value),self.assertRaises(RecorderError):
                vision_video.validate_tracking_config({**config,'sliced_new_confidence':value})
        with self.assertRaises(RecorderError):
            vision_video.validate_tracking_config({**config,'inference_slicing':'off'})

    def predict(self, detector, frame, mode='overlap-640-v1'):
        function = getattr(vision_video, 'predict_frame', None)
        self.assertTrue(callable(function), 'bounded overlapping frame inference is missing')
        return function(detector, frame, device='cpu', confidence=0.1,
                        nms_iou=0.5, image_size=640, slicing=mode)

    def test_tile_coordinates_merge_duplicates_and_preserve_distinct_animals(self):
        detector = MagicMock()
        detector.predict.side_effect = [
            result([([210, 30, 280, 100], 0.8), ([500, 300, 600, 400], 0.6)]),
            result([([210, 30, 280, 100], 0.7)]),
            result([([50, 30, 120, 100], 0.9)]),
        ]
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        boxes, evidence = self.predict(detector, frame)
        self.assertEqual(boxes, [{'xyxy': [210, 30, 280, 100], 'confidence': 0.9},
                                 {'xyxy': [500, 300, 600, 400], 'confidence': 0.6}])
        self.assertEqual(evidence['passes'], 3)
        self.assertEqual(evidence['candidates_before_merge'], 4)
        self.assertEqual(evidence['actual_device'], 'cpu')
        self.assertEqual([call.args[0].shape for call in detector.predict.call_args_list],
                         [(600, 800, 3), (600, 640, 3), (600, 640, 3)])

    def test_small_input_is_not_repeated_and_default_is_unchanged(self):
        for shape, mode in [((480, 640, 3), 'overlap-640-v1'), ((1080, 1920, 3), 'off')]:
            with self.subTest(shape=shape, mode=mode):
                detector = MagicMock()
                detector.predict.return_value = result([])
                boxes, evidence = self.predict(detector, np.zeros(shape, dtype=np.uint8), mode)
                self.assertEqual(boxes, [])
                self.assertEqual(detector.predict.call_count, 1)
                self.assertEqual(evidence['passes'], 1)
                self.assertEqual(detector.predict.call_args.kwargs,
                    dict(device='cpu', conf=0.1, iou=0.5, max_det=100, imgsz=640, verbose=False))

    def test_windows_cover_edges_with_bounded_overlap(self):
        function = getattr(vision_video, 'sliced_windows', None)
        self.assertTrue(callable(function), 'bounded slicing windows are missing')
        windows = function(1920, 1080)
        self.assertEqual(len(windows), 8)
        coverage = np.zeros((1080, 1920), dtype=np.uint8)
        for x1, y1, x2, y2 in windows:
            self.assertEqual((x2-x1, y2-y1), (640, 640))
            coverage[y1:y2, x1:x2] += 1
        self.assertTrue(np.all(coverage > 0))
        self.assertLessEqual(int(coverage.max()), 4)
        with self.assertRaises(RecorderError):
            function(120000, 100)

    def test_unknown_mode_rejected_before_model_runs(self):
        detector = MagicMock()
        with self.assertRaises(RecorderError):
            self.predict(detector, np.zeros((10, 10, 3)), 'guess')
        detector.predict.assert_not_called()

    def test_tracking_configuration_rejects_unknown_slicing(self):
        config = dict(schema_version=1, species='lizard', sample_fps=3, confidence=0.4,
                      max_step_diagonals=0.15, max_gap_seconds=0.6, zones={})
        original = copy.deepcopy(config)
        vision_video.validate_tracking_config(config)
        self.assertEqual(config, original)
        for value in (None, True, 'guess', {'width': 640}):
            with self.subTest(value=value), self.assertRaises(RecorderError):
                vision_video.validate_tracking_config({**config, 'inference_slicing': value})


if __name__ == '__main__':
    unittest.main()
