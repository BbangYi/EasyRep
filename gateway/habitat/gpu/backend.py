"""One bounded COLMAP → Splatfacto → Gaussian PLY subprocess pipeline."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import UUID

from habitat.digital_twin.ply import validate_ply


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class DiagnosticIntegrityError(BackendError):
    def __init__(self, message: str):
        super().__init__("input_corrupt", message)


def job_experiment(config: dict, job_id: str) -> dict | None:
    """Experiments are server-owned and bound to one exact, new job UUID."""
    experiments = config.get("experiments", {})
    if not isinstance(experiments, dict):
        raise BackendError("invalid_experiment", "Invalid server experiment configuration")
    if job_id not in experiments:
        return None
    experiment = experiments[job_id]
    try:
        if not isinstance(experiment, dict) or set(experiment) - {
            "source_job_id", "source_manifest", "use_scale_regularization", "diagnostics_rois"
        }:
            raise ValueError
        source = experiment["source_job_id"]
        if str(UUID(job_id)) != job_id or str(UUID(source)) != source or source == job_id:
            raise ValueError
        if type(experiment["use_scale_regularization"]) is not bool:
            raise ValueError
        for field in ("source_manifest", "diagnostics_rois"):
            if field == "source_manifest" or field in experiment:
                if not isinstance(experiment[field], str) or not Path(experiment[field]).is_absolute():
                    raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise BackendError("invalid_experiment", "Invalid server experiment configuration") from None
    return dict(experiment)


def select_colmap_model(sparse_dir: Path) -> tuple[Path, dict[str, int]]:
    """COLMAP numbers models by discovery order, not registration quality."""
    counts = {}
    for images in sorted(sparse_dir.glob("*/images.bin")):
        with images.open("rb") as source:
            header = source.read(8)
        if len(header) != 8:
            raise BackendError("colmap_failed", "COLMAP model has an invalid image-count header")
        counts[images.parent.name] = struct.unpack("<Q", header)[0]
    if not counts:
        raise BackendError("colmap_failed", "COLMAP did not produce a sparse reconstruction")
    selected = max(counts, key=counts.get)
    return sparse_dir / selected, counts


def prepare_images(images_dir: Path, output_dir: Path, max_dimension: int,
                   cancel: threading.Event | None = None) -> int:
    """Use the same documented RGB/downscale preparation for jobs and sample data."""
    from PIL import Image, ImageOps
    images = sorted(p for p in Path(images_dir).iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    if len(images) < 3:
        raise BackendError("invalid_input", "At least three RGB photographs are required")
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, source in enumerate(images):
        if cancel is not None and cancel.is_set():
            raise BackendError("interrupted", "Reconstruction stopped with the service")
        with Image.open(source) as original:
            resized = ImageOps.exif_transpose(original).convert("RGB")
            resized.thumbnail((max_dimension,) * 2, Image.Resampling.LANCZOS)
            resized.save(output_dir / f"frame_{i:05d}.png")
    return len(images)


PROBE = r'''
import importlib.metadata as m, json, torch
assert torch.cuda.is_available(), "CUDA is unavailable"
a = torch.arange(16, device="cuda", dtype=torch.float32).reshape(4,4)
assert torch.allclose(a @ torch.eye(4,device="cuda"), a)
from nerfstudio.models.splatfacto import SplatfactoModel
from gsplat import rasterization
means = torch.tensor([[0.,0.,2.]],device="cuda",requires_grad=True)
rgb, alpha, _ = rasterization(means, torch.tensor([[1.,0.,0.,0.]],device="cuda"),
    torch.full((1,3),0.1,device="cuda"), torch.ones(1,device="cuda")*0.5,
    torch.ones((1,3),device="cuda"), torch.eye(4,device="cuda")[None],
    torch.tensor([[[16.,0.,8.],[0.,16.,8.],[0.,0.,1.]]],device="cuda"),16,16)
rgb.sum().backward()
torch.cuda.synchronize()
assert torch.isfinite(rgb).all() and means.grad is not None
print(json.dumps({"name":torch.cuda.get_device_name(0),
 "vram_total_bytes":torch.cuda.get_device_properties(0).total_memory,
 "vram_free_bytes":torch.cuda.mem_get_info()[0], "cuda_version":torch.version.cuda,
 "versions":{name:m.version(name) for name in ("torch","torchvision","nerfstudio","gsplat")},
 "cuda_matrix_check":True,"gsplat_forward_backward_check":True}))
'''


# Parse the trusted, hash-verified native configuration in its GPU environment.
# ns-train replaces CLI overrides when --load-config is provided.
FROZEN_TRAINING_CONFIG = r'''
import os, sys, yaml
from pathlib import Path
source, target, data, output = map(Path, sys.argv[1:5])
regularization = sys.argv[5]
if regularization not in ("True", "False"):
    raise ValueError("invalid experiment regularization")
config = yaml.load(source.read_text(), Loader=yaml.Loader)
if (config.method_name != "splatfacto" or config.machine.seed != 42
    or config.experiment_name != "habitat-preview" or config.timestamp != "run"
    or any(getattr(config, name) is not None for name in ("load_config", "load_dir", "load_checkpoint", "load_step"))):
    raise ValueError("source training configuration is not the frozen baseline")
config.data = data
config.pipeline.datamanager.data = data
config.pipeline.datamanager.dataparser.data = data
config.output_dir = output
config.max_num_iterations = 30000
config.steps_per_save = 3000
config.save_only_latest_checkpoint = False
config.pipeline.model.use_scale_regularization = regularization == "True"
with target.with_suffix(".part").open("x") as stream:
    stream.write(yaml.dump(config))
    stream.flush()
    os.fsync(stream.fileno())
os.replace(target.with_suffix(".part"), target)
'''

# No preexec_fn in the threaded API. The small session leader kills its complete
# process group if its API parent disappears, including during an abrupt crash.
SUPERVISE = r'''
import os, signal, subprocess, sys, threading, time
parent = int(sys.argv[1])
def watch_parent():
    while True:
        if os.getppid() != parent:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        time.sleep(0.25)
threading.Thread(target=watch_parent, daemon=True).start()
sys.exit(subprocess.Popen(sys.argv[2:]).wait())
'''


class Backend:
    def __init__(self, config: dict):
        self.config = config
        self.python = str(config.get("python", sys.executable))
        self.bin_dir = Path(self.python).parent
        # A 3000-step run stops before Splatfacto's default oversized-splat pruning.
        self.preview = {"max_image_dimension": 1280, "iterations": 30000,
                        "resolution_schedule": 500, "num_downscales": 2,
                        "colmap_gpu": False, "min_registered_fraction": 0.5,
                        **config.get("preview", {})}
        self.env = {key: value for key, value in os.environ.items()
                    if not (key.startswith("HABITAT_") and "TOKEN" in key)}
        cuda_home = str(config.get("cuda_home", "/usr/local/cuda-11.8"))
        # WSL's nvidia-smi lives outside systemd's minimal default PATH.
        self.env.update({"PATH": os.pathsep.join([str(self.bin_dir), cuda_home + "/bin", "/usr/lib/wsl/lib", self.env.get("PATH", "")]),
                         "CUDA_HOME": cuda_home, "CC": str(config.get("cc", "gcc-11")),
                         "CXX": str(config.get("cxx", "g++-11")), "MAX_JOBS": "2",
                         "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4",
                         "QT_QPA_PLATFORM": "offscreen", "PYTHONUNBUFFERED": "1"})
        self.env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parents[2]), self.env.get("PYTHONPATH", "")])
        self.probe_result: dict = {}
        self.probe_error: str | None = None
        self.ready = False
        if config.get("name", "not_configured") == "splatfacto":
            self.probe()

    def _tool(self, name: str) -> str:
        result = shutil.which(name, path=self.env["PATH"])
        if result is None:
            raise BackendError("backend_not_ready", f"Required tool is unavailable: {name}")
        return result

    def probe(self) -> bool:
        """Readiness requires actual CUDA and gsplat forward/backward execution."""
        self.ready = False
        self.probe_result = {}
        try:
            for tool in ("colmap", "ffmpeg", "ns-process-data", "ns-train", "ns-export", "ns-render"):
                self._tool(tool)
            args = [self.python, "-c", PROBE]
            if os.name == "posix":
                args = [sys.executable, "-c", SUPERVISE, str(os.getpid()), *args]
            with subprocess.Popen(args, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=os.name == "posix") as process:
                try:
                    stdout, _ = process.communicate(timeout=self.config.get("probe_timeout_seconds", 1800))
                    if process.returncode:
                        raise subprocess.CalledProcessError(process.returncode, args)
                finally:
                    self._stop(process)
            self.probe_result = json.loads(stdout.strip().splitlines()[-1])
            colmap = subprocess.run([self._tool("colmap"), "-h"], env=self.env, capture_output=True,
                                    text=True, timeout=15, check=True)
            self.probe_result["versions"]["colmap"] = colmap.stdout.splitlines()[0]
            self.ready, self.probe_error = True, None
        except (OSError, ValueError, subprocess.SubprocessError, BackendError) as exc:
            self.probe_error = type(exc).__name__  # no paths or credentials in API health
        return self.ready

    def health(self) -> dict:
        return {"backend": "splatfacto" if self.ready else "not_configured", "gpu": {
            "name": self.probe_result.get("name"), "cuda_available": bool(self.probe_result),
            "vram_total_bytes": self.probe_result.get("vram_total_bytes"),
            "reconstruction_ready": self.ready}}

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            if process.poll() is not None:
                return
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "posix":
                process.kill()
        finally:
            # The supervisor may exit before a descendant that ignores SIGTERM.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.wait(timeout=10)

    def _disk_check(self, path: Path) -> None:
        if shutil.disk_usage(path).free < self.config.get("min_free_disk_bytes", 2 * 1024**3):
            raise BackendError("storage_unavailable", "Insufficient free disk space for reconstruction")

    def _command(self, args: list[str], work: Path, phase: str, cancel: threading.Event,
        measurements: dict) -> None:
        self._disk_check(work)
        if cancel.is_set():
            raise BackendError("interrupted", "Reconstruction stopped with the service")
        log_path = work / f"{phase}.log"
        started = time.monotonic()
        timeout = self.config.get("stage_timeout_seconds", {}).get(phase, 3600)
        if os.name == "posix":
            args = [sys.executable, "-c", SUPERVISE, str(os.getpid()), *args]
        with log_path.open("wb") as log:
            process = subprocess.Popen(args, cwd=work, env=self.env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
            try:
                while process.poll() is None:
                    if cancel.wait(1):
                        raise BackendError("interrupted", "Reconstruction stopped with the service")
                    if process.poll() is not None:
                        break
                    if time.monotonic() - started > timeout:
                        raise BackendError("timeout", f"{phase} exceeded its execution deadline")
                    self._disk_check(work)
                    try:
                        memory = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                                env=self.env, capture_output=True, text=True, timeout=3, check=True)
                        used = int(memory.stdout.splitlines()[0].strip()) * 1024**2
                        measurements["peak_device_vram_bytes"] = max(measurements.get("peak_device_vram_bytes", 0), used)
                        measurements["vram_measurement"] = "whole-device nvidia-smi sampled approximately every second"
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass  # WSL nvidia-smi telemetry is not available on every driver.
                if process.returncode:
                    with log_path.open("rb") as failed_log:
                        failed_log.seek(max(0, log_path.stat().st_size - 32768))
                        tail = failed_log.read().lower()
                    code = "gpu_out_of_memory" if b"out of memory" in tail else "subprocess_failed"
                    if b"no space left" in tail:
                        code = "storage_unavailable"
                    if phase == "diagnostics" and process.returncode in (65, 73):
                        code = "input_corrupt" if process.returncode == 65 else "storage_unavailable"
                    raise BackendError(code, f"{phase} process failed; see protected server logs")
            finally:
                self._stop(process)
                measurements["stage_seconds"][phase] = round(time.monotonic() - started, 3)

    def _reuse_processed(self, experiment: dict, images_dir: Path, work_dir: Path,
                         cancel: threading.Event) -> tuple[dict, str]:
        """Copy a hash-pinned sibling job; never run COLMAP or edit the source."""
        source_job = work_dir.parent / experiment["source_job_id"]
        source = source_job / "processed"
        destination = work_dir / "processed"
        if source_job.is_symlink() or source.is_symlink() or not source.is_dir() or destination.exists():
            raise BackendError("invalid_experiment", "Frozen reconstruction source or destination is invalid")
        manifest_bytes = Path(experiment["source_manifest"]).read_bytes()
        try:
            manifest = json.loads(manifest_bytes)
            files = manifest["processed_files"]
            if (manifest["source_job_id"] != experiment["source_job_id"]
                    or manifest["capture_id"] != images_dir.name or not isinstance(files, dict) or not files):
                raise ValueError
            for name, expected in files.items():
                path = Path(name)
                if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                        or path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/"))
                        or not isinstance(expected, str) or len(expected) != 64
                        or any(c not in "0123456789abcdef" for c in expected)):
                    raise ValueError
            expected_config = manifest["training_config_sha256"]
            if not isinstance(expected_config, str) or len(expected_config) != 64:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise BackendError("invalid_experiment", "Frozen reconstruction manifest is invalid") from None

        def verify_tree(root):
            actual = set()
            for path in root.rglob("*"):
                if path.is_symlink():
                    raise BackendError("invalid_experiment", "Frozen reconstruction cannot contain symbolic links")
                if path.is_file():
                    actual.add(path.relative_to(root).as_posix())
            if actual != set(files):
                raise BackendError("input_corrupt", "Frozen reconstruction file set changed")
            for name, expected in files.items():
                if cancel.is_set():
                    raise BackendError("interrupted", "Reconstruction stopped with the service")
                with (root / name).open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise BackendError("input_corrupt", "Frozen reconstruction failed integrity validation")

        config = source_job / "trained" / "habitat-preview" / "splatfacto" / "run" / "config.yml"
        if any(path.is_symlink() for path in (config, *config.parents[:5])):
            raise BackendError("invalid_experiment", "Frozen reconstruction config cannot be a symbolic link")
        config_bytes = config.read_bytes()
        if hashlib.sha256(config_bytes).hexdigest() != expected_config:
            raise BackendError("input_corrupt", "Frozen reconstruction training configuration changed")
        verify_tree(source)
        metadata_path = source_job / "reconstruction.json"
        if metadata_path.is_symlink():
            raise BackendError("invalid_experiment", "Frozen reconstruction metadata cannot be a symbolic link")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            model_name = metadata["selected_colmap_model"]
            if not isinstance(model_name, str) or not model_name.isdecimal():
                raise ValueError
            models = metadata["colmap_model_image_counts"]
            with (source / "colmap" / "sparse" / model_name / "images.bin").open("rb") as stream:
                registered = struct.unpack("<Q", stream.read(8))[0]
            if (not isinstance(models, dict) or models.get(model_name) != registered
                    or type(metadata["input_image_count"]) is not int
                    or metadata["input_image_count"] < registered
                    or not isinstance(metadata["preset"], dict)):
                raise ValueError
        except (KeyError, ValueError, TypeError, struct.error):
            raise BackendError("invalid_experiment", "Frozen reconstruction metadata is invalid") from None

        def copy_file(src, dst):
            if cancel.is_set():
                raise BackendError("interrupted", "Reconstruction stopped with the service")
            self._disk_check(work_dir)
            return shutil.copy2(src, dst)

        shutil.copytree(source, destination, copy_function=copy_file)
        verify_tree(destination)
        with (work_dir / "frozen-source-config.yml").open("xb") as stream:
            stream.write(config_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        return metadata, hashlib.sha256(manifest_bytes).hexdigest()

    def _diagnostics(self, work_dir: Path, experiment: dict | None, cancel: threading.Event,
                     measurements: dict) -> dict:
        from habitat.gpu.diagnostics import atomic_json
        output = work_dir / "diagnostics"
        args = [self.python, "-m", "habitat.gpu.diagnostics", "--job-dir", str(work_dir), "--output", str(output)]
        rois = (experiment or {}).get("diagnostics_rois") or self.config.get("diagnostics_rois")
        if rois:
            args += ["--rois", str(rois)]
        if experiment:
            args += ["--steps", "3000", "15000", "29999"]
        try:
            self._command(args, work_dir, "diagnostics", cancel, measurements)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        except BackendError as exc:
            if cancel.is_set() or exc.code in {"interrupted", "input_corrupt", "storage_unavailable"}:
                raise
            summary = {"schema_version": 1, "status": "partial", "quality_status": "partial",
                       "source_job_id": work_dir.name, "reason": exc.code,
                       "causal_attribution": "unresolved", "details": "protected_local_diagnostics_json"}
            atomic_json(output / "summary.json", summary)
        if len(json.dumps(summary, allow_nan=False).encode()) > 64 * 1024:
            raise BackendError("invalid_output", "Diagnostics metadata exceeded the size limit")
        return summary

    def run(self, images_dir: Path, work_dir: Path, stage: Callable[[str], None],
            cancel: threading.Event) -> tuple[Path, dict]:
        if not self.ready:
            raise BackendError("backend_not_ready", "CUDA reconstruction backend is not ready")
        try:
            memory = subprocess.run([self.python, "-c", "import torch; assert torch.cuda.is_available(); print(torch.cuda.mem_get_info()[0])"],
                                    env=self.env, capture_output=True, text=True, timeout=30, check=True)
            free_vram = int(memory.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.ready = False
            self.probe_result = {}
            raise BackendError("gpu_unavailable", "CUDA device is no longer available") from exc
        if free_vram < self.config.get("min_free_vram_bytes", 1024**3):
            raise BackendError("gpu_out_of_memory", "Insufficient free GPU memory to start reconstruction")
        work_dir = Path(work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        measurements: dict = {"stage_seconds": {}, "vram_measurement": "unavailable",
                              "free_vram_bytes_before": free_vram,
                              "disk_free_bytes_before": shutil.disk_usage(work_dir).free}
        try:
            self._disk_check(work_dir)
            experiment = job_experiment(self.config, work_dir.name)
            preview = dict(self.preview)
            stage("colmap")
            processed = work_dir / "processed"
            if experiment:
                source_metadata, manifest_hash = self._reuse_processed(experiment, images_dir, work_dir, cancel)
                input_count = source_metadata["input_image_count"]
                preview.update(source_metadata["preset"], iterations=30000)
                selected_model = processed / "colmap" / "sparse" / source_metadata["selected_colmap_model"]
                model_counts = source_metadata["colmap_model_image_counts"]
            else:
                prepared = work_dir / "input"
                input_count = prepare_images(images_dir, prepared, preview["max_image_dimension"], cancel)
                # ponytail: exhaustive matching is O(n²); add vocab-tree matching if large captures exceed the deadline.
                self._command([self._tool("ns-process-data"), "images", "--data", str(prepared),
                               "--output-dir", str(processed), "--sfm-tool", "colmap", "--matching-method", "exhaustive",
                               "--num-downscales", "0", "--no-refine-intrinsics",
                               "--no-gpu" if not preview["colmap_gpu"] else "--gpu"],
                              work_dir, "colmap", cancel, measurements)
                selected_model, model_counts = select_colmap_model(processed / "colmap" / "sparse")
                if self.config.get("diagnostics_enabled", False):
                    shutil.copytree(selected_model, work_dir / "colmap-pre-ba")
                self._command([self._tool("colmap"), "bundle_adjuster", "--input_path", str(selected_model),
                               "--output_path", str(selected_model), "--BundleAdjustment.refine_principal_point", "1"],
                              work_dir, "colmap_refine", cancel, measurements)
                self._command([self._tool("ns-process-data"), "images", "--data", str(processed / "images"),
                               "--output-dir", str(processed), "--skip-colmap", "--skip-image-processing",
                               "--colmap-model-path", selected_model.relative_to(processed).as_posix(),
                               "--num-downscales", "0"], work_dir, "colmap_convert", cancel, measurements)
            transforms_path = processed / "transforms.json"
            if not transforms_path.is_file():
                raise BackendError("colmap_failed", "COLMAP did not produce registered camera poses")
            registered = len(json.loads(transforms_path.read_text())["frames"])
            if registered < max(3, input_count * preview["min_registered_fraction"]):
                raise BackendError("colmap_failed", "Too few input views registered for preview reconstruction")
            stage("training")
            trained = work_dir / "trained"
            if experiment:
                frozen_config = work_dir / "frozen-training-config.yml"
                self._command([self.python, "-c", FROZEN_TRAINING_CONFIG, str(work_dir / "frozen-source-config.yml"),
                               str(frozen_config), str(processed), str(trained), str(experiment["use_scale_regularization"])],
                              work_dir, "training_config", cancel, measurements)
                training_args = [self._tool("ns-train"), "splatfacto", "--load-config", str(frozen_config)]
            else:
                training_args = [self._tool("ns-train"), "splatfacto", "--data", str(processed),
                                 "--output-dir", str(trained), "--experiment-name", "habitat-preview", "--timestamp", "run",
                                 "--max-num-iterations", str(preview["iterations"]), "--vis", "tensorboard",
                                 "--steps-per-eval-batch", "1000000", "--steps-per-eval-image", "1000000",
                                 "--steps-per-eval-all-images", "1000000", "--pipeline.datamanager.cache-images", "cpu",
                                 "--pipeline.model.resolution-schedule", str(preview["resolution_schedule"]),
                                 "--pipeline.model.num-downscales", str(preview["num_downscales"]),
                                 "nerfstudio-data", "--downscale-factor", "1"]
            self._command(training_args, work_dir, "training", cancel, measurements)
            config = trained / "habitat-preview" / "splatfacto" / "run" / "config.yml"
            if not config.is_file() or not list(config.parent.glob("nerfstudio_models/*.ckpt")):
                raise BackendError("training_failed", "Training did not produce a model checkpoint")
            stage("exporting")
            exported = work_dir / "export"
            self._command([self._tool("ns-export"), "gaussian-splat", "--load-config", str(config),
                           "--output-dir", str(exported)], work_dir, "exporting", cancel, measurements)
            artifact = exported / "splat.ply"
            if not artifact.is_file():
                raise BackendError("export_failed", "Gaussian export file is missing")
            summary = validate_ply(artifact)
            if self.config.get("render_preview", True):
                self._command([self._tool("ns-render"), "dataset", "--load-config", str(config),
                               "--output-path", str(work_dir / "renders"), "--split", "test",
                               "--rendered-output-names", "rgb", "gt-rgb"], work_dir, "rendering", cancel, measurements)
            metadata = {"backend": "splatfacto", "backend_version": self.probe_result["versions"]["nerfstudio"],
                        "tool_versions": self.probe_result["versions"], "cuda_version": self.probe_result["cuda_version"],
                        "preset": {"name": "preview", **preview}, "input_image_count": input_count,
                        "selected_colmap_model": selected_model.name, "colmap_model_image_counts": model_counts,
                        "registered_image_count": registered, "coordinate_system": "Nerfstudio normalized COLMAP coordinates; arbitrary scale, not metric",
                        "ply": summary, "measurements": measurements}
            if experiment:
                metadata["experiment"] = {"source_job_id": experiment["source_job_id"], "target_job_id": work_dir.name,
                                          "source_manifest_sha256": manifest_hash, "colmap_execution": "reused",
                                          "training_config_sha256": hashlib.sha256(frozen_config.read_bytes()).hexdigest(),
                                          "seed": 42, "steps_per_save": 3000, "save_only_latest_checkpoint": False,
                                          "use_scale_regularization": experiment["use_scale_regularization"]}
            from habitat.gpu.diagnostics import atomic_json
            atomic_json(work_dir / "reconstruction.json", metadata)
            if self.config.get("diagnostics_enabled", False):
                metadata["diagnostics"] = self._diagnostics(work_dir, experiment, cancel, measurements)
            measurements["total_seconds"] = round(time.monotonic() - started, 3)
            measurements["disk_free_bytes_after"] = shutil.disk_usage(work_dir).free
            measurements["job_file_bytes_before_artifact_copy"] = sum(p.stat().st_size for p in work_dir.rglob("*") if p.is_file())
            atomic_json(work_dir / "reconstruction.json", metadata)
            return artifact, metadata
        except OSError as exc:
            code = "storage_unavailable" if exc.errno in {errno.ENOSPC, errno.EACCES, errno.EDQUOT} else "backend_io_failed"
            raise BackendError(code, "Reconstruction filesystem operation failed") from exc
        except ValueError as exc:
            raise BackendError("invalid_output", "Reconstruction output did not pass content validation") from exc
