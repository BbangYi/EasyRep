import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from behavior_recorder import vision_memory
from behavior_recorder.core import RecorderError


class BoxSeedSupportTests(unittest.TestCase):
    def support(self, boxes, masks):
        return vision_memory.confirm_retry_masks(boxes, masks, allow_unmatched_masks=True)

    def test_each_seed_requires_its_own_current_mask_but_extra_masks_are_allowed(self):
        seeds = [dict(xyxy=[10,10,30,30]), dict(xyxy=[60,10,80,30])]
        masks = [dict(xyxy=[61,10,81,30],confidence=.8),
                 dict(xyxy=[11,10,31,30],confidence=.8),
                 dict(xyxy=[10,50,30,70],confidence=.8)]
        self.assertTrue(self.support(seeds, masks)['accepted'])
        self.assertFalse(vision_memory.confirm_retry_masks(seeds, masks)['accepted'],
                         'Existing retry requires the complete mask set')

    def test_missing_weak_ambiguous_or_shared_support_cannot_initialize(self):
        seed = dict(xyxy=[10,10,30,30])
        mask = dict(xyxy=[11,10,31,30],confidence=.8)
        for seeds, masks in [([], [mask]), ([seed], []),
                             ([seed], [dict(mask,confidence=.49)]),
                             ([seed], [dict(mask,xyxy=[50,10,70,30])]),
                             ([seed], [mask,mask]), ([seed,seed], [mask])]:
            with self.subTest(seeds=seeds,masks=masks):
                self.assertFalse(self.support(seeds,masks)['accepted'])

    def test_invalid_geometry_or_confidence_is_not_silently_accepted(self):
        for box in ([10,10,float('nan'),30],[10,10,10,30]):
            with self.assertRaises(RecorderError):
                self.support([dict(xyxy=box)],[])
        with self.assertRaises(RecorderError):
            self.support([dict(xyxy=[10,10,30,30])],
                         [dict(xyxy=[10,10,30,30],confidence=float('nan'))])


class BoxSeedFlowTests(unittest.TestCase):
    def run_sequence(self, *, enabled, current_masks):
        import numpy as np
        box = dict(xyxy=[20,10,50,40],confidence=.8)

        class Detector:
            idle = {'memory':0}
            workers = {}
            def __init__(self): self.calls = 0
            def predict_frame(self, frame):
                masks = current_masks[self.calls]; self.calls += 1
                return [dict(box)], dict(input_image='frame.png',mask_sha256='unused',
                    sam3=dict(mask_name='unused.npz',predictions=masks),
                    primary=dict(inference=dict(raw_grounding_predictions=[],verifier_details=[])),
                    route=dict(selected_auxiliary_indices=[]))
            def close(self): pass

        class Memory:
            process = SimpleNamespace(pid=0)
            def __init__(self): self.predict_calls = []
            def request(self, operation, **payload):
                if operation in ('reset','park'):
                    return dict(idle_mps=dict(driver_bytes=0))
                self.predict_calls.append(payload)
                return dict(image_sha256=payload['image_sha256'],mps=dict(driver_bytes=0),
                    predictions=[dict(box,object_slot=1)],visible_objects=1,seeded_objects=1)
            def close(self): pass

        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'frames').mkdir(); (root/'seeds').mkdir()
            predictor=vision_memory.MemoryHybridPredictor.__new__(vision_memory.MemoryHybridPredictor)
            predictor.directory=root
            predictor.card=dict(model_id='fixture',recipe={'box_seed_mask_support':1} if enabled else {})
            predictor.clock=vision_memory.MemoryClock(max_gap=.6,refresh_seconds=.5,max_frames=120)
            predictor.detector=Detector(); predictor.memory=Memory()
            predictor.index=predictor.generation=0; predictor.active=predictor.closed=False
            try:
                rows=[predictor.predict_frame(np.zeros((80,100,3),dtype=np.uint8),offset_seconds=i*.5)
                      for i in range(len(current_masks))]
                return rows,predictor.memory.predict_calls
            finally: predictor.close()

    def test_unsupported_first_box_never_reaches_memory_and_next_frame_redetects(self):
        mask=dict(xyxy=[20,10,50,40],confidence=.8,mask_index=0)
        rows,calls=self.run_sequence(enabled=True,current_masks=[[],[mask]])
        self.assertEqual(rows[0][0],[])
        self.assertEqual(rows[0][1]['seed']['count'],0)
        self.assertFalse(rows[0][1]['box_seed_mask_support']['accepted'])
        self.assertEqual(rows[1][1]['reset_reason'],'missing_object')
        self.assertEqual(len(rows[1][0]),1)
        self.assertEqual([call['offset_seconds'] for call in calls],[.5])
        self.assertEqual(calls[0]['seed']['kind'],'box')

    def test_opt_in_does_not_change_legacy_primary_only_acquisition(self):
        rows,calls=self.run_sequence(enabled=False,current_masks=[[]])
        self.assertEqual(len(rows[0][0]),1)
        self.assertEqual(len(calls),1)

    def test_refresh_cannot_replace_a_valid_track_with_an_unsupported_box(self):
        mask=dict(xyxy=[20,10,50,40],confidence=.8,mask_index=0)
        rows,calls=self.run_sequence(enabled=True,current_masks=[[mask],[]])
        self.assertEqual(len(rows[0][0]),1)
        self.assertEqual(rows[1][0],[])
        self.assertEqual(len(calls),1)


if __name__=='__main__': unittest.main()
