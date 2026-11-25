"""Mask imports must preserve complete instances and bounded byte ranges."""
import io
import unittest
import zipfile

from behavior_recorder.core import RecorderError
from scripts.import_openimages_masks import RangeReader, parse_masks, select_complete_masks, validate_range


def annotation(box_id='12345678', **changes):
    image_id='0123456789abcdef'
    return dict(MaskPath=f'{image_id}_m04m9y_{box_id}.png', ImageID=image_id, LabelName='/m/04m9y',
                BoxID=box_id, BoxXMin='.1', BoxXMax='.5', BoxYMin='.2', BoxYMax='.8',
                PredictedIoU='.9', Clicks='.2 .3 1;.8 .9 0', **changes)


def box(xmin='.1', xmax='.5'):
    return dict(publisher_annotation=dict(XMin=xmin, XMax=xmax, YMin='.2', YMax='.8'))


class MaskImportTests(unittest.TestCase):
    def test_only_complete_unambiguous_instance_coverage_is_eligible(self):
        records=parse_masks([annotation()])
        image_id=records[0]['image_id']
        selected, rejected=select_complete_masks(records, {image_id:[box()]})
        self.assertEqual(len(selected[image_id]),1)
        selected, rejected=select_complete_masks(records,{image_id:[box(),box('.6','.9')]})
        self.assertEqual(selected,{})
        self.assertIn('incomplete',rejected[image_id])
        duplicate=parse_masks([annotation(),annotation('87654321')])
        selected,rejected=select_complete_masks(duplicate,{image_id:[box(),box()]})
        self.assertEqual(selected,{})
        self.assertIn('ambiguous',rejected[image_id])

    def test_untrusted_mask_paths_coordinates_and_clicks_are_rejected(self):
        for replacement in [dict(MaskPath='../escape.png'),dict(BoxXMin='nan'),dict(BoxXMax='.01'),
                            dict(Clicks='.2 .3 2'),dict(Clicks='1.1 .3 1'),dict(PredictedIoU='1.2')]:
            row=annotation();row.update(replacement)
            with self.subTest(replacement=replacement),self.assertRaises(RecorderError):
                parse_masks([row])
        with self.assertRaises(RecorderError):
            parse_masks([annotation(),annotation()])

    def test_range_rejects_full_download_stale_version_and_truncation(self):
        headers={'Content-Range':'bytes 2-4/10','ETag':'"fixed"'}
        self.assertEqual(validate_range(206,headers,b'abc',2,4,10,'"fixed"'),b'abc')
        for status,changed,payload in [(200,headers,b'abc'),(206,{**headers,'ETag':'"new"'},b'abc'),
                                       (206,{**headers,'Content-Range':'bytes 3-5/10'},b'abc'),(206,headers,b'ab')]:
            with self.subTest(status=status,changed=changed),self.assertRaises(RecorderError):
                validate_range(status,changed,payload,2,4,10,'"fixed"')

    def test_zip_roundtrip_and_cached_reads_use_only_requested_bytes(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('one.png',b'first mask')
            archive.writestr('two.png',b'second mask')
        payload=buffer.getvalue();calls=[]
        def fetch(start,end):
            calls.append((start,end));return payload[start:end+1]
        reader=RangeReader(len(payload),fetch)
        with zipfile.ZipFile(reader) as archive:
            self.assertEqual(archive.read('two.png'),b'second mask')
        reader.seek(0);reader.read(2);before=len(calls);reader.seek(1);reader.read(1)
        self.assertEqual(len(calls),before)
        self.assertTrue(all(0<=a<=b<len(payload) for a,b in calls))
        self.assertEqual(reader.bytes_downloaded,sum(b-a+1 for a,b in calls))

    def test_request_and_transfer_caps_stop_large_or_short_reads(self):
        reader=RangeReader(1024,lambda a,b:b'x'*(b-a+1),max_request=64,max_total=100)
        with self.assertRaises(RecorderError):reader.read(65)
        self.assertEqual(len(reader.read(64)),64)
        reader.seek(128)
        with self.assertRaises(RecorderError):reader.read(64)
        with self.assertRaises(ValueError):reader.seek(-1)
        short=RangeReader(10,lambda a,b:b'x')
        with self.assertRaises(RecorderError):short.read(5)


if __name__=='__main__':
    unittest.main()
