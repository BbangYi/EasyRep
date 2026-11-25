"""Synthetic native-clock and provenance checks; no biological performance evidence."""
import json
import platform
import unittest
from unittest.mock import patch

import test_appearance_predictor as fixtures
from behavior_recorder import appearance_predictor as predictor
from behavior_recorder import appearance_alarm_runner as runner
from behavior_recorder.appearance_alarm_evaluation import freeze_design, evaluate_alarms
from behavior_recorder.appearance_evaluation import required_time
from behavior_recorder.core import RecorderError, read_json


class AppearanceAlarmRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearancePredictorTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.fit_plan = self.fixture.save('fit.json', self.fixture.settings)
        with patch.object(predictor, 'now', return_value='2026-11-06T03:00:00Z'):
            predictor.fit_run(self.fit_plan, self.root / 'fit-run', software_test=True)
        self.plan = dict(schema_version=1, kind='appearance_alarm_runner_plan',
            fit_plan='fit.json', fit_run='fit-run', journal='alarm-journal',
            animals=['fixture-animal'], role='test', evaluation_start='2026-11-07T02:00:00Z',
            evaluation_end='2026-11-09T02:00:00Z', cadence_hours=24, horizon_hours=48,
            minimum_lead_hours=1, max_lateness_seconds=60, max_observation_age_hours=48)
        self.plan_path = self.fixture.save('runner-plan.json', self.plan)
        self.schedule_path = self.root / 'schedule.json'
        self.inputs = self.fixture.save('live-inputs.json', dict(
            timelines=self.fixture.fixture.plan['timelines']))

    def freeze(self):
        self.fixture.save('runner-plan.json', self.plan)
        with patch.object(runner, 'now', return_value='2026-11-06T04:00:00Z'):
            return runner.freeze_schedule(self.plan_path, self.schedule_path)

    def issue(self, at='2026-11-07T02:00:00Z', key='fixture-animal:0'):
        with patch.object(runner, 'now', return_value=at):
            return runner.issue_slot(self.plan_path, self.schedule_path, self.inputs, key,
                                     platform.node())

    def test_freeze_binds_model_and_future_grid_without_labels(self):
        schedule = self.freeze()
        self.assertEqual(len(schedule['decision_grid']), 2)
        self.assertEqual(set(schedule['decision_grid'][0]), {'decision_id', 'animal_id', 'scheduled_at'})
        self.assertNotIn('target', json.dumps(schedule))
        self.assertFalse(schedule['actuation_allowed'])

    def test_cannot_freeze_after_first_slot_or_before_completed_fit(self):
        for at in ('2026-11-07T03:00:00Z', '2026-11-06T02:00:00Z'):
            with self.subTest(at=at), patch.object(runner, 'now', return_value=at):
                with self.assertRaisesRegex(RecorderError, 'fit.*freeze.*schedule'):
                    runner.freeze_schedule(self.plan_path, self.schedule_path)

    def test_freeze_checks_completion_clock_before_first_slot(self):
        with patch.object(runner, 'now', side_effect=['2026-11-06T04:00:00Z', '2026-11-07T02:00:00Z']):
            with self.assertRaisesRegex(RecorderError, 'freeze completed too late'):
                runner.freeze_schedule(self.plan_path, self.schedule_path)
        self.assertFalse(self.schedule_path.exists())

    def test_issue_converts_observation_relative_hours_without_probability(self):
        self.freeze()
        result = self.issue('2026-11-07T02:00:30Z')
        self.assertEqual(result['status'], 'provided')
        self.assertAlmostEqual(result['prediction']['hours_until_start'],
            result['forecast_at_observation']['hours_until_start'] - 1 - 30 / 3600)
        self.assertIsNone(result['prediction']['probability_onset_within_horizon'])
        self.assertEqual(result['prediction']['issued_at'], '2026-11-07T02:00:30Z')
        self.assertFalse(result['biological_validation_complete'])
        self.assertTrue(result['actual_model_inference'])
        self.assertFalse(result['declared_real_input_inference'])

    def test_future_slot_does_not_create_attempt_and_duplicate_slot_is_locked(self):
        self.freeze()
        with self.assertRaisesRegex(RecorderError, 'not due'):
            self.issue('2026-11-07T01:59:59Z')
        self.assertFalse((self.root / 'alarm-journal').exists())
        self.issue()
        with self.assertRaisesRegex(RecorderError, 'already attempted'):
            self.issue()

    def test_late_slot_is_recorded_without_forecast_or_backdating(self):
        self.freeze()
        with patch.object(runner, 'forecast', side_effect=AssertionError('must not infer late')):
            result = self.issue('2026-11-07T02:01:01Z')
        self.assertEqual(result['status'], 'late')
        self.assertIsNone(result['prediction']['hours_until_start'])
        self.assertEqual(result['prediction']['issued_at'], '2026-11-07T02:01:01Z')

    def test_completion_clock_makes_slow_inference_late(self):
        self.freeze()
        with patch.object(runner, 'now', side_effect=['2026-11-07T02:00:00Z', '2026-11-07T02:01:01Z']):
            result = runner.issue_slot(self.plan_path, self.schedule_path, self.inputs,
                                       'fixture-animal:0', platform.node())
        self.assertEqual(result['status'], 'late')
        self.assertIsNone(result['prediction']['hours_until_start'])

    def test_stale_observation_abstains(self):
        self.plan['max_observation_age_hours'] = .5
        self.freeze()
        result = self.issue()
        self.assertIn('stale_observation', result['reasons'])
        self.assertIsNone(result['prediction']['hours_until_start'])

    def test_expired_estimate_is_not_clamped_to_imminent_alert(self):
        self.freeze()
        with patch.object(runner, 'forecast', return_value=([
            dict(animal_id='fixture-animal', record_id='future', hours_until_start=.1)], [{}])):
            result = self.issue()
        self.assertIn('estimate_expired', result['reasons'])
        self.assertIsNone(result['prediction']['hours_until_start'])

    def test_observation_expiring_during_inference_abstains(self):
        self.plan['max_observation_age_hours'] = 1
        self.freeze()
        result = self.issue('2026-11-07T02:00:30Z')
        self.assertIn('stale_observation', result['reasons'])
        self.assertIsNone(result['prediction']['hours_until_start'])

    def test_active_or_uncertain_shed_blocks_the_forecast(self):
        self.freeze()
        event = dict(record_id='new-start', stage='started', latest_at='2026-11-07T01:30:00Z',
                     available_at='2026-11-07T01:30:00Z')
        with patch.object(runner, 'available_events', return_value=[event]):
            result = self.issue()
        self.assertIn('known_active_or_uncertain_shed', result['reasons'])
        self.assertIsNone(result['forecast_at_observation'])

    def test_completion_after_observation_requires_a_new_observation(self):
        self.freeze()
        event = dict(record_id='new-end', stage='completed', latest_at='2026-11-07T01:30:00Z',
                     available_at='2026-11-07T01:30:00Z')
        with patch.object(runner, 'available_events', return_value=[event]):
            result = self.issue()
        self.assertIn('completion_after_observation', result['reasons'])
        self.assertIsNone(result['forecast_at_observation'])

    def test_known_events_exclude_future_labels_and_preserve_past_completion(self):
        schedule = self.freeze()
        inputs = read_json(self.inputs)
        datasets = runner.load_inputs({**inputs, 'feature_version': schedule['feature_version'],
            'dataset_kind': 'test'}, self.root)
        events = runner.available_events(inputs, self.root, datasets, 'fixture-animal',
            required_time('2026-11-07T02:00:00Z'), lambda: None)
        ids = {event['record_id'] for event in events}
        self.assertIn('end', ids)
        self.assertNotIn('start-two', ids)
        self.assertNotIn('end-two', ids)

    def test_clock_rollback_preserves_failure_instead_of_backdating(self):
        self.freeze()
        with patch.object(runner, 'now', side_effect=['2026-11-07T02:00:30Z', '2026-11-07T02:00:00Z']):
            with self.assertRaisesRegex(RecorderError, 'clock moved backwards'):
                runner.issue_slot(self.plan_path, self.schedule_path, self.inputs, 'fixture-animal:0', platform.node())
        folder = self.root / 'alarm-journal' / runner.slot_name('fixture-animal:0')
        self.assertTrue((folder / 'failure.json').exists())
        self.assertFalse((folder / 'prediction.json').exists())

    def test_preflight_rejection_does_not_create_journal(self):
        self.freeze()
        with patch.object(runner, 'native_preflight', side_effect=RecorderError('resource unavailable')):
            with self.assertRaisesRegex(RecorderError, 'resource unavailable'):
                self.issue()
        self.assertFalse((self.root / 'alarm-journal').exists())

    def test_latest_invalid_row_does_not_fall_back(self):
        dataset = dict(rows=[dict(record_id='older', observed_at='2026-11-07T00:00:00Z',
            as_of='2026-11-07T00:00:00Z', features={'valid': True}, role='test'),
            dict(record_id='newer', observed_at='2026-11-07T01:00:00Z',
            as_of='2026-11-07T01:00:00Z', features=None, role='test')], source_records=[])
        row, reasons = runner.select_row(dataset, required_time('2026-11-07T02:00:00Z'), self.plan)
        self.assertEqual(row['record_id'], 'newer')
        self.assertIn('latest_observation_unusable', reasons)

    def test_future_availability_is_not_selected(self):
        dataset = dict(rows=[dict(record_id='newer', observed_at='2026-11-07T01:00:00Z',
            as_of='2026-11-07T03:00:00Z', features={}, role='test')], source_records=[])
        row, reasons = runner.select_row(dataset, required_time('2026-11-07T02:00:00Z'), self.plan)
        self.assertIsNone(row)
        self.assertEqual(reasons, ['no_available_observation'])

    def test_failure_retains_started_and_blocks_automatic_retry(self):
        self.freeze()
        with patch.object(runner, 'load_inputs', side_effect=RecorderError('changed input')):
            with self.assertRaisesRegex(RecorderError, 'changed input'):
                self.issue()
        folder = self.root / 'alarm-journal' / runner.slot_name('fixture-animal:0')
        self.assertTrue((folder / 'started.json').exists())
        self.assertTrue((folder / 'failure.json').exists())
        self.assertFalse((folder / 'receipt.json').exists())
        with self.assertRaisesRegex(RecorderError, 'already attempted'):
            self.issue()

    def test_changed_model_and_schedule_are_rejected(self):
        self.freeze()
        value = read_json(self.schedule_path)
        value['decision_grid'][0]['scheduled_at'] = '2026-11-07T01:00:00Z'
        self.fixture.save('schedule.json', value)
        with self.assertRaisesRegex(RecorderError, 'schedule.*binding'):
            self.issue()

    def test_changed_model_file_is_rejected_before_attempt(self):
        self.freeze()
        model = read_json(self.root / 'fit-run/model.json')
        model['parameters']['intercept'] += 1
        self.fixture.save('fit-run/model.json', model)
        with self.assertRaisesRegex(RecorderError, 'run artifact hash mismatch'):
            self.issue()
        self.assertFalse((self.root / 'alarm-journal').exists())

    def test_training_image_is_protected_even_under_a_new_record_id(self):
        schedule = self.freeze()
        self.assertTrue(schedule['training_image_sha256'])
        with patch.object(runner, 'observation_image', return_value=schedule['training_image_sha256'][0]):
            result = self.issue()
        self.assertIn('training_image_reuse', result['reasons'])
        self.assertIsNone(result['forecast_at_observation'])

    def test_training_source_changed_after_freeze_is_rejected(self):
        self.freeze()
        row = self.fixture.cohort['training_rows'][0]
        roots = runner.series_roots(self.fixture.cohort['timelines'], self.root)
        path = roots[row['animal_id']] / row['artifact']
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(RecorderError, 'training source artifact changed'):
            self.issue()

    def evaluation(self):
        schedule = read_json(self.schedule_path)
        plan = dict(schema_version=1, kind='appearance_alarm_evaluation_plan',
            experiment_id='fixture-alarms', dataset_kind='test',
            feature_version=schedule['feature_version'], mode=schedule['mode'], role='test',
            fit_cutoff=schedule['fit_cutoff'], training_completed_at=schedule['training_completed_at'],
            model_id=schedule['model_id'], evaluation_start=self.plan['evaluation_start'],
            evaluation_end=self.plan['evaluation_end'], labels_as_of='2026-11-12T00:00:00Z',
            cadence_hours=24, horizon_hours=48, minimum_lead_hours=1, max_lateness_seconds=60,
            timelines=self.fixture.fixture.plan['timelines'], animals=['fixture-animal'],
            negative_windows=[], observer='fixture-reviewer', evidence_reference='synthetic only')
        p = self.fixture.save('alarm-evaluation-plan.json', plan)
        d = self.root / 'alarm-design.json'
        freeze_design(p, d)
        return p, d

    def test_export_integrates_evaluator_and_retains_missing_slots(self):
        self.freeze()
        self.issue()
        p, d = self.evaluation()
        output = self.root / 'export'
        runner.export_predictions(self.plan_path, self.schedule_path, p, d, output)
        report = evaluate_alarms(p, d, output / 'predictions.json')
        self.assertEqual(report['candidate']['scheduled'], 2)
        self.assertEqual(report['candidate']['missing'], 1)
        self.assertEqual(report['probabilities']['count'], 0)
        self.assertFalse(report['model_identity_verified'])

    def test_export_detects_prediction_tampering(self):
        self.freeze()
        self.issue()
        folder = self.root / 'alarm-journal' / runner.slot_name('fixture-animal:0')
        value = read_json(folder / 'prediction.json')
        value['hours_until_start'] = 1
        self.fixture.save(str((folder / 'prediction.json').relative_to(self.root)), value)
        p, d = self.evaluation()
        with self.assertRaisesRegex(RecorderError, 'receipt.*hash'):
            runner.export_predictions(self.plan_path, self.schedule_path, p, d, self.root / 'export')

    def test_export_preserves_failed_slot_as_missing_with_partial_evidence(self):
        self.freeze()
        with patch.object(runner, 'load_inputs', side_effect=RecorderError('changed input')):
            with self.assertRaises(RecorderError):
                self.issue()
        p, d = self.evaluation()
        evidence = runner.export_predictions(self.plan_path, self.schedule_path, p, d, self.root / 'export')
        self.assertEqual(evidence['missing'], 2)
        self.assertEqual(evidence['partial_slots'], ['fixture-animal:0'])

    def test_changed_evaluation_policy_is_rejected(self):
        self.freeze()
        self.issue()
        p, d = self.evaluation()
        plan = read_json(p)
        plan['horizon_hours'] = 24
        p2 = self.fixture.save('changed-evaluation.json', plan)
        d2 = self.root / 'changed-design.json'
        freeze_design(p2, d2)
        with self.assertRaisesRegex(RecorderError, 'evaluation policy'):
            runner.export_predictions(self.plan_path, self.schedule_path, p2, d2, self.root / 'export')

    def test_cli_freeze_issue_export_and_collision(self):
        args = ['--plan', str(self.plan_path), '--schedule', str(self.schedule_path),
                '--execution-host', platform.node()]
        with patch.object(runner, 'now', return_value='2026-11-06T04:00:00Z'):
            self.assertEqual(runner.main(['freeze', *args]), 0)
        with patch.object(runner, 'now', return_value='2026-11-07T02:00:00Z'):
            self.assertEqual(runner.main(['issue', *args, '--inputs', str(self.inputs),
                                         '--decision', 'fixture-animal:0']), 0)
        p, d = self.evaluation()
        export = ['export', *args, '--evaluation-plan', str(p), '--design', str(d),
                  '--output', str(self.root / 'export')]
        self.assertEqual(runner.main(export), 0)
        self.assertEqual(runner.main(export), 2)


if __name__ == '__main__':
    unittest.main()
