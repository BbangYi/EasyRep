"""Process-lifetime resource limits for a dedicated Windows CUDA worker."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import threading
import time

from .core import atomic_json, now, number, require


def validate_limits(limits):
    require(isinstance(limits, dict) and set(limits) ==
            {"cuda_memory_fraction", "max_temperature_c", "max_wall_seconds"}, "invalid worker limits")
    number(limits["cuda_memory_fraction"], .1, .75)
    number(limits["max_temperature_c"], 50, 85)
    number(limits["max_wall_seconds"], 60, 6000)
    return dict(limits)


def parse_gpu_sample(output):
    fields = output.strip().split(",")
    require(len(fields) == 3 and "\n" not in output.strip(), "invalid GPU measurement")
    temperature, memory, utilization = [float(value) for value in fields]
    number(temperature, 0, 120)
    number(memory, 0, 1024 * 1024)
    number(utilization, 0, 100)
    return dict(temperature_c=temperature, memory_mib=memory, utilization_percent=utilization)


def gpu_sample():
    result = subprocess.run(["nvidia-smi", "--id=0",
        "--query-gpu=temperature.gpu,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True, timeout=5)
    return parse_gpu_sample(result.stdout)


def abort_worker(path, report, reason):
    report.update(state="aborted", reason=reason, finished_at=now())
    try:
        atomic_json(path, report)
        print("Worker stopped: " + reason, flush=True)
    finally:
        # This is a dedicated worker. Exit this process, never another user's process.
        os._exit(124)


def apply_process_limits(limits):
    require(os.name == "nt", "guarded worker requires Windows")
    import ctypes
    import torch
    require(torch.cuda.is_available(), "guarded worker requires CUDA")
    torch.cuda.set_per_process_memory_fraction(limits["cuda_memory_fraction"], 0)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    require(bool(kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000)), "cannot set BelowNormal priority")


@contextmanager
def worker_limits(limits, evidence_path):
    if limits is None:
        yield
        return
    limits = validate_limits(limits)
    apply_process_limits(limits)
    path = Path(evidence_path)
    started = time.monotonic()
    stop = threading.Event()
    report = dict(state="running", started_at=now(), pid=os.getpid(), limits=limits,
        priority="BelowNormal", cuda_device=0, sample_interval_seconds=3, samples=[])

    def check():
        require(time.monotonic() - started < limits["max_wall_seconds"], "worker wall-time limit reached")
        sample = dict(at=now(), **gpu_sample())
        report["samples"].append(sample)
        require(sample["temperature_c"] < limits["max_temperature_c"], "GPU temperature limit reached")
        atomic_json(path, report)

    def monitor():
        while not stop.wait(3):
            try:
                check()
            except Exception as error:
                abort_worker(path, report, str(error))

    thread = None
    completed = False
    try:
        check()  # Refuse to start training when the guard cannot observe the GPU.
        thread = threading.Thread(target=monitor, name="vision-worker-limits", daemon=True)
        thread.start()
        yield
        require(time.monotonic() - started < limits["max_wall_seconds"], "worker wall-time limit reached")
        completed = True
    except BaseException as error:
        report["reason"] = str(error)
        raise
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=7)
        elapsed = time.monotonic() - started
        overdue = completed and elapsed >= limits["max_wall_seconds"]
        if overdue:
            report["reason"] = "worker wall-time limit reached during cleanup"
        report.update(state="complete" if completed and not overdue else "failed", finished_at=now(),
                      elapsed_seconds=elapsed)
        atomic_json(path, report)
        require(not overdue, report.get("reason", "worker wall-time limit reached"))
