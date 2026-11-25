"""New cross-batch contracts; synthetic diary inputs, no animal measurements."""
import copy
from io import BytesIO
import json
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from PIL import Image

from behavior_recorder import appearance_intake as intake
from behavior_recorder.appearance_journal import Journal
from behavior_recorder.appearance_series import build_series
from behavior_recorder.appearance_timeline import build_timeline
from behavior_recorder.core import RecorderError, digest, now, read_json


class AppearanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='easyrep-history-test-'))
        self.plan_path = self.root / 'history-plan.json'
        self.output = self.root / 'history.json'
        self.counter = 0
        self.plan = dict(schema_version=1, kind='appearance_reviewed_history_plan', intakes=[])

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def batch(self, name, day=1, stage='started', animal='fixture-animal', kind='test', color=None, hold=False, wet=False):
        self.counter += 1
        base = self.root / name
        journal = Journal(base / 'diary', dataset_kind=kind)
        key = f'{self.counter:032x}'
        photo = None
        if color is not None:
            blob = BytesIO(); Image.new('RGB', (16, 16), (color, color, color)).save(blob, format='PNG')
            photo = journal.photo(blob.getvalue(), 'synthetic.png')
            Image.new('L', (16, 16), 255).save(base / 'mask.png')
        observed = f'2026-11-{day:02d}T01:00:00Z'
        journal.record(dict(record_id=key, animal_id=animal, enclosure_id=None, observer='fixture-owner',
            earliest_at=observed, latest_at=observed, assessment=stage if color is None else 'paler',
            identity_confirmed=True, note='synthetic history contract', photo_id=photo['id'] if photo else None))
        plan_path = base / 'review.json'
        plan = intake.prepare_review(journal.storage, [key], plan_path)
        plan.update(reviewer='fixture-reviewer', reviewed_at=now(), identity_confirmed=True, enclosure_id='fixture-enclosure')
        entry = plan['entries'][0]
        if not hold:
            entry['hold_reason'] = None
            if color is None:
                entry['event_stage'] = stage
            else:
                entry['color_review'] = dict(observed_at=observed, body_region='dorsal', mask='mask.png',
                    mask_sha256=digest(base / 'mask.png'), media_rights=dict(basis='own', evidence_reference='synthetic pixels'),
                    capture=dict(camera_id='fixture', camera_revision='1', mode='visible_rgb', color_space='sRGB',
                        illumination_revision='1', settings_revision='1', reference_revision='1',
                        exposure_locked=True, white_balance_locked=True),
                    review=dict(observer='fixture-reviewer', identity_confirmed=True, skin_only=True, dry=not wet, sharp=True))
        self.save(plan_path, plan)
        intake.collect_review(plan_path, base / 'reviewed', platform.node())
        path = base / 'reviewed/intake-report.json'
        self.plan['intakes'].append(dict(path=path.relative_to(self.root).as_posix(), sha256=digest(path)))
        return path

    def run_history(self, output=None):
        self.assertTrue(callable(getattr(intake, 'compose_history', None)), 'completed-batch provenance composition is missing')
        self.save(self.plan_path, self.plan)
        return intake.compose_history(self.plan_path, output or self.output, platform.node())

    def refresh_report(self, path, report):
        self.save(path, report)
        next(x for x in self.plan['intakes'] if x['path'] == path.relative_to(self.root).as_posix())['sha256'] = digest(path)

    def test_two_batches_preserve_originals_and_chronology_without_cycle_labels(self):
        self.batch('later', day=3, stage='completed'); self.batch('earlier', day=1)
        before = {str(p.relative_to(self.root)): digest(p) for p in self.root.rglob('*') if p.is_file()}
        receipt = self.run_history()
        series = build_series(self.output)
        self.assertEqual([r['stage'] for r in series['records']], ['started', 'completed'])
        self.assertEqual(series['counts']['records'], 2)
        self.assertEqual(series['cycle_pairing'], 'not_performed')
        self.assertFalse(receipt['actual_training']); self.assertIsNone(receipt['prediction'])
        self.assertFalse(receipt['actuation_allowed'])
        for p, value in before.items(): self.assertEqual(digest(self.root / p), value)
        self.assertEqual(receipt['manifest_sha256'], digest(self.output))

    def test_colour_history_connects_existing_timeline_without_reextracting_pixels(self):
        a = self.batch('first', day=1, color=80); b = self.batch('second', day=2, color=100)
        stamps = [read_json(p.parent / read_json(p)['records'][0]['artifact'])['created_at'] for p in (a,b)]
        self.run_history()
        plan = dict(schema_version=1, kind='appearance_temporal_plan', series='history.json', max_gap_hours=48, cycles=[])
        timeline = build_timeline(self.save(self.root / 'temporal.json', plan))
        self.assertEqual(timeline['rows'][1]['features']['rgb_delta'], [20,20,20])
        self.assertIsNone(timeline['rows'][1]['target'])
        self.assertEqual([read_json(p.parent / read_json(p)['records'][0]['artifact'])['created_at'] for p in (a,b)], stamps)

    def test_held_only_batch_is_preserved_without_promoting_it_to_event(self):
        self.batch('start'); self.batch('hold', day=2, hold=True)
        receipt = self.run_history()
        self.assertEqual(len(receipt['held']), 1)
        self.assertEqual(build_series(self.output)['counts']['records'], 1)

    def test_changed_report_or_artifact_rejected_before_final_manifest(self):
        p = self.batch('first'); self.batch('second', day=2)
        original = p.read_bytes(); p.write_bytes(original + b' ')
        with self.assertRaisesRegex(RecorderError, 'hash'): self.run_history()
        p.write_bytes(original)
        artifact = p.parent / read_json(p)['records'][0]['artifact']; artifact.write_bytes(artifact.read_bytes()+b' ')
        with self.assertRaisesRegex(RecorderError, 'hash'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_partial_or_failed_intake_rejected(self):
        p = self.batch('first'); self.save(p.parent / 'failure.json', dict(error='synthetic interruption'))
        with self.assertRaisesRegex(RecorderError, 'failed|partial'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_missing_completion_report_rejected(self):
        self.plan['intakes'] = [dict(path='uncompleted/intake-report.json', sha256='a'*64)]
        with self.assertRaises((OSError, RecorderError)): self.run_history()
        self.assertFalse(self.output.exists())

    def test_duplicate_intake_and_cross_animal_are_rejected(self):
        self.batch('first'); self.plan['intakes'] *= 2
        with self.assertRaisesRegex(RecorderError, 'duplicate'): self.run_history()
        self.plan['intakes'] = self.plan['intakes'][:1]; self.batch('other', animal='other-animal')
        with self.assertRaisesRegex(RecorderError, 'identity|animal'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_synthetic_and_real_batches_cannot_be_pooled(self):
        self.batch('test'); self.batch('real', kind='real')
        with self.assertRaisesRegex(RecorderError, 'identity|dataset'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_source_series_record_list_cannot_disagree_with_completion(self):
        p = self.batch('first'); report = read_json(p); report['records'] = []
        self.refresh_report(p, report)
        with self.assertRaisesRegex(RecorderError, 'record|series'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_same_image_body_region_across_batches_is_rejected(self):
        self.batch('first', color=80); self.batch('second', day=2, color=80)
        with self.assertRaisesRegex(RecorderError, 'same image'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_repeated_output_cannot_overwrite(self):
        self.batch('first'); self.run_history(); value = digest(self.output)
        with self.assertRaises(RecorderError): self.run_history()
        self.assertEqual(digest(self.output), value)

    def test_wrong_source_series_schema_rejected_even_when_hashes_match(self):
        p = self.batch('first'); report = read_json(p)
        source = p.parent / report['series_manifest']; series = read_json(source)
        series['kind'] = 'unreviewed_series'; self.save(source, series)
        report['files'][report['series_manifest']] = digest(source); self.refresh_report(p, report)
        with self.assertRaisesRegex(RecorderError, 'series'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_null_hashes_cannot_bypass_source_bindings(self):
        p = self.batch('first'); original = read_json(p)
        for target in ('artifact', 'review', 'series'):
            report = copy.deepcopy(original)
            if target == 'artifact':
                row = report['records'][0]; row['artifact_sha256'] = None
                report['files'][row['artifact']] = None
            elif target == 'review':
                report['plan_sha256'] = None; report['files']['review-plan.source.json'] = None
            else:
                report['files'][report['series_manifest']] = None
            self.refresh_report(p, report)
            with self.subTest(target=target), self.assertRaisesRegex(RecorderError, 'hash|SHA256'):
                self.run_history()
            self.assertFalse(self.output.exists())

    def test_failed_publication_leaves_evidence_without_completed_manifest(self):
        self.batch('first'); original = intake.save_artifact
        def fail_final(path, value):
            if Path(path) == self.output: raise OSError('synthetic disk publication failure')
            return original(path, value)
        with patch.object(intake, 'save_artifact', fail_final), self.assertRaises(OSError): self.run_history()
        self.assertFalse(self.output.exists())
        failure = read_json(self.output.with_name('history.json.failure.json'))
        self.assertTrue(failure['partial_outputs_retained'])
        with self.assertRaisesRegex(RecorderError, 'partial'): self.run_history()

    def test_uncertain_and_excluded_records_keep_their_status(self):
        self.batch('uncertain', stage='uncertain'); self.batch('wet', day=2, color=80, wet=True)
        self.run_history(); series = build_series(self.output)
        self.assertEqual(series['counts']['uncertain'], 1)
        self.assertEqual(series['counts']['excluded'], 1)
        self.assertEqual(series['counts']['started'], 0)
        plan = dict(schema_version=1, kind='appearance_temporal_plan', series='history.json', max_gap_hours=48, cycles=[])
        timeline = build_timeline(self.save(self.root / 'temporal.json', plan))
        self.assertIsNone(timeline['rows'][0]['features'])

    def test_cli_publishes_existing_series_format(self):
        self.batch('first'); self.save(self.plan_path, self.plan)
        with redirect_stdout(StringIO()):
            result = intake.main(['history', '--plan', str(self.plan_path), '--output', str(self.output),
                                  '--execution-host', platform.node()])
        self.assertEqual(result, 0)
        self.assertEqual(build_series(self.output)['counts']['records'], 1)

    def test_oversized_or_empty_plan_rejected_without_publication(self):
        with self.assertRaises(RecorderError): self.run_history()
        self.batch('first'); self.plan['padding'] = 'x' * (1024**2)
        with self.assertRaisesRegex(RecorderError, 'byte limit'): self.run_history()
        self.assertFalse(self.output.exists())

    def test_plan_hash_path_and_output_boundary_enforced(self):
        p = self.batch('first'); original = copy.deepcopy(self.plan)
        self.plan['intakes'][0]['sha256'] = None
        with self.assertRaises(RecorderError): self.run_history()
        self.plan = copy.deepcopy(original); self.plan['intakes'][0]['path'] = '../outside.json'
        with self.assertRaises(RecorderError): self.run_history()
        self.plan = original
        with self.assertRaisesRegex(RecorderError, 'ancestor|source'): self.run_history(p.parent / 'history.json')


if __name__ == '__main__':
    unittest.main()
