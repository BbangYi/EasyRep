"""Synthetic clock, provenance and multimodal integration checks; no real observations."""
import copy
import hashlib
import importlib.util
import json
import unittest
from unittest.mock import patch
import subprocess
import sys
from datetime import timedelta

import test_appearance_predictor as fixtures
from behavior_recorder.core import RecorderError, timestamp
from behavior_recorder import appearance_evaluation as evaluation, appearance_predictor as predictor

if importlib.util.find_spec('behavior_recorder.appearance_context'):
    from behavior_recorder import appearance_context as context
else:
    context = None


def clock(error=0):
    return dict(source='operator', accuracy_ms=error)


class AppearanceContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearancePredictorTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        timeline = json.loads((self.root/'timeline.json').read_text())
        self.identity = timeline['identity']
        self.plan = dict(schema_version=1, kind='appearance_context_plan',
            dataset_kind='test', animal_id=self.identity['animal_id'], enclosure_id=self.identity['enclosure_id'],
            observer='fixture-reviewer', evidence_reference='synthetic binding, not independent identity verification',
            max_clock_error_ms=2000, behaviour_window_seconds=3600, min_behaviour_coverage=.4,
            sensors=[dict(feature='temperature_c', sensor_id='temp', unit='Cel', max_age_seconds=3600,
                          geometry_revision='geometry-1', placement_revision='placement-1'),
                     dict(feature='humidity_percent', sensor_id='humid', unit='%RH', max_age_seconds=3600,
                          geometry_revision='geometry-1', placement_revision='placement-1')],
            anchors=[dict(record_id=r['record_id'], observed_at=r['observed_at'], as_of=r['as_of'],
                          observed_clock=clock(), as_of_clock=clock()) for r in timeline['rows']], sources=[])
        self.sensors, self.behaviour = [], []
        for a in self.plan['anchors']:
            t=timestamp(a['as_of']);rid=a['record_id']
            self.sensors.append(dict(record_id=rid+'-sensor', enclosure_id=self.plan['enclosure_id'],
                observed_at=(t-timedelta(seconds=60)).isoformat(), received_at=(t-timedelta(seconds=40)).isoformat(),
                recorded_at=(t-timedelta(seconds=20)).isoformat(), observed_clock=clock(),received_clock=clock(),recorded_clock=clock(),
                source='simulation',geometry_revision='geometry-1',placement_revision='placement-1',
                readings=[dict(sensor_id='temp',unit='Cel',value=24.,quality='valid'),
                          dict(sensor_id='humid',unit='%RH',value=65.,quality='valid')]))
            self.behaviour.append(dict(record_id=rid+'-behaviour',animal_id=self.plan['animal_id'],enclosure_id=self.plan['enclosure_id'],
                start_at=(t-timedelta(seconds=2400)).isoformat(),end_at=(t-timedelta(seconds=600)).isoformat(),
                observed_clock=clock(),received_at=(t-timedelta(seconds=500)).isoformat(),received_clock=clock(),
                recorded_at=(t-timedelta(seconds=400)).isoformat(),recorded_clock=clock(),
                quality='valid',identity_method='human_confirmed',active_seconds=450.,
                observer='fixture-reviewer',evidence_reference='synthetic reviewed activity interval'))

    def tearDown(self):
        self.fixture.fixture.fixture.tearDown()

    def api(self):
        self.assertIsNotNone(context,'context alignment is not implemented')
        return context

    def save(self,name,value):
        return self.fixture.save(name,value)

    def build(self):
        sources=[]
        for kind,rows in [('sensors',self.sensors),('behaviour',self.behaviour)]:
            path=self.save(kind+'.json',dict(schema_version=1,kind='appearance_context_'+kind,
                                            dataset_kind='test',records=rows))
            sources.append(dict(kind=kind,path=kind+'.json',sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.plan['sources']=sources
        return self.api().build_context(self.save('context-plan.json',self.plan))

    def row(self,report,index=0):
        return report['rows'][index]

    def test_valid_features_have_units_coverage_and_provenance(self):
        report=self.build();row=self.row(report)
        self.assertEqual(row['features'],dict(temperature_c=24.,humidity_percent=65.,activity_fraction=.25,behaviour_coverage=.5))
        self.assertEqual(len(row['audit']['temperature_c']['used']),1)
        self.assertEqual(len(row['audit']['activity_fraction']['used']),1)
        self.assertFalse(report['independent_identity_or_clock_verification'])
        self.assertFalse(report['actuation_allowed'])

    def test_backfilled_received_and_recorded_times_cannot_leak(self):
        for field in ['received_at','recorded_at']:
            with self.subTest(field=field):
                row=self.sensors[0];old=row[field];row[field]='2027-01-01T00:00:00Z'
                result=self.row(self.build())
                self.assertIsNone(result['features']['temperature_c'])
                self.assertIn('not_available',str(result['audit']))
                row[field]=old

    def test_future_and_boundary_crossing_clock_uncertainty_are_excluded(self):
        self.sensors[0]['observed_at']=self.plan['anchors'][0]['as_of']
        self.sensors[0]['observed_clock']=clock(1)
        self.sensors[0]['received_at']=self.plan['anchors'][0]['as_of']
        self.sensors[0]['recorded_at']=self.plan['anchors'][0]['as_of']
        row=self.row(self.build())
        self.assertIsNone(row['features']['temperature_c'])
        self.assertIn('not_safely_past',str(row['audit']))

    def test_unknown_anchor_and_source_clock_never_mean_exact_zero(self):
        self.plan['anchors'][0]['as_of_clock']=dict(source='unknown',accuracy_ms=None)
        row=self.row(self.build());self.assertTrue(all(v is None for v in row['features'].values()))
        self.plan['anchors'][0]['as_of_clock']=clock()
        self.sensors[0]['observed_clock']=dict(source='unknown',accuracy_ms=None)
        self.assertIsNone(self.row(self.build())['features']['temperature_c'])

    def test_stale_invalid_unit_revision_and_wrong_enclosure_do_not_fallback(self):
        for change in ['unit','quality','revision','enclosure','stale']:
            with self.subTest(change=change):
                original=copy.deepcopy(self.sensors[0]);r=self.sensors[0]
                if change=='unit':r['readings'][0]['unit']='F'
                elif change=='quality':r['readings'][0].update(quality='invalid',value=None)
                elif change=='revision':r['placement_revision']='placement-2'
                elif change=='enclosure':r['enclosure_id']='different-enclosure'
                else:r['observed_at']=(timestamp(self.plan['anchors'][0]['as_of'])-timedelta(hours=2)).isoformat()
                self.assertIsNone(self.row(self.build())['features']['temperature_c'])
                self.sensors[0]=original

    def test_newer_invalid_sensor_blocks_older_valid_value(self):
        old=copy.deepcopy(self.sensors[0]);old['record_id']='older';old['observed_at']=(timestamp(old['observed_at'])-timedelta(seconds=60)).isoformat()
        self.sensors.append(old);self.sensors[0]['readings'][0].update(quality='invalid',value=None)
        self.assertIsNone(self.row(self.build())['features']['temperature_c'])

    def test_uncertainty_overlapping_sensor_order_is_ambiguous(self):
        old=copy.deepcopy(self.sensors[0]);old['record_id']='overlap';old['observed_clock']=clock(1000)
        self.sensors[0]['observed_clock']=clock(1000)
        old['observed_at']=(timestamp(old['observed_at'])-timedelta(milliseconds=500)).isoformat()
        self.sensors.append(old)
        self.assertIsNone(self.row(self.build())['features']['temperature_c'])
        self.assertIn('ambiguous',str(self.row(self.build())['audit']))

    def test_activity_identity_and_missing_coverage_are_not_zero_activity(self):
        self.behaviour[0]['identity_method']='unknown'
        self.assertIsNone(self.row(self.build())['features']['activity_fraction'])
        self.behaviour[0]['identity_method']='human_confirmed';self.plan['min_behaviour_coverage']=.75
        row=self.row(self.build());self.assertIsNone(row['features']['activity_fraction']);self.assertEqual(row['features']['behaviour_coverage'],.5)
        self.behaviour=[]
        row=self.row(self.build());self.assertIsNone(row['features']['activity_fraction']);self.assertIsNone(row['features']['behaviour_coverage'])

    def test_overlapping_behaviour_is_not_counted_twice(self):
        duplicate=copy.deepcopy(self.behaviour[0]);duplicate['record_id']='overlap';self.behaviour.append(duplicate)
        row=self.row(self.build());self.assertIsNone(row['features']['activity_fraction']);self.assertIn('overlap',str(row['audit']))

    def test_behaviour_wrong_animal_and_future_end_are_excluded(self):
        self.behaviour[0]['animal_id']='another-animal'
        self.assertIsNone(self.row(self.build())['features']['activity_fraction'])
        self.behaviour[0]['animal_id']=self.plan['animal_id'];self.behaviour[0]['end_at']='2027-01-01T00:00:00Z'
        self.assertIsNone(self.row(self.build())['features']['activity_fraction'])

    def test_invalid_schemas_bounds_duplicates_and_real_test_mixing_rejected(self):
        self.build();path=self.root/'context-plan.json'
        for field,value in [('max_clock_error_ms',True),('min_behaviour_coverage',0),('behaviour_window_seconds',float('nan'))]:
            with self.subTest(field=field):
                plan=copy.deepcopy(self.plan);plan[field]=value
                with self.assertRaises(RecorderError):self.api().build_context(self.save('bad.json',plan))
        self.sensors.append(copy.deepcopy(self.sensors[0]))
        with self.assertRaisesRegex(RecorderError,'duplicate'):self.build()
        self.sensors.pop();self.build();p=self.root/'sensors.json';d=json.loads(p.read_text());d['dataset_kind']='real';self.save('sensors.json',d)
        self.plan['sources'][0]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError,'dataset_kind'):self.api().build_context(self.save('bad.json',self.plan))

    def test_source_hash_and_artifact_regeneration_reject_tampering(self):
        report=self.build();self.save('context.json',report)
        binding=dict(plan='context-plan.json',artifact='context.json',sha256=hashlib.sha256((self.root/'context.json').read_bytes()).hexdigest())
        timeline=json.loads((self.root/'timeline.json').read_text())
        report['rows'][0]['features']['temperature_c']=99;self.save('context.json',report)
        binding['sha256']=hashlib.sha256((self.root/'context.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError,'regenerated'):self.api().attach_context(timeline,binding,self.root)
        self.save('context.json',self.build());self.save('sensors.json',{})
        binding['sha256']=hashlib.sha256((self.root/'context.json').read_bytes()).hexdigest()
        with self.assertRaisesRegex(RecorderError,'hash'):self.api().attach_context(timeline,binding,self.root)

    def test_context_binding_requires_exact_animal_observation_and_asof(self):
        report=self.build();timeline=json.loads((self.root/'timeline.json').read_text())
        for change in ['animal','time','missing']:
            with self.subTest(change=change):
                original=copy.deepcopy(self.plan)
                if change=='animal':self.plan['animal_id']='different-animal'
                elif change=='time':self.plan['anchors'][0]['as_of']='2027-01-01T00:00:00Z'
                else:self.plan['anchors'].pop()
                self.save('context.json',self.build())
                b=dict(plan='context-plan.json',artifact='context.json',sha256=hashlib.sha256((self.root/'context.json').read_bytes()).hexdigest())
                with self.assertRaises(RecorderError):self.api().attach_context(copy.deepcopy(timeline),b,self.root)
                self.plan=original

    def test_multimodal_timeline_cohort_fit_forecast_scoring_and_colour_compatibility(self):
        self.api();old=json.loads((self.root/'timeline.json').read_text())
        self.save('context.json',self.build())
        f=self.fixture.fixture
        f.fixture.plan['context']=dict(plan='context-plan.json',artifact='context.json',sha256=hashlib.sha256((self.root/'context.json').read_bytes()).hexdigest())
        f.plan['feature_version']='past-only-reviewed-srgb-context-v1';f.refresh()
        cohort=f.freeze('context-cohort.json')
        settings={**self.fixture.settings,'cohort':'context-cohort.json','cohort_sha256':hashlib.sha256((self.root/'context-cohort.json').read_bytes()).hexdigest(),
                  'features':['elapsed_hours','red_delta','temperature_c','humidity_percent','activity_fraction']}
        model=predictor.train_artifact(cohort,settings,software_test=True)
        rows,audit=predictor.forecast(model,cohort['forecast_rows'])
        self.assertFalse(model['actual_biological_fit']);self.assertEqual(model['feature_version'],f.plan['feature_version'])
        payload=dict(schema_version=1,kind='appearance_point_predictions',dataset_kind='test',feature_version=model['feature_version'],
                     model_id=model['model_id'],cohort_sha256=settings['cohort_sha256'],rows=rows)
        scored=evaluation.evaluate_predictions(self.root/'evaluation.json',self.root/'context-cohort.json',self.save('context-predictions.json',payload))
        self.assertFalse(scored['biological_validation_complete'])
        f.fixture.plan.pop('context');f.plan['feature_version']='past-only-reviewed-srgb-v1';f.refresh()
        new=json.loads((self.root/'timeline.json').read_text());old.pop('created_at');new.pop('created_at')
        self.assertEqual(old,new)

    def test_resource_guard_rejects_cumulative_output_before_later_anchors(self):
        self.build()
        class RowsTooLarge:
            def __init__(self): self.calls=0
            def __call__(self, value):
                self.calls += 1
                if self.calls > 2: raise AssertionError('continued building an oversized artifact')
                return b'x' * 5000000
        encoder=RowsTooLarge()
        with patch.object(context, 'encode', side_effect=encoder):
            with self.assertRaisesRegex(RecorderError, '8 MiB'):
                context.build_context(self.root/'context-plan.json')

    def test_receipt_before_event_and_review_before_receipt_are_rejected(self):
        self.sensors[0]['received_at']=(timestamp(self.sensors[0]['observed_at'])-timedelta(seconds=10)).isoformat()
        row=self.row(self.build());self.assertIsNone(row['features']['temperature_c'])
        self.assertIn('precedes_event',str(row['audit']))
        self.behaviour[0]['recorded_at']=(timestamp(self.behaviour[0]['received_at'])-timedelta(seconds=10)).isoformat()
        row=self.row(self.build());self.assertIsNone(row['features']['activity_fraction'])
        self.assertIn('precedes_receipt',str(row['audit']))

    def test_context_feature_selection_rejects_colour_only_cohort(self):
        self.api()
        settings={**self.fixture.settings, 'features':['elapsed_hours','temperature_c']}
        with self.assertRaisesRegex(RecorderError,'context-bound'):
            predictor.train_artifact(self.fixture.cohort, settings, software_test=True)

    def test_context_cli_host_resources_versioned_output_and_no_overwrite(self):
        import platform
        self.build()
        command=[sys.executable,'-B','-m','behavior_recorder.appearance_context','--plan',str(self.root/'context-plan.json'),
                 '--output',str(self.root/'cli-context.json'),'--execution-host',platform.node()]
        first=subprocess.run(command,capture_output=True,text=True,timeout=15)
        self.assertEqual(first.returncode,0,first.stderr)
        before=(self.root/'cli-context.json').read_bytes()
        second=subprocess.run(command,capture_output=True,text=True,timeout=15)
        self.assertNotEqual(second.returncode,0)
        self.assertIn('already exists',second.stderr)
        self.assertEqual(before,(self.root/'cli-context.json').read_bytes())
        result=json.loads(before);self.assertFalse(result['actual_model_fit'])
