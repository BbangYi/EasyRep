import unittest
from behavior_recorder.core import RecorderError
from scripts.import_sawit_camera import convert_labels, select_frames


class SawitImportTests(unittest.TestCase):
    def test_selection_excludes_entire_evaluation_camera_and_spaces_frames(self):
        videos = [{"video": "TE1-015--2021-03-10--11-01-19.avi"},
                  {"video": "TE1-002--2021-03-10--11-01-19.avi"}]
        labels = [{"path": v['video'] + f"_{n}.txt"} for v in videos for n in range(100)]
        selected = select_frames(labels, videos, {"TE1-002"}, max_per_video=8, frame_gap=12)
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(r['camera'] == 'TE1-015' for r in selected))
        self.assertTrue(all(b['frame'] - a['frame'] >= 12 for a, b in zip(selected, selected[1:])))

    def test_mapping_checks_names_coordinates_and_rejects_partial_annotations(self):
        line = "1 0.5 0.5 0.2 0.4\n"
        self.assertEqual(convert_labels(line, "Lizard 40 30 60 70\n", 100, 100),
                         "0 0.5 0.5 0.2 0.4\n")
        for voc in ("Bird 40 30 60 70", "Lizard 10 10 20 20", "", "Lizard 40 30 60 70\nLizard 1 1 2 2"):
            with self.assertRaises(RecorderError):
                convert_labels(line, voc, 100, 100)
        with self.assertRaises(RecorderError):
            convert_labels("0 0.5 0.5 0.2 0.4", "Lizard 40 30 60 70", 100, 100)
