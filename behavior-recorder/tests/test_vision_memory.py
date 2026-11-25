import importlib
import importlib.util
import unittest
import io
import json
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from behavior_recorder.core import RecorderError


class MemoryBoundaryTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('behavior_recorder.vision_memory'),
                             'Stateful video memory backend is missing')
        return importlib.import_module('behavior_recorder.vision_memory')

    def test_scene_gap_and_resolution_changes_require_fresh_detection(self):
        clock=self.module().MemoryClock(max_gap=.6, refresh_seconds=10, max_frames=120)
        self.assertEqual(clock.advance((100,80),0), 'first_frame')
        self.assertIsNone(clock.advance((100,80),.5))
        self.assertEqual(clock.advance((100,80),1,cut=True),'scene_cut')
        self.assertEqual(clock.advance((100,80),2),'time_gap')
        self.assertEqual(clock.advance((120,80),2.5),'resolution_change')

    def test_periodic_refresh_bounds_memory_and_discovers_new_objects(self):
        clock=self.module().MemoryClock(max_gap=.6,refresh_seconds=1,max_frames=120)
        self.assertEqual(clock.advance((10,10),0),'first_frame')
        self.assertIsNone(clock.advance((10,10),.5))
        self.assertEqual(clock.advance((10,10),1),'periodic_detection')
        clock=self.module().MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=2)
        clock.advance((10,10),0)
        self.assertIsNone(clock.advance((10,10),.1))
        self.assertEqual(clock.advance((10,10),.2),'memory_frame_limit')

    def test_absent_mask_forces_redetection_and_clock_rejects_rewind(self):
        clock=self.module().MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120)
        clock.advance((10,10),0)
        clock.redetect=True
        self.assertEqual(clock.advance((10,10),.5),'missing_object')
        for value in [.5,.4,float('nan')]:
            with self.assertRaises(RecorderError):clock.advance((10,10),value)
        self.assertIsNone(clock.advance((10,10),1))

    def test_mask_seed_used_only_when_it_covers_all_accepted_detections(self):
        select=self.module().select_seeds
        a=dict(xyxy=[0,0,10,10],confidence=.9,mask_index=2)
        b=dict(xyxy=[20,0,30,10],confidence=.8,mask_index=3)
        evidence=dict(route=dict(selected_auxiliary_indices=[0]),sam3=dict(predictions=[a]))
        self.assertEqual(select([a],evidence),dict(kind='mask',mask_indices=[2],count=1))
        result=select([a,b],evidence)
        self.assertEqual(result,dict(kind='box',boxes=[[0,0,10,10],[20,0,30,10]],count=2))

    def test_empty_and_excessive_seed_counts_do_not_create_phantom_objects(self):
        select=self.module().select_seeds
        evidence=dict(route=dict(selected_auxiliary_indices=[]),sam3=dict(predictions=[]))
        self.assertEqual(select([],evidence),dict(kind='empty',count=0))
        with self.assertRaises(RecorderError):
            select([dict(xyxy=[0,0,10,10],confidence=.9)]*17,evidence)


class MemoryCliTests(unittest.TestCase):
    def test_preview_distinguishes_binary_presence_and_pending_identity(self):
        import cv2
        import numpy as np
        from behavior_recorder.vision_video import render_review_frame
        config=dict(confidence=.4)
        for state in ('tentative','active'):
            with self.subTest(state=state):
                row=dict(offset_seconds=0,status='track_pending',inference=dict(model='sam2-hybrid'),
                         detections=[dict(xyxy=[10,10,70,70],confidence=1.,track_id=3,identity_status=state)])
                with patch.object(cv2,'putText',wraps=cv2.putText) as draw:
                    rendered=render_review_frame(np.zeros((100,100,3),dtype=np.uint8),row,config)
                text='\n'.join(call.args[1] for call in draw.call_args_list)
                self.assertNotIn('1.00',text)
                self.assertIn('binary mask presence',text)
                self.assertEqual('T3 pending' in text,state=='tentative')
                self.assertTrue(rendered.any())

    def run_clip(self, fail=False):
        import cv2
        import numpy as np
        from behavior_recorder import vision_memory
        from behavior_recorder.vision import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            writer=cv2.VideoWriter(str(root/'source.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),3,(100,100))
            self.assertTrue(writer.isOpened())
            for value in [0,0,255]:writer.write(np.full((100,100,3),value,dtype=np.uint8))
            writer.release()
            config=dict(schema_version=1,species='lizard',sample_fps=3,confidence=.4,nms_iou=.5,
                        max_step_diagonals=.15,max_gap_seconds=.6,zones={'all':[0,0,1,1]})
            (root/'config.json').write_text(json.dumps(config))
            calls,closed=[],[]
            class NeuralFixture:
                def __init__(self,*args,max_gap_seconds):
                    if max_gap_seconds != .6:raise AssertionError('Lost configured gap')
                def predict_frame(self,frame,*,offset_seconds,scene_cut):
                    calls.append((offset_seconds,scene_cut))
                    if fail and len(calls)==2:raise RuntimeError('memory worker failure fixture')
                    return [dict(xyxy=[10,10,30,30],confidence=1.,memory_object_id='1:1')],dict(actual_device='cpu',model='synthetic_test')
                def close(self):closed.append(True)
            card=dict(species='lizard',recipe=dict(image_size=640),model_id='fixture',status='experimental')
            out,err=io.StringIO(),io.StringIO()
            with patch.object(vision_memory,'load_memory_bundle',return_value=(card,{},())), \
                    patch.object(vision_memory,'MemoryHybridPredictor',NeuralFixture),redirect_stdout(out),redirect_stderr(err):
                try:
                    code=main(['infer','--backend','sam2-hybrid','--model',str(root),'--video',str(root/'source.mp4'),
                        '--config',str(root/'config.json'),'--output',str(root/'result'),'--device','cpu','--threads','1',
                        '--provenance','synthetic_test'])
                except SystemExit:
                    self.fail('Public CLI does not expose the stateful memory backend')
            self.assertEqual(closed,[True])
            if fail:
                self.assertEqual(code,1)
                self.assertEqual(json.loads((root/'result/status.json').read_text())['state'],'failed')
                return
            self.assertEqual(code,0,err.getvalue())
            self.assertEqual(calls,[(0.,False),(1/3,False),(2/3,True)])
            rows=list(map(json.loads,(root/'result/observations.jsonl').read_text().splitlines()))
            self.assertTrue(any(e['kind']=='scene_change' for e in rows[2]['tracking_events']))
            self.assertNotEqual(rows[2]['detections'][0]['track_id'],rows[1]['detections'][0]['track_id'])
            for row in rows:
                self.assertIsNone(row['step_diagonals'])
                self.assertIsNone(row['zone'])
                for track in row['tracks']:self.assertIsNone(track['speed_diagonals_per_second'])
            summary=json.loads((root/'result/summary.json').read_text())
            self.assertEqual(summary['detector_backend'],'sam2-hybrid')
            self.assertEqual(summary['motion_measurement'],'withheld_experimental_memory')
            self.assertIsNone(summary['observed_path_diagonals'])
            self.assertIsNone(summary['zone_observed_samples'])

    def test_public_cli_passes_real_time_and_scene_boundaries(self):self.run_clip()
    def test_public_cli_marks_worker_failure_and_closes(self):self.run_clip(fail=True)


class MemoryRefreshTests(unittest.TestCase):
    def replay_refresh(self, *, repeated_miss=False):
        import numpy as np
        from types import SimpleNamespace
        from behavior_recorder.vision_memory import MemoryHybridPredictor
        class Detector:
            def __init__(self,root):
                self.directory=root;self.idle={'memory':0};self.workers={};self.index=0
            def predict_frame(self,frame):
                missing=self.index==1 or (repeated_miss and self.index==2)
                self.index+=1
                boxes=[] if missing else [dict(xyxy=[20,10,50,40],confidence=.8)]
                return boxes,dict(input_image='frame.png',sam3=dict(mask_name='mask.npz',predictions=[]),
                                  route=dict(selected_auxiliary_indices=[]))
            def close(self):pass
        class Memory:
            process=SimpleNamespace(pid=0)
            def __init__(self):self.alive=False
            def request(self,operation,**payload):
                if operation=='reset':self.alive=False
                if operation in ('reset','park'):return dict(idle_mps=dict(driver_bytes=0))
                if payload['seed'] is not None:self.alive=True
                if not self.alive:raise AssertionError('Propagated without a live neural session')
                return dict(image_sha256=payload['image_sha256'],mps=dict(driver_bytes=0),
                    predictions=[dict(xyxy=[20,10,50,40],confidence=1.,object_slot=1)],
                    visible_objects=1,seeded_objects=1)
            def close(self):pass
        with tempfile.TemporaryDirectory() as directory:
            predictor=MemoryHybridPredictor.__new__(MemoryHybridPredictor)
            predictor.directory=Path(directory);(predictor.directory/'frames').mkdir()
            predictor.card=dict(model_id='fixture');predictor.clock=self.clock()
            predictor.detector=Detector(predictor.directory);predictor.memory=Memory()
            predictor.index=predictor.generation=0;predictor.active=predictor.closed=False
            try:
                return [predictor.predict_frame(np.zeros((80,100,3),dtype=np.uint8),offset_seconds=i*.5005)
                        for i in range(23)]
            finally:predictor.close()

    def test_periodic_miss_runs_current_frame_memory_without_losing_session(self):
        rows=self.replay_refresh()
        self.assertEqual(len(rows[20][0]),1,'A failed detector refresh erased a live temporal observation')
        self.assertEqual(rows[20][0][0]['memory_object_id'],rows[19][0][0]['memory_object_id'])
        self.assertEqual(rows[21][1]['reset_reason'],'refresh_retry')
        self.assertEqual(len(rows[21][0]),1)

    def test_second_detector_miss_discards_memory_instead_of_self_renewing(self):
        rows=self.replay_refresh(repeated_miss=True)
        self.assertEqual(len(rows[20][0]),1)
        self.assertEqual(rows[21][0],[])
        self.assertEqual(rows[22][1]['reset_reason'],'missing_object')

    def clock(self):
        from behavior_recorder.vision_memory import MemoryClock
        return MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120,refresh_retry_frames=1)

    def advance_to_refresh(self,clock):
        for index in range(21):reason=clock.advance((100,80),index*.5005)
        self.assertEqual(reason,'periodic_detection')

    def test_one_empty_refresh_retains_original_age_until_retry_commits(self):
        clock=self.clock();self.advance_to_refresh(clock)
        self.assertTrue(clock.can_defer_refresh('periodic_detection'))
        clock.defer_refresh()
        self.assertEqual(clock.started,0.)
        self.assertEqual(clock.advance((100,80),10.5105),'refresh_retry')
        self.assertFalse(clock.can_defer_refresh('refresh_retry'))
        clock.commit_refresh()
        self.assertEqual(clock.started,10.5105)
        self.assertIsNone(clock.advance((100,80),11.011))

    def test_deferred_refresh_never_overrides_scene_gap_resolution_or_missing_mask(self):
        for kind in ('scene','gap','resolution','missing'):
            with self.subTest(kind=kind):
                clock=self.clock();self.advance_to_refresh(clock);clock.defer_refresh()
                clock.redetect=kind=='missing'
                reason=clock.advance((120,80) if kind=='resolution' else (100,80),
                                     11. if kind=='gap' else 10.5105,cut=kind=='scene')
                self.assertEqual(reason,dict(scene='scene_cut',gap='time_gap',resolution='resolution_change',missing='missing_object')[kind])
                self.assertFalse(clock.can_defer_refresh(reason))

    def test_retry_cannot_extend_frame_limit_or_default_recipe(self):
        from behavior_recorder.vision_memory import MemoryClock
        clock=MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120)
        self.advance_to_refresh(clock)
        self.assertFalse(clock.can_defer_refresh('periodic_detection'))
        clock=self.clock()
        for index in range(121):reason=clock.advance((100,80),index*.09)
        self.assertFalse(clock.can_defer_refresh(reason))

    def test_worker_age_guard_allows_only_one_bounded_extra_forward(self):
        from behavior_recorder import vision_memory_worker as worker
        validate=getattr(worker,'validate_memory_step',None)
        self.assertIsNotNone(validate,'Worker has no independently enforced retry age bound')
        self.assertFalse(validate(9.,0.,9.5,19,.6,retry_used=False,allow_refresh_retry=False))
        self.assertTrue(validate(9.51,0.,10.01,20,.6,retry_used=False,allow_refresh_retry=True))
        for last,offset,index,used,allowed in [(9.51,10.01,20,False,False),
                (10.01,10.51,21,True,True),(10.2,10.7,21,False,True),
                (9.51,10.01,120,False,True),(9.,10.01,20,False,True)]:
            with self.subTest(offset=offset,index=index,used=used,allowed=allowed),self.assertRaises(RecorderError):
                validate(last,0.,offset,index,.6,retry_used=used,allow_refresh_retry=allowed)


if __name__=='__main__':unittest.main()
