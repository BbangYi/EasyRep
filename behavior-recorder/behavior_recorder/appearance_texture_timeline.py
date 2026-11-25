"""Causal texture joins from frozen reviewed sidecars; no pixel re-extraction."""
import math
from pathlib import Path
from statistics import median

from .analysis_features import fingerprint
from .appearance_series import ARTIFACT_LIMIT, load_artifact, validate_artifact
from .appearance_texture import FEATURE_VERSION, MAX_PIXELS, validate_plan
from .core import digest, number, read_json, relative, require, timestamp

TEXTURE_LIMIT = 8 * 1024**2
TEXTURE_VERSIONS = ('past-only-reviewed-srgb-texture-v1', 'past-only-reviewed-srgb-context-texture-v1')
TEXTURE_FEATURES = ('texture_mean_absolute_difference', 'texture_rms_difference',
                    'texture_absolute_delta', 'texture_rms_delta',
                    'texture_absolute_rate', 'texture_rms_rate',
                    'texture_history_hours', 'texture_observation_age_hours')


def required_time(value):
    parsed = timestamp(value)
    require(parsed is not None, 'texture timestamp required')
    return parsed


def texture_inputs(bindings, root):
    """Count bounded metadata before loading features; shared with cohort accounting."""
    require(isinstance(bindings, list) and 1 <= len(bindings) <= 512, 'one to512 texture bindings required')
    entries, seen, total = [], set(), 0
    for binding in bindings:
        require(isinstance(binding, dict) and set(binding) == {'plan', 'artifact', 'sha256'}, 'invalid texture binding')
        plan_path, artifact_path = [relative(root, binding[key]) for key in ('plan', 'artifact')]
        require(artifact_path not in seen, 'duplicate texture artifact binding')
        seen.add(artifact_path)
        plan = read_json(plan_path, limit=ARTIFACT_LIMIT)
        validate_plan(plan)
        input_path = relative(plan_path.parent, plan['observation_input'])
        # Count the extra referenced colour read even when the series reads the same file.
        for path in (plan_path, artifact_path, input_path, relative(plan_path.parent, plan['observation_artifact'])):
            size = path.stat().st_size
            require(size <= ARTIFACT_LIMIT, 'texture metadata file exceeds64KiB')
            total += size
            require(total <= TEXTURE_LIMIT, 'texture metadata exceeds8MiB')
        entries.append((binding, plan_path, plan, artifact_path, input_path))
    return entries, total


def load_textures(bindings, root, colours):
    entries, total = texture_inputs(bindings, root)
    records = {}
    for binding, plan_path, plan, artifact_path, input_path in entries:
        texture, texture_hash = load_artifact(artifact_path)
        require(texture_hash == binding['sha256'], 'texture artifact hash mismatch')
        require(isinstance(texture, dict) and set(texture) == {
            'schema_version', 'kind', 'feature_version', 'created_at', 'available_at', 'status', 'observation',
            'observation_artifact', 'observation_metadata_sha256', 'plan_sha256', 'extraction', 'geometry',
            'review', 'implementation_sha256', 'runtime', 'physical_offset_mm', 'physical_offset_mm_interval',
            'features', 'measurements', 'comparison_group', 'reasons', 'files', 'media_reverified',
            'actual_model_fit', 'shedding_prediction', 'actuation_allowed', 'evidence'}, 'invalid texture observation')
        require(type(texture['schema_version']) is int and texture['schema_version'] == 1
                and texture['kind'] == 'appearance_texture_observation'
                and texture['feature_version'] == FEATURE_VERSION, 'unsupported texture observation')
        require(texture['actual_model_fit'] is False and texture['shedding_prediction'] is None
                and texture['actuation_allowed'] is False, 'only unpromoted texture observations allowed')
        observation = texture['observation']
        require(isinstance(observation, dict) and observation.get('record_id') in colours,
                'texture observation is absent from the declared series')
        rid = observation['record_id']
        require(rid not in records, 'duplicate texture observation binding')
        colour = colours[rid]
        metadata, colour_reasons = validate_artifact(colour)
        require(metadata['kind'] == 'color_observation' and observation == {key: metadata[key] for key in (
            'dataset_kind', 'record_id', 'animal_id', 'species', 'enclosure_id', 'body_region', 'observed_at')},
            'texture observation identity or timestamp mismatch')
        referenced, colour_hash = load_artifact(relative(plan_path.parent, plan['observation_artifact']))
        require(referenced == colour and colour_hash == plan['observation_sha256']
                and texture['observation_artifact'] == dict(path=plan['observation_artifact'], sha256=colour_hash),
                'texture observation artifact binding mismatch')
        require(read_json(input_path, limit=ARTIFACT_LIMIT) == metadata
                and texture['files'] == colour['files']
                and texture['observation_metadata_sha256'] == colour['metadata_sha256'], 'texture observation source mismatch')
        require(texture['plan_sha256'] == fingerprint(plan)
                and all(texture[key] == plan[key] for key in ('extraction', 'geometry', 'review')), 'texture plan mismatch')
        implementation = {name: digest(Path(__file__).parent/name) for name in ('appearance_texture.py', 'appearance.py')}
        require(texture['implementation_sha256'] == implementation, 'texture extractor revision mismatch; use recorded revision')
        created, available, observed = [required_time(texture[key]) for key in ('created_at', 'available_at')] + [required_time(metadata['observed_at'])]
        require(available == max(created, required_time(colour['created_at']), observed), 'texture availability mismatch')
        reasons = texture['reasons']
        require(isinstance(reasons, list) and len(reasons) <= 32
                and all(isinstance(reason, str) and 0 < len(reason) <= 128 for reason in reasons), 'invalid texture reasons')
        required_reasons = validate_plan(plan) + colour_reasons
        require(set(required_reasons) <= set(reasons), 'texture review exclusions were removed')
        if texture['status'] == 'excluded':
            require(reasons and texture['features'] is None and texture['comparison_group'] is None,
                    'excluded texture cannot supply measurements')
        else:
            require(texture['status'] == 'measured' and not reasons and texture['media_reverified'] is True,
                    'measured texture requires completed source review')
            runtime = texture['runtime']
            require(isinstance(runtime, dict) and set(runtime) == {'python', 'numpy', 'pillow'}
                    and all(isinstance(v, str) and 0 < len(v) <= 128 for v in runtime.values()), 'texture runtime required')
            expected_group = fingerprint(dict(feature_version=FEATURE_VERSION, colour_group=colour['comparison_group'],
                extraction=plan['extraction'], geometry=plan['geometry'], implementation_sha256=implementation, runtime=runtime))
            require(texture['comparison_group'] == expected_group, 'texture comparison group mismatch')
            features, measurements = texture['features'], texture['measurements']
            require(isinstance(features, dict) and set(features) == {'mean_absolute_difference', 'root_mean_square_difference'}
                    and isinstance(measurements, dict) and set(measurements) == {
                        'horizontal', 'vertical', 'mean_absolute_difference', 'root_mean_square_difference', 'reasons'}
                    and measurements['reasons'] == [], 'complete texture measurements required')
            for axis in ('horizontal', 'vertical'):
                row = measurements[axis]
                require(isinstance(row, dict) and set(row) == {'pairs', 'mean_absolute_difference', 'mean_squared_difference'},
                        'invalid directional measurement')
                require(type(row['pairs']) is int
                        and plan['extraction']['minimum_pairs'] <= row['pairs'] <= min(MAX_PIXELS, colour['features']['selected_pixels']),
                        'invalid texture measurement pair count')
                absolute = number(row['mean_absolute_difference'], 0, 1)
                squared = number(row['mean_squared_difference'], 0, 1)
                require(absolute**2 - 1e-6 <= squared <= absolute + 1e-6, 'inconsistent directional measurement moments')
            expected = dict(mean_absolute_difference=math.fsum(measurements[a]['mean_absolute_difference'] for a in ('horizontal','vertical'))/2,
                root_mean_square_difference=math.sqrt(math.fsum(measurements[a]['mean_squared_difference'] for a in ('horizontal','vertical'))/2))
            for key, value in expected.items():
                require(math.isclose(number(features[key],0,1), value, rel_tol=1e-12, abs_tol=1e-12)
                        and measurements[key] == features[key], 'texture measurement summary mismatch')
            scale, error = plan['geometry']['pixels_per_mm'], plan['geometry']['scale_relative_error']
            require(texture['physical_offset_mm'] == plan['extraction']['pixel_offset']/scale
                    and texture['physical_offset_mm_interval'] == [plan['extraction']['pixel_offset']/(scale*f) for f in (1+error,1-error)],
                    'texture physical offset mismatch')
        records[rid] = texture
    return records, total


def feature_availability(colour, texture):
    available = max(required_time(colour['metadata']['observed_at']), required_time(colour['created_at']))
    if texture is not None and texture['status'] == 'measured':
        available = max(available, required_time(texture['available_at']))
    return available


def attach_texture(timeline, bindings, records, cycles, metadata_bytes):
    cycles = {cycle['cycle_id']: cycle for cycle in cycles}
    hashes = {rid: fingerprint(record) for rid, record in records.items()}
    for row in timeline['rows']:
        current = records.get(row['record_id'])
        values = dict.fromkeys(TEXTURE_FEATURES)
        audit = dict(status='unavailable', history_record_ids=[], reasons=['not_bound'])
        if current is not None:
            audit.update(status=current['status'], reasons=list(current['reasons']), artifact_fingerprint=hashes[row['record_id']],
                         available_at=current['available_at'], comparison_group=current['comparison_group'])
        if current is not None and current['status'] == 'measured' and row['features'] is not None:
            observed, as_of = required_time(row['observed_at']), required_time(row['as_of'])
            require(required_time(current['available_at']) <= as_of, 'texture not available to this anchor')
            cycle = cycles.get(row['cycle_id'])
            lower = cycle['previous_completed_event']['latest'] if cycle else None
            candidates = [t for t in records.values() if t['status'] == 'measured'
                and t['comparison_group'] == current['comparison_group']
                and required_time(t['observation']['observed_at']) < observed
                and required_time(t['available_at']) <= as_of
                and (lower is None or required_time(t['observation']['observed_at']) > lower)]
            candidates.sort(key=lambda t: required_time(t['observation']['observed_at']), reverse=True)
            history, boundary = [], observed
            for item in candidates:
                captured = required_time(item['observation']['observed_at'])
                if (boundary-captured).total_seconds()/3600 > timeline['max_gap_hours']:
                    break
                history.append(item); boundary = captured
            history.reverse()
            values.update(texture_mean_absolute_difference=current['features']['mean_absolute_difference'],
                texture_rms_difference=current['features']['root_mean_square_difference'],
                texture_history_hours=(observed-boundary).total_seconds()/3600,
                texture_observation_age_hours=(as_of-observed).total_seconds()/3600)
            if history:
                hours = (observed-required_time(history[-1]['observation']['observed_at'])).total_seconds()/3600
                for short, key in [('absolute','mean_absolute_difference'),('rms','root_mean_square_difference')]:
                    values['texture_'+short+'_delta'] = current['features'][key]-median(t['features'][key] for t in history)
                    values['texture_'+short+'_rate'] = (current['features'][key]-history[-1]['features'][key])/hours
            else:
                audit['reasons'].append('no_causal_comparable_texture_history')
            audit['history_record_ids'] = [t['observation']['record_id'] for t in history]
            audit['history_artifact_fingerprints'] = [hashes[rid] for rid in audit['history_record_ids']]
        if row['features'] is not None:
            row['features'].update(values)
        row['texture'] = audit
    timeline['texture_bindings'] = bindings
    timeline['texture_metadata_bytes'] = metadata_bytes
    timeline['feature_version'] = TEXTURE_VERSIONS[1 if 'context_binding' in timeline else 0]
    timeline['unavailable_feature_families'] = [v for v in timeline['unavailable_feature_families'] if v != 'skin_texture']
    timeline['evidence'] += (' Texture sidecar hashes, declared source bindings and measurement summaries checked; '
        'pixels are not re-extracted here and hashes are not execution attestation. Anchor availability includes '
        'current texture processing; targets, elapsed time and optional context use that same later time. '
        'Texture history requires earlier captures, causal availability and identical comparison groups within the linked cycle.')
    return timeline
