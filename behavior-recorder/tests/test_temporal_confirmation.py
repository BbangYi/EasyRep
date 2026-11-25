import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from behavior_recorder import vision_memory
from behavior_recorder.core import RecorderError


class TemporalConfirmationTests(unittest.TestCase):
    def choose(self, previous=None, primary=None, auxiliary=None, **kwargs):
        fn=getattr(vision_memory,'confirm_temporal_seed',None)
        self.assertTrue(callable(fn),'Current-frame cross-model confirmation is missing')
        prior=dict(size=(100,80),offset_seconds=9.5,consecutive_frames=4,seeded_objects=1,
                   predictions=[dict(xyxy=[20,10,50,40],object_slot=1)])
        p=[dict(xyxy=[22,10,52,40],confidence=.95)]
        a=[dict(xyxy=[22,10,52,40],confidence=.8,mask_index=7)]
        options=dict(size=(100,80),offset_seconds=10.,reason='periodic_detection',max_gap=.6)
        options.update(kwargs)
        return fn(prior if previous is None else previous,p if primary is None else primary,
                  a if auxiliary is None else auxiliary,**options)

    def test_current_models_can_confirm_only_an_existing_bounded_track(self):
        seed,details=self.choose()
        self.assertEqual(seed,dict(kind='mask',mask_indices=[7],count=1))
        self.assertTrue(details['accepted'])
        self.assertEqual(self.choose(reason='refresh_retry')[0],seed)

    def test_no_recovery_from_weak_models_or_disagreement(self):
        cases=[dict(primary=[]),dict(auxiliary=[]),
               dict(primary=[dict(xyxy=[22,10,52,40],confidence=.89)]),
               dict(auxiliary=[dict(xyxy=[22,10,52,40],confidence=.49,mask_index=0)]),
               dict(auxiliary=[dict(xyxy=[60,10,90,40],confidence=.9,mask_index=0)]),
               dict(primary=[dict(xyxy=[60,10,90,40],confidence=.95)],
                    auxiliary=[dict(xyxy=[60,10,90,40],confidence=.9,mask_index=0)])]
        for case in cases:
            with self.subTest(case=case):self.assertIsNone(self.choose(**case)[0])

    def test_scene_gap_geometry_and_unconfirmed_history_cannot_be_bypassed(self):
        for reason in ('first_frame','scene_cut','time_gap','resolution_change','missing_object','memory_frame_limit'):
            with self.subTest(reason=reason):self.assertIsNone(self.choose(reason=reason)[0])
        for kwargs in [dict(offset_seconds=10.2),dict(offset_seconds=9.5),dict(size=(120,80))]:
            with self.subTest(kwargs=kwargs):self.assertIsNone(self.choose(**kwargs)[0])
        for previous in [dict(size=(100,80),offset_seconds=9.5,consecutive_frames=1,seeded_objects=1,predictions=[dict(xyxy=[20,10,50,40])]),
                         dict(size=(100,80),offset_seconds=9.5,consecutive_frames=4,seeded_objects=2,predictions=[dict(xyxy=[20,10,50,40])])]:
            self.assertIsNone(self.choose(previous=previous)[0])

    def test_multiple_objects_require_complete_unique_correspondence(self):
        previous=dict(size=(100,80),offset_seconds=9.5,consecutive_frames=4,seeded_objects=2,
                      predictions=[dict(xyxy=[10,10,30,30],object_slot=1),dict(xyxy=[65,10,85,30],object_slot=2)])
        primary=[dict(xyxy=[66,10,86,30],confidence=.95),dict(xyxy=[11,10,31,30],confidence=.95)]
        auxiliary=[dict(xyxy=[66,10,86,30],confidence=.9,mask_index=3),dict(xyxy=[11,10,31,30],confidence=.9,mask_index=7)]
        self.assertEqual(self.choose(previous,primary,auxiliary)[0],dict(kind='mask',mask_indices=[7,3],count=2))
        self.assertIsNone(self.choose(previous,primary[:1],auxiliary[:1])[0])
        self.assertIsNone(self.choose(previous,primary+primary[:1],auxiliary)[0])
        merged=[dict(xyxy=[11,10,86,30],confidence=.95,mask_index=0)]
        self.assertIsNone(self.choose(previous,primary,merged)[0])

    def test_nonfinite_current_geometry_fails_validation(self):
        with self.assertRaises(RecorderError):
            self.choose(primary=[dict(xyxy=[float('nan'),10,52,40],confidence=.95)])

    def test_native_edge_proposal_uses_existing_clipping_contract(self):
        previous=dict(size=(100,80),offset_seconds=9.5,consecutive_frames=4,seeded_objects=1,
                      predictions=[dict(xyxy=[0,10,30,40],object_slot=1)])
        try:
            seed,_=self.choose(previous,[dict(xyxy=[-2,10,30,40],confidence=.95)],
                              [dict(xyxy=[0,10,30,40],confidence=.8,mask_index=0)])
        except RecorderError as exc:
            self.fail('A valid clipped edge proposal aborted confirmation: '+str(exc))
        self.assertEqual(seed,dict(kind='mask',mask_indices=[0],count=1))


class TemporalConfirmationFlowTests(unittest.TestCase):
    def run_refresh(self, enabled, *, mask_support=False, absent_on_refresh=False):
        import numpy as np
        from behavior_recorder.core import digest
        from behavior_recorder.vision_memory_worker import validate_memory_step
        class Detector:
            def __init__(self,root):
                self.directory=root/'detector';(self.directory/'masks').mkdir(parents=True)
                self.idle={'memory':0};self.workers={};self.index=0
            def predict_frame(self,frame):
                missing=self.index in (1,2);name=f'{self.index:06d}.npz'
                mask=np.zeros((1,80,100),dtype=bool);mask[:,10:40,20:50]=True
                path=self.directory/'masks'/name;np.savez_compressed(path,masks=mask)
                confidence=.5 if self.index==1 else .95;self.index+=1
                return ([] if missing else [dict(xyxy=[20,10,50,40],confidence=.8)]),dict(
                    input_image='frame.png',mask_sha256=digest(path),sam3=dict(mask_name=name,
                    predictions=[] if missing and absent_on_refresh else [dict(xyxy=[20,10,50,40],confidence=.8,mask_index=0)]),
                    primary=dict(inference=dict(raw_grounding_predictions=[dict(xyxy=[20,10,50,40],confidence=confidence)],verifier_details=[])),
                    route=dict(selected_auxiliary_indices=[]))
            def close(self):pass
        class Memory:
            process=SimpleNamespace(pid=0)
            def __init__(self):self.last=self.started=None;self.index=0;self.used=False
            def request(self,operation,**payload):
                if operation=='reset':self.last=self.started=None;self.index=0;self.used=False
                if operation in ('reset','park'):return dict(idle_mps=dict(driver_bytes=0))
                if payload['seed'] is not None:self.last=None;self.started=payload['offset_seconds'];self.index=0;self.used=False
                if self.started is None:raise AssertionError('No live memory')
                self.used=validate_memory_step(self.last,self.started,payload['offset_seconds'],self.index,.6,
                    retry_used=self.used,allow_refresh_retry=payload['allow_refresh_retry'])
                self.last=payload['offset_seconds'];self.index+=1
                return dict(image_sha256=payload['image_sha256'],mps=dict(driver_bytes=0),
                    predictions=[dict(xyxy=[20,10,50,40],confidence=1.,object_slot=1)],visible_objects=1,seeded_objects=1)
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'frames').mkdir();(root/'seeds').mkdir()
            predictor=vision_memory.MemoryHybridPredictor.__new__(vision_memory.MemoryHybridPredictor)
            predictor.directory=root;predictor.card=dict(model_id='fixture',recipe={'temporal_seed_confirmation':1} if enabled else {})
            if mask_support:predictor.card['recipe']['refresh_mask_support']=1
            predictor.clock=vision_memory.MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120,refresh_retry_frames=1)
            predictor.detector=Detector(root);predictor.memory=Memory();predictor.index=predictor.generation=0
            predictor.active=predictor.closed=False
            try:return [predictor.predict_frame(np.zeros((80,100,3),dtype=np.uint8),offset_seconds=i*.5) for i in range(23)]
            finally:predictor.close()

    def test_opt_in_reseeds_current_mask_after_retry_without_extending_worker_age(self):
        rows=self.run_refresh(True)
        self.assertEqual(len(rows[21][0]),1,'Supported current-frame recovery was lost at the retry')
        self.assertEqual(rows[21][1]['seed']['kind'],'mask')
        self.assertTrue(rows[21][1]['temporal_seed_confirmation']['accepted'])
        self.assertEqual(len(rows[22][0]),1)

    def test_existing_recipe_still_discards_a_second_failed_refresh(self):
        rows=self.run_refresh(False)
        self.assertEqual(rows[21][0],[])

    def test_retry_does_not_publish_memory_drift_without_current_segmentation(self):
        rows=self.run_refresh(True,mask_support=True,absent_on_refresh=True)
        self.assertEqual(rows[20][0],[],'Unsupported memory survived an empty current segmentation')
        self.assertFalse(rows[20][1]['refresh_mask_support']['accepted'])
        self.assertEqual(rows[21][1]['reset_reason'],'missing_object')

    def test_supported_current_retry_keeps_the_bounded_recovery(self):
        rows=self.run_refresh(True,mask_support=True)
        self.assertEqual(len(rows[20][0]),1)
        self.assertIn('refresh_mask_support',rows[20][1])
        self.assertTrue(rows[20][1]['refresh_mask_support']['accepted'])
        self.assertEqual(len(rows[21][0]),1)


class RetryMaskSupportTests(unittest.TestCase):
    def test_support_is_complete_unique_current_mask_overlap(self):
        fn=getattr(vision_memory,'confirm_retry_masks',None)
        self.assertTrue(callable(fn),'Deferred output has no current-mask support gate')
        old=[dict(xyxy=[10,10,30,30]),dict(xyxy=[60,10,80,30])]
        current=[dict(xyxy=[11,10,31,30],confidence=.8),dict(xyxy=[61,10,81,30],confidence=.8)]
        self.assertTrue(fn(old,current)['accepted'])
        for values in [[],current[:1],current+current[:1],[dict(xyxy=[40,10,55,30],confidence=.8),current[1]],
                       [dict(xyxy=[11,10,31,30],confidence=.49),current[1]]]:
            with self.subTest(values=values):self.assertFalse(fn(old,values)['accepted'])
        with self.assertRaises(RecorderError):fn(old,[dict(xyxy=[0,0,float('nan'),30],confidence=.8)])


if __name__=='__main__':unittest.main()
