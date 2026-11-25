"""Frozen regular-grid alarm audit. No fitting, live alarms or physical control."""
import argparse
from datetime import timedelta, timezone
import hashlib
from pathlib import Path
from statistics import mean, median
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance_evaluation import (COHORT_LIMIT, FEATURE_VERSIONS, load_inputs,
                                    required_time, without_created)
from .core import RecorderError, encode, identifier, now, number, read_json, require

GRID_LIMIT = 8192
PLAN_LIMIT = 2 * 1024**2


def evidence(value):
    identifier(value['observer'])
    require(isinstance(value['evidence_reference'], str)
            and 0 < len(value['evidence_reference'].strip()) <= 1024, 'review evidence required')


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {
        'schema_version', 'kind', 'experiment_id', 'dataset_kind', 'feature_version', 'mode', 'role',
        'fit_cutoff', 'training_completed_at', 'model_id', 'evaluation_start', 'evaluation_end',
        'labels_as_of', 'cadence_hours', 'horizon_hours', 'minimum_lead_hours', 'max_lateness_seconds',
        'timelines', 'animals', 'negative_windows', 'observer', 'evidence_reference'}, 'invalid alarm plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_alarm_evaluation_plan', 'unsupported alarm plan')
    identifier(plan['experiment_id'])
    identifier(plan['model_id'])
    evidence(plan)
    require(plan['dataset_kind'] in ('real', 'test'), 'invalid dataset_kind')
    require(plan['feature_version'] in FEATURE_VERSIONS, 'unsupported feature version')
    require(plan['mode'] in ('future_cycle', 'held_out_animal'), 'invalid evaluation mode')
    require(plan['role'] in ('validation', 'test'), 'one separate evaluation role required')
    fit, start, end, labels = [required_time(plan[k]) for k in (
        'fit_cutoff', 'evaluation_start', 'evaluation_end', 'labels_as_of')]
    require(fit <= required_time(plan['training_completed_at']) < start < end <= labels,
            'fit cutoff, training completion, evaluation and label cutoffs must be ordered')
    number(plan['cadence_hours'], .001, 8760)
    horizon = number(plan['horizon_hours'], .001, 8760)
    require(number(plan['minimum_lead_hours'], 0, 8760) < horizon, 'minimum lead must be below horizon')
    number(plan['max_lateness_seconds'], 0, min(3600, plan['cadence_hours'] * 3600))
    require(isinstance(plan['timelines'], list) and 1 <= len(plan['timelines']) <= 16, 'bounded timelines required')
    require(isinstance(plan['animals'], list) and 1 <= len(plan['animals']) <= 16, 'bounded animals required')
    for animal in plan['animals']:
        identifier(animal)
    require(len(set(plan['animals'])) == len(plan['animals']), 'duplicate evaluation animal')
    slots = (end - start).total_seconds() / (plan['cadence_hours'] * 3600)
    require(slots * len(plan['animals']) <= GRID_LIMIT, 'decision grid exceeds limit')
    require(isinstance(plan['negative_windows'], list) and len(plan['negative_windows']) <= 1024,
            'bounded negative review windows required')


def label_ready(cycle, labels):
    start, end = cycle['started_event'], cycle['completed_event']
    return not cycle['unresolved_event_ids'] and max(start['available'], end['available'], end['latest']) <= labels


def baseline_history(plan, datasets):
    fit = required_time(plan['fit_cutoff'])
    trained = required_time(plan['training_completed_at'])
    history = []
    for animal, (dataset, cycles) in datasets.items():
        for cycle in cycles:
            if cycle['role'] != 'train':
                continue
            previous, start, end = [cycle[k + '_event'] for k in ('previous_completed', 'started', 'completed')]
            require(all(max(e['latest'], e['available']) <= fit for e in (previous, start, end)),
                    'training cycle crosses fit cutoff')
            require(all(max(e['latest'], e['available']) <= trained for e in (previous, start, end)),
                    'training cycle was unavailable at declared training completion')
            require(all(required_time(row['as_of']) <= fit for row in dataset['rows']
                        if row['cycle_id'] == cycle['cycle_id']), 'training feature crosses fit cutoff')
            require(all(required_time(row['as_of']) <= trained for row in dataset['rows']
                        if row['cycle_id'] == cycle['cycle_id']),
                    'training feature was unavailable at declared training completion')
            if cycle['unresolved_event_ids']:
                continue
            duration = mean(((start['earliest'] - previous['latest']).total_seconds() / 3600,
                             (start['latest'] - previous['earliest']).total_seconds() / 3600))
            history.append(dict(animal_id=animal, cycle_id=cycle['cycle_id'],
                                completed_at=end['latest'].isoformat(), duration_hours=duration))
    require(history, 'eligible training intervals required for baseline')
    train_animals = {animal for animal, (_, cycles) in datasets.items()
                     if any(cycle['role'] == 'train' for cycle in cycles)}
    if plan['mode'] == 'future_cycle':
        require(set(plan['animals']) <= {h['animal_id'] for h in history},
                'personalized evaluation needs training history')
    else:
        require(not set(plan['animals']) & train_animals, 'held-out animals overlap training')
    return history


def baseline_at(cycles, history, point):
    # Hold duration fixed from training. Later known completions only reset elapsed time.
    completions = {}
    for cycle in cycles:
        start, end = cycle['started_event'], cycle['completed_event']
        if max(start['latest'], start['available']) <= point < max(end['latest'], end['available']):
            return None
        for key in ('previous_completed_event', 'completed_event'):
            event = cycle[key]
            if max(event['latest'], event['available']) <= point:
                completions[event['record_id']] = event
    if not completions:
        return None
    previous = max(completions.values(), key=lambda e: e['latest'])
    elapsed = mean((point - previous[k]).total_seconds() / 3600 for k in ('earliest', 'latest'))
    return dict(hours_until_start=max(0., median(h['duration_hours'] for h in history) - elapsed),
                previous_completion=previous['record_id'])


def review_windows(plan, datasets):
    result, ids = {a: [] for a in plan['animals']}, set()
    for window in plan['negative_windows']:
        require(isinstance(window, dict) and set(window) == {'record_id', 'animal_id', 'kind',
            'start_at', 'end_at', 'available_at', 'observer', 'evidence_reference'}, 'invalid negative window')
        record = identifier(window['record_id'])
        require(record not in ids, 'duplicate negative review record')
        ids.add(record)
        animal = window['animal_id']
        require(animal in result and window['kind'] == 'confirmed_no_onset', 'invalid negative review identity')
        evidence(window)
        start, end, available = [required_time(window[k]) for k in ('start_at', 'end_at', 'available_at')]
        require(start < end <= available, 'negative review availability must follow review interval')
        for record in datasets[animal][0]['source_records']:
            if record['kind'] == 'shedding_event' and record['stage'] in ('started', 'uncertain'):
                require(end < required_time(record['earliest_at']) or start > required_time(record['latest_at']),
                        'negative review contradicts an onset or uncertain event')
        if available <= required_time(plan['labels_as_of']):
            result[animal].append((start, end))
    return {a: sorted(windows) for a, windows in result.items()}


def unlinked_ranges(dataset, cycles, plan):
    linked = {cycle[key] for cycle in cycles for key in ('previous_completed', 'started', 'completed')}
    ranges = []
    for record in dataset['source_records']:
        if record['kind'] != 'shedding_event' or record['record_id'] in linked:
            continue
        start, end = required_time(record['earliest_at']), required_time(record['latest_at'])
        # Without the matching endpoint, the extent of an active shed is unknown.
        if record['stage'] == 'started':
            end = max(end, required_time(plan['evaluation_end']) + timedelta(hours=plan['horizon_hours']))
        elif record['stage'] == 'completed':
            start = min(start, required_time(plan['evaluation_start']))
        ranges.append((start, end))
    return ranges


def truth_at(point, cycles, windows, blocked, horizon, labels):
    stop = point + timedelta(hours=horizon)
    unknown = dict(label=None, cycle_id=None, reason='unreviewed_period')
    if any(left <= stop and right >= point for left, right in blocked):
        return {**unknown, 'reason': 'unlinked_shedding_event'}
    for cycle in cycles:
        start, end = cycle['started_event'], cycle['completed_event']
        if start['earliest'] <= point <= end['latest']:
            return {**unknown, 'reason': 'active_or_uncertain_start'}
        if start['latest'] <= point:
            continue
        # Only the nearest next cycle can match this alert.
        if start['earliest'] <= stop:
            if not label_ready(cycle, labels):
                return {**unknown, 'reason': 'label_pending_or_unresolved'}
            if start['earliest'] > point and start['latest'] <= stop:
                return dict(label=1, cycle_id=cycle['cycle_id'], reason='confirmed_next_onset')
            return {**unknown, 'reason': 'onset_crosses_horizon_boundary'}
        break
    covered_until = point
    for start, end in windows:
        if end < covered_until:
            continue
        if start > covered_until:
            break
        covered_until = max(covered_until, end)
        if covered_until >= stop:
            return dict(label=0, cycle_id=None, reason='continuous_confirmed_no_onset_review')
    return unknown


def build_design(plan_path):
    plan_path = Path(plan_path)
    plan = read_json(plan_path, limit=PLAN_LIMIT)
    validate_plan(plan)
    datasets = load_inputs(plan, plan_path.parent)
    require(set(plan['animals']) <= set(datasets), 'unknown evaluation animal')
    history = baseline_history(plan, datasets)
    windows = review_windows(plan, datasets)
    start, end = required_time(plan['evaluation_start']), required_time(plan['evaluation_end'])
    grid, blocked = [], {}
    for animal in plan['animals']:
        dataset, cycles = datasets[animal]
        blocked[animal] = unlinked_ranges(dataset, cycles, plan)
        for cycle in cycles:
            if cycle['started_event']['earliest'] < end + timedelta(hours=plan['horizon_hours']) \
                    and cycle['completed_event']['latest'] >= start:
                require(cycle['role'] == plan['role'], 'evaluation window crosses another cycle role')
        if plan['mode'] == 'held_out_animal':
            require(all(c['role'] == plan['role'] for c in cycles), 'held-out roles must use separate animals')
        selected = history
        if plan['mode'] == 'future_cycle':
            selected = sorted((h for h in history if h['animal_id'] == animal),
                              key=lambda h: required_time(h['completed_at']))[-1:]
        point, index = start, 0
        while point < end:
            require(len(grid) < GRID_LIMIT, 'decision grid exceeds limit')
            grid.append(dict(decision_id=f'{animal}:{index}', animal_id=animal,
                scheduled_at=point.isoformat(), baseline=baseline_at(cycles, selected, point)))
            index += 1
            point = start + timedelta(hours=index * plan['cadence_hours'])
    result = dict(schema_version=1, kind='appearance_frozen_alarm_design', created_at=now(),
        plan_sha256=fingerprint(plan), dataset_kind=plan['dataset_kind'], model_id=plan['model_id'],
        experiment_id=plan['experiment_id'], role=plan['role'], mode=plan['mode'],
        measurement_code_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('appearance_alarm_evaluation.py', 'appearance_evaluation.py',
                         'appearance_timeline.py', 'appearance_series.py', 'appearance_context.py',
                         'appearance.py', 'core.py', 'analysis_features.py')},
        decision_grid=grid, baseline_training_cycles=history,
        biological_validation_complete=False, model_identity_verified=False, actuation_allowed=False)
    require(len(encode(result)) <= COHORT_LIMIT, 'design exceeds output limit')
    return result, plan, datasets, windows, blocked


def freeze_design(plan_path, output_path):
    require(not Path(output_path).exists(), 'output already exists; choose a new version')
    result, _, _, _, _ = build_design(plan_path)
    save_artifact(output_path, result)
    return result


def load_predictions(path, design_path, design, plan):
    payload = read_json(Path(path), limit=COHORT_LIMIT)
    require(isinstance(payload, dict) and set(payload) == {'schema_version', 'kind', 'dataset_kind',
        'model_id', 'design_sha256', 'rows'}, 'invalid alarm predictions')
    require(type(payload['schema_version']) is int and payload['schema_version'] == 1
            and payload['kind'] == 'appearance_alarm_predictions', 'unsupported alarm predictions')
    require(payload['dataset_kind'] == plan['dataset_kind'] and payload['model_id'] == plan['model_id'],
            'prediction dataset/model identity mismatch')
    require(payload['design_sha256'] == hashlib.sha256(Path(design_path).read_bytes()).hexdigest(),
            'frozen design byte hash mismatch')
    require(isinstance(payload['rows'], list) and len(payload['rows']) <= len(design['decision_grid']),
            'prediction rows exceed decision grid')
    grid = {row['decision_id']: row for row in design['decision_grid']}
    result = {}
    for row in payload['rows']:
        require(isinstance(row, dict) and set(row) == {'decision_id', 'issued_at', 'features_available_at',
            'hours_until_start', 'probability_onset_within_horizon'}, 'invalid decision fields')
        key = row['decision_id']
        require(isinstance(key, str) and key in grid and key not in result, 'unknown or duplicate decision')
        scheduled, issued, available = required_time(grid[key]['scheduled_at']), required_time(row['issued_at']), required_time(row['features_available_at'])
        require(issued >= scheduled, 'prediction issued before scheduled decision')
        require(available <= scheduled, 'feature availability exceeds scheduled decision')
        point, probability = row['hours_until_start'], row['probability_onset_within_horizon']
        if point is not None:
            number(point, 0, 8760)
        if probability is not None:
            number(probability, 0, 1)
            require(point is not None, 'probability supplied for abstained prediction')
        status = 'late' if (issued - scheduled).total_seconds() > plan['max_lateness_seconds'] \
            else ('abstained' if point is None else 'provided')
        result[key] = {**row, 'status': status}
    return result


def decision_summary(rows, name):
    known = [r for r in rows if r[name]['status'] == 'provided' and r['truth']['label'] is not None]
    negative = [r for r in known if r['truth']['label'] == 0]
    true = sum(r[name]['alarm'] and r['truth']['label'] == 1 for r in known)
    false = sum(r[name]['alarm'] for r in negative)
    return dict(scheduled=len(rows), scored_decisions=len(known),
        scored_fraction=len(known) / len(rows), known_negative_decisions=len(negative),
        true_alerts=true, false_alerts=false,
        false_alarm_fraction=false / len(negative) if negative else None,
        precision=true / (true + false) if true + false else None,
        unscored_alerts=sum(r[name]['alarm'] is True and r['truth']['label'] is None for r in rows),
        **{status: sum(r[name]['status'] == status for r in rows) for status in ('missing', 'late', 'abstained')})


def cycle_summary(rows, plan, datasets, windows, blocked):
    labels = required_time(plan['labels_as_of'])
    left, right = required_time(plan['evaluation_start']), required_time(plan['evaluation_end'])
    result = []
    for animal in plan['animals']:
        cycles = datasets[animal][1]
        for cycle in cycles:
            start = cycle['started_event']
            if cycle['role'] != plan['role'] or start['latest'] < left or start['earliest'] >= right:
                continue
            eligible = label_ready(cycle, labels) and left <= start['earliest'] <= start['latest'] < right
            animal_rows = [r for r in rows if r['animal_id'] == animal]
            opportunities = []
            for row in animal_rows:
                point = required_time(row['scheduled_at'])
                latest_issue = point + timedelta(seconds=plan['max_lateness_seconds'])
                truth = truth_at(point, cycles, windows[animal], blocked[animal], plan['horizon_hours'], labels)
                if truth['cycle_id'] == cycle['cycle_id'] and latest_issue < start['earliest'] \
                        and (start['earliest'] - latest_issue).total_seconds() / 3600 >= plan['minimum_lead_hours']:
                    opportunities.append(row['decision_id'])
            entry = dict(animal_id=animal, cycle_id=cycle['cycle_id'], eligible=eligible,
                covered=eligible and bool(opportunities), scheduled_opportunities=opportunities,
                exclusion_reason=None if eligible else 'label_pending_unresolved_or_onset_crosses_window')
            for name in ('candidate', 'baseline'):
                alarms = [required_time(r['effective_at']) for r in animal_rows
                    if r[name]['alarm'] is True and r['truth']['cycle_id'] == cycle['cycle_id']
                    and (start['earliest'] - required_time(r['effective_at'])).total_seconds() / 3600
                    >= plan['minimum_lead_hours']]
                # A cycle without a guaranteed scheduled opportunity is reported separately.
                detected = entry['covered'] and bool(alarms)
                entry[name + '_detected'] = detected
                entry[name + '_lead_hours'] = [(start[k] - min(alarms)).total_seconds() / 3600
                    for k in ('earliest', 'latest')] if detected else None
            result.append(entry)
    covered = [r for r in result if r['covered']]
    eligible = sum(r['eligible'] for r in result)
    return dict(rows=result, eligible_cycles=eligible, excluded_cycles=len(result) - eligible,
        covered_cycles=len(covered), uncovered_cycles=eligible - len(covered),
        covered_fraction=len(covered) / eligible if eligible else None,
        **{name + '_' + outcome: sum(r[name + '_detected'] == (outcome == 'detected') for r in covered)
           for name in ('candidate', 'baseline') for outcome in ('detected', 'missed')})


def probability_summary(rows):
    values = [(r['candidate']['probability'], r['truth']['label']) for r in rows
        if r['candidate']['status'] == 'provided' and r['candidate']['probability'] is not None
        and r['truth']['label'] is not None]
    bins = []
    for index in range(5):
        low, high = index / 5, (index + 1) / 5
        items = [(p, y) for p, y in values if low <= p < high or index == 4 and p == 1]
        bins.append(dict(lower=low, upper=high, count=len(items),
            mean_probability=mean(p for p, _ in items) if items else None,
            observed_fraction=mean(y for _, y in items) if items else None))
    return dict(count=len(values), brier_score=mean((p - y)**2 for p, y in values) if values else None,
                bins=bins, calibration_established=False)


def daily_summary(rows):
    groups = {}
    for row in rows:
        # Group by the declared schedule, retaining missing and late decisions in their day.
        day = required_time(row['scheduled_at']).astimezone(timezone.utc).date().isoformat()
        groups.setdefault((row['animal_id'], day), []).append(row)
    return [dict(animal_id=animal, scheduled_utc_date=day,
                 candidate=decision_summary(items, 'candidate'), baseline=decision_summary(items, 'baseline'))
            for (animal, day), items in sorted(groups.items())]


def evaluate_alarms(plan_path, design_path, predictions_path):
    frozen = read_json(Path(design_path), limit=COHORT_LIMIT)
    design, plan, datasets, windows, blocked = build_design(plan_path)
    require(without_created(frozen) == without_created(design), 'frozen design or source inputs changed')
    predictions = load_predictions(predictions_path, design_path, design, plan)
    rows = []
    for slot in design['decision_grid']:
        prediction = predictions.get(slot['decision_id'])
        status = prediction['status'] if prediction else 'missing'
        scheduled = required_time(slot['scheduled_at'])
        point = required_time(prediction['issued_at']) if status in ('provided', 'abstained') else scheduled
        truth = truth_at(point, datasets[slot['animal_id']][1], windows[slot['animal_id']],
                         blocked[slot['animal_id']], plan['horizon_hours'], required_time(plan['labels_as_of']))
        candidate_point = prediction['hours_until_start'] if status == 'provided' else None
        baseline = slot['baseline']
        baseline_point = max(0., baseline['hours_until_start'] - (point - scheduled).total_seconds() / 3600) if baseline else None
        rows.append(dict(decision_id=slot['decision_id'], animal_id=slot['animal_id'],
            scheduled_at=slot['scheduled_at'], effective_at=point.isoformat(),
            recorded_issue_at=prediction['issued_at'] if prediction else None, truth=truth,
            candidate=dict(status=status, hours_until_start=candidate_point,
                alarm=candidate_point <= plan['horizon_hours'] if candidate_point is not None else None,
                probability=prediction['probability_onset_within_horizon'] if status == 'provided' else None),
            baseline=dict(status='provided' if baseline_point is not None else 'abstained',
                hours_until_start=baseline_point,
                alarm=baseline_point <= plan['horizon_hours'] if baseline_point is not None else None)))
    paired = [r for r in rows if r['truth']['label'] is not None
              and r['candidate']['status'] == r['baseline']['status'] == 'provided']
    result = dict(schema_version=1, kind='appearance_alarm_evaluation', created_at=now(),
        plan_sha256=fingerprint(plan), design_sha256=hashlib.sha256(Path(design_path).read_bytes()).hexdigest(),
        predictions_sha256=hashlib.sha256(Path(predictions_path).read_bytes()).hexdigest(),
        model_id=plan['model_id'], dataset_kind=plan['dataset_kind'], role=plan['role'], rows=rows,
        candidate=decision_summary(rows, 'candidate'), baseline=decision_summary(rows, 'baseline'),
        paired=dict(count=len(paired), candidate_correct=sum(r['candidate']['alarm'] == bool(r['truth']['label']) for r in paired),
                    baseline_correct=sum(r['baseline']['alarm'] == bool(r['truth']['label']) for r in paired)),
        cycles=cycle_summary(rows, plan, datasets, windows, blocked), probabilities=probability_summary(rows),
        per_animal_day=daily_summary(rows),
        actual_model_fit=False, biological_validation_complete=False, comparison_criteria_passed=False,
        model_identity_verified=False, actuation_allowed=False,
        limitations=['Retrospective supplied decisions; model IDs, event reviews, clocks and feature availability are declarations, not execution attestations.',
            'Point hours are relative to issued_at; no probability is derived from point output.',
            'Adjacent decisions are dependent. Fractions and Brier score are descriptive; no confidence intervals or biological sufficiency claimed.',
            'Coverage, abstentions, late/missing slots and unreviewed periods must accompany every error metric.',
            'This retrospective audit alone does not attest live execution. Local runner receipts remain separate evidence; no automatic acceptance or physical actuation.'])
    require(len(encode(result)) <= COHORT_LIMIT, 'report exceeds output limit')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'evaluate'))
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--design')
    parser.add_argument('--predictions')
    parser.add_argument('--execution-host', required=True)
    args = parser.parse_args(argv)
    try:
        require(not Path(args.output).exists(), 'output already exists')
        from .appearance_predictor import native_preflight
        snapshot, guard = native_preflight({'execution_host': args.execution_host})
        print(encode({'preflight': snapshot}).decode(), end='', flush=True)
        if args.action == 'freeze':
            result, _, _, _, _ = build_design(args.plan)
        else:
            require(args.design and args.predictions, 'design and predictions required')
            result = evaluate_alarms(args.plan, args.design, args.predictions)
        guard()
        save_artifact(args.output, result)
        print(encode({'output': args.output, 'kind': result['kind']}).decode(), end='')
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
