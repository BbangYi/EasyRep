"""Six tiny synthetic videos, recorder sessions, a fitted model and held-out evaluation."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from behavior_recorder.analysis_features import build_dataset, save_artifact
from behavior_recorder.anomaly import evaluate, fit, predict
from behavior_recorder.core import Session, atomic_json, create_session, digest, read_json, require
from behavior_recorder.media import ingest
from behavior_recorder.records import import_labels


def make_video(path, seed, anomalous=False):
    frames = []
    x = 3
    direction = 1
    for index in range(48):
        fast = anomalous and index >= 16
        x += direction * (10 if fast else 1 + seed % 2)
        if x > 48:
            x, direction = 96 - x, -1
        elif x < 0:
            x, direction = -x, 1
        pixels = bytearray([55 + seed % 3] * (64 * 48))
        for y in range(12, 24):
            pixels[y * 64 + x:y * 64 + x + 12] = bytes([180]) * 12
        pixels[-1] = 30 + seed  # Distinct raw originals, even when motion patterns match.
        frames.append(bytes(pixels))
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "rawvideo", "-pix_fmt", "gray",
                    "-s", "64x48", "-r", "4", "-i", "pipe:0", "-c:v", "mpeg4", "-q:v", "3",
                    "-threads", "1", str(path)], input=b"".join(frames), check=True, timeout=20)


def run(destination):
    destination = Path(destination)
    require(not destination.exists(), "demo destination already exists; choose a new directory")
    destination.mkdir(parents=True)
    inbox = destination / "inbox"
    inbox.mkdir()
    config = read_json(Path(__file__).with_name("config.test.json"))
    config["cameras"] = [config["cameras"][0]]
    config["cameras"][0]["expected_fps"] = 4
    features = {"schema_version": 1, "camera_id": "rgb-01", "animal_id": "test-subject", "context": "synthetic-day",
                "roi": None, "window_seconds": 1, "sample_fps": 4, "pixel_delta": 20, "max_clock_error_ms": 500, "sensors": []}
    save_artifact(destination / "features.config.json", features)
    splits = {"training": [], "calibration": [], "test": []}
    for index in range(6):
        split = "training" if index < 2 else "calibration" if index < 4 else "test"
        name = f"synthetic-{index}"
        video = inbox / f"{name}.mp4"
        make_video(video, index, anomalous=index == 5)
        root = destination / "sessions" / name
        create_session(root, config)
        descriptor = {"schema_version": 1, "input_id": name, "camera_id": "rgb-01", "file": video.name,
                      "sha256": digest(video), "recording_id": f"synthetic-recording-{index}", "sequence": 0,
                      "provenance": "synthetic_test", "captured_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat(),
                      "capture_clock": {"source": "operator", "accuracy_ms": 0}, "placement_revision": None, "calibration_revision": None}
        descriptor_path = inbox / f"{name}.capture.json"
        atomic_json(descriptor_path, descriptor)
        with Session(root) as session:
            clip_id = ingest(session, descriptor_path)["clip_id"]
            base = {"clip_id": clip_id, "animal_id": "test-subject", "behavior": None, "visibility": "visible",
                    "certainty": "certain", "annotator": "synthetic_fixture_generator",
                    "note": "Synthetic rectangle only; not an animal observation", "supersedes": None}
            labels = [{**base, "label_id": f"normal-{index}", "start_seconds": 0, "end_seconds": 4 if index == 5 else 12, "assessment": "normal"}]
            if index == 5:
                labels.append({**base, "label_id": "synthetic-anomaly-5", "start_seconds": 4, "end_seconds": 12, "assessment": "anomaly"})
            import_labels(session, labels)
            session.event("session_stopped", updates={"state": "stopped", "ended_at": descriptor["captured_at"]})
        splits[split].append(root)
    datasets = {name: build_dataset(paths, features) for name, paths in splits.items()}
    for name, dataset in datasets.items():
        save_artifact(destination / f"{name}.features.json", dataset)
    model = fit(datasets["training"], datasets["calibration"])
    predictions = predict(model, datasets["test"])
    report = evaluate(model, datasets["test"])
    save_artifact(destination / "model.json", model)
    save_artifact(destination / "predictions.json", predictions)
    save_artifact(destination / "evaluation.json", report)
    summary = {"evidence_scope": "synthetic_pipeline_only", "real_animal_observations": 0,
               "sessions": 6, "source_video_seconds": 72, "windows_per_split": {k: len(v["rows"]) for k, v in datasets.items()},
               "model_id": model["model_id"], "alerts": len(predictions["alerts"]), "model_metrics": report["model"]}
    save_artifact(destination / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    print(json.dumps(run(parser.parse_args().destination), ensure_ascii=False, indent=2))
