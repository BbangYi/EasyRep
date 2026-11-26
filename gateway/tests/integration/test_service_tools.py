"""Desktop service/verifier regressions using synthetic HTTP data, never real GPU evidence."""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator

from test_api import API, APIHarness, SYNTHETIC_PLY, SyntheticBackend
from scripts import verify_reconstruction as verifier


class ServiceToolsTests(APIHarness):
    def verifier_args(self, live):
        images = self.config.storage_dir / "verifier-input"
        images.mkdir(exist_ok=True)
        for index in range(3):
            (images / f"synthetic-{index}.png").write_bytes(self.image)
        record = self.config.storage_dir / "verification" / "record.json"
        return ["verify_reconstruction", "--base-url", f"http://127.0.0.1:{live.port}",
                "--images", str(images), "--record", str(record),
                "--captured-at", "2026-09-20T00:00:00+00:00"], record

    def invoke_verifier(self, args):
        output = io.StringIO()
        # Speed up polling without changing the server thread's actual time module.
        clock = SimpleNamespace(sleep=lambda _: time.sleep(0.01), monotonic=time.monotonic, time=time.time)
        with patch.object(sys, "argv", args), patch.dict(os.environ, {"HABITAT_GPU_TOKEN": self.token}), \
                patch.object(verifier, "time", clock), redirect_stdout(output):
            verifier.main()
        self.assertTrue(self.token not in output.getvalue(), "Verifier printed a credential")
        return output.getvalue()

    def test_verifier_download_and_resume_keep_uuid_and_do_not_rerun(self):
        backend = SyntheticBackend()
        live, _ = self.start(backend)
        args, record_path = self.verifier_args(live)
        self.invoke_verifier(args)
        first = json.loads(record_path.read_text())
        self.assertTrue(first["download_verified"])
        self.assertEqual(first["pi_to_gpu"], "not_run")
        self.assertEqual(Path(first["downloaded_artifact"]).read_bytes(), SYNTHETIC_PLY)
        self.assertEqual(first["ply"]["vertex_count"], 1)
        self.invoke_verifier(args)
        repeated = json.loads(record_path.read_text())
        self.assertEqual(repeated["job"]["job_id"], first["job"]["job_id"])
        self.assertEqual(repeated["manifest"]["capture_id"], first["manifest"]["capture_id"])
        self.assertEqual(backend.calls, 1)
        image = self.config.storage_dir / "verifier-input/synthetic-0.png"
        image.write_bytes(b"changed input")
        with self.assertRaisesRegex(RuntimeError, "Input changed"):
            self.invoke_verifier(args)
        self.assertEqual(backend.calls, 1)
        self.assertTrue(self.token not in record_path.read_text(), "Saved verification contains a credential")

    def test_verifier_rejects_redirect_without_forwarding_credentials(self):
        calls = []

        def respond(request):
            calls.append(request.url.host)
            return httpx.Response(307, headers={"Location": "https://must-not-contact.invalid/v1/gpu/health"})

        client = httpx.Client(transport=httpx.MockTransport(respond), base_url="https://desktop.invalid",
                             follow_redirects=False)
        self.addCleanup(client.close)
        with patch.object(verifier.httpx, "Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "HTTP 307"):
                self.invoke_verifier(["verify_reconstruction", "--base-url", "https://desktop.invalid", "--health-only"])
        self.assertEqual(calls, ["desktop.invalid"])

    def test_verifier_rejects_mismatched_capture_and_file_receipt(self):
        live, _ = self.start()
        args, _ = self.verifier_args(live)
        original_request = httpx.Client.request
        for target in ("capture", "receipt"):
            with self.subTest(response=target):
                def altered_request(client, method, url, **kwargs):
                    response = original_request(client, method, url, **kwargs)
                    matches = (target == "capture" and method == "POST" and str(url) == f"{API}/captures") or (
                        target == "receipt" and method == "PUT")
                    if matches and response.status_code == 200:
                        body = response.json()
                        body["capture_id"] = str(uuid4())
                        return httpx.Response(200, json=body, request=response.request)
                    return response

                with patch.object(httpx.Client, "request", altered_request):
                    with self.assertRaises((RuntimeError, ValueError)):
                        self.invoke_verifier(args)

    def test_verifier_poll_deadline_preserves_uuid_record_for_retry(self):
        live, _ = self.start(SyntheticBackend("block"))
        args, record_path = self.verifier_args(live)
        with self.assertRaisesRegex(RuntimeError, "Polling deadline exceeded"):
            self.invoke_verifier(args + ["--wait-seconds", "0"])
        record = json.loads(record_path.read_text())
        self.assertTrue(record["job"]["job_id"])
        self.assertIn(record["last_status"]["status"], {"queued", "running"})
        self.assertFalse(record.get("download_verified", False))

    def test_verifier_rejects_download_over_limit_or_content_hash_mismatch(self):
        live, _ = self.start()
        args, record_path = self.verifier_args(live)
        with self.assertRaisesRegex(RuntimeError, "download limit"):
            self.invoke_verifier(args + ["--max-artifact-bytes", "1"])
        original_stream = httpx.Client.stream

        @contextmanager
        def altered_stream(client, method, url, **kwargs):
            with original_stream(client, method, url, **kwargs) as response:
                corrupted = SYNTHETIC_PLY[:-1] + b"x"
                with patch.object(response, "iter_raw", return_value=iter((corrupted,))):
                    yield response

        with patch.object(httpx.Client, "stream", altered_stream):
            with self.assertRaisesRegex(RuntimeError, "Artifact content differs"):
                self.invoke_verifier(args)
        self.assertFalse(json.loads(record_path.read_text()).get("download_verified", False))

    def test_cli_configuration_error_does_not_print_secret_or_config_input(self):
        config = self.config.storage_dir / "invalid.toml"
        private_marker = "DO_NOT_ECHO_CONFIG_INPUT"
        config.write_text(f'unknown_setting = "{private_marker}"\n', encoding="utf-8")
        env_file = self.config.storage_dir / "gpu.env"
        env_file.write_text("HABITAT_GPU_TOKEN=" + self.token + "\n", encoding="utf-8")
        process = subprocess.run([sys.executable, "-m", "apps.api", "--config", str(config),
                                  "--env-file", str(env_file), "--check-config"],
                                 capture_output=True, text=True, timeout=20,
                                 cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stderr.strip(), "invalid_gpu_configuration_or_credentials")
        self.assertTrue(self.token not in process.stdout + process.stderr, "CLI printed a credential")
        self.assertNotIn(private_marker, process.stdout + process.stderr)

    def test_verifier_rejects_malformed_secret_before_constructing_http_client(self):
        self.token += "\r\nPRIVATE_VALUE"
        with patch.object(verifier.httpx, "Client") as client:
            with self.assertRaises(RuntimeError) as failure:
                self.invoke_verifier(["verify_reconstruction", "--base-url", "https://desktop.invalid", "--health-only"])
            client.assert_not_called()
        self.assertTrue(self.token not in str(failure.exception), "Invalid token appeared in error text")

    def test_openapi_error_schemas_match_actual_http_responses(self):
        backend = SyntheticBackend(ready=False, backend="not_configured")
        _, client = self.start(backend)
        spec = self.checked(client.get("/openapi.json"), 200)
        self.error(client.get("/openapi.json", headers={"Authorization": ""}), 401)
        self.assertEqual(spec["info"]["version"], "1.0.0")
        for path, methods in spec["paths"].items():
            for method, operation in methods.items():
                self.assertTrue(operation["security"], f"Missing auth in {method} {path}")
                for status in (400, 401, 403, 404, 409, 413, 422, 429, 503):
                    definition = operation["responses"][str(status)]["content"]["application/json"]["schema"]
                    self.assertEqual(definition, {"$ref": "#/components/schemas/ErrorResponse"})
        manifest = self.manifest()
        self.checked(client.post(f"{API}/captures", json=manifest), 200)
        samples = [
            ("/v1/gpu/health", "get", client.get(f"{API}/health", headers={"Authorization": ""})),
            ("/v1/gpu/captures", "post", client.post(f"{API}/captures", json={**manifest, "cage_id": "OTHER"})),
            ("/v1/gpu/captures/{capture_id}", "get", client.get(f"{API}/captures/{uuid4()}")),
            ("/v1/gpu/jobs", "post", client.post(f"{API}/jobs", json=self.request(manifest))),
            ("/v1/gpu/captures", "post", client.post(f"{API}/captures", content=b" " * (1024 * 1024 + 1))),
            ("/v1/gpu/captures", "post", client.post(f"{API}/captures", json={})),
        ]
        self.upload(client, manifest)
        samples.append(("/v1/gpu/jobs", "post", client.post(f"{API}/jobs", json=self.request(manifest))))
        self.assertEqual({response.status_code for _, _, response in samples}, {401, 403, 404, 409, 413, 422, 503})
        for path, method, response in samples:
            schema = spec["paths"][path][method]["responses"][str(response.status_code)]["content"]["application/json"]["schema"]
            Draft202012Validator({**schema, "components": spec["components"]}).validate(response.json())

    @unittest.skipUnless(os.name == "posix", "systemd provisioning is Linux-only")
    def test_provisioning_quotes_paths_uses_home_defaults_and_preserves_secret(self):
        from scripts import provision_service as provision

        self.assertEqual(provision.unit_quote('/tmp/a b/"x"/%/\\'), '"/tmp/a b/\\"x\\"/%%/\\\\"')
        for value in ("newline\npath", "carriage\rpath", "nul\0path"):
            with self.assertRaises(ValueError):
                provision.unit_quote(value)
        account_home = self.config.storage_dir / "service home"
        account = SimpleNamespace(pw_dir=str(account_home), pw_uid=os.getuid(), pw_gid=os.getgid())
        unit_path = self.config.storage_dir / "habitat-gpu.service"
        api_python, gpu_python = account_home / "api env/bin/python", account_home / "gpu env/bin/python"
        real_path = Path

        def path(value):
            return unit_path if str(value) == "/etc/systemd/system/habitat-gpu.service" else real_path(value)

        args = ["provision_service", "--user", "service-test", "--api-python", str(api_python), "--gpu-python", str(gpu_python)]
        with patch.object(provision, "Path", side_effect=path), patch.object(provision.pwd, "getpwnam", return_value=account), \
                patch.object(provision.os, "geteuid", return_value=0), patch.object(provision.os, "chown"), \
                patch.object(provision.subprocess, "run") as run, patch.object(sys, "argv", args), \
                redirect_stdout(io.StringIO()):
            provision.main()
            env_file = account_home / ".config/habitat-gpu/gpu.env"
            original_secret = env_file.read_bytes()
            provision.main()
            self.assertTrue(env_file.read_bytes() == original_secret, "Provisioning replaced an existing token")
        config_path = account_home / ".config/habitat-gpu/gpu.toml"
        config = tomllib.loads(config_path.read_text())
        self.assertEqual(config["storage_dir"], str(account_home / ".local/share/habitat-gpu/service"))
        self.assertEqual(config["backend"]["python"], str(gpu_python))
        self.assertEqual((config["host"], config["port"]), ("127.0.0.1", 8100))
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
        self.assertIn(f"ExecStart={provision.unit_quote(api_python)}", unit_path.read_text())
        self.assertEqual(run.call_args_list[-1].args[0], ["systemctl", "enable", "habitat-gpu.service"])


if __name__ == "__main__":
    unittest.main()
