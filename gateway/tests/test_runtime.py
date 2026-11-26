import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def startup_config(tmp_path):
    runtime = tmp_path / "runtime"
    source = Path("config/simulation.toml").read_text().replace(
        'database = "var/data/simulation.sqlite3"', f'database = "{runtime / "gateway.sqlite3"}"'
    )
    return tmp_path / "gateway.toml", runtime, source


def run_gateway_cli(path, check_config, environment=None, extra_args=()):
    env = os.environ.copy()
    for name in ("HABITAT_API_TOKEN", "HABITAT_CLOUD_TOKEN", "HABITAT_MQTT_PASSWORD"):
        env.pop(name, None)
    env.update(environment or {})
    command = [sys.executable, "-m", "habitat_gateway", "--config", str(path)]
    if check_config:
        command.append("--check-config")
    command.extend(extra_args)
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("check_config", [False, True], ids=["start", "check-config"])
@pytest.mark.parametrize("invalid_section", [
    '[cloud]\nendpoint = "https://user:{secret}@example.invalid/sync"\n',
    '[cloud]\nendpoint = "https://example.invalid/sync?token={secret}"\n',
    '[cloud]\ntoken = "{secret}"\n',
    '[mqtt]\npassword = "{secret}"\n',
    '[cloud]\ntoken_env = "{secret}\n',
    '[server]\nhost = "{secret}"\n',
    '[server]\nport = "{secret}"\n',
], ids=["url-userinfo", "url-query", "cloud-token", "mqtt-password", "malformed-toml",
        "server-host", "server-port"])
def test_cli_rejects_invalid_config_without_exposing_input_or_starting(
        startup_config, check_config, invalid_section):
    path, runtime, source = startup_config
    secret = "test-secret-47"
    path.write_text(source.replace("[[cages]]", invalid_section.format(secret=secret) + "\n[[cages]]", 1))

    result = run_gateway_cli(path, check_config)

    assert result.returncode == 2
    assert "invalid_gateway_configuration" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not runtime.exists(), "invalid input must fail before database/lock creation or server startup"


@pytest.mark.parametrize("check_config", [False, True], ids=["start", "check-config"])
def test_cli_unreadable_config_omits_path_and_exits_before_start(tmp_path, check_config):
    secret = "synthetic-private-config-name"
    missing = tmp_path / secret / "gateway.toml"

    result = run_gateway_cli(missing, check_config)

    assert result.returncode == 2
    assert "gateway_configuration_unreadable" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("check_config", [False, True], ids=["start", "check-config"])
@pytest.mark.parametrize("credential_case", ["cloud-token", "cloud-token-env", "mqtt-password-env"])
def test_cli_invalid_credentials_omit_values_and_names_before_start(
        startup_config, check_config, credential_case):
    path, runtime, source = startup_config
    secret = "synthetic-secret"
    if credential_case in ("cloud-token", "cloud-token-env"):
        section = '[cloud]\nenabled = true\nendpoint = "https://example.invalid/sync"\n'
        environment = {"HABITAT_CLOUD_TOKEN": secret}
        if credential_case == "cloud-token-env":
            section += f'token_env = "{secret}"\n'
            environment = {secret: ""}
    else:
        source = source.replace('transport = "simulated"', 'transport = "mqtt"')
        section = f'[mqtt]\npassword_env = "{secret}"\n'
        environment = {"HABITAT_API_TOKEN": "runtime-test-api-token-32-characters", secret: ""}
    path.write_text(source.replace("[[cages]]", section + "\n[[cages]]", 1))

    result = run_gateway_cli(path, check_config, environment)

    assert result.returncode == 2
    assert "invalid_gateway_credentials" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not runtime.exists()


@pytest.mark.parametrize("check_config", [False, True], ids=["start", "check-config"])
@pytest.mark.parametrize("override", [
    ("--host", "synthetic-private-host"),
    ("--port", "synthetic-private-port"),
    ("--port", "0"),
    ("--port", "65536"),
], ids=["host", "port-text", "port-zero", "port-too-large"])
def test_cli_invalid_override_is_redacted_and_does_not_start(startup_config, check_config, override):
    path, runtime, source = startup_config
    path.write_text(source)

    result = run_gateway_cli(path, check_config, extra_args=override)

    assert result.returncode == 2
    assert "invalid_gateway_configuration" in result.stderr
    assert override[1] not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert not runtime.exists()


def test_cli_valid_check_config_preserves_json_without_runtime_writes(startup_config):
    path, runtime, source = startup_config
    path.write_text(source)

    result = run_gateway_cli(path, check_config=True)

    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["valid"] is True
    assert response["site_id"] == "STORE-001"
    assert response["gateway_id"] == "PI-001"
    assert response["transport"] == "simulated"
    assert response["cloud_enabled"] is False
    assert not runtime.exists(), "check-config must not create the runtime directory or database"


@pytest.mark.parametrize("check_config", [False, True])
def test_heartbeat_cli_requires_cloud_without_creating_database(startup_config, check_config):
    path, runtime, source = startup_config
    path.write_text(source)
    result = run_gateway_cli(path, check_config, extra_args=("--heartbeat-only",))
    assert result.returncode == 2
    assert "heartbeat_only_requires_cloud" in result.stderr
    assert not runtime.exists()


def test_heartbeat_config_check_requires_only_cloud_credentials(startup_config):
    path, runtime, source = startup_config
    source = source.replace('transport = "simulated"', 'transport = "mqtt"')
    source = source.replace("[[cages]]", '[cloud]\nenabled = true\nendpoint = "https://example.invalid/sync"\n\n[[cages]]', 1)
    path.write_text(source)
    result = run_gateway_cli(path, True, {"HABITAT_CLOUD_TOKEN": "heartbeat-test-credential-at-least-32-characters"},
                             extra_args=("--heartbeat-only",))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["execution_mode"] == "heartbeat_only"
    assert not runtime.exists()


def test_cli_server_applies_and_expires_simulated_output(tmp_path):
    """Exercise the actual CLI, lifespan worker and HTTP stack using only fake hardware."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config = Path("config/simulation.toml").read_text().replace(
        'database = "var/data/simulation.sqlite3"', f'database = "{tmp_path / "runtime.sqlite3"}"'
    )
    config_path = tmp_path / "runtime.toml"
    config_path.write_text(config)
    environment = os.environ.copy()
    environment.pop("HABITAT_API_TOKEN", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "habitat_gateway", "--config", str(config_path), "--port", str(port)],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 8
            while True:
                assert process.poll() is None, process.stdout.read()
                try:
                    response = client.get("/health")
                    if response.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                assert time.monotonic() < deadline, "server did not become healthy"
                time.sleep(0.1)
            command_id = str(uuid4())
            response = client.post("/v1/cages/CAGE-001/commands", json={
                "request_id": command_id, "actuator_id": "fan", "action": "on", "duration_s": 2,
            })
            assert response.status_code == 202
            deadline = time.monotonic() + 5
            while client.get(f"/v1/commands/{command_id}").json()["status"] != "applied":
                assert time.monotonic() < deadline, "node acknowledgement not received"
                time.sleep(0.1)
            assert client.get("/v1/cages/CAGE-001").json()["actuators"]["fan"]["observed"]["state"] is True
            deadline = time.monotonic() + 5
            while client.get("/v1/cages/CAGE-001").json()["actuators"]["fan"]["observed"]["state"]:
                assert time.monotonic() < deadline, "node output did not expire"
                time.sleep(0.1)
            assert client.get("/health").status_code == 200
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
