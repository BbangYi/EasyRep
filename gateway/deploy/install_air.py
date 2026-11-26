"""Install the optional local air viewer without restarting or modifying the gateway.

Use a release built with --with-air. Existing geometry config is preserved.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from install import point_link, prepare_release, verify_release, write_atomic


def install_air_dependencies(target):
    """Public runtime dependencies must be readable by the service's DynamicUser."""
    previous_umask = os.umask(0o022)
    try:
        wheel = next((target / 'wheels').glob('habitat_gateway-*.whl'))
        subprocess.run([str(target / 'venv/bin/python'), '-m', 'pip', 'install', '--no-cache-dir', '--no-index',
            '--find-links', str(target / 'wheels'), '--constraint', str(target / 'requirements.lock'),
            str(wheel) + '[air]'], check=True)
    finally:
        os.umask(previous_umask)


def install_air(release):
    manifest = verify_release(release)
    for name in ('habitat-air-viewer.service', 'air-viewer.json', 'air-upload.json'):
        if name not in manifest['files']:
            raise ValueError('release must be built with --with-air')
    for path in ('/etc/habitat-gateway/gateway.toml', '/etc/habitat-gateway/gateway.env'):
        if not Path(path).is_file():
            raise ValueError('existing gateway configuration required')
    base = Path('/opt/habitat-air-viewer')
    base.mkdir(mode=0o755, parents=True, exist_ok=True)
    with (base / '.install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = prepare_release(release, manifest, base)
        python = target / 'venv/bin/python'
        install_air_dependencies(target)
        config = Path('/etc/habitat-air-viewer/air.json')
        config.parent.mkdir(mode=0o755, exist_ok=True)
        if not config.exists():
            write_atomic(config, (target / 'air-viewer.json').read_text())
        upload = config.with_name('upload.json')
        if not upload.exists():
            write_atomic(upload, (target / 'air-upload.json').read_text())
        # Validate geometry and cage mapping before changing the service or link.
        subprocess.run([str(python), '-c',
            'from habitat.digital_twin.air.model import load_config; '
            'from habitat_gateway.config import load_settings; '
            'from habitat.saas.air import load_upload_config; '
            'load_upload_config("/etc/habitat-air-viewer/upload.json"); '
            'c=load_config("/etc/habitat-air-viewer/air.json"); '
            's=load_settings("/etc/habitat-gateway/gateway.toml"); '
            'assert s.transport == "mqtt" and c["cage_id"] in [x.id for x in s.cages]'], check=True)
        current = base / 'current'
        old_link = current.resolve() if current.is_symlink() else None
        unit = Path('/etc/systemd/system/habitat-air-viewer.service')
        old_unit = unit.read_bytes() if unit.exists() else None
        content = (target / unit.name).read_text()
        if old_unit is not None and old_unit != content.encode():
            backup = unit.with_name(unit.name + '.before-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
            with backup.open('xb') as out:
                out.write(old_unit)
        try:
            write_atomic(unit, content)
            point_link(current, target)
            subprocess.run(['systemctl', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', 'restart', unit.name], check=True)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 25
            while True:
                try:
                    with opener.open('http://127.0.0.1:8765/api/air', timeout=2) as response:
                        status = json.load(response)
                    if status['source_mode'] != 'live':
                        raise ValueError('live mode required')
                    break
                except (OSError, ValueError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('air viewer HTTP verification failed') from None
                    time.sleep(.5)
            subprocess.run(['systemctl', 'enable', unit.name], check=True)
            print(json.dumps({'release_id': manifest['release_id'], 'cage_id': status['cage_id'],
                'status': status['status'], 'url': 'http://127.0.0.1:8765',
                'gateway_modified': False}))
        except Exception:
            if old_link is not None:
                point_link(current, old_link)
            if old_unit is not None:
                write_atomic(unit, old_unit.decode())
                subprocess.run(['systemctl', 'daemon-reload'], check=False)
                subprocess.run(['systemctl', 'restart', unit.name], check=False)
            else:
                subprocess.run(['systemctl', 'stop', unit.name], check=False)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('root is required to install the system service')
    install_air(args.release.resolve())


if __name__ == '__main__':
    main()
