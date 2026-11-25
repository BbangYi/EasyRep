import copy
import json
from pathlib import Path
import tempfile
import unittest

from behavior_recorder.core import RecorderError, atomic_json
from behavior_recorder.vision_tracking_eval import evaluate_video


def prediction(track_id=1, score=0.9, xyxy=None):
    return {'xyxy': xyxy or [10, 10, 30, 30], 'confidence': score,
            'track_id': track_id, 'identity_status': 'active'}


class TrackingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.analysis = self.root / 'analysis'
        self.analysis.mkdir()
        self.summary = {'source': {'sha256': 'a'*64, 'width': 100, 'height': 100,
                                   'duration_seconds': 1, 'provenance': 'synthetic_test'},
                        'model_id': 'fixture', 'config': {'confidence': 0.4, 'tracking_revision': 2},
                        'target_selection_mode': 'automatic'}
        self.rows = [{'frame_index': i, 'pts': i, 'offset_seconds': i/10,
                      'detections': [prediction()]} for i in range(4)]
        self.reference = {'schema_version': 1, 'source_sha256': 'a'*64,
                          'selection': 'complete', 'evaluation_target': 'visible_lizard_extent',
                          'records': [{'frame_index': i, 'pts': i, 'offset_seconds': i/10,
                                       'reviewed': True, 'review_method': 'synthetic_fixture', 'reviewer': 'fixture',
                                       'visibility': 'visible', 'reference_boxes': [[10, 10, 30, 30]],
                                       'reference_identity': 'subject-1'} for i in range(4)]}

    def evaluate(self):
        atomic_json(self.analysis/'status.json', {'state': 'complete'})
        atomic_json(self.analysis/'summary.json', self.summary)
        (self.analysis/'observations.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in self.rows))
        (self.root/'references.json').write_text(json.dumps(self.reference))
        return evaluate_video(self.analysis, self.root/'references.json')

    def multiple_animals(self):
        self.reference['schema_version'] = 2
        for ref, row in zip(self.reference['records'], self.rows):
            del ref['reference_boxes'], ref['reference_identity']
            ref['reference_instances'] = [
                {'identity': 'animal-a', 'xyxy': [10, 10, 30, 30]},
                {'identity': 'animal-b', 'xyxy': [60, 60, 90, 90]}]
            row['detections'] = [prediction(1), prediction(2, xyxy=[60, 60, 90, 90])]

    def test_multiple_animals_count_each_identity_swap(self):
        self.multiple_animals()
        for row in self.rows[2:]:
            row['detections'][0]['track_id'] = 2
            row['detections'][1]['track_id'] = 1
        report = self.evaluate()
        self.assertEqual(report['schema_version'], 2)
        self.assertEqual(report['selected_detections']['true_positive'], 8)
        self.assertEqual(report['tracking']['visible_instance_samples'], 8)
        self.assertEqual(report['tracking']['matched_active_instance_samples'], 8)
        self.assertEqual(report['tracking']['eligible_adjacent_pairs'], 6)
        self.assertEqual(report['tracking']['stable_pairs'], 4)
        self.assertEqual(report['tracking']['id_changes'], 2)

    def test_duplicate_boxes_cannot_hide_a_missing_second_animal(self):
        self.multiple_animals()
        self.rows[1]['detections'][1]['xyxy'] = [10, 10, 30, 30]
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 7)
        self.assertEqual(report['selected_detections']['false_positive'], 1)
        self.assertEqual(report['selected_detections']['false_negative'], 1)
        self.assertEqual(report['tracking']['matched_active_instance_samples'], 7)
        self.assertEqual(report['tracking']['untracked_pairs'], 2)
        self.assertEqual(report['tracking']['stable_pairs'], 4)

    def test_overlapping_references_cannot_share_one_prediction(self):
        self.multiple_animals()
        for ref, row in zip(self.reference['records'], self.rows):
            ref['reference_instances'][1]['xyxy'] = [15, 10, 35, 30]
            row['detections'] = [prediction(1)]
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 4)
        self.assertEqual(report['selected_detections']['false_negative'], 4)
        self.assertEqual(report['tracking']['matched_active_instance_samples'], 4)
        self.assertEqual(report['tracking']['stable_pairs'], 3)
        self.assertEqual(report['tracking']['untracked_pairs'], 3)

    def test_same_active_id_on_two_animals_is_an_identity_conflict(self):
        self.multiple_animals()
        for row in self.rows:
            row['detections'][1]['track_id'] = 1
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 8)
        self.assertEqual(report['tracking']['matched_active_instance_samples'], 0)
        self.assertEqual(report['tracking']['identity_conflict_frames'], 4)
        self.assertEqual(report['tracking']['untracked_pairs'], 6)
        self.assertIsNone(report['tracking']['id_changes'])

    def test_single_animal_cannot_claim_stability_with_duplicate_active_ids(self):
        for row in self.rows:
            row['detections'].append(prediction(1, xyxy=[50, 50, 70, 70]))
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 4)
        self.assertEqual(report['selected_detections']['false_positive'], 4)
        self.assertEqual(report['tracking']['matched_active_frames'], 0)
        self.assertEqual(report['tracking']['identity_conflict_frames'], 4)
        self.assertEqual(report['tracking']['stable_pairs'], 0)
        self.assertEqual(report['tracking']['untracked_pairs'], 3)
        self.assertEqual(report['tracking']['continuity'], 0)
        self.assertIsNone(report['tracking']['id_changes'])

    def test_inactive_or_below_threshold_duplicate_ids_do_not_create_conflicts(self):
        for row in self.rows:
            row['detections'].append(prediction(1, score=.399, xyxy=[50, 50, 70, 70]))
            inactive = prediction(1, xyxy=[50, 50, 70, 70])
            inactive['identity_status'] = 'ambiguous_association'
            row['detections'].append(inactive)
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 4)
        self.assertEqual(report['selected_detections']['false_positive'], 4)
        self.assertEqual(report['tracking']['matched_active_frames'], 4)
        self.assertEqual(report['tracking']['stable_pairs'], 3)
        self.assertEqual(report['tracking']['identity_conflict_frames'], 0)

    def test_sparse_multi_animal_labels_do_not_prove_continuity(self):
        self.multiple_animals()
        self.reference['records'] = [self.reference['records'][0], self.reference['records'][3]]
        self.reference['selection'] = 'manual_spot_check'
        report = self.evaluate()
        self.assertEqual(report['tracking']['visible_instance_samples'], 4)
        self.assertEqual(report['tracking']['eligible_adjacent_pairs'], 0)
        self.assertIsNone(report['tracking']['continuity'])
        self.assertIsNone(report['tracking']['id_changes'])

    def test_multi_animal_reference_identities_must_be_unique(self):
        self.multiple_animals()
        self.reference['records'][0]['reference_instances'][1]['identity'] = 'animal-a'
        with self.assertRaisesRegex(RecorderError, 'duplicate reference identity'):
            self.evaluate()

    def test_multi_animal_unreviewable_and_absent_remain_distinct(self):
        self.multiple_animals()
        self.reference['records'][1].update(visibility='unreviewable', reference_instances=None)
        self.reference['records'][2].update(reviewed=False, visibility=None, reference_instances=None)
        self.reference['records'][3].update(visibility='absent', reference_instances=[])
        report = self.evaluate()
        self.assertEqual(report['evaluated_frames'], 2)
        self.assertEqual(report['selected_detections']['negative_image'], 1)
        self.assertEqual(report['selected_detections']['false_positive'], 2)
        self.assertEqual(report['tracking']['visible_instance_samples'], 2)
        self.assertIsNone(report['tracking']['continuity'])

    def test_multi_animal_schema_rejects_legacy_fields_and_invalid_boxes(self):
        self.multiple_animals()
        self.reference['records'][0]['reference_identity'] = 'ambiguous-legacy-id'
        with self.assertRaisesRegex(RecorderError, 'mixed reference schema'):
            self.evaluate()
        del self.reference['records'][0]['reference_identity']
        self.reference['records'][0]['reference_instances'][0]['xyxy'] = [10, 10, 130, 30]
        with self.assertRaises(RecorderError):
            self.evaluate()

    def test_duplicate_false_box_miss_and_id_change_are_measured_separately(self):
        self.rows[0]['detections'].append(prediction(8))
        self.rows[1]['detections'] = []
        self.rows[3]['detections'] = [prediction(2)]
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 3)
        self.assertEqual(report['selected_detections']['false_positive'], 1)
        self.assertEqual(report['selected_detections']['false_negative'], 1)
        self.assertEqual(report['tracking']['eligible_adjacent_pairs'], 3)
        self.assertEqual(report['tracking']['untracked_pairs'], 2)
        self.assertEqual(report['tracking']['id_changes'], 1)
        self.assertFalse(report['field_validated'])

    def test_sparse_references_do_not_claim_zero_identity_changes(self):
        self.reference['records'] = [self.reference['records'][0], self.reference['records'][3]]
        self.reference['selection'] = 'manual_spot_check'
        report = self.evaluate()
        self.assertEqual(report['tracking']['eligible_adjacent_pairs'], 0)
        self.assertIsNone(report['tracking']['id_changes'])
        self.assertIsNone(report['tracking']['continuity'])
        self.assertEqual(report['evaluated_frames'], 2)

    def test_unreviewed_and_unreviewable_are_not_negative_examples(self):
        self.reference['records'][1].update(reviewed=False, reference_boxes=None, visibility=None)
        self.reference['records'][2].update(visibility='unreviewable', reference_boxes=None, reference_identity=None)
        self.reference['records'][3].update(visibility='absent', reference_boxes=[], reference_identity=None)
        report = self.evaluate()
        self.assertEqual(report['evaluated_frames'], 2)
        self.assertEqual(report['selected_detections']['negative_image'], 1)
        self.assertEqual(report['selected_detections']['false_positive'], 1)
        self.assertEqual(report['excluded_frames'], {'unreviewed': 1, 'unreviewable': 1})

    def test_guided_filtering_does_not_overstate_detector_accuracy(self):
        self.summary['target_selection_mode'] = 'initial_box_guided'
        self.summary['config']['target_seed'] = {'source_sha256':'a'*64, 'xyxy':[0.1,0.1,0.3,0.3]}
        for row in self.rows:
            row['detector_candidates'] = [prediction(), prediction(8, xyxy=[50,50,90,90])]
        report = self.evaluate()
        self.assertEqual(report['excluded_frames'], {'initialization': 1})
        self.assertEqual(report['raw_detector']['false_positive'], 3)
        self.assertEqual(report['selected_detections']['false_positive'], 0)
        self.assertEqual(report['mode'], 'initial_box_guided')
        del self.rows[2]['detector_candidates']
        with self.assertRaisesRegex(RecorderError, 'raw detector'):
            self.evaluate()

    def test_wrong_source_pts_and_duplicate_reference_fail_closed(self):
        original = copy.deepcopy(self.reference)
        self.reference['source_sha256'] = 'b'*64
        with self.assertRaisesRegex(RecorderError, 'source'):
            self.evaluate()
        self.reference = copy.deepcopy(original)
        self.reference['records'][0]['pts'] = 123
        with self.assertRaisesRegex(RecorderError, 'timestamp'):
            self.evaluate()
        self.reference = copy.deepcopy(original)
        self.reference['records'].append(copy.deepcopy(self.reference['records'][0]))
        with self.assertRaisesRegex(RecorderError, 'duplicate reference'):
            self.evaluate()

    def test_invalid_or_multi_animal_references_are_rejected(self):
        original = copy.deepcopy(self.reference)
        for boxes in ([[10,10,float('nan'),30]], [[10,10,120,30]], [], [[10,10,30,30],[40,40,60,60]]):
            self.reference = copy.deepcopy(original)
            self.reference['records'][0]['reference_boxes'] = boxes
            with self.assertRaises(RecorderError):
                self.evaluate()

    def test_ambiguous_identity_is_not_counted_as_stable_tracking(self):
        self.rows[1]['detections'][0]['identity_status'] = 'ambiguous_association'
        report = self.evaluate()
        self.assertEqual(report['selected_detections']['true_positive'], 4)
        self.assertEqual(report['tracking']['matched_active_frames'], 3)
        self.assertEqual(report['tracking']['untracked_pairs'], 2)
        self.assertEqual(report['tracking']['stable_pairs'], 1)

    def test_legacy_tracker_filtered_outputs_cannot_claim_raw_detection_performance(self):
        del self.summary['config']['tracking_revision']
        with self.assertRaisesRegex(RecorderError, 'raw detector'):
            self.evaluate()


if __name__ == '__main__':
    unittest.main()
