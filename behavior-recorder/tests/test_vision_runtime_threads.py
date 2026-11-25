import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('ultralytics'), 'requires the vision runtime')
class VisionRuntimeThreadsTests(unittest.TestCase):
    def test_cpu_device_selection_preserves_requested_parallelism(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''
import json,sys
from pathlib import Path
from behavior_recorder.vision_model import runtime
runtime(Path(sys.argv[1]), 1)
import torch
from ultralytics.utils import torch_utils
counts = []
for threads in (1, 2):
    runtime(Path(sys.argv[1]), threads)
    # Trainer and validator select a device after runtime setup.
    torch.set_num_threads(4)
    torch_utils.select_device('cpu', verbose=False)
    counts.append(torch.get_num_threads())
print(json.dumps(counts))
'''
            result = subprocess.run([sys.executable, '-c', code, directory],
                                    cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1]), [1, 2])


if __name__ == '__main__':
    unittest.main()
