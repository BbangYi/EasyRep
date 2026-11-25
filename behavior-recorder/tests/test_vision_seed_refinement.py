import unittest
import numpy as np
from behavior_recorder.core import RecorderError
from behavior_recorder.vision_seed_refinement import crop_requests, choose_refinement

class SeedRefinementTests(unittest.TestCase):
    def setUp(self):
        self.anchor=dict(xyxy=[40,40,60,60],confidence=.9)
        self.detail=dict(accepted=True,verifier_score=.95,prediction_index=0,
                         clipped_proposal=dict(xyxy=[40,10,60,60],confidence=.8))

    def test_partial_extent_requests_a_native_padded_crop(self):
        self.assertEqual(crop_requests([self.anchor],[self.detail],[],100,100),
                         [dict(object_index=0,primary_prediction_index=0,crop_xyxy=[35,0,65,73])])

    def test_weak_or_ambiguous_extent_does_not_trigger_an_extra_pass(self):
        weak=dict(self.detail,clipped_proposal=dict(self.detail['clipped_proposal'],confidence=.2))
        self.assertEqual(crop_requests([self.anchor],[weak],[],100,100),[])
        self.assertEqual(crop_requests([self.anchor],[self.detail,self.detail],[],100,100),[])

    def test_extent_crossing_another_animal_is_not_requested(self):
        neighbor=dict(xyxy=[40,15,60,25],confidence=.9)
        self.assertEqual(crop_requests([self.anchor,neighbor],[self.detail],[],100,100),[])
        self.assertEqual(crop_requests([self.anchor],[self.detail],[neighbor],100,100),[])

    def test_retained_body_with_longer_tail_is_selected(self):
        old=np.zeros((50,50),bool);old[20:30,20:30]=True
        new=old.copy();new[3:20,24:26]=True
        chosen,details=choose_refinement(old,np.zeros((0,50,50),bool),new[None])
        self.assertEqual(chosen,0);self.assertEqual(details[0]['retained_fraction'],1.)

    def test_merge_loss_of_body_or_ambiguous_candidates_are_rejected(self):
        old=np.zeros((50,50),bool);old[20:30,20:30]=True
        other=np.zeros_like(old);other[3:7,24:26]=True
        merged=old.copy();merged[3:20,24:26]=True
        self.assertIsNone(choose_refinement(old,other[None],merged[None])[0])
        lost=merged.copy();lost[20:28,20:30]=False
        self.assertIsNone(choose_refinement(old,np.zeros((0,50,50),bool),lost[None])[0])
        self.assertIsNone(choose_refinement(old,np.zeros((0,50,50),bool),np.stack([merged,merged]))[0])
        self.assertIsNone(choose_refinement(old,np.zeros((0,50,50),bool),old[None])[0])

    def test_shape_dtype_and_empty_anchor_are_rejected(self):
        old=np.ones((5,5),bool)
        for anchor,others,candidates in [(old.astype(float),np.zeros((0,5,5),bool),old[None]),(old,np.zeros((0,4,5),bool),old[None]),(np.zeros_like(old),np.zeros((0,5,5),bool),old[None])]:
            with self.assertRaises(RecorderError):choose_refinement(anchor,others,candidates)

if __name__=='__main__':unittest.main()
