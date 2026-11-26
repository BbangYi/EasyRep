"""Real CLI + loopback HTTP receiver; no cloud service or physical device is contacted."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

import httpx
import pytest

from habitat_gateway.sync_contract import SYNC_PATH, SyncRequest
from habitat_gateway.store import Store
from tests.conftest import confirm_empty_cloud


def test_three_cages_retry_after_process_restart(tmp_path):
    allow_ack = threading.Event()
    received = set()
    observed_cages = set()
    observation_lock = threading.Lock()
    token = "runtime-cloud-test-token-32-characters"

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path != "/v1/edge/sync" or self.headers.get("Authorization") != f"Bearer {token}":
                self.send_response(401)
                self.end_headers()
                return
            if not allow_ack.is_set():
                self.send_response(503)
                self.end_headers()
                return
            with observation_lock:
                received.update(e["event_id"] for e in payload["events"])
                observed_cages.update(c["state"]["cage_id"] for c in payload["gateway"]["cages"])
            body = json.dumps({
                "schema_version": 1, "site_id": payload["site_id"], "gateway_id": payload["gateway_id"],
                "accepted_event_ids": [e["event_id"] for e in payload["events"]],
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    database = tmp_path / "gateway.sqlite3"
    store = Store(str(database), event_identity=("STORE-001", "PI-001"))
    try:
        confirm_empty_cloud(store)  # This test created the empty loopback receiver above.
    finally:
        store.close()
    prefix, cage = Path("config/simulation.toml").read_text().split("[[cages]]", 1)
    prefix = prefix.replace('database = "var/data/simulation.sqlite3"', f'database = "{database}"')
    cloud = f'''[cloud]
enabled = true
endpoint = "http://127.0.0.1:{server.server_port}/v1/edge/sync"
interval_s = 1
retry_max_s = 1
'''
    config = tmp_path / "three-cages.toml"
    config.write_text(prefix + cloud + "\n" + "\n".join(
        "[[cages]]" + cage.replace("CAGE-001", f"CAGE-{i:03d}").replace("ESP32-001", f"ESP32-{i:03d}")
        for i in range(1, 4)
    ))
    environment = os.environ.copy()
    environment.pop("HABITAT_API_TOKEN", None)
    environment["HABITAT_CLOUD_TOKEN"] = token

    def start():
        return subprocess.Popen(
            [sys.executable, "-m", "habitat_gateway", "--config", str(config), "--port", str(port)],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def stop(process):
        process.terminate()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=5)
        assert token not in output

    def wait_for(client, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            assert process.poll() is None, "gateway process exited unexpectedly"
            try:
                status = client.get("/v1/cloud").json()
                if predicate(status):
                    return status
            except httpx.ConnectError:
                pass
            time.sleep(0.05)
        raise AssertionError("cloud state did not converge")

    process = start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as client:
            status = wait_for(client, lambda s: s["last_error"] == "http_503")
            assert status["pending_events"] >= 3
            assert client.get("/health").status_code == 200
            stop(process)
            with sqlite3.connect(database) as db:
                pending = {r[0] for r in db.execute("SELECT event_id FROM cloud_outbox")}
            assert len(pending) >= 3
            allow_ack.set()
            process = start()
            wait_for(client, lambda s: s["last_success_at"] is not None)
            with observation_lock:
                assert pending <= received
                assert observed_cages == {"CAGE-001", "CAGE-002", "CAGE-003"}
            assert client.get("/health").status_code == 200
    finally:
        if process.poll() is None:
            stop(process)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_heartbeat_cli_retries_and_restarts_without_sensors_api_or_database(tmp_path):
    token = "heartbeat-runtime-test-credential-32-characters"
    received = []
    attempts = []
    enough = threading.Event()
    target_count = 3

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != SYNC_PATH or self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(401)
                return
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            attempts.append(payload)
            if len(attempts) == 1:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            received.append(payload)
            body = json.dumps({"schema_version":1,"site_id":payload["site_id"],
                               "gateway_id":payload["gateway_id"],"accepted_event_ids":[]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if len(received) >= target_count:
                enough.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"existing runtime database must remain untouched")
    original = database.read_bytes()
    source = Path("config/simulation.toml").read_text().replace('transport = "simulated"', 'transport = "mqtt"')
    source = source.replace('database = "var/data/simulation.sqlite3"', f'database = "{database}"')
    source = source.replace("[[cages]]", f'[cloud]\nenabled = true\nendpoint = "http://127.0.0.1:{server.server_port}{SYNC_PATH}"\ninterval_s = 1\nretry_max_s = 1\n\n[[cages]]', 1)
    config = tmp_path / "heartbeat.toml"
    config.write_text(source)
    environment = {k:v for k,v in os.environ.items() if k not in ("HABITAT_API_TOKEN", "HABITAT_CLOUD_TOKEN", "HABITAT_MQTT_PASSWORD")}
    environment["HABITAT_CLOUD_TOKEN"] = token
    log = tmp_path / "runtime.log"
    process = None
    try:
        with log.open("w+") as stream:
            for target_count in (3, 5):
                enough.clear()
                # An occupied API port also proves heartbeat mode does not start Uvicorn.
                process = subprocess.Popen([sys.executable, "-m", "habitat_gateway", "--config", str(config),
                                            "--heartbeat-only", "--port", str(server.server_port)],
                                           env=environment, stdout=stream, stderr=subprocess.STDOUT)
                assert enough.wait(12), "heartbeat sender did not recover and continue"
                assert process.poll() is None
                process.terminate()
                process.wait(timeout=5)
        for payload in attempts:
            SyncRequest.model_validate(payload)
            assert payload["events"] == []
            assert payload["gateway"]["healthy"] is True
            assert all(c["state"]["telemetry"] is None and not c["state"]["transport_connected"]
                       for c in payload["gateway"]["cages"])
        assert len({p["sent_at"] for p in received}) == len(received)
        assert database.read_bytes() == original
        assert not Path(str(database) + ".lock").exists()
        output = log.read_text()
        assert "http_503" in output and "Cloud heartbeat acknowledged" in output
        assert token not in output
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("accepted", [True, False], ids=["matching-ack", "wrong-pi-ack"])
def test_check_connection_exits_with_verified_result_and_never_opens_device_db(tmp_path, accepted):
    token = "test-one-shot-connection-token-32-characters"
    requests = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(401)
                return
            body = json.dumps({"schema_version":1,"site_id":payload["site_id"],
                               "gateway_id":payload["gateway_id"] if accepted else "OTHER-PI",
                               "accepted_event_ids":[]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    database = tmp_path / "existing.sqlite3"
    original = b"Existing device history remains untouched."
    database.write_bytes(original)
    source = Path("config/simulation.toml").read_text().replace('transport = "simulated"', 'transport = "mqtt"')
    source = source.replace('database = "var/data/simulation.sqlite3"', f'database = "{database}"')
    source = source.replace("[[cages]]", f'[cloud]\nenabled = true\nendpoint = "http://127.0.0.1:{server.server_port}{SYNC_PATH}"\n\n[[cages]]', 1)
    config = tmp_path / "gateway.toml"
    config.write_text(source)
    environment = {k:v for k,v in os.environ.items() if k not in ("HABITAT_API_TOKEN", "HABITAT_CLOUD_TOKEN", "HABITAT_MQTT_PASSWORD")}
    environment["HABITAT_CLOUD_TOKEN"] = token
    try:
        result = subprocess.run([sys.executable,"-m","habitat_gateway","--config",str(config),"--check-connection"],
                                env=environment,capture_output=True,text=True,timeout=15)
        assert result.returncode == (0 if accepted else 1)
        reply = json.loads(result.stdout)
        assert reply["connected"] is accepted
        assert reply["error"] == (None if accepted else "ack_mismatch")
        assert len(requests) == 1
        SyncRequest.model_validate(requests[0])
        assert requests[0]["events"] == []
        assert requests[0]["gateway"]["healthy"] is True
        assert all(c["state"]["telemetry"] is None and not c["state"]["transport_connected"]
                   for c in requests[0]["gateway"]["cages"])
        assert token not in result.stdout + result.stderr
        assert database.read_bytes() == original
        assert not Path(str(database)+".lock").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
