"""Measured values, estimate freshness and receive-only HTTP behavior."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

import numpy as np

from habitat.digital_twin.air.model import AirModel, load_config
from habitat.digital_twin.air.service import AirState, start_server
from habitat.saas.air_contract import MODEL_ID, MODEL_VERSION


CONFIG = Path(__file__).resolve().parents[2] / 'configs/examples/air-viewer.json'
NOW = datetime(2026, 10, 24, 4, 0, tzinfo=timezone.utc)


def event(index=0, stamp=None, values=(23.2, 23., 23.)):
    readings = {
        key: dict(value=value, quality='valid')
        for key, value in zip(('T1', 'T2', 'T3'), values)
    }
    return dict(
        event='telemetry', fresh_unique=True, retained=False,
        message_id=str(UUID(int=index + 1)),
        sampled_at=(stamp or NOW + timedelta(seconds=5 * index)).isoformat(),
        readings=readings, payload=dict(readings=copy.deepcopy(readings)),
    )


class AirStateTests(unittest.TestCase):
    def test_generated_at_is_fixed_to_accepted_sample_and_keeps_model_identity(self):
        state = AirState(CONFIG)
        self.assertIsNone(state.snapshot(NOW, 0)['generated_at'])
        received = NOW + timedelta(seconds=2)
        self.assertTrue(state.ingest(event(), received, 0))
        initial = state.snapshot(received, 0)
        later = state.snapshot(received + timedelta(seconds=90), 90)
        self.assertEqual(initial['generated_at'], received.isoformat(timespec='milliseconds'))
        self.assertEqual(later['generated_at'], initial['generated_at'])
        self.assertEqual(later['model_id'], MODEL_ID)
        self.assertEqual(later['model_version'], MODEL_VERSION)
        self.assertEqual(later['stale_after_s'], state.cfg['stale_after_s'])
        self.assertFalse(state.ingest(event(), received + timedelta(seconds=90), 90))
        self.assertEqual(state.snapshot(received, 90)['generated_at'], initial['generated_at'])
        newest = NOW + timedelta(seconds=95)
        self.assertTrue(state.ingest(event(1, newest), newest, 95))
        self.assertEqual(state.snapshot(newest, 95)['generated_at'], newest.isoformat(timespec='milliseconds'))

    def test_temperature_triplet_preserves_measurements_and_message_id(self):
        state = AirState(CONFIG)
        waiting = state.snapshot(NOW, 0)
        self.assertEqual(waiting['status'], 'waiting')
        self.assertIsNone(waiting['message_id'])
        self.assertIsNone(waiting['field'])
        data = event(values=(22.375, 23.125, 24.625))
        data['readings']['RH1'] = dict(value=None, quality='invalid')
        self.assertTrue(state.ingest(data, NOW, 0))
        snap = state.snapshot(NOW, 0)
        self.assertTrue(snap['fresh'])
        self.assertFalse(snap['held'])
        self.assertEqual(snap['status'], 'live')
        self.assertEqual(snap['message_id'], data['message_id'])
        self.assertEqual([s['value_c'] for s in snap['sensors']], [22.375, 23.125, 24.625])
        self.assertEqual(snap['field']['method'], 'flow_sensor')
        self.assertEqual(snap['baseline']['method'], 'idw')
        self.assertEqual(snap['grid']['shape_zyx'], [30, 20, 20])
        self.assertEqual(len(snap['field']['values_c']), 12000)
        self.assertTrue(np.isfinite(snap['field']['values_c']).all())
        self.assertGreaterEqual(min(snap['baseline']['values_c']), 22.375)
        self.assertLessEqual(max(snap['baseline']['values_c']), 24.625)
        self.assertIn('가정', ' '.join(snap['assumptions']))

    def test_rejection_holds_last_accepted_field_id_and_measurements(self):
        cases = (
            'retained', 'not_unique', 'duplicate', 'out_of_order',
            'future', 'missing', 'invalid', 'nan', 'infinity', 'boolean',
            'range', 'unit', 'message_id', 'timestamp', 'naive_timestamp',
            'payload_shape', 'readings_shape', 'reading_shape',
        )
        for case in cases:
            with self.subTest(case=case):
                state = AirState(CONFIG)
                first = event()
                self.assertTrue(state.ingest(first, NOW, 0))
                before = state.snapshot(NOW, 0)
                bad = event(1)
                received = NOW + timedelta(seconds=5)
                if case == 'retained': bad['retained'] = True
                if case == 'not_unique': bad['fresh_unique'] = False
                if case == 'duplicate': bad['message_id'] = first['message_id']
                if case == 'out_of_order': bad['sampled_at'] = first['sampled_at']
                if case == 'future': bad['sampled_at'] = (NOW + timedelta(seconds=60)).isoformat()
                if case == 'missing': del bad['readings']['T2']
                if case == 'invalid': bad['readings']['T2'] = dict(value=None, quality='invalid')
                if case == 'nan': bad['readings']['T2']['value'] = float('nan')
                if case == 'infinity': bad['readings']['T2']['value'] = float('inf')
                if case == 'boolean': bad['readings']['T2']['value'] = True
                if case == 'range': bad['readings']['T2']['value'] = 60.01
                if case == 'unit': bad['payload']['readings']['T2']['unit'] = 'degF'
                if case == 'message_id': bad['message_id'] = ''
                if case == 'timestamp': bad['sampled_at'] = 'not-a-time'
                if case == 'naive_timestamp': bad['sampled_at'] = '2026-10-24T04:00:05'
                if case == 'payload_shape': bad['payload'] = None
                if case == 'readings_shape': bad['readings'] = []
                if case == 'reading_shape': bad['readings']['T2'] = None
                self.assertFalse(state.ingest(bad, received, 5))
                # Inspect before the accepted sample expires; a rejected reading
                # must not mutate the measured values or the model's time step.
                snap = state.snapshot(NOW + timedelta(seconds=5), 5)
                self.assertEqual(snap['status'], 'held')
                self.assertFalse(snap['fresh'])
                self.assertTrue(snap['held'])
                self.assertEqual(snap['accepted_samples'], 1)
                self.assertEqual(snap['rejected_samples'], 1)
                self.assertEqual(snap['message_id'], first['message_id'])
                self.assertEqual(snap['sampled_at'], before['sampled_at'])
                self.assertEqual(snap['sensors'], before['sensors'])
                self.assertEqual(snap['field'], before['field'])
                self.assertEqual(state.model.last_stamp, NOW)
                later = NOW + timedelta(seconds=10)
                self.assertTrue(state.ingest(event(2), later, 10))
                self.assertTrue(state.snapshot(later, 10)['fresh'])

    def test_delayed_valid_measurements_update_field_without_becoming_fresh(self):
        state = AirState(CONFIG)
        old = NOW - timedelta(seconds=55)
        self.assertTrue(state.ingest(event(stamp=old), NOW, 0))
        snapshot = state.snapshot(NOW, 0)
        self.assertEqual(snapshot['status'], 'stale')
        self.assertEqual(snapshot['data_origin'], 'mqtt')
        self.assertEqual(snapshot['source_age_seconds'], 55)
        self.assertEqual(snapshot['sampled_at'], old.isoformat(timespec='milliseconds'))
        self.assertEqual(snapshot['received_at_utc'], NOW.isoformat(timespec='milliseconds'))
        self.assertIsNotNone(snapshot['field'])
        self.assertFalse(snapshot['fresh'])
        self.assertTrue(snapshot['held'])
        self.assertEqual((snapshot['accepted_samples'], snapshot['live_samples']), (1, 1))
        newer = event(1, old + timedelta(seconds=5), (24., 23., 22.))
        self.assertTrue(state.ingest(newer, NOW, 1))
        self.assertEqual(state.snapshot(NOW, 1)['message_id'], newer['message_id'])
        self.assertEqual(state.snapshot(NOW, 1)['status'], 'stale')

    def test_identical_numbers_with_new_ids_and_times_are_separate_measurements(self):
        state = AirState(CONFIG)
        for index in range(3):
            stamp = NOW + timedelta(seconds=5 * index)
            self.assertTrue(state.ingest(event(index, stamp, (25., 25., 25.)), stamp, 5 * index))
        snapshot = state.snapshot(NOW + timedelta(seconds=10), 10)
        self.assertEqual(snapshot['accepted_samples'], 3)
        self.assertEqual(snapshot['live_samples'], 3)
        self.assertEqual(snapshot['history_samples'], 0)
        self.assertEqual([sensor['value_c'] for sensor in snapshot['sensors']], [25., 25., 25.])
        self.assertTrue(snapshot['fresh'])

    def test_history_restores_original_values_time_and_identity_without_receipt(self):
        state = AirState(CONFIG)
        loaded = NOW + timedelta(days=5)
        data = event(values=(22.375, 23.125, 24.625))
        self.assertTrue(state.restore(data, now=loaded))
        initial = state.snapshot(loaded)
        self.assertEqual(initial['status'], 'history')
        self.assertEqual(initial['data_origin'], 'history')
        self.assertEqual(initial['message_id'], data['message_id'])
        self.assertEqual(initial['sampled_at'], NOW.isoformat(timespec='milliseconds'))
        self.assertEqual(initial['generated_at'], loaded.isoformat(timespec='milliseconds'))
        self.assertEqual(initial['loaded_at'], loaded.isoformat(timespec='milliseconds'))
        self.assertEqual(initial['source_age_seconds'], 5 * 86400)
        self.assertEqual([sensor['value_c'] for sensor in initial['sensors']], [22.375, 23.125, 24.625])
        self.assertEqual((initial['accepted_samples'], initial['history_samples'], initial['live_samples']), (1, 1, 0))
        self.assertIsNone(initial['received_at_utc'])
        self.assertIsNone(initial['age_seconds'])
        self.assertFalse(initial['fresh'])
        self.assertTrue(initial['held'])
        self.assertFalse(state.restore(copy.deepcopy(data), now=loaded + timedelta(seconds=1)))
        self.assertEqual(state.snapshot(loaded + timedelta(seconds=10))['generated_at'], initial['generated_at'])
        state.mark('waiting', 'mqtt_connected_waiting_for_telemetry')
        self.assertEqual(state.snapshot(loaded)['status'], 'history')
        state.ingest(dict(event='status', online=True), now=loaded)
        self.assertEqual(state.snapshot(loaded)['status'], 'history')
        state.mark('held', 'invalid_sensor_message')
        self.assertEqual(state.snapshot(loaded)['status'], 'held')
        state.mark('offline', 'bb6_status_offline')
        self.assertEqual(state.snapshot(loaded)['status'], 'offline')
        self.assertIsNotNone(state.snapshot(loaded)['field'])

    def test_recent_history_is_not_live_and_matching_mqtt_promotes_without_recalculation(self):
        state = AirState(CONFIG)
        data = event()
        state.restore(data, now=NOW)
        before = state.snapshot(NOW)
        self.assertFalse(before['fresh'])
        with patch.object(state.model, 'update', side_effect=AssertionError('must not recalculate')):
            self.assertTrue(state.ingest(copy.deepcopy(data), NOW + timedelta(seconds=1), 10))
        after = state.snapshot(NOW + timedelta(seconds=1), 10)
        self.assertTrue(after['fresh'])
        self.assertEqual(after['data_origin'], 'mqtt')
        self.assertEqual((after['accepted_samples'], after['history_samples'], after['live_samples']), (1, 1, 1))
        self.assertEqual(after['generated_at'], before['generated_at'])
        self.assertEqual(after['field'], before['field'])
        self.assertEqual(after['received_at_utc'], (NOW + timedelta(seconds=1)).isoformat(timespec='milliseconds'))

    def test_history_restore_preserves_offline_before_and_during_batch(self):
        state = AirState(CONFIG)
        loaded = NOW + timedelta(days=1)
        state.mark('offline', 'bb6_status_offline')
        self.assertTrue(state.restore(event(), now=loaded))
        first = state.snapshot(loaded)
        self.assertEqual(first['status'], 'offline')
        self.assertEqual(first['status_reason'], 'bb6_status_offline')
        self.assertIsNotNone(first['field'])
        self.assertFalse(first['fresh'])
        state.mark('offline', 'mqtt_disconnected')
        self.assertTrue(state.restore(event(1), now=loaded))
        second = state.snapshot(loaded)
        self.assertEqual(second['status'], 'offline')
        self.assertEqual(second['status_reason'], 'mqtt_disconnected')
        self.assertEqual(second['message_id'], event(1)['message_id'])
        self.assertEqual(second['history_samples'], 2)
        self.assertFalse(state.restore(event(1), now=loaded))
        self.assertEqual(state.snapshot(loaded), second)
        # A genuinely received current measurement can establish live display.
        self.assertTrue(state.ingest(event(2, loaded), now=loaded, monotonic=0))
        current = state.snapshot(loaded, 0)
        self.assertEqual(current['status'], 'live')
        self.assertTrue(current['fresh'])
        self.assertEqual((current['history_samples'], current['live_samples']), (2, 1))

    def test_history_cannot_replace_newer_live_data_or_change_its_status(self):
        state = AirState(CONFIG)
        later = NOW + timedelta(seconds=10)
        current = event(2)
        state.ingest(current, later, 10)
        before = state.snapshot(later, 10)
        for previous in (event(), event(1), current):
            self.assertFalse(state.restore(previous, now=later))
            self.assertEqual(state.snapshot(later, 10), before)
        future = event(3, later + timedelta(seconds=60))
        self.assertFalse(state.restore(future, now=later))
        after = state.snapshot(later, 10)
        self.assertTrue(after['fresh'])
        self.assertEqual(after['field'], before['field'])
        self.assertEqual(after['message_id'], current['message_id'])

    def test_conflicting_mqtt_payload_cannot_promote_a_restored_record(self):
        state = AirState(CONFIG)
        original = event()
        state.restore(original, now=NOW)
        changed = event(values=(26., 25., 24.))
        self.assertFalse(state.ingest(changed, NOW, 0))
        snapshot = state.snapshot(NOW, 0)
        self.assertEqual(snapshot['data_origin'], 'history')
        self.assertEqual(snapshot['accepted_samples'], 1)
        self.assertEqual(snapshot['live_samples'], 0)
        self.assertEqual(snapshot['sensors'][0]['value_c'], 23.2)

    def test_history_input_keeps_validation_and_gap_reset(self):
        state = AirState(CONFIG)
        loaded = NOW + timedelta(days=1)
        bad = event()
        bad['readings']['T1'] = dict(value=None, quality='invalid')
        self.assertFalse(state.restore(bad, now=loaded))
        self.assertIsNone(state.snapshot(loaded)['field'])
        self.assertTrue(state.restore(event(), now=loaded))
        later = event(1, NOW + timedelta(seconds=60), (24., 24., 24.))
        self.assertTrue(state.restore(later, now=loaded))
        snapshot = state.snapshot(loaded)
        self.assertEqual(snapshot['history_samples'], 2)
        self.assertEqual(snapshot['gap_resets'], 1)
        self.assertFalse(snapshot['fresh'])

    def test_invalid_envelopes_and_transport_errors_do_not_crash_or_become_fresh(self):
        state = AirState(CONFIG)
        for bad in (None, [], dict(event='payload_error'),
                    dict(event='telemetry', fresh_unique=False, validation_issues=None)):
            self.assertFalse(state.ingest(bad, NOW, 0))
        snap = state.snapshot(NOW, 0)
        self.assertFalse(snap['fresh'])
        self.assertIsNone(snap['field'])
        self.assertEqual(snap['rejected_samples'], 4)

    def test_source_and_receipt_clock_expire_independently(self):
        state = AirState(CONFIG)
        state.ingest(event(), NOW, 10)
        self.assertEqual(state.snapshot(NOW, 40)['status'], 'live')
        self.assertEqual(state.snapshot(NOW, 40.01)['status'], 'stale')
        self.assertEqual(state.snapshot(NOW + timedelta(seconds=30.01), 10)['status'], 'stale')
        self.assertEqual(state.snapshot(NOW - timedelta(seconds=5.01), 10)['status'], 'stale')
        self.assertEqual(state.snapshot(NOW, 10)['message_id'], event()['message_id'])

    def test_status_requires_new_temperature_to_resume(self):
        state = AirState(CONFIG)
        state.ingest(event(), NOW, 0)
        state.ingest(dict(event='status', retained=False, online=False), NOW, 1)
        self.assertEqual(state.snapshot(NOW + timedelta(seconds=60), 60)['status'], 'offline')
        state.ingest(dict(event='status', retained=False, online=True), NOW, 2)
        self.assertEqual(state.snapshot(NOW, 2)['status'], 'held')
        self.assertFalse(state.snapshot(NOW, 2)['fresh'])
        state.ingest(dict(event='status', retained=True, online=True), NOW, 3)
        self.assertEqual(state.snapshot(NOW, 3)['last_rejection'], 'retained_status_ignored')
        state.ingest(event(1), NOW + timedelta(seconds=5), 5)
        self.assertTrue(state.snapshot(NOW + timedelta(seconds=5), 5)['fresh'])
        state.ingest(dict(event='subscriber_process_exited'), NOW, 6)
        self.assertEqual(state.snapshot(NOW, 6)['status'], 'offline')

    def test_replay_uses_receipt_clock_and_is_explicitly_labelled(self):
        state = AirState(CONFIG, source_mode='replay')
        wall = NOW + timedelta(days=5)
        self.assertTrue(state.ingest(event(), wall, 100))
        snap = state.snapshot(wall, 100)
        self.assertEqual(snap['status'], 'replay')
        self.assertTrue(snap['fresh'])
        self.assertEqual(snap['source_age_seconds'], 5 * 86400)
        self.assertEqual(state.snapshot(wall, 131)['status'], 'stale')
        state.mark('replay_complete', 'csv_playback_finished_last_estimate_held')
        snap = state.snapshot(wall, 131)
        self.assertEqual(snap['status'], 'replay_complete')
        self.assertTrue(snap['held'])
        self.assertFalse(snap['fresh'])

    def test_freshness_options_reject_unbounded_or_nonnumeric_values(self):
        for name, values in (
            ('max_sample_age', (0, -1, True, float('nan'), float('inf'))),
            ('max_future_skew', (-1, True, float('nan'), float('inf'))),
        ):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    AirState(CONFIG, **{name: value})
        with self.assertRaises(ValueError):
            AirState(CONFIG, source_mode='unknown')

    def test_configured_gap_resets_model_and_extends_color_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = load_config(CONFIG)
            cfg['stale_after_s'] = 10
            path = Path(folder) / 'air.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            state = AirState(path)
            self.assertEqual(state.max_sample_age, 10)
            state.ingest(event(), NOW, 0)
            old_scale = state.snapshot(NOW, 0)['color_range_c']
            self.assertEqual(state.snapshot(NOW, 10.01)['status'], 'stale')
            later = NOW + timedelta(seconds=11)
            data = event(1, later, (30, 31, 32))
            self.assertTrue(state.ingest(data, later, 11))
            snap = state.snapshot(later, 11)
            self.assertEqual(snap['gap_resets'], 1)
            # A stale gap starts a new estimate from the arriving measurements;
            # it must not integrate the assumed flow over the missing interval.
            fresh = AirState(path)
            fresh.ingest(data, later, 11)
            self.assertEqual(snap['field'], fresh.snapshot(later, 11)['field'])
            self.assertLessEqual(snap['color_range_c'][0], old_scale[0])
            self.assertGreaterEqual(snap['color_range_c'][1], 32)


class AirModelTests(unittest.TestCase):
    def test_constant_field_stays_constant_and_time_must_increase(self):
        model = AirModel(load_config(CONFIG))
        values = dict(T1=25., T2=25., T3=25.)
        for seconds in (0, 5, 10):
            estimated, baseline = model.update(values, NOW + timedelta(seconds=seconds))
            np.testing.assert_allclose(estimated, 25., atol=1e-5, rtol=0)
            np.testing.assert_allclose(baseline, 25., atol=1e-5, rtol=0)
        with self.assertRaisesRegex(ValueError, 'strictly increase'):
            model.update(values, NOW)

    def test_config_rejects_unsupported_geometry_units_and_sensor_coordinates(self):
        config = load_config(CONFIG)
        replacements = [
            dict(dimensions_m=[.3, .2, .3]), dict(payload_temperature_unit='degF'),
            dict(stale_after_s=float('nan')), dict(stale_after_s=True),
            dict(temperature_limits_c=[60, -20]), dict(sensors=[]),
        ]
        cases = [dict(config, **replacement) for replacement in replacements]
        for xyz in ([.5, .1, .1], [.1, .1, float('inf')], [True, 0, 0],
                    config['sensors']['T2']['xyz_m']):
            cfg = copy.deepcopy(config)
            cfg['sensors']['T1']['xyz_m'] = xyz
            cases.append(cfg)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'air.json'
            for index, cfg in enumerate(cases):
                with self.subTest(case=index):
                    path.write_text(json.dumps(cfg), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        load_config(path)


class AirHTTPTests(unittest.TestCase):
    def test_registry_routes_each_cage_and_keeps_states_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            other_config = load_config(CONFIG)
            other_config['cage_id'] = 'CAGE-002'
            other_config['sensors']['T1']['label'] = 'Second cage ceiling'
            other_path = Path(folder) / 'second-air.json'
            other_path.write_text(json.dumps(other_config), encoding='utf-8')
            first, second = AirState(CONFIG), AirState(other_path)
            first.ingest(event(values=(21., 22., 23.)), NOW, 0)
            second.ingest(event(1, NOW, (27., 28., 29.)), NOW, 0)
            states = {'CAGE-001': first, 'CAGE-002': second}
            server = start_server(states, port=0)
            # Server captures its registered cages, independently of caller mutation.
            states.clear()
            base = 'http://127.0.0.1:' + str(server.server_address[1])
            try:
                with urlopen(base + '/api/cages', timeout=3) as response:
                    cages = json.load(response)
                self.assertEqual(cages, dict(cage_ids=['CAGE-001', 'CAGE-002'], default_cage_id='CAGE-001'))
                with urlopen(base + '/api/air', timeout=3) as response:
                    default = json.load(response)
                with urlopen(base + '/api/air?cage_id=CAGE-002', timeout=3) as response:
                    selected = json.load(response)
                self.assertEqual(default['cage_id'], 'CAGE-001')
                self.assertEqual(default['message_id'], event()['message_id'])
                self.assertEqual(selected['cage_id'], 'CAGE-002')
                self.assertEqual(selected['message_id'], event(1)['message_id'])
                self.assertEqual([s['value_c'] for s in selected['sensors']], [27., 28., 29.])
                self.assertEqual(selected['sensors'][0]['label'], 'Second cage ceiling')
                self.assertNotEqual(selected['field'], default['field'])
                second.mark('offline', 'test_transport_disconnected')
                self.assertEqual(first.snapshot(NOW, 0)['status'], 'live')
                self.assertEqual(first.cfg['sensors']['T1']['label'], load_config(CONFIG)['sensors']['T1']['label'])
                self.assertEqual(first.model.last_stamp, NOW)
                for query in ('cage_id=MISSING', 'cage_id=', 'cage_id=CAGE-001&cage_id=CAGE-002',
                              'cage_id=CAGE-001&cage_id=CAGE-001'):
                    with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                        urlopen(base + '/api/air?' + query, timeout=3)
                    self.assertEqual(error.exception.code, 404)
                self.assertEqual(first.snapshot(NOW, 0)['accepted_samples'], 1)
                self.assertEqual(second.snapshot(NOW, 0)['accepted_samples'], 1)
            finally:
                server.shutdown()
                server.server_close()

    def test_registry_rejects_empty_or_mismatched_state_before_binding(self):
        state = AirState(CONFIG)
        for registry in ({}, {'wrong-cage': state}, {'CAGE-001': object()}, {1: state}):
            with self.subTest(registry=list(registry)), self.assertRaisesRegex(ValueError, 'registry'):
                start_server(registry, port=0)

    def test_http_api_static_assets_and_read_only_boundary(self):
        state = AirState(CONFIG)
        server = start_server(state, port=0)
        base = 'http://127.0.0.1:' + str(server.server_address[1])
        try:
            with urlopen(base + '/api/air', timeout=3) as response:
                snap = json.load(response)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(snap['status'], 'waiting')
            self.assertIsNone(snap['field'])
            with urlopen(base + '/api/cages', timeout=3) as response:
                self.assertEqual(json.load(response), dict(cage_ids=['CAGE-001'], default_cage_id='CAGE-001'))
            # Zero monotonic receipt guarantees held/stale state independent of
            # the calendar date at which this test runs.
            state.ingest(event(), NOW, 0)
            with urlopen(base + '/api/air', timeout=3) as response:
                snap = json.load(response)
            self.assertEqual(snap['status'], 'stale')
            self.assertEqual(snap['message_id'], event()['message_id'])
            self.assertEqual(len(snap['field']['values_c']), 12000)
            with urlopen(base + '/', timeout=3) as response:
                html = response.read().decode()
            self.assertIn('20 × 20 × 30cm', html)
            self.assertIn('점은 센서 실측값', html)
            for element in ('source-mode', 'source-host', 'cage-picker', 'cage-select', 'source-age', 'receipt-age', 'baseline-option'):
                self.assertIn('id="' + element + '"', html)
            with urlopen(base + '/app.js', timeout=3) as response:
                self.assertIn(b'/api/air', response.read())
            for route in ('/%2e%2e/service.py', '/air-viewer.json', '/%00.html'):
                with self.subTest(route=route), self.assertRaises(HTTPError) as error:
                    urlopen(base + route, timeout=3)
                self.assertEqual(error.exception.code, 404)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + '/api/air', method='POST'), timeout=3)
            self.assertEqual(error.exception.code, 501)
        finally:
            server.shutdown()
            server.server_close()

    def test_http_static_symlink_cannot_escape_web_root(self):
        state = AirState(CONFIG)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            web = root / 'web'
            web.mkdir()
            outside = root / 'private.html'
            outside.write_text('outside web root', encoding='utf-8')
            (web / 'link.html').symlink_to(outside)
            server = start_server(state, port=0, web_root=web)
            try:
                base = 'http://127.0.0.1:' + str(server.server_address[1])
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/link.html', timeout=3)
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
