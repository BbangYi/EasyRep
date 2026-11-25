"""Private, bounded SAM2 session worker using the pinned native processor."""
from contextlib import redirect_stdout
import gc
from inspect import getclosurevars
import json
from pathlib import Path
import sys
from time import perf_counter

from .core import atomic_json, digest, number, require


def validate_memory_step(last, started, offset, frame_index, maximum_gap, *, retry_used, allow_refresh_retry):
    require(type(allow_refresh_retry) is bool, 'Invalid refresh retry flag')
    require(last is None or 0 < offset-last <= maximum_gap, 'Memory time gap requires reset')
    require(frame_index < 120, 'Memory frame limit exceeded')
    if offset-started >= 10:
        require(allow_refresh_retry and not retry_used and offset-started < 10+min(maximum_gap,.6),
                'Memory refresh deadline exceeded')
        return True
    require(not allow_refresh_retry, 'Refresh retry is only allowed at the refresh deadline')
    return retry_used


def main():
    model_path, artifact_path, maximum_gap = sys.argv[1:]
    model_path, artifact_path = Path(model_path), Path(artifact_path).resolve()
    maximum_gap = number(float(maximum_gap), .01, 10)
    import numpy as np
    import torch
    import transformers
    from torch.utils._pytree import tree_map_only
    from PIL import Image
    from transformers import Sam2VideoModel, Sam2VideoProcessor, Sam2VideoInferenceSession
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(42)
    require(transformers.__version__ == '5.20.2' and torch.backends.mps.is_available(), 'Measured SAM2 runtime unavailable')
    torch.mps.manual_seed(42)
    torch.mps.set_per_process_memory_fraction(3*1024**3/torch.mps.recommended_max_memory())
    with redirect_stdout(sys.stderr):
        model, loading = Sam2VideoModel.from_pretrained(model_path,local_files_only=True,trust_remote_code=False,
            dtype=torch.float16,attn_implementation='sdpa',output_loading_info=True)
        require(not any(loading.get(k) for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')),
                'Incomplete SAM2 model load')
        model.eval().requires_grad_(False)
        processor = Sam2VideoProcessor.from_pretrained(model_path,local_files_only=True,trust_remote_code=False)
    session, object_ids = None, []
    last_offset = started_offset = dimensions = None
    frame_index, resets, parks = 0, 0, 0
    retry_used = False

    def usage():
        torch.mps.synchronize()
        return dict(current_bytes=torch.mps.current_allocated_memory(),driver_bytes=torch.mps.driver_allocated_memory())

    def park():
        nonlocal parks
        if session is not None:
            # The pinned session keeps prompts and small object pointers on its inference device.
            for field in ('point_inputs_per_obj','mask_inputs_per_obj','output_dict_per_obj'):
                setattr(session,field,tree_map_only(torch.Tensor,lambda value:value.to('cpu'),getattr(session,field)))
        model.to('cpu')
        cleared = set()
        for module in model.modules():
            wrapper = getattr(module,'build_sine_position_embedding',None)
            if wrapper is not None:
                cached = getclosurevars(wrapper).nonlocals['func_with_cache']
                if id(cached) not in cleared:
                    cached.cache_clear()
                    cleared.add(id(cached))
        require(len(cleared) == 2, 'Pinned SAM2 positional caches differ')
        gc.collect()
        torch.mps.synchronize()
        torch.mps.empty_cache()
        idle = usage()
        require(idle['current_bytes'] == 0, 'Video memory GPU tensors survived CPU parking')
        parks += 1
        return idle

    def reset():
        nonlocal session, object_ids, last_offset, started_offset, dimensions, frame_index, resets, retry_used
        if session is not None:
            session.reset_inference_session()
        session, object_ids = None, []
        last_offset = started_offset = dimensions = None
        frame_index, retry_used = 0, False
        idle = park()
        resets += 1
        return idle

    def owned_path(value):
        path = Path(value).resolve()
        require(path.is_relative_to(artifact_path), 'Memory artifact escaped output directory')
        return path

    def predict(request):
        nonlocal session, object_ids, last_offset, started_offset, dimensions, frame_index, retry_used
        started = perf_counter()
        limit = number(request['mps_limit_bytes'],1,3*1024**3)
        torch.mps.set_per_process_memory_fraction(limit/torch.mps.recommended_max_memory())
        path = owned_path(request['image'])
        require(digest(path) == request['image_sha256'], 'Memory input changed')
        image = Image.open(path).convert('RGB')
        offset = number(request['offset_seconds'],0,3600)
        name = request['mask_name']
        require(isinstance(name,str) and Path(name).name == name and name.endswith('.npz'), 'Invalid memory mask name')
        destination = artifact_path/'masks'/name
        require(not destination.exists(), 'Memory mask output already exists')
        seed = request.get('seed')
        if seed is not None:
            reset()
            count = seed['count']
            require(type(count) is int and 1 <= count <= 16, 'Invalid memory object count')
            object_ids = list(range(1,count+1))
            dimensions = (image.height,image.width)
            session = Sam2VideoInferenceSession(video_height=image.height,video_width=image.width,
                inference_device='mps',inference_state_device='cpu',video_storage_device='cpu',
                dtype=torch.float16,max_vision_features_cache_size=1)
            if seed['kind'] == 'mask':
                seed_path = owned_path(seed['path'])
                require(digest(seed_path) == seed['sha256'], 'Seed masks changed')
                with np.load(seed_path,allow_pickle=False) as archive:
                    initial = archive['masks']
                require(initial.dtype == bool and initial.shape == (count,*dimensions)
                        and bool(initial.reshape(count,-1).any(axis=1).all()), 'Invalid seed masks')
                processor.add_inputs_to_inference_session(session,frame_idx=0,obj_ids=list(object_ids),
                                                          input_masks=[m.copy() for m in initial])
            else:
                require(seed['kind'] == 'box' and len(seed['boxes']) == count, 'Invalid box seed')
                for box in seed['boxes']:
                    require(len(box) == 4, 'Invalid seed box')
                    x1,y1,x2,y2 = box
                    for value in (x1,x2): number(value,0,image.width)
                    for value in (y1,y2): number(value,0,image.height)
                    require(x2>x1 and y2>y1, 'Degenerate seed box')
                processor.add_inputs_to_inference_session(session,frame_idx=0,obj_ids=list(object_ids),
                                                          input_boxes=[seed['boxes']])
            started_offset = offset
        require(session is not None and dimensions == (image.height,image.width), 'Memory needs a fresh seed')
        retry_used = validate_memory_step(last_offset,started_offset,offset,frame_index,maximum_gap,
            retry_used=retry_used,allow_refresh_retry=request.get('allow_refresh_retry',False))
        model.to('mps')
        tensors = processor(images=image,device='cpu',return_tensors='pt')
        with torch.inference_mode():
            output = model(inference_session=session,frame_idx=frame_index,frame=tensors.pixel_values[0].to(dtype=torch.float16))
        require(output.frame_idx == frame_index and list(output.object_ids) == object_ids, 'Memory object association differs')
        logits = output.object_score_logits.detach().float().cpu().reshape(-1)
        raw = output.pred_masks.detach().float().cpu()
        require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(raw).all()), 'Nonfinite memory output')
        masks = processor.post_process_masks([raw],original_sizes=[list(dimensions)],binarize=True,
                                             mask_threshold=0.,apply_non_overlapping_constraints=True)[0][:,0].numpy()
        require(masks.shape == (len(object_ids),*dimensions) and bool((masks.sum(axis=0)<=1).all()), 'Memory masks overlap or differ in shape')
        predictions, objects = [], []
        for slot, object_id in enumerate(object_ids):
            y,x = np.where(masks[slot])
            present = bool(logits[slot]>0) and bool(len(x))
            box = [int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1] if present else None
            objects.append(dict(object_slot=object_id,present=present,object_presence_logit=float(logits[slot]),mask_index=slot))
            if present:
                predictions.append(dict(xyxy=box,confidence=1.,object_slot=object_id,mask_index=slot,
                    confidence_semantics='binary mask presence; not a calibrated detection probability'))
        with destination.open('xb') as stream:
            np.savez_compressed(stream,masks=masks)
        del output, tensors, logits, raw
        state = usage()
        require(state['current_bytes'] <= limit, 'Memory GPU allowance exceeded')
        result = dict(image_sha256=request['image_sha256'],predictions=predictions,objects=objects,
            visible_objects=len(predictions),seeded_objects=len(object_ids),frame_sequence=frame_index,
            mask_artifact='memory/masks/'+name,mask_sha256=digest(destination),mps=state,
            offset_seconds=offset,seconds=perf_counter()-started,refresh_retry_used=retry_used)
        last_offset = offset
        frame_index += 1
        return result

    print(json.dumps(dict(id=0,ok=True,idle_mps=reset())),flush=True)
    code = 0
    try:
        for line in sys.stdin:
            request = {}
            try:
                require(len(line) < 4*1024**2, 'Memory request exceeded limit')
                request = json.loads(line)
                if request['operation'] == 'reset':
                    result = dict(idle_mps=reset())
                elif request['operation'] == 'park':
                    require(session is not None, 'Cannot park an empty memory session')
                    result = dict(idle_mps=park())
                else:
                    require(request['operation'] == 'predict', 'Unknown memory operation')
                    result = predict(request)
                print(json.dumps(dict(result,id=request['id'],ok=True),allow_nan=False),flush=True)
            except Exception as exc:
                print(json.dumps(dict(id=request.get('id'),ok=False,error=type(exc).__name__+': '+str(exc))),flush=True)
                code = 1
                break
    finally:
        idle = reset()
        atomic_json(artifact_path/'shutdown.json',dict(exit_code=code,resets=resets,parks=parks,idle_mps=idle))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
