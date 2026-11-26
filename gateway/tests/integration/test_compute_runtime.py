"""Real Pi CLIs + loopback HTTP; all images, GPU results and cage nodes are synthetic."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
from PIL import Image

from tests.contract.compute_stub import ComputeStub, TEST_TOKEN


def test_compute_timeout_restart_and_local_control_cloud_isolation(tmp_path):
    peer = ComputeStub()
    health_entered, release_health, cloud_received = (threading.Event() for _ in range(3))

    class Receiver(BaseHTTPRequestHandler):
        def handle_request(self):
            content = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/v1/edge/sync":
                body = json.loads(content)
                response = httpx.Response(200, json={"schema_version": 1,
                    "site_id": body["site_id"], "gateway_id": body["gateway_id"],
                    "accepted_event_ids": [event["event_id"] for event in body["events"]]})
                cloud_received.set()
            else:
                if self.path == "/v1/gpu/health" and not release_health.is_set():
                    health_entered.set()
                    release_health.wait(5)
                request = httpx.Request(self.command, "http://127.0.0.1" + self.path,
                                        headers=dict(self.headers), content=content)
                response = peer(request)
            self.send_response(response.status_code)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(response.content)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The timeout is intentional.

        do_GET = do_POST = do_PUT = handle_request

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        gateway_port = listener.getsockname()[1]
    original = Path("config/simulation.toml").read_text().replace(
        'database = "var/data/simulation.sqlite3"', f'database = "{tmp_path / "gateway.sqlite3"}"')
    prefix, cages = original.split("[[cages]]", 1)
    gateway_config = tmp_path / "gateway.toml"
    gateway_config.write_text(prefix + f'''[cloud]
enabled = true
endpoint = "http://127.0.0.1:{server.server_port}/v1/edge/sync"
interval_s = 1
retry_max_s = 1
[[cages]]''' + cages)
    config = tmp_path / "compute.toml"
    config.write_text(f'''enabled = true
base_url = "http://127.0.0.1:{server.server_port}"
storage_dir = "{tmp_path / "compute"}"
timeout_s = 1
poll_interval_s = 0.1
retry_max_s = 1
''')
    photos = tmp_path / "photos"
    photos.mkdir()
    for i in range(3):
        Image.new("RGB", (8, 8), (i, i, i)).save(photos / f"test-{i}.png")
    environment = {**os.environ, "HABITAT_GPU_TOKEN": TEST_TOKEN, "HABITAT_CLOUD_TOKEN": TEST_TOKEN}
    environment.pop("HABITAT_API_TOKEN", None)
    command = [sys.executable, "-m", "apps.worker", "--config", str(config),
               "--gateway-config", str(gateway_config)]

    def cli(*args):
        result = subprocess.run([*command, *args], env=environment, capture_output=True, text=True, timeout=15)
        assert TEST_TOKEN not in result.stdout + result.stderr
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    def stop(process):
        if process and process.poll() is None:
            process.terminate()
        if process:
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate(timeout=5)
            assert TEST_TOKEN not in output

    gateway = worker = None
    try:
        task = cli("enqueue", "--cage-id", "CAGE-001", "--folder", str(photos),
                   "--captured-at", "2026-09-19T12:00:00+09:00")
        gateway = subprocess.Popen([sys.executable, "-m", "habitat_gateway", "--config", str(gateway_config),
            "--port", str(gateway_port)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", trust_env=False, timeout=2) as client:
            deadline = time.monotonic() + 10
            while True:
                assert gateway.poll() is None
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.05)
            worker = subprocess.Popen([*command, "work", "--once"], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert health_entered.wait(5)
            cloud_received.clear()
            request_id = str(uuid4())
            response = client.post("/v1/cages/CAGE-001/commands", json={"request_id": request_id,
                "actuator_id": "fan", "action": "on", "duration_s": 2})
            assert response.status_code == 202
            deadline = time.monotonic() + 5
            while client.get(f"/v1/commands/{request_id}").json()["status"] != "applied":
                assert time.monotonic() < deadline
                time.sleep(0.05)
            assert cloud_received.wait(3)
            output, _ = worker.communicate(timeout=5)
            assert worker.returncode == 0 and TEST_TOKEN not in output
            assert cli("show", task["job_id"])["error"] == "compute_timeout"
            assert client.get("/health").status_code == 200
            release_health.set()
            cli("retry", task["job_id"])
            assert cli("work", "--once")[0]["state"] == "waiting"
            time.sleep(0.15)
            assert cli("work", "--once")[0]["state"] == "complete"
            result = cli("show", task["job_id"])
            assert result["capture_id"] == task["capture_id"]
            assert list(peer.jobs) == [task["job_id"]]
            assert set(peer.upload_count.values()) == {1}
            artifact = tmp_path / "compute/artifacts" / task["job_id"] / f"{peer.artifact_id}.ply"
            assert artifact.read_bytes() == peer.artifact
            assert client.get("/health").status_code == 200
    finally:
        release_health.set()
        stop(worker)
        stop(gateway)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
