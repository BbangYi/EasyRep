import importlib
import json
import math
import io
import os
import sys
from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from behavior_recorder.analysis_features import fingerprint
from behavior_recorder.core import RecorderError, atomic_json, digest


class HybridTests(unittest.TestCase):
    def setUp(self):
        try:
            self.hybrid = importlib.import_module("behavior_recorder.vision_hybrid")
        except ModuleNotFoundError:
            self.fail("selectable hybrid backend is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self):
        for folder in ("detector", "encoder"):
            (self.root/folder).mkdir()
            (self.root/folder/"model.safetensors").write_bytes(b"test-only inert model bytes")
            (self.root/folder/"config.json").write_text("{}\n")
        for name in ("preprocessor_config.json", "tokenizer_config.json", "tokenizer.json",
                     "special_tokens_map.json", "added_tokens.json", "vocab.txt"):
            (self.root/"detector"/name).write_text("{}\n")
        verifier = dict(
            kind="experimental_crop_presence_verifier", schema_version=1, threshold=.8,
            preprocessing=dict(detected_box_padding_fraction_per_side=.1,
                               mean=[.485,.456,.406], std=[.229,.224,.225]),
            head=dict(feature_dim=384, mean=[0]*384, std=[1]*384, active_indices=[0],
                      coefficients=[1], bias=0),
            backbone=dict(sha256=digest(self.root/"encoder/model.safetensors"),
                          config_sha256=digest(self.root/"encoder/config.json")))
        verifier["model_id"] = fingerprint(verifier)
        atomic_json(self.root/"verifier.json", verifier)
        joint = dict(kind="experimental_hinge_proposal_score", schema_version=1, threshold=.5,
                     output_gate=.4, input_features=["logit_detector","logit_verifier","min(logit_verifier,0)"],
                     detector_weights_sha256=digest(self.root/"detector/model.safetensors"),
                     verifier_model_sha256=digest(self.root/"verifier.json"),
                     head=dict(feature_dim=3, mean=[0]*3, std=[1]*3, active_indices=[0,1,2],
                               coefficients=[2,.5,1], bias=0))
        joint["model_id"] = fingerprint(joint)
        atomic_json(self.root/"joint.json", joint)
        card = dict(schema_version=1, backend="grounding-dinov2-hinge", species="lizard",
                    status="experimental", production_validated=False, model_id=joint["model_id"],
                    recipe=dict(image_size=640), settings=dict(prompt="a lizard.", raw_confidence=.1,
                    text_threshold=.3, nms_iou=.5, processor_size=dict(longest_edge=640,shortest_edge=640)),
                    files={p.relative_to(self.root).as_posix():digest(p)
                           for p in self.root.rglob("*") if p.is_file()})
        self.write_card(card)
        return card

    def write_card(self, card):
        card.pop("package_id", None)
        card["package_id"] = fingerprint(card)
        atomic_json(self.root/"model-card.json", card)

    def test_bundle_can_be_moved_and_tampered_weights_are_rejected(self):
        self.bundle()
        moved = self.root/"moved"
        moved.mkdir()
        for p in list(self.root.iterdir()):
            if p != moved:
                p.rename(moved/p.name)
        card, _, joint = self.hybrid.load_hybrid_bundle(moved)
        self.assertEqual(card["model_id"], joint["model_id"])
        (moved/"encoder/model.safetensors").write_bytes(b"changed")
        with self.assertRaises(RecorderError):
            self.hybrid.load_hybrid_bundle(moved)

    def test_packager_preserves_bound_files_and_refuses_overwrite(self):
        from scripts.package_hybrid_model import package_model
        self.bundle()
        destination = self.root/"portable"
        arguments = dict(detector=self.root/"detector", encoder=self.root/"encoder",
                         verifier=self.root/"verifier.json", joint=self.root/"joint.json",
                         output=destination)
        card = package_model(**arguments)
        loaded, _, _ = self.hybrid.load_hybrid_bundle(destination)
        self.assertEqual(card, loaded)
        before = digest(destination/"joint.json")
        with self.assertRaises(RecorderError):
            package_model(**arguments)
        self.assertEqual(digest(destination/"joint.json"), before)

    def test_packager_does_not_publish_mismatched_components(self):
        from scripts.package_hybrid_model import package_model
        self.bundle()
        (self.root/"encoder/model.safetensors").write_bytes(b"wrong checkpoint")
        destination = self.root/"portable"
        with self.assertRaises(RecorderError):
            package_model(detector=self.root/"detector", encoder=self.root/"encoder",
                          verifier=self.root/"verifier.json", joint=self.root/"joint.json",
                          output=destination)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob(".hybrid-package-*")))

    def test_bundle_cannot_reference_outside_files(self):
        card = self.bundle()
        card["files"]["../external.safetensors"] = "0"*64
        self.write_card(card)
        with self.assertRaises(RecorderError):
            self.hybrid.load_hybrid_bundle(self.root)

    def test_unbound_verifier_is_rejected_even_if_manifest_checksums_are_updated(self):
        card = self.bundle()
        verifier = json.loads((self.root/"verifier.json").read_text())
        verifier["threshold"] = .7
        verifier.pop("model_id")
        verifier["model_id"] = fingerprint(verifier)
        atomic_json(self.root/"verifier.json", verifier)
        card["files"]["verifier.json"] = digest(self.root/"verifier.json")
        self.write_card(card)
        with self.assertRaises(RecorderError):
            self.hybrid.load_hybrid_bundle(self.root)

    def test_unvalidated_slicing_or_confidence_cannot_silently_change_hybrid(self):
        config = dict(confidence=.4, inference_slicing="off", inference_image_size=640, nms_iou=.5)
        self.hybrid.validate_hybrid_config(config)
        for updates in (dict(confidence=.3), dict(inference_slicing="overlap-640-v1"),
                        dict(inference_image_size=960), dict(nms_iou=.3)):
            with self.assertRaises(RecorderError):
                self.hybrid.validate_hybrid_config(dict(config, **updates))

    def test_unavailable_mps_or_automatic_fallback_fails_before_loading_weights(self):
        import torch
        import torchvision.ops  # Load Torch introspection before replacing the MPS availability function.
        transformers = SimpleNamespace(__version__="4.57.1", AutoConfig=Mock(), AutoModel=Mock(),
            AutoModelForZeroShotObjectDetection=Mock(), AutoProcessor=Mock())
        bundle = ({"settings": {}, "package_id": "fixture"}, {}, {})
        for available, fallback, message in ((False, "0", "MPS device is unavailable"),
                                              (True, "1", "automatic CPU fallback disabled")):
            with self.subTest(available=available, fallback=fallback), \
                    patch.dict(sys.modules, {"transformers": transformers}), \
                    patch.dict(os.environ, {"PYTORCH_ENABLE_MPS_FALLBACK": fallback}), \
                    patch.object(torch.backends.mps, "is_available", return_value=available), \
                    patch.object(torch.mps, "set_per_process_memory_fraction") as memory_limit:
                with self.assertRaisesRegex(RecorderError, message):
                    self.hybrid.HybridPredictor(self.root, bundle, "mps")
                memory_limit.assert_not_called()
        transformers.AutoConfig.from_pretrained.assert_not_called()
        transformers.AutoModel.from_pretrained.assert_not_called()
        transformers.AutoModelForZeroShotObjectDetection.from_pretrained.assert_not_called()

    def test_hinge_can_reject_strong_detector_and_preserve_box_boundary(self):
        self.bundle()
        _, _, joint = self.hybrid.load_hybrid_bundle(self.root)
        p = dict(xyxy=[1,2,9,10], confidence=.9)
        d = dict(prediction_index=0, feature_index=0, verifier_score=.01, clipped_proposal=p)
        boxes, detail = self.hybrid.fuse_predictions([p], [d], joint["head"], .5)
        self.assertEqual(boxes[0]["xyxy"], [1,2,9,10])
        self.assertLess(boxes[0]["confidence"], .4)
        self.assertLess(detail[0]["joint_score"], .1)
        joint["head"]["coefficients"] = [0,1,0]
        d["verifier_score"] = .8
        boxes, _ = self.hybrid.fuse_predictions([p], [d], joint["head"], .8)
        self.assertAlmostEqual(boxes[0]["confidence"], .4)

    def test_invalid_proposal_order_and_nonfinite_scores_fail(self):
        self.bundle()
        _, _, joint = self.hybrid.load_hybrid_bundle(self.root)
        p = dict(xyxy=[1,2,9,10], confidence=.9)
        d = dict(prediction_index=1, feature_index=0, verifier_score=.8, clipped_proposal=p)
        with self.assertRaises(RecorderError):
            self.hybrid.fuse_predictions([p], [d], joint["head"], .8)
        with self.assertRaises(RecorderError):
            self.hybrid.score_features(.9, math.nan)

    def test_public_cli_preserves_scores_and_withholds_motion_on_low_confidence(self):
        import cv2
        import numpy as np
        from behavior_recorder.vision import main
        self.bundle()
        model = self.root/"model"
        model.mkdir()
        for p in list(self.root.iterdir()):
            if p != model:
                p.rename(model/p.name)
        source = self.root/"source.mp4"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 3, (100,100))
        self.assertTrue(writer.isOpened())
        for _ in range(5):
            writer.write(np.zeros((100,100,3), dtype=np.uint8))
        writer.release()
        config = dict(schema_version=1, species="lizard", sample_fps=3, confidence=.4,
                      max_step_diagonals=.15, max_gap_seconds=.6, zones={})
        atomic_json(self.root/"tracking.json", config)

        class NeuralFixture:
            """Only replace expensive neural inference; use real media and tracker."""
            def __init__(self, directory, bundle, device):
                self.index = 0

            def predict_frame(self, frame):
                index = self.index
                self.index += 1
                boxes = [] if index == 0 else [dict(xyxy=[10 if index == 1 else 16, 10,
                    30 if index == 1 else 36, 30], confidence=[.45, .41, .9, .2][index - 1])]
                return boxes, dict(
                    actual_device="cpu", seconds=0, model="synthetic_neural_fixture")

        output = self.root/"result"
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.hybrid, "HybridPredictor", NeuralFixture), redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(["infer", "--backend", "hybrid", "--model", str(model), "--video", str(source),
                             "--config", str(self.root/"tracking.json"), "--output", str(output),
                             "--device", "cpu", "--threads", "1", "--provenance", "synthetic_test"])
            except SystemExit:
                self.fail("public infer command does not accept the selectable backend")
        self.assertEqual(code, 0, stderr.getvalue())
        rows = [json.loads(line) for line in (output/"observations.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["detections"], [])
        self.assertEqual([r["detections"][0]["confidence"] for r in rows[1:]], [.45,.41,.9,.2])
        self.assertEqual(rows[2]["status"], "observed")
        self.assertIsNone(rows[2]["speed_diagonals_per_second"])
        self.assertEqual(rows[-1]["status"], "no_confident_track")
        self.assertIsNone(rows[-1]["step_diagonals"])
        summary = json.loads((output/"summary.json").read_text())
        self.assertEqual(summary["source"]["provenance"], "synthetic_test")
        self.assertEqual(summary["detector_backend"], "hybrid")
        self.assertFalse(summary["production_validated"])


if __name__ == "__main__":
    unittest.main()
