"""Declared, past-only context aligned to appearance observations; no identity inference."""
import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
import subprocess

from .analysis_features import fingerprint, save_artifact, sensor_feature
from .core import RecorderError, clock, digest, encode, identifier, now, number, read_json, relative, require, timestamp

FEATURE_VERSION = 'past-only-reviewed-srgb-context-v1'
CONTEXT_VERSION = 'declared-past-context-v1'
LIMIT = 8 * 1024**2
FEATURES = ('temperature_c', 'humidity_percent', 'activity_fraction', 'behaviour_coverage')


def required_time(value):
    result = timestamp(value)
    require(result is not None, 'context timestamp must be explicit')
    return result


def declared_clock(value):
    clock(value)
    if value['accuracy_ms'] is not None:
        number(value['accuracy_ms'], 0, 86400000)
    return value['accuracy_ms']


def evidence(row):
    identifier(row['observer'])
    require(isinstance(row['evidence_reference'], str) and 0 < len(row['evidence_reference'].strip()) <= 1024,
            'explicit binding/review evidence required')


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {'schema_version', 'kind', 'dataset_kind', 'animal_id',
        'enclosure_id', 'observer', 'evidence_reference', 'max_clock_error_ms', 'behaviour_window_seconds',
        'min_behaviour_coverage', 'sensors', 'anchors', 'sources'}, 'invalid context plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_context_plan', 'unsupported context plan')
    require(plan['dataset_kind'] in ('real', 'test'), 'invalid dataset_kind')
    identifier(plan['animal_id']); identifier(plan['enclosure_id']); evidence(plan)
    number(plan['max_clock_error_ms'], 0, 10000)
    number(plan['behaviour_window_seconds'], 1, 86400)
    number(plan['min_behaviour_coverage'], 1e-12, 1)
    require(isinstance(plan['sensors'], list) and len(plan['sensors']) <= 2, 'at most two declared sensor channels')
    names, ids = set(), set()
    for sensor in plan['sensors']:
        require(isinstance(sensor, dict) and set(sensor) == {'feature', 'sensor_id', 'unit', 'max_age_seconds',
                'geometry_revision', 'placement_revision'}, 'invalid context sensor config')
        name = sensor['feature']
        require(name in FEATURES[:2] and name not in names, 'duplicate or unknown sensor feature')
        require(sensor['unit'] == ('Cel' if name == 'temperature_c' else '%RH'), 'explicit canonical unit required')
        sid = identifier(sensor['sensor_id']); require(sid not in ids, 'duplicate sensor channel')
        ids.add(sid); names.add(name)
        number(sensor['max_age_seconds'], .01, 3600)
        identifier(sensor['geometry_revision']); identifier(sensor['placement_revision'])
    require(isinstance(plan['anchors'], list) and 1 <= len(plan['anchors']) <= 512, 'one to 512 context anchors')
    seen = set()
    for anchor in plan['anchors']:
        require(isinstance(anchor, dict) and set(anchor) == {'record_id', 'observed_at', 'as_of',
                'observed_clock', 'as_of_clock'}, 'invalid context anchor')
        rid = identifier(anchor['record_id']); require(rid not in seen, 'duplicate anchor'); seen.add(rid)
        require(required_time(anchor['observed_at']) <= required_time(anchor['as_of']), 'anchor before observation')
        declared_clock(anchor['observed_clock']); declared_clock(anchor['as_of_clock'])
    require(isinstance(plan['sources'], list) and len(plan['sources']) <= 8, 'at most eight context sources')


def validate_record(row, kind, dataset_kind):
    common = {'record_id', 'enclosure_id', 'observed_clock', 'received_at', 'received_clock', 'recorded_at', 'recorded_clock'}
    extra = {'observed_at', 'source', 'geometry_revision', 'placement_revision', 'readings'} if kind == 'sensors' else {
        'animal_id', 'start_at', 'end_at', 'quality', 'identity_method', 'active_seconds', 'observer', 'evidence_reference'}
    require(isinstance(row, dict) and set(row) == common | extra, 'invalid context record fields')
    identifier(row['record_id']); identifier(row['enclosure_id'])
    for name in ('observed_clock', 'received_clock', 'recorded_clock'):
        declared_clock(row[name])
    for name in ('received_at', 'recorded_at'):
        required_time(row[name])
    if kind == 'sensors':
        required_time(row['observed_at'])
        require(row['source'] == ('sensor' if dataset_kind == 'real' else 'simulation'), 'sensor dataset_kind mismatch')
        identifier(row['geometry_revision']); identifier(row['placement_revision'])
        require(isinstance(row['readings'], list) and 1 <= len(row['readings']) <= 64, 'bounded sensor readings required')
        ids = set()
        for reading in row['readings']:
            require(isinstance(reading, dict) and set(reading) == {'sensor_id', 'unit', 'value', 'quality'}, 'invalid sensor reading')
            sid = identifier(reading['sensor_id']); require(sid not in ids, 'duplicate sensor ID'); ids.add(sid)
            require(isinstance(reading['unit'], str) and 0 < len(reading['unit']) <= 64, 'sensor unit required')
            require(reading['quality'] in ('valid', 'invalid', 'crc_error', 'disconnected', 'missing', 'unknown'), 'invalid sensor quality')
            if reading['quality'] == 'valid':
                number(reading['value'], -1e12, 1e12)
            else:
                require(reading['value'] is None, 'invalid reading must be null')
    else:
        identifier(row['animal_id']); evidence(row)
        duration = (required_time(row['end_at']) - required_time(row['start_at'])).total_seconds()
        require(duration > 0, 'behaviour interval must be ordered')
        require(row['quality'] in ('valid', 'invalid', 'unknown'), 'invalid behaviour quality')
        require(row['identity_method'] in ('human_confirmed', 'unknown'), 'tracking ID is not animal identity')
        if row['quality'] == 'valid':
            number(row['active_seconds'], 0, duration)
        else:
            require(row['active_seconds'] is None, 'unreviewed activity must be null')


def source_rows(plan, root):
    groups, seen, total = {'sensors': [], 'behaviour': []}, set(), 0
    for source in plan['sources']:
        require(isinstance(source, dict) and set(source) == {'kind', 'path', 'sha256'}
                and source['kind'] in groups, 'invalid context source reference')
        path = relative(root, source['path']); total += path.stat().st_size
        require(total <= LIMIT, 'context source metadata exceeds 8 MiB')
        require(digest(path) == source['sha256'], 'context source hash mismatch')
        payload = read_json(path, limit=LIMIT)
        require(isinstance(payload, dict) and set(payload) == {'schema_version', 'kind', 'dataset_kind', 'records'}, 'invalid source artifact')
        require(type(payload['schema_version']) is int and payload['schema_version'] == 1
                and payload['kind'] == 'appearance_context_' + source['kind'], 'unsupported source artifact')
        require(payload['dataset_kind'] == plan['dataset_kind'], 'source dataset_kind mismatch')
        require(isinstance(payload['records'], list) and len(payload['records']) <= 4096, 'too many context records')
        for row in payload['records']:
            validate_record(row, source['kind'], plan['dataset_kind'])
            key = (source['kind'], row['record_id']); require(key not in seen, 'duplicate context record'); seen.add(key)
            require(len(seen) <= 4096, 'total context record limit exceeded')
            groups[source['kind']].append((row, dict(kind=source['kind'], record_id=row['record_id'],
                source=source['path'], source_sha256=source['sha256'], row_sha256=fingerprint(row),
                observed_at=row.get('observed_at'), start_at=row.get('start_at'), end_at=row.get('end_at'),
                received_at=row['received_at'], recorded_at=row['recorded_at'])))
    return groups


def available(row, cutoff):
    event_error = row['observed_clock']['accuracy_ms']
    received_error = row['received_clock']['accuracy_ms']
    recorded_error = row['recorded_clock']['accuracy_ms']
    if received_error is not None and event_error is not None:
        end = required_time(row.get('observed_at', row.get('end_at')))
        if required_time(row['received_at']) + timedelta(milliseconds=received_error) < end - timedelta(milliseconds=event_error):
            return 'receipt_precedes_event'
    if received_error is not None and recorded_error is not None:
        if required_time(row['recorded_at']) + timedelta(milliseconds=recorded_error) < required_time(row['received_at']) - timedelta(milliseconds=received_error):
            return 'review_precedes_receipt'
    for name in ('received', 'recorded'):
        error = row[name + '_clock']['accuracy_ms']
        if error is None:
            return 'availability_clock_unknown'
        if required_time(row[name + '_at']) + timedelta(milliseconds=error) > cutoff:
            return 'not_available'
    return None


def temporal_reason(row, start, end, anchor, plan, window):
    error = row['observed_clock']['accuracy_ms']
    aerror = max(anchor['as_of_clock']['accuracy_ms'], anchor['observed_clock']['accuracy_ms'])
    if error is None or error + aerror > plan['max_clock_error_ms']:
        return 'clock_alignment_unverified'
    center = required_time(anchor['as_of'])
    if end + timedelta(milliseconds=error) > center - timedelta(milliseconds=aerror):
        return 'not_safely_past'
    if start - timedelta(milliseconds=error) < center + timedelta(milliseconds=aerror) - timedelta(seconds=window):
        return 'outside_trailing_window'
    return None


def align_anchor(anchor, plan, groups):
    values = dict.fromkeys(FEATURES)
    audit = {name: dict(used=[], excluded=[], reasons=[]) for name in FEATURES}
    errors = [anchor[key]['accuracy_ms'] for key in ('observed_clock', 'as_of_clock')]
    if any(value is None for value in errors) or max(errors) > plan['max_clock_error_ms']:
        for report in audit.values(): report['reasons'].append('anchor_clock_unverified')
        return dict(**anchor, features=values, audit=audit)
    aerror = max(errors)
    center = required_time(anchor['as_of']); cutoff = center - timedelta(milliseconds=aerror)
    for sensor in plan['sensors']:
        name = sensor['feature']; candidates = []
        for row, ref in groups['sensors']:
            if not any(reading['sensor_id'] == sensor['sensor_id'] for reading in row['readings']): continue
            reason = 'enclosure_mismatch' if row['enclosure_id'] != plan['enclosure_id'] else available(row, cutoff)
            observed = required_time(row['observed_at'])
            if not reason and observed > center: reason = 'future_event'
            if reason:
                audit[name]['excluded'].append(dict(**ref, reason=reason)); continue
            candidates.append((observed, row, ref))
        if not candidates:
            audit[name]['reasons'].append('sensor_missing'); continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        observed, newest, ref = candidates[0]
        reason = temporal_reason(newest, observed, observed, anchor, plan, sensor['max_age_seconds'])
        # Uncertainty can make the order ambiguous even with distinct nominal timestamps.
        if not reason:
            low = observed - timedelta(milliseconds=newest['observed_clock']['accuracy_ms'])
            if any(row['observed_clock']['accuracy_ms'] is None or when + timedelta(milliseconds=row['observed_clock']['accuracy_ms']) >= low
                   for when, row, _ in candidates[1:]):
                reason = 'ambiguous_sensor_order'
        if not reason:
            value, _, reason = sensor_feature([newest], sensor,
                dict(enclosure_id=plan['enclosure_id'], capture_clock=dict(accuracy_ms=aerror)), center, plan)
            if not reason:
                lo, hi = (-100, 150) if name == 'temperature_c' else (0, 100)
                if not lo <= value <= hi: reason = 'sensor_value_out_of_range'
        if reason:
            audit[name]['excluded'].append(dict(**ref, reason=reason)); audit[name]['reasons'].append(reason)
        else:
            values[name] = value; audit[name]['used'].append(ref)
        for _, _, oldref in candidates[1:]: audit[name]['excluded'].append(dict(**oldref, reason='older_sensor_record'))
    for name in FEATURES[:2]:
        if name not in [sensor['feature'] for sensor in plan['sensors']]: audit[name]['reasons'].append('channel_not_declared')
    eligible, exclusions = [], []
    for row, ref in groups['behaviour']:
        start, end = required_time(row['start_at']), required_time(row['end_at'])
        reason = ('identity_unconfirmed' if row['animal_id'] != plan['animal_id'] or row['identity_method'] != 'human_confirmed'
                  else 'enclosure_mismatch' if row['enclosure_id'] != plan['enclosure_id']
                  else 'behaviour_invalid' if row['quality'] != 'valid' else available(row, cutoff))
        reason = reason or temporal_reason(row, start, end, anchor, plan, plan['behaviour_window_seconds'])
        if reason: exclusions.append(dict(**ref, reason=reason))
        else: eligible.append((start, end, row, ref))
    eligible.sort(key=lambda item: item[0])
    reason = None
    if not eligible: reason = 'behaviour_missing'
    elif any(a[1] + timedelta(milliseconds=a[2]['observed_clock']['accuracy_ms']) >
             b[0] - timedelta(milliseconds=b[2]['observed_clock']['accuracy_ms']) for a, b in zip(eligible, eligible[1:])):
        reason = 'overlapping_behaviour_intervals'
    if reason is None:
        duration = sum((end-start).total_seconds() for start, end, _, _ in eligible)
        guaranteed = sum(max(0., (end-start).total_seconds() - 2*row['observed_clock']['accuracy_ms']/1000)
                         for start, end, row, _ in eligible)
        values['behaviour_coverage'] = guaranteed / plan['behaviour_window_seconds']
        if values['behaviour_coverage'] >= plan['min_behaviour_coverage']:
            values['activity_fraction'] = sum(row['active_seconds'] for _, _, row, _ in eligible)/duration
        else: reason = 'insufficient_behaviour_coverage'
    if reason == 'overlapping_behaviour_intervals':
        exclusions.extend(dict(**ref, reason=reason) for _, _, _, ref in eligible)
    for name in FEATURES[2:]:
        audit[name] = dict(used=[ref for _, _, _, ref in eligible] if reason != 'overlapping_behaviour_intervals' else [],
            excluded=exclusions, reasons=[reason] if reason else [])
    return dict(**anchor, features=values, audit=audit)


def build_context(plan_path, guard=lambda: None):
    path = Path(plan_path); plan = read_json(path, limit=LIMIT); validate_plan(plan)
    groups = source_rows(plan, path.parent)
    rows, row_bytes = [], 0
    for anchor in plan['anchors']:
        guard()
        row = align_anchor(anchor, plan, groups)
        row_bytes += len(encode(row))
        require(row_bytes <= LIMIT, 'aligned context exceeds 8 MiB; reduce input scope')
        rows.append(row)
    result = dict(schema_version=1, kind='appearance_aligned_context', created_at=now(),
        feature_version=CONTEXT_VERSION, dataset_kind=plan['dataset_kind'], animal_id=plan['animal_id'], enclosure_id=plan['enclosure_id'],
        plan_sha256=fingerprint(plan), sources=plan['sources'], rows=rows,
        independent_identity_or_clock_verification=False, actual_model_fit=False, actuation_allowed=False,
        evidence='Operator-declared identity and clock error bounds, not independent verification. Latest causal sensor '
                 'only; invalid newest values do not fall back. Activity fraction is duration-weighted across reviewed '
                 'nonoverlapping intervals; coverage uses conservative clock bounds. Missing context is not zero. '
                 'Observation, receipt and review availability all constrain historical use. No pixels or model fit.')
    require(len(encode(result)) <= LIMIT, 'aligned context exceeds 8 MiB; reduce input scope')
    return result


def attach_context(timeline, binding, root):
    require(isinstance(binding, dict) and set(binding) == {'plan', 'artifact', 'sha256'}, 'invalid context binding')
    path = relative(root, binding['artifact'])
    require(path.stat().st_size <= LIMIT and digest(path) == binding['sha256'], 'context artifact hash mismatch')
    saved = read_json(path, limit=LIMIT); regenerated = build_context(relative(root, binding['plan']))
    require({k:v for k,v in saved.items() if k != 'created_at'} == {k:v for k,v in regenerated.items() if k != 'created_at'},
            'context differs from regenerated source records')
    for name in ('animal_id', 'enclosure_id', 'dataset_kind'):
        require(saved[name] == timeline['identity'][name], 'context identity mismatch')
    by_id = {row['record_id']: row for row in saved['rows']}
    require(set(by_id) == {row['record_id'] for row in timeline['rows']}, 'context must cover exact observation anchors')
    for row in timeline['rows']:
        context = by_id[row['record_id']]
        require(all(required_time(row[key]) == required_time(context[key]) for key in ('observed_at', 'as_of')),
                'context observation/as_of mismatch')
        if row['features'] is not None: row['features'].update(context['features'])
        row['context'] = dict(feature_version=CONTEXT_VERSION, row_sha256=fingerprint(context),
                              audit=context['audit'])
    timeline['context_binding'] = binding
    timeline['feature_version'] = FEATURE_VERSION
    timeline['unavailable_feature_families'] = ['skin_texture']
    timeline['evidence'] += ' Context is a separately hashed/regenerated, operator-declared input; per-feature missingness remains explicit.'
    return timeline


def main(argv=None):
    parser = argparse.ArgumentParser(description='Align declared behaviour and environment metadata on the declared CPU host')
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execution-host',required=True)
    args=parser.parse_args(argv)
    try:
        from .appearance_predictor import native_preflight
        require(not args.output.exists(), 'output already exists; choose a new version')
        preflight,guard=native_preflight(dict(execution_host=args.execution_host))
        result=build_context(args.plan,guard);guard();save_artifact(args.output,result)
        print(json.dumps(dict(output=str(args.output.resolve()),rows=len(result['rows']),preflight=preflight,actual_model_fit=False,actuation_allowed=False)))
        return 0
    except (RecorderError,OSError,ValueError,KeyError,TypeError,ImportError,subprocess.TimeoutExpired) as exc:
        print(json.dumps(dict(error=type(exc).__name__,message=str(exc))),file=sys.stderr);return 1


if __name__ == '__main__':
    raise SystemExit(main())
