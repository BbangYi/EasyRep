"""Synthetic alarm denominators and causal boundaries, not biological validation."""
import copy
import hashlib
from datetime import timedelta
import unittest
from unittest.mock import patch

import test_appearance_evaluation as fixtures
from behavior_recorder.core import RecorderError
from behavior_recorder.appearance_alarm_evaluation import (freeze_design, evaluate_alarms,
    build_design, truth_at, main)
from behavior_recorder.appearance_evaluation import required_time


class AppearanceAlarmEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearanceEvaluationTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.plan = dict(schema_version=1, kind='appearance_alarm_evaluation_plan',
            experiment_id='fixture-alarms', dataset_kind='test',
            feature_version='past-only-reviewed-srgb-v1', mode='future_cycle', role='test',
            fit_cutoff='2026-11-06T02:00:00Z', training_completed_at='2026-11-06T02:00:00Z',
            model_id='synthetic-no-model', evaluation_start='2026-11-07T00:00:00Z',
            evaluation_end='2026-11-11T00:00:00Z', labels_as_of='2026-11-12T00:00:00Z',
            cadence_hours=24, horizon_hours=48, minimum_lead_hours=1, max_lateness_seconds=60,
            timelines=self.fixture.plan['timelines'], animals=['fixture-animal'],
            negative_windows=[dict(record_id='review-one', animal_id='fixture-animal',
                kind='confirmed_no_onset', start_at='2026-11-07T00:00:00Z',
                end_at='2026-11-10T00:00:00Z', available_at='2026-11-10T00:00:00Z',
                observer='fixture-reviewer', evidence_reference='synthetic continuous review')],
            observer='fixture-reviewer', evidence_reference='synthetic frozen design')

    def freeze(self):
        return freeze_design(self.fixture.save('alarms-plan.json', self.plan), self.root / 'alarms-design.json')

    def payload(self, values=(12, 72, 72, 12), **changes):
        rows = []
        for index, value in enumerate(values):
            scheduled = f'2026-11-{7 + index:02d}T00:00:00Z'
            row = dict(decision_id=f'fixture-animal:{index}', issued_at=scheduled,
                features_available_at=scheduled, hours_until_start=value,
                probability_onset_within_horizon=None)
            row.update(changes)
            rows.append(row)
        return dict(schema_version=1, kind='appearance_alarm_predictions', dataset_kind='test',
            model_id=self.plan['model_id'],
            design_sha256=hashlib.sha256((self.root / 'alarms-design.json').read_bytes()).hexdigest(), rows=rows)

    def score(self, payload=None):
        return evaluate_alarms(self.root / 'alarms-plan.json', self.root / 'alarms-design.json',
            self.fixture.save('alarms-predictions.json', payload or self.payload()))

    def test_hand_calculated_false_alarm_detection_and_lead_interval(self):
        design = self.freeze()
        self.assertEqual(len(design['decision_grid']), 4)
        self.assertNotIn('truth', design['decision_grid'][0])
        report = self.score()
        self.assertEqual([r['truth']['label'] for r in report['rows']], [0, 0, 1, 1])
        self.assertEqual(report['candidate']['true_alerts'], 1)
        self.assertEqual(report['candidate']['false_alerts'], 1)
        self.assertEqual(report['candidate']['false_alarm_fraction'], .5)
        self.assertEqual(len(report['per_animal_day']), 4)
        self.assertEqual(report['per_animal_day'][0]['candidate']['false_alerts'], 1)
        self.assertEqual(report['cycles']['candidate_detected'], 1)
        self.assertEqual(report['cycles']['rows'][0]['candidate_lead_hours'], [1, 3])
        self.assertFalse(report['biological_validation_complete'])
        self.assertFalse(report['model_identity_verified'])
        self.assertFalse(report['actuation_allowed'])

    def test_missing_slots_retained_and_cycle_counted_as_missed(self):
        self.freeze()
        report = self.score(self.payload(values=()))
        self.assertEqual(report['candidate']['missing'], 4)
        self.assertEqual(report['candidate']['scored_decisions'], 0)
        self.assertIsNone(report['candidate']['false_alarm_fraction'])
        self.assertEqual(report['cycles']['candidate_missed'], 1)
        self.assertEqual(report['cycles']['covered_cycles'], 1)

    def test_abstention_is_not_a_correct_negative(self):
        self.freeze()
        report = self.score(self.payload(values=(None, None, None, None)))
        self.assertEqual(report['candidate']['abstained'], 4)
        self.assertEqual(report['candidate']['known_negative_decisions'], 0)
        self.assertEqual(report['cycles']['candidate_missed'], 1)

    def test_no_review_does_not_mean_negative(self):
        self.plan['negative_windows'] = []
        self.freeze()
        report = self.score()
        self.assertEqual([r['truth']['label'] for r in report['rows']], [None, None, 1, 1])
        self.assertEqual(report['candidate']['unscored_alerts'], 1)
        self.assertEqual(report['candidate']['false_alerts'], 0)

    def test_review_gap_is_unscored(self):
        first = self.plan['negative_windows'][0]
        first['end_at'] = '2026-11-08T00:00:00Z'
        second = copy.deepcopy(first)
        second.update(record_id='review-two', start_at='2026-11-08T00:00:01Z',
                      end_at='2026-11-10T00:00:00Z')
        self.plan['negative_windows'].append(second)
        self.freeze()
        self.assertIsNone(self.score()['rows'][0]['truth']['label'])

    def test_adjacent_review_windows_cover_whole_horizon(self):
        first = self.plan['negative_windows'][0]
        second = copy.deepcopy(first)
        first['end_at'] = '2026-11-08T00:00:00Z'
        second.update(record_id='review-two', start_at=first['end_at'])
        self.plan['negative_windows'].append(second)
        self.freeze()
        self.assertEqual(self.score()['rows'][0]['truth']['label'], 0)

    def test_future_review_is_not_available(self):
        self.plan['negative_windows'][0]['available_at'] = '2026-11-13T00:00:00Z'
        self.freeze()
        self.assertIsNone(self.score()['rows'][0]['truth']['label'])

    def test_negative_review_conflicting_with_start_rejected(self):
        self.plan['negative_windows'][0].update(end_at='2026-11-10T02:00:00Z',
                                                available_at='2026-11-10T02:00:00Z')
        with self.assertRaisesRegex(RecorderError, 'contradicts'):
            self.freeze()

    def test_boundary_crossing_onset_is_unscored(self):
        self.plan['horizon_hours'] = 26
        self.freeze()
        self.assertIsNone(self.score()['rows'][2]['truth']['label'])

    def test_label_pending_cannot_satisfy_cycle_denominator(self):
        self.plan['labels_as_of'] = '2026-11-11T00:00:00Z'
        self.freeze()
        report = self.score()
        self.assertIsNone(report['rows'][3]['truth']['label'])
        self.assertEqual(report['cycles']['eligible_cycles'], 0)
        self.assertEqual(report['cycles']['excluded_cycles'], 1)

    def test_future_features_and_backdated_issue_rejected(self):
        self.freeze()
        p = self.payload()
        p['rows'][0]['features_available_at'] = '2026-11-07T00:00:01Z'
        with self.assertRaisesRegex(RecorderError, 'feature availability'):
            self.score(p)
        p = self.payload()
        p['rows'][0]['issued_at'] = '2026-11-06T23:59:59Z'
        with self.assertRaisesRegex(RecorderError, 'before scheduled'):
            self.score(p)

    def test_late_alarm_does_not_receive_prospective_credit(self):
        self.freeze()
        p = self.payload(values=(72, 72, 72, 12))
        p['rows'][3]['issued_at'] = '2026-11-10T00:02:00Z'
        report = self.score(p)
        self.assertEqual(report['candidate']['late'], 1)
        self.assertEqual(report['cycles']['candidate_missed'], 1)

    def test_real_issue_time_controls_minimum_lead(self):
        self.freeze()
        p = self.payload(values=(72, 72, 72, 12))
        p['rows'][3]['issued_at'] = '2026-11-10T00:01:00Z'
        report = self.score(p)
        self.assertEqual(report['candidate']['true_alerts'], 1)
        self.assertEqual(report['cycles']['candidate_missed'], 1)

    def test_uncovered_cycle_is_explicit_not_a_miss(self):
        self.plan.update(cadence_hours=96, horizon_hours=1, minimum_lead_hours=0)
        self.freeze()
        report = self.score(self.payload(values=(12,)))
        self.assertEqual(report['cycles']['eligible_cycles'], 1)
        self.assertEqual(report['cycles']['uncovered_cycles'], 1)
        self.assertEqual(report['cycles']['candidate_missed'], 0)

    def test_probability_reliability_only_uses_supplied_probabilities(self):
        self.freeze()
        p = self.payload()
        for row, probability in zip(p['rows'], [.2, .1, .8, 1.]):
            row['probability_onset_within_horizon'] = probability
        report = self.score(p)
        self.assertAlmostEqual(report['probabilities']['brier_score'], .0225)
        self.assertEqual(report['probabilities']['count'], 4)
        self.assertEqual(sum(b['count'] for b in report['probabilities']['bins']), 4)
        self.assertEqual(self.score()['probabilities']['count'], 0)

    def test_duplicate_unknown_identity_and_invalid_values_rejected(self):
        self.freeze()
        for mutate in (lambda p: p['rows'].append(copy.deepcopy(p['rows'][0])),
                       lambda p: p['rows'][0].update(decision_id='unknown'),
                       lambda p: p.update(model_id='other'),
                       lambda p: p['rows'][0].update(hours_until_start=True),
                       lambda p: p['rows'][0].update(probability_onset_within_horizon=1.1),
                       lambda p: p['rows'][0].update(hours_until_start=None,
                                                   probability_onset_within_horizon=.5)):
            p = self.payload()
            mutate(p)
            with self.assertRaises(RecorderError):
                self.score(p)

    def test_training_cutoff_and_role_leakage_rejected(self):
        self.plan['fit_cutoff'] = '2026-11-05T04:00:00Z'
        self.plan['training_completed_at'] = self.plan['fit_cutoff']
        with self.assertRaisesRegex(RecorderError, 'training.*cutoff'):
            self.freeze()
        self.plan['fit_cutoff'] = '2026-11-06T02:00:00Z'
        with self.assertRaisesRegex(RecorderError, 'training completion'):
            self.freeze()
        self.plan['training_completed_at'] = self.plan['fit_cutoff']
        self.plan['role'] = 'validation'
        with self.assertRaisesRegex(RecorderError, 'role'):
            self.freeze()

    def test_held_out_animal_cannot_overlap_training(self):
        self.plan['mode'] = 'held_out_animal'
        with self.assertRaisesRegex(RecorderError, 'held-out'):
            self.freeze()

    def test_design_and_source_hash_binding_and_no_overwrite(self):
        self.freeze()
        with self.assertRaisesRegex(RecorderError, 'exists'):
            self.freeze()
        self.plan['horizon_hours'] = 72
        self.fixture.save('alarms-plan.json', self.plan)
        with self.assertRaisesRegex(RecorderError, 'frozen'):
            self.score()

    def test_bounded_grid_rejects_unbounded_schedule(self):
        self.plan['cadence_hours'] = .001
        self.plan['max_lateness_seconds'] = 0
        with self.assertRaisesRegex(RecorderError, 'grid'):
            self.freeze()

    def test_nearest_onset_matches_only_one_cycle(self):
        self.freeze()
        _, _, datasets, _, _ = build_design(self.root / 'alarms-plan.json')
        cycles = datasets['fixture-animal'][1]
        later = copy.deepcopy(cycles[-1])
        later['cycle_id'] = 'cycle-three'
        for key in ('previous_completed_event', 'started_event', 'completed_event'):
            for field in ('earliest', 'latest', 'available'):
                later[key][field] += timedelta(days=10)
        truth = truth_at(required_time('2026-11-09T00:00:00Z'), cycles + [later], [], [],
                         400, required_time('2026-11-30T00:00:00Z'))
        self.assertEqual(truth['cycle_id'], 'cycle-two')

    def test_unlinked_uncertain_event_cannot_be_negative_or_positive(self):
        self.plan['negative_windows'] = []
        temporal = self.fixture.fixture
        temporal.event('uncertain', 'uncertain', '2026-11-09T12:00:00Z')
        self.fixture.refresh()
        self.plan['timelines'] = self.fixture.plan['timelines']
        self.freeze()
        report = self.score()
        self.assertIsNone(report['rows'][2]['truth']['label'])
        self.assertEqual(report['cycles']['excluded_cycles'], 1)

    def test_baseline_duration_uses_training_only(self):
        design = self.freeze()
        self.assertEqual([r['cycle_id'] for r in design['baseline_training_cycles']], ['cycle-one'])
        self.assertEqual(design['baseline_training_cycles'][0]['duration_hours'], 97.5)
        self.assertEqual(design['decision_grid'][0]['baseline']['hours_until_start'], 74.5)
        self.assertEqual(design['decision_grid'][2]['baseline']['hours_until_start'], 26.5)

    def test_cli_preflight_failure_cannot_create_output(self):
        path = self.fixture.save('alarms-plan.json', self.plan)
        output = self.root / 'cli-output.json'
        with patch('behavior_recorder.appearance_predictor.native_preflight',
                   side_effect=RecorderError('native fitting/scoring must run on the declared Windows PC')):
            self.assertEqual(main(['freeze', '--plan', str(path), '--output', str(output),
                                   '--execution-host', 'DESKTOP-GMQFQTR']), 2)
        self.assertFalse(output.exists())

    def test_cli_freezes_and_scores_on_declared_cpu_host(self):
        import json
        import platform
        import subprocess
        import sys
        self.fixture.save('alarms-plan.json', self.plan)
        base = [sys.executable, '-B', '-m', 'behavior_recorder.appearance_alarm_evaluation']
        common = ['--plan', str(self.root/'alarms-plan.json'), '--execution-host', platform.node()]
        frozen = subprocess.run(base + ['freeze', '--output', str(self.root/'alarms-design.json')] + common,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(frozen.returncode, 0, frozen.stderr)
        self.assertEqual(json.loads(frozen.stdout.splitlines()[0])['preflight']['execution_device'], 'cpu')
        predictions = self.fixture.save('alarms-predictions.json', self.payload())
        output = self.root/'cli-scores.json'
        scored = subprocess.run(base + ['evaluate', '--design', str(self.root/'alarms-design.json'),
            '--predictions', str(predictions), '--output', str(output)] + common,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(scored.returncode, 0, scored.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report['candidate']['false_alerts'], 1)
        self.assertFalse(report['biological_validation_complete'])
        self.assertFalse(report['actuation_allowed'])


if __name__ == '__main__':
    unittest.main()
