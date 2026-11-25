"""Synthetic temporal contracts; no biological observations, pixels or model fit."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import unittest

import test_appearance_series as fixtures
from behavior_recorder.core import RecorderError

if importlib.util.find_spec('behavior_recorder.appearance_timeline'):
    from behavior_recorder.appearance_timeline import build_timeline, write_timeline
else:
    build_timeline = write_timeline = None


class AppearanceTimelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AppearanceSeriesTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.plan = {'schema_version': 1, 'kind': 'appearance_temporal_plan',
                     'series': 'series.json', 'max_gap_hours': 48, 'cycles': []}

    def event(self, record_id, stage, earliest, latest=None):
        artifact = self.fixture.event(record_id, stage, earliest, latest or earliest)
        artifact['created_at'] = latest or earliest
        self.fixture.save(record_id + '.json', artifact)

    def color(self, record_id, observed, value=80, revision='camera-v1', created=None, wet=False):
        artifact = self.fixture.color(record_id, observed, revision=revision, wet=wet)
        artifact['created_at'] = created or observed
        if not wet:
            artifact['features'] = {'selected_pixels': 64, 'image_fraction': .5,
                                    'rgb_median': [value, value, value], 'rgb_iqr': [5, 5, 5],
                                    'saturation_median': 0, 'value_median': value / 255,
                                    'clipped_pixel_fraction': 0}
        self.fixture.save(record_id + '.json', artifact)
        return artifact

    def cycle(self):
        self.event('previous', 'completed', '2026-11-01T00:00:00Z', '2026-11-01T01:00:00Z')
        self.event('start', 'started', '2026-11-05T01:00:00Z', '2026-11-05T03:00:00Z')
        self.event('end', 'completed', '2026-11-06T01:00:00Z')
        self.plan['cycles'] = [{'cycle_id': 'cycle-one', 'previous_completed': 'previous',
                               'started': 'start', 'completed': 'end', 'role': 'train',
                               'observer': 'fixture-reviewer', 'evidence_reference': 'synthetic cycle linkage'}]

    def report(self):
        self.assertTrue(callable(build_timeline), 'temporal pipeline is not implemented')
        self.fixture.save('series.json', self.fixture.manifest)
        return build_timeline(self.fixture.save('plan.json', self.plan))

    def test_hand_calculated_past_change_and_interval_target(self):
        self.cycle()
        self.color('a', '2026-11-02T01:00:00Z', 80)
        self.color('b', '2026-11-03T01:00:00Z', 100)
        report = self.report()
        row = report['rows'][1]
        self.assertEqual(row['features']['history_record_ids'], ['a'])
        self.assertEqual(row['features']['rgb_delta'], [20, 20, 20])
        self.assertAlmostEqual(row['features']['rgb_change_per_hour'][0], 20 / 24)
        self.assertEqual(row['features']['hours_since_previous_completion'], [48, 49])
        self.assertEqual(row['target']['hours_until_start'], [48, 50])
        self.assertEqual(row['role'], 'train')
        self.assertEqual(report['counts']['linked_cycles'], 1)
        self.assertEqual(report['counts']['interval_labelled_rows'], 2)
        self.assertIsNone(report['shedding_prediction'])
        self.assertEqual(report['training_readiness'], 'not_assessed')
        self.assertFalse(report['actuation_allowed'])

    def test_future_values_and_input_order_cannot_change_earlier_features(self):
        self.cycle()
        self.color('a', '2026-11-02T01:00:00Z')
        self.color('b', '2026-11-03T01:00:00Z', 100)
        before = self.report()['rows'][1]
        self.color('future', '2026-11-04T01:00:00Z', 250)
        self.fixture.manifest['records'].reverse()
        after = next(r for r in self.report()['rows'] if r['record_id'] == 'b')
        self.assertEqual(before, after)

    def test_late_processed_observation_is_not_available_to_earlier_rows(self):
        self.cycle()
        self.color('late', '2026-11-02T01:00:00Z', 250, created='2026-11-06T02:00:00Z')
        self.color('b', '2026-11-03T01:00:00Z', 100)
        rows = {r['record_id']: r for r in self.report()['rows']}
        self.assertEqual(rows['b']['features']['history_record_ids'], [])
        self.assertIsNone(rows['late']['target'])
        self.assertIn('not_strictly_before_start', rows['late']['reasons'])

    def test_capture_change_gap_and_wet_observation_do_not_supply_history(self):
        self.cycle()
        self.color('a', '2026-11-02T01:00:00Z', revision='other')
        self.color('wet', '2026-11-02T12:00:00Z', wet=True)
        self.color('b', '2026-11-03T01:00:00Z')
        rows = {r['record_id']: r for r in self.report()['rows']}
        self.assertEqual(rows['b']['features']['history_record_ids'], [])
        self.assertIsNone(rows['wet']['features'])
        self.assertIsNone(rows['wet']['target'])
        self.color('c', '2026-11-04T01:00:00Z')
        self.plan['max_gap_hours'] = 12
        row = next(r for r in self.report()['rows'] if r['record_id'] == 'c')
        self.assertEqual(row['features']['history_record_ids'], [])

    def test_unlinked_and_uncertain_periods_never_become_negative_labels(self):
        self.color('a', '2026-11-02T01:00:00Z')
        row = self.report()['rows'][0]
        self.assertIsNone(row['target'])
        self.assertIsNone(row['role'])
        self.cycle()
        self.event('unclear', 'uncertain', '2026-11-03T00:00:00Z', '2026-11-04T00:00:00Z')
        row = self.report()['rows'][0]
        self.assertIsNone(row['target'])
        self.assertIn('unresolved_event_in_cycle', row['reasons'])

    def test_start_interval_boundary_is_not_a_pre_shedding_target(self):
        self.cycle()
        self.color('boundary', '2026-11-05T01:00:00Z')
        row = self.report()['rows'][0]
        self.assertIsNone(row['target'])
        self.assertIn('not_strictly_before_start', row['reasons'])

    def test_reused_missing_or_wrong_stage_cycle_links_are_rejected(self):
        self.cycle()
        original = copy.deepcopy(self.plan)
        for field, value in [('started', 'missing'), ('started', 'previous'), ('completed', 'previous')]:
            with self.subTest(field=field, value=value):
                self.plan = copy.deepcopy(original)
                self.plan['cycles'][0][field] = value
                with self.assertRaises(RecorderError):
                    self.report()
        self.plan = original
        self.plan['cycles'].append({**original['cycles'][0], 'cycle_id': 'duplicate'})
        with self.assertRaises(RecorderError):
            self.report()

    def test_temporal_roles_cannot_train_on_a_later_cycle_after_test(self):
        self.cycle()
        self.plan['cycles'][0]['role'] = 'test'
        self.event('start-two', 'started', '2026-11-10T01:00:00Z')
        self.event('end-two', 'completed', '2026-11-11T01:00:00Z')
        self.plan['cycles'].append({'cycle_id': 'cycle-two', 'previous_completed': 'end',
                                   'started': 'start-two', 'completed': 'end-two', 'role': 'train',
                                   'observer': 'fixture-reviewer', 'evidence_reference': 'synthetic'})
        with self.assertRaises(RecorderError):
            self.report()
        self.plan['cycles'][0]['role'] = 'train'
        self.plan['cycles'][1]['role'] = 'test'
        self.color('train-a', '2026-11-02T01:00:00Z')
        self.color('test-a', '2026-11-07T01:00:00Z', 100)
        rows = self.report()['rows']
        self.assertEqual([r['role'] for r in rows], ['train', 'test'])
        self.assertEqual(rows[1]['features']['history_record_ids'], [])

    def test_numeric_feature_corruption_and_ambiguous_timestamps_are_rejected(self):
        original = self.color('a', '2026-11-02T01:00:00Z')
        for key, value in [('rgb_median', [80, True, 80]), ('value_median', float('nan')),
                           ('image_fraction', 0), ('selected_pixels', 0), ('rgb_iqr', [-1, 2, 3])]:
            with self.subTest(key=key):
                bad = copy.deepcopy(original)
                bad['features'][key] = value
                self.fixture.save('a.json', bad)
                with self.assertRaises((RecorderError, ValueError)):
                    self.report()
        self.fixture.save('a.json', original)
        self.color('same-time', '2026-11-02T10:00:00+09:00')
        with self.assertRaises(RecorderError):
            self.report()

    def test_unrecorded_completion_cannot_supply_a_known_previous_shed_feature(self):
        self.cycle()
        previous = json.loads((self.root / 'previous.json').read_text())
        previous['created_at'] = '2026-11-04T00:00:00Z'
        self.fixture.save('previous.json', previous)
        self.color('a', '2026-11-02T01:00:00Z')
        row = self.report()['rows'][0]
        self.assertIsNone(row['features']['hours_since_previous_completion'])
        self.assertIsNone(row['target'])
        self.assertIn('previous_completion_not_available', row['reasons'])

    def test_cli_writes_once_and_leaves_source_intact(self):
        self.cycle()
        self.color('a', '2026-11-02T01:00:00Z')
        self.report()
        path = self.root / 'plan.json'
        before = path.read_bytes()
        output = self.root / 'timeline.json'
        command = [sys.executable, '-m', 'behavior_recorder.appearance_timeline',
                   '--plan', str(path), '--output', str(output)]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        first = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = output.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, timeout=10, env=env)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(output.read_bytes(), saved)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(RecorderError):
            write_timeline(path, path)

    def test_label_availability_cannot_precede_its_confirmed_completion_interval(self):
        self.cycle()
        end = json.loads((self.root / 'end.json').read_text())
        end['created_at'] = '2026-11-02T00:00:00Z'
        self.fixture.save('end.json', end)
        self.color('a', '2026-11-02T01:00:00Z')
        self.assertEqual(self.report()['rows'][0]['target']['available_at'],
                         '2026-11-06T01:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
