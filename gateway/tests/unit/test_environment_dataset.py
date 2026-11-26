"""Offline export regression checks. Every SQLite database here is fabricated."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from habitat.compute.environment_dataset import build_dataset, read_dataset, DatasetManifest


class DatasetTests(unittest.TestCase):
    def setUp(self):
        Path('var/tmp').mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(prefix='environment-dataset-', dir='var/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root/'gateway.sqlite3'
        self.manifest_path = self.root/'manifest.json'
        self.output = self.root/'windows.jsonl'
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.manifest = {
            'schema_version': 1, 'data_source': 'simulation', 'site_id': 'fixture',
            'gateway_id': 'fixture-pi', 'sensor_ids': ['T1', 'RH1', 'T2', 'T3'],
            'sessions': [{
                'session_id': 'test-1', 'episode_id': 'trial-1', 'database': self.db.name,
                'cage_id': 'cage-1', 'split': 'test', 'start': self.stamp(0), 'end': self.stamp(5400),
                'geometry_revision': 1, 'placement_revision': 1,
                'mist_history': 'declared_zero', 'declared_by': 'unit-test',
                'coverage_note': 'Synthetic fixture only; never actual hardware evidence.'}]}
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''
                CREATE TABLE cloud_identity(site_id TEXT,gateway_id TEXT);
                INSERT INTO cloud_identity VALUES ('fixture','fixture-pi');
                CREATE TABLE telemetry(cage_id TEXT,message_id TEXT,sampled_at TEXT,received_at TEXT,body TEXT);
                CREATE TABLE audit(occurred_at TEXT,kind TEXT,cage_id TEXT,body TEXT);
            ''')
            for minute in range(91):
                message_id = str(uuid4())
                stamp = self.stamp(minute*60)
                values = [20+minute*.01, 50+minute*.1, 25+minute*.01, 22+minute*.01]
                body = dict(schema_version=1, data_source='simulation', message_id=message_id,
                            sampled_at=stamp, geometry_revision=1, placement_revision=1,
                            readings={s: {'value': v, 'quality': 'valid'}
                                      for s, v in zip(self.manifest['sensor_ids'], values)}, actuators={})
                db.execute('INSERT INTO telemetry VALUES (?,?,?,?,?)',
                           ('cage-1', message_id, stamp, stamp, json.dumps(body)))

    def stamp(self, seconds):
        return (self.start+timedelta(seconds=seconds)).isoformat()

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding='utf-8')

    def build(self):
        self.write_manifest()
        return build_dataset(self.manifest_path, self.output)

    def modify_sample(self, minute, **changes):
        with closing(sqlite3.connect(self.db)) as db, db:
            body = json.loads(db.execute('SELECT body FROM telemetry WHERE sampled_at=?',
                                         (self.stamp(minute*60),)).fetchone()[0])
            body.update(changes)
            db.execute('UPDATE telemetry SET body=? WHERE sampled_at=?',
                       (json.dumps(body), self.stamp(minute*60)))

    def execution(self, start, end, recorded=None, **changes):
        body = dict(command_id=str(uuid4()), started_at=self.stamp(start), ended_at=self.stamp(end),
                    duration_s=end-start, data_source='simulation', volume_ml=None, reason='fixture')
        body.update(changes)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                       (self.stamp(end if recorded is None else recorded), 'mist_execution', 'cage-1', json.dumps(body)))

    def test_complete_window_and_read_only_source(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        summary = self.build()
        header, windows, footer = read_dataset(self.output)
        self.assertEqual(summary, footer)
        self.assertEqual(summary['windows_by_split'], {'test': 1})
        self.assertFalse(summary['field_validated'])
        self.assertFalse(summary['all_splits_present'])
        self.assertEqual(header['source']['data_source'], 'simulation')
        window = windows[0]
        self.assertEqual(window['history_times'][0], self.start.timestamp()+60)
        self.assertEqual(window['history'][-1][:4], [20.3, 53.0, 25.3, 22.3])
        self.assertEqual(window['targets'][4], [20.35, 53.5, 25.35, 22.35])
        self.assertEqual(window['targets'][-1], [20.9, 59.0, 25.9, 22.9])
        self.assertEqual(window['future_executed_seconds'], [0.0]*60)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['gateway.sqlite3', 'manifest.json', 'windows.jsonl'])

    def test_elapsed_execution_is_split_at_minute_boundary(self):
        self.manifest['sessions'][0]['mist_history'] = 'execution_log'
        self.execution(1796, 1800)
        self.execution(1858, 1862)
        self.build()
        _, windows, _ = read_dataset(self.output)
        self.assertEqual(windows[0]['history'][-1][4], 4)
        self.assertEqual(windows[0]['future_executed_seconds'][:3], [2, 2, 0])

    def test_past_execution_must_be_finished_and_available_at_origin(self):
        self.manifest['sessions'][0]['mist_history'] = 'execution_log'
        self.execution(1795, 1799, recorded=1801)
        with self.assertRaisesRegex(ValueError, 'no complete'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_late_telemetry_is_not_leaked_into_history(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE telemetry SET received_at=? WHERE sampled_at=?',
                       (self.stamp(1801), self.stamp(1800)))
        with self.assertRaisesRegex(ValueError, 'no complete'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_and_invalid_future_target_are_not_filled(self):
        self.modify_sample(35, readings={'RH1': {'value': None, 'quality': 'crc_error'}})
        with self.assertRaisesRegex(ValueError, 'no complete'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_mixed_sources_and_revisions_are_rejected(self):
        for change, error in [({'data_source': 'sensor'}, 'mixed'),
                              ({'data_source': 'simulation', 'placement_revision': 2}, 'revision')]:
            with self.subTest(change=change):
                self.modify_sample(15, **change)
                with self.assertRaisesRegex(ValueError, error):
                    self.build()
                self.assertFalse(self.output.exists())

    def test_declared_zero_is_not_inferred_from_absent_execution_events(self):
        self.modify_sample(20, actuators={'mist': True})
        with self.assertRaisesRegex(ValueError, 'active actuator'):
            self.build()
        self.modify_sample(20, actuators={})
        self.execution(1201, 1205)
        with self.assertRaisesRegex(ValueError, 'execution log'):
            self.build()

    def test_invalid_or_overlapping_execution_rejected(self):
        self.manifest['sessions'][0]['mist_history'] = 'execution_log'
        self.execution(1201, 1205)
        self.execution(1204, 1206)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            self.build()

    def test_cage_split_overlap_and_reversed_order_and_episode_leakage(self):
        first = self.manifest['sessions'][0]
        first['split'] = 'train'
        second = {**first, 'session_id': 'second', 'episode_id': 'other', 'split': 'test',
                  'database': 'copy.sqlite3'}
        self.manifest['sessions'].append(second)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            DatasetManifest.model_validate(self.manifest)
        second.update(start=self.stamp(5460), end=self.stamp(10860), episode_id='trial-1')
        with self.assertRaisesRegex(ValueError, 'episode'):
            DatasetManifest.model_validate(self.manifest)
        second.update(episode_id='other', split='train')
        first['split'] = 'test'
        with self.assertRaisesRegex(ValueError, 'time order'):
            DatasetManifest.model_validate(self.manifest)

    def test_wrong_database_identity_and_missing_source_rejected(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE cloud_identity SET gateway_id='another-pi'")
        with self.assertRaisesRegex(ValueError, 'site/gateway'):
            self.build()
        self.manifest['sessions'][0]['database'] = 'not-present.sqlite3'
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertFalse((self.root/'not-present.sqlite3').exists())
        self.assertFalse(self.output.exists())

    def test_no_overwrite_and_modified_or_truncated_export_rejected(self):
        self.build()
        original = self.output.read_text(encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_text(encoding='utf-8'), original)
        self.output.write_text('\n'.join(original.splitlines()[:-1])+'\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            read_dataset(self.output)
        self.output.write_text(original.replace('"targets":[[20.31', '"targets":[[99.31'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'modified'):
            read_dataset(self.output)

    def test_malformed_export_and_unfinished_execution_rejected(self):
        for invalid in ('', '[]\n', 'null\n', '{"kind":"manifest","schema_version":1}\n'):
            with self.subTest(invalid=invalid):
                self.output.write_text(invalid, encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_dataset(self.output)
        self.output.unlink()
        self.manifest['sessions'][0]['mist_history'] = 'execution_log'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                       (self.stamp(1200), 'mist_execution', 'cage-1', json.dumps({'started_at': self.stamp(1200)})))
        with self.assertRaisesRegex(ValueError, 'incomplete mist'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_cli_export_and_evaluation_roundtrip(self):
        self.write_manifest()
        command = [sys.executable, '-B', '-m', 'apps.worker.environment_dataset']
        built = subprocess.run(command+['build', '--manifest', str(self.manifest_path), '--output', str(self.output)],
                               capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        _, windows, _ = read_dataset(self.output)
        w = windows[0]
        prediction = {'window_id': w['window_id'], 'model_id': 'oracle-fixture-not-trained',
                      'origin_epoch': w['origin_epoch'], 'generated_at_epoch': w['origin_epoch']+7200,
                      'prediction_kind': 'retrospective_action_conditioned',
                      'planned_seconds': w['future_executed_seconds'],
                      'values': {str(h): w['targets'][h-1] for h in (5, 10, 30, 60)}}
        predictions = self.root/'predictions.jsonl'
        predictions.write_text(json.dumps(prediction)+'\n', encoding='utf-8')
        report_path = self.root/'report.json'
        evaluated = subprocess.run(command+['evaluate', '--dataset', str(self.output), '--predictions', str(predictions),
                                           '--output', str(report_path)], capture_output=True, text=True)
        self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'retrospective_only')
        self.assertFalse(report['field_validated'])
        metrics = report['modes']['retrospective_action_conditioned']['horizons']['5']['metrics']['humidity_pct']
        self.assertEqual(metrics['model']['mae'], 0)
        self.assertAlmostEqual(metrics['persistence']['mae'], .5)


if __name__ == '__main__':
    unittest.main()
