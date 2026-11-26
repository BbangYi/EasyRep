"""First-time, interactive store setup using the shared release installer."""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import time
import tomllib

if __package__:
    from . import install, provision
else:
    import install
    import provision


class SetupError(Exception):
    """Operator-facing explanation; never include rejected inputs or credentials."""


def require_new_gateway(user_directory):
    paths = [user_directory / ".config/habitatos/gateway.env",
             user_directory / ".config/habitatos/gateway.toml",
             user_directory / ".config/systemd/user" / install.HEARTBEAT_SERVICE,
             Path("/etc/habitat-gateway/gateway.toml")]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise SetupError("This Pi already has Gateway settings. Nothing was changed. Use the existing service or the upgrade installer.")


def ask_registration(default_endpoint):
    print("Copy the IDs and the token for THIS Pi from the website.")
    site_id = input("Store ID: ").strip()
    gateway_id = input("Pi / Gateway ID: ").strip()
    cage_ids = [value.strip() for value in input("Cage IDs (comma-separated): ").split(",")]
    endpoint = input(f"SaaS sync URL [{default_endpoint}]: ").strip() or default_endpoint
    print("The token is hidden while you paste it. Press Enter when finished.")
    token = getpass.getpass("Pi token: ").strip()
    return site_id, gateway_id, cage_ids, endpoint, token


def check_connection(target, config_path, token):
    environment = {**os.environ, "HABITAT_CLOUD_TOKEN": token, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([str(target / "venv/bin/python"), "-m", "habitat_gateway",
                             "--config", str(config_path), "--check-connection"],
                            env=environment, cwd=target, capture_output=True, text=True, timeout=45)
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise SetupError("Connection check could not run. Check the supplied URL and IDs and the Pi's Python installation.") from None
    if result.returncode or reply.get("connected") is not True:
        messages = {
            "http_401": "The website rejected the token. Copy the token issued for this Pi and try again.",
            "http_403": "The token does not authorize these Store/Pi/cage IDs. Check their registration on the website.",
            "network_error": "Cannot reach the website. Check Wi-Fi/Ethernet, DNS, and the Pi's clock.",
            "timeout": "The website did not respond in time. Check the internet connection and try again.",
        }
        raise SetupError(messages.get(reply.get("error"), "The website did not return a valid acknowledgment. Check the SaaS service and try again."))
    config = tomllib.loads(config_path.read_text())
    if (reply.get("site_id"), reply.get("gateway_id")) != (config["site_id"], config["gateway_id"]):
        raise SetupError("The connection response did not match this Pi's registration.")


def enable_boot_start():
    user = pwd.getpwuid(os.getuid()).pw_name
    def lingering():
        return install.run("loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value",
                           capture_output=True, text=True).stdout.strip() == "yes"
    if lingering():
        return
    print("Enabling connection after logout and reboot. Raspberry Pi OS may request administrator authentication.")
    result = subprocess.run(["loginctl", "enable-linger", user], capture_output=True, text=True)
    if result.returncode:
        install.run("sudo", "loginctl", "enable-linger", user)
    if not lingering():
        raise SetupError("Automatic boot startup could not be enabled. Ask the Pi administrator to enable user lingering.")


def wait_for_service_ack(timeout=30):
    unit = install.HEARTBEAT_SERVICE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = install.run("systemctl", "--user", "show", unit, "--property=ActiveState", "--property=InvocationID",
                            capture_output=True, text=True).stdout
        state = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
        invocation = state.get("InvocationID")
        if state.get("ActiveState") == "active" and invocation:
            records = install.run("journalctl", "--user-unit=" + unit, "--no-pager", "-n", "100", "-o", "json",
                                  capture_output=True, text=True).stdout
            for line in records.splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("_SYSTEMD_INVOCATION_ID") == invocation and "Cloud heartbeat acknowledged:" in record.get("MESSAGE", ""):
                    return True
        time.sleep(1)
    return False


def connect_new_gateway(release, *, user_directory=None, ask=ask_registration):
    user_directory = Path.home() if user_directory is None else Path(user_directory)
    require_new_gateway(user_directory)
    manifest = install.verify_release(release)
    required = {"cloud-defaults.toml", "connect.py", "connect.sh", "provision.py", install.HEARTBEAT_SERVICE}
    if not required <= manifest["files"].keys():
        raise SetupError("This release does not include store setup. Use the complete new-store release package.")
    # Check service-manager access before collecting any secret or changing startup settings.
    install.run("systemctl", "--user", "show", "--property=Version", capture_output=True, text=True)
    base = user_directory / ".local/share/habitatos/gateway"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (base / ".connect.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_new_gateway(user_directory)
        cloud_defaults = (release / "cloud-defaults.toml").read_text()
        site_id, gateway_id, cage_ids, endpoint, token = ask(tomllib.loads(cloud_defaults)["cloud"]["endpoint"])
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{32,4096}", token):
            raise SetupError("The token format is invalid. Paste only the Pi token from the website.")
        try:
            config_text = provision.generate_heartbeat((release / "simulation.toml").read_text(), cloud_defaults,
                                                       site_id, gateway_id, cage_ids, endpoint)
        except ValueError:
            raise SetupError("Invalid registration. IDs must use letters, digits, underscores, or hyphens; cage IDs must be distinct.") from None
        print("Preparing HabitatOS and checking the website connection...")
        target = install.prepare_release(release, manifest, base)
        with tempfile.TemporaryDirectory(prefix="habitatos-setup-") as temporary:
            config_path = Path(temporary) / "gateway.toml"
            config_path.write_text(config_text)
            check_connection(target, config_path, token)
            print("Website acknowledgment verified for this Store and Pi.")
            enable_boot_start()
            require_new_gateway(user_directory)
            etc = user_directory / ".config/habitatos"
            etc.mkdir(parents=True, exist_ok=True, mode=0o700)
            if etc.is_symlink() or etc.stat().st_uid != os.getuid():
                raise SetupError("The private settings directory is not owned by this user.")
            etc.chmod(0o700)
            credential = etc / "gateway.env"
            fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write("HABITAT_CLOUD_TOKEN=" + token + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                install.install_user_heartbeat(release, config_path, user_directory=user_directory)
            except BaseException:
                # The installer restores configuration/service state on failure.
                # Preserve credentials if interruption left an applied configuration.
                if not (etc / "gateway.toml").exists():
                    credential.unlink(missing_ok=True)
                raise
        if not wait_for_service_ack():
            print("Setup is saved and automatic retries are running, but the background acknowledgment was not confirmed.")
            print("Check: journalctl --user-unit=habitat-heartbeat.service -n 20 --no-pager")
            return False
        print(f"CONNECTED: {site_id} / {gateway_id}. Heartbeats and boot startup are active.")
        print("Open the website to check Pi status. Sensors remain unavailable until installed.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Connect a new store's Pi to HabitatOS. The token is entered privately.")
    parser.add_argument("--release", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.exit(2, "Run this setup as the Pi's normal user, without sudo.\n")
    try:
        # Existing installations must be refused even when invoked without a terminal.
        require_new_gateway(Path.home())
        if not sys.stdin.isatty():
            raise SetupError("Open a terminal on the Pi and run bash connect.sh; token input must be hidden.")
        success = connect_new_gateway(args.release.resolve())
    except SetupError as error:
        parser.exit(1, str(error) + "\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(130, "Setup interrupted.\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "Setup could not finish. Check the release package, Python/CPU compatibility, user permissions, and network.\nNo secret values are printed.\n")
    if not success:
        parser.exit(1)


if __name__ == "__main__":
    main()
