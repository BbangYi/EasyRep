"""Install a loopback authentication proxy; never publish it or alter the gateway.

Requires an installed Caddy binary. The root-only login file holds a new random
password; neither it nor its hash is printed or passed as a process argument.
Use --root /tmp/... --no-service for staging without modifying system services.
"""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

try:
    from .install import write_atomic
except ImportError:
    from install import write_atomic


SERVICE = 'habitat-air-remote.service'
CADDY = '/usr/bin/caddy'


def template(name):
    bundled = Path(__file__).resolve().parent / name
    if bundled.is_file():
        return bundled.read_text()
    folder = 'deploy/systemd' if name.endswith('.service') else 'configs/examples'
    return (Path(__file__).resolve().parents[1] / folder / name).read_text()


def check_settings(username, listen_port, upstream_port):
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', username):
        raise ValueError('invalid remote viewer username')
    if any(type(port) is not int or not 1024 <= port <= 65535 for port in (listen_port, upstream_port)):
        raise ValueError('remote viewer ports must be integers from 1024 to 65535')
    if listen_port == upstream_port:
        raise ValueError('proxy and viewer ports must differ')


def password_hash(password):
    result = subprocess.run([CADDY, 'hash-password', '--algorithm', 'bcrypt'],
                            input=password + '\n', capture_output=True, text=True, check=False)
    value = result.stdout.strip()
    if result.returncode or not re.fullmatch(r'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}', value):
        raise RuntimeError('Caddy password hashing failed')
    return value


def render_config(username, hashed, listen_port, upstream_port):
    check_settings(username, listen_port, upstream_port)
    if not re.fullmatch(r'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}', hashed):
        raise ValueError('invalid bcrypt hash')
    content = template('air-remote.Caddyfile')
    for key, value in {'USERNAME': username, 'PASSWORD_HASH': hashed,
                       'LISTEN_PORT': listen_port, 'UPSTREAM_PORT': upstream_port}.items():
        content = content.replace('@@' + key + '@@', str(value))
    return content


def validate_config(content):
    with tempfile.TemporaryDirectory(prefix='habitat-air-remote-') as folder:
        path = Path(folder) / 'Caddyfile'
        write_atomic(path, content, 0o600)
        result = subprocess.run([CADDY, 'validate', '--config', str(path), '--adapter', 'caddyfile'],
                                capture_output=True, check=False)
        if result.returncode:
            raise ValueError('Caddy configuration validation failed; private details suppressed')


def private_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('existing remote viewer files must be regular files')
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o600:
        raise ValueError('existing remote viewer files must be owned by the installer user with mode 0600')


def prepare_credentials(config, login, username, listen_port, upstream_port):
    check_settings(username, listen_port, upstream_port)
    if config.exists() or login.exists() or config.is_symlink() or login.is_symlink():
        private_file(config)
        private_file(login)
        try:
            credentials = json.loads(login.read_text())
        except (OSError, ValueError):
            raise ValueError('cannot read existing remote viewer login file') from None
        if not isinstance(credentials, dict) or any(credentials.get(key) != value for key, value in {
                'username': username, 'listen_port': listen_port, 'upstream_port': upstream_port}.items()):
            raise ValueError('existing remote viewer settings differ; preserve them or migrate explicitly')
        password = credentials.get('password')
        if not isinstance(password, str) or not re.fullmatch(r'[A-Za-z0-9_-]{24,128}', password):
            raise ValueError('invalid existing remote viewer password')
        content = config.read_text()
    else:
        credentials = dict(username=username, password=secrets.token_urlsafe(24),
                           listen_port=listen_port, upstream_port=upstream_port)
        content = render_config(username, password_hash(credentials['password']), listen_port, upstream_port)
    validate_config(content)
    return credentials, content


def verify_proxy(credentials, timeout=60):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = 'http://127.0.0.1:' + str(credentials['listen_port'])
    encoded = base64.b64encode((credentials['username'] + ':' + credentials['password']).encode()).decode()
    wrong = base64.b64encode((credentials['username'] + ':' + secrets.token_urlsafe(32)).encode()).decode()
    deadline = time.monotonic() + timeout
    while True:
        try:
            for path in ('/', '/app.js', '/api/cages', '/api/air'):
                for auth, expected in ((None, 401), ('Basic ' + wrong, 401), ('Basic ' + encoded, 200)):
                    headers = {} if auth is None else {'Authorization': auth}
                    try:
                        # Caddy 2.6 uses bcrypt cost 14; allow CPU-quota-limited verification.
                        with opener.open(urllib.request.Request(base + path, headers=headers), timeout=10) as response:
                            code = response.status
                    except urllib.error.HTTPError as error:
                        code = error.code
                        error.close()
                    if code != expected:
                        raise ValueError('remote viewer authentication verification failed')
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError('remote viewer proxy did not become ready') from None
            time.sleep(.25)


def systemctl(*arguments, check=True):
    result = subprocess.run(['systemctl', *arguments], capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError('remote viewer service operation failed')
    return result.returncode


def restore_unit(unit, old_unit, was_active, no_service):
    # Stop while systemd still knows the candidate unit, cancelling Restart= timers.
    if not no_service:
        systemctl('stop', SERVICE, check=False)
    if old_unit is not None:
        write_atomic(unit, old_unit)
    else:
        unit.unlink(missing_ok=True)
    if not no_service:
        systemctl('daemon-reload', check=False)
        if was_active and old_unit is not None:
            systemctl('restart', SERVICE, check=False)


def install_remote(*, root=Path('/'), no_service=False, username='habitat', listen_port=8766, upstream_port=8765):
    root = root.resolve()
    if root == Path('/') and (os.geteuid() != 0 or no_service):
        raise ValueError('system installation requires root and service management')
    if root != Path('/') and not no_service:
        raise ValueError('staging installation requires --no-service')
    config_dir = root / 'etc/habitat-air-viewer'
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    config = config_dir / 'remote.Caddyfile'
    login = config_dir / 'remote-login.json'
    unit = root / 'etc/systemd/system' / SERVICE
    with (config_dir / '.remote-install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        credentials, content = prepare_credentials(config, login, username, listen_port, upstream_port)
        # Keep a generated pair on failed service startup so a retry never rotates credentials.
        if not login.exists():
            write_atomic(login, json.dumps(credentials, indent=2) + '\n', 0o600)
            try:
                write_atomic(config, content, 0o600)
            except Exception:
                login.unlink()
                raise
        unit.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        old_unit = unit.read_text() if unit.exists() else None
        new_unit = template(SERVICE)
        if old_unit is not None and old_unit != new_unit:
            backup = unit.with_name(unit.name + '.before-' + str(time.time_ns()))
            write_atomic(backup, old_unit)
        was_active = not no_service and systemctl('is-active', '--quiet', SERVICE, check=False) == 0
        try:
            write_atomic(unit, new_unit)
            if not no_service:
                systemctl('daemon-reload')
                systemctl('restart', SERVICE)
                verify_proxy(credentials)
                systemctl('enable', SERVICE)
        except Exception:
            restore_unit(unit, old_unit, was_active, no_service)
            raise
    return dict(service=SERVICE, username=username, proxy_url='http://127.0.0.1:' + str(listen_port),
                login_file=str(login), credentials_preserved=True, public_access_enabled=False,
                gateway_modified=False, staging=no_service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'))
    parser.add_argument('--no-service', action='store_true')
    parser.add_argument('--username', default='habitat')
    parser.add_argument('--listen-port', type=int, default=8766)
    parser.add_argument('--upstream-port', type=int, default=8765)
    args = parser.parse_args()
    try:
        result = install_remote(**vars(args))
    except (OSError, ValueError, RuntimeError) as error:
        # Do not include subprocess output, config text, credentials, or request headers.
        parser.exit(1, 'Remote viewer installation failed: ' + str(error) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
