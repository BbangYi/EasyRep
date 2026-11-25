import tempfile
import unittest
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from behavior_recorder.behavior_windows import window_observations
from behavior_recorder.core import RecorderError, atomic_json
from behavior_recorder.vision_lab import Lab, process_job
from behavior_recorder import vision_lab


class MemoryLabTests(unittest.TestCase):
    def lab(self, directory, device="mps"):
        with patch("behavior_recorder.vision_lab.MODELS", {}):
            lab = Lab(directory, device=device, load_catalog=False)
        lab.models = [{"key": "memory_lizard_v8", "model_id": "memory-id", "species": "lizard"}]
        atomic_json(lab.storage / "uploads/test.json", {"sha256": "a" * 64, "name": "test.mp4", "suffix": ".mp4"})
        return lab

    def request(self):
        return {"upload_id": "test", "model": "memory_lizard_v8", "provenance": "synthetic_test", "context": {}}

    def test_memory_job_retains_backend_and_evaluated_two_fps_config(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            job = lab.create_job(self.request())
            self.assertEqual(job.get("backend"), "sam2-hybrid")
            self.assertEqual(job["tracking_config"]["sample_fps"], 2)
            self.assertEqual(job["tracking_config"]["camera_motion"], "background-affine-v1")
            self.assertEqual(job["tracking_config"]["confidence"], .4)
            self.assertEqual(lab.create_job(self.request())["id"], job["id"])
            lab.jobs[job["id"]]["state"] = "failed"
            retry = lab.retry_job(job["id"])
            self.assertNotEqual(retry["id"], job["id"])
            self.assertEqual(retry["backend"], "sam2-hybrid")

    def test_cpu_rejection_happens_before_job_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory, "cpu")
            with self.assertRaisesRegex(RecorderError, "MPS"):
                lab.create_job(self.request())
            self.assertEqual(lab.jobs, {})

    def test_memory_catalog_uses_memory_manifest_and_reports_cpu_unavailability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            model.mkdir()
            (model / "model-card.json").write_text("{}")
            card = {"model_id": "memory-id", "species": "lizard"}
            with patch("behavior_recorder.vision_lab.ROOT", root), \
                 patch("behavior_recorder.vision_lab.MODELS", {"memory_lizard_v8": ("Memory", "model")}), \
                 patch("behavior_recorder.vision_memory.load_memory_bundle", return_value=(card, {}, {})):
                lab = Lab(root / "lab", device="cpu", load_catalog=False)
            self.assertEqual(len(lab.models), 1)
            self.assertEqual(lab.models[0]["backend"], "sam2-hybrid")
            self.assertFalse(lab.models[0]["available"])

    def test_withheld_motion_never_becomes_behavior_training_data(self):
        summary = {"model_id": "memory-id", "motion_measurement": "withheld_experimental_memory",
                   "source": {"duration_seconds": 5, "sha256": "a" * 64, "provenance": "real_camera"},
                   "config": {"max_gap_seconds": .6, "zones": {}}}
        # Even stale/non-null movement fields must not override the run's explicit abstention.
        observations = [{"offset_seconds": i / 2, "status": "observed", "track_id": 1,
                         "center": [.2 + i / 100, .5], "speed_diagonals_per_second": .1}
                        for i in range(10)]
        window = window_observations(summary, observations, {}, window_seconds=5)["windows"][0]
        self.assertEqual(window["quality_reason"], "measurement_withheld")
        self.assertIsNone(window["features"])
        self.assertEqual(window["coverage"], 0)

    def test_worker_dispatches_memory_and_rejects_backend_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            video = lab.storage / "uploads/test.mp4"
            video.write_bytes(b"video fixture")
            from behavior_recorder.core import digest
            atomic_json(lab.storage / "uploads/test.json", {"sha256": digest(video), "name": "test.mp4", "suffix": ".mp4"})
            job = lab.create_job(self.request())
            with patch("behavior_recorder.vision_lab.load_registered_card", return_value={"model_id": "memory-id"}), \
                 patch("behavior_recorder.vision_video.infer_video", side_effect=RuntimeError("dispatch reached")) as infer:
                with self.assertRaisesRegex(RuntimeError, "dispatch reached"):
                    process_job(lab.storage, job["id"])
                self.assertEqual(infer.call_args.kwargs["backend"], "sam2-hybrid")
                self.assertEqual(infer.call_args.kwargs["threads"], 1)
                job["backend"] = "yolo"
                lab.persist_job(job)
                with self.assertRaisesRegex(RecorderError, "backend changed"):
                    process_job(lab.storage, job["id"])
                self.assertEqual(infer.call_count, 1)

    @unittest.skipUnless(os.name == "posix", "Process groups require POSIX")
    def test_stopping_job_also_stops_descendant_ignoring_term(self):
        stop_process = getattr(vision_lab, "stop_job_process", None)
        self.assertTrue(callable(stop_process), "Job shutdown must stop neural descendants")
        child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
        parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(60)"
        process = subprocess.Popen([sys.executable, "-c", parent, child],
                                   start_new_session=True, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            stop_process(process)
            # A surviving grandchild would keep stdout open and time out here.
            process.communicate(timeout=2)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
