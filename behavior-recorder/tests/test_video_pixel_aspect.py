import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from behavior_recorder.core import RecorderError
from behavior_recorder.vision_video import sampled_frames, source_video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg required')
class VideoPixelAspectTests(unittest.TestCase):
    def test_anamorphic_video_must_be_normalized_before_vision(self):
        with tempfile.TemporaryDirectory() as folder:
            for ratio, accepted in [('1/1', True), ('2/1', False)]:
                with self.subTest(ratio=ratio):
                    video = Path(folder) / ('square.mkv' if accepted else 'anamorphic.mkv')
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
                        '-f', 'lavfi', '-i', 'color=c=gray:s=32x24:r=25:d=0.12',
                        '-vf', f'setsar={ratio}', '-filter_threads', '1',
                        '-c:v', 'ffv1', '-threads', '1', str(video)],
                        check=True, capture_output=True, timeout=20)
                    if accepted:
                        path, metadata, timeline = source_video(video=video, provenance='synthetic_test')
                        frames = list(sampled_frames(path, metadata, timeline, 25))
                        self.assertEqual(len(frames), 3)
                        self.assertEqual(frames[0][0].shape[:2], (24, 32))
                    else:
                        with self.assertRaisesRegex(RecorderError, 'non-square video pixels'):
                            source_video(video=video, provenance='synthetic_test')


if __name__ == '__main__':
    unittest.main()
