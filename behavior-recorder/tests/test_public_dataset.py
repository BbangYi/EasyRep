import copy
import unittest

from behavior_recorder.core import RecorderError
from scripts.import_bearded_research import asset_family, grouped_splits


class PublicDatasetTests(unittest.TestCase):
    def row(self, key, bits, **extra):
        return dict(family=key, pixel_sha256=key, dhash=bits, origin='zenodo', original_split='train', **extra)

    def test_export_suffixes_and_unknown_sequences_remain_grouped(self):
        self.assertEqual(asset_family('train/images/reptile-1-_jpg.rf.123.jpg'),
                         asset_family('test/images/reptile-1-_png.rf.456.jpg'))
        self.assertEqual(asset_family('IMG_2334_JPG.rf.x.jpg'), asset_family('videoframe_6428_png.rf.y.jpg'))
        self.assertEqual(asset_family('Screenshot-2025-02-22-185736_png.rf.x.jpg'),
                         asset_family('Screenshot-2025-02-22-192532_png.rf.y.jpg'))

    def test_transitive_near_duplicates_never_cross_splits(self):
        rows = [self.row('a', 0), self.row('b', 63), self.row('c', 4095)]
        result = grouped_splits(rows)
        self.assertEqual(len({r['group_id'] for r in result}), 1)
        self.assertEqual(len({r['split'] for r in result}), 1)

    def test_existing_splits_are_preserved_and_conflicts_stop_import(self):
        rows = [self.row('a', 0), self.row('b', 7)]
        rows[0].update(origin='commons', original_split='test')
        result = grouped_splits(copy.deepcopy(rows))
        self.assertEqual([r['split'] for r in result], ['test', 'test'])
        rows[1].update(origin='commons', original_split='train')
        with self.assertRaisesRegex(RecorderError, 'cross splits'):
            grouped_splits(rows)
