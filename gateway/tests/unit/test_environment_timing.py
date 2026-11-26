"""R15 policy bounds and old MLP feature compatibility; no hardware or weights."""
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from habitat.compute.environment import MistingProposal, MIST_MAX_RUN_SECONDS
from habitat.control.r15_timing import request_timing, TIMING_MODE, TIMING_PROFILE

path = Path(__file__).resolve().parents[2] / 'experiments/environment_sim/predictive_misting.py'
spec = importlib.util.spec_from_file_location('predictive_misting_fixture', path)
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


class TimingTests(unittest.TestCase):
    def test_result_contract_rejects_overlong_or_inconsistent_proposals(self):
        base = dict(pulse_seconds=3., max_pulse_seconds=3., cooldown_minutes=3., decision='learned_forecast')
        self.assertEqual(MistingProposal(**base).pulse_seconds, MIST_MAX_RUN_SECONDS)
        for changes in ({'pulse_seconds':3.001}, {'max_pulse_seconds':6.},
                        {'max_pulse_seconds':2.}, {'pulse_seconds':float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                MistingProposal(**{**base, **changes})

    def test_candidates_stay_within_r15_and_input_scale_is_not_changed(self):
        cfg = experiment.settings()
        self.assertEqual(cfg['candidate_pulse_seconds'], [1,2,3])
        self.assertEqual(cfg['max_pulse_seconds'], MIST_MAX_RUN_SECONDS)
        h = np.tile([26.,65.,29.,25.,3.], (30,1))
        p = np.zeros((1,60)); p[0,0] = 3
        values = experiment.features(h,p,3)
        self.assertTrue(np.array_equal(values[0,4:150:5], np.full(30,.5)))
        self.assertEqual(values[0,150], .5)
        for changes in ({'max_pulse_seconds':6}, {'candidate_pulse_seconds':[2,4,6]},
                        {'candidate_pulse_seconds':[0]}, {'candidate_pulse_seconds':[]},
                        {'baseline_pulse_seconds':4}, {'candidate_pulse_seconds':[float('nan')]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                experiment.validate_timing({**cfg, **changes})

    def test_chooser_uses_model_forecasts_and_never_splits_oversize_actions(self):
        cfg = experiment.settings()
        history = np.tile([26.,65.,29.,25.,0.], (30,1))
        class ForecastFixture:
            plans = None
            def predict(self, history, plans):
                self.plans = plans
                values = np.tile([26.,65.,29.,25.], (len(plans),60,1))
                # Make a 2s first action uniquely preferable without a sensor rule.
                values[:,:,1] += (plans[:,0,None]-2)**2 * 20
                return values
        model = ForecastFixture()
        pulse, _, reason = experiment.choose(model,history,cfg['profiles'][1],cfg,30)
        self.assertEqual((pulse,reason), (2.,'learned_forecast'))
        self.assertTrue(set(np.unique(model.plans)) <= {0,1,2,3})
        bad = copy.deepcopy(cfg); bad['candidate_pulse_seconds'] = [4]
        with self.assertRaises(ValueError):
            experiment.choose(model,history,cfg['profiles'][1],bad,30)

    def test_request_candidates_are_forward_mapped_before_model_and_cost(self):
        cfg = experiment.settings()
        history = np.tile([26.,65.,29.,25.,0.], (30,1))
        for desired, hold in ((1.959, 3000), (3., 4500)):
            model = ForecastFixture(desired)
            selected, forecast, reason = experiment.choose_request_plan(model,history,cfg['profiles'][1],cfg,30)
            self.assertEqual(reason, 'learned_forecast')
            self.assertEqual(selected['request_hold_ms'][0], hold)
            self.assertEqual(selected['expected_virtual_run_s'][0], desired)
            self.assertEqual(forecast.shape, (60,4))
            self.assertEqual(len(selected['request_hold_ms']), 60)
            self.assertEqual(len(selected['expected_virtual_run_s']), 60)
            self.assertTrue(set(np.unique(model.plans)) <= {0., .959, 1.959, 2.959, 3.})
            self.assertTrue(np.any(model.plans == .959))
            for req, run in zip(selected['request_hold_ms'], selected['expected_virtual_run_s']):
                self.assertIs(type(req), int)
                self.assertEqual(request_timing(req)['expected_virtual_run_s'], run)

    def test_request_plan_interlocks_and_configured_run_limit_are_preserved(self):
        cfg = experiment.settings()
        history = np.tile([26.,65.,29.,25.,0.], (30,1))
        for flags in ({'fresh':False}, {'water_ok':False}, {'leak':True}):
            model = ForecastFixture(3.)
            selected, forecast, reason = experiment.choose_request_plan(model,history,cfg['profiles'][1],cfg,30,**flags)
            self.assertIsNone(model.plans)
            self.assertIsNone(forecast)
            self.assertEqual(reason, 'interlock')
            self.assertEqual(selected, {'request_hold_ms':[0]*60, 'expected_virtual_run_s':[0.]*60})
        limited = {**cfg, 'candidate_pulse_seconds':[1,2], 'baseline_pulse_seconds':2, 'max_pulse_seconds':2}
        model = ForecastFixture(3.)
        experiment.choose_request_plan(model,history,cfg['profiles'][1],limited,0)
        self.assertLessEqual(float(model.plans.max()), 2.)
        self.assertTrue((model.plans[:,:3] == 0).all())


class ForecastFixture:
    """Contract test double: no weights, training, field data or GPU execution."""
    def __init__(self, preferred=1.959):
        self.preferred = preferred
        self.plans = None

    def predict(self, history, plans):
        self.plans = np.array(plans, copy=True)
        values = np.tile([26.,65.,29.,25.], (len(plans),60,1))
        values[:,:,1] += np.abs(plans[:,0,None]-self.preferred) * 20
        return values


class GPUWorkerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the actual standalone request handler with explicit CUDA/model
        # doubles. No CUDA availability or trained-model claim follows from this.
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None,
                              get_device_name=lambda _: 'contract-test-double'))
        file = path.with_name('gpu_predict.py')
        spec = importlib.util.spec_from_file_location('gpu_predict_contract_fixture', file)
        cls.worker = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'torch':torch, 'predictive_misting':experiment}):
            spec.loader.exec_module(cls.worker)

    def request(self, schema=2):
        now = 1800000000.
        result = dict(schema_version=schema, mode='simulation', request_id='fixture',
                      site_id='site', gateway_id='gateway', cage_id='cage',
                      history=np.tile([26.,65.,29.,25.,0.], (30,1)).tolist(),
                      sample_times=[now-60*(29-i) for i in range(30)],
                      humidity_band=[60,70], temperature_band=[23,29], water_ok=True, leak=False)
        if schema == 2:
            result.update(timing_mode=TIMING_MODE, timing_profile=TIMING_PROFILE)
        return result

    def predict(self, request):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Tiny disposable checksum fixture; no real model file is touched.
            content = b'not-trained-weights-contract-fixture'
            (root/'model_3sensors.npz').write_bytes(content)
            (root/'training_report.json').write_text(json.dumps({'models':[
                {'weights_sha256':hashlib.sha256(content).hexdigest()}]}), encoding='utf-8')
            with patch.object(self.worker, 'ROOT', root), patch.object(self.worker.time, 'time', return_value=1800000000.), \
                    patch.object(self.worker, 'loaded_model', return_value=ForecastFixture()):
                return self.worker.predict(request)

    def test_schema2_preserves_full_plan_and_first_request_run_distinction(self):
        result = self.predict(self.request())
        self.assertEqual((result['schema_version'], result['timing_mode'], result['timing_profile']),
                         (2, TIMING_MODE, TIMING_PROFILE))
        plan, first = result['selected_plan'], result['misting_proposal']
        self.assertEqual((first['request_hold_ms'], first['expected_virtual_run_s'], first['pulse_seconds']),
                         (3000, 1.959, 1.959))
        self.assertEqual(len(plan['request_hold_ms']), 60)
        self.assertEqual(len(plan['expected_virtual_run_s']), 60)
        self.assertIn('phase-zero', result['prediction_condition'])
        self.assertFalse(result['field_validated'])
        self.assertFalse(result['hardware_execution_allowed'])
        self.assertEqual([p['horizon_minutes'] for p in result['predictions']], [5,10,30,60])

    def test_schema1_keeps_historical_response_shape_and_candidate_units(self):
        result = self.predict(self.request(1))
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['misting_proposal']['pulse_seconds'], 2.)
        self.assertEqual(set(result['misting_proposal']),
                         {'pulse_seconds','decision','cooldown_minutes','max_pulse_seconds'})
        for key in ('timing_mode', 'timing_profile', 'selected_plan'):
            self.assertNotIn(key, result)

    def test_schema2_interlock_returns_zero_plan_without_claiming_execution(self):
        request = self.request(); request['leak'] = True
        result = self.predict(request)
        self.assertEqual(result['misting_proposal']['decision'], 'interlock')
        self.assertEqual(result['selected_plan'], {'request_hold_ms':[0]*60, 'expected_virtual_run_s':[0.]*60})
        self.assertEqual(result['misting_proposal']['request_hold_ms'], 0)
        self.assertEqual(result['misting_proposal']['pulse_seconds'], 0.)

    def test_invalid_schema_mode_and_profile_rejected_before_model_access(self):
        invalid = [dict(schema_version=True), dict(schema_version=3), dict(schema_version='2'),
                   dict(schema_version=1), dict(timing_mode='desired_run_ideal'),
                   dict(timing_mode=None), dict(timing_profile='unknown'), dict(timing_profile=None)]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.worker.predict({**self.request(), **changes})
        for missing in ('timing_mode', 'timing_profile'):
            request = self.request(); del request[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.worker.predict(request)


if __name__ == '__main__':
    unittest.main()
