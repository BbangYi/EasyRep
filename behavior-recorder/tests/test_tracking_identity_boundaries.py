"""Source-time and neural-object resets must not inherit active confirmation."""
import tempfile
import unittest
from pathlib import Path

from behavior_recorder.vision_tracking import VideoTracker
from behavior_recorder.vision_video import observation


class TrackingIdentityBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from behavior_recorder.vision_model import runtime
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        runtime(Path(cls.temporary.name), 1)

    def tracker(self, *, memory=False, pending=False):
        self.config = dict(confidence=.4, sample_fps=3, max_gap_seconds=.5,
                           track_lost_seconds=1., max_step_diagonals=.15, zones={})
        return VideoTracker(self.config, 200, 100, fuse_confirmation_score=False,
                            memory_association=memory, memory_pending_association=pending)

    def box(self, memory='1:1'):
        return dict(xyxy=[10, 20, 30, 40], confidence=.9, memory_object_id=memory)

    def test_elapsed_gap_requires_reconfirmation_without_an_empty_update(self):
        # Removing the elapsed-time check would falsely keep the delayed frame active.
        for memory, pending in [(False, False), (True, False), (True, True)]:
            with self.subTest(memory=memory, pending=pending):
                tracker = self.tracker(memory=memory, pending=pending)
                tracker.update([self.box()], 0)
                before = tracker.update([self.box()], .2)[0][0]
                delayed, _, events = tracker.update([self.box()], .9)
                self.assertEqual(delayed[0]['track_id'], before['track_id'])
                self.assertEqual(delayed[0]['identity_status'], 'reacquired')
                self.assertFalse(delayed[0]['motion_allowed'])
                self.assertTrue(any(e['kind'] == 'reacquired' for e in events))
                row = observation(delayed, None, .9, 200, 100, self.config)
                self.assertEqual(row['status'], 'track_pending')
                confirmed = tracker.update([self.box()], 1.1)[0]
                self.assertEqual(confirmed[0]['identity_status'], 'active')
                next_row = observation(confirmed, row, 1.1, 200, 100, self.config)
                self.assertIsNone(next_row['speed_diagonals_per_second'])

    def test_new_memory_object_cannot_inherit_an_active_track_at_the_same_location(self):
        # A geometric ByteTrack match must not bypass a neural session/object reset.
        for pending in [False, True]:
            for memory in ['2:1', '1:2']:
                with self.subTest(pending=pending, memory=memory):
                    tracker = self.tracker(memory=True, pending=pending)
                    tracker.update([self.box()], 0)
                    old = tracker.update([self.box()], .2)[0][0]
                    first, _, events = tracker.update([self.box(memory)], .4)
                    self.assertNotEqual(first[0]['track_id'], old['track_id'])
                    self.assertEqual(first[0]['identity_status'], 'tentative')
                    self.assertFalse(first[0]['motion_allowed'])
                    self.assertTrue(any(e.get('reason') == 'memory_identity_changed' for e in events))
                    second = tracker.update([self.box(memory)], .6)[0][0]
                    self.assertEqual(second['track_id'], first[0]['track_id'])
                    self.assertEqual(second['identity_status'], 'active')

    def test_new_memory_object_cannot_inherit_a_pending_first_hit(self):
        # An unconfirmed library track is also tied to the original neural object.
        for pending in [False, True]:
            with self.subTest(pending=pending):
                tracker = self.tracker(memory=True, pending=pending)
                tracker.update([], 0)
                first = tracker.update([self.box()], .2)[0][0]
                self.assertIsNone(first['track_id'])
                changed, _, events = tracker.update([self.box('2:1')], .4)
                self.assertFalse(changed[0]['motion_allowed'])
                self.assertNotEqual(changed[0]['identity_status'], 'active')
                self.assertFalse(any(e['kind'] == 'confirmed_pending' for e in events))
                confirmed = tracker.update([self.box('2:1')], .6)[0][0]
                self.assertEqual(confirmed['identity_status'], 'active')


if __name__ == '__main__':
    unittest.main()
