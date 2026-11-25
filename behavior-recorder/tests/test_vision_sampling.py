import collections
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import yaml

from behavior_recorder import vision_model
from behavior_recorder.core import RecorderError, digest, read_json


class TrainingSamplingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.records = []
        for index in range(13):
            split = 'val' if index == 11 else 'test' if index == 12 else 'train'
            image = f'images/{split}/{index:02d}.jpg'
            label = f'labels/{split}/{index:02d}.txt'
            path = self.run / 'learner-data' / label
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('0 .5 .5 .1 .2\n' if index != 9 else '0 .5 .5 .5 .5\n')
            if index == 10:
                path.write_text('')
            self.records.append(dict(id=f'image-{index:02d}', image=image, label=label,
                image_sha256=f'{index:064x}', group_id='one-camera' if index<9 else f'group-{index}',
                split=split, box_count=0 if index==10 else 1))
        self.manifest = dict(dataset_id='fixture', records=self.records)
        self.configuration = self.run / 'data.yaml'
        self.configuration.write_text(yaml.safe_dump(dict(path=str(self.run/'learner-data'),
            train='images/train', val='images/val', test='images/test', names=['lizard'])))

    def sample(self):
        function = getattr(vision_model, 'write_training_sampling', None)
        self.assertTrue(callable(function), 'explicit source-group-capped training sampling is missing')
        return function(self.manifest, self.run, 'small-body-v1')

    def test_small_training_images_repeat_but_source_group_and_evaluation_do_not(self):
        before = copy.deepcopy(self.manifest)
        audit = self.sample()
        configuration = yaml.safe_load(self.configuration.read_text())
        paths = (self.run/'train-samples.txt').read_text().splitlines()
        counts = collections.Counter(paths)
        self.assertEqual(len(paths), 27)  # 11 originals + 8 selected images twice more.
        self.assertEqual(len(counts), 11)
        self.assertEqual(sorted(counts.values()), [1,1,1,3,3,3,3,3,3,3,3])
        self.assertEqual(counts['./learner-data/images/train/00.jpg'], 3)
        self.assertEqual(counts['./learner-data/images/train/08.jpg'], 1)
        self.assertEqual(counts['./learner-data/images/train/09.jpg'], 1)
        self.assertEqual(counts['./learner-data/images/train/10.jpg'], 1)
        self.assertFalse(any('/val/' in p or '/test/' in p for p in paths))
        self.assertEqual(Path(configuration['train']).resolve(), (self.run/'train-samples.txt').resolve())
        self.assertEqual(configuration['val'], 'images/val')
        self.assertEqual(configuration['test'], 'images/test')
        self.assertEqual(audit['unique_training_images'], 11)
        self.assertEqual(audit['training_entries'], 27)
        self.assertEqual(self.manifest, before)

    def test_sampling_is_order_independent_and_unknown_preset_is_rejected(self):
        first = self.sample()
        content = (self.run/'train-samples.txt').read_bytes()
        self.manifest['records'].reverse()
        second = self.sample()
        self.assertEqual(first, second)
        self.assertEqual(content, (self.run/'train-samples.txt').read_bytes())
        with self.assertRaises(RecorderError):
            vision_model.write_training_sampling(self.manifest, self.run, 'guess')

    def test_runtime_rejects_deduplication_or_validation_leakage(self):
        self.sample()
        paths = [str(self.run/p.removeprefix('./')) for p in (self.run/'train-samples.txt').read_text().splitlines()]
        trainer = SimpleNamespace(train_loader=SimpleNamespace(dataset=SimpleNamespace(im_files=paths)))
        function = getattr(vision_model, 'verify_training_sampling', None)
        self.assertTrue(callable(function), 'runtime sampling verification is missing')
        function(trainer, self.run)
        self.assertTrue(read_json(self.run/'sampling-runtime.json')['verified'])
        for invalid in (sorted(set(paths)), paths[:-1]+[str(self.run/'learner-data/images/val/11.jpg')]):
            trainer.train_loader.dataset.im_files = invalid
            with self.assertRaisesRegex(RecorderError, 'sampling'):
                function(trainer, self.run)


class TargetReplayTests(TrainingSamplingTests):
    def review(self, index, reasons):
        row = self.records[index]
        row['species_confirmed'] = True
        row['original_taxon'] = 'Correlophus ciliatus' if 'crested' in reasons else 'Eublepharis macularius'
        row['label_sha256'] = digest(self.run / 'learner-data' / row['label'])
        row['training_focus_review'] = dict(image_sha256=row['image_sha256'],
            label_sha256=row['label_sha256'], reasons=reasons, review_method='assistant')

    def target_sample(self):
        try:
            vision_model.validate_training_options({'training_sampling': 'target-replay-v1'})
            return vision_model.write_training_sampling(self.manifest, self.run, 'target-replay-v1')
        except RecorderError as exc:
            self.fail(f'reviewed target replay is not supported: {exc}')

    def test_replay_needs_bound_review_does_not_multiply_overlapping_reasons_or_include_evaluation(self):
        self.review(0, ['crested', 'night'])
        self.review(1, ['night'])
        self.review(9, ['crested'])
        self.review(10, ['negative'])
        self.review(11, ['crested', 'night'])
        self.review(12, ['crested', 'night'])
        self.records[2]['original_taxon'] = 'Correlophus ciliatus'
        before = copy.deepcopy(self.manifest)
        audit = self.target_sample()
        paths = (self.run / 'train-samples.txt').read_text().splitlines()
        counts = collections.Counter(paths)
        self.assertEqual(len(counts), 11)
        self.assertEqual(len(paths), 23)
        for index in (0,1,9,10):
            self.assertEqual(counts[f'./learner-data/images/train/{index:02d}.jpg'],4)
        self.assertEqual(counts['./learner-data/images/train/02.jpg'],1)
        self.assertFalse(any('/val/' in p or '/test/' in p for p in paths))
        self.assertEqual(audit['unique_training_images'],11)
        self.assertFalse(audit['extra_exposures_are_new_images'])
        self.assertEqual(self.manifest,before)
        configuration=yaml.safe_load(self.configuration.read_text())
        self.assertEqual((configuration['val'],configuration['test']),('images/val','images/test'))

    def test_one_source_cannot_dominate_replay_and_selection_is_order_independent(self):
        for index in range(9):
            self.review(index,['night'])
        for index in range(13,34):
            row = dict(self.records[0],id=f'image-{index:02d}',image=f'images/train/{index:02d}.jpg',
                label=f'labels/train/{index:02d}.txt',image_sha256=f'{index:064x}')
            (self.run/'learner-data'/row['label']).write_text('0 .5 .5 .1 .2\n')
            row['training_focus_review']=dict(row['training_focus_review'],image_sha256=row['image_sha256'])
            self.records.append(row)
        first=self.target_sample(); content=(self.run/'train-samples.txt').read_bytes()
        group=[r for r in first['records'] if r['group_id']=='one-camera']
        self.assertEqual(len(group),30)
        self.assertEqual(sum(r['repeat']-1 for r in group),48)
        self.assertTrue(all(2<=r['repeat']<=4 for r in group))
        self.manifest['records'].reverse()
        self.assertEqual(first,self.target_sample())
        self.assertEqual(content,(self.run/'train-samples.txt').read_bytes())

    def test_changed_labels_unbound_reviews_and_contradictory_focus_are_rejected(self):
        self.review(0,['crested'])
        self.target_sample()
        good=copy.deepcopy(self.records[0])
        mutations=[{'image_sha256':'f'*64},{'label_sha256':'e'*64},{'reasons':['negative']},
                   {'reasons':['crested','unknown']},{'review_method':'unreviewed'},
                   {'reasons':[]},{'reasons':['crested','crested']},{'review_method':[]}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.records[0]=copy.deepcopy(good)
                self.records[0]['training_focus_review'].update(mutation)
                with self.assertRaises(RecorderError):
                    vision_model.write_training_sampling(self.manifest,self.run,'target-replay-v1')
        self.records[0]=copy.deepcopy(good)
        (self.run/'learner-data'/good['label']).write_text('')
        with self.assertRaises(RecorderError):
            vision_model.write_training_sampling(self.manifest,self.run,'target-replay-v1')

    def test_non_string_sampling_options_report_validation_errors(self):
        for invalid in (None, [], {}, 3):
            with self.subTest(preset=invalid), self.assertRaises(RecorderError):
                vision_model.validate_training_options({'training_sampling':invalid})
            with self.subTest(direct_preset=invalid), self.assertRaises(RecorderError):
                vision_model.write_training_sampling(self.manifest,self.run,invalid)

    def test_runtime_must_observe_replayed_training_entries(self):
        self.review(0,['night']);self.review(10,['negative']);self.target_sample()
        paths=[str(self.run/p.removeprefix('./')) for p in (self.run/'train-samples.txt').read_text().splitlines()]
        trainer=SimpleNamespace(train_loader=SimpleNamespace(dataset=SimpleNamespace(im_files=paths)))
        vision_model.verify_training_sampling(trainer,self.run)
        trainer.train_loader.dataset.im_files=sorted(set(paths))
        with self.assertRaises(RecorderError):
            vision_model.verify_training_sampling(trainer,self.run)


if __name__ == '__main__':
    unittest.main()
