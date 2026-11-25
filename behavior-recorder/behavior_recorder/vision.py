"""Real-image detection training and recorder-compatible video analysis commands."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .core import RecorderError, read_json
from .vision_data import dataset_summary, init_plan, load_dataset, prepare_dataset
from .vision_model import environment, evaluate, runtime, train
from .vision_images import review_images
from .vision_benchmark import benchmark
from .vision_video import extract_frames, export_tracking_review, infer_video
from .vision_tracking_eval import evaluate_video
from .analysis_features import save_artifact


def video_arguments(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", type=Path)
    group.add_argument("--session", type=Path)
    parser.add_argument("--clip")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Crested gecko real-data vision workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--runtime", type=Path, default=Path("data/vision-runtime"))
    init = commands.add_parser("init-dataset", help="Create an unreviewed plan from an extracted YOLO/CVAT dataset")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--source-url", required=True)
    init.add_argument("--license", required=True)
    init.add_argument("--attribution", required=True)
    init.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--root", type=Path, required=True)
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--dataset", type=Path, required=True)
    training = commands.add_parser("train")
    training.add_argument("--dataset", type=Path, required=True)
    training.add_argument("--weights", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    training.add_argument("--device", default="cpu")
    training.add_argument("--epochs", type=int, default=30)
    training.add_argument("--image-size", type=int, default=640)
    training.add_argument("--batch", type=int, default=4)
    training.add_argument("--threads", type=int, default=2)
    training.add_argument("--max-minutes", type=float, default=30)
    training.add_argument("--training-options", type=Path, help="Validated optimizer/freeze/augmentation JSON")
    training.add_argument("--parent-model", type=Path, help="Fine-tuned initial model; inherits its evaluation exclusions")
    training.add_argument("--smoke", action="store_true", help="One 160px epoch; software integration proof only")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--dataset", type=Path, required=True)
    evaluation.add_argument("--model", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--device", default="cpu")
    benchmark_parser = commands.add_parser("benchmark", help="Fixed-threshold detection and negative-image errors")
    benchmark_parser.add_argument("--dataset", type=Path, required=True)
    benchmark_parser.add_argument("--model", type=Path, required=True)
    benchmark_parser.add_argument("--output", type=Path, required=True)
    benchmark_parser.add_argument("--split", choices=("val", "test"), default="val")
    benchmark_parser.add_argument("--confidence", type=float, default=0.4)
    benchmark_parser.add_argument("--device", default="cpu")
    review = commands.add_parser("review-images", help="Draw model boxes beside attributed reference labels")
    review.add_argument("--dataset", type=Path, required=True)
    review.add_argument("--model", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--split", choices=("train", "val", "test"), default="test")
    review.add_argument("--limit", type=int, default=20)
    review.add_argument("--confidence", type=float, default=0.4)
    review.add_argument("--device", default="cpu")
    extraction = commands.add_parser("extract")
    video_arguments(extraction)
    extraction.add_argument("--sample-fps", type=float, default=0.2)
    extraction.add_argument("--source-url", required=True)
    extraction.add_argument("--license", required=True)
    extraction.add_argument("--attribution", required=True)
    extraction.add_argument("--provenance", choices=("public_real", "real_camera"),
                            help="Required for external video; operator declaration preserved in output")
    extraction.add_argument("--output", type=Path, required=True)
    inference = commands.add_parser("infer")
    video_arguments(inference)
    inference.add_argument("--model", type=Path, required=True)
    inference.add_argument("--config", type=Path, required=True)
    inference.add_argument("--output", type=Path, required=True)
    inference.add_argument("--device", default="cpu")
    inference.add_argument("--backend", choices=("yolo", "hybrid", "sam3-hybrid", "sam2-hybrid"), default="yolo")
    inference.add_argument("--threads", type=int, default=2)
    inference.add_argument("--provenance", choices=("public_real", "real_camera", "synthetic_test"),
                           help="Explicit external video origin; defaults to unverified_file")
    tracking_review = commands.add_parser("export-tracking-review", help="Export uncertain moments for box/identity labeling")
    tracking_review.add_argument("--analysis", type=Path, required=True)
    tracking_review.add_argument("--video", type=Path, required=True)
    tracking_review.add_argument("--output", type=Path, required=True)
    tracking_review.add_argument("--limit", type=int, default=40)
    tracking_review.add_argument("--selection", choices=("failures", "uniform", "consecutive"), default="failures",
                                 help="Failure mining, evenly spaced samples, or first consecutive samples")
    video_benchmark = commands.add_parser("benchmark-video", help="Evaluate source-bound body references and adjacent tracking links")
    video_benchmark.add_argument("--analysis", type=Path, required=True)
    video_benchmark.add_argument("--references", type=Path, required=True)
    video_benchmark.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            runtime(args.runtime)
            result = {"executable": sys.executable, **environment()}
        elif args.command == "init-dataset":
            result = init_plan(args.root, args.output, args.source_url, args.license, args.attribution)
        elif args.command == "prepare":
            result = prepare_dataset(args.root, args.plan, args.output)
        elif args.command == "check":
            result = dataset_summary(load_dataset(args.dataset))
        elif args.command == "train":
            result = train(args.dataset, args.weights, args.output, device=args.device, epochs=args.epochs,
                           image_size=args.image_size, batch=args.batch, threads=args.threads,
                           max_minutes=args.max_minutes, smoke=args.smoke,
                           training_options=read_json(args.training_options) if args.training_options else None,
                           parent_model_directory=args.parent_model)
        elif args.command == "evaluate":
            result = evaluate(args.dataset, args.model, args.output, device=args.device)
        elif args.command == "benchmark":
            result = benchmark(args.dataset, args.model, args.output, split=args.split,
                               confidence=args.confidence, device=args.device)
        elif args.command == "review-images":
            result = review_images(args.dataset, args.model, args.output, split=args.split, limit=args.limit,
                                   confidence=args.confidence, device=args.device)
        elif args.command == "extract":
            result = extract_frames(args.output, video=args.video, session_path=args.session, clip_id=args.clip,
                                    sample_fps=args.sample_fps, source_url=args.source_url,
                                    license_name=args.license, attribution=args.attribution, provenance=args.provenance)
        elif args.command == "export-tracking-review":
            result = export_tracking_review(args.analysis, args.video, args.output, limit=args.limit, selection=args.selection)
        elif args.command == "benchmark-video":
            result = evaluate_video(args.analysis, args.references)
            save_artifact(args.output, result)
        else:
            result = infer_video(args.model, args.output, read_json(args.config), video=args.video,
                                 session_path=args.session, clip_id=args.clip, device=args.device, provenance=args.provenance,
                                 backend=args.backend, threads=args.threads)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (RecorderError, OSError, ValueError, TypeError, KeyError, ImportError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        message = str(exc)
        if isinstance(exc, ImportError):
            if getattr(args, "backend", None) in {"sam3-hybrid", "sam2-hybrid"}:
                message += "; configure the isolated local runtimes listed in model-card.json"
            else:
                requirements = "requirements-hybrid.txt" if getattr(args, "backend", None) == "hybrid" else "requirements-vision.txt"
                message += f"; install {requirements} in the dedicated vision virtual environment"
        print(json.dumps({"error": type(exc).__name__, "message": message}, ensure_ascii=False), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
