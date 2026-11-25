import unittest
import tempfile
from pathlib import Path

from behavior_recorder.core import RecorderError, read_json
from behavior_recorder.vision_tracking import SeededTarget, VideoTracker, tracking_options
from behavior_recorder.vision_video import observation
from behavior_recorder.behavior_windows import window_observations

ROOT = Path(__file__).resolve().parents[1]


def box(x, y=20, w=20, score=0.9):
    return {"xyxy": [x, y, x+w, y+20], "confidence": score}


class AssociationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from behavior_recorder.vision_model import runtime
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        runtime(Path(cls.temporary.name), 2)

    def setUp(self):
        self.config = read_json(ROOT / "examples/vision.tracking.json")
        self.tracker = VideoTracker(self.config, 200, 100)

    def test_same_object_keeps_id_and_confirmation_requires_two_observations(self):
        first, _, _ = self.tracker.update([box(10)], 0)
        second, _, _ = self.tracker.update([box(12)], 0.2)
        self.assertEqual(first[0]["track_id"], second[0]["track_id"])
        self.assertEqual(first[0]["identity_status"], "tentative")
        self.assertEqual(second[0]["identity_status"], "active")

    def test_scene_reset_starts_new_segment_without_reusing_confirmation(self):
        self.tracker.update([box(10)], 0)
        before, _, _ = self.tracker.update([box(11)], .2)
        events = self.tracker.reset_for_scene_change()
        first, lost, _ = self.tracker.update([box(11)], .4)
        second, _, _ = self.tracker.update([box(12)], .6)
        self.assertNotEqual(first[0]['track_id'], before[0]['track_id'])
        self.assertEqual(events[0]['ended_track_ids'], [before[0]['track_id']])
        self.assertEqual(lost, [])
        self.assertFalse(first[0]['motion_allowed'])
        self.assertEqual(second[0]['identity_status'], 'active')

    def test_scene_reset_preserves_timestamp_validation_and_clears_pending(self):
        self.tracker.update([], 0)
        self.tracker.update([box(10)], .2)
        self.tracker.reset_for_scene_change()
        with self.assertRaises(RecorderError):
            self.tracker.update([box(10)], .1)
        first, _, _ = self.tracker.update([box(10)], .4)
        self.assertFalse(first[0]['motion_allowed'])

    def test_scene_reset_does_not_reuse_another_trackers_library_ids(self):
        self.tracker.update([box(10)], 0)
        other = VideoTracker(self.config, 200, 100)
        other.update([box(10)], 0)
        self.tracker.reset_for_scene_change()
        other.update([box(11), box(150)], .2)
        tracked, _, _ = other.update([box(12), box(149)], .4)
        self.assertTrue(all(b['identity_status'] == 'active' for b in tracked))
        self.assertEqual(len({b['track_id'] for b in tracked}), 2)

    def test_two_separated_objects_do_not_merge(self):
        first, _, _ = self.tracker.update([box(10), box(150)], 0)
        second, _, _ = self.tracker.update([box(12), box(148)], 0.2)
        self.assertEqual([b["track_id"] for b in first], [b["track_id"] for b in second])
        self.assertEqual(len({b["track_id"] for b in second}), 2)
        self.assertTrue(all(b["motion_allowed"] for b in second))

    def test_late_arrival_activates_on_second_strong_observation(self):
        self.tracker.update([], 0)
        first, _, _ = self.tracker.update([box(10)], 0.2)
        second, _, _ = self.tracker.update([box(11)], 0.4)
        self.assertIsNone(first[0]['track_id'])
        self.assertIsNotNone(second[0]['track_id'])
        self.assertEqual(second[0]['identity_status'], 'active')
        previous = observation(first, None, 0.2, 200, 100, self.config)
        current = observation(second, previous, 0.4, 200, 100, self.config)
        self.assertEqual(current['status'], 'observed')
        self.assertIsNone(current['speed_diagonals_per_second'])

    def test_weak_late_arrival_does_not_replace_second_strong_observation(self):
        self.tracker.update([], 0)
        self.tracker.update([box(10)], 0.2)
        weak, _, _ = self.tracker.update([box(11, score=0.2)], 0.4)
        first, _, _ = self.tracker.update([box(12)], 0.6)
        second, _, _ = self.tracker.update([box(13)], 0.8)
        self.assertFalse(weak[0]['motion_allowed'])
        self.assertFalse(first[0]['motion_allowed'])
        self.assertEqual(second[0]['identity_status'], 'active')

    def test_pending_jump_cannot_inherit_confirmation(self):
        self.tracker.update([], 0)
        self.tracker.update([box(10, w=120)], 0.2)
        jumped, _, _ = self.tracker.update([box(52, w=120)], 0.4)
        settled, _, _ = self.tracker.update([box(54, w=120)], 0.6)
        self.assertFalse(jumped[0]['motion_allowed'])
        self.assertTrue(settled[0]['motion_allowed'])

    def test_pending_confirmation_requires_short_elapsed_time(self):
        self.tracker.update([], 0)
        self.tracker.update([box(10)], 0.2)
        after, _, _ = self.tracker.update([box(11)], 1.0)
        self.assertFalse(after[0]['motion_allowed'])

    def test_merged_pending_tracks_remain_ambiguous(self):
        self.tracker.update([], 0)
        self.tracker.update([box(40), box(70)], 0.2)
        merged, _, _ = self.tracker.update([box(40, w=50)], 0.4)
        self.assertEqual(merged[0]['identity_status'], 'ambiguous_association')
        self.assertFalse(merged[0]['motion_allowed'])

    def test_unconfirmed_neighbor_does_not_break_an_established_track(self):
        self.tracker.update([box(40, w=40)], 0)
        active, _, _ = self.tracker.update([box(41, w=40)], 0.2)
        self.tracker.update([box(42, w=40), box(70, w=40)], 0.4)
        continued, _, _ = self.tracker.update([box(43, w=40)], 0.6)
        self.assertEqual(continued[0]['track_id'], active[0]['track_id'])
        self.assertEqual(continued[0]['identity_status'], 'active')

    def test_distinct_continuations_with_partial_box_overlap_are_not_a_merge(self):
        first, _, _ = self.tracker.update([box(40, w=40), box(65, w=40)], 0)
        second, _, events = self.tracker.update([box(41, w=40), box(66, w=40)], 0.2)
        self.assertEqual([b['track_id'] for b in first], [b['track_id'] for b in second])
        self.assertEqual([b['identity_status'] for b in second], ['active', 'active'])
        self.assertTrue(all(b['motion_allowed'] for b in second))
        self.assertFalse(any(e['kind'] == 'ambiguous_association' for e in events))

    def test_partial_overlap_still_abstains_when_neighbor_has_no_continuation(self):
        self.tracker.update([box(40, w=40), box(65, w=40)], 0)
        self.tracker.update([box(41, w=40), box(66, w=40)], 0.2)
        result, _, _ = self.tracker.update([box(42, w=40)], 0.4)
        self.assertEqual(result[0]['identity_status'], 'ambiguous_association')
        self.assertFalse(result[0]['motion_allowed'])

    def test_one_box_covering_both_partially_overlapping_tracks_is_still_ambiguous(self):
        self.tracker.update([box(40, w=40), box(65, w=40)], 0)
        self.tracker.update([box(41, w=40), box(66, w=40)], 0.2)
        result, _, _ = self.tracker.update([box(41, w=65)], 0.4)
        self.assertEqual(result[0]['identity_status'], 'ambiguous_association')
        self.assertFalse(result[0]['motion_allowed'])

    def test_short_gap_can_reassociate_but_does_not_invent_motion(self):
        first, _, _ = self.tracker.update([box(10)], 0)
        strong, _, _ = self.tracker.update([box(11)], 0.2)
        absent, lost, _ = self.tracker.update([], 0.4)
        self.assertEqual(absent, [])
        self.assertEqual(lost[0]["track_id"], first[0]["track_id"])
        back, _, events = self.tracker.update([box(12)], 0.6)
        self.assertEqual(back[0]["track_id"], first[0]["track_id"])
        self.assertFalse(back[0]["motion_allowed"])
        self.assertEqual(back[0]["identity_status"], "reacquired")
        self.assertIsNone(observation(back, None, 0.6, 200, 100, self.config)["speed_diagonals_per_second"])

    def test_actual_elapsed_time_expires_even_without_intermediate_updates(self):
        first, _, _ = self.tracker.update([box(10)], 0)
        self.tracker.update([box(10)], 0.2)
        after, _, events = self.tracker.update([box(10)], 3)
        after, _, _ = self.tracker.update([box(10)], 3.2)
        self.assertNotEqual(after[0]["track_id"], first[0]["track_id"])
        self.assertIn("expired", [event["kind"] for event in events])

    def test_overlapping_candidates_are_not_asserted_as_identity(self):
        self.tracker.update([box(40), box(70)], 0)
        self.tracker.update([box(43), box(67)], 0.2)
        overlap, _, _ = self.tracker.update([box(48, w=35), box(55, w=30)], 0.4)
        self.assertTrue(all(b["identity_status"] == "ambiguous_association" for b in overlap))
        self.assertTrue(all(not b["motion_allowed"] for b in overlap))

    def test_merged_box_covering_two_recent_tracks_is_ambiguous(self):
        self.tracker.update([box(40), box(70)], 0)
        self.tracker.update([box(40), box(70)], 0.2)
        merged, _, _ = self.tracker.update([box(40, w=50)], 0.4)
        self.assertEqual(merged[0]["identity_status"], "ambiguous_association")

    def test_low_confidence_preserves_association_not_activity_evidence(self):
        first, _, _ = self.tracker.update([box(10)], 0)
        weak, _, _ = self.tracker.update([box(11, score=0.2)], 0.2)
        self.assertEqual(weak[0]["track_id"], first[0]["track_id"])
        self.assertEqual(weak[0]["identity_status"], "low_confidence")
        self.assertFalse(weak[0]["motion_allowed"])

    def test_jump_starts_one_new_segment_and_never_bridges_motion(self):
        self.tracker.update([box(10, w=120)], 0)
        before, _, _ = self.tracker.update([box(12, w=120)], 0.2)
        jumped, _, jump_events = self.tracker.update([box(52, w=120)], 0.4)
        settled, _, settled_events = self.tracker.update([box(54, w=120)], 0.6)
        self.assertNotEqual(before[0]['track_id'], jumped[0]['track_id'])
        self.assertEqual(jumped[0]['identity_status'], 'implausible_jump')
        self.assertFalse(jumped[0]['motion_allowed'])
        self.assertEqual(jumped[0]['track_id'], settled[0]['track_id'])
        self.assertEqual(settled[0]['identity_status'], 'active')
        self.assertEqual(self.tracker.summary()['segments_created'], 2)
        self.assertEqual([e['reason'] for e in jump_events if e['kind']=='segment_break'], ['jump'])
        self.assertFalse(any(e['kind']=='segment_break' for e in settled_events))
        previous = observation(jumped, None, 0.4, 200, 100, self.config)
        current = observation(settled, previous, 0.6, 200, 100, self.config)
        self.assertEqual(current['status'], 'observed')
        self.assertIsNone(current['step_diagonals'])
        self.assertIsNone(current['speed_diagonals_per_second'])

    def test_weak_box_after_jump_does_not_count_as_confirmation(self):
        self.tracker.update([box(10, w=120)], 0)
        self.tracker.update([box(12, w=120)], 0.2)
        jumped, _, _ = self.tracker.update([box(52, w=120)], 0.4)
        weak, _, _ = self.tracker.update([box(53, w=120, score=0.2)], 0.6)
        first, _, _ = self.tracker.update([box(54, w=120)], 0.8)
        confirmed, _, _ = self.tracker.update([box(55, w=120)], 1.0)
        self.assertEqual([b[0]['track_id'] for b in (jumped,weak,first,confirmed)], [jumped[0]['track_id']]*4)
        self.assertFalse(weak[0]['motion_allowed'])
        self.assertFalse(first[0]['motion_allowed'])
        self.assertTrue(confirmed[0]['motion_allowed'])

    def test_real_overlap_still_breaks_identity_on_recovery(self):
        self.tracker.update([box(40)], 0)
        active, _, _ = self.tracker.update([box(41)], 0.2)
        ambiguous, _, _ = self.tracker.update([box(42),box(46)], 0.4)
        clear, _, events = self.tracker.update([box(43)], 0.6)
        confirmed, _, _ = self.tracker.update([box(44)], 0.8)
        self.assertTrue(all(not b['motion_allowed'] for b in ambiguous))
        self.assertNotEqual(active[0]['track_id'], clear[0]['track_id'])
        self.assertEqual(clear[0]['track_id'], confirmed[0]['track_id'])
        self.assertFalse(clear[0]['motion_allowed'])
        self.assertTrue(confirmed[0]['motion_allowed'])
        self.assertEqual([e['reason'] for e in events if e['kind']=='segment_break'], ['ambiguous_association'])

    def test_unconfirmed_track_also_expires_by_source_time(self):
        self.tracker.update([], 0)
        first, _, _ = self.tracker.update([box(10)], 0.2)
        self.assertIsNone(first[0]["track_id"])
        after, _, _ = self.tracker.update([box(10)], 3)
        self.assertIsNone(after[0]["track_id"])

    def test_invalid_input_and_timestamps_fail_without_mutation(self):
        self.tracker.update([box(10)], 0)
        for boxes, time in (([box(float("nan"))], 0.2), ([box(195)], 0.2), ([box(10)], 0)):
            with self.assertRaises(RecorderError):
                self.tracker.update(boxes, time)
        self.assertEqual(self.tracker.frame_number, 1)


class WindowIdentityTests(unittest.TestCase):
    def test_distinct_tracks_are_not_pooled_into_one_animal_baseline(self):
        rows = [{"offset_seconds": i/10, "status":"observed", "track_id":1 if i < 25 else 2,
                 "center":[0.4,0.5], "speed_diagonals_per_second":0.01} for i in range(51)]
        summary = {"source":{"duration_seconds":5, "sha256":"source", "provenance":"real_camera"},
                   "model_id":"model", "config":{"max_gap_seconds":0.6,"zones":{}}}
        result = window_observations(summary, rows, {}, window_seconds=5)["windows"][0]
        self.assertGreater(result["coverage"], 0.8)
        self.assertEqual(result["quality"], "insufficient_observation")
        self.assertEqual(result["quality_reason"], "multiple_track_segments")
        self.assertIsNone(result["features"])


class SeededTargetTests(unittest.TestCase):
    def setUp(self):
        self.config=read_json(ROOT/'examples/vision.tracking.json')
        self.config['target_seed']={'source_sha256':'a'*64,'xyxy':[0.1,0.2,0.2,0.4]}
        self.target=SeededTarget(self.config,200,100)

    def test_background_box_cannot_win_just_because_its_score_is_higher(self):
        candidates=[{'xyxy':[0,0,200,100],'confidence':0.99},box(20,score=0.8)]
        chosen,reason=self.target.select(candidates,0)
        self.assertEqual(chosen,[candidates[1]])
        self.assertEqual(reason,'seed_matched')

    def test_near_tied_candidates_abstain_and_do_not_move_anchor(self):
        self.assertEqual(self.target.select([box(20),box(21)],0),([], 'ambiguous_seed_candidates'))
        self.assertEqual(self.target.box,[20,20,40,40])

    def test_weak_duplicate_does_not_override_strong_matching_body(self):
        strong=box(21,score=0.9)
        self.assertEqual(self.target.select([box(20,score=0.15),strong],0)[0],[strong])

    def test_expiry_requires_new_selection_even_if_box_returns_later(self):
        self.target.select([box(20)],0)
        self.assertEqual(self.target.select([],0.5)[0],[])
        self.assertEqual(self.target.select([box(20)],2)[1],'seed_lost_requires_new_selection')
        self.assertEqual(self.target.select([box(20)],2.2)[0],[])

    def test_invalid_seed_bounds_and_source_hash_are_rejected(self):
        for seed in ({'source_sha256':'x','xyxy':[0,0,1,1]},
                     {'source_sha256':'a'*64,'xyxy':[0.5,0,0.4,1]},
                     {'source_sha256':'a'*64,'xyxy':[0,0,float('nan'),1]}):
            with self.assertRaises(RecorderError):tracking_options({**self.config,'target_seed':seed})


class HybridAssociationTests(AssociationTests):
    """The hybrid confirmation mode must preserve every existing association guard."""
    def setUp(self):
        self.config = read_json(ROOT / "examples/vision.tracking.json")
        self.tracker = VideoTracker(self.config, 200, 100, fuse_confirmation_score=False)


if __name__ == "__main__":
    unittest.main()
