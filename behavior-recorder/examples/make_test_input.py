"""Create only a 2-second, 160x120 synthetic clip. Never opens a camera."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from behavior_recorder.core import atomic_json, digest

parser = argparse.ArgumentParser()
parser.add_argument("inbox", type=Path)
args = parser.parse_args()
args.inbox.mkdir(parents=True, exist_ok=True)
video = args.inbox / "synthetic-001.mp4"
subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5",
                "-t", "2", "-c:v", "mpeg4", "-threads", "1", "-q:v", "8", str(video)], check=True, timeout=20)
atomic_json(args.inbox / "synthetic-001.capture.json", {
    "schema_version": 1, "input_id": "synthetic-input-001", "camera_id": "rgb-01", "file": video.name,
    "sha256": digest(video), "recording_id": "synthetic-recording-001", "sequence": 0,
    "provenance": "synthetic_test", "captured_at": None,
    "capture_clock": {"source": "unknown", "accuracy_ms": None},
    "placement_revision": None, "calibration_revision": None,
})
print(args.inbox / "synthetic-001.capture.json")
