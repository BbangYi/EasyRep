"""Run with py -3.12; install only into this checkout's dedicated vision venv."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.worker_power import keep_awake


def main():
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this installer on Windows with py -3.12")
    destination = ROOT / ".venv-vision"
    python = destination / "Scripts" / "python.exe"
    with keep_awake():
        if not destination.exists():
            venv.EnvBuilder(with_pip=True).create(destination)
        if not python.is_file() or not (destination / "pyvenv.cfg").is_file():
            raise SystemExit("Existing .venv-vision is incomplete; inspect it before retrying")
        pip = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir"]
        subprocess.run([*pip, "torch==2.8.0", "torchvision==0.23.0", "--index-url",
                        "https://download.pytorch.org/whl/cu128"], check=True, cwd=ROOT, timeout=2400)
        subprocess.run([*pip, "-r", str(ROOT / "requirements-vision.txt")], check=True, cwd=ROOT, timeout=1200)
        subprocess.run([str(python), "-m", "behavior_recorder.vision", "doctor"], check=True, cwd=ROOT, timeout=120)


if __name__ == "__main__":
    main()
