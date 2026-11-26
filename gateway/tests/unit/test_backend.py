"""Backend contract checks; these do not claim real GPU reconstruction."""

import struct
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from uuid import uuid4

from habitat.gpu.backend import Backend, BackendError, FROZEN_TRAINING_CONFIG, job_experiment, select_colmap_model
from habitat.gpu.worker import Worker
from habitat.digital_twin.ply import REQUIRED, validate_ply


class BackendTests(unittest.TestCase):
    def frozen_fixture(self, directory):
        root = Path(directory)
        source_id, target_id, capture_id = (str(uuid4()) for _ in range(3))
        source, target = root / "jobs" / source_id, root / "jobs" / target_id
        processed = source / "processed"
        (processed / "images").mkdir(parents=True)
        (processed / "colmap/sparse/1").mkdir(parents=True)
        for i in range(3):
            (processed / "images" / f"frame_{i:05d}.png").write_bytes(b"frozen test image")
        (processed / "colmap/sparse/1/images.bin").write_bytes(struct.pack("<Q", 3))
        (processed / "transforms.json").write_text(json.dumps({"frames": [{}, {}, {}]}))
        config = source / "trained/habitat-preview/splatfacto/run/config.yml"
        config.parent.mkdir(parents=True)
        config.write_bytes(b"machine: {seed: 42}\n")
        metadata = {"selected_colmap_model": "1", "colmap_model_image_counts": {"1": 3},
                    "input_image_count": 3, "preset": {"iterations": 3000, "max_image_dimension": 1280,
                    "resolution_schedule": 500, "num_downscales": 2, "min_registered_fraction": 0.5}}
        (source / "reconstruction.json").write_text(json.dumps(metadata))
        manifest = {"source_job_id": source_id, "capture_id": capture_id,
                    "training_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                    "processed_files": {p.relative_to(processed).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in processed.rglob("*") if p.is_file()}}
        manifest_path = root / "frozen-manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        target.mkdir(parents=True)
        images = root / "captures" / capture_id
        images.mkdir(parents=True)
        experiment = {"source_job_id": source_id, "source_manifest": str(manifest_path),
                      "use_scale_regularization": False}
        return source, target, images, experiment, manifest

    def test_default_training_budget_and_explicit_short_override(self):
        self.assertEqual(Backend({}).preview["iterations"], 30000)
        short = Backend({"preview": {"iterations": 3000}})
        self.assertEqual(short.preview["iterations"], 3000)
        self.assertEqual(short.preview["resolution_schedule"], 500)

    def test_experiment_configuration_is_job_bound_and_strict(self):
        target, source = str(uuid4()), str(uuid4())
        experiment = {"source_job_id": source, "source_manifest": str(Path.cwd() / "manifest.json"),
                      "use_scale_regularization": False}
        config = {"experiments": {target: experiment}}
        self.assertEqual(job_experiment(config, target), experiment)
        self.assertIsNone(job_experiment(config, str(uuid4())))
        for fields in ({"source_job_id": target}, {"source_job_id": "../escape"},
                       {"source_manifest": "relative.json"}, {"use_scale_regularization": "False"},
                       {"arbitrary_cli": "--load-dir"}, {"diagnostics_rois": "relative.json"}):
            with self.subTest(fields=fields), self.assertRaises(BackendError) as error:
                job_experiment({"experiments": {target: {**experiment, **fields}}}, target)
            self.assertEqual(error.exception.code, "invalid_experiment")

    def test_frozen_processed_copy_integrity_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, images, experiment, manifest = self.frozen_fixture(directory)
            backend = Backend({"min_free_disk_bytes": 0})
            metadata, manifest_hash = backend._reuse_processed(experiment, images, target, threading.Event())
            self.assertEqual(metadata["selected_colmap_model"], "1")
            self.assertEqual(manifest_hash, hashlib.sha256(Path(experiment["source_manifest"]).read_bytes()).hexdigest())
            for relative, expected in manifest["processed_files"].items():
                src, dst = source / "processed" / relative, target / "processed" / relative
                self.assertFalse(src.samefile(dst))
                self.assertEqual(hashlib.sha256(dst.read_bytes()).hexdigest(), expected)
                self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), expected)
            (target / "processed/images/frame_00000.png").write_bytes(b"changed copy")
            self.assertEqual((source / "processed/images/frame_00000.png").read_bytes(), b"frozen test image")

    def test_frozen_processed_rejects_corruption_escape_and_wrong_capture(self):
        for problem in ("escape", "hash", "extra", "config", "capture", "copied_hash"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                source, target, images, experiment, manifest = self.frozen_fixture(directory)
                if problem == "escape":
                    manifest["processed_files"]["../outside"] = "a" * 64
                elif problem == "hash":
                    manifest["processed_files"]["images/frame_00000.png"] = "a" * 64
                elif problem == "extra":
                    (source / "processed/extra.txt").write_text("unexpected")
                elif problem == "config":
                    manifest["training_config_sha256"] = "a" * 64
                elif problem == "capture":
                    manifest["capture_id"] = str(uuid4())
                Path(experiment["source_manifest"]).write_text(json.dumps(manifest))
                backend = Backend({"min_free_disk_bytes": 0})
                if problem == "copied_hash":
                    def bad_copy(src, dst):
                        Path(dst).write_bytes(b"bad copy")
                        return dst
                    with patch("habitat.gpu.backend.shutil.copy2", side_effect=bad_copy), self.assertRaises(BackendError):
                        backend._reuse_processed(experiment, images, target, threading.Event())
                else:
                    with self.assertRaises(BackendError):
                        backend._reuse_processed(experiment, images, target, threading.Event())

    @unittest.skipUnless(sys.platform == "linux", "Linux symlink safety")
    def test_frozen_processed_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, images, experiment, _ = self.frozen_fixture(directory)
            image = source / "processed/images/frame_00000.png"
            image.unlink()
            image.symlink_to(source / "processed/images/frame_00001.png")
            with self.assertRaises(BackendError) as error:
                Backend({"min_free_disk_bytes": 0})._reuse_processed(experiment, images, target, threading.Event())
            self.assertEqual(error.exception.code, "invalid_experiment")

    def test_worker_rejects_experiment_scope_or_unfinished_source_before_run(self):
        for change in ({"status": "running"}, {"capture_id": str(uuid4())}, {"site_id": "OTHER"},
                       {"gateway_id": "OTHER"}, {"cage_id": "OTHER"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                _, target, images, experiment, _ = self.frozen_fixture(directory)
                job = {"job_id": target.name, "capture_id": images.name,
                       "site_id": "STORE", "gateway_id": "PI", "cage_id": "CAGE"}
                source = {**job, "job_id": experiment["source_job_id"], "status": "succeeded", **change}
                store = Mock(root=Path(directory))
                store.job.return_value = source
                backend = Mock(config={"experiments": {target.name: experiment}})
                Worker(store, backend).execute(job)
                backend.run.assert_not_called()
                self.assertEqual(store.update_job.call_args.kwargs["error"]["code"], "invalid_experiment")

    def test_frozen_run_keeps_pipeline_and_isolates_training_flags(self):
        for regularization in (False, True):
            with self.subTest(regularization=regularization), tempfile.TemporaryDirectory() as directory:
                _, target, images, experiment, _ = self.frozen_fixture(directory)
                experiment["use_scale_regularization"] = regularization
                backend = Backend({"min_free_disk_bytes": 0, "render_preview": False,
                                   "preview": {"iterations": 123, "resolution_schedule": 999},
                                   "experiments": {target.name: experiment}})
                backend.ready = True
                backend.probe_result = {"versions": {"nerfstudio": "test"}, "cuda_version": "test"}
                calls, stages = [], []
                def command(args, work, phase, cancel, measurements):
                    calls.append((phase, args))
                    if phase == "training_config":
                        (work / "frozen-training-config.yml").write_text("derived test config")
                    elif phase == "training":
                        config = work / "trained/habitat-preview/splatfacto/run/config.yml"
                        config.parent.mkdir(parents=True)
                        config.write_text("test config")
                        (config.parent / "nerfstudio_models").mkdir()
                        (config.parent / "nerfstudio_models/step-000029999.ckpt").write_bytes(b"test checkpoint")
                    elif phase == "exporting":
                        (work / "export").mkdir()
                        (work / "export/splat.ply").write_bytes(b"test export")
                with patch.object(backend, "_command", side_effect=command), patch.object(backend, "_tool", side_effect=lambda name: name), \
                        patch("habitat.gpu.backend.subprocess.run", return_value=subprocess.CompletedProcess([], 0, str(2**40), "")), \
                        patch("habitat.gpu.backend.validate_ply", return_value={"vertex_count": 1}), \
                        patch("habitat.gpu.backend.prepare_images") as prepare:
                    _, metadata = backend.run(images, target, stages.append, threading.Event())
                prepare.assert_not_called()
                self.assertEqual(stages, ["colmap", "training", "exporting"])
                self.assertEqual([phase for phase, _ in calls], ["training_config", "training", "exporting"])
                self.assertEqual(calls[0][1][2], FROZEN_TRAINING_CONFIG)
                self.assertEqual(calls[0][1][-1], str(regularization))
                self.assertEqual(calls[1][1], ["ns-train", "splatfacto", "--load-config", str(target / "frozen-training-config.yml")])
                self.assertEqual(backend.preview["iterations"], 123)
                self.assertEqual(backend.preview["resolution_schedule"], 999)
                self.assertIsNone(job_experiment(backend.config, str(uuid4())))
                self.assertEqual(metadata["experiment"]["use_scale_regularization"], regularization)
                self.assertEqual(metadata["experiment"]["colmap_execution"], "reused")
                self.assertNotIn(directory, json.dumps(metadata))

    def test_memory_sampling_uses_backend_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = Backend({"min_free_disk_bytes": 0})
            measurements = {"stage_seconds": {}}
            with patch("habitat.gpu.backend.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "321\n", "")) as sample:
                backend._command([sys.executable, "-c", "import time; time.sleep(1.2)"], Path(directory),
                                 "sample", threading.Event(), measurements)
            self.assertEqual(sample.call_args.kwargs["env"], backend.env)
            self.assertEqual(measurements["peak_device_vram_bytes"], 321 * 1024**2)
            self.assertIn("/usr/lib/wsl/lib", backend.env["PATH"])

    def test_selects_largest_colmap_model_not_first(self):
        with tempfile.TemporaryDirectory() as directory:
            sparse = Path(directory)
            with self.assertRaises(BackendError):
                select_colmap_model(sparse)
            for name, count in (("0", 2), ("1", 38), ("2", 7)):
                (sparse / name).mkdir()
                (sparse / name / "images.bin").write_bytes(struct.pack("<Q", count))
            selected, counts = select_colmap_model(sparse)
            self.assertEqual(selected, sparse / "1")
            self.assertEqual(counts, {"0": 2, "1": 38, "2": 7})
            (sparse / "2" / "images.bin").write_bytes(b"short")
            with self.assertRaises(BackendError):
                select_colmap_model(sparse)

    @unittest.skipUnless(sys.platform == "linux", "Linux process-group supervision")
    def test_probe_timeout_kills_descendant_ignoring_sigterm(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "probe.pid"
            code = ("import os,time,signal,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)")
            backend = Backend({"probe_timeout_seconds": 0.5})
            with patch.object(backend, "_tool", return_value=sys.executable), patch("habitat.gpu.backend.PROBE", code):
                self.assertFalse(backend.probe())
            self.assertEqual(backend.probe_error, "TimeoutExpired")
            stat = Path(f"/proc/{int(pid_path.read_text())}/stat")
            deadline = time.monotonic() + 2
            while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(not stat.exists() or stat.read_text().split()[2] == "Z")

    @unittest.skipUnless(sys.platform == "linux", "Linux process-group supervision")
    def test_timeout_kills_descendant_ignoring_sigterm(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "child.pid"
            code = ("import os,time,signal,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)")
            backend = Backend({"min_free_disk_bytes": 0, "stage_timeout_seconds": {"test": 0.2}})
            with self.assertRaises(BackendError):
                backend._command([sys.executable, "-c", code], Path(directory), "test", threading.Event(), {"stage_seconds": {}})
            stat = Path(f"/proc/{int(pid_path.read_text())}/stat")
            deadline = time.monotonic() + 2
            while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(not stat.exists() or stat.read_text().split()[2] == "Z")

    @unittest.skipUnless(sys.platform == "linux", "Linux process-group supervision")
    def test_api_crash_kills_subprocess_group(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "child.pid"
            child = f"import os,time,pathlib; pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)"
            runner = ("from habitat.gpu.backend import Backend; from pathlib import Path; import threading,sys; "
                      f"Backend({{'min_free_disk_bytes':0}})._command([sys.executable,'-c',{child!r}], "
                      f"Path({directory!r}), 'crash', threading.Event(), {{'stage_seconds':{{}}}})")
            api = subprocess.Popen([sys.executable, "-c", runner])
            try:
                deadline = time.monotonic() + 10
                while not pid_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(pid_path.exists())
                child_pid = int(pid_path.read_text())
                api.kill()
                api.wait(timeout=5)
                stat = Path(f"/proc/{child_pid}/stat")
                deadline = time.monotonic() + 5
                while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(not stat.exists() or stat.read_text().split()[2] == "Z")
            finally:
                if api.poll() is None:
                    api.kill()
                api.wait(timeout=5)

    def test_gaussian_payload_formats_and_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.ply"
            names = sorted(REQUIRED)
            properties = "".join(f"property float {name}\n" for name in names)
            for encoding, endian in (("ascii", ""), ("binary_little_endian", "<"), ("binary_big_endian", ">")):
                header = f"ply\nformat {encoding} 1.0\nelement vertex 1\n{properties}end_header\n".encode()
                payload = (" ".join(["0"] * len(names)) + "\n").encode() if not endian else struct.pack(endian + "f" * len(names), *([0.] * len(names)))
                path.write_bytes(header + payload)
                self.assertEqual(validate_ply(path)["vertex_count"], 1)
                path.write_bytes(header + payload + b"extra")
                with self.assertRaises(ValueError):
                    validate_ply(path)
                path.write_bytes(header + (b"nan " * len(names) + b"\n" if not endian else struct.pack(endian + "f" * len(names), *([float("nan")] * len(names)))))
                with self.assertRaises(ValueError):
                    validate_ply(path)
            path.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n0\n")
            with self.assertRaises(ValueError):
                validate_ply(path)

    def test_binary_gaussian_validation_checks_every_chunk_and_scalar(self):
        # A uint whose bits encode float NaN is still a valid integer.
        properties = [("double" if i % 2 else "float", name, "d" if i % 2 else "f", -0.5)
                      for i, name in enumerate(sorted(REQUIRED))]
        properties += [("uint", "label", "I", 0x7fc00000), ("double", "extra", "d", 1e200)]
        values = [value for _, _, _, value in properties]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.ply"
            for encoding, endian in (("binary_little_endian", "<"), ("binary_big_endian", ">")):
                header = (f"ply\nformat {encoding} 1.0\nelement vertex 4097\n"
                          + "".join(f"property {kind} {name}\n" for kind, name, _, _ in properties)
                          + "end_header\n").encode()
                layout = struct.Struct(endian + "".join(code for _, _, code, _ in properties))
                payload = layout.pack(*values) * 4097
                path.write_bytes(header + payload)
                self.assertEqual(validate_ply(path), {
                    "encoding": encoding, "vertex_count": 4097,
                    "properties": [name for _, name, _, _ in properties],
                    "size_bytes": len(header) + len(payload),
                })
                for vertex, field in ((0, 0), (4095, len(values) - 1), (4096, len(values) - 1)):
                    for invalid in (float("nan"), float("inf"), float("-inf")):
                        with self.subTest(encoding=encoding, vertex=vertex, field=field, invalid=invalid):
                            bad_values, corrupted = values.copy(), bytearray(payload)
                            bad_values[field] = invalid
                            layout.pack_into(corrupted, vertex * layout.size, *bad_values)
                            path.write_bytes(header + corrupted)
                            with self.assertRaisesRegex(ValueError, "Non-finite vertex value"):
                                validate_ply(path)
                path.write_bytes(header + payload[:-1])
                with self.assertRaisesRegex(ValueError, "PLY vertex payload length mismatch"):
                    validate_ply(path)

    def test_unconfigured_cannot_run(self):
        backend = Backend({})
        self.assertFalse(backend.health()["gpu"]["reconstruction_ready"])
        with self.assertRaises(BackendError) as error:
            backend.run(Path("."), Path("."), lambda stage: None, threading.Event())
        self.assertEqual(error.exception.code, "backend_not_ready")

    def test_gpu_loss_and_low_memory_preflight(self):
        backend = Backend({})
        backend.ready = True
        backend.probe_result = {"name": "Previously available GPU"}
        with patch("habitat.gpu.backend.subprocess.run", side_effect=subprocess.CalledProcessError(1, "probe")):
            with self.assertRaises(BackendError) as error:
                backend.run(Path("."), Path("."), lambda stage: None, threading.Event())
            self.assertEqual(error.exception.code, "gpu_unavailable")
            self.assertFalse(backend.health()["gpu"]["reconstruction_ready"])
            self.assertFalse(backend.health()["gpu"]["cuda_available"])
        backend.ready = True
        with patch("habitat.gpu.backend.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "0\n", "")):
            with self.assertRaises(BackendError) as error:
                backend.run(Path("."), Path("."), lambda stage: None, threading.Event())
            self.assertEqual(error.exception.code, "gpu_out_of_memory")

    def test_subprocess_failure_deadline_cancel_and_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            backend = Backend({"min_free_disk_bytes": 0, "stage_timeout_seconds": {"test": 0.05}})
            cases = [("raise RuntimeError('CUDA out of memory')", "gpu_out_of_memory", threading.Event()),
                     ("import time; time.sleep(30)", "timeout", threading.Event())]
            cancelled = threading.Event()
            cancelled.set()
            cases.append(("import time; time.sleep(30)", "interrupted", cancelled))
            for code, expected, cancel in cases:
                with self.assertRaises(BackendError) as error:
                    backend._command([sys.executable, "-c", code], path, "test", cancel, {"stage_seconds": {}})
                self.assertEqual(error.exception.code, expected)
            backend.config["min_free_disk_bytes"] = 2**100
            with self.assertRaises(BackendError) as error:
                backend._disk_check(path)
            self.assertEqual(error.exception.code, "storage_unavailable")


if __name__ == "__main__":
    unittest.main()
