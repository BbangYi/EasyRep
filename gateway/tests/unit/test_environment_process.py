"""Real pipe/process checks without CUDA; model accuracy is tested separately."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

from habitat.gpu.backend import Backend
from habitat.gpu.environment_api import ResidentPredictor


@unittest.skipUnless(os.name == 'posix', 'GPU service uses Linux/WSL pipes')
class EnvironmentProcessTests(unittest.TestCase):
    def test_reuse_invalid_input_timeout_crash_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / 'fake_predict.py'
            worker.write_text('''import json, os, sys, time
for raw in sys.stdin:
    p = json.loads(raw)
    action = p.get('action')
    if action == 'timeout': time.sleep(30)
    if action == 'crash': os._exit(3)
    if action == 'oversize':
        print('x' * 65537, flush=True)
        continue
    if action == 'invalid':
        print(json.dumps({'error':'invalid_prediction_input'}), flush=True)
        continue
    result = {'request_id':p['request_id'], 'hardware_execution_allowed':False,
              'worker_pid':os.getpid()}
    if action == 'wrong_id': result['request_id'] = 'wrong'
    print(json.dumps(result), flush=True)
''')
            predictor = ResidentPredictor(Backend({'python':sys.executable}), worker)
            self.addCleanup(predictor.close)
            first = predictor.request({'request_id':'first'})
            second = predictor.request({'request_id':'second'})
            self.assertEqual(first['worker_pid'], second['worker_pid'])
            self.assertEqual(second['request_id'], 'second')
            self.assertEqual(predictor.request({'request_id':'bad','action':'invalid'}),
                             {'error':'invalid_prediction_input'})
            self.assertEqual(first['worker_pid'], predictor.request({'request_id':'third'})['worker_pid'])
            for action in ('wrong_id', 'oversize', 'crash', 'timeout'):
                previous = predictor.process
                predictor.timeout_seconds = .2 if action == 'timeout' else 5
                with self.assertRaises((ValueError, OSError)):
                    predictor.request({'request_id':action, 'action':action})
                self.assertIsNone(predictor.process)
                self.assertIsNotNone(previous.poll())
                predictor.timeout_seconds = 5
                self.assertEqual(predictor.request({'request_id':'recovered'})['request_id'], 'recovered')
            previous = predictor.process
            predictor.close()
            self.assertIsNotNone(previous.poll())
            self.assertTrue(previous.stdin.closed)
            self.assertTrue(previous.stdout.closed)
            predictor.close()


if __name__ == '__main__':
    unittest.main()
