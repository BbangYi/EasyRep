"""Past-only colour features and explicitly linked interval targets; no model fit."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance_series import ARTIFACT_LIMIT, build_series, load_artifact
from .core import RecorderError, encode, identifier, now, number, read_json, relative, require, timestamp


def validate_features(features):
    require(isinstance(features, dict) and set(features) == {
        'selected_pixels', 'image_fraction', 'rgb_median', 'rgb_iqr',
        'saturation_median', 'value_median', 'clipped_pixel_fraction'},
        'complete reviewed-srgb-v1 features required')
    require(type(features['selected_pixels']) is int and 64 <= features['selected_pixels'] <= 4 * 1024**2,
            'invalid selected skin pixel count')
    number(features['image_fraction'], 1e-12, 1)
    for key in ('rgb_median', 'rgb_iqr'):
        require(isinstance(features[key], list) and len(features[key]) == 3, 'three RGB values required')
        for value in features[key]:
            number(value, 0, 255)
    for key in ('saturation_median', 'value_median', 'clipped_pixel_fraction'):
        number(features[key], 0, 1)


def linked_cycles(declarations, artifacts):
    require(isinstance(declarations, list) and len(declarations) <= 128, 'at most 128 explicit cycles allowed')
    result, ids, starts, completions = [], set(), set(), set()
    events = {key: value for key, value in artifacts.items() if value['metadata']['kind'] == 'shedding_event'}
    for declaration in declarations:
        require(isinstance(declaration, dict) and set(declaration) == {
            'cycle_id', 'previous_completed', 'started', 'completed', 'role', 'observer', 'evidence_reference'},
            'invalid cycle link fields')
        cycle_id = identifier(declaration['cycle_id'])
        identifier(declaration['observer'])
        evidence = declaration['evidence_reference']
        require(isinstance(evidence, str) and 0 < len(evidence.strip()) <= 1024, 'cycle linkage evidence required')
        require(cycle_id not in ids, 'duplicate cycle_id')
        require(declaration['role'] in ('train', 'validation', 'test'), 'explicit cycle role required')
        ids.add(cycle_id)
        cycle = dict(declaration)
        for key, stage in [('previous_completed', 'completed'), ('started', 'started'), ('completed', 'completed')]:
            record_id = identifier(declaration[key])
            require(record_id in events and events[record_id]['metadata']['stage'] == stage,
                    'cycle must reference existing events with the correct stages')
            artifact = events[record_id]
            metadata = artifact['metadata']
            cycle[key + '_event'] = {'record_id': record_id, 'earliest': timestamp(metadata['earliest_at']),
                                    'latest': timestamp(metadata['latest_at']), 'available': timestamp(artifact['created_at'])}
        previous, start, end = [cycle[key + '_event'] for key in ('previous_completed', 'started', 'completed')]
        require(previous['latest'] < start['earliest'] and start['latest'] <= end['earliest'],
                'cycle event intervals must be strictly ordered without ambiguous start/completion overlap')
        require(start['record_id'] not in starts and end['record_id'] not in completions,
                'a start or completion cannot label multiple cycles')
        starts.add(start['record_id'])
        completions.add(end['record_id'])
        references = {previous['record_id'], start['record_id'], end['record_id']}
        cycle['unresolved_event_ids'] = sorted(key for key, artifact in events.items()
            if key not in references
            and timestamp(artifact['metadata']['latest_at']) > previous['latest']
            and timestamp(artifact['metadata']['earliest_at']) < end['latest'])
        result.append(cycle)
    result.sort(key=lambda cycle: cycle['started_event']['earliest'])
    order = {'train': 0, 'validation': 1, 'test': 2}
    for earlier, later in zip(result, result[1:]):
        require(earlier['completed_event']['latest'] <= later['previous_completed_event']['latest'],
                'linked cycle windows overlap')
        require(order[earlier['role']] <= order[later['role']],
                'later cycles cannot be assigned to an earlier training role')
    return result


def temporal_features(current, candidates, cycle, as_of, max_gap_hours):
    observed = timestamp(current['metadata']['observed_at'])
    lower = cycle['previous_completed_event']['latest'] if cycle else None
    eligible = [artifact for artifact in candidates
                if artifact['comparison_group'] == current['comparison_group']
                and timestamp(artifact['metadata']['observed_at']) < observed
                and timestamp(artifact['created_at']) <= as_of
                and (lower is None or timestamp(artifact['metadata']['observed_at']) > lower)]
    eligible.sort(key=lambda artifact: timestamp(artifact['metadata']['observed_at']), reverse=True)
    history, boundary = [], observed
    for artifact in eligible:
        time = timestamp(artifact['metadata']['observed_at'])
        if (boundary - time).total_seconds() / 3600 > max_gap_hours:
            break
        history.append(artifact)
        boundary = time
    history.reverse()
    values = current['features']
    features = {**values, 'history_record_ids': [item['metadata']['record_id'] for item in history],
                'history_hours': (observed - boundary).total_seconds() / 3600,
                'rgb_delta': None, 'saturation_delta': None, 'value_delta': None,
                'rgb_change_per_hour': None, 'hours_since_previous_completion': None}
    if history:
        features['rgb_delta'] = [values['rgb_median'][index] - median(
            item['features']['rgb_median'][index] for item in history) for index in range(3)]
        for name in ('saturation', 'value'):
            features[name + '_delta'] = values[name + '_median'] - median(
                item['features'][name + '_median'] for item in history)
        previous = history[-1]
        hours = (observed - timestamp(previous['metadata']['observed_at'])).total_seconds() / 3600
        features['rgb_change_per_hour'] = [(value - before) / hours
                                          for value, before in zip(values['rgb_median'], previous['features']['rgb_median'])]
    if cycle:
        previous = cycle['previous_completed_event']
        if previous['available'] <= as_of:
            features['hours_since_previous_completion'] = [
                (as_of - previous[key]).total_seconds() / 3600 for key in ('latest', 'earliest')]
    return features


def build_timeline(plan_path):
    plan_path = Path(plan_path)
    plan = read_json(plan_path, limit=ARTIFACT_LIMIT)
    require(isinstance(plan, dict) and set(plan) == {
        'schema_version', 'kind', 'series', 'max_gap_hours', 'cycles'} | {key for key in ('context', 'textures') if key in plan}, 'invalid temporal plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_temporal_plan', 'unsupported temporal plan')
    number(plan['max_gap_hours'], 1e-6, 8760)
    series_path = relative(plan_path.parent, plan['series'])
    series = build_series(series_path)
    artifacts, measured, timestamps = {}, [], set()
    for entry in series['records']:
        artifact, digest = load_artifact(relative(series_path.parent, entry['artifact']))
        require(digest == entry['artifact_sha256'], 'artifact changed during temporal preparation')
        artifacts[entry['record_id']] = artifact
        if artifact['status'] == 'measured':
            validate_features(artifact['features'])
            key = (artifact['comparison_group'], timestamp(artifact['metadata']['observed_at']))
            require(key not in timestamps, 'ambiguous simultaneous observations in one comparison group')
            timestamps.add(key)
            measured.append(artifact)
    cycles = linked_cycles(plan['cycles'], artifacts)
    textures, texture_bytes = {}, 0
    if 'textures' in plan:
        from .appearance_texture_timeline import load_textures, feature_availability, attach_texture
        textures, texture_bytes = load_textures(plan['textures'], plan_path.parent, artifacts)
    rows = []
    for entry in series['records']:
        if entry['kind'] != 'color_observation':
            continue
        artifact = artifacts[entry['record_id']]
        observed = timestamp(entry['observed_at'])
        # A backfilled review cannot pretend its features were available at capture time.
        as_of = max(observed, timestamp(artifact['created_at']))
        if entry['record_id'] in textures:
            as_of = feature_availability(artifact, textures[entry['record_id']])
        matches = [cycle for cycle in cycles if cycle['previous_completed_event']['latest'] < observed
                   <= cycle['completed_event']['latest']]
        require(len(matches) <= 1, 'observation belongs to overlapping cycles')
        cycle = matches[0] if matches else None
        reasons = list(entry['reasons'])
        row = {'record_id': entry['record_id'], 'observed_at': entry['observed_at'], 'as_of': as_of.isoformat(),
               'artifact': entry['artifact'], 'artifact_sha256': entry['artifact_sha256'],
               'comparison_group': entry['comparison_group'], 'cycle_id': cycle['cycle_id'] if cycle else None,
               'role': cycle['role'] if cycle else None, 'features': None, 'target': None, 'reasons': reasons}
        if artifact['status'] == 'measured':
            row['features'] = temporal_features(artifact, measured, cycle, as_of, plan['max_gap_hours'])
        if cycle is None:
            reasons.append('no_explicit_cycle_link')
        else:
            previous, start, end = [cycle[key + '_event'] for key in ('previous_completed', 'started', 'completed')]
            if previous['available'] > as_of:
                reasons.append('previous_completion_not_available')
            if cycle['unresolved_event_ids']:
                reasons.append('unresolved_event_in_cycle')
            if as_of >= start['earliest']:
                reasons.append('not_strictly_before_start')
            if not reasons:
                row['target'] = {'kind': 'interval_until_confirmed_start',
                                 'hours_until_start': [(start[key] - as_of).total_seconds() / 3600
                                                       for key in ('earliest', 'latest')],
                                 'start_record_id': start['record_id'], 'completion_record_id': end['record_id'],
                                 'available_at': max(start['available'], end['available'], end['latest']).isoformat()}
        rows.append(row)
    result = {'schema_version': 1, 'kind': 'appearance_temporal_dataset', 'created_at': now(),
            'feature_version': 'past-only-reviewed-srgb-v1', 'identity': series['identity'],
            'plan_sha256': fingerprint(plan), 'series_manifest_sha256': series['manifest_sha256'],
            'source_records': series['records'], 'max_gap_hours': plan['max_gap_hours'],
            'cycle_links': plan['cycles'], 'rows': rows,
            'counts': {'color_rows': len(rows), 'linked_cycles': len(cycles),
                       'interval_labelled_rows': sum(row['target'] is not None for row in rows)},
            'unavailable_feature_families': ['skin_texture', 'aligned_behaviour', 'aligned_environment'],
            'training_readiness': 'not_assessed', 'shedding_prediction': None, 'actuation_allowed': False,
            'evidence': 'Operator-declared identities and cycle links. Structure and numeric ranges checked; '
                        'raw media, feature values and clocks are not independently reverified. Artifact creation '
                        'time is conservative feature availability; target availability is recorded separately. '
                        'Cycle roles are fixed, but fit cutoffs, held-out-animal evaluation and biological sample '
                        'sufficiency are not assessed. Unlabelled rows are not negative examples. No model fitted.'}
    if 'context' in plan:
        from .appearance_context import attach_context
        result = attach_context(result, plan['context'], plan_path.parent)
    if 'textures' in plan:
        result = attach_texture(result, plan['textures'], textures, cycles, texture_bytes)
    require(len(encode(result)) <= 4 * 1024**2, 'timeline output exceeds4MiB; reduce the declared scope')
    return result


def write_timeline(plan_path, output_path):
    require(not Path(output_path).exists(), 'output already exists; choose a new versioned filename')
    result = build_timeline(plan_path)
    save_artifact(output_path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build past-only colour features and confirmed-cycle interval targets')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = write_timeline(args.plan, args.output)
        print(json.dumps({'output': str(args.output.resolve()), 'counts': result['counts'],
                          'training_readiness': result['training_readiness'], 'actuation_allowed': False}))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
