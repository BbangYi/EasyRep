"""Opt-in SAM2 video memory, periodically reseeded by the verified SAM3 detector."""
import os
from math import hypot
from pathlib import Path
import sys
from time import perf_counter

from .analysis_features import fingerprint
from .core import digest, number, read_json, relative, require
from .vision_sam3 import NeuralWorker, Sam3HybridPredictor, load_sam3_bundle, memory_allowance
from .vision_seed_refinement import crop_requests, choose_refinement
from .vision_benchmark import intersection_over_union
from .vision_hybrid import clip_proposal


class MemoryClock:
    def __init__(self, *, max_gap, refresh_seconds, max_frames, refresh_retry_frames=0):
        self.max_gap = number(max_gap, .01, 10)
        self.refresh_seconds = number(refresh_seconds, .1, 60)
        require(type(max_frames) is int and 1 <= max_frames <= 120, 'Invalid memory frame limit')
        self.max_frames = max_frames
        require(type(refresh_retry_frames) is int and refresh_retry_frames in (0,1), 'Invalid refresh retry limit')
        self.refresh_retry_frames = refresh_retry_frames
        self.retry_pending = False
        self.last = self.started = self.size = None
        self.frames, self.redetect = 0, False

    def advance(self, size, offset, *, cut=False):
        number(offset, 0, 3600)
        require(self.last is None or offset > self.last, 'Memory timestamps must increase')
        require(type(cut) is bool and len(size) == 2 and all(type(v) is int and v > 0 for v in size),
                'Invalid memory frame geometry or boundary')
        reason = ('first_frame' if self.last is None else 'scene_cut' if cut else
                  'resolution_change' if size != self.size else 'time_gap' if offset-self.last > self.max_gap else
                  'missing_object' if self.redetect else 'refresh_retry' if self.retry_pending else
                  'periodic_detection' if offset-self.started >= self.refresh_seconds else
                  'memory_frame_limit' if self.frames >= self.max_frames else None)
        if reason and not (self.refresh_retry_frames and reason in ('periodic_detection','refresh_retry')):
            self.started, self.frames, self.redetect = offset, 0, False
            self.retry_pending = False
        self.last, self.size = offset, size
        self.frames += 1
        return reason

    def can_defer_refresh(self, reason):
        return bool(self.refresh_retry_frames and reason == 'periodic_detection' and not self.retry_pending
                    and self.frames <= self.max_frames
                    and self.last-self.started < self.refresh_seconds+min(self.max_gap,.6))

    def defer_refresh(self):
        require(self.can_defer_refresh('periodic_detection'), 'Refresh retry deadline exceeded')
        self.retry_pending = True

    def commit_refresh(self):
        self.started, self.frames = self.last, 1
        self.retry_pending = self.redetect = False


def confirm_temporal_seed(previous, primary, auxiliary, *, size, offset_seconds, reason, max_gap):
    """Confirm current masks for existing objects; never acquire from history alone."""
    rejected = dict(accepted=False, reason='ineligible_history', matches=[])
    if (reason not in ('periodic_detection','refresh_retry') or previous is None
            or tuple(previous['size']) != tuple(size)
            or not 0 < offset_seconds-previous['offset_seconds'] <= min(max_gap,.6)
            or previous['consecutive_frames'] < 2
            or not 0 < len(previous['predictions']) == previous['seeded_objects'] <= 16):
        return None, rejected
    width,height = size
    primary = [clipped for p in primary if (clipped := clip_proposal(p,width,height)) is not None]
    for proposal in previous['predictions'] + primary + auxiliary:
        require(len(proposal['xyxy']) == 4, 'Invalid confirmation box')
        a,b,c,d = proposal['xyxy']
        for value in (a,c): number(value,0,width)
        for value in (b,d): number(value,0,height)
        require(a<c and b<d, 'Degenerate confirmation box')
    for proposal in primary+auxiliary:number(proposal['confidence'],0,1)
    for proposal in auxiliary:
        require(type(proposal['mask_index']) is int and proposal['mask_index'] >= 0, 'Invalid confirmation mask index')
    raw = [p for p in primary if p['confidence'] >= .9]
    masks = [p for p in auxiliary if p['confidence'] >= .5]
    prior = previous['predictions']
    if len(raw) != len(prior) or len(masks) != len(prior):
        return None, dict(rejected,reason='incomplete_current_support')
    candidates = []
    for old in prior:
        a,b,c,d = old['xyxy'];area = (c-a)*(d-b)
        matches = []
        for j,mask in enumerate(masks):
            x1,y1,x2,y2 = mask['xyxy']
            overlap = intersection_over_union(old['xyxy'],mask['xyxy'])
            step = hypot((x1+x2-a-c)/2,(y1+y2-b-d)/2)/hypot(width,height)
            ratio = (x2-x1)*(y2-y1)/area
            anchors = [k for k,p in enumerate(raw) if intersection_over_union(p['xyxy'],mask['xyxy']) >= .7]
            if overlap >= .3 and step <= .15 and .5 <= ratio <= 2 and len(anchors) == 1:
                matches.append(dict(mask=j,primary=anchors[0],prior_iou=overlap,step_diagonals=step,area_ratio=ratio))
        if len(matches) != 1:
            return None, dict(rejected,reason='ambiguous_or_discontinuous_match')
        candidates.append(matches[0])
    if (len({p['mask'] for p in candidates}) != len(prior)
            or len({p['primary'] for p in candidates}) != len(prior)
            or len({m['mask_index'] for m in masks}) != len(prior)):
        return None, dict(rejected,reason='shared_current_object')
    return dict(kind='mask',mask_indices=[masks[p['mask']]['mask_index'] for p in candidates],count=len(prior)), \
        dict(accepted=True,reason='current_models_and_temporal_location_agree',matches=candidates,
             prior_offset_seconds=previous['offset_seconds'],current_offset_seconds=offset_seconds,
             primary_raw_threshold=.9,auxiliary_raw_threshold=.5,global_verifier_bypassed_for_continuation_only=True)


def confirm_retry_masks(temporal, auxiliary, *, allow_unmatched_masks=False):
    """Require unique current mask support; box seeds may leave other masks unused."""
    for box in temporal+auxiliary:
        require(len(box['xyxy']) == 4, 'Invalid retry support box')
        a,b,c,d = [number(v,0,1e8) for v in box['xyxy']]
        require(a<c and b<d, 'Degenerate retry support box')
    masks = [p for p in auxiliary if number(p['confidence'],0,1) >= .5]
    if not temporal or (not allow_unmatched_masks and len(masks) != len(temporal)):
        return dict(accepted=False,reason='incomplete_current_masks',matches=[])
    matches = [[j for j,p in enumerate(masks) if intersection_over_union(old['xyxy'],p['xyxy']) >= .5]
               for old in temporal]
    accepted = all(len(row)==1 for row in matches) and len({row[0] for row in matches})==len(temporal)
    return dict(accepted=accepted,reason='current_masks_agree' if accepted else 'ambiguous_or_disagreeing_masks',
                matches=matches,minimum_iou=.5,auxiliary_score_min=.5)


def select_seeds(boxes, evidence):
    accepted = [box for box in boxes if box['confidence'] >= .4]
    require(len(accepted) <= 16, 'Too many objects for bounded video memory')
    if not accepted:
        return dict(kind='empty', count=0)
    selected = [evidence['sam3']['predictions'][i] for i in evidence['route']['selected_auxiliary_indices']]
    # A partially accepted mask set must not silently omit an accepted primary detection.
    if len(selected) == len(accepted) and [p['xyxy'] for p in selected] == [p['xyxy'] for p in accepted]:
        return dict(kind='mask', mask_indices=[p['mask_index'] for p in selected], count=len(selected))
    return dict(kind='box', boxes=[p['xyxy'] for p in accepted], count=len(accepted))


def enhance_detection_frame(frame):
    """Fixed photo-validated contrast retry; geometry and source pixels stay intact."""
    import cv2
    import numpy as np
    require(isinstance(frame,np.ndarray) and frame.dtype == np.uint8 and frame.ndim == 3
            and frame.shape[2] == 3 and min(frame.shape[:2]) >= 8, 'Invalid contrast retry frame')
    lab = cv2.cvtColor(frame,cv2.COLOR_BGR2LAB)
    lab[:,:,0] = cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(lab[:,:,0])
    return cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)


def temporal_recheck(previous, predictions, *, size, offset_seconds, generation, max_gap):
    """Spatial disagreement requests fresh evidence; it does not classify an animal as absent."""
    width, height = size
    slots = [p['object_slot'] for p in predictions]
    require(all(type(slot) is int and slot > 0 for slot in slots) and len(slots) == len(set(slots)),
            'Invalid temporal object slots')
    def validate_geometry(proposals):
        for proposal in proposals:
            require(len(proposal['xyxy']) == 4, 'Invalid temporal recheck geometry')
            a, b, c, d = proposal['xyxy']
            for value in (a, c): number(value, 0, width)
            for value in (b, d): number(value, 0, height)
            require(a < c and b < d, 'Degenerate temporal recheck box')
    validate_geometry(predictions)
    result = dict(required=False, reason='ineligible_history', object_slots=[], checks=[],
                  minimum_iou=.1, maximum_step_diagonals=.15)
    if (previous is None or tuple(previous['size']) != tuple(size) or previous['generation'] != generation
            or previous['consecutive_frames'] < 2
            or not 0 < offset_seconds-previous['offset_seconds'] <= min(max_gap, .6)):
        return result
    validate_geometry(previous['predictions'])
    prior = {p['object_slot']: p for p in previous['predictions']}
    require(len(prior) == len(previous['predictions']), 'Duplicated prior temporal slots')
    if not slots or set(prior) != set(slots) or len(slots) != previous['seeded_objects']:
        return dict(result, reason='incomplete_objects')
    for proposal in predictions:
        slot = proposal['object_slot']
        a, b, c, d = prior[slot]['xyxy']
        x1, y1, x2, y2 = proposal['xyxy']
        overlap = intersection_over_union(prior[slot]['xyxy'], proposal['xyxy'])
        step = hypot((x1+x2-a-c)/2, (y1+y2-b-d)/2) / hypot(width, height)
        result['checks'].append(dict(object_slot=slot, prior_iou=overlap, step_diagonals=step))
        if overlap < .1 or step > .15:
            result['object_slots'].append(slot)
    result.update(required=bool(result['object_slots']), reason='spatial_discontinuity' if result['object_slots'] else 'stable')
    return result


def load_memory_bundle(directory):
    directory = Path(directory).resolve()
    card = read_json(directory/'model-card.json')
    require(card['schema_version'] == 1 and card['backend'] == 'sam2-hybrid' and card['species'] == 'lizard'
            and card['status'] == 'experimental' and card['production_validated'] is False, 'Unsupported video memory package')
    require(card['model_id'] == fingerprint({k:v for k,v in card.items() if k != 'model_id'}), 'Memory package identity differs')
    base_recipe = dict(image_size=640,refresh_seconds=10,max_memory_frames=120,non_overlapping_masks=True)
    require(card['recipe'] in (base_recipe,dict(base_recipe,refresh_retry_frames=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1,refresh_mask_support=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1,refresh_mask_support=1,box_seed_mask_support=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1,refresh_mask_support=1,box_seed_mask_support=1,
                                   memory_pending_association=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1,refresh_mask_support=1,box_seed_mask_support=1,
                                   memory_pending_association=1,unstable_mask_redetection=1),
                              dict(base_recipe,refresh_retry_frames=1,seed_crop_revision=1,memory_slot_association=1,
                                   temporal_seed_confirmation=1,refresh_mask_support=1,box_seed_mask_support=1,
                                   memory_pending_association=1,unstable_mask_redetection=1,
                                   empty_detection_contrast_retry=1)), 'Unsupported memory recipe')
    paths = {name:(directory/path).resolve() for name,path in card['paths'].items()}
    require(set(paths) == {'detector','memory','runtime'} and all(p.is_dir() for p in paths.values()), 'Missing memory component')
    detector = load_sam3_bundle(paths['detector'])
    require(detector[0]['model_id'] == card['detector_model_id'], 'Detector package differs')
    require({'model.safetensors','config.json','processor_config.json'} <= card['memory_files'].keys(), 'Incomplete memory package')
    for name, checksum in card['memory_files'].items():
        require(digest(relative(paths['memory'],name)) == checksum, 'Memory component changed: '+name)
    require(digest(paths['runtime']/'transformers/__init__.py') == card['runtime_entry_sha256'], 'Memory runtime differs')
    return card, paths, detector


class MemoryHybridPredictor:
    def __init__(self, directory, bundle, device, artifact_directory, *, max_gap_seconds):
        require(device == 'mps', 'Video memory requires the measured MPS runtime')
        self.card, paths, detector_bundle = bundle
        self.directory = Path(artifact_directory).resolve()
        self.directory.mkdir()
        for name in ('frames','seeds','masks'):
            (self.directory/name).mkdir()
        self.clock = MemoryClock(max_gap=max_gap_seconds, refresh_seconds=self.card['recipe']['refresh_seconds'],
                                 max_frames=self.card['recipe']['max_memory_frames'],
                                 refresh_retry_frames=self.card['recipe'].get('refresh_retry_frames',0))
        self.detector = self.memory = None
        self.index = self.generation = 0
        self.active, self.closed = False, False
        self.previous_temporal = None
        try:
            self.detector = Sam3HybridPredictor(paths['detector'],detector_bundle,device,self.directory/'detector')
            root = Path(__file__).resolve().parents[1]
            environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(paths['runtime']),str(root))),
                OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false',
                HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', PYTORCH_ENABLE_MPS_FALLBACK='0')
            self.memory = NeuralWorker([sys.executable,'-m','behavior_recorder.vision_memory_worker',str(paths['memory']),
                                        str(self.directory),str(max_gap_seconds)], environment=environment,
                                       log=self.directory/'memory.log')
            self.detector.idle['memory'] = self.memory.ready['idle_mps']['driver_bytes']
        except BaseException:
            self.close()
            raise

    def _detect_seed(self, frame):
        box_support = None
        boxes, detection = self.detector.predict_frame(frame)
        detection['input_image'] = 'memory/detector/frames/' + Path(detection['input_image']).name
        detection['mask_artifact'] = 'memory/detector/masks/' + detection['sam3']['mask_name']
        seed = select_seeds(boxes,detection)
        if seed['kind'] == 'box' and self.card.get('recipe',{}).get('box_seed_mask_support') == 1:
            box_support = confirm_retry_masks([dict(xyxy=box) for box in seed['boxes']],
                detection['sam3']['predictions'],allow_unmatched_masks=True)
            box_support['proposed_boxes'] = seed['boxes']
            if not box_support['accepted']:
                seed = dict(kind='empty',count=0)
        return boxes, detection, seed, box_support

    def _refresh(self, frame, previous, reason, offset_seconds):
        """Acquire and prepare a current-frame seed using the same guarded detection path."""
        import numpy as np
        height, width = frame.shape[:2]
        confirmation = None
        deferred = False
        retain = self.active and self.clock.can_defer_refresh(reason)
        reply = self.memory.request(operation='park' if retain else 'reset')
        self.detector.idle['memory'] = reply['idle_mps']['driver_bytes']
        if not retain:
            self.active = False
        boxes, detection, seed, box_support = self._detect_seed(frame)
        if not seed['count'] and self.card.get('recipe',{}).get('temporal_seed_confirmation') == 1:
            candidate,confirmation = confirm_temporal_seed(previous,
                detection['primary']['inference']['raw_grounding_predictions'],detection['sam3']['predictions'],
                size=(width,height),offset_seconds=offset_seconds,reason=reason,max_gap=self.clock.max_gap)
            if candidate is not None:seed = candidate
        if not seed['count'] and self.card.get('recipe',{}).get('empty_detection_contrast_retry') == 1:
            retry_boxes, attempt, retry_seed, retry_support = self._detect_seed(enhance_detection_frame(frame))
            retry = dict(accepted=bool(retry_seed['count']), original=detection, attempt=attempt,
                         original_box_support=box_support, attempt_box_support=retry_support,
                         transform=dict(name='CLAHE',space='LAB L',clip_limit=2.0,tile_grid=[8,8]))
            if retry['accepted']:
                boxes, detection, seed, box_support = retry_boxes, attempt, retry_seed, retry_support
            # Keep both actual inputs, including failed attempts. SAM2 still receives the original frame.
            detection = dict(detection,contrast_retry=retry)
        if retain and not seed['count']:
            self.clock.defer_refresh()
            deferred = True
        else:
            self.clock.commit_refresh()
            self.generation += 1
            self.active = seed['count'] > 0
        if seed['kind'] == 'mask':
            source = self.detector.directory/'masks'/detection['sam3']['mask_name']
            require(digest(source) == detection['mask_sha256'], 'Detector seed masks changed')
            with np.load(source,allow_pickle=False) as archive:
                masks = archive['masks'][seed.pop('mask_indices')]
            require(masks.shape == (seed['count'],height,width), 'Seed dimensions differ')
            if self.card['recipe'].get('seed_crop_revision') == 1:
                accepted=[box for box in boxes if box['confidence']>=.4]
                requests=crop_requests(accepted,detection['primary']['inference']['verifier_details'],
                                       detection['sam3']['predictions'],width,height)
                refinements=[]
                for request in requests:
                    x1,y1,x2,y2=request['crop_xyxy'];slot=request['object_index']
                    crop_boxes,crop_evidence=self.detector.predict_frame(frame[y1:y2,x1:x2].copy())
                    crop_evidence['input_image']='memory/detector/frames/'+Path(crop_evidence['input_image']).name
                    crop_evidence['mask_artifact']='memory/detector/masks/'+crop_evidence['sam3']['mask_name']
                    crop_seed=select_seeds(crop_boxes,crop_evidence)
                    chosen,checks=None,[]
                    if crop_seed['kind']=='mask':
                        path=self.detector.directory/'masks'/crop_evidence['sam3']['mask_name']
                        require(digest(path)==crop_evidence['mask_sha256'],'Refinement masks changed')
                        with np.load(path,allow_pickle=False) as archive:
                            local_masks=archive['masks'][crop_seed['mask_indices']]
                        require(local_masks.dtype==bool and local_masks.shape==(crop_seed['count'],y2-y1,x2-x1),'Refinement dimensions differ')
                        mapped=np.zeros((len(local_masks),height,width),dtype=bool)
                        mapped[:,y1:y2,x1:x2]=local_masks
                        chosen,checks=choose_refinement(masks[slot],np.delete(masks,slot,axis=0),mapped)
                        if chosen is not None:masks[slot]=mapped[chosen]
                    refinements.append(dict(request,chosen_candidate=chosen,checks=checks,inference=crop_evidence))
                detection['seed_refinements']=refinements
            destination = self.directory/'seeds'/f'{self.index:06d}.npz'
            with destination.open('xb') as stream:
                np.savez_compressed(stream,masks=masks)
            seed.update(path=str(destination),sha256=digest(destination))
        return seed, detection, confirmation, box_support, deferred

    def _propagate(self, image, checksum, offset_seconds, seed, *, deferred=False, suffix=''):
        allowance = memory_allowance([value for name,value in self.detector.idle.items() if name != 'memory'])
        reply = self.memory.request(operation='predict',image=str(image),image_sha256=checksum,
            offset_seconds=offset_seconds,seed=None if deferred else seed,
            allow_refresh_retry=deferred,mask_name=f'{self.index:06d}{suffix}.npz',mps_limit_bytes=allowance)
        require(reply['image_sha256'] == checksum, 'Temporal frame identity differs')
        self.detector.idle['memory'] = reply['mps']['driver_bytes']
        return reply

    def predict_frame(self, frame, *, offset_seconds, scene_cut=False):
        import cv2
        from PIL import Image
        require(not self.closed, 'Video memory predictor is closed')
        started = perf_counter()
        try:
            height, width = frame.shape[:2]
            reason = self.clock.advance((width,height),offset_seconds,cut=scene_cut)
            image = self.directory/'frames'/f'{self.index:06d}.png'
            Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).save(image)
            checksum = digest(image)
            seed, detection = None, None
            previous = getattr(self,'previous_temporal',None)
            confirmation = None
            refresh_support = None
            box_support = None
            recheck = None
            deferred = False
            if reason:
                seed, detection, confirmation, box_support, deferred = self._refresh(frame, previous, reason, offset_seconds)
            reply = None
            if self.active:
                reply = self._propagate(image, checksum, offset_seconds, seed, deferred=deferred)
                boxes = [dict(p,memory_object_id=f'{self.generation}:{p["object_slot"]}') for p in reply['predictions']]
                self.clock.redetect = reply['visible_objects'] != reply['seeded_objects']
                if deferred and self.card.get('recipe',{}).get('refresh_mask_support') == 1:
                    refresh_support = confirm_retry_masks(reply['predictions'],detection['sam3']['predictions'])
                    if not refresh_support['accepted']:
                        boxes = []
                        self.active, self.clock.redetect = False, True
                        reset = self.memory.request(operation='reset')
                        self.detector.idle['memory'] = reset['idle_mps']['driver_bytes']
                if reason is None and self.card.get('recipe',{}).get('unstable_mask_redetection') == 1:
                    recheck = temporal_recheck(previous, reply['predictions'], size=(width,height),
                        offset_seconds=offset_seconds, generation=self.generation, max_gap=self.clock.max_gap)
                    if recheck['required']:
                        # One bounded restart on this input. The first mask remains in the audit;
                        # only a newly seeded, currently supported mask may replace it.
                        recheck.update(propagated_temporal=reply, previous_generation=self.generation)
                        reason = 'unstable_mask'
                        seed, detection, confirmation, box_support, deferred = self._refresh(frame, previous, reason, offset_seconds)
                        require(not deferred, 'An unstable mask cannot defer fresh detection')
                        reply, boxes = None, []
                        if self.active:
                            reply = self._propagate(image, checksum, offset_seconds, seed, suffix='-recheck')
                            support = confirm_retry_masks(reply['predictions'], detection['sam3']['predictions'],
                                                          allow_unmatched_masks=True)
                            recheck['fresh_mask_support'] = support
                            if support['accepted']:
                                boxes = [dict(p,memory_object_id=f'{self.generation}:{p["object_slot"]}')
                                         for p in reply['predictions']]
                            else:
                                self.active = False
                                reset = self.memory.request(operation='reset')
                                self.detector.idle['memory'] = reset['idle_mps']['driver_bytes']
                        self.clock.redetect = (not boxes or reply['visible_objects'] != reply['seeded_objects'])
            else:
                boxes = []
                self.clock.redetect = True
            self.previous_temporal = None
            if reply is not None and reply['visible_objects'] == reply['seeded_objects'] and boxes:
                consecutive = (previous['consecutive_frames']+1 if previous is not None
                               and previous['generation'] == self.generation else 1)
                self.previous_temporal = dict(size=(width,height),offset_seconds=offset_seconds,
                    consecutive_frames=consecutive,generation=self.generation,seeded_objects=reply['seeded_objects'],
                    predictions=reply['predictions'])
            if seed and seed['kind'] == 'mask':
                seed = dict(seed, path='memory/seeds/' + Path(seed['path']).name)
            evidence = dict(actual_device='mps',model='sam2-hybrid',package_id=self.card['model_id'],
                frame_sequence=self.index,seconds=perf_counter()-started,input_image='memory/frames/'+image.name,
                input_image_sha256=checksum,memory_session_id=self.generation,reset_reason=reason,
                detector=detection,temporal=reply,seed=seed,refresh_deferred=deferred,
                temporal_seed_confirmation=confirmation,
                refresh_mask_support=refresh_support,
                box_seed_mask_support=box_support,
                temporal_recheck=recheck,
                identity_scope='Memory slots are session-local; public identity remains guarded by VideoTracker.',
                confidence_semantics='Binary mask presence, not a calibrated detection probability.',
                memory_limits=dict(refresh_seconds=self.clock.refresh_seconds,max_frames=self.clock.max_frames,
                                   refresh_retry_frames=self.clock.refresh_retry_frames),
                neural_processes={**{name:worker.process.pid for name,worker in self.detector.workers.items()},
                                  'memory':self.memory.process.pid})
            self.index += 1
            return boxes, evidence
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.memory is not None:
                self.memory.close()
        finally:
            if self.detector is not None:
                self.detector.close()
