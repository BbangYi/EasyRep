"""Frozen, retrospective cycle evaluation. No model fitting, pixels or control."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance_series import ARTIFACT_LIMIT, load_artifact
from .appearance_timeline import build_timeline, linked_cycles
from .core import RecorderError, encode, identifier, now, number, read_json, relative, require, timestamp

FEATURE_VERSION = 'past-only-reviewed-srgb-v1'
FEATURE_VERSIONS = (FEATURE_VERSION, 'past-only-reviewed-srgb-context-v1',
                    'past-only-reviewed-srgb-texture-v1', 'past-only-reviewed-srgb-context-texture-v1')
COHORT_LIMIT = 16 * 1024**2


def without_created(value):
    require(isinstance(value, dict), 'artifact object required')
    return {key: item for key, item in value.items() if key != 'created_at'}


def required_time(value):
    result = timestamp(value)
    require(result is not None, 'a non-null timestamp is required')
    return result


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {
        'schema_version', 'kind', 'experiment_id', 'dataset_kind', 'feature_version', 'mode',
        'fit_cutoff', 'evaluation_start', 'evaluation_end', 'labels_as_of', 'timelines', 'anchors',
        'minimums', 'acceptance', 'observer', 'evidence_reference'}, 'invalid evaluation plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_evaluation_plan', 'unsupported evaluation plan')
    identifier(plan['experiment_id'])
    identifier(plan['observer'])
    require(isinstance(plan['evidence_reference'], str) and 0 < len(plan['evidence_reference'].strip()) <= 1024,
            'evaluation design evidence required')
    require(plan['feature_version'] in FEATURE_VERSIONS, 'unsupported feature version')
    require(plan['dataset_kind'] in ('real', 'test'), 'invalid dataset_kind')
    require(plan['mode'] in ('future_cycle', 'held_out_animal'), 'separate evaluation mode required')
    fit, start, end, labels = [required_time(plan[key]) for key in (
        'fit_cutoff', 'evaluation_start', 'evaluation_end', 'labels_as_of')]
    require(fit < start < end <= labels, 'fit/evaluation/label cutoffs must be ordered')
    require(isinstance(plan['minimums'], dict) and set(plan['minimums']) == {
        'train_cycles', 'train_animals', 'evaluation_cycles', 'evaluation_animals'}, 'declare sample minimums')
    for value in plan['minimums'].values():
        require(type(value) is int and 1 <= value <= 8192, 'sample minimums must be positive integers')
    require(isinstance(plan['acceptance'], dict) and set(plan['acceptance']) == {
        'min_scored_fraction', 'max_mean_interval_error_hours', 'min_relative_error_reduction'},
        'declare comparison criteria before freezing')
    number(plan['acceptance']['min_scored_fraction'], 1e-12, 1)
    number(plan['acceptance']['max_mean_interval_error_hours'], 0, 8760)
    number(plan['acceptance']['min_relative_error_reduction'], 1e-12, 1)
    require(isinstance(plan['timelines'], list) and 1 <= len(plan['timelines']) <= 16,
            'one to sixteen explicit timelines required')
    require(isinstance(plan['anchors'], list) and 1 <= len(plan['anchors']) <= 2048,
            'one to 2048 explicit evaluation anchors required')


def load_inputs(plan, root):
    datasets, frames, species, total_bytes = {}, set(), set(), 0
    for entry in plan['timelines']:
        require(isinstance(entry, dict) and set(entry) == {'plan', 'timeline', 'sha256'},
                'timeline path, plan and byte hash required')
        path = relative(root, entry['timeline'])
        require(path.stat().st_size <= 4 * 1024**2, 'timeline exceeds 4 MiB')
        content = path.read_bytes()
        total_bytes += len(content)
        require(hashlib.sha256(content).hexdigest() == entry['sha256'], 'timeline byte hash mismatch')
        saved = json.loads(content)
        temporal_path = relative(root, entry['plan'])
        temporal = read_json(temporal_path, limit=ARTIFACT_LIMIT)
        if 'textures' in temporal:
            from .appearance_texture_timeline import texture_inputs
            _, texture_bytes = texture_inputs(temporal['textures'], temporal_path.parent)
            total_bytes += texture_bytes
            require(total_bytes <= 32 * 1024**2, 'cohort metadata exceeds 32 MiB')
        if 'context' in temporal:
            binding = temporal['context']
            context_path = relative(temporal_path.parent, binding['plan'])
            context_plan = read_json(context_path, limit=8 * 1024**2)
            total_bytes += context_path.stat().st_size + relative(temporal_path.parent, binding['artifact']).stat().st_size
            total_bytes += sum(relative(context_path.parent, source['path']).stat().st_size for source in context_plan['sources'])
            require(total_bytes <= 32 * 1024**2, 'cohort metadata exceeds 32 MiB')
        series_path = relative(temporal_path.parent, temporal['series'])
        series = read_json(series_path, limit=ARTIFACT_LIMIT)
        artifacts = {}
        total_bytes += temporal_path.stat().st_size + series_path.stat().st_size
        require(isinstance(series['records'], list) and len(series['records']) <= 512, 'too many artifacts')
        for name in series['records']:
            artifact_path = relative(series_path.parent, name)
            total_bytes += artifact_path.stat().st_size
            require(total_bytes <= 32 * 1024**2, 'cohort metadata exceeds 32 MiB')
            artifact, _ = load_artifact(artifact_path)
            artifacts[artifact['metadata']['record_id']] = artifact
            if artifact['metadata']['kind'] == 'color_observation':
                frame = artifact['files']['image']['sha256']
                require(frame not in frames, 'repeated source image across cohort')
                frames.add(frame)
        regenerated = build_timeline(temporal_path)
        require(without_created(saved) == without_created(regenerated),
                'timeline disagrees with regenerated reviewed artifacts')
        require(saved['feature_version'] == plan['feature_version'], 'feature version mismatch')
        require(saved['identity']['dataset_kind'] == plan['dataset_kind'], 'dataset_kind mismatch')
        animal = saved['identity']['animal_id']
        require(animal not in datasets, 'one complete timeline per animal required')
        species.add(saved['identity']['species'])
        datasets[animal] = (saved, linked_cycles(temporal['cycles'], artifacts))
    require(len(species) == 1, 'separate species require separate evaluations')
    return datasets


def build_cohort(plan_path):
    plan_path = Path(plan_path)
    plan = read_json(plan_path, limit=ARTIFACT_LIMIT)
    validate_plan(plan)
    datasets = load_inputs(plan, plan_path.parent)
    fit = required_time(plan['fit_cutoff'])
    training, intervals, lookup = [], [], {}
    for animal, (dataset, cycles) in datasets.items():
        for row in dataset['rows']:
            lookup[(animal, row['record_id'])] = row
        for cycle in cycles:
            if cycle['role'] != 'train':
                continue
            events = [cycle[key + '_event'] for key in ('previous_completed', 'started', 'completed')]
            require(all(max(event['latest'], event['available']) <= fit for event in events),
                    'training cycle label crosses fit cutoff')
            rows = [row for row in dataset['rows'] if row['cycle_id'] == cycle['cycle_id']]
            require(all(required_time(row['as_of']) <= fit for row in rows),
                    'training feature crosses fit cutoff')
            usable = [row for row in rows if row['target'] is not None]
            for row in usable:
                require(required_time(row['target']['available_at']) <= fit,
                        'training target crosses fit cutoff')
                training.append({'animal_id': animal, **row})
            if usable:
                previous, start, end = events
                intervals.append(dict(animal_id=animal, cycle_id=cycle['cycle_id'],
                    completed_at=end['latest'].isoformat(), hours=[
                        (start['earliest'] - previous['latest']).total_seconds() / 3600,
                        (start['latest'] - previous['earliest']).total_seconds() / 3600]))
    train_animals = {item['animal_id'] for item in intervals}
    forecasts, truths, baseline, used_records, used_cycles = [], {}, [], set(), set()
    role_animals = {'validation': set(), 'test': set()}
    for anchor in plan['anchors']:
        require(isinstance(anchor, dict) and set(anchor) == {'animal_id', 'record_id'}, 'invalid anchor')
        key = (identifier(anchor['animal_id']), identifier(anchor['record_id']))
        require(key in lookup and key not in used_records, 'unknown or duplicate evaluation anchor')
        used_records.add(key)
        row = lookup[key]
        require(row['role'] in (None, 'validation', 'test'), 'training record cannot be an evaluation anchor')
        require(required_time(plan['evaluation_start']) <= required_time(row['as_of'])
                < required_time(plan['evaluation_end']), 'anchor outside prediction window')
        if plan['mode'] == 'future_cycle':
            require(key[0] in train_animals, 'personalized evaluation requires animal training history')
        else:
            require(key[0] not in train_animals, 'held-out animal overlaps training animals')
        if row['cycle_id'] is not None:
            cycle_key = (key[0], row['cycle_id'])
            require(cycle_key not in used_cycles, 'only one evaluation anchor per cycle allowed')
            used_cycles.add(cycle_key)
            role_animals[row['role']].add(key[0])
        # Only this label-free view is exported to a future fitting/forecast runner.
        forecast = {name: value for name, value in row.items() if name not in ('target', 'reasons')}
        forecast['animal_id'] = key[0]
        forecast['feature_status'] = 'available' if row['features'] is not None else 'excluded'
        forecasts.append(forecast)
        truths[key] = row['target']
        history = [item for item in intervals if item['animal_id'] == key[0]]
        if plan['mode'] == 'future_cycle':
            history = sorted(history, key=lambda item: required_time(item['completed_at']))[-1:]
        else:
            history = intervals
        elapsed = row['features'].get('hours_since_previous_completion') if row['features'] else None
        prediction = None
        if history and elapsed is not None:
            duration = median(mean(item['hours']) for item in history)
            prediction = max(0., duration - mean(elapsed))
        baseline.append({**anchor, 'hours_until_start': prediction,
                         'method': 'last_individual_interval' if plan['mode'] == 'future_cycle'
                                   else 'training_population_median',
                         'source_cycle': [history[0]['animal_id'], history[0]['cycle_id']]
                                         if plan['mode'] == 'future_cycle' and history else None})
    if plan['mode'] == 'held_out_animal':
        require(not role_animals['validation'] & role_animals['test'],
                'held-out validation and test animals must also be disjoint')
    # Validation observations and not-yet-confirmed labels cannot satisfy test sufficiency.
    scored_test_cycles = {(row['animal_id'], row['cycle_id']) for row in forecasts
                         if row['role'] == 'test' and truths[(row['animal_id'], row['record_id'])] is not None
                         and required_time(truths[(row['animal_id'], row['record_id'])]['available_at'])
                         <= required_time(plan['labels_as_of'])}
    counts = dict(train_cycles=len(intervals), train_animals=len(train_animals),
                  evaluation_cycles=len(scored_test_cycles),
                  evaluation_animals=len({key[0] for key in scored_test_cycles}))
    reasons = ['insufficient_' + key for key, minimum in plan['minimums'].items() if counts[key] < minimum]
    if plan['dataset_kind'] != 'real':
        reasons.append('synthetic_dataset')
    result = dict(schema_version=1, kind='appearance_frozen_cohort', created_at=now(),
        experiment_id=plan['experiment_id'], dataset_kind=plan['dataset_kind'], feature_version=plan['feature_version'],
        mode=plan['mode'], evaluation_plan_sha256=fingerprint(plan), timelines=plan['timelines'],
        fit_cutoff=plan['fit_cutoff'], evaluation_start=plan['evaluation_start'],
        evaluation_end=plan['evaluation_end'], labels_as_of=plan['labels_as_of'],
        minimums=plan['minimums'], acceptance=plan['acceptance'], counts=counts,
        training_rows=training, forecast_rows=forecasts, baseline=baseline,
        baseline_training_cycles=intervals,
        model_fitting_allowed=not reasons, gate_reasons=reasons, actual_model_fit=False,
        biological_validation_complete=False, actuation_allowed=False,
        evidence='Retrospective design, structurally checked declared data. Source pixels, identity, clocks '
                 'and biological sufficiency are not independently established. Minimums are operator declarations. '
                 'Fitting also requires fresh execution-host resource checks. Forecast export excludes evaluation targets. '
                 'Baseline uses the last eligible individual interval or training-population median for a new animal. '
                 'Baseline interval midpoints are conventions, not confidence intervals. No model is fitted.')
    return result, truths


def freeze_cohort(plan_path, output_path):
    require(not Path(output_path).exists(), 'output already exists; use a new version')
    result, _ = build_cohort(plan_path)
    require(len(encode(result)) <= COHORT_LIMIT, 'cohort output exceeds byte limit; reduce the declared cohort')
    save_artifact(output_path, result)
    return result


def interval_error(prediction, bounds):
    return max(bounds[0] - prediction, 0., prediction - bounds[1])


def summarize(rows, name):
    errors = [row[name + '_error_hours'] for row in rows if row[name + '_error_hours'] is not None]
    return dict(anchors=len(rows), scored=len(errors), scored_fraction=len(errors) / len(rows),
                missing=sum(row[name + '_status'] == 'missing' for row in rows),
                abstained=sum(row[name + '_status'] == 'abstained' for row in rows),
                mean_interval_error_hours=mean(errors) if errors else None,
                within_observed_interval_fraction=sum(error == 0 for error in errors) / len(errors) if errors else None)


def evaluate_predictions(plan_path, cohort_path, predictions_path):
    cohort_path = Path(cohort_path)
    frozen = read_json(cohort_path, limit=COHORT_LIMIT)
    regenerated, truths = build_cohort(plan_path)
    require(without_created(frozen) == without_created(regenerated), 'frozen cohort or design changed')
    payload = read_json(Path(predictions_path), limit=4 * 1024**2)
    require(isinstance(payload, dict) and set(payload) == {
        'schema_version', 'kind', 'dataset_kind', 'feature_version', 'model_id', 'cohort_sha256', 'rows'},
        'invalid prediction artifact')
    require(type(payload['schema_version']) is int and payload['schema_version'] == 1
            and payload['kind'] == 'appearance_point_predictions', 'unsupported predictions')
    identifier(payload['model_id'])
    require(payload['dataset_kind'] == frozen['dataset_kind'] and payload['feature_version'] == frozen['feature_version'],
            'prediction dataset_kind or feature version mismatch')
    require(payload['cohort_sha256'] == hashlib.sha256(cohort_path.read_bytes()).hexdigest(),
            'prediction cohort hash mismatch')
    require(isinstance(payload['rows'], list) and len(payload['rows']) <= len(truths), 'too many predictions')
    candidates = {}
    for prediction in payload['rows']:
        require(isinstance(prediction, dict) and set(prediction) == {
            'animal_id', 'record_id', 'hours_until_start'}, 'invalid point prediction')
        key = (identifier(prediction['animal_id']), identifier(prediction['record_id']))
        require(key in truths and key not in candidates, 'unknown or duplicate prediction key')
        if prediction['hours_until_start'] is not None:
            number(prediction['hours_until_start'], 0, 8760)
        candidates[key] = prediction['hours_until_start']
    baselines = {(row['animal_id'], row['record_id']): row['hours_until_start'] for row in frozen['baseline']}
    rows = []
    for forecast in frozen['forecast_rows']:
        key = (forecast['animal_id'], forecast['record_id'])
        target = truths[key]
        status = ('unlabelled' if target is None else 'label_pending'
                  if required_time(target['available_at']) > required_time(frozen['labels_as_of']) else 'available')
        row = dict(animal_id=key[0], record_id=key[1], cycle_id=forecast['cycle_id'],
                   role=forecast['role'], label_status=status,
                   target_hours=target['hours_until_start'] if status == 'available' else None)
        for name, values in [('candidate', candidates), ('baseline', baselines)]:
            prediction = values.get(key)
            row[name + '_status'] = 'missing' if key not in values else 'abstained' if prediction is None else 'provided'
            row[name + '_hours_until_start'] = prediction
            row[name + '_error_hours'] = (interval_error(prediction, row['target_hours'])
                                          if status == 'available' and prediction is not None else None)
        rows.append(row)
    # Validation and test are never pooled into an acceptance decision.
    groups = {}
    for role in ('validation', 'test'):
        selected = [row for row in rows if row['role'] == role]
        if selected:
            groups[role] = comparison(selected, frozen['acceptance'])
    aggregate = comparison(rows, frozen['acceptance'])
    return dict(schema_version=1, kind='appearance_interval_evaluation', created_at=now(),
        cohort_sha256=payload['cohort_sha256'], model_id=payload['model_id'], dataset_kind=frozen['dataset_kind'],
        mode=frozen['mode'], rows=rows, candidate=aggregate['candidate'], baseline=aggregate['baseline'],
        paired=aggregate['paired'], by_role=groups,
        comparison_criteria_passed=bool(groups.get('test', {}).get('criteria_passed'))
                                  and frozen['model_fitting_allowed'],
        biological_validation_complete=False, actuation_allowed=False,
        evidence='Offline point timing scores only. Interval containment is not calibrated probability coverage. '
                 'Pending/unlabelled rows remain unscored, never negative. No survival censoring assumption. '
                 'One anchor per cycle does not measure daily false alarms, missed cycles, calibration or prospective '
                 'lead time. Supplied model IDs/hashes do not prove honest fitting; a runner audit remains required.')


def comparison(rows, acceptance):
    candidate, baseline = summarize(rows, 'candidate'), summarize(rows, 'baseline')
    pairs = [row for row in rows if row['candidate_error_hours'] is not None and row['baseline_error_hours'] is not None]
    candidate_error = mean(row['candidate_error_hours'] for row in pairs) if pairs else None
    baseline_error = mean(row['baseline_error_hours'] for row in pairs) if pairs else None
    reduction = (baseline_error - candidate_error) / baseline_error if baseline_error else None
    passed = (len(pairs) / len(rows) >= acceptance['min_scored_fraction']
              and candidate_error is not None and candidate_error <= acceptance['max_mean_interval_error_hours']
              and reduction is not None and reduction >= acceptance['min_relative_error_reduction'])
    return dict(candidate=candidate, baseline=baseline, paired=dict(count=len(pairs),
                mean_candidate_error_hours=candidate_error, mean_baseline_error_hours=baseline_error,
                relative_error_reduction=reduction), criteria_passed=passed)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Freeze or score a retrospective appearance cohort; no model fitting')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cohort', type=Path)
    parser.add_argument('--predictions', type=Path)
    args = parser.parse_args(argv)
    try:
        require(not args.output.exists(), 'output already exists; use a new version')
        require((args.cohort is None) == (args.predictions is None), 'cohort and predictions must be supplied together')
        if args.cohort is None:
            result = freeze_cohort(args.plan, args.output)
        else:
            result = evaluate_predictions(args.plan, args.cohort, args.predictions)
            save_artifact(args.output, result)
        print(json.dumps(dict(output=str(args.output.resolve()), kind=result['kind'],
                              biological_validation_complete=False, actuation_allowed=False)))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(error=type(exc).__name__, message=str(exc))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
