"""Numerical/serialization fixtures, never biological observations or performance."""
import copy
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import unittest

import test_appearance_evaluation as fixtures
from behavior_recorder.core import RecorderError

if importlib.util.find_spec('behavior_recorder.appearance_predictor'):
    from behavior_recorder import appearance_predictor as predictor
else:
    predictor = None


class AppearancePredictorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearanceEvaluationTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.fixture.fixture.color('train-c', '2026-11-04T01:00:00Z', 120)
        self.fixture.fixture.color('future-history', '2026-11-06T02:00:00Z', 100)
        self.fixture.refresh()
        self.cohort = self.fixture.freeze()
        self.settings = dict(schema_version=1, kind='appearance_fit_plan',
            experiment_id='fixture-evaluation', cohort='cohort.json',
            cohort_sha256=hashlib.sha256((self.root / 'cohort.json').read_bytes()).hexdigest(),
            algorithm='cycle-weighted-ridge-v1', features=['elapsed_hours', 'red_delta'],
            regularization=1., max_target_interval_hours=4., minimum_train_rows=2,
            max_abs_z=4., max_prediction_hours=8760., seed=None,
            execution_host=platform.node(), observer='fixture-reviewer',
            evidence_reference='fixed synthetic software-test configuration, not biological data')

    def api(self):
        self.assertIsNotNone(predictor, 'prediction runner is not implemented')
        return predictor

    def model(self, cohort=None, settings=None):
        return self.api().train_artifact(cohort or self.cohort, settings or self.settings,
                                        software_test=True)

    def save(self, name, value):
        return self.fixture.save(name, value)

    def test_weighted_ridge_matches_hand_calculation_and_unpenalized_intercept(self):
        model = self.api().ridge_fit([[0.], [2.]], [1., 5.], [.5, .5], 1.)
        self.assertEqual(model['means'], [1.])
        self.assertEqual(model['scales'], [1.])
        self.assertAlmostEqual(model['intercept'], 3.)
        self.assertAlmostEqual(model['coefficients'][0], 1.)

    def test_cycle_balancing_is_invariant_to_repeating_a_cycle_observation(self):
        api = self.api()
        a = api.ridge_fit([[0.], [2.]], [1., 5.], [.5, .5], 1.)
        b = api.ridge_fit([[0.], [0.], [2.]], [1., 1., 5.], [.25, .25, .5], 1.)
        self.assertEqual(a, b)
        model = self.model()
        self.assertEqual(model['training']['cycle_count'], 1)
        self.assertEqual(model['training']['row_count'], 2)
        self.assertEqual([r['weight'] for r in model['training']['used']], [.5, .5])

    def test_forecasts_do_not_change_training_statistics_or_model_identity(self):
        original = self.model()
        changed = copy.deepcopy(self.cohort)
        changed['forecast_rows'][0]['features']['rgb_delta'] = [220, 200, 190]
        changed['forecast_rows'].reverse()
        changed['baseline'][0]['hours_until_start'] = 8000
        settings = {**self.settings, 'cohort_sha256': 'f' * 64}
        after = self.model(changed, settings)
        self.assertEqual(original['parameters'], after['parameters'])
        self.assertEqual(original['model_id'], after['model_id'])
        self.assertEqual(original['training'], after['training'])

    def test_test_data_requires_explicit_software_mode_and_never_claims_real_fitting(self):
        api = self.api()
        with self.assertRaisesRegex(RecorderError, 'synthetic'):
            api.train_artifact(self.cohort, self.settings)
        model = self.model()
        self.assertEqual(model['status'], 'software_test_only')
        self.assertFalse(model['actual_biological_fit'])
        self.assertFalse(model['biological_validation_complete'])
        real = {**self.cohort, 'dataset_kind': 'real', 'model_fitting_allowed': True}
        with self.assertRaisesRegex(RecorderError, 'software.*test'):
            api.train_artifact(real, self.settings, software_test=True)

    def test_missing_history_is_excluded_and_minimums_are_rechecked_after_selection(self):
        model = self.model()
        self.assertEqual(model['training']['excluded'][0]['record_id'], 'train-a')
        self.assertIn('missing_red_delta', model['training']['excluded'][0]['reasons'])
        cohort = copy.deepcopy(self.cohort)
        cohort['minimums']['train_cycles'] = 2
        with self.assertRaisesRegex(RecorderError, 'eligible training cycles'):
            self.model(cohort)
        with self.assertRaisesRegex(RecorderError, 'eligible training rows'):
            self.model(settings={**self.settings, 'minimum_train_rows': 3})

    def test_wide_training_intervals_are_not_silently_treated_as_precise_labels(self):
        with self.assertRaisesRegex(RecorderError, 'eligible training rows'):
            self.model(settings={**self.settings, 'max_target_interval_hours': 1.})

    def test_future_label_feature_and_wrong_role_are_rejected_before_fit(self):
        for field in ['label', 'feature', 'role']:
            with self.subTest(field=field):
                cohort = copy.deepcopy(self.cohort)
                row = cohort['training_rows'][1]
                if field == 'label':
                    row['target']['available_at'] = '2026-11-20T00:00:00Z'
                elif field == 'feature':
                    row['as_of'] = '2026-11-20T00:00:00Z'
                else:
                    row['role'] = 'test'
                with self.assertRaises(RecorderError):
                    self.model(cohort)

    def test_no_missing_values_are_imputed_in_forecasts(self):
        model = self.model()
        forecasts = copy.deepcopy(self.cohort['forecast_rows'])
        forecasts[0]['features']['rgb_delta'] = None
        rows, audit = self.api().forecast(model, forecasts)
        self.assertIsNone(rows[0]['hours_until_start'])
        self.assertIn('missing_red_delta', audit[0]['reasons'])

    def test_out_of_training_support_abstains_instead_of_extrapolating(self):
        model = self.model()
        forecasts = copy.deepcopy(self.cohort['forecast_rows'])
        forecasts[0]['features']['rgb_delta'] = [255, 255, 255]
        rows, audit = self.api().forecast(model, forecasts)
        self.assertIsNone(rows[0]['hours_until_start'])
        self.assertIn('outside_training_support', audit[0]['reasons'])

    def test_fixed_valid_colour_forecast_is_finite_and_model_serializes(self):
        model = self.model()
        restored = json.loads(json.dumps(model, allow_nan=False))
        rows, audit = self.api().forecast(restored, self.cohort['forecast_rows'])
        self.assertIsInstance(rows[0]['hours_until_start'], float)
        self.assertEqual(audit[0]['reasons'], [])
        self.assertEqual(self.api().model_fingerprint(restored), model['model_id'])
        self.assertEqual(restored['randomness'], {'seed': None, 'used': False})

    def test_invalid_numbers_features_and_duplicate_rows_rejected(self):
        for value in [0, True, float('nan'), -1]:
            with self.subTest(regularization=value):
                with self.assertRaises(RecorderError):
                    self.model(settings={**self.settings, 'regularization': value})
        with self.assertRaises(RecorderError):
            self.model(settings={**self.settings, 'features': ['elapsed_hours', 'unknown']})
        cohort = copy.deepcopy(self.cohort)
        cohort['training_rows'].append(copy.deepcopy(cohort['training_rows'][1]))
        with self.assertRaises(RecorderError):
            self.model(cohort)

    def test_constant_feature_has_zero_coefficient_and_changed_constant_abstains(self):
        settings = {**self.settings, 'features': ['elapsed_hours', 'saturation_delta']}
        model = self.model(settings=settings)
        self.assertEqual(model['parameters']['coefficients'][1], 0)
        forecasts = copy.deepcopy(self.cohort['forecast_rows'])
        forecasts[0]['features']['saturation_delta'] = .01
        rows, audit = self.api().forecast(model, forecasts)
        self.assertIsNone(rows[0]['hours_until_start'])
        self.assertIn('changed_constant_feature', audit[0]['reasons'])

    def test_cli_rejects_synthetic_biological_run_then_fits_scores_and_preserves_outputs(self):
        self.api()
        plan = self.save('fit-plan.json', self.settings)
        output = self.root / 'software-run'
        command = [sys.executable, '-B', '-m', 'behavior_recorder.appearance_predictor',
                   'fit', '--plan', str(plan), '--output', str(output)]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        result = subprocess.run(command + ['--software-test'], capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        model_bytes = (output / 'model.json').read_bytes()
        prediction = json.loads((output / 'predictions.json').read_text())
        self.assertEqual(prediction['dataset_kind'], 'test')
        self.assertEqual(prediction['cohort_sha256'], self.settings['cohort_sha256'])
        run = self.api().verify_run(plan, output)
        self.assertEqual(run['status'], 'software_test_only')
        self.assertFalse(run['actual_biological_fit'])
        scores = self.root / 'scores.json'
        score_command = [sys.executable, '-B', '-m', 'behavior_recorder.appearance_predictor',
                         'score', '--plan', str(plan), '--run', str(output),
                         '--evaluation-plan', str(self.root / 'evaluation.json'), '--output', str(scores)]
        result = subprocess.run(score_command, capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        scored = json.loads(scores.read_text())
        self.assertFalse(scored['biological_validation_complete'])
        self.assertTrue(scored['runner_integrity_verified'])
        result = subprocess.run(command + ['--software-test'], capture_output=True, text=True, env=env, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output / 'model.json').read_bytes(), model_bytes)
        damaged = json.loads(model_bytes)
        damaged['parameters']['intercept'] += 1
        (output / 'model.json').write_text(json.dumps(damaged))
        with self.assertRaises(RecorderError):
            self.api().verify_run(plan, output)

    def test_forecast_failure_preserves_completed_fit_and_reports_partial_execution(self):
        api = self.api()
        cohort = copy.deepcopy(self.cohort)
        cohort['forecast_rows'][0]['target'] = {'unexpected': 'future label'}
        path = self.save('bad-forecast-cohort.json', cohort)
        settings = {**self.settings, 'cohort': path.name,
                    'cohort_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        plan = self.save('bad-forecast-fit-plan.json', settings)
        output = self.root / 'failed-software-run'
        with self.assertRaisesRegex(RecorderError, 'label-free'):
            api.fit_run(plan, output, software_test=True)
        self.assertTrue((output / 'model.json').is_file())
        self.assertFalse((output / 'run.json').exists())
        failure = json.loads((output / 'failure.json').read_text())
        self.assertTrue(failure['fit_completed'])
        self.assertFalse(failure['forecast_completed'])
        self.assertFalse(failure['actual_biological_fit'])
        self.assertFalse(failure['automatic_retry'])

    def test_budget_failure_prevents_fit_and_preserves_initial_receipt(self):
        from unittest.mock import patch
        api = self.api()
        plan = self.save('fit-plan.json', self.settings)
        output = self.root / 'budget-software-run'

        def reject():
            raise RecorderError('bounded test budget exhausted')

        with patch.object(api, 'native_preflight', return_value=({'synthetic': True}, reject)):
            with self.assertRaisesRegex(RecorderError, 'budget exhausted'):
                api.fit_run(plan, output, software_test=True)
        self.assertTrue((output / 'started.json').exists())
        self.assertFalse((output / 'model.json').exists())
        failure = json.loads((output / 'failure.json').read_text())
        self.assertFalse(failure['fit_completed'])
        self.assertFalse(failure['actual_biological_fit'])


if __name__ == '__main__':
    unittest.main()
