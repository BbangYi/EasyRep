"""Wake the known GPU PC, send an immutable reviewed-data job, retrieve model/evidence."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.core import digest, number, require
from behavior_recorder.vision_data import load_dataset
from behavior_recorder.vision_model import assert_unseen, load_model_card, validate_training_options
from verify_home_gpu import SSH, REMOTE_ROOT, remote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment", type=Path, help="Bounded comparison config with baseline and candidates")
    initialization = parser.add_mutually_exclusive_group()
    initialization.add_argument("--initial-model", type=Path, help="Continue from a validated local model card and checkpoint")
    initialization.add_argument("--pretrained-weights", type=Path, help="Use a trusted local pretrained .pt checkpoint instead of worker YOLO11n")
    parser.add_argument("--development-only", action="store_true", help="Preserve baseline recall and do not inspect test")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--max-training-minutes", type=float, default=5)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--guarded", action="store_true", help="Limit CUDA allocation, lower process priority, and stop on excess temperature/time")
    args = parser.parse_args()
    require(not (args.initial_model or args.development_only) or args.experiment, "these options require an experiment")
    require(re.fullmatch(r"[A-Za-z0-9-]{1,40}", args.run_id), "invalid run ID")
    number(args.epochs, 1, 100)
    number(args.max_training_minutes, 1, 30)
    number(args.batch, 1, 16)
    pretrained = args.pretrained_weights.resolve() if args.pretrained_weights else None
    if pretrained:
        require(pretrained.is_file() and pretrained.suffix == ".pt", "pretrained weights must be an existing .pt file")
        require(0 < pretrained.stat().st_size <= 32 * 1024**2, "pretrained checkpoint size must be 1 byte to 32 MiB")
    manifest = load_dataset(args.dataset)
    require(manifest["dataset_kind"] == "real", "real reviewed input required")
    job_root = REMOTE_ROOT + "\\data\\jobs\\" + args.run_id
    destination = ROOT / "data" / "gpu-jobs" / args.run_id
    request = {"run_id": args.run_id, "dataset_id": manifest["dataset_id"],
               "weights": job_root + r"\pretrained\best.pt" if pretrained else REMOTE_ROOT + r"\data\weights\yolo11n.pt",
               "weights_sha256": digest(pretrained or ROOT / "data/weights/yolo11n.pt"),
               "epochs": args.epochs, "image_size": 640, "batch": args.batch, "max_training_minutes": args.max_training_minutes,
               "evaluation_nms_iou": 0.5,
               "test_use": "one evaluation after validation-selected candidate training"}
    baseline = None
    if args.experiment:
        experiment = json.loads(args.experiment.read_text())
        require(set(experiment) == {"baseline", "candidates", "confidence", "iou"}, "invalid experiment fields")
        require(experiment["confidence"] == 0.4 and experiment["iou"] == 0.5, "comparison uses fixed confidence=0.4/IoU=0.5")
        candidates = experiment["candidates"]
        require(isinstance(candidates, list) and 1 <= len(candidates) <= 3, "select 1-3 candidates")
        names = {"baseline"}
        for candidate in candidates:
            require(set(candidate) == {"name", "epochs", "seed", "training_options"}, "invalid candidate fields")
            name = candidate["name"]
            require(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]{1,40}", name) and name not in names, "invalid/duplicate candidate name")
            names.add(name)
            require(type(candidate["epochs"]) is int and 1 <= candidate["epochs"] <= 100, "candidate epochs out of range")
            require(type(candidate["seed"]) is int and 0 <= candidate["seed"] <= 10000, "invalid seed")
            validate_training_options(candidate["training_options"])
        baseline = Path(experiment["baseline"]).resolve()
        card = load_model_card(baseline)
        assert_unseen(card, [r for r in manifest["records"] if r["split"] == "test"])
        request["experiment"] = {**experiment, "baseline": "baseline", "baseline_model_id": card["model_id"]}
        request.pop("epochs")
        request["development_only"] = args.development_only
        if args.development_only:
            request["test_use"] = "none: development-only follow-up; prior test is not reused as new evidence"
    parent = None
    if args.guarded:
        count = len(request.get("experiment", {}).get("candidates", [None]))
        request["worker_limits"] = dict(cuda_memory_fraction=.55, max_temperature_c=78,
                                       max_wall_seconds=360 + count * args.max_training_minutes * 60)
    if args.initial_model:
        parent = args.initial_model.resolve()
        parent_card = load_model_card(parent)
        assert_unseen(parent_card, [r for r in manifest["records"] if r["split"] == "test"])
        request.update(weights=job_root + r"\parent\best.pt", weights_sha256=parent_card["weights"]["sha256"],
                       parent_model="parent", parent_model_id=parent_card["model_id"])
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("request.json", json.dumps(request, ensure_ascii=False, indent=2))
        archive.write(ROOT / "scripts/execute_vision_job.py", "execute_vision_job.py")
        if pretrained:
            archive.write(pretrained, "pretrained/best.pt")
        if baseline:
            for name in ("model.json", "status.json", "best.pt"):
                archive.write(baseline / name, "baseline/" + name)
        if parent:
            for name in ("model.json", "status.json", "best.pt"):
                archive.write(parent / name, "parent/" + name)
        for path in (ROOT / "behavior_recorder").glob("*.py"):
            archive.write(path, "behavior_recorder/" + path.name)
        for path in args.dataset.rglob("*"):
            if path.is_file():
                archive.write(path, "dataset/" + path.relative_to(args.dataset).as_posix())
    payload_bytes = payload.getvalue()
    if pretrained:
        with zipfile.ZipFile(io.BytesIO(payload_bytes)) as archive:
            require(hashlib.sha256(archive.read("pretrained/best.pt")).hexdigest() == request["weights_sha256"],
                    "pretrained checkpoint changed while packaging")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "request.json").write_text(json.dumps({**request, "source_zip_sha256": checksum,
                                                       "worker_job_root": job_root}, indent=2) + "\n")
    wake = subprocess.run([*SSH, "bbangi", "cd /opt/giminu-control-center/current && ENABLE_WOL=true "
                           "WOL_SCHEDULE_DEVICE_IDS=desktop-main node scripts/send-scheduled-wol.mjs"],
                          check=True, capture_output=True, timeout=20)
    (destination / "wake.log").write_bytes(wake.stdout + wake.stderr)
    for attempt in range(20):
        try:
            require(remote("hostname", timeout=8).stdout.decode().strip() == "DESKTOP-GMQFQTR", "unexpected worker")
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 19:
                raise
            time.sleep(2)
    code = ("import sys,io,zipfile,hashlib; from pathlib import Path; "
            f"p=Path(r'{job_root}'); p.mkdir(parents=True,exist_ok=False); data=sys.stdin.buffer.read(); "
            f"assert hashlib.sha256(data).hexdigest()=='{checksum}'; "
            "zipfile.ZipFile(io.BytesIO(data)).extractall(p)")
    remote(f'py -3.12 -c "{code}"', input=payload_bytes, timeout=60)
    print(f"Reviewed dataset transferred. Starting bounded CUDA job {args.run_id}", flush=True)
    python = REMOTE_ROOT + r"\.venv-vision\Scripts\python.exe"
    command = f"cd /d {job_root} && set PYTHONUTF8=1&& {python} execute_vision_job.py > execution.log 2>&1"
    try:
        candidates = len(request.get("experiment", {}).get("candidates", [None]))
        execution = subprocess.run([*SSH, "desktop", command], capture_output=True,
                                   timeout=600 + candidates * (args.max_training_minutes * 60 + 120))
    except subprocess.TimeoutExpired:
        # The remote process may still be live. Preserve its ID/path, never retry blindly.
        raise RuntimeError(f"Observation timed out; inspect {job_root} before any retry")
    (destination / "ssh.log").write_bytes(execution.stdout + execution.stderr)
    code = ("import io,zipfile,sys; from pathlib import Path; "
            f"r=Path(r'{job_root}'); b=io.BytesIO(); z=zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED); "
            "files=[r/'execution.log']+list(r.glob('worker-limits.json'))+[p for p in (r/'result').rglob('*') if p.is_file() "
            "and 'learner-data' not in p.parts and 'runtime' not in p.parts and 'weights' not in p.parts "
            "and (p.suffix in {'.json','.csv','.yaml','.pt'} or p.name=='train-samples.txt')]; "
            "[z.write(p,p.relative_to(r).as_posix()) for p in files]; z.close(); sys.stdout.buffer.write(b.getvalue())")
    evidence = remote(f'py -3.12 -c "{code}"', timeout=60).stdout
    require(len(evidence) <= 100 * 1024**2, "evidence bundle exceeds limit")
    with zipfile.ZipFile(io.BytesIO(evidence)) as archive:
        for item in archive.infolist():
            name = Path(item.filename)
            require(not name.is_absolute() and ".." not in name.parts and "\\" not in item.filename,
                    "unsafe evidence path")
            require(item.file_size <= 32 * 1024**2, "oversized evidence entry")
        archive.extractall(destination)
    if execution.returncode:
        raise RuntimeError(f"Worker job failed; inspect {destination / 'execution.log'}")
    operation = "Development-only comparison" if args.development_only else "Training and held-out evaluation"
    print(f"{operation} finished; evidence: {destination}", flush=True)


if __name__ == "__main__":
    main()
