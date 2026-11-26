"""Install this single-user WSL service with persistent, private configuration.

Run as root in WSL with --user, --api-python and --gpu-python. Existing
configuration/secrets are preserved. Tokens are never passed as arguments.
"""

import argparse
import os
from pathlib import Path
import pwd
import secrets
import subprocess


def exclusive_write(path, content, uid, gid, mode=0o600):
    if path.exists():
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    os.chown(path, uid, gid)


def unit_quote(value):
    value = str(value)
    if any(c in value for c in "\n\r\x00"):
        raise ValueError("Invalid service path")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--api-python", type=Path, required=True)
    parser.add_argument("--gpu-python", type=Path, required=True)
    parser.add_argument("--site-id", default="STORE-001")
    parser.add_argument("--gateway-id", default="PI-001")
    parser.add_argument("--cage-id", default="CAGE-001")
    parser.add_argument("--replace-service", action="store_true", help="back up and replace the existing unit")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run this installation command as root inside WSL")
    import re
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) for value in (args.site_id, args.gateway_id, args.cage_id)):
        parser.error("invalid scope identifier")
    account = pwd.getpwnam(args.user)
    project = Path(__file__).resolve().parents[1]
    config_dir = Path(account.pw_dir) / ".config/habitat-gpu"
    runtime = Path(account.pw_dir) / ".local/share/habitat-gpu/service"
    for directory in (config_dir, runtime):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chown(directory, account.pw_uid, account.pw_gid)
        directory.chmod(0o700)
    env_file = config_dir / "gpu.env"
    exclusive_write(env_file, "HABITAT_GPU_TOKEN=" + secrets.token_urlsafe(48) + "\n", account.pw_uid, account.pw_gid)
    config = config_dir / "gpu.toml"
    import json
    exclusive_write(config, f'''storage_dir = {json.dumps(str(runtime))}
host = "127.0.0.1"
port = 8100

[[credentials]]
site_id = "{args.site_id}"
gateway_id = "{args.gateway_id}"
cage_ids = ["{args.cage_id}"]
token_env = "HABITAT_GPU_TOKEN"

[backend]
name = "splatfacto"
python = {json.dumps(str(args.gpu_python))}
cuda_home = "/usr/local/cuda-11.8"
render_preview = true

[backend.preview]
max_image_dimension = 1280
iterations = 30000
colmap_gpu = false
min_registered_fraction = 0.5
''', account.pw_uid, account.pw_gid)
    unit = f'''[Unit]
Description=HabitatOS GPU reconstruction API and worker
After=network.target

[Service]
Type=simple
User={args.user}
WorkingDirectory={str(project).replace('%', '%%')}
ExecStart={unit_quote(args.api_python)} -m apps.api --config {unit_quote(config)} --env-file {unit_quote(env_file)}
Restart=on-failure
RestartSec=3
KillMode=control-group
TimeoutStopSec=45
UMask=0077
Nice=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
'''
    target = Path("/etc/systemd/system/habitat-gpu.service")
    if target.exists() and target.read_text() != unit:
        if not args.replace_service:
            raise SystemExit("Existing habitat-gpu.service differs; inspect it before replacing")
        target.with_suffix(".service.previous").write_text(target.read_text(), encoding="utf-8")
    target.write_text(unit, encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "habitat-gpu.service"], check=True)
    print("Service installed; configuration/secrets preserved; start with systemctl start habitat-gpu")


if __name__ == "__main__":
    main()
