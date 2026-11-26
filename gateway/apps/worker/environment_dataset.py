"""Build offline environment datasets or evaluate prediction JSONL files."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from habitat.compute.environment_dataset import build_dataset, read_dataset
from habitat.compute.environment_evaluation import evaluate_predictions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Export windows from a source manifest")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("evaluate", help="Score an existing prediction JSONL")
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--predictions", type=Path, required=True)
    evaluate.add_argument("--split", choices=("train", "validation", "test"), default="test")
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            result = build_dataset(args.manifest, args.output)
        else:
            header, windows, summary = read_dataset(args.dataset)
            predictions = []
            prediction_bytes = args.predictions.read_bytes()
            for number, line in enumerate(prediction_bytes.decode('utf-8').splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    predictions.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"predictions line {number}: {error.msg}") from None
            if not predictions:
                raise ValueError("predictions JSONL is empty")
            result = evaluate_predictions(windows, predictions, split=args.split)
            result.update(
                dataset_source=header["source"],
                source_manifest_sha256=header["source_manifest_sha256"],
                dataset_windows_sha256=summary["windows_sha256"],
                predictions_sha256=hashlib.sha256(prediction_bytes).hexdigest(),
                hardware_execution_allowed=False,
            )
            encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            args.output.parent.mkdir(parents=True, exist_ok=True)
            created = False
            try:
                with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                    created = True
                    stream.write(encoded)
            except BaseException:
                if created:
                    args.output.unlink(missing_ok=True)
                raise
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
