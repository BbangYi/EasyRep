"""Compile the real IR headers against host GPIO/MQTT/RTOS mocks.

These check fail-OFF decisions and protocol compatibility. They do not measure
electrical behavior, optical output, or actual ESP32 task scheduling latency.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


@pytest.mark.parametrize("source,defines,case_count", [
    ("test_ir_controller.cpp", [], 34),
    ("test_ir_runtime.cpp", [], 19),
    ("test_ir_runtime.cpp", ["-DHABITAT_IR_OUTPUTS=0"], 4),
], ids=["controller-and-r15-compatibility", "runtime", "runtime-outputs-locked"])
def test_production_ir_firmware(source, defines, case_count):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("A C++17 compiler is required for native firmware checks")
    with tempfile.TemporaryDirectory(prefix="habitatos-ir-test-") as directory:
        binary = Path(directory) / "ir-tests"
        compiled = subprocess.run([
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-O0", *defines, str(Path(__file__).with_name(source)), "-o", str(binary),
        ], capture_output=True, text=True, timeout=60)
        assert compiled.returncode == 0, compiled.stderr
        result = subprocess.run([str(binary)], cwd=directory,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["hardware_tested"] is False
    assert report["total"] == case_count
    assert report["failed"] == 0
    assert all(case["passed"] for case in report["cases"])
