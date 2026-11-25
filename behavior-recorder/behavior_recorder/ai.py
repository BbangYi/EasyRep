"""Offline feature, training, inference and evaluation commands."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .analysis_features import build_dataset, load_dataset, save_artifact
from .anomaly import evaluate, fit, predict
from .core import RecorderError, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Portable offline anomaly model baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features")
    features.add_argument("sessions", type=Path, nargs="+")
    features.add_argument("--config", type=Path, required=True)
    features.add_argument("--output", type=Path, required=True)
    train = commands.add_parser("train")
    train.add_argument("--training", type=Path, required=True)
    train.add_argument("--calibration", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--false-alarm-rate", type=float, default=0.05)
    train.add_argument("--consecutive-windows", type=int, default=2)
    for name in ("infer", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--model", type=Path, required=True)
        command.add_argument("--data", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "evaluate":
            command.add_argument("--baseline-motion-threshold", type=float, default=0.05)
    args = parser.parse_args(argv)
    try:
        if args.command == "features":
            result = build_dataset(args.sessions, read_json(args.config))
            summary = {"windows": len(result["rows"]), "reviewed_normal": sum(r["human_assessment"] == "normal" for r in result["rows"])}
        elif args.command == "train":
            result = fit(load_dataset(args.training), load_dataset(args.calibration), args.false_alarm_rate, args.consecutive_windows)
            summary = {"model_id": result["model_id"], "status": result["status"], "threshold": result["threshold"]}
        else:
            model = read_json(args.model, 32 * 1024**2)
            data = load_dataset(args.data)
            if args.command == "infer":
                result = predict(model, data)
                summary = {"windows": len(result["predictions"]), "alerts": len(result["alerts"])}
            else:
                result = evaluate(model, data, args.baseline_motion_threshold)
                summary = {"evidence_scope": result["evidence_scope"], "metrics": result["model"]}
        save_artifact(args.output, result)
        print(json.dumps({"output": str(args.output), **summary}, ensure_ascii=False, indent=2))
        return 0
    except (RecorderError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
