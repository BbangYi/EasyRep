"""Wake the known home worker, sync this task's code, check CUDA, retrieve evidence.

No global configuration changes, no real-image training, and no deletion.
Run only after setup_vision_windows.py has installed this dedicated checkout.
"""
import hashlib
import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = r"C:\Users\HOME\HabitatOS\vision-20261014"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=15"]


def remote(command, **kwargs):
    return subprocess.run([*SSH, "desktop", command], check=True, capture_output=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    run_id = parser.parse_args().run_id
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,40}", run_id):
        raise SystemExit("run-id must contain 1-40 letters, digits, or hyphens")
    check_folder = f"worker-gpu-check-{run_id}"
    destination = ROOT / f"data/home-gpu-verification-{run_id}"
    destination.mkdir(parents=True, exist_ok=False)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        paths = [p for directory in ("behavior_recorder", "scripts", "tests") for p in (ROOT / directory).glob("*.py")]
        paths += list((ROOT / "examples").glob("vision*.json"))
        paths += [ROOT / name for name in ("README.md", "AI_PIPELINE.md", "examples/config.pi.crested-gecko.json",
                                          "data/weights/yolo11n.source.json")]
        for path in sorted(paths):
            archive.write(path, path.relative_to(ROOT).as_posix())
    checksum = hashlib.sha256(payload.getvalue()).hexdigest()
    wake = subprocess.run([*SSH, "bbangi", "cd /opt/giminu-control-center/current && ENABLE_WOL=true "
                           "WOL_SCHEDULE_DEVICE_IDS=desktop-main node scripts/send-scheduled-wol.mjs"],
                          check=True, capture_output=True, timeout=20)
    (destination / "wake.log").write_bytes(wake.stdout + wake.stderr)
    print("Wake requested; checking SSH readiness", flush=True)
    for attempt in range(20):
        try:
            host = remote("hostname", timeout=8).stdout.decode().strip()
            if host != "DESKTOP-GMQFQTR":
                raise RuntimeError("Unexpected worker hostname")
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 19:
                raise
            time.sleep(2)
    code = ("import sys,io,zipfile,hashlib; from pathlib import Path; "
            f"p=Path(r'{REMOTE_ROOT}'); assert (p/'.venv-vision/Scripts/python.exe').is_file(); "
            f"data=sys.stdin.buffer.read(); assert hashlib.sha256(data).hexdigest()=='{checksum}'; "
            "zipfile.ZipFile(io.BytesIO(data)).extractall(p); print('source integrity verified')")
    result = remote(f'py -3.12 -c "{code}"', input=payload.getvalue(), timeout=40)
    (destination / "transfer.log").write_bytes(result.stdout + result.stderr)
    print("Source transferred; running CUDA and focused tests", flush=True)
    python = r".venv-vision\Scripts\python.exe"
    command = (f"cd /d {REMOTE_ROOT} && set PYTHONUTF8=1&& "
               f"{python} scripts\\check_vision_worker.py --device 0 --weights data\\weights\\yolo11n.pt "
               f"--output data\\{check_folder} && "
               f"{python} -m unittest discover -s tests -p test_vision.py -v > data\\vision-tests-windows.txt 2>&1 && "
               f"{python} -m pip freeze > data\\vision-requirements-windows.txt")
    try:
        result = remote(command, timeout=300)
    except subprocess.CalledProcessError as exc:
        (destination / "execution.log").write_bytes((exc.stdout or b"") + (exc.stderr or b""))
        raise
    (destination / "execution.log").write_bytes(result.stdout + result.stderr)
    code = ("import io,zipfile,sys; from pathlib import Path; "
            f"root=Path(r'{REMOTE_ROOT}')/'data'; b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); "
            f"files=['{check_folder}/worker.json','{check_folder}/status.json',"
            "'vision-tests-windows.txt','vision-requirements-windows.txt']; "
            "[z.write(root/f,f) for f in files]; z.close(); sys.stdout.buffer.write(b.getvalue())")
    evidence = remote(f'py -3.12 -c "{code}"', timeout=30).stdout
    with zipfile.ZipFile(io.BytesIO(evidence)) as archive:
        expected = {f"{check_folder}/worker.json", f"{check_folder}/status.json",
                    "vision-tests-windows.txt", "vision-requirements-windows.txt"}
        if set(archive.namelist()) != expected or any(i.file_size > 4 * 1024**2 for i in archive.infolist()):
            raise RuntimeError("Unexpected evidence bundle")
        archive.extractall(destination)
    report = json.loads((destination / check_folder / "worker.json").read_text())
    assert report["actual_model_device"] == "cuda:0" and report["finite_gradient_check"]
    (destination / "source.json").write_text(json.dumps({"worker": host, "source_zip_sha256": checksum,
                                                       "remote_root": REMOTE_ROOT}, indent=2) + "\n")
    print(f"CUDA execution verified; evidence saved in {destination}", flush=True)


if __name__ == "__main__":
    main()
