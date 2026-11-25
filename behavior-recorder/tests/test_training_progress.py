"""Training evidence must describe work performed, including interrupted passes."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from behavior_recorder.core import RecorderError, read_json
from behavior_recorder.vision_model import TrainingProgress, train, validate_training_options


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires PyTorch")
class TrainingProgressTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "progress.json"
        self.parameter = torch.nn.Parameter(torch.tensor([1.0]))
        self.optimizer = torch.optim.SGD([self.parameter], lr=0.1)
        self.trainer = SimpleNamespace(device=torch.device("cpu"), amp=False,
            scaler=torch.amp.GradScaler("cpu", enabled=False), optimizer=self.optimizer,
            train_loader=[None] * 3, batch_size=2, epoch=0)

    def test_partial_pass_and_validation_do_not_inflate_completed_passes(self):
        progress = TrainingProgress(self.path, amp=False)
        progress.start(self.trainer)
        progress.epoch_start(self.trainer)
        for _ in range(3):
            self.parameter.grad = self.torch.ones_like(self.parameter)
            self.optimizer.step()
            progress.batch_end(self.trainer)
        progress.epoch_end(self.trainer)
        self.trainer.epoch = 1
        progress.epoch_start(self.trainer)
        progress.batch_end(self.trainer)  # accumulated gradient; no optimizer step
        progress.epoch_end(self.trainer)
        progress.epoch_end(self.trainer)  # repeated end/validation must not add work
        progress.finish(completed=True)
        evidence = read_json(self.path)
        self.assertEqual(evidence["batches"], 4)
        self.assertEqual(evidence["optimizer_steps"], 3)
        self.assertEqual(evidence["full_passes_processed"], 1)
        self.assertEqual([a["batches"] for a in evidence["epoch_attempts"]], [3, 1])
        self.optimizer.step()  # hook removed after completion
        self.assertEqual(progress.stats["optimizer_steps"], 3)

    def test_scaler_skipped_step_is_not_counted_as_weight_update(self):
        progress = TrainingProgress(self.path, amp=False)
        progress.start(self.trainer)
        scaler = self.torch.amp.GradScaler("cpu", init_scale=8)
        scaler.scale(self.parameter.sum()).backward()
        scaler.step(self.optimizer)
        scaler.update()
        self.optimizer.zero_grad()
        scaler.scale(self.parameter.sum() * float("inf")).backward()
        scaler.step(self.optimizer)
        scaler.update()
        progress.finish(completed=False)
        self.assertEqual(read_json(self.path)["optimizer_steps"], 1)
        self.assertEqual(read_json(self.path)["state"], "failed")

    def test_amp_fallback_is_rejected_before_any_training(self):
        progress = TrainingProgress(self.path, amp=True)
        with self.assertRaisesRegex(RecorderError, "AMP"):
            progress.start(self.trainer)
        progress.finish(completed=False)
        self.assertEqual(read_json(self.path)["optimizer_steps"], 0)

    def test_epoch_retry_keeps_processed_batches_without_claiming_full_pass(self):
        progress = TrainingProgress(self.path, amp=False)
        progress.start(self.trainer)
        progress.epoch_start(self.trainer)
        progress.batch_end(self.trainer)
        self.trainer.train_loader = [None] * 6
        self.trainer.batch_size = 1
        progress.epoch_start(self.trainer)  # framework retried same epoch after OOM
        for _ in range(6):
            progress.batch_end(self.trainer)
        progress.epoch_end(self.trainer)
        progress.finish(completed=False)
        evidence = read_json(self.path)
        self.assertEqual(evidence["batches"], 7)
        self.assertEqual(evidence["full_passes_processed"], 1)
        self.assertEqual([a["batch_size"] for a in evidence["epoch_attempts"]], [2, 1])
        self.assertFalse(evidence["epoch_attempts"][0]["ended"])

    def test_missing_telemetry_cannot_be_reported_as_complete(self):
        progress = TrainingProgress(self.path, amp=False)
        with self.assertRaisesRegex(RecorderError, "without recorded"):
            progress.finish(completed=True)
        self.assertEqual(read_json(self.path)["state"], "failed")

    def test_requested_cpu_threads_are_observed_before_training(self):
        original = self.torch.get_num_threads()
        self.addCleanup(self.torch.set_num_threads, original)
        self.torch.set_num_threads(2)
        progress = TrainingProgress(self.path, amp=False, expected_threads=2)
        progress.start(self.trainer)
        self.addCleanup(progress.finish, completed=False)
        self.assertEqual(read_json(self.path)['actual_torch_threads'], 2)

    def test_cpu_parallelism_change_is_rejected_before_next_epoch(self):
        original = self.torch.get_num_threads()
        self.addCleanup(self.torch.set_num_threads, original)
        self.torch.set_num_threads(2)
        progress = TrainingProgress(self.path, amp=False, expected_threads=1)
        with self.assertRaisesRegex(RecorderError, 'thread'):
            progress.start(self.trainer)
        progress = TrainingProgress(self.path, amp=False, expected_threads=2)
        progress.start(self.trainer)
        self.addCleanup(progress.finish, completed=False)
        self.torch.set_num_threads(4)
        with self.assertRaisesRegex(RecorderError, 'thread'):
            progress.epoch_start(self.trainer)
        self.assertEqual(progress.stats['batches'], 0)


class TrainingPrecisionOptionTests(unittest.TestCase):
    def test_nominal_batch_requires_a_bounded_integer(self):
        for value in (1, 2, 64, 128):
            self.assertEqual(validate_training_options({"nbs": value}), {"nbs": value})
        for invalid in (0, -1, 129, True, 2.0, "2", None):
            with self.subTest(value=invalid), self.assertRaises(RecorderError):
                validate_training_options({"nbs": invalid})

    def test_amp_requires_explicit_boolean(self):
        self.assertEqual(validate_training_options({"amp": True}), {"amp": True})
        for invalid in (1, "true", None):
            with self.subTest(value=invalid), self.assertRaises(RecorderError):
                validate_training_options({"amp": invalid})

    def test_non_cuda_amp_is_rejected_before_reading_any_dataset(self):
        for device in ("cpu", "mps"):
            with self.subTest(device=device), self.assertRaisesRegex(RecorderError, "explicit CUDA"):
                train("not-read", "not-read.pt", "not-created", device=device, training_options={"amp": True})
