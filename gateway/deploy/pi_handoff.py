"""Portable source updater for an already installed Raspberry Pi gateway."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile


CURRENT = Path('/opt/habitat-gateway/current')
CONFIG = Path('/etc/habitat-gateway/gateway.toml')
SYSTEM_PYTHON = Path('/usr/bin/python3')


def read_package(path):
    """Verify the complete source payload before extracting or executing it."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if (len(entries) > 2048 or len(set(names)) != len(names)
                or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024):
            raise ValueError('Invalid package size or duplicate archive entries')
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if (entry.is_dir() or name.is_absolute() or '..' in name.parts
                    or '\\' in entry.filename or name.as_posix() != entry.filename
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or not (entry.filename in ('__main__.py', 'handoff.json')
                            or entry.filename.startswith('source/'))):
                raise ValueError('Unsafe source package path')
        manifest = json.loads(archive.read('handoff.json'))
        if not re.fullmatch(r'\d+\.\d+\.\d+', manifest['version']):
            raise ValueError('Invalid package version')
        files = manifest['files']
        required = {'__main__.py', 'source/deploy/build_release.py', 'source/deploy/install.py',
                    'source/pyproject.toml', 'source/requirements.lock'}
        if not isinstance(files, dict) or not required <= files.keys() or set(files) != set(names) - {'handoff.json'}:
            raise ValueError('Incomplete or unregistered package content')
        content = {}
        for name, expected in files.items():
            data = archive.read(name)
            if not isinstance(expected, str) or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Source package checksum mismatch')
            content[name] = data
        version = tomllib.loads(content['source/pyproject.toml'].decode('utf-8'))['project']['version']
        if version != manifest['version']:
            raise ValueError('Source and package versions differ')
    return manifest, content


def python_info(executable, *, build=False):
    code = ('import json,platform,sys,venv,ensurepip; '
            'from importlib.metadata import version; '
            'print(json.dumps({"python":f"{sys.version_info.major}.{sys.version_info.minor}",'
            '"machine":platform.machine()'
            + (',"pip":version("pip"),"setuptools":version("setuptools")' if build else '') + '}))')
    try:
        result = subprocess.run([str(executable), '-B', '-c', code],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError):
        raise ValueError('Python environment needs pip/setuptools and working venv support: '
                         + str(executable)) from None


def check_environment(build_python):
    if platform.system() != 'Linux' or sys.version_info < (3, 11):
        raise ValueError('Installation requires Linux on the existing Pi and Python 3.11+')
    config = tomllib.loads(CONFIG.read_text(encoding='utf-8'))
    if config.get('hardware_outputs_enabled') is not False:
        raise ValueError('Existing config must explicitly set hardware_outputs_enabled = false')
    if not CONFIG.with_suffix('.env').is_file():
        raise ValueError('Existing gateway.env is missing; this updater cannot create a new store')
    if not CURRENT.is_symlink():
        raise ValueError('Existing installer-managed current release is required')
    release = CURRENT.resolve(strict=True)
    if release.parent != CURRENT.parent / 'releases':
        raise ValueError('Current release is outside the managed releases directory')
    installed = json.loads((release / 'release.json').read_text(encoding='utf-8'))
    cache = release / 'wheels'
    if not cache.is_dir() or not any(cache.glob('*.whl')):
        raise ValueError('Existing offline wheel cache is missing')
    system = python_info(SYSTEM_PYTHON)
    builder = python_info(build_python, build=True)
    running = {'python': f'{sys.version_info.major}.{sys.version_info.minor}', 'machine': platform.machine()}
    if any(info.get(key) != installed.get(key) for info in (system, builder, running)
           for key in ('python', 'machine')):
        raise ValueError('System, build and installed Python/CPU must match; do not use Windows wheels')
    if int(builder['setuptools'].split('.')[0]) < 77:
        raise ValueError('The existing build Python requires setuptools >= 77')
    return config, cache, installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--inspect', action='store_true', help='Verify package only; never install')
    mode.add_argument('--check', action='store_true', help='Verify package and existing Pi environment; never install')
    parser.add_argument('--build-python', type=Path,
                        default=Path.home() / 'Desktop/habitat/.venv/bin/python')
    args = parser.parse_args()
    manifest, content = read_package(Path(sys.argv[0]))
    if args.inspect:
        print(json.dumps({'mode': 'inspect', 'package_verified': True, 'installed': False,
                          'version': manifest['version'], 'source_files': len(content) - 1,
                          'source_bytes': sum(map(len, content.values()))}))
        return
    # Keep the venv executable path: resolving its symlink would discard the venv.
    build_python = args.build_python.expanduser().absolute()
    config, cache, installed = check_environment(build_python)
    if args.check:
        print(json.dumps({'mode': 'check', 'environment_verified': True, 'installed': False,
                          'version': manifest['version'], 'current_release': installed['release_id'],
                          'python': installed['python'], 'machine': installed['machine']}))
        return
    subprocess.run(['sudo', '-v'], check=True)
    with tempfile.TemporaryDirectory(prefix='habitat-pi-update-') as temporary:
        work = Path(temporary)
        for name, data in content.items():
            if name.startswith('source/'):
                destination = work / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        source, output = work / 'source', work / 'release'
        subprocess.run([str(build_python), '-B', str(source / 'deploy/build_release.py'),
                        '--output', str(output), '--wheel-cache', str(cache)], check=True, cwd=source,
                       env={**os.environ, 'PIP_NO_INDEX': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'})
        archives = list(output.glob('habitat-gateway-*.tar.gz'))
        if len(archives) != 1:
            raise ValueError('Build must produce exactly one release archive')
        subprocess.run(['sudo', '-n', str(SYSTEM_PYTHON), '-B', str(source / 'deploy/install.py'),
                        '--archive', str(archives[0]), '--config', str(CONFIG)], check=True)
    server = config.get('server', {})
    host = server.get('host', '127.0.0.1')
    host = '127.0.0.1' if host == '0.0.0.0' else ('::1' if host == '::' else host)
    host = f'[{host}]' if ':' in host else host
    print('INSTALL_OK')
    print(f"LiveScene: http://{host}:{server.get('port', 8000)}/livescene")


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f'UPDATE_FAILED: {error}', file=sys.stderr)
        sys.exit(1)
