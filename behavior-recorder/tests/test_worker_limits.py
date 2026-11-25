import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from behavior_recorder.core import RecorderError
from behavior_recorder.worker_limits import parse_gpu_sample, validate_limits, worker_limits


class WorkerLimitsTests(unittest.TestCase):
    def test_cleanup_overrun_is_failed_and_earlier_exception_is_preserved(self):
        limits = dict(cuda_memory_fraction=.55, max_temperature_c=78, max_wall_seconds=60)
        for body_error in (False, True):
            with self.subTest(body_error=body_error), tempfile.TemporaryDirectory() as temporary:
                clock = [0.0]
                target = Path(temporary) / 'guard.json'
                with patch('behavior_recorder.worker_limits.apply_process_limits'), \
                     patch('behavior_recorder.worker_limits.gpu_sample', return_value=dict(temperature_c=40)), \
                     patch('behavior_recorder.worker_limits.time.monotonic', side_effect=lambda: clock[0]), \
                     patch('behavior_recorder.worker_limits.threading.Thread') as thread:
                    thread.return_value.join.side_effect = lambda **kwargs: clock.__setitem__(0, 120.0)
                    expected = ValueError if body_error else RecorderError
                    message = 'original failure' if body_error else 'wall-time'
                    with self.assertRaisesRegex(expected, message):
                        with worker_limits(limits, target):
                            if body_error:
                                raise ValueError('original failure')
                report = json.loads(target.read_text())
                self.assertEqual(report['state'], 'failed')
                self.assertIn(message, report['reason'])

    def test_work_returning_after_deadline_cannot_be_marked_complete(self):
        limits = dict(cuda_memory_fraction=.55, max_temperature_c=78, max_wall_seconds=60)
        clock = [0.0]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'guard.json'
            with patch('behavior_recorder.worker_limits.apply_process_limits'), \
                 patch('behavior_recorder.worker_limits.gpu_sample', return_value=dict(temperature_c=40)), \
                 patch('behavior_recorder.worker_limits.time.monotonic', side_effect=lambda: clock[0]), \
                 patch('behavior_recorder.worker_limits.threading.Thread'), \
                 self.assertRaisesRegex(RecorderError, 'wall-time'):
                with worker_limits(limits, target):
                    clock[0] = 120.0
            report = json.loads(target.read_text())
            self.assertEqual(report['state'], 'failed')
            self.assertEqual(report['elapsed_seconds'], 120.0)

    def test_limits_reject_unbounded_or_malformed_requests(self):
        good = dict(cuda_memory_fraction=.55, max_temperature_c=78, max_wall_seconds=2160)
        self.assertEqual(validate_limits(good), good)
        for key, value in [('cuda_memory_fraction', 1), ('max_temperature_c', 100),
                           ('max_wall_seconds', 0), ('max_wall_seconds', True),
                           ('max_temperature_c', float('nan')), ('unrecognized', 1)]:
            with self.subTest(key=key, value=value), self.assertRaises(RecorderError):
                validate_limits(dict(good, **{key: value}))

    def test_unavailable_gpu_measurements_cannot_be_treated_as_cool(self):
        self.assertEqual(parse_gpu_sample('61, 5782, 95\n'),
                         dict(temperature_c=61.0, memory_mib=5782.0, utilization_percent=95.0))
        for output in ('N/A, 1, 1', '61, 2', '61, 2, 3\n62, 3, 4', '61, 2, 101'):
            with self.subTest(output=output), self.assertRaises((RecorderError, ValueError)):
                parse_gpu_sample(output)

    def test_abort_writes_reason_and_exits_only_its_own_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'guard.json'
            code = ('from pathlib import Path; from behavior_recorder.worker_limits import abort_worker; '
                    'import sys; abort_worker(Path(sys.argv[1]), {}, "temperature limit reached")')
            result = subprocess.run([sys.executable, '-c', code, str(target)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 124)
            report = json.loads(target.read_text())
            self.assertEqual(report['state'], 'aborted')
            self.assertEqual(report['reason'], 'temperature limit reached')

    def test_guard_rejects_heat_and_expired_deadline_before_work(self):
        limits = dict(cuda_memory_fraction=.55, max_temperature_c=78, max_wall_seconds=60)
        for temperature, elapsed, message in [(78, 0, 'temperature'), (40, 60, 'wall-time')]:
            with self.subTest(temperature=temperature), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / 'guard.json'
                with patch('behavior_recorder.worker_limits.apply_process_limits'), \
                     patch('behavior_recorder.worker_limits.gpu_sample', return_value=dict(temperature_c=temperature)), \
                     patch('behavior_recorder.worker_limits.time.monotonic', side_effect=[0, elapsed, elapsed]), \
                     self.assertRaisesRegex(RecorderError, message):
                    with worker_limits(limits, target):
                        self.fail('work started after a resource limit was exceeded')
                self.assertEqual(json.loads(target.read_text())['state'], 'failed')
