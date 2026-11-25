"""Source-bound video evaluation. Sparse labels never imply full-video accuracy."""
from collections import Counter
import json
from pathlib import Path

from .core import digest, identifier, number, read_json, require
from .vision_benchmark import detection_matches, match_detections, summarize


def checked_box(box, width, height):
    require(isinstance(box, list) and len(box) == 4, "box must be pixel xyxy")
    x1, y1, x2, y2 = box
    for value in (x1, x2):
        number(value, 0, width)
    for value in (y1, y2):
        number(value, 0, height)
    require(x2 > x1 and y2 > y1, "box must have positive area")


def evaluate_video(analysis, references, *, iou=0.5):
    """Reuse detection matching; count identity links only across adjacent labeled samples."""
    number(iou, 0.1, 0.95)
    analysis, references = Path(analysis), Path(references)
    summary_path, observations_path = analysis/'summary.json', analysis/'observations.jsonl'
    require(read_json(analysis/'status.json')['state'] == 'complete', "analysis must be complete")
    hashes = {str(path): digest(path) for path in (summary_path, observations_path, references)}
    summary, reference = read_json(summary_path), read_json(references)
    version = reference.get('schema_version')
    require(type(version) is int and version in (1, 2), "unknown reference schema")
    require(reference.get('evaluation_target') == 'visible_lizard_extent', "body evaluation target required")
    require(reference.get('selection') in {'complete', 'uniform', 'consecutive', 'failure_mining', 'manual_spot_check'},
            "reference sampling method required")
    require(reference.get('source_sha256') == summary['source']['sha256'], "reference source differs")
    require(observations_path.stat().st_size <= 32 * 1024**2, "observation file size limit")
    rows = [json.loads(line) for line in observations_path.read_text().splitlines()]
    require(0 < len(rows) <= 18000, "invalid observation count")
    require(isinstance(reference.get('records'), list) and 0 < len(reference['records']) <= 18000,
            "reference records required")
    width, height = summary['source']['width'], summary['source']['height']
    number(width, 1, 16384); number(height, 1, 16384)
    confidence = number(summary['config']['confidence'], 0.01, 0.99)
    mode = summary.get('target_selection_mode', 'automatic')
    require(mode in {'automatic', 'initial_box_guided'}, "unknown target selection mode")
    guided = mode == 'initial_box_guided'
    require(guided == bool(summary['config'].get('target_seed')), "target selection config differs")
    require(guided or summary['config'].get('tracking_revision') == 2 or
            all('detector_candidates' in row for row in rows),
            "legacy tracker output lacks raw detector candidates; rerun inference")
    if guided:
        require(summary['config']['target_seed']['source_sha256'] == summary['source']['sha256'],
                "target seed source differs")
    inventory = {}
    previous_index, previous_time = -1, -1
    for position, row in enumerate(rows):
        frame = row['frame_index']
        require(type(frame) is int and frame > previous_index, "observation frames must increase")
        offset = number(row['offset_seconds'], 0, summary['source']['duration_seconds'])
        require(offset > previous_time and type(row['pts']) is int, "invalid observation timestamp")
        if guided:
            require('detector_candidates' in row, "guided evaluation requires raw detector candidates")
        raw = row.get('detector_candidates', row['detections'])
        for predictions in (raw, row['detections']):
            require(isinstance(predictions, list) and len(predictions) <= 100, "invalid prediction count")
            for box in predictions:
                checked_box(box['xyxy'], width, height)
                number(box['confidence'], 0, 1)
                track_id = box.get('track_id')
                require(track_id is None or type(track_id) in (int, str), "invalid track ID")
        inventory[frame] = (position, row)
        previous_index, previous_time = frame, offset
    selected_metrics, detector_metrics, frame_reports = [], [], []
    excluded, methods = Counter(), Counter()
    labeled, seen, conflict_frames = {}, set(), 0
    for ref in reference['records']:
        frame = ref['frame_index']
        require(type(frame) is int and frame in inventory, "reference frame not in analysis")
        require(frame not in seen, "duplicate reference frame")
        seen.add(frame)
        position, row = inventory[frame]
        require(type(ref['pts']) is int and ref['pts'] == row['pts'] and
                abs(number(ref['offset_seconds'], 0, summary['source']['duration_seconds']) - row['offset_seconds']) < 1e-6,
                "reference timestamp differs")
        require(type(ref.get('reviewed')) is bool, "reviewed flag required")
        if guided and position == 0:
            excluded['initialization'] += 1
            continue
        if not ref['reviewed']:
            excluded['unreviewed'] += 1
            continue
        method = ref.get('review_method')
        require(method in {'assistant', 'human', 'synthetic_fixture'}, "review method required")
        require(isinstance(ref.get('reviewer'), str) and 0 < len(ref['reviewer'].strip()) <= 160,
                "named reviewer required")
        visibility = ref.get('visibility')
        require(visibility in {'visible', 'absent', 'unreviewable'}, "visibility required")
        if version == 2:
            require('reference_boxes' not in ref and 'reference_identity' not in ref, "mixed reference schema")
            instances = ref.get('reference_instances')
            if visibility == 'unreviewable':
                require(instances is None, "unreviewable is not a negative reference")
                excluded['unreviewable'] += 1
                continue
            require(isinstance(instances, list) and len(instances) <= 100, "reference instances required")
            require(bool(instances) == (visibility == 'visible'), "reference instances differ from visibility")
            identities, boxes = [], []
            for instance in instances:
                require(isinstance(instance, dict) and set(instance) == {'identity', 'xyxy'}, "invalid reference instance")
                identifier(instance['identity'])
                checked_box(instance['xyxy'], width, height)
                require(instance['identity'] not in identities, "duplicate reference identity")
                identities.append(instance['identity'])
                boxes.append(instance['xyxy'])
        else:
            boxes, identity = ref.get('reference_boxes'), ref.get('reference_identity')
            identities = [identity] if visibility == 'visible' else []
        if visibility == 'unreviewable':
            require(boxes is None and identity is None, "unreviewable is not a negative reference")
            excluded['unreviewable'] += 1
            continue
        require(isinstance(boxes, list), "reference boxes required")
        if visibility == 'visible' and version == 1:
            require(len(boxes) == 1, "single-animal evaluation needs exactly one visible reference")
            checked_box(boxes[0], width, height)
            identifier(identity)
        elif visibility == 'absent' and version == 1:
            require(boxes == [] and identity is None, "absent reference must have no boxes or identity")
        methods[method] += 1
        selected = match_detections(boxes, row['detections'], confidence=confidence, iou=iou)
        raw = match_detections(boxes, row.get('detector_candidates', row['detections']), confidence=confidence, iou=iou)
        selected_metrics.append(selected); detector_metrics.append(raw)
        matches = dict(detection_matches(boxes, row['detections'], confidence=confidence, iou=iou))
        active_ids = Counter(b.get('track_id') for b in row['detections']
                             if b['confidence'] >= confidence and b.get('identity_status') == 'active'
                             and b.get('track_id') is not None)
        conflicts = {key for key, count in active_ids.items() if count > 1}
        conflict_frames += bool(conflicts)
        tracked = {}
        for index, identity in enumerate(identities):
            matched = row['detections'][matches[index]] if index in matches else None
            track_id = matched.get('track_id') if matched and matched.get('identity_status') == 'active' else None
            tracked[identity] = None if track_id in conflicts else track_id
        labeled[position] = tracked
        frame_report = {'frame_index': frame, 'offset_seconds': row['offset_seconds'], 'selected': selected, 'raw': raw}
        if version == 1:
            frame_report.update(reference_identity=ref.get('reference_identity'),
                                matched_active_track_id=next(iter(tracked.values()), None))
        else:
            frame_report['instances'] = [dict(reference_identity=identity, xyxy=boxes[index],
                prediction_index=matches.get(index), matched_active_track_id=tracked[identity])
                for index, identity in enumerate(identities)]
        frame_reports.append(frame_report)
    pairs = stable = changes = untracked = matched_pairs = 0
    for position, ref in labeled.items():
        previous = labeled.get(position-1, {})
        for identity, track_id in ref.items():
            if identity not in previous:
                continue
            pairs += 1
            if track_id is None or previous[identity] is None:
                untracked += 1
            else:
                matched_pairs += 1
                changes += track_id != previous[identity]
                stable += track_id == previous[identity]
    visible = sum(len(r) for r in labeled.values())
    active = sum(track_id is not None for r in labeled.values() for track_id in r.values())
    tracking = {'matched_active_fraction': active/visible if visible else None,
                'eligible_adjacent_pairs': pairs, 'stable_pairs': stable, 'untracked_pairs': untracked,
                'id_changes': changes if matched_pairs else None, 'continuity': stable/pairs if pairs else None,
                'identity_conflict_frames': conflict_frames}
    if version == 1:
        tracking.update(visible_frames=visible, matched_active_frames=active)
    else:
        tracking.update(visible_instance_samples=visible, matched_active_instance_samples=active)
    require(all(digest(Path(path)) == value for path, value in hashes.items()), "evaluation inputs changed")
    return {'schema_version': version, 'source_sha256': summary['source']['sha256'], 'model_id': summary['model_id'],
            'mode': mode, 'sampling': reference['selection'], 'evaluation_target': reference['evaluation_target'],
            'confidence': confidence, 'iou': iou, 'analysis_frames': len(rows), 'evaluated_frames': len(frame_reports),
            'reference_review_methods': dict(methods), 'excluded_frames': dict(excluded),
            'selected_detections': summarize(selected_metrics), 'raw_detector': summarize(detector_metrics),
            'tracking': tracking,
            'per_frame': sorted(frame_reports, key=lambda r: r['frame_index']),
            'input_sha256': {'summary': hashes[str(summary_path)], 'observations': hashes[str(observations_path)],
                             'references': hashes[str(references)]},
            'field_validated': False, 'independent_evaluation': False, 'anomaly_evaluated': False,
            'limitation': 'Labeled samples only. Guided selection is not detector improvement. Adjacent-link counts are not IDF1/HOTA; sparse labels cannot measure continuity. No claim of held-out source groups or field event accuracy.'}
