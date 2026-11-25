"""Public annotation conversion must not turn excluded animals into background."""
import unittest

from scripts import import_openimages_lizards as importer
from behavior_recorder.core import RecorderError


def box(image_id, **changes):
    return dict(ImageID=image_id, Source='xclick', LabelName='/m/04m9y', Confidence='1',
                XMin='0.1', XMax='0.5', YMin='0.2', YMax='0.8', IsGroupOf='0',
                IsDepiction='0', IsOccluded='0', IsTruncated='0', **changes)


class OpenImagesTest(unittest.TestCase):
    def test_excluded_group_or_depiction_excludes_entire_image(self):
        rows = [box('a'), {**box('a'), 'IsGroupOf': '1'}, box('b'),
                {**box('c'), 'IsDepiction': '1'}, {**box('d'), 'LabelName': '/m/06bt6'}]
        selected, rejected = importer.select_boxes(rows)
        self.assertEqual(set(selected), {'b'})
        self.assertEqual(set(rejected), {'a', 'c'})
        self.assertEqual(selected['b'][0]['yolo'], [0.3, 0.5, 0.4, 0.6])

    def test_invalid_coordinates_fail_instead_of_creating_training_labels(self):
        with self.assertRaises(RecorderError):
            importer.select_boxes([{**box('a'), 'XMax': 'nan'}])

    def test_same_flickr_author_uses_same_group_despite_display_name_change(self):
        first = {'Author': 'Alice', 'AuthorProfileURL': 'https://www.flickr.com/people/123@N01/'}
        second = {'Author': 'New name', 'AuthorProfileURL': 'http://www.flickr.com/people/123@N01'}
        self.assertEqual(importer.author_family(first, 'one'), importer.author_family(second, 'two'))
        self.assertNotEqual(importer.author_family(first, 'one'), importer.author_family({}, 'two'))

    def test_new_near_duplicate_inherits_existing_reserved_split(self):
        existing = {'id': 'old', 'group_id': 'old-camera', 'split': 'test', 'pixel_sha256': 'a', 'dhash': 0}
        new = {'id': 'new', 'family': 'new-author', 'pixel_sha256': 'b', 'dhash': 1}
        rows = importer.assign_groups([existing], [new])
        self.assertEqual([row['split'] for row in rows], ['test', 'test'])
        self.assertEqual(rows[0]['group_id'], rows[1]['group_id'])


if __name__ == '__main__':
    unittest.main()
