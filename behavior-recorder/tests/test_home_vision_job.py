"""Remote job packaging tests; no network, torch load, or real training."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('home_vision_job',SCRIPTS/'run_home_vision_job.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from behavior_recorder.core import RecorderError


class HomeVisionJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ['scripts','behavior_recorder','data/weights','dataset']:
            (self.root/name).mkdir(parents=True)
        (self.root/'scripts/execute_vision_job.py').write_text('# fixture')
        (self.root/'behavior_recorder/__init__.py').write_text('')
        (self.root/'data/weights/yolo11n.pt').write_bytes(b'default fixture')
        self.custom=self.root/'data/weights/yolo11s.pt'
        self.custom.write_bytes(b'custom fixture; never deserialize')
        self.payloads=[]

    def remote(self,command,**kwargs):
        if command=='hostname':
            return subprocess.CompletedProcess([],0,b'DESKTOP-GMQFQTR\n',b'')
        if 'input' in kwargs:
            self.payloads.append(kwargs['input'])
            return subprocess.CompletedProcess([],0,b'',b'')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('execution.log','fixture')
        return subprocess.CompletedProcess([],0,output.getvalue(),b'')

    def invoke(self,extra):
        args=['runner','--dataset',str(self.root/'dataset'),'--run-id','fixture',*extra]
        with (patch.object(runner,'ROOT',self.root),patch.object(runner,'remote',side_effect=self.remote) as remote,
             patch.object(runner,'load_dataset',return_value={'dataset_kind':'real','dataset_id':'fixture'}),
             patch.object(runner.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'wol_schedule_sent=1',b'')) as shell,
             patch.object(sys,'argv',args)):
            self.remote_mock = remote
            self.shell_mock = shell
            runner.main()
        return remote

    def test_explicit_checkpoint_is_packaged_and_hash_bound(self):
        self.invoke(['--pretrained-weights',str(self.custom)])
        with zipfile.ZipFile(io.BytesIO(self.payloads[0])) as archive:
            request=json.loads(archive.read('request.json'))
            self.assertEqual(archive.read('pretrained/best.pt'),self.custom.read_bytes())
            self.assertTrue(request['weights'].endswith(r'\fixture\pretrained\best.pt'))
            self.assertEqual(request['weights_sha256'],runner.digest(self.custom))
            self.assertNotIn('parent_model',request)

    def test_default_keeps_existing_worker_checkpoint(self):
        self.invoke([])
        with zipfile.ZipFile(io.BytesIO(self.payloads[0])) as archive:
            request=json.loads(archive.read('request.json'))
            self.assertTrue(request['weights'].endswith(r'\data\weights\yolo11n.pt'))
            self.assertNotIn('pretrained/best.pt',archive.namelist())
            self.assertNotIn('worker_limits',request)

    def test_guarded_job_freezes_process_limits_in_request(self):
        self.invoke(['--guarded', '--max-training-minutes', '30'])
        with zipfile.ZipFile(io.BytesIO(self.payloads[0])) as archive:
            request=json.loads(archive.read('request.json'))
            self.assertEqual(request['worker_limits'], dict(cuda_memory_fraction=.55,
                max_temperature_c=78, max_wall_seconds=2160))

    def test_invalid_checkpoint_fails_before_network(self):
        bad=self.root/'bad.txt';bad.write_bytes(b'not a checkpoint')
        with self.assertRaisesRegex(RecorderError,'pretrained'):
            self.invoke(['--pretrained-weights',str(bad)])
        self.remote_mock.assert_not_called()
        self.shell_mock.assert_not_called()
        self.assertEqual(self.payloads,[])

    def test_empty_missing_and_oversized_checkpoints_fail_before_network(self):
        empty = self.root/'empty.pt'
        empty.touch()
        oversized = self.root/'oversized.pt'
        with oversized.open('wb') as handle:
            handle.truncate(32 * 1024**2 + 1)
        for path in (empty, oversized, self.root/'missing.pt'):
            with self.subTest(path=path.name), self.assertRaisesRegex(RecorderError, 'pretrained'):
                self.invoke(['--pretrained-weights', str(path)])
            self.remote_mock.assert_not_called()
            self.shell_mock.assert_not_called()
        self.assertFalse((self.root/'data/gpu-jobs').exists())

    def test_parent_and_pretrained_override_cannot_be_combined(self):
        with self.assertRaises(SystemExit):
            self.invoke(['--pretrained-weights',str(self.custom),'--initial-model',str(self.root)])
        self.assertEqual(self.payloads,[])


if __name__=='__main__':unittest.main()
