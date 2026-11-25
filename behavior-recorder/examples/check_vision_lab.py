"""Bounded real-model integration check on a synthetic clip; no camera is opened."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.core import atomic_json, digest, now, read_json


def main():
    with tempfile.TemporaryDirectory(prefix='habitat-lab-check-') as temporary:
        base = Path(temporary)
        inbox = base / 'inbox'
        inbox.mkdir()
        video = inbox / 'synthetic.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=5',
                        '-t', '2', '-c:v', 'mpeg4', '-threads', '1', str(video)], check=True, timeout=15)
        config = read_json(ROOT / 'examples/config.test.json')
        config['input']['inbox'] = 'inbox'
        config['animals'][0]['species'] = 'crested_gecko'
        config_path = base / 'camera.json'
        atomic_json(config_path, config)
        descriptor = {'schema_version': 1, 'input_id': 'synthetic-one', 'camera_id': 'rgb-01',
                      'file': video.name, 'sha256': digest(video), 'recording_id': 'synthetic-recording',
                      'sequence': 0, 'provenance': 'synthetic_test', 'captured_at': None,
                      'capture_clock': {'source': 'unknown', 'accuracy_ms': None},
                      'placement_revision': None, 'calibration_revision': None}
        atomic_json(inbox / 'a-invalid.capture.json', {**descriptor, 'sha256': '0' * 64})
        atomic_json(inbox / 'b-valid.capture.json', descriptor)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        address = f'http://127.0.0.1:{port}'
        command = [sys.executable, '-m', 'behavior_recorder.vision_lab', '--storage', str(base / 'lab'),
                   '--watch-config', str(config_path), '--conditions', 'synthetic-check', '--port', str(port)]

        def fetch(route):
            with urlopen(address + route, timeout=2) as response:
                return json.load(response)

        def until(predicate, process, timeout=45):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('lab exited before verification')
                try:
                    state = fetch('/api/state')
                    if predicate(state):
                        return state
                    failures = [j for j in state['jobs'] if j['state'] == 'failed']
                    if failures:
                        raise RuntimeError(failures[0].get('error'))
                except OSError:
                    pass
                time.sleep(0.2)
            raise TimeoutError('lab verification exceeded time limit')

        def stop(process):
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError('graceful shutdown failed')
            assert process.returncode == 0, process.returncode

        with (base / 'server.log').open('wb') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                state = until(lambda s: len(s['jobs']) == 1 and s['jobs'][0]['state'] == 'complete', process)
                job_id = state['jobs'][0]['id']
                detail = fetch('/api/jobs/' + job_id)
                assert not state['camera_connected']
                assert state['camera_input']['pending_file_errors'] == 1
                assert detail['summary']['source']['provenance'] == 'synthetic_test'
                assert detail['summary']['sampled_frames'] > 0
                assert not detail['comparison']['field_validated']
                assert all(w['status'] == 'unknown' for w in detail['comparison']['windows'])
                with urlopen(address + detail['video'], timeout=5) as response:
                    assert response.read(32)
            finally:
                stop(process)
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                until(lambda s: len(s['jobs']) == 1, process)
                time.sleep(2.5)  # Allow one inbox scan after restart.
                state = fetch('/api/state')
                assert len(state['jobs']) == 1 and state['jobs'][0]['id'] == job_id
                assert state['jobs'][0]['state'] == 'complete'
            finally:
                stop(process)
        report = {'checked_at': now(), 'input': 'two-second synthetic color-pattern video',
                  'sampled_frames': detail['summary']['sampled_frames'], 'camera_connected': False,
                  'field_validated': False, 'checks_passed': ['automatic finalized-file ingestion',
                  'invalid checksum does not block valid input', 'actual detector subprocess',
                  'browser preview served', 'no synthetic personal-reference judgment',
                  'SIGTERM graceful shutdown', 'restart preserves job without duplicate processing']}
        atomic_json(ROOT / 'data/vision-lab/operational-check.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
