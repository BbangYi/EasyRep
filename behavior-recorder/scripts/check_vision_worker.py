"""Check actual compute and official checkpoint inference; no animal training occurs."""
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import digest
from behavior_recorder.vision_data import output_directory
from behavior_recorder.vision_model import check_device, environment, runtime
from behavior_recorder.worker_power import keep_awake


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with keep_awake(), output_directory(args.output, "vision_worker_acceptance") as run:
        YOLO = runtime(run / "runtime", threads=2)
        check_device(args.device)
        import numpy as np
        import torch
        target = f"cuda:{args.device}" if args.device.isdigit() else args.device
        layer = torch.nn.Linear(8, 2).to(target)
        loss = layer(torch.ones((2, 8), device=target)).square().mean()
        loss.backward()
        gradients_ok = all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in layer.parameters())
        if not gradients_ok:
            raise RuntimeError("compute gradient check failed")
        model = YOLO(str(args.weights.resolve()), task="detect")
        prediction = model.track(np.zeros((160, 160, 3), dtype=np.uint8), persist=True,
                                 tracker="bytetrack.yaml", device=args.device, imgsz=160, verbose=False)[0]
        # Ultralytics copies the original module into its inference backend.
        actual_device = str(next(model.predictor.model.model.parameters()).device)
        # Tensor devices use canonical names (for example, "mps" becomes "mps:0").
        if actual_device != str(layer.weight.device):
            raise RuntimeError(f"Inference backend used {actual_device}, requested {target}")
        report = {"environment": environment(), "requested_device": args.device,
                  "actual_model_device": actual_device, "gradient_device": str(layer.weight.device),
                  "finite_gradient_check": gradients_ok, "checkpoint_forward_and_tracking": True,
                  "checkpoint_sha256": digest(args.weights), "checkpoint_classes": model.names,
                  "input": "blank 160x160 software fixture", "detections": len(prediction.boxes),
                  "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
                  "real_animal_training_images": 0, "animal_performance_evaluated": False}
        save_artifact(run / "worker.json", report)
        print(f"Worker compute passed: {report['actual_model_device']}; animal training/evaluation: not performed")


if __name__ == "__main__":
    main()
