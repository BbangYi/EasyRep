"""Private JSON-lines worker. Each reply releases neural weights from the GPU."""
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

from .core import digest, number, require


def main():
    kind, model_path, artifact_path = sys.argv[1:]
    require(kind in ('primary', 'sam3'), 'Unknown worker kind')
    model_path, artifact_path = Path(model_path), Path(artifact_path).resolve()
    import numpy as np
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoModel, AutoProcessor
    from .vision_sam3 import normalise_masks, clear_position_caches, select_sam3_queries, park_frozen_weights
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    require(torch.backends.mps.is_available(), 'MPS unavailable; no automatic CPU fallback')
    torch.mps.manual_seed(42)
    torch.mps.set_per_process_memory_fraction(min(.25, 3 * 1024**3 / torch.mps.recommended_max_memory()))
    started = perf_counter()
    with redirect_stdout(sys.stderr):
        if kind == 'primary':
            require(transformers.__version__ == '4.57.1', 'Primary runtime differs')
            from .vision_hybrid import HybridPredictor, load_hybrid_bundle
            model = HybridPredictor(model_path, load_hybrid_bundle(model_path), 'mps')
        else:
            require(transformers.__version__ == '5.20.2', 'SAM3 runtime differs')
            model, loading = AutoModel.from_pretrained(model_path, local_files_only=True, trust_remote_code=False,
                dtype=torch.float16, attn_implementation='sdpa', output_loading_info=True)
            require(not any(loading.get(key) for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')), 'Incomplete SAM3 weights')
            model.eval().requires_grad_(False)
            processor = AutoProcessor.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)

    cpu_weights = {}
    def park():
        if kind == 'primary':
            cpu_weights['detector'] = park_frozen_weights(model.detector, cpu_weights.get('detector'))
            cpu_weights['encoder'] = park_frozen_weights(model.encoder, cpu_weights.get('encoder'))
            model.mean, model.std = model.mean.cpu(), model.std.cpu()
        else:
            cpu_weights['sam3'] = park_frozen_weights(model, cpu_weights.get('sam3'))
            clear_position_caches(model)
        torch.mps.synchronize()
        torch.mps.empty_cache()
        return dict(current_bytes=torch.mps.current_allocated_memory(), driver_bytes=torch.mps.driver_allocated_memory(),
                    cpu_cached_weight_bytes=sum(t.numel() * t.element_size() for state in cpu_weights.values() for t in state.values()),
                    weight_parking_revision=2)

    def primary_request(request, image):
        from .vision_verifier import padded_crop_box, crop_verifier_image, score_feature_vector
        model.encoder.to('mps')
        model.mean, model.std = model.mean.to('mps'), model.std.to('mps')
        if request['operation'] == 'detect':
            model.detector.to('mps')
            predictions, evidence = model.predict_frame(np.asarray(image)[:, :, ::-1].copy())
            return dict(predictions=predictions, inference=evidence)
        require(request['operation'] == 'verify', 'Unknown primary operation')
        arrays, details = [], []
        for proposal in request['proposals']:
            crop = padded_crop_box(proposal['xyxy'], image.width, image.height)
            prepared = crop_verifier_image(image, crop)
            arrays.append(np.asarray(prepared, dtype=np.float32).transpose(2, 0, 1) / 255)
            details.append(dict(crop_xyxy=crop, crop_rgb_sha256=hashlib.sha256(prepared.tobytes()).hexdigest()))
        scores = []
        for offset in range(0, len(arrays), 16):
            batch = arrays[offset:offset + 16]
            count = len(batch)
            tensor = torch.from_numpy(np.stack(batch + [batch[-1]] * (16 - count))).to('mps')
            with torch.inference_mode():
                features = model.encoder(pixel_values=(tensor - model.mean) / model.std).last_hidden_state[:, 0, :]
            require(features.shape == (16, 384) and bool(torch.isfinite(features).all()), 'Invalid crop features')
            scores.extend(score_feature_vector(row.tolist(), model.card['head']) for row in features[:count].cpu().numpy())
        return dict(scores=scores, crops=details)

    def sam3_request(request, image):
        from torchvision.ops import nms
        require(request['operation'] == 'segment', 'Unknown SAM3 operation')
        name = request['mask_name']
        require(Path(name).name == name and name.endswith('.npz'), 'Invalid mask artifact name')
        model.to('mps')
        inputs = processor(images=image, text='lizard', return_tensors='pt').to('mps', dtype=torch.float16)
        require(list(inputs['pixel_values'].shape[-2:]) == [1008, 1008], 'SAM3 resolution changed')
        with torch.inference_mode():
            outputs = model(**inputs)
        for key in ('pred_boxes', 'pred_logits', 'pred_masks', 'presence_logits'):
            tensor = getattr(outputs, key)
            require(bool(torch.isfinite(tensor).all()), 'Nonfinite SAM3 output')
            setattr(outputs, key, tensor.detach().float().cpu())
        postprocess_started = perf_counter()
        outputs, query_filter = select_sam3_queries(outputs)
        processed = processor.post_process_instance_segmentation(outputs, threshold=.05, mask_threshold=.5,
            target_sizes=[(image.height, image.width)])[0]
        require(len(processed['boxes']) == len(processed['scores']), 'SAM3 proposal count differs')
        masks = normalise_masks(processed['masks'].cpu().numpy(), len(processed['scores']), width=image.width, height=image.height)
        native = []
        for index, (box, score) in enumerate(zip(processed['boxes'].tolist(), processed['scores'].tolist(), strict=True)):
            clipped = [max(0., min(float(value), image.size[k % 2])) for k, value in enumerate(box)]
            if clipped[2] > clipped[0] and clipped[3] > clipped[1]:
                native.append(dict(xyxy=clipped, confidence=score, mask_index=index))
        kept = nms(torch.tensor([p['xyxy'] for p in native], dtype=torch.float32),
                   torch.tensor([p['confidence'] for p in native], dtype=torch.float32), .5).tolist() if native else []
        path = artifact_path / 'masks' / name
        with path.open('xb') as stream:
            np.savez_compressed(stream, masks=masks)
        return dict(predictions=[native[i] for i in kept], raw_predictions=native, nms_indices=kept,
                    mask_name=name, mask_sha256=digest(path), mask_shape=list(masks.shape),
                    postprocess_revision=2, query_filter=query_filter,
                    postprocess_seconds=perf_counter() - postprocess_started,
                    mask_coordinate_system='original source pixels', prompt='lizard')

    print(json.dumps(dict(id=0, ok=True, runtime=transformers.__version__, load_seconds=perf_counter() - started,
                          idle_mps=park())), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        request_started = perf_counter()
        try:
            budget = number(request['mps_limit_bytes'], 1, 3 * 1024**3)
            torch.mps.set_per_process_memory_fraction(budget / torch.mps.recommended_max_memory())
            path = Path(request['image']).resolve()
            require(path.parent == artifact_path / 'frames', 'Frame path outside worker workspace')
            require(digest(path) == request['image_sha256'], 'Frame bytes changed before inference')
            with Image.open(path) as source:
                image = source.convert('RGB')
            with redirect_stdout(sys.stderr):
                result = primary_request(request, image) if kind == 'primary' else sam3_request(request, image)
                idle = park()
            require(digest(path) == request['image_sha256'], 'Frame bytes changed during inference')
            print(json.dumps(dict(result, id=request['id'], ok=True, image_sha256=request['image_sha256'],
                seconds=perf_counter() - request_started, idle_mps=idle, mps_limit_bytes=int(budget)), allow_nan=False), flush=True)
        except Exception as exc:
            print(json.dumps(dict(id=request.get('id'), ok=False, error=type(exc).__name__ + ': ' + str(exc))), flush=True)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
