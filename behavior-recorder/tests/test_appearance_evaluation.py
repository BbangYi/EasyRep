"""Synthetic evaluation contracts; no real animals, pixels or model fitting."""
import copy
import hashlib
import importlib.util
import json
import unittest

import test_appearance_timeline as fixtures
from behavior_recorder.core import RecorderError

if importlib.util.find_spec('behavior_recorder.appearance_evaluation'):
    from behavior_recorder.appearance_evaluation import freeze_cohort, evaluate_predictions
else:
    freeze_cohort = evaluate_predictions = None


class AppearanceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearanceTimelineTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.fixture.cycle()
        self.fixture.color('train-a', '2026-11-02T01:00:00Z')
        self.fixture.color('train-b', '2026-11-03T01:00:00Z', 100)
        self.fixture.event('start-two', 'started', '2026-11-10T01:00:00Z', '2026-11-10T03:00:00Z')
        self.fixture.event('end-two', 'completed', '2026-11-11T01:00:00Z')
        self.fixture.plan['cycles'].append(dict(cycle_id='cycle-two', previous_completed='end',
            started='start-two', completed='end-two', role='test', observer='fixture-reviewer',
            evidence_reference='synthetic explicit link'))
        self.fixture.color('future', '2026-11-07T01:00:00Z', 120)
        self.plan = dict(schema_version=1, kind='appearance_evaluation_plan', experiment_id='fixture-evaluation',
            dataset_kind='test', feature_version='past-only-reviewed-srgb-v1', mode='future_cycle',
            fit_cutoff='2026-11-06T02:00:00Z', evaluation_start='2026-11-07T00:00:00Z',
            evaluation_end='2026-11-09T00:00:00Z', labels_as_of='2026-11-12T00:00:00Z',
            timelines=[], anchors=[dict(animal_id='fixture-animal', record_id='future')],
            minimums=dict(train_cycles=1, train_animals=1, evaluation_cycles=1, evaluation_animals=1),
            acceptance=dict(min_scored_fraction=1, max_mean_interval_error_hours=12,
                            min_relative_error_reduction=.1),
            observer='fixture-reviewer', evidence_reference='synthetic predeclared design')
        self.refresh()

    def save(self, name, value):
        return self.fixture.fixture.save(name, value)

    def refresh(self):
        report = self.fixture.report()
        path = self.save('timeline.json', report)
        self.plan['timelines'] = [dict(plan='plan.json', timeline='timeline.json',
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())]

    def freeze(self, name='cohort.json'):
        self.assertTrue(callable(freeze_cohort), 'evaluation pipeline is not implemented')
        return freeze_cohort(self.save('evaluation.json', self.plan), self.root / name)

    def score(self, predictions=None):
        self.assertTrue(callable(evaluate_predictions), 'evaluation pipeline is not implemented')
        if predictions is None:
            predictions = [dict(animal_id='fixture-animal', record_id='future', hours_until_start=73)]
        payload = dict(schema_version=1, kind='appearance_point_predictions', dataset_kind='test',
                       feature_version=self.plan['feature_version'], model_id='synthetic-no-model',
                       cohort_sha256=hashlib.sha256((self.root / 'cohort.json').read_bytes()).hexdigest(),
                       rows=predictions)
        return evaluate_predictions(self.root / 'evaluation.json', self.root / 'cohort.json',
                                    self.save('predictions.json', payload))

    def test_whole_cycle_baseline_and_forecast_label_separation(self):
        cohort = self.freeze()
        self.assertEqual(cohort['counts']['train_cycles'], 1)
        self.assertEqual(len(cohort['training_rows']), 2)
        forecast = cohort['forecast_rows'][0]
        self.assertNotIn('target', forecast)
        self.assertNotIn('hours_until_start', forecast)
        self.assertEqual(cohort['baseline'][0]['hours_until_start'], 73.5)
        self.assertFalse(cohort['model_fitting_allowed'])
        self.assertIn('synthetic_dataset', cohort['gate_reasons'])
        report = self.score()
        self.assertEqual(report['candidate']['mean_interval_error_hours'], 0)
        self.assertEqual(report['candidate']['within_observed_interval_fraction'], 1)
        self.assertFalse(report['biological_validation_complete'])
        self.assertFalse(report['actuation_allowed'])

    def test_late_training_label_and_feature_are_rejected(self):
        self.plan['fit_cutoff'] = '2026-11-05T04:00:00Z'
        with self.assertRaisesRegex(RecorderError, 'training.*cutoff'):
            self.freeze()
        self.plan['fit_cutoff'] = '2026-11-06T02:00:00Z'
        artifact = json.loads((self.root / 'train-a.json').read_text())
        artifact['created_at'] = '2026-11-06T03:00:00Z'
        self.save('train-a.json', artifact)
        self.refresh()
        with self.assertRaisesRegex(RecorderError, 'training.*cutoff'):
            self.freeze()

    def test_timeline_hash_and_regenerated_content_are_checked(self):
        original = json.loads((self.root / 'timeline.json').read_text())
        original['rows'][0]['features']['rgb_median'][0] = 250
        path = self.save('timeline.json', original)
        with self.assertRaisesRegex(RecorderError, 'hash'):
            self.freeze()
        self.plan['timelines'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError, 'regenerated'):
            self.freeze()

    def test_real_test_mixing_and_wrong_feature_version_rejected(self):
        self.plan['dataset_kind'] = 'real'
        with self.assertRaisesRegex(RecorderError, 'dataset_kind'):
            self.freeze()
        self.plan['dataset_kind'] = 'test'
        self.plan['feature_version'] = 'unknown'
        with self.assertRaisesRegex(RecorderError, 'feature version'):
            self.freeze()

    def test_duplicate_cycle_anchors_and_training_anchor_rejected(self):
        self.plan['anchors'].append(copy.deepcopy(self.plan['anchors'][0]))
        with self.assertRaises(RecorderError):
            self.freeze()
        self.plan['anchors'] = [dict(animal_id='fixture-animal', record_id='train-a')]
        with self.assertRaises(RecorderError):
            self.freeze()

    def test_held_out_animal_cannot_overlap_fit_animals(self):
        self.plan['mode'] = 'held_out_animal'
        with self.assertRaisesRegex(RecorderError, 'held-out animal'):
            self.freeze()

    def test_future_cycle_requires_animal_training_history(self):
        self.fixture.plan['cycles'][0]['role'] = 'validation'
        self.refresh()
        with self.assertRaisesRegex(RecorderError, 'personalized'):
            self.freeze()

    def test_missing_and_pending_labels_remain_unscored(self):
        self.plan['labels_as_of'] = '2026-11-10T04:00:00Z'
        self.freeze()
        report = self.score()
        self.assertEqual(report['rows'][0]['label_status'], 'label_pending')
        self.assertEqual(report['candidate']['scored'], 0)
        self.assertIsNone(report['candidate']['mean_interval_error_hours'])
        self.assertFalse(report['comparison_criteria_passed'])

    def test_unlinked_observation_is_not_a_negative_or_an_eligible_cycle(self):
        self.fixture.color('unlinked', '2026-11-13T01:00:00Z')
        self.refresh()
        self.plan.update(evaluation_start='2026-11-13T00:00:00Z',
                         evaluation_end='2026-11-14T00:00:00Z', labels_as_of='2026-11-15T00:00:00Z')
        self.plan['anchors'] = [dict(animal_id='fixture-animal', record_id='unlinked')]
        cohort = self.freeze()
        self.assertEqual(cohort['counts']['evaluation_cycles'], 0)
        report = self.score([dict(animal_id='fixture-animal', record_id='unlinked', hours_until_start=24)])
        self.assertEqual(report['rows'][0]['label_status'], 'unlabelled')
        self.assertEqual(report['candidate']['scored'], 0)

    def test_abstention_missing_and_unknown_prediction_keys(self):
        self.freeze()
        report = self.score([])
        self.assertEqual(report['candidate']['missing'], 1)
        report = self.score([dict(animal_id='fixture-animal', record_id='future', hours_until_start=None)])
        self.assertEqual(report['candidate']['abstained'], 1)
        with self.assertRaises(RecorderError):
            self.score([dict(animal_id='fixture-animal', record_id='other', hours_until_start=2)])
        with self.assertRaises(RecorderError):
            self.score([dict(animal_id='fixture-animal', record_id='future', hours_until_start=True)])

    def test_interval_error_is_distance_to_interval_not_midpoint_error(self):
        self.freeze()
        report = self.score([dict(animal_id='fixture-animal', record_id='future', hours_until_start=70)])
        self.assertEqual(report['candidate']['mean_interval_error_hours'], 2)
        self.assertEqual(report['candidate']['within_observed_interval_fraction'], 0)
        self.assertEqual(report['paired']['count'], 1)
        self.assertFalse(report['comparison_criteria_passed'])

    def test_design_and_cohort_cannot_change_after_freeze(self):
        self.freeze()
        self.plan['acceptance']['max_mean_interval_error_hours'] = 999
        self.save('evaluation.json', self.plan)
        with self.assertRaisesRegex(RecorderError, 'frozen'):
            self.score()

    def test_minimums_use_unique_cycles_not_colour_rows(self):
        self.plan['minimums']['train_cycles'] = 2
        cohort = self.freeze()
        self.assertEqual(cohort['counts']['train_cycles'], 1)
        self.assertIn('insufficient_train_cycles', cohort['gate_reasons'])

    def test_output_is_write_once_and_inputs_remain_intact(self):
        before = (self.root / 'timeline.json').read_bytes()
        self.freeze()
        saved = (self.root / 'cohort.json').read_bytes()
        with self.assertRaises(RecorderError):
            self.freeze()
        self.assertEqual((self.root / 'cohort.json').read_bytes(), saved)
        self.assertEqual((self.root / 'timeline.json').read_bytes(), before)

    def add_held_out_animal(self):
        other = fixtures.AppearanceTimelineTests()
        other.setUp()
        other.root = self.root / 'other'
        other.root.mkdir()
        other.fixture.root = other.root
        other.fixture.manifest['animal_id'] = 'held-animal'
        other.event('previous', 'completed', '2026-11-06T01:00:00Z')
        other.event('start', 'started', '2026-11-10T01:00:00Z', '2026-11-10T03:00:00Z')
        other.event('end', 'completed', '2026-11-11T01:00:00Z')
        other.plan['cycles'] = [dict(cycle_id='held-cycle', previous_completed='previous',
            started='start', completed='end', role='test', observer='fixture-reviewer',
            evidence_reference='synthetic held-out cycle')]
        other.color('held-color', '2026-11-07T01:00:00Z')
        path = other.fixture.save('timeline.json', other.report())
        self.plan['timelines'].append(dict(plan='other/plan.json', timeline='other/timeline.json',
                                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.plan['mode'] = 'held_out_animal'
        self.plan['anchors'] = [dict(animal_id='held-animal', record_id='held-color')]
        return other

    def test_new_animal_uses_training_population_baseline_without_its_own_labels(self):
        self.add_held_out_animal()
        cohort = self.freeze()
        self.assertEqual(cohort['baseline'][0]['method'], 'training_population_median')
        self.assertIsNone(cohort['baseline'][0]['source_cycle'])
        self.assertEqual([(r['animal_id'], r['cycle_id']) for r in cohort['baseline_training_cycles']],
                         [('fixture-animal', 'cycle-one')])
        self.assertEqual(cohort['baseline'][0]['hours_until_start'], 73.5)
        self.assertEqual({row['animal_id'] for row in cohort['training_rows']}, {'fixture-animal'})
        self.assertEqual(cohort['counts']['evaluation_animals'], 1)

    def test_same_source_image_relabelled_for_another_animal_is_rejected(self):
        other = self.add_held_out_animal()
        artifact = json.loads((other.root / 'held-color.json').read_text())
        original = json.loads((self.root / 'train-a.json').read_text())
        artifact['files']['image']['sha256'] = original['files']['image']['sha256']
        other.fixture.save('held-color.json', artifact)
        path = other.fixture.save('timeline.json', other.report())
        self.plan['timelines'][-1]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError, 'source image'):
            self.freeze()

    def test_validation_and_pending_labels_cannot_satisfy_test_cycle_minimum(self):
        self.fixture.plan['cycles'][1]['role'] = 'validation'
        self.refresh()
        cohort = self.freeze()
        self.assertEqual(cohort['counts']['evaluation_cycles'], 0)
        self.assertIn('insufficient_evaluation_cycles', cohort['gate_reasons'])
        self.fixture.plan['cycles'][1]['role'] = 'test'
        self.refresh()
        self.plan['labels_as_of'] = '2026-11-10T04:00:00Z'
        cohort = self.freeze('pending-cohort.json')
        self.assertEqual(cohort['counts']['evaluation_cycles'], 0)

    def test_cli_freeze_score_and_output_collision(self):
        import os
        import subprocess
        import sys
        path = self.save('evaluation.json', self.plan)
        command = [sys.executable, '-B', '-m', 'behavior_recorder.appearance_evaluation',
                   '--plan', str(path), '--output', str(self.root / 'cohort.json')]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.score()
        command[-1] = str(self.root / 'scored.json')
        command += ['--cohort', str(self.root / 'cohort.json'), '--predictions', str(self.root / 'predictions.json')]
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (self.root / 'scored.json').read_bytes()
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'scored.json').read_bytes(), before)

    def test_output_byte_limit_rejects_before_writing_an_unreadable_cohort(self):
        from unittest.mock import patch
        import behavior_recorder.appearance_evaluation as evaluation
        with patch.object(evaluation, 'COHORT_LIMIT', 100, create=True):
            with self.assertRaisesRegex(RecorderError, 'cohort output'):
                self.freeze()
        self.assertFalse((self.root / 'cohort.json').exists())


if __name__ == '__main__':
    unittest.main()
