import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from behavior_recorder import vision_memory
from behavior_recorder.core import RecorderError


class TemporalRecheckTests(unittest.TestCase):
    def check(self, previous=None, predictions=None, **kwargs):
        function=getattr(vision_memory,'temporal_recheck',None)
        self.assertTrue(callable(function),'Unstable memory recheck is missing')
        old=dict(size=(100,80),offset_seconds=.5,consecutive_frames=2,generation=1,seeded_objects=1,
                 predictions=[dict(xyxy=[10,10,30,30],object_slot=1)])
        current=[dict(xyxy=[60,50,80,70],object_slot=1)]
        options=dict(size=(100,80),offset_seconds=1.,generation=1,max_gap=.6)
        options.update(kwargs)
        return function(old if previous is None else previous,current if predictions is None else predictions,**options)

    def test_low_overlap_or_large_step_requests_current_frame_redetection(self):
        result=self.check()
        self.assertTrue(result['required'])
        self.assertEqual(result['object_slots'],[1])
        self.assertFalse(self.check(predictions=[dict(xyxy=[11,10,31,30],object_slot=1)])['required'])

    def test_no_history_extension_across_gaps_sessions_or_incomplete_objects(self):
        old=dict(size=(100,80),offset_seconds=.5,consecutive_frames=1,generation=1,seeded_objects=1,
                 predictions=[dict(xyxy=[10,10,30,30],object_slot=1)])
        self.assertFalse(self.check(previous=old)['required'])
        for change in [dict(generation=2),dict(size=(200,80)),dict(offset_seconds=1.2),dict(predictions=[])]:
            with self.subTest(change=change):self.assertFalse(self.check(**change)['required'])
        self.assertFalse(self.check(size=(20,80),predictions=[dict(xyxy=[10,10,15,20],object_slot=1)])['required'])

    def test_only_the_discontinuous_slot_triggers_a_whole_frame_recheck(self):
        previous=dict(size=(100,80),offset_seconds=.5,consecutive_frames=2,generation=1,seeded_objects=2,
                      predictions=[dict(xyxy=[10,10,30,30],object_slot=1),dict(xyxy=[60,10,80,30],object_slot=2)])
        current=[dict(xyxy=[11,10,31,30],object_slot=1),dict(xyxy=[60,50,80,70],object_slot=2)]
        self.assertEqual(self.check(previous=previous,predictions=current)['object_slots'],[2])

    def test_unique_slots_and_finite_geometry_required(self):
        for current in [[dict(xyxy=[0,0,float('nan'),10],object_slot=1)],
                        [dict(xyxy=[0,0,10,10],object_slot=1)]*2]:
            with self.subTest(current=current),self.assertRaises(RecorderError):self.check(predictions=current)


class TemporalRecheckFlowTests(unittest.TestCase):
    def run_sequence(self, *, enabled=True, empty_refresh=False, unsupported_fresh=False, fail_refresh=False, cut=False):
        import numpy as np
        original=[10,10,30,30];drift=[65,50,85,70];fresh=[15,12,35,32]
        class Detector:
            idle={'memory':0};workers={}
            def __init__(self):self.calls=0;self.closed=False
            def predict_frame(self,frame):
                self.calls+=1;box=original if self.calls==1 else fresh
                boxes=[] if empty_refresh and self.calls==2 else [dict(xyxy=box,confidence=.8)]
                return boxes,dict(input_image='frame.png',mask_sha256='unused',
                    sam3=dict(mask_name='unused.npz',predictions=[dict(xyxy=box,confidence=.8,mask_index=0)] if boxes else []),
                    primary=dict(inference=dict(raw_grounding_predictions=[],verifier_details=[])),
                    route=dict(selected_auxiliary_indices=[]))
            def close(self):self.closed=True
        class Memory:
            process=SimpleNamespace(pid=0)
            def __init__(self):self.last=None;self.requests=[];self.predictions=0;self.closed=False
            def request(self,operation,**payload):
                self.requests.append(dict(operation=operation,**payload))
                if operation=='reset':self.last=None
                if operation in ('reset','park'):return dict(idle_mps=dict(driver_bytes=0))
                self.predictions+=1
                if fail_refresh and self.predictions==4:raise RuntimeError('fresh memory failed')
                if self.last is not None and payload['offset_seconds']<=self.last:raise AssertionError('Repeated time without reset')
                self.last=payload['offset_seconds']
                box=(original if self.predictions<=2 else drift if self.predictions==3 or unsupported_fresh else fresh)
                return dict(image_sha256=payload['image_sha256'],mps=dict(driver_bytes=0),
                    predictions=[dict(xyxy=box,confidence=1.,object_slot=1)],visible_objects=1,seeded_objects=1,
                    mask_artifact='memory/masks/'+payload['mask_name'],mask_sha256='fixture')
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'frames').mkdir();(root/'seeds').mkdir()
            predictor=vision_memory.MemoryHybridPredictor.__new__(vision_memory.MemoryHybridPredictor)
            predictor.directory=root;predictor.card=dict(model_id='fixture',recipe={'box_seed_mask_support':1})
            if enabled:predictor.card['recipe']['unstable_mask_redetection']=1
            predictor.clock=vision_memory.MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120,refresh_retry_frames=1)
            predictor.detector=Detector();predictor.memory=Memory();predictor.index=predictor.generation=0
            predictor.active=predictor.closed=False
            rows=[]
            try:
                for index in range(4):
                    rows.append(predictor.predict_frame(np.zeros((80,100,3),dtype=np.uint8),
                        offset_seconds=index*.5,scene_cut=cut and index==2))
            except RuntimeError:
                if not fail_refresh:raise
                self.assertTrue(predictor.closed and predictor.detector.closed and predictor.memory.closed)
                return rows,predictor.detector.calls,predictor.memory.requests
            finally:predictor.close()
            if fail_refresh:self.fail('Fresh memory request was never attempted')
            return rows,predictor.detector.calls,predictor.memory.requests

    def test_rechecks_current_frame_and_reseeds_without_copying_the_previous_box(self):
        rows,calls,requests=self.run_sequence()
        self.assertEqual(rows[2][0][0]['xyxy'],[15,12,35,32])
        self.assertEqual(rows[2][1]['reset_reason'],'unstable_mask')
        self.assertEqual(calls,2)
        self.assertNotEqual(rows[2][0][0]['memory_object_id'],rows[1][0][0]['memory_object_id'])
        current=[r for r in requests if r['operation']=='predict' and r['offset_seconds']==1.]
        self.assertEqual(len(current),2)
        self.assertNotEqual(current[0]['mask_name'],current[1]['mask_name'])
        self.assertTrue(rows[2][1]['temporal_recheck']['fresh_mask_support']['accepted'])

    def test_empty_or_unsupported_recheck_discards_drift_and_retries_on_next_input(self):
        for options in [dict(empty_refresh=True),dict(unsupported_fresh=True)]:
            with self.subTest(options=options):
                rows,calls,requests=self.run_sequence(**options)
                self.assertEqual(rows[2][0],[])
                self.assertEqual(rows[3][1]['reset_reason'],'missing_object')
                self.assertEqual(calls,3)
                self.assertLessEqual(sum(r['operation']=='predict' and r['offset_seconds']==1. for r in requests),2)

    def test_legacy_recipe_does_not_trigger_a_second_detector(self):
        rows,calls,_=self.run_sequence(enabled=False)
        self.assertEqual(calls,1)
        self.assertEqual(rows[2][0][0]['xyxy'],[65,50,85,70])

    def test_scene_refresh_is_not_followed_by_another_same_frame_recheck(self):
        rows,calls,requests=self.run_sequence(cut=True)
        self.assertEqual(rows[2][1]['reset_reason'],'scene_cut')
        self.assertEqual(calls,2)
        self.assertEqual(sum(r['operation']=='predict' and r['offset_seconds']==1. for r in requests),1)

    def test_fresh_worker_failure_closes_all_workers(self):
        self.run_sequence(fail_refresh=True)


if __name__=='__main__':unittest.main()
