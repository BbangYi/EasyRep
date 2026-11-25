import unittest
from behavior_recorder.core import RecorderError
from behavior_recorder.vision_tracking import VideoTracker

class MemorySlotAssociationTests(unittest.TestCase):
    def tracker(self, enabled=True):
        config=dict(confidence=.4,sample_fps=2,max_gap_seconds=.6,max_step_diagonals=.15)
        return VideoTracker(config,500,500,fuse_confirmation_score=False,memory_association=enabled)

    def box(self,coords=(50,50,80,250),memory='1:1'):
        return dict(xyxy=list(coords),confidence=1.,memory_object_id=memory)

    def established(self,tracker):
        tracker.update([self.box()],0)
        return tracker.update([self.box()],.5)[0][0]['track_id']

    def test_same_memory_slot_preserves_identity_across_pose_and_new_byte_id(self):
        tracker=self.tracker();identity=self.established(tracker)
        for t in [1.,1.5]:
            rows,_,events=tracker.update([self.box((50,175,240,245))],t)
            self.assertEqual(rows[0]['track_id'],identity)
            self.assertEqual(rows[0]['identity_status'],'active')
            self.assertTrue(any(e['kind']=='memory_association_recovered' for e in events))

    def test_disabled_mode_retains_original_tracker_behavior(self):
        tracker=self.tracker(False);self.established(tracker)
        rows,_,events=tracker.update([self.box((50,175,240,245))],1.)
        self.assertIsNone(rows[0]['track_id'])
        self.assertFalse(any(e['kind']=='memory_association_recovered' for e in events))

    def test_new_session_gap_missing_frame_and_jump_do_not_recover(self):
        for kind in ['new_session','gap','missing','jump','scene']:
            with self.subTest(kind=kind):
                tracker=self.tracker();old=self.established(tracker)
                if kind=='missing':tracker.update([],1.)
                if kind=='scene':tracker.reset_for_scene_change()
                t=2. if kind=='gap' else 1.5 if kind=='missing' else 1.
                box=self.box((380,380,480,480) if kind=='jump' else (50,175,240,245),memory='2:1' if kind=='new_session' else '1:1')
                rows,_,events=tracker.update([box],t)
                self.assertFalse(any(e['kind']=='memory_association_recovered' for e in events))
                self.assertFalse(rows[0]['track_id']==old and rows[0]['identity_status']=='active')

    def test_merged_neighbor_and_duplicate_memory_slots_are_rejected(self):
        tracker=self.tracker();a=self.box();b=self.box((200,50,230,250),'1:2')
        tracker.update([a,b],0);tracker.update([a,b],.5)
        rows,_,events=tracker.update([self.box((50,50,250,250))],1.)
        self.assertFalse(any(e['kind']=='memory_association_recovered' for e in events))
        self.assertNotEqual(rows[0]['identity_status'],'active')
        with self.assertRaises(RecorderError):self.tracker().update([self.box(),self.box((300,50,330,250))],0)

if __name__=='__main__':unittest.main()
