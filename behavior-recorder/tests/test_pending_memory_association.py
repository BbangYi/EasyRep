import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_tracking import VideoTracker


class PendingMemoryAssociationTests(unittest.TestCase):
    def tracker(self, enabled=True):
        return VideoTracker(dict(confidence=.4, sample_fps=2, max_gap_seconds=.6,
            max_step_diagonals=.15), 500, 500, fuse_confirmation_score=False,
            memory_association=True, memory_pending_association=enabled)

    def box(self, coords=(50,50,80,250), memory='1:1', confidence=1.):
        return dict(xyxy=list(coords), confidence=confidence, memory_object_id=memory)

    def test_first_hit_state_can_confirm_after_pose_change(self):
        tracker=self.tracker()
        first=tracker.update([self.box()],0)[0][0]
        self.assertNotEqual(first['identity_status'],'active')
        rows,_,events=tracker.update([self.box((50,175,240,245))],.5)
        self.assertEqual(rows[0]['identity_status'],'active')
        self.assertEqual(rows[0]['track_id'],first['track_id'])
        self.assertTrue(any(e['kind']=='memory_pending_association_recovered' for e in events))

    def test_library_pending_candidate_can_confirm_without_waiting_for_static_pose(self):
        tracker=self.tracker();tracker.update([],0)
        first=tracker.update([self.box()],.5)[0][0]
        self.assertIsNone(first['track_id'])
        rows,_,events=tracker.update([self.box((50,175,240,245))],1.)
        self.assertEqual(rows[0]['identity_status'],'active')
        self.assertTrue(any(e['kind']=='confirmed_pending' for e in events))
        self.assertTrue(any(e['kind']=='memory_pending_association_recovered' for e in events))

    def test_same_pending_slot_does_not_skip_two_strong_observations(self):
        for first_score,second_score in [(.3,1.),(1.,.3)]:
            with self.subTest(first=first_score,second=second_score):
                tracker=self.tracker();tracker.update([],0)
                tracker.update([self.box(confidence=first_score)],.5)
                rows,_,_=tracker.update([self.box((50,175,240,245),confidence=second_score)],1.)
                self.assertNotEqual(rows[0]['identity_status'],'active')

    def test_repeated_pose_changes_do_not_create_competing_shadow_pending_tracks(self):
        tracker=self.tracker();tracker.update([],0);tracker.update([self.box()],.5)
        identity=None
        for offset,coords in [(1.,(50,175,240,245)),(1.5,(50,50,80,250)),
                              (2.,(50,175,240,245)),(2.5,(50,50,80,250))]:
            rows,_,_=tracker.update([self.box(coords)],offset)
            self.assertEqual(rows[0]['identity_status'],'active')
            identity=identity or rows[0]['track_id']
            self.assertEqual(rows[0]['track_id'],identity)
            self.assertFalse(tracker.pending)

    def test_pending_association_requires_explicit_boolean_and_memory_mode(self):
        for enabled,memory in [(1,True),('yes',True),(True,False)]:
            with self.subTest(enabled=enabled,memory=memory), self.assertRaises(RecorderError):
                VideoTracker(dict(confidence=.4,sample_fps=2,max_gap_seconds=.6,max_step_diagonals=.15),
                    500,500,memory_association=memory,memory_pending_association=enabled)

    def test_pending_slot_cannot_bridge_session_scene_gap_absence_or_jump(self):
        for kind in ['session','scene','gap','absence','jump']:
            with self.subTest(kind=kind):
                tracker=self.tracker();tracker.update([],0);tracker.update([self.box()],.5)
                if kind=='scene':tracker.reset_for_scene_change()
                if kind=='absence':tracker.update([],1.)
                offset=2. if kind=='gap' else 1.5 if kind=='absence' else 1.
                row=self.box((380,380,480,480) if kind=='jump' else (50,175,240,245),
                    memory='2:1' if kind=='session' else '1:1')
                rows,_,events=tracker.update([row],offset)
                self.assertNotEqual(rows[0]['identity_status'],'active')
                self.assertFalse(any(e['kind']=='memory_pending_association_recovered' for e in events))

    def test_merged_pending_animals_are_not_confirmed_as_one(self):
        tracker=self.tracker();tracker.update([],0)
        tracker.update([self.box(),self.box((200,50,230,250),memory='1:2')],.5)
        rows,_,events=tracker.update([self.box((50,50,250,250))],1.)
        self.assertNotEqual(rows[0]['identity_status'],'active')
        self.assertFalse(any(e['kind']=='memory_pending_association_recovered' for e in events))

    def test_disabled_recipe_keeps_previous_pending_behavior(self):
        tracker=self.tracker(False);tracker.update([],0);tracker.update([self.box()],.5)
        rows,_,events=tracker.update([self.box((50,175,240,245))],1.)
        self.assertNotEqual(rows[0]['identity_status'],'active')
        self.assertFalse(any(e['kind']=='memory_pending_association_recovered' for e in events))


if __name__=='__main__':unittest.main()
