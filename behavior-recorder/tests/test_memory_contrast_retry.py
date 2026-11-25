import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from behavior_recorder import vision_memory
from behavior_recorder.core import RecorderError, digest


class ContrastRetryTests(unittest.TestCase):
    def exercise(self, *, enabled=True, original_supported=False, retry_supported=True,
                 retry_fails=False, mask_seed=False, temporal_supported=False):
        frame = np.arange(80*100*3, dtype=np.uint16).reshape(80,100,3).astype(np.uint8) // 4
        saved = frame.copy()
        box = dict(xyxy=[20,10,50,40], confidence=.8)
        class Detector:
            workers = {}
            def __init__(self, root):
                self.directory=root; self.idle={'memory':0}; self.inputs=[]; self.closed=False
                (root/'frames').mkdir(parents=True); (root/'masks').mkdir()
            def predict_frame(self, image):
                self.inputs.append(image.copy()); index=len(self.inputs)-1
                if retry_fails and index: raise RuntimeError('contrast detector failed')
                supported=(original_supported or temporal_supported) if index==0 else retry_supported
                path=self.directory/'frames'/f'{index}.png'
                Image.fromarray(image[:,:,::-1]).save(path)
                masks=np.zeros((1 if supported else 0,80,100),dtype=bool)
                if supported: masks[0,10:40,20:50]=True
                mask=self.directory/'masks'/f'{index}.npz'
                np.savez_compressed(mask,masks=masks)
                return ([] if temporal_supported else [dict(box)]), dict(input_image=str(path),input_image_sha256=digest(path),
                    mask_artifact=str(mask),mask_sha256=digest(mask),
                    sam3=dict(mask_name=mask.name,predictions=[dict(box,mask_index=0)] if supported else []),
                    primary=dict(inference=dict(raw_grounding_predictions=[dict(box,confidence=.95)] if temporal_supported else [],verifier_details=[])),
                    route=dict(selected_auxiliary_indices=[0] if supported and mask_seed else []))
            def close(self): self.closed=True
        class Memory:
            process=SimpleNamespace(pid=0)
            def __init__(self): self.requests=[]; self.closed=False
            def request(self, operation, **payload):
                if operation in ('park','reset'): return dict(idle_mps=dict(driver_bytes=0))
                self.requests.append(payload)
                image=np.asarray(Image.open(payload['image']).convert('RGB'))
                if not np.array_equal(image,saved[:,:,::-1]): raise AssertionError('Temporal model saw enhanced pixels')
                if payload['seed']['kind']=='mask':
                    with np.load(payload['seed']['path'],allow_pickle=False) as archive:
                        if archive['masks'].shape!=(1,80,100): raise AssertionError('Wrong mask geometry')
                return dict(image_sha256=payload['image_sha256'],mps=dict(driver_bytes=0),
                    predictions=[dict(box,object_slot=1)],visible_objects=1,seeded_objects=1)
            def close(self): self.closed=True
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'frames').mkdir(); (root/'seeds').mkdir()
            predictor=vision_memory.MemoryHybridPredictor.__new__(vision_memory.MemoryHybridPredictor)
            predictor.directory=root
            predictor.card=dict(model_id='fixture',recipe=dict(box_seed_mask_support=1))
            if enabled: predictor.card['recipe']['empty_detection_contrast_retry']=1
            predictor.clock=vision_memory.MemoryClock(max_gap=.6,refresh_seconds=10,max_frames=120)
            predictor.detector=Detector(root/'detector'); predictor.memory=Memory()
            predictor.index=predictor.generation=0; predictor.active=predictor.closed=False
            if temporal_supported:
                predictor.card['recipe']['temporal_seed_confirmation']=1
                predictor.clock.refresh_seconds=1
                predictor.clock.advance((100,80),0); predictor.clock.advance((100,80),.5)
                predictor.active=True
                predictor.previous_temporal=dict(size=(100,80),offset_seconds=.5,consecutive_frames=2,
                    generation=0,seeded_objects=1,predictions=[dict(box,object_slot=1)])
            try:
                if retry_fails:
                    with self.assertRaisesRegex(RuntimeError,'contrast detector failed'):
                        predictor.predict_frame(frame,offset_seconds=0)
                    self.assertTrue(predictor.closed and predictor.detector.closed and predictor.memory.closed)
                    return
                boxes,evidence=predictor.predict_frame(frame,offset_seconds=1 if temporal_supported else 0)
                self.assertTrue(np.array_equal(frame,saved),'Source frame was modified')
                return boxes,evidence,predictor.detector.inputs,predictor.memory.requests
            finally: predictor.close()

    def test_retry_requires_current_mask_and_temporal_model_keeps_original_pixels(self):
        for mask_seed in (False,True):
            with self.subTest(mask_seed=mask_seed):
                boxes,evidence,inputs,requests=self.exercise(mask_seed=mask_seed)
                self.assertEqual(len(inputs),2)
                self.assertEqual(len(boxes),1)
                self.assertFalse(np.array_equal(inputs[0],inputs[1]))
                self.assertEqual(len(requests),1)
                retry=evidence['detector']['contrast_retry']
                self.assertTrue(retry['accepted'])
                self.assertEqual(retry['original']['input_image_sha256'],evidence['input_image_sha256'])
                self.assertEqual(retry['attempt']['input_image_sha256'],evidence['detector']['input_image_sha256'])
                self.assertNotEqual(evidence['detector']['input_image_sha256'],evidence['input_image_sha256'])

    def test_accepted_original_and_legacy_recipe_do_not_retry(self):
        for options in (dict(original_supported=True),dict(enabled=False)):
            with self.subTest(options=options):
                boxes,evidence,inputs,_=self.exercise(**options)
                self.assertEqual(len(inputs),1)
                self.assertNotIn('contrast_retry',evidence['detector'])
                self.assertEqual(bool(boxes),options.get('original_supported',False))

    def test_failed_retry_is_bounded_and_cannot_seed_an_unsupported_box(self):
        boxes,evidence,inputs,requests=self.exercise(retry_supported=False)
        self.assertEqual(len(inputs),2)
        self.assertEqual(boxes,[]); self.assertEqual(requests,[])
        self.assertFalse(evidence['detector']['contrast_retry']['accepted'])
        self.assertEqual(evidence['detector']['input_image_sha256'],evidence['input_image_sha256'])

    def test_retry_worker_failure_closes_both_workers(self):
        self.exercise(retry_fails=True)

    def test_current_temporal_confirmation_precedes_contrast_retry(self):
        boxes,evidence,inputs,_=self.exercise(temporal_supported=True)
        self.assertEqual(len(boxes),1); self.assertEqual(len(inputs),1)
        self.assertTrue(evidence['temporal_seed_confirmation']['accepted'])
        self.assertNotIn('contrast_retry',evidence['detector'])

    def test_transform_matches_frozen_photo_recipe_and_rejects_invalid_input(self):
        transform=getattr(vision_memory,'enhance_detection_frame',None)
        self.assertTrue(callable(transform),'Contrast retry transform is missing')
        frame=np.arange(32*48*3,dtype=np.uint16).reshape(32,48,3).astype(np.uint8)
        original=frame.copy();lab=cv2.cvtColor(frame,cv2.COLOR_BGR2LAB)
        lab[:,:,0]=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(lab[:,:,0])
        self.assertTrue(np.array_equal(transform(frame),cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)))
        self.assertTrue(np.array_equal(original,frame))
        for invalid in (frame.astype(np.float32),frame[:4],frame[:,:,0]):
            with self.subTest(shape=invalid.shape),self.assertRaises(RecorderError): transform(invalid)


if __name__=='__main__': unittest.main()
