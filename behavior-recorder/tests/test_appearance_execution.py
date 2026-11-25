"""Resource and host gates for bounded CPU execution; no biological fixtures."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from behavior_recorder import appearance_predictor as api
from behavior_recorder.core import RecorderError


class AppearanceExecutionTests(unittest.TestCase):
    def setUp(self):
        self.process = Mock(pid=123)
        self.process.nice.return_value = 0
        self.process.create_time.return_value = 100.0
        self.process.memory_info.return_value = SimpleNamespace(rss=20 * 1024**2)
        self.process.cpu_affinity.return_value = [0]
        self.stack = []
        for target, value in [('platform.node', 'fixture-host'), ('platform.system', 'Darwin'),
                              ('psutil.Process', self.process),
                              ('psutil.virtual_memory', SimpleNamespace(available=4 * 1024**3)),
                              ('psutil.process_iter', [])]:
            mocked = patch(target, return_value=value)
            self.stack.append(mocked.start())
            self.addCleanup(mocked.stop)
        env = patch.dict(os.environ)
        env.start(); self.addCleanup(env.stop)

    def run_preflight(self):
        return api.native_preflight({'execution_host': 'fixture-host'})

    def test_darwin_cpu_path_does_not_query_nvidia_or_fake_affinity(self):
        with patch.object(api.subprocess, 'run') as command:
            snapshot, guard = self.run_preflight()
            guard()
        command.assert_not_called()
        self.process.cpu_affinity.assert_not_called()
        self.process.nice.assert_any_call(10)
        self.assertIsNone(snapshot['cpu_affinity'])
        self.assertIsNone(snapshot['gpu'])
        self.assertEqual(snapshot['gpu_allocation_bytes'], 0)
        self.assertEqual(snapshot['execution_device'], 'cpu')
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                     'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            self.assertEqual(os.environ[name], '1')

    def test_windows_retains_affinity_priority_and_gpu_snapshot(self):
        with patch('platform.system', return_value='Windows'), \
             patch('psutil.BELOW_NORMAL_PRIORITY_CLASS', 16384, create=True), \
             patch.object(api.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='40, 100, 8192, 0')):
            snapshot, _ = self.run_preflight()
        self.process.cpu_affinity.assert_any_call([0])
        self.process.nice.assert_any_call(16384)
        self.assertEqual(snapshot['gpu'], '40, 100, 8192, 0')

    def test_host_mismatch_rejects_before_process_changes(self):
        with self.assertRaisesRegex(RecorderError, 'declared execution host'):
            api.native_preflight({'execution_host': 'different-host'})
        self.process.nice.assert_not_called()

    def test_unsupported_platform_rejects(self):
        with patch('platform.system', return_value='Linux'), self.assertRaisesRegex(RecorderError, 'unsupported'):
            self.run_preflight()
        self.process.nice.assert_not_called()

    def test_free_ram_gate_remains_active_after_start(self):
        _, guard = self.run_preflight()
        with patch('psutil.virtual_memory', return_value=SimpleNamespace(available=2 * 1024**3)), \
             self.assertRaisesRegex(RecorderError, 'free RAM'):
            guard()

    def test_rss_gate_remains_active(self):
        _, guard = self.run_preflight()
        self.process.memory_info.return_value = SimpleNamespace(rss=513 * 1024**2)
        with self.assertRaisesRegex(RecorderError, 'RSS'):
            guard()

    def test_deadline_is_checked_after_start(self):
        with patch.object(api.time, 'monotonic', return_value=0):
            _, guard = self.run_preflight()
        with patch.object(api.time, 'monotonic', return_value=61), self.assertRaisesRegex(RecorderError, 'deadline'):
            guard()

    def test_existing_lower_priority_is_preserved(self):
        self.process.nice.return_value = 15
        self.run_preflight()
        self.process.nice.assert_any_call(15)
