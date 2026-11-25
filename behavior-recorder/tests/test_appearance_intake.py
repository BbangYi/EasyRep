"""Reviewed diary bridge fixtures, never real animal observations."""
import copy
from io import BytesIO
import json
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from behavior_recorder import appearance_intake as intake
from behavior_recorder.appearance_journal import Journal
from behavior_recorder.appearance_series import build_series
from behavior_recorder.appearance_timeline import build_timeline
from behavior_recorder.core import RecorderError, digest, now, read_json


class AppearanceIntakeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='easyrep-reviewed-intake-test-'))
        self.journal = Journal(self.root / 'diary', dataset_kind='test')
        self.row = dict(record_id='a' * 32, animal_id='fixture-animal', enclosure_id=None,
            observer='fixture-owner', earliest_at='2026-11-01T01:00:00Z', latest_at='2026-11-01T02:00:00Z',
            assessment='started', note='synthetic explicit observation', identity_confirmed=True, photo_id=None)
        self.journal.record(self.row)
        self.plan_path = self.root / 'review.json'
        self.output = self.root / 'reviewed-v1'

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))
        return path

    def draft(self, ids=None):
        return intake.prepare_review(self.journal.storage, ids or [self.row['record_id']], self.plan_path)

    def reviewed(self, stage='started'):
        plan = self.draft()
        plan.update(reviewer='fixture-reviewer', reviewed_at=now(), identity_confirmed=True,
                    enclosure_id='fixture-enclosure')
        plan['entries'][0].update(event_stage=stage, hold_reason=None)
        self.save(self.plan_path, plan)
        return plan

    def run_intake(self):
        return intake.collect_review(self.plan_path, self.output, platform.node())

    def add_photo(self):
        pixels = Image.new('RGB', (16, 16), (120, 60, 30))
        blob = BytesIO(); pixels.save(blob, format='PNG')
        photo = self.journal.photo(blob.getvalue(), 'synthetic.png')
        row = {**self.row, 'record_id': 'b' * 32, 'photo_id': photo['id'], 'assessment': 'paler'}
        self.journal.record(row)
        mask = self.root / 'mask.png'; Image.new('L', (16, 16), 255).save(mask)
        return row, photo, mask

    def color_plan(self):
        row, photo, mask = self.add_photo()
        plan = self.draft([row['record_id']])
        plan.update(reviewer='fixture-reviewer', reviewed_at=now(), identity_confirmed=True,
                    enclosure_id='fixture-enclosure')
        color = dict(observed_at='2026-11-01T01:30:00Z', body_region='dorsal', mask='mask.png',
            mask_sha256=digest(mask), media_rights=dict(basis='own', evidence_reference='synthetic fixture pixels and mask'),
            capture=dict(camera_id='fixture', camera_revision='fixed-1', mode='visible_rgb', color_space='sRGB',
                illumination_revision='fixed-1', settings_revision='fixed-1', reference_revision='fixed-1',
                exposure_locked=True, white_balance_locked=True),
            review=dict(observer='fixture-reviewer', identity_confirmed=True, skin_only=True, dry=True, sharp=True))
        plan['entries'][0].update(color_review=color, hold_reason=None)
        self.save(self.plan_path, plan)
        return plan, photo

    def test_prepare_is_read_only_and_cannot_admit_unreviewed_draft(self):
        before = {str(p.relative_to(self.journal.storage)): digest(p) for p in self.journal.storage.rglob('*') if p.is_file()}
        plan = self.draft()
        self.assertFalse(plan['identity_confirmed'])
        self.assertIsNone(plan['entries'][0]['event_stage'])
        with self.assertRaises(RecorderError): self.run_intake()
        self.assertFalse(self.output.exists())
        after = {str(p.relative_to(self.journal.storage)): digest(p) for p in self.journal.storage.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_reader_never_creates_a_missing_journal_or_allows_writes(self):
        missing = self.root / 'missing'
        with self.assertRaises(RecorderError): Journal(missing, dataset_kind='test', read_only=True)
        self.assertFalse(missing.exists())
        reader = Journal(self.journal.storage, dataset_kind='test', read_only=True)
        self.assertEqual(len(reader.state()['records']), 1)
        with self.assertRaises(RecorderError): reader.record(self.row)
        with self.assertRaises(RecorderError): reader.photo(b'bad', 'x.png')

    def test_confirmed_event_preserves_interval_observer_source_and_review(self):
        self.reviewed()
        original = self.journal.storage / 'records' / (self.row['record_id'] + '.json')
        before = digest(original)
        report = self.run_intake()
        self.assertEqual(report['counts']['human_events'], 1)
        self.assertFalse(report['actual_training'])
        artifact = read_json(self.output / report['records'][0]['artifact'])
        self.assertEqual(artifact['metadata']['earliest_at'], self.row['earliest_at'])
        self.assertEqual(artifact['metadata']['latest_at'], self.row['latest_at'])
        self.assertEqual(artifact['metadata']['observer'], self.row['observer'])
        self.assertEqual(artifact['metadata']['enclosure_id'], 'fixture-enclosure')
        self.assertEqual(digest(original), before)
        self.assertFalse(read_json(original)['training_admitted'])
        self.assertEqual(build_series(self.output / 'series.json')['counts']['started'], 1)

    def test_uncertain_event_stays_uncertain_and_no_auto_start(self):
        row = {**self.row, 'record_id': 'b' * 32, 'assessment': 'uncertain'}
        self.journal.record(row)
        plan = self.draft([row['record_id']])
        plan.update(reviewer='fixture-reviewer', reviewed_at=now(), identity_confirmed=True, enclosure_id='fixture-enclosure')
        plan['entries'][0].update(event_stage='started', hold_reason=None)
        self.save(self.plan_path, plan)
        with self.assertRaisesRegex(RecorderError, 'event stage.*source'): self.run_intake()
        self.assertFalse(self.output.exists())
        plan['entries'][0]['event_stage'] = 'uncertain'; self.save(self.plan_path, plan)
        self.run_intake()
        self.assertEqual(build_series(self.output / 'series.json')['counts']['uncertain'], 1)

    def test_usual_or_paler_cannot_become_positive_or_negative_event(self):
        row = {**self.row, 'record_id': 'b' * 32, 'assessment': 'usual'}
        self.journal.record(row)
        plan = self.draft([row['record_id']])
        plan.update(reviewer='fixture-reviewer', reviewed_at=now(), identity_confirmed=True, enclosure_id='fixture-enclosure')
        plan['entries'][0].update(event_stage='completed', hold_reason=None)
        self.save(self.plan_path, plan)
        with self.assertRaisesRegex(RecorderError, 'event stage.*source'): self.run_intake()

    def test_held_record_can_remain_unbound_and_produces_no_training_series(self):
        plan = self.draft(); plan.update(reviewer='fixture-reviewer', reviewed_at=now())
        self.save(self.plan_path, plan)
        report = self.run_intake()
        self.assertEqual(report['counts']['held'], 1)
        self.assertIsNone(report['series_manifest'])
        self.assertFalse((self.output / 'series.json').exists())

    def test_enclosure_and_identity_must_be_explicit_before_collector(self):
        plan = self.reviewed(); plan['enclosure_id'] = None; self.save(self.plan_path, plan)
        with self.assertRaises(RecorderError): self.run_intake()
        self.assertFalse(self.output.exists())

    def test_changed_record_hash_or_review_clock_rejected(self):
        plan = self.reviewed(); original = copy.deepcopy(plan)
        for change in ('hash', 'clock'):
            plan = copy.deepcopy(original)
            if change == 'hash': plan['entries'][0]['record_sha256'] = 'f' * 64
            else: plan['reviewed_at'] = '2026-10-30T00:00:00Z'
            self.save(self.plan_path, plan)
            with self.subTest(change=change), self.assertRaises(RecorderError): self.run_intake()
        self.assertFalse(self.output.exists())

    def test_null_source_hash_cannot_bypass_frozen_record_binding(self):
        plan=self.reviewed();plan['entries'][0]['record_sha256']=None;self.save(self.plan_path,plan)
        with self.assertRaisesRegex(RecorderError,'source record SHA256'):self.run_intake()
        self.assertFalse(self.output.exists())

    def test_test_journal_cannot_be_relabelled_real(self):
        plan = self.reviewed(); plan['dataset_kind'] = 'real'; self.save(self.plan_path, plan)
        with self.assertRaisesRegex(RecorderError, 'dataset'): self.run_intake()

    def test_duplicate_entries_and_cross_animal_selection_rejected(self):
        plan = self.reviewed(); plan['entries'] *= 2; self.save(self.plan_path, plan)
        with self.assertRaisesRegex(RecorderError, 'duplicate'): self.run_intake()
        row = {**self.row, 'record_id': 'c' * 32, 'animal_id': 'another-animal'}; self.journal.record(row)
        with self.assertRaisesRegex(RecorderError, 'one animal'):
            intake.prepare_review(self.journal.storage, [self.row['record_id'], row['record_id']], self.root / 'other.json')

    def test_reviewed_photo_uses_original_bytes_and_existing_collector(self):
        plan, photo = self.color_plan()
        original = self.journal.storage / photo['path']; original_hash = digest(original)
        report = self.run_intake()
        artifact = read_json(self.output / report['records'][0]['artifact'])
        self.assertEqual(artifact['status'], 'measured')
        self.assertEqual(artifact['features']['rgb_median'], [120, 60, 30])
        self.assertEqual(artifact['files']['image']['sha256'], original_hash)
        self.assertEqual(digest(original), original_hash)
        self.assertEqual(report['counts']['human_events'], 0)
        self.assertEqual(build_series(self.output / 'series.json')['counts']['measured'], 1)

    def test_photo_needs_explicit_rights_mask_capture_time_and_reviewer(self):
        plan, _ = self.color_plan()
        changes = [('media_rights', None), ('mask_sha256', 'f' * 64), ('observed_at', '2026-11-02T00:00:00Z')]
        for key, value in changes:
            changed = copy.deepcopy(plan); changed['entries'][0]['color_review'][key] = value
            self.save(self.plan_path, changed)
            with self.subTest(key=key), self.assertRaises(RecorderError): self.run_intake()
        changed = copy.deepcopy(plan); changed['entries'][0]['color_review']['review']['observer'] = 'other-reviewer'
        self.save(self.plan_path, changed)
        with self.assertRaisesRegex(RecorderError, 'reviewer'): self.run_intake()
        self.assertFalse(self.output.exists())

    def test_ir_or_wet_review_remains_excluded(self):
        plan, _ = self.color_plan(); plan['entries'][0]['color_review']['review']['dry'] = False
        self.save(self.plan_path, plan)
        report = self.run_intake()
        artifact = read_json(self.output / report['records'][0]['artifact'])
        self.assertEqual(artifact['status'], 'excluded')
        self.assertIsNone(artifact['features'])
        self.assertEqual(report['counts']['excluded_color'], 1)

    def test_one_source_can_supply_separate_event_and_color_records_without_cycle_labels(self):
        plan, photo = self.color_plan()
        row = {**self.row, 'record_id': 'c' * 32, 'photo_id': photo['id']}
        self.journal.record(row)
        plan['reviewed_at'] = now()
        plan['entries'][0].update(record_id=row['record_id'], event_stage='started',
            record_sha256=digest(self.journal.storage / 'records' / (row['record_id'] + '.json')))
        self.save(self.plan_path, plan)
        report = self.run_intake()
        self.assertEqual(report['counts']['human_events'], 1)
        self.assertEqual(report['counts']['measured_color'], 1)
        self.assertEqual(len({r['artifact'] for r in report['records']}), 2)
        timeline_plan=self.save(self.output/'timeline-plan.json',dict(schema_version=1,
            kind='appearance_temporal_plan',series='series.json',max_gap_hours=24,cycles=[]))
        timeline=build_timeline(timeline_plan)
        self.assertEqual(len(timeline['rows']),1)
        self.assertIsNone(timeline['rows'][0]['target'])
        self.assertEqual(timeline['cycle_links'],[])

    def test_same_image_body_region_cannot_be_counted_twice_in_batch(self):
        plan, photo = self.color_plan()
        row = {**self.row, 'record_id': 'c'*32, 'photo_id':photo['id']}; self.journal.record(row)
        second=copy.deepcopy(plan['entries'][0]);second.update(record_id=row['record_id'],
            record_sha256=digest(self.journal.storage/'records'/(row['record_id']+'.json')))
        plan['entries'].append(second);plan['reviewed_at']=now();self.save(self.plan_path,plan)
        with self.assertRaisesRegex(RecorderError,'duplicate image/body region'):self.run_intake()
        self.assertFalse(self.output.exists())

    def test_media_budget_rejects_before_output_or_pixel_collection(self):
        self.color_plan()
        with patch.object(intake,'RAW_LIMIT',1),patch.object(intake,'collect',side_effect=AssertionError('no pixels')):
            with self.assertRaisesRegex(RecorderError,'payload exceeds'):self.run_intake()
        self.assertFalse(self.output.exists())

    def test_oversize_plan_is_rejected_without_unbounded_hash_read(self):
        self.reviewed()
        original=intake.digest
        def forbid_unbounded_plan(path):
            if Path(path)==self.plan_path: raise AssertionError('unbounded plan hash read')
            return original(path)
        with patch.object(intake,'PLAN_LIMIT',32),patch.object(intake,'digest',side_effect=forbid_unbounded_plan):
            with self.assertRaisesRegex(RecorderError,'byte limit'):self.run_intake()
        self.assertFalse(self.output.exists())

    def test_new_reader_constructor_keeps_default_writer_and_original_files(self):
        row={**self.row,'record_id':'c'*32,'enclosure_id':'fixture-enclosure'}
        self.journal.record(row)
        plan=self.draft([self.row['record_id'],row['record_id']])
        self.assertEqual(plan['enclosure_id'],'fixture-enclosure')
        self.assertFalse(plan['identity_confirmed'])
        self.assertEqual(len(Journal(self.journal.storage,dataset_kind='test').state()['records']),2)

    def test_resource_rejection_cannot_create_intake_output(self):
        self.reviewed()
        with patch.object(intake,'native_preflight',side_effect=RecorderError('no resource headroom')):
            with self.assertRaisesRegex(RecorderError,'resource headroom'):self.run_intake()
        self.assertFalse(self.output.exists())

    def test_source_change_during_copy_is_retained_as_failed_attempt(self):
        self.reviewed()
        original=intake.copy_verified
        def change_before_copy(source,target,expected,limit,guard):
            if target.name==self.row['record_id']+'.json':
                source.write_bytes(source.read_bytes()+b'\n')
            return original(source,target,expected,limit,guard)
        with patch.object(intake,'copy_verified',side_effect=change_before_copy):
            with self.assertRaisesRegex(RecorderError,'source changed during intake copy'):self.run_intake()
        self.assertTrue((self.output/'failure.json').exists())
        self.assertFalse((self.output/'intake-report.json').exists())

    def test_metadata_changed_between_validation_and_copy_is_rejected(self):
        _,photo=self.color_plan()
        original=intake.copy_verified
        def change_metadata(source,target,expected,limit,guard):
            if target.name==photo['id']+'.json':
                value=read_json(source);value['original_name']='changed.png';self.save(source,value)
                expected=digest(source)
            return original(source,target,expected,limit,guard)
        with patch.object(intake,'copy_verified',side_effect=change_metadata):
            with self.assertRaisesRegex(RecorderError,'photo metadata changed'):self.run_intake()
        self.assertTrue((self.output/'failure.json').exists())
        self.assertFalse((self.output/'series.json').exists())

    def test_collection_clock_cannot_backdate_reviewed_artifact(self):
        self.reviewed()
        original=intake.collect
        def older_result(source,output):
            result=original(source,output)
            result['created_at']='2026-10-01T00:00:00Z'
            return result
        with patch.object(intake,'collect',side_effect=older_result):
            with self.assertRaisesRegex(RecorderError,'collection clock precedes review'):self.run_intake()
        self.assertTrue((self.output/'failure.json').exists())
        self.assertFalse((self.output/'series.json').exists())

    def test_signature_only_attachment_fails_decode_and_preserves_partial_evidence(self):
        photo = self.journal.photo(b'\x89PNG\r\n\x1a\nnot an image', 'bad.png')
        plan, _ = self.color_plan()
        row = {**self.row, 'record_id': 'c' * 32, 'photo_id': photo['id']}; self.journal.record(row)
        plan['reviewed_at'] = now()
        plan['entries'][0].update(record_id=row['record_id'],
            record_sha256=digest(self.journal.storage / 'records' / (row['record_id'] + '.json')))
        self.save(self.plan_path, plan)
        with self.assertRaises((RecorderError, OSError)): self.run_intake()
        self.assertTrue((self.output / 'failure.json').exists())
        self.assertFalse((self.output / 'series.json').exists())
        with self.assertRaisesRegex(RecorderError, 'output already exists'): self.run_intake()

    def test_attachment_tampering_and_escaping_mask_rejected(self):
        plan, photo = self.color_plan()
        changed = copy.deepcopy(plan); changed['entries'][0]['color_review']['mask'] = '../mask.png'
        self.save(self.plan_path, changed)
        with self.assertRaises(RecorderError): self.run_intake()
        self.save(self.plan_path, plan)
        (self.journal.storage / photo['path']).write_bytes(b'tamper')
        with self.assertRaisesRegex(RecorderError, 'photo'): self.run_intake()

    def test_output_cannot_write_into_original_journal(self):
        self.reviewed()
        with self.assertRaisesRegex(RecorderError, 'original journal'):
            intake.collect_review(self.plan_path, self.journal.storage / 'derived', platform.node())
        self.assertFalse((self.journal.storage / 'derived').exists())

    def test_cli_prepare_collect_and_output_collision(self):
        self.assertEqual(intake.main(['prepare', '--journal', str(self.journal.storage), '--records', self.row['record_id'],
            '--output', str(self.plan_path)]), 0)
        plan=read_json(self.plan_path);plan.update(reviewer='fixture-reviewer',reviewed_at=now(),identity_confirmed=True,enclosure_id='fixture-enclosure')
        plan['entries'][0].update(event_stage='started',hold_reason=None);self.save(self.plan_path,plan)
        args=['collect','--plan',str(self.plan_path),'--output',str(self.output),'--execution-host',platform.node()]
        self.assertEqual(intake.main(args),0)
        self.assertEqual(intake.main(args),2)


if __name__ == '__main__':
    unittest.main()
