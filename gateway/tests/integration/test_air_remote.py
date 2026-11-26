"""Real Caddy authentication checks against an isolated, sensor-free HTTP stub."""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

from deploy import install_air_remote as remote


@pytest.fixture(scope='module')
def login():
    if not shutil.which(remote.CADDY):
        pytest.skip('Caddy is required for remote proxy integration tests')
    password = secrets.token_urlsafe(24)
    return {'username': 'test_viewer', 'password': password, 'hash': remote.password_hash(password)}


@pytest.fixture
def directory():
    with tempfile.TemporaryDirectory(prefix='habitat-air-remote-test-') as folder:
        yield Path(folder)


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def service_environment(directory):
    # Do not inherit the interactive shell's HOME, USER or XDG variables.
    environment = {'PATH': '/usr/bin:/bin'}
    for line in remote.template(remote.SERVICE).splitlines():
        if line.startswith('Environment='):
            key, value = line.removeprefix('Environment=').split('=', 1)
            environment[key] = value.replace('/var/lib/habitat-air-remote', str(directory))
    return environment


@contextmanager
def proxy(login, directory):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            body = json.dumps({'path': self.path}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    port = available_port()
    config = directory / 'Caddyfile'
    content = remote.render_config(login['username'], login['hash'], port, upstream.server_port)
    config.write_text(content)
    config.chmod(0o600)
    remote.validate_config(content)
    process = None
    try:
        with tempfile.TemporaryFile() as logs:
            process = subprocess.Popen([remote.CADDY, 'run', '--config', str(config), '--adapter', 'caddyfile'],
                                       stdout=logs, stderr=logs, cwd=directory,
                                       env=service_environment(directory))
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    pytest.fail('isolated Caddy process exited; private config output suppressed')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.5):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        pytest.fail('isolated Caddy listener did not become ready')
                    time.sleep(.05)
            yield port, requests
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def request(port, path, authorization=None):
    headers = {'Host': 'viewer.example.test:8443'}
    if authorization is not None:
        headers['Authorization'] = authorization
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    query = urllib.request.Request('http://127.0.0.1:' + str(port) + path, headers=headers)
    try:
        response = opener.open(query, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def test_authentication_protects_all_paths_and_strips_credentials(login, directory):
    correct = 'Basic ' + base64.b64encode((login['username'] + ':' + login['password']).encode()).decode()
    wrong = 'Basic ' + base64.b64encode((login['username'] + ':incorrect').encode()).decode()
    with proxy(login, directory) as (port, upstream_requests):
        for path in ('/', '/app.js', '/api/cages', '/api/air?cage_id=CAGE-001', '/unknown'):
            for auth in (None, wrong):
                before = len(upstream_requests)
                status, headers, _ = request(port, path, auth)
                assert status == 401
                assert headers['WWW-Authenticate'].startswith('Basic ')
                assert len(upstream_requests) == before
            status, headers, body = request(port, path, correct)
            assert status == 200
            assert headers['Cache-Control'] == 'no-store'
            assert json.loads(body)['path'] == path
            assert all(key.lower() != 'authorization' for key in upstream_requests[-1][1])
        assert len(upstream_requests) == 5
        remote.verify_proxy(dict(login, listen_port=port))
    autosave = directory / 'config/caddy/autosave.json'
    assert autosave.is_file()
    assert autosave.stat().st_mode & 0o777 == 0o600
    assert login['password'] not in autosave.read_text()
    assert login['hash'] in autosave.read_text()


def test_staging_install_preserves_credentials_and_private_permissions(login, directory, monkeypatch, capsys):
    monkeypatch.setattr(remote.secrets, 'token_urlsafe', lambda _: login['password'])
    monkeypatch.setattr(remote, 'password_hash', lambda _: login['hash'])
    result = remote.install_remote(root=directory, no_service=True)
    config = directory / 'etc/habitat-air-viewer/remote.Caddyfile'
    credential = directory / 'etc/habitat-air-viewer/remote-login.json'
    original = {path: path.read_bytes() for path in (config, credential)}
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in original)
    assert result['public_access_enabled'] is False
    assert result['gateway_modified'] is False
    assert 'password' not in result and 'hash' not in result
    monkeypatch.setattr(remote, 'password_hash', lambda _: pytest.fail('existing credential was rotated'))
    remote.install_remote(root=directory, no_service=True)
    assert all(path.read_bytes() == value for path, value in original.items())
    assert capsys.readouterr().out == ''
    assert not (directory / 'etc/systemd/system/habitat-gateway.service').exists()
    with pytest.raises(ValueError, match='settings differ'):
        remote.install_remote(root=directory, no_service=True, listen_port=8767)
    assert all(path.read_bytes() == value for path, value in original.items())


def test_incomplete_existing_configuration_is_preserved(directory):
    folder = directory / 'etc/habitat-air-viewer'
    folder.mkdir(parents=True)
    path = folder / 'remote.Caddyfile'
    path.write_text('existing private configuration')
    path.chmod(0o600)
    with pytest.raises(ValueError, match='regular files'):
        remote.install_remote(root=directory, no_service=True)
    assert path.read_text() == 'existing private configuration'
    assert not (folder / 'remote-login.json').exists()


def test_validation_failure_does_not_install_files(login, directory, monkeypatch):
    monkeypatch.setattr(remote, 'password_hash', lambda _: login['hash'])
    monkeypatch.setattr(remote, 'render_config', lambda *args: '{\ninvalid_private_directive\n}\n')
    with pytest.raises(ValueError, match='private details suppressed'):
        remote.install_remote(root=directory, no_service=True)
    assert not (directory / 'etc/habitat-air-viewer/remote.Caddyfile').exists()
    assert not (directory / 'etc/habitat-air-viewer/remote-login.json').exists()
    assert not (directory / 'etc/systemd/system/habitat-air-remote.service').exists()


@pytest.mark.parametrize('old_unit,was_active', [(None, False), ('old service', False), ('old service', True)])
def test_rollback_stops_candidate_before_removing_or_restoring_unit(directory, monkeypatch, old_unit, was_active):
    unit = directory / remote.SERVICE
    unit.write_text('candidate service')
    actions = []

    def systemctl(*arguments, check):
        actions.append(arguments)
        assert check is False
        if arguments[0] == 'stop':
            assert unit.read_text() == 'candidate service'
        elif old_unit is None:
            assert not unit.exists()
        else:
            assert unit.read_text() == old_unit
        return 0

    monkeypatch.setattr(remote, 'systemctl', systemctl)
    remote.restore_unit(unit, old_unit, was_active, False)
    expected = [('stop', remote.SERVICE), ('daemon-reload',)]
    if was_active:
        expected.append(('restart', remote.SERVICE))
    assert actions == expected


@pytest.mark.parametrize('username,listen,upstream', [
    ('user\n}', 8766, 8765), ('user:pass', 8766, 8765), ('habitat', 8765, 8765),
    ('habitat', 80, 8765), ('habitat', 8766, 65536), ('habitat', True, 8765),
])
def test_invalid_or_unsafe_settings_are_rejected(username, listen, upstream):
    with pytest.raises(ValueError):
        remote.check_settings(username, listen, upstream)
