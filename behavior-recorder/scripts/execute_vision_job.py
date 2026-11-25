"""Execute an immutable, local GPU training job snapshot. Called by run_home_vision_job."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from behavior_recorder.analysis_features import save_artifact
from behavior_recorder.core import atomic_json, digest, now, read_json, require
from behavior_recorder.vision_data import load_dataset, output_directory
from behavior_recorder.vision_model import evaluate, train
from behavior_recorder.vision_benchmark import benchmark, select_candidate
from behavior_recorder.worker_power import keep_awake
from behavior_recorder.worker_limits import worker_limits


def main():
    request = read_json(ROOT / "request.json")
    dataset = ROOT / "dataset"
    weights = Path(request["weights"])
    nms_iou = request.get("evaluation_nms_iou", 0.7)
    require(digest(weights) == request["weights_sha256"], "worker initial weights differ from requested weights")
    require(load_dataset(dataset)["dataset_id"] == request["dataset_id"], "worker dataset differs from reviewed dataset")
    with worker_limits(request.get("worker_limits"), ROOT / "worker-limits.json"), \
            keep_awake(), output_directory(ROOT / "result", "train_and_evaluate_real_photo_seed") as result:
        def progress(stage):
            atomic_json(result / "progress.json", {"stage": stage, "at": now()})
            print(stage, flush=True)

        if "experiment" in request:
            experiment = request["experiment"]
            models = {"baseline": ROOT / "baseline"}
            reports = {}
            for candidate in experiment["candidates"]:
                name = candidate["name"]
                progress("training_" + name)
                models[name] = result / name
                train(dataset, weights, models[name], device="0", epochs=candidate["epochs"], image_size=640,
                      batch=request["batch"], threads=2, max_minutes=request["max_training_minutes"], seed=candidate["seed"],
                      training_options=candidate["training_options"],
                      parent_model_directory=ROOT / request["parent_model"] if request.get("parent_model") else None)
            for name, path in models.items():
                progress("development_benchmark_" + name)
                reports[name] = benchmark(dataset, path, result / (name + "-val"), device="0", split="val",
                                          confidence=experiment["confidence"], iou=experiment["iou"], nms_iou=nms_iou)
            development_only = request.get("development_only", False)
            selected = select_candidate(reports, preserve_baseline_recall=development_only)
            selection = {"selected": selected, "basis": "validation F1, then negative-image false positives; baseline wins exact tie",
                         "preserve_baseline_recall": development_only,
                         "validation_metrics": {name: report["metrics"] for name, report in reports.items()},
                         "test_used_for_selection": False}
            save_artifact(result / "selection.json", selection)
            final_reports = {}
            # The selection file is finalized before touching the held-out set.
            for name in (() if development_only else dict.fromkeys(("baseline", selected))):
                progress("held_out_benchmark_" + name)
                final_reports[name] = benchmark(dataset, models[name], result / (name + "-test"), device="0", split="test",
                                                confidence=experiment["confidence"], iou=experiment["iou"], nms_iou=nms_iou)
            save_artifact(result / "job.json", {"request": request, "selection": selection,
                          "held_out_metrics": {name: r["metrics"] for name, r in final_reports.items()},
                          "field_validated": False, "purpose": "bounded real-photo detector comparison"})
            progress("finished")
            return

        progress("one_epoch_integration_training")
        smoke = train(dataset, weights, result / "smoke", device="0", smoke=True, max_minutes=2)
        progress("candidate_training")
        model = train(dataset, weights, result / "model", device="0", epochs=request["epochs"], image_size=request["image_size"],
                      batch=request["batch"], threads=2, max_minutes=request["max_training_minutes"])
        progress("held_out_photo_evaluation")
        evaluation = evaluate(dataset, result / "model", result / "evaluation", device="0", threads=2)
        fixed = benchmark(dataset, result / "model", result / "benchmark-test", device="0", split="test")
        save_artifact(result / "job.json", {"request": request, "smoke": smoke, "model": model,
                      "evaluation": evaluation, "fixed_threshold_metrics": fixed["metrics"], "field_validated": False,
                      "purpose": "Real-photo seed detector and software integration; no behavior/anomaly training"})
        progress("finished")


if __name__ == "__main__":
    main()
