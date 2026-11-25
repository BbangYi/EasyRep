"""Offline Grounding DINO + DINOv2 + learned hinge score backend.

The package binds weights, preprocessing and both learned heads. This remains an
experimental lizard detector, not a species, identity, health or anomaly model.
"""
import hashlib
import math
import os
from pathlib import Path
from time import perf_counter

from .analysis_features import fingerprint
from .core import digest, number, read_json, relative, require
from .vision_verifier import crop_verifier_image, padded_crop_box, score_feature_vector


SETTINGS = dict(prompt="a lizard.", raw_confidence=.1, text_threshold=.3, nms_iou=.5,
                processor_size=dict(longest_edge=640, shortest_edge=640))
DETECTOR_FILES = ("model.safetensors", "config.json", "preprocessor_config.json",
                  "tokenizer_config.json", "tokenizer.json", "special_tokens_map.json",
                  "added_tokens.json", "vocab.txt")
ENCODER_FILES = ("model.safetensors", "config.json")


def load_hybrid_bundle(directory):
    directory = Path(directory).resolve()
    card = read_json(directory/"model-card.json")
    require(card["schema_version"] == 1 and card["backend"] == "grounding-dinov2-hinge" and
            card["species"] == "lizard" and card["status"] == "experimental" and
            card["production_validated"] is False, "unsupported hybrid model card")
    require(card["package_id"] == fingerprint({k:v for k,v in card.items() if k != "package_id"}),
            "hybrid package identity differs")
    require(card["settings"] == SETTINGS and card["recipe"] == dict(image_size=640),
            "unvalidated hybrid inference settings")
    files = card["files"]
    required = {"detector/"+n for n in DETECTOR_FILES}
    required |= {"encoder/"+n for n in ENCODER_FILES} | {"verifier.json", "joint.json"}
    require(isinstance(files, dict) and required <= files.keys() and len(files) <= 64,
            "hybrid component inventory is incomplete")
    for name, checksum in files.items():
        path = relative(directory, name)
        require(path.is_file() and path.stat().st_size <= 1024**3 and digest(path) == checksum,
                "hybrid component changed: " + name)
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    require(actual == set(files) | {"model-card.json"}, "unlisted hybrid package file")
    verifier, joint = read_json(directory/"verifier.json"), read_json(directory/"joint.json")
    for component in (verifier, joint):
        require(component["model_id"] == fingerprint({k:v for k,v in component.items() if k != "model_id"}),
                "learned component identity differs")
        number(component["threshold"], 1e-12, 1-1e-12)
    require(verifier["kind"] == "experimental_crop_presence_verifier" and
            joint["kind"] == "experimental_hinge_proposal_score", "unsupported learned components")
    require(verifier["head"]["feature_dim"] == 384 and joint["head"]["feature_dim"] == 3 and
            joint["input_features"] == ["logit_detector","logit_verifier","min(logit_verifier,0)"] and
            joint["output_gate"] == .4, "unsupported learned feature layout")
    score_feature_vector([0.0]*384, verifier["head"])
    score_feature_vector([0.0]*3, joint["head"])
    require(verifier["preprocessing"]["detected_box_padding_fraction_per_side"] == .1 and
            verifier["preprocessing"]["mean"] == [.485,.456,.406] and
            verifier["preprocessing"]["std"] == [.229,.224,.225], "unvalidated crop preprocessing")
    require(joint["verifier_model_sha256"] == files["verifier.json"] and
            joint["detector_weights_sha256"] == files["detector/model.safetensors"] and
            verifier["backbone"]["sha256"] == files["encoder/model.safetensors"] and
            verifier["backbone"]["config_sha256"] == files["encoder/config.json"] and
            card["model_id"] == joint["model_id"], "hybrid components are not bound to this candidate")
    return card, verifier, joint


def validate_hybrid_config(config):
    require(config["confidence"] == .4 and config.get("nms_iou", .5) == .5 and
            config.get("inference_image_size", 640) == 640 and
            config.get("inference_slicing", "off") == "off", "hybrid requires its frozen score and geometry settings")


def score_features(detector_score, verifier_score):
    values = [number(detector_score, 0, 1), number(verifier_score, 0, 1)]
    logits = [math.log(max(1e-6, min(1-1e-6, p))) -
            math.log1p(-max(1e-6, min(1-1e-6, p))) for p in values]
    return logits + [min(logits[1], 0.0)]


def fuse_predictions(proposals, details, head, threshold):
    number(threshold, 1e-12, 1-1e-12)
    require(len(proposals) == len(details), "proposal detail count differs")
    require(head["feature_dim"] == 3, "hinge model requires three score features")
    predictions, evidence = [], []
    for index, (proposal, detail) in enumerate(zip(proposals, details)):
        require(detail["prediction_index"] == index, "proposal detail order differs")
        if detail["feature_index"] is None:
            require(not detail.get("accepted", False), "outside proposal was accepted")
            continue
        require(type(detail["feature_index"]) is int and detail["feature_index"] >= 0, "invalid feature index")
        box = detail["clipped_proposal"]
        require(box["confidence"] == proposal["confidence"], "raw confidence differs")
        require(len(box["xyxy"]) == 4, "invalid clipped geometry")
        x1, y1, x2, y2 = [number(v, 0, 1e8) for v in box["xyxy"]]
        require(x1 < x2 and y1 < y2, "empty clipped geometry")
        features = score_features(proposal["confidence"], detail["verifier_score"])
        score = max(1e-6, min(1-1e-6, score_feature_vector(features, head)))
        # Preserve the learned decision boundary exactly at the existing tracker gate.
        logit = score_features(score, threshold)
        shifted = logit[0] - logit[1] + math.log(.4/.6)
        mapped = 1/(1+math.exp(-shifted)) if shifted >= 0 else math.exp(shifted)/(1+math.exp(shifted))
        if score >= threshold:
            mapped = max(.4, mapped)
        else:
            mapped = min(math.nextafter(.4, 0), mapped)
        predictions.append(dict(xyxy=list(box["xyxy"]), confidence=mapped))
        evidence.append(dict(prediction_index=index, raw_detector_confidence=proposal["confidence"],
            verifier_score=detail["verifier_score"], joint_score=score, confidence=mapped))
    return predictions, evidence


def clip_proposal(proposal, width, height):
    require(type(width) is int and width > 0 and type(height) is int and height > 0,
            "invalid image dimensions")
    box = proposal["xyxy"]
    require(isinstance(box, (list, tuple)) and len(box) == 4, "box requires four coordinates")
    x1, y1, x2, y2 = [number(v, -1e8, 1e8) for v in box]
    confidence = number(proposal["confidence"], 0, 1)
    require(x1 < x2 and y1 < y2, "empty detector box")
    clipped = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        return None
    return dict(xyxy=clipped, confidence=confidence)


class HybridPredictor:
    def __init__(self, directory, bundle, device):
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                          HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        import numpy as np
        import torch
        import transformers
        from torchvision.ops import nms
        from transformers import AutoConfig, AutoModel, AutoModelForZeroShotObjectDetection, AutoProcessor

        require(transformers.__version__ == "4.57.1", "hybrid requires transformers 4.57.1")
        require(device in ("cpu", "mps") or (isinstance(device, str) and device.isdigit()),
                "hybrid device must be cpu, mps, or one CUDA index")
        package, card, joint = bundle
        self.torch, self.np, self.nms = torch, np, nms
        self.request, self.card, self.joint = package["settings"], card, joint
        self.package_id = package["package_id"]
        self.device = device if device in ("cpu", "mps") else "cuda:" + device
        self.mps_allocator_limit_bytes = None
        if device == "mps":
            require(torch.backends.mps.is_available(), "requested MPS device is unavailable; no silent CPU fallback")
            require(os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") == "0",
                    "hybrid MPS requires automatic CPU fallback disabled before starting Python")
            recommended = number(torch.mps.recommended_max_memory(), 1, 1e15)
            fraction = min(.25, 3 * 1024**3 / recommended)
            torch.mps.set_per_process_memory_fraction(fraction)
            self.mps_allocator_limit_bytes = int(fraction * recommended)
            # Torchvision NMS runs explicitly on CPU; both neural models stay on MPS.
            self.nms = lambda boxes, scores, iou: nms(boxes.cpu(), scores.cpu(), iou).to(boxes.device)
        runtime = Path(directory)/"detector"
        model_dir = Path(directory)/"encoder"
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        config = AutoConfig.from_pretrained(runtime, local_files_only=True, trust_remote_code=False)
        config.disable_custom_kernels = True
        self.processor = AutoProcessor.from_pretrained(
            runtime, local_files_only=True, trust_remote_code=False, use_fast=False)
        self.detector = AutoModelForZeroShotObjectDetection.from_pretrained(
            runtime, config=config, local_files_only=True, trust_remote_code=False,
            use_safetensors=True).eval().requires_grad_(False).to(self.device)
        self.encoder = AutoModel.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False, use_safetensors=True,
            attn_implementation="eager").eval().requires_grad_(False).to(self.device)
        self.mean = torch.tensor(card["preprocessing"]["mean"], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor(card["preprocessing"]["std"], device=self.device).view(1, 3, 1, 1)
        require(all(next(m.parameters()).dtype == torch.float32 for m in [self.detector, self.encoder]),
                "unexpected inference precision")

    def predict(self, image):
        torch, np = self.torch, self.np
        if self.device == "mps":
            # Different frame shapes otherwise retain allocator blocks across calls.
            torch.mps.synchronize()
            torch.mps.empty_cache()
        image = image.convert("RGB")
        inputs = self.processor(images=image, text=self.request["prompt"], return_tensors="pt",
                                size=self.request["processor_size"]).to(self.device)
        require(max(inputs["pixel_values"].shape[-2:]) <= 640, "unexpected detector image size")
        with torch.inference_mode():
            output = self.detector(**inputs)
        grounded = self.processor.post_process_grounded_object_detection(
            output, inputs.input_ids, threshold=self.request["raw_confidence"],
            text_threshold=self.request["text_threshold"], target_sizes=[(image.height, image.width)])[0]
        boxes, scores = grounded["boxes"], grounded["scores"]
        require(bool(torch.isfinite(boxes).all() and torch.isfinite(scores).all()), "non-finite output")
        keep = self.nms(boxes, scores, self.request["nms_iou"])
        raw = [dict(xyxy=[float(v) for v in boxes[i].cpu().tolist()], confidence=float(scores[i].cpu()))
               for i in keep]
        del inputs, output, grounded
        bounded, details, arrays = [], [], []
        for index, proposal in enumerate(raw):
            clipped = clip_proposal(proposal, image.width, image.height)
            if clipped is None:
                details.append(dict(prediction_index=index, accepted=False, reason="outside_image",
                                    verifier_score=None, crop_xyxy=None, feature_index=None))
                continue
            crop = padded_crop_box(proposal["xyxy"], image.width, image.height)
            prepared = crop_verifier_image(image, crop)
            details.append(dict(prediction_index=index, clipped_proposal=clipped, crop_xyxy=crop,
                                crop_rgb_sha256=hashlib.sha256(prepared.tobytes()).hexdigest(),
                                feature_index=len(arrays)))
            arrays.append(np.asarray(prepared, dtype=np.float32).transpose(2, 0, 1) / 255)
            bounded.append(clipped)
        chunks = []
        for offset in range(0, len(arrays), 16):
            batch = arrays[offset:offset + 16]
            count = len(batch)
            batch = batch + [batch[-1]] * (16 - count)
            tensor = torch.from_numpy(np.stack(batch)).to(self.device)
            with torch.inference_mode():
                features = self.encoder(pixel_values=(tensor - self.mean) / self.std).last_hidden_state[:, 0, :]
            require(features.shape == (16, 384) and bool(torch.isfinite(features).all()), "invalid features")
            chunks.append(features[:count].cpu().numpy())
        matrix = np.concatenate(chunks) if chunks else np.empty((0, 384), dtype=np.float32)
        accepted = []
        for detail in details:
            if detail["feature_index"] is None:
                continue
            score = score_feature_vector(matrix[detail["feature_index"]].tolist(), self.card["head"])
            detail.update(verifier_score=score, accepted=score >= self.card["threshold"])
            if detail["accepted"]:
                accepted.append(detail["clipped_proposal"])
        return dict(raw_predictions=raw, bounded_predictions=bounded, predictions=accepted,
                    verifier_details=details), matrix

    def predict_frame(self, frame):
        import cv2
        from PIL import Image
        started = perf_counter()
        result, matrix = self.predict(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        boxes, joint_details = fuse_predictions(result["raw_predictions"], result["verifier_details"],
                                                self.joint["head"], self.joint["threshold"])
        if self.device == "mps":
            self.torch.mps.synchronize()
        evidence = dict(actual_device=self.device, seconds=perf_counter()-started,
            model="grounding-dinov2-hinge", package_id=self.package_id,
            raw_grounding_predictions=result["raw_predictions"], verifier_details=result["verifier_details"],
            joint_details=joint_details, feature_rows=len(matrix), detector_windows=1)
        if self.device == "mps":
            evidence.update(nms_device="cpu", mps_allocator_limit_bytes=self.mps_allocator_limit_bytes,
                            mps_cache_cleared_per_frame=True)
        return boxes, evidence
