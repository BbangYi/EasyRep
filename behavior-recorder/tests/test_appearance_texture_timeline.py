"""Synthetic RGB/cycle fixtures for causal texture integration, not animal data."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_appearance_predictor as fixtures
from behavior_recorder.appearance import collect
from behavior_recorder.appearance_texture import collect_texture
from behavior_recorder import appearance_evaluation as evaluation, appearance_predictor as predictor
from behavior_recorder.core import RecorderError, timestamp


class AppearanceTextureTimelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearancePredictorTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.temporal = self.fixture.fixture.fixture
        self.evaluation = self.fixture.fixture
        self.bindings = []
        for index, rid in enumerate(['train-a', 'train-b', 'train-c', 'future-history', 'future']):
            self.measure(rid, amplitude=10*(index+1))
        self.evaluation.refresh()
        self.plain = json.loads((self.root/'timeline.json').read_text())

    def save(self, name, value):
        return self.evaluation.save(name, value)

    def measure(self, rid, amplitude=20, created=None, pose='pose-1', dry=True):
        import numpy as np
        from PIL import Image
        existing = json.loads((self.root/(rid+'.json')).read_text())
        row = copy.deepcopy(existing['metadata'])
        row.update(image=rid+'.png', mask=rid+'-mask.png')
        row['review']['dry'] = dry
        array = np.repeat((100 + amplitude * (2*(np.indices((16,16)).sum(axis=0)%2)-1))[:, :, None], 3, axis=2).astype('uint8')
        Image.fromarray(array).save(self.root/row['image'])
        Image.new('L',(16,16),255).save(self.root/row['mask'])
        source = self.save(rid+'-input.json', row)
        # Explicitly simulated processing clocks; every fixture remains dataset_kind=test.
        with patch('behavior_recorder.appearance.now', return_value=row['observed_at']):
            colour = collect(source, self.root/(rid+'-collected-'+str(amplitude)+'-'+str(dry)+'.json'))
        self.save(rid+'.json', colour)
        plan = dict(schema_version=1, kind='appearance_texture_plan', observation_input=source.name,
            observation_artifact=rid+'.json', observation_sha256=hashlib.sha256((self.root/(rid+'.json')).read_bytes()).hexdigest(),
            extraction=dict(pixel_offset=1, minimum_pairs=16, max_clipped_fraction=.1, max_scale_relative_error=.05),
            geometry=dict(pixels_per_mm=10., scale_relative_error=.02, reference_revision='scale-1', pose_revision=pose, planar_region_confirmed=True),
            review=dict(observer='fixture-reviewer', flat_lighting_confirmed=True, same_pose_confirmed=True,
                        rights_confirmed=True, owner_id='fixture-creator', rights_evidence='generated fixture only'),
            evidence_reference='synthetic extraction and processing clock')
        plan_path = self.save(rid+'-texture-plan.json', plan)
        out = self.root/(rid+'-texture-'+str(len(list(self.root.glob(rid+'-texture-*.json'))))+'.json')
        with patch('behavior_recorder.appearance_texture.now', return_value=created or row['observed_at']):
            collect_texture(plan_path, out)
        self.bindings = [b for b in self.bindings if b['plan'] != plan_path.name]
        self.bindings.append(dict(plan=plan_path.name, artifact=out.name, sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
        return self.bindings[-1]

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('behavior_recorder.appearance_texture_timeline'), 'texture integration is missing')
        from behavior_recorder import appearance_texture_timeline
        return appearance_texture_timeline

    def timeline(self):
        self.api()
        self.temporal.plan['textures'] = self.bindings
        return self.temporal.report()

    def row(self, report, rid='train-c'):
        return next(row for row in report['rows'] if row['record_id'] == rid)

    def mutate(self, rid, update, rehash=True):
        b=next(b for b in self.bindings if b['plan']==rid+'-texture-plan.json')
        path=self.root/b['artifact'];value=json.loads(path.read_text());update(value);self.save(path.name,value)
        if rehash:b['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()

    def cohort(self, name='texture-cohort.json'):
        self.timeline(); self.evaluation.plan['feature_version']='past-only-reviewed-srgb-texture-v1'
        self.evaluation.refresh()
        cohort=self.evaluation.freeze(name)
        settings={**self.fixture.settings, 'features':['elapsed_hours','texture_absolute_delta','texture_absolute_rate'],
                  'cohort':name,'cohort_sha256':hashlib.sha256((self.root/name).read_bytes()).hexdigest()}
        return cohort, settings

    def test_hand_calculated_changes_rates_and_cycle_reset(self):
        report=self.timeline();row=self.row(report);f=row['features']
        self.assertAlmostEqual(f['texture_mean_absolute_difference'],60/255,places=6)
        self.assertAlmostEqual(f['texture_absolute_delta'],30/255,places=6)
        self.assertAlmostEqual(f['texture_absolute_rate'],20/255/24,places=6)
        self.assertEqual(f['texture_history_hours'],48)
        self.assertEqual(row['texture']['history_record_ids'],['train-a','train-b'])
        self.assertEqual(self.row(report,'future')['texture']['history_record_ids'],['future-history'])
        self.assertEqual(report['feature_version'],'past-only-reviewed-srgb-texture-v1')

    def test_late_current_processing_rebases_elapsed_and_target(self):
        self.mutate('train-c', lambda t:t.update(created_at='2026-11-04T03:00:00Z',available_at='2026-11-04T03:00:00Z'))
        row=self.row(self.timeline())
        self.assertEqual(timestamp(row['as_of']),timestamp('2026-11-04T03:00:00Z'))
        self.assertEqual(row['features']['hours_since_previous_completion'],[74,75])
        self.assertEqual(row['target']['hours_until_start'],[22,24])
        self.assertEqual(row['features']['texture_observation_age_hours'],2)

    def test_processing_after_onset_cannot_supply_pre_onset_target(self):
        self.mutate('train-c',lambda t:t.update(created_at='2026-11-05T04:00:00Z',available_at='2026-11-05T04:00:00Z'))
        row=self.row(self.timeline());self.assertIsNone(row['target'])
        self.assertIn('not_strictly_before_start',row['reasons'])

    def test_late_history_and_large_gaps_are_not_used(self):
        self.mutate('train-b',lambda t:t.update(created_at='2026-11-04T02:00:00Z',available_at='2026-11-04T02:00:00Z'))
        self.assertEqual(self.row(self.timeline())['texture']['history_record_ids'],['train-a'])
        self.temporal.plan['max_gap_hours']=24
        row=self.row(self.timeline());self.assertIsNone(row['features']['texture_absolute_delta'])
        self.assertEqual(row['features']['texture_history_hours'],0)

    def test_changed_pose_cannot_mix_comparison_groups(self):
        self.measure('train-c',amplitude=31,pose='pose-2')
        row=self.row(self.timeline());self.assertIsNone(row['features']['texture_absolute_delta'])
        self.assertEqual(row['texture']['history_record_ids'],[])

    def test_future_measurement_changes_do_not_change_earlier_features(self):
        before=self.row(self.timeline())
        self.measure('future',amplitude=55)
        self.assertEqual(before,self.row(self.timeline()))

    def test_missing_and_excluded_texture_are_null_not_zero(self):
        self.bindings=[b for b in self.bindings if b['plan']!='train-c-texture-plan.json']
        row=self.row(self.timeline());self.assertIsNone(row['features']['texture_mean_absolute_difference'])
        self.assertIn('not_bound',row['texture']['reasons'])
        self.measure('train-c',amplitude=32,dry=False)
        row=self.row(self.timeline());self.assertIsNone(row['features']);self.assertIsNone(row['target'])

    def test_sidecar_hash_and_source_binding_tampering_rejected(self):
        self.mutate('train-c',lambda t:t['features'].update(mean_absolute_difference=.9),rehash=False)
        with self.assertRaisesRegex(RecorderError,'hash'):self.timeline()

    def test_rehashed_inconsistent_measurement_is_rejected(self):
        self.mutate('train-c',lambda t:t['features'].update(mean_absolute_difference=.9))
        with self.assertRaisesRegex(RecorderError,'measurement'):self.timeline()

    def test_identity_dataset_and_flags_cannot_be_relabelled(self):
        for field,value in [('animal_id','other'),('body_region','head'),('dataset_kind','real')]:
            original=copy.deepcopy(self.bindings); b=next(b for b in self.bindings if b['plan']=='train-c-texture-plan.json')
            saved=(self.root/b['artifact']).read_bytes()
            self.mutate('train-c',lambda t:t['observation'].update({field:value}))
            with self.subTest(field=field),self.assertRaisesRegex(RecorderError,'observation'):self.timeline()
            (self.root/b['artifact']).write_bytes(saved);self.bindings=original
        self.mutate('train-c',lambda t:t.update(actuation_allowed=True))
        with self.assertRaisesRegex(RecorderError,'unpromoted'):self.timeline()

    def test_backdated_availability_rejected(self):
        self.mutate('train-c',lambda t:t.update(available_at='2026-11-01T00:00:00Z'))
        with self.assertRaisesRegex(RecorderError,'availability'):self.timeline()

    def test_duplicate_and_excessive_bindings_rejected(self):
        self.bindings.append(copy.deepcopy(self.bindings[-1]))
        with self.assertRaisesRegex(RecorderError,'duplicate'):self.timeline()
        self.bindings*=100
        with self.assertRaisesRegex(RecorderError,'512'):self.api().texture_inputs(self.bindings,self.root)

    def test_metadata_budget_rejects_before_loading_later_sidecars(self):
        api=self.api()
        with patch.object(api,'TEXTURE_LIMIT',100),self.assertRaisesRegex(RecorderError,'metadata'):self.timeline()

    def test_metadata_accounting_includes_referenced_colour_read(self):
        _, actual=self.api().texture_inputs(self.bindings,self.root)
        expected=0
        for binding in self.bindings:
            path=self.root/binding['plan'];plan=json.loads(path.read_text())
            expected+=sum(p.stat().st_size for p in [path,self.root/binding['artifact'],
                path.parent/plan['observation_input'],path.parent/plan['observation_artifact']])
        self.assertEqual(actual,expected)

    def test_end_to_end_cohort_fit_forecast_and_scoring(self):
        cohort,settings=self.cohort()
        model=predictor.train_artifact(cohort,settings,software_test=True)
        rows,audit=predictor.forecast(model,cohort['forecast_rows'])
        self.assertFalse(model['actual_biological_fit'])
        self.assertEqual(model['training']['row_count'],2)
        self.assertIn('appearance_texture_timeline.py',model['code_sha256'])
        payload=dict(schema_version=1,kind='appearance_point_predictions',dataset_kind='test',feature_version=model['feature_version'],
            model_id=model['model_id'],cohort_sha256=settings['cohort_sha256'],rows=rows)
        report=evaluation.evaluate_predictions(self.root/'evaluation.json',self.root/'texture-cohort.json',self.save('texture-predictions.json',payload))
        self.assertFalse(report['biological_validation_complete'])

    def test_feature_families_require_corresponding_bound_cohort(self):
        cohort,settings=self.cohort()
        with self.assertRaisesRegex(RecorderError,'context-bound'):
            predictor.train_artifact(cohort,{**settings,'features':['elapsed_hours','temperature_c']},software_test=True)
        cohort['feature_version']='past-only-reviewed-srgb-v1'
        with self.assertRaisesRegex(RecorderError,'texture-bound'):
            predictor.train_artifact(cohort,settings,software_test=True)

    def test_delayed_training_texture_cannot_cross_fit_cutoff(self):
        self.mutate('train-c',lambda t:t.update(created_at='2026-11-07T04:00:00Z',available_at='2026-11-07T04:00:00Z'))
        with self.assertRaisesRegex(RecorderError,'training feature crosses'):self.cohort()

    def test_optional_texture_removed_restores_colour_only_rows(self):
        self.timeline();self.temporal.plan.pop('textures');plain=self.temporal.report()
        self.assertEqual(evaluation.without_created(plain),evaluation.without_created(self.plain))

    def test_combined_context_texture_uses_same_updated_asof(self):
        import test_appearance_context as context_fixtures
        c=context_fixtures.AppearanceContextTests();c.setUp()
        c.root=self.root;c.fixture=self.fixture
        self.mutate('train-c',lambda t:t.update(created_at='2026-11-04T01:10:00Z',available_at='2026-11-04T01:10:00Z'))
        timeline=self.timeline()
        for anchor,row in zip(c.plan['anchors'],timeline['rows']):
            self.assertEqual(anchor['record_id'],row['record_id']);anchor['as_of']=row['as_of']
        path=self.save('context.json',c.build())
        self.temporal.plan['context']=dict(plan='context-plan.json',artifact=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        combined=self.timeline();self.assertEqual(combined['feature_version'],'past-only-reviewed-srgb-context-texture-v1')
        self.assertIsNotNone(self.row(combined)['features']['temperature_c'])
        self.assertIsNotNone(self.row(combined)['features']['texture_absolute_delta'])

    def test_old_context_anchors_cannot_be_reused_after_texture_delay(self):
        import test_appearance_context as context_fixtures
        c=context_fixtures.AppearanceContextTests();c.setUp();c.root=self.root;c.fixture=self.fixture
        path=self.save('context.json',c.build())
        self.temporal.plan['context']=dict(plan='context-plan.json',artifact=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.mutate('train-c',lambda t:t.update(created_at='2026-11-04T01:10:00Z',available_at='2026-11-04T01:10:00Z'))
        with self.assertRaisesRegex(RecorderError,'as_of mismatch'):self.timeline()

    def test_source_metadata_and_extractor_revision_mismatch_rejected(self):
        path=self.root/'train-c-input.json';original=path.read_bytes();value=json.loads(original);value['body_region']='head';self.save(path.name,value)
        with self.assertRaisesRegex(RecorderError,'source mismatch'):self.timeline()
        path.write_bytes(original)
        self.mutate('train-c',lambda t:t['implementation_sha256'].update({'appearance.py':'0'*64}))
        with self.assertRaisesRegex(RecorderError,'revision mismatch'):self.timeline()

    def test_runtime_change_remains_separate_comparison_group(self):
        from behavior_recorder.analysis_features import fingerprint
        colour=json.loads((self.root/'train-c.json').read_text())
        def change(t):
            t['runtime']['python']='different-recorded-runtime'
            t['comparison_group']=fingerprint(dict(feature_version=t['feature_version'],colour_group=colour['comparison_group'],
                extraction=t['extraction'],geometry=t['geometry'],implementation_sha256=t['implementation_sha256'],runtime=t['runtime']))
        self.mutate('train-c',change)
        self.assertEqual(self.row(self.timeline())['texture']['history_record_ids'],[])

    def test_false_rights_review_cannot_be_rehashed_into_measured_texture(self):
        from behavior_recorder.analysis_features import fingerprint
        path=self.root/'train-c-texture-plan.json';plan=json.loads(path.read_text());plan['review']['rights_confirmed']=False;self.save(path.name,plan)
        self.mutate('train-c',lambda t:t.update(review=plan['review'],plan_sha256=fingerprint(plan)))
        with self.assertRaisesRegex(RecorderError,'exclusions were removed'):self.timeline()

    def test_future_texture_does_not_change_train_normalization_or_model_id(self):
        first,settings=self.cohort();model=predictor.train_artifact(first,settings,software_test=True)
        self.measure('future',amplitude=56)
        other,settings=self.cohort('texture-cohort-two.json');second=predictor.train_artifact(other,settings,software_test=True)
        self.assertEqual(model['parameters'],second['parameters']);self.assertEqual(model['model_id'],second['model_id'])
        self.assertNotEqual(first['forecast_rows'],other['forecast_rows'])

    def test_missing_selected_texture_abstains_and_bad_numbers_reject(self):
        cohort,settings=self.cohort();model=predictor.train_artifact(cohort,settings,software_test=True)
        rows=copy.deepcopy(cohort['forecast_rows']);rows[0]['features']['texture_absolute_delta']=None
        predictions,audit=predictor.forecast(model,rows)
        self.assertIsNone(predictions[0]['hours_until_start']);self.assertIn('missing_texture_absolute_delta',audit[0]['reasons'])
        for invalid in [float('nan'),True,2]:
            rows[0]['features']['texture_absolute_delta']=invalid
            with self.subTest(invalid=invalid),self.assertRaises(RecorderError):predictor.forecast(model,rows)

    def test_output_and_cohort_metadata_limits_include_texture(self):
        self.api()
        with patch('behavior_recorder.appearance_timeline.encode',return_value=b'x'*(4*1024**2+1)),self.assertRaisesRegex(RecorderError,'4MiB'):
            self.timeline()
        self.timeline();self.evaluation.plan['feature_version']='past-only-reviewed-srgb-texture-v1';self.evaluation.refresh()
        api=self.api();original=api.texture_inputs
        def too_big(*args):
            entries,total=original(*args);return entries,33*1024**2
        with patch.object(api,'texture_inputs',side_effect=too_big),self.assertRaisesRegex(RecorderError,'32 MiB'):
            self.evaluation.freeze('too-big.json')

    def test_local_fit_and_score_cli_accepts_texture_cohort(self):
        import subprocess
        import sys
        cohort,settings=self.cohort();plan=self.save('texture-fit-plan.json',settings);output=self.root/'texture-software-run'
        fit=subprocess.run([sys.executable,'-B','-m','behavior_recorder.appearance_predictor','fit',
            '--plan',str(plan),'--output',str(output),'--software-test'],capture_output=True,text=True,timeout=20)
        self.assertEqual(fit.returncode,0,fit.stderr)
        receipt=predictor.verify_run(plan,output);self.assertFalse(receipt['actual_biological_fit'])
        scored=subprocess.run([sys.executable,'-B','-m','behavior_recorder.appearance_predictor','score',
            '--plan',str(plan),'--run',str(output),'--evaluation-plan',str(self.root/'evaluation.json'),
            '--output',str(self.root/'texture-score.json')],capture_output=True,text=True,timeout=20)
        self.assertEqual(scored.returncode,0,scored.stderr)
        self.assertFalse(json.loads((self.root/'texture-score.json').read_text())['biological_validation_complete'])
