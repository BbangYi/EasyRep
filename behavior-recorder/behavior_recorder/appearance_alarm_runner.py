"""Bounded, one-shot scheduled forecasts. No daemon, notifications or physical control."""
import argparse
from datetime import timedelta
import hashlib
from pathlib import Path
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance_evaluation import COHORT_LIMIT, load_inputs, required_time, without_created
from .appearance_predictor import forecast, load_plan, native_preflight, verify_run
from .core import RecorderError, digest, encode, identifier, now, number, read_json, relative, require

LIMIT = 2 * 1024**2
POLICY = ('animals', 'role', 'evaluation_start', 'evaluation_end', 'cadence_hours',
          'horizon_hours', 'minimum_lead_hours', 'max_lateness_seconds')


def slot_name(decision_id):
    return hashlib.sha256(decision_id.encode()).hexdigest()


def series_roots(bindings, root):
    result = {}
    for binding in bindings:
        temporal_path = relative(root, binding['plan'])
        temporal = read_json(temporal_path, limit=64 * 1024)
        series = relative(temporal_path.parent, temporal['series'])
        manifest = read_json(series, limit=64 * 1024)
        require(manifest['animal_id'] not in result, 'one series per animal required')
        result[manifest['animal_id']] = series.parent
    return result


def training_images(fit_plan):
    _, cohort, path = load_plan(fit_plan)
    roots = series_roots(cohort['timelines'], path.parent)
    images, total = set(), 0
    # All declared training rows remain protected, including rows omitted by the fit gate.
    for row in cohort['training_rows']:
        artifact_path = relative(roots[row['animal_id']], row['artifact'])
        total += artifact_path.stat().st_size
        require(total <= 16 * 1024**2, 'training source metadata exceeds 16 MiB')
        artifact = read_json(artifact_path, limit=64 * 1024)
        require(digest(artifact_path) == row['artifact_sha256'], 'training source artifact changed')
        images.add(artifact['files']['image']['sha256'])
    return sorted(images)


def observation_image(inputs, root, animal, row):
    path = relative(series_roots(inputs['timelines'], root)[animal], row['artifact'])
    artifact = read_json(path, limit=64 * 1024)
    require(digest(path) == row['artifact_sha256'], 'observation artifact changed')
    return artifact['files']['image']['sha256']


def load_schedule(plan_path, created_at):
    path = Path(plan_path)
    plan = read_json(path, limit=64 * 1024)
    require(isinstance(plan, dict) and set(plan) == {'schema_version', 'kind', 'fit_plan', 'fit_run',
        'journal', 'max_observation_age_hours', *POLICY}, 'invalid runner plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_alarm_runner_plan', 'unsupported runner plan')
    require(isinstance(plan['animals'], list) and 1 <= len(plan['animals']) <= 16,
            'one to sixteen animals required')
    for animal in plan['animals']:
        identifier(animal)
    require(len(set(plan['animals'])) == len(plan['animals']), 'duplicate animal')
    require(plan['role'] in ('validation', 'test'), 'one separate evaluation role required')
    cadence = number(plan['cadence_hours'], .001, 8760)
    horizon = number(plan['horizon_hours'], .001, 8760)
    require(number(plan['minimum_lead_hours'], 0, 8760) < horizon, 'lead must be below horizon')
    number(plan['max_lateness_seconds'], 0, min(3600, cadence * 3600))
    number(plan['max_observation_age_hours'], .001, 8760)
    relative(path.parent, plan['journal'])
    fit_plan, fit_root = relative(path.parent, plan['fit_plan']), relative(path.parent, plan['fit_run'])
    # Bound existing run receipt reads before the shared verifier hashes them.
    for name in ('model.json', 'predictions.json', 'forecast-review.json', 'started.json', 'run.json'):
        require((fit_root / name).stat().st_size <= COHORT_LIMIT, 'fit artifact exceeds limit')
    run = verify_run(fit_plan, fit_root)
    model = read_json(fit_root / 'model.json', limit=COHORT_LIMIT)
    start, end, frozen, trained, fit = [required_time(value) for value in (
        plan['evaluation_start'], plan['evaluation_end'], created_at,
        run['created_at'], model['training']['fit_cutoff'])]
    require(fit <= trained <= frozen < start < end, 'fit completion, freeze and schedule must be ordered')
    train_animals = {row['animal_id'] for row in model['training']['used']}
    require(set(plan['animals']) <= train_animals if model['training']['mode'] == 'future_cycle'
            else not set(plan['animals']) & train_animals, 'schedule animal training-role mismatch')
    grid = []
    require((end - start).total_seconds() / (cadence * 3600) * len(plan['animals']) <= 8192,
            'schedule exceeds bounded grid')
    for animal in plan['animals']:
        point, index = start, 0
        while point < end:
            require(len(grid) < 8192, 'schedule exceeds bounded grid')
            grid.append(dict(decision_id=f'{animal}:{index}', animal_id=animal, scheduled_at=point.isoformat()))
            index += 1
            point = start + timedelta(hours=index * cadence)
    result = dict(schema_version=1, kind='appearance_frozen_forecast_schedule', created_at=created_at,
        plan_sha256=digest(path), fit_run_sha256=digest(fit_root / 'run.json'),
        model_sha256=digest(fit_root / 'model.json'), model_id=model['model_id'],
        dataset_kind=model['dataset_kind'], feature_version=model['feature_version'],
        mode=model['training']['mode'], fit_cutoff=model['training']['fit_cutoff'],
        training_completed_at=run['created_at'], policy={key: plan[key] for key in POLICY},
        training_image_sha256=training_images(fit_plan),
        max_observation_age_hours=plan['max_observation_age_hours'], decision_grid=grid,
        runner_sha256=digest(Path(__file__)), actuation_allowed=False,
        evidence='Local hashes and host-clock receipts; not independent clock, identity or biological attestation.')
    require(len(encode(result)) <= LIMIT, 'schedule exceeds size limit')
    return result, plan, model


def freeze_schedule(plan_path, schedule_path):
    require(not Path(schedule_path).exists(), 'schedule already exists')
    schedule, _, _ = load_schedule(plan_path, now())
    completed_at = now()
    require(required_time(schedule['created_at']) <= required_time(completed_at)
            < required_time(schedule['policy']['evaluation_start']),
            'schedule freeze completed too late or host clock moved backwards')
    schedule['created_at'] = completed_at
    save_artifact(schedule_path, schedule)
    return schedule


def verified_schedule(plan_path, schedule_path):
    frozen = read_json(Path(schedule_path), limit=LIMIT)
    expected, plan, model = load_schedule(plan_path, frozen['created_at'])
    require(frozen == expected, 'schedule/model/code binding changed')
    return frozen, plan, model


def select_row(dataset, scheduled, plan):
    eligible = [row for row in dataset['rows'] if required_time(row['as_of']) <= scheduled]
    if not eligible:
        return None, ['no_available_observation']
    latest = max(required_time(row['observed_at']) for row in eligible)
    rows = [row for row in eligible if required_time(row['observed_at']) == latest]
    if len(rows) != 1:
        return None, ['ambiguous_latest_observation']
    row, reasons = rows[0], []
    if row['features'] is None:
        reasons.append('latest_observation_unusable')
    if row['role'] not in (None, plan['role']):
        reasons.append('observation_role_mismatch')
    if (scheduled - latest).total_seconds() / 3600 > plan['max_observation_age_hours']:
        reasons.append('stale_observation')
    return row, reasons


def available_events(inputs, root, datasets, animal, scheduled, guard):
    result, total = [], 0
    for binding in inputs['timelines']:
        temporal_path = relative(root, binding['plan'])
        temporal = read_json(temporal_path, limit=64 * 1024)
        series = relative(temporal_path.parent, temporal['series'])
        manifest = read_json(series, limit=64 * 1024)
        if manifest['animal_id'] != animal:
            continue
        for record in datasets[animal][0]['source_records']:
            if record['kind'] != 'shedding_event':
                continue
            guard()
            path = relative(series.parent, record['artifact'])
            total += path.stat().st_size
            require(total <= 8 * 1024**2, 'event metadata exceeds 8 MiB')
            artifact = read_json(path, limit=64 * 1024)
            require(digest(path) == record['artifact_sha256'], 'event artifact changed')
            available = max(required_time(artifact['created_at']), required_time(record['latest_at']))
            if available <= scheduled:
                result.append(dict(record_id=record['record_id'], stage=record['stage'],
                    latest_at=record['latest_at'], available_at=available.isoformat(), sha256=record['artifact_sha256']))
    return result


def issue_slot(plan_path, schedule_path, inputs_path, decision_id, execution_host):
    schedule, plan, model = verified_schedule(plan_path, schedule_path)
    slots = {row['decision_id']: row for row in schedule['decision_grid']}
    require(decision_id in slots, 'unknown scheduled decision')
    slot = slots[decision_id]
    scheduled = required_time(slot['scheduled_at'])
    snapshot, guard = native_preflight({'execution_host': execution_host})
    started_at = now()
    require(required_time(started_at) >= scheduled, 'scheduled decision is not due')
    journal = relative(Path(plan_path).parent, plan['journal'])
    folder = journal / slot_name(decision_id)
    require(not folder.exists(), 'slot already attempted; inspect existing receipts, never automatically retry')
    # Atomic directory creation is the per-slot lock, including failed/partial attempts.
    journal.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    save_artifact(folder / 'started.json', dict(at=started_at, decision_id=decision_id,
        schedule_sha256=digest(Path(schedule_path)), preflight=snapshot))
    try:
        reasons, selected, raw, audit, events = [], None, None, None, []
        available_at = slot['scheduled_at']  # No feature used for an abstained no-input/late slot.
        late = (required_time(started_at) - scheduled).total_seconds() > plan['max_lateness_seconds']
        if late:
            reasons.append('late_execution')
        else:
            inputs_path = Path(inputs_path)
            inputs = read_json(inputs_path, limit=64 * 1024)
            require(isinstance(inputs, dict) and set(inputs) == {'timelines'}
                and isinstance(inputs['timelines'], list) and 1 <= len(inputs['timelines']) <= 16,
                'bounded timeline input manifest required')
            save_artifact(folder / 'input-manifest.json', inputs)
            datasets = load_inputs({**inputs, 'feature_version': schedule['feature_version'],
                                    'dataset_kind': schedule['dataset_kind']}, inputs_path.parent)
            require(slot['animal_id'] in datasets, 'scheduled animal missing from inputs')
            dataset = datasets[slot['animal_id']][0]
            require(dataset['identity']['dataset_kind'] == schedule['dataset_kind']
                    and dataset['feature_version'] == schedule['feature_version'], 'input dataset/feature version mismatch')
            row, reasons = select_row(dataset, scheduled, plan)
            events = available_events(inputs, inputs_path.parent, datasets, slot['animal_id'], scheduled, guard)
            if row is not None:
                selected = {key: value for key, value in row.items() if key not in ('target', 'reasons')}
                selected['animal_id'] = slot['animal_id']
                available_at = row['as_of']
                if observation_image(inputs, inputs_path.parent, slot['animal_id'], row) \
                        in schedule['training_image_sha256']:
                    reasons.append('training_image_reuse')
                if required_time(row['as_of']) <= required_time(schedule['fit_cutoff']):
                    reasons.append('observation_before_fit_cutoff')
                completions = [e for e in events if e['stage'] == 'completed']
                completed = max((required_time(e['latest_at']) for e in completions), default=None)
                if any(e['stage'] in ('started', 'uncertain') and (completed is None
                       or required_time(e['latest_at']) >= completed) for e in events):
                    reasons.append('known_active_or_uncertain_shed')
                if any(e['stage'] == 'completed' and required_time(e['available_at']) > required_time(row['as_of'])
                       for e in events):
                    reasons.append('completion_after_observation')
                if not reasons:
                    predictions, reviews = forecast(model, [selected], guard)
                    raw, audit = predictions[0], reviews[0]
                    reasons.extend(audit.get('reasons', []))
            save_artifact(folder / 'feature.json', dict(row=selected, known_events=events,
                no_future_targets_passed=True, no_raw_media_reverification=True))
        guard()
        issued_at = now()  # Actual completion clock, never the scheduled or observation clock.
        issued = required_time(issued_at)
        require(issued >= required_time(started_at), 'host clock moved backwards')
        if (issued - scheduled).total_seconds() > plan['max_lateness_seconds']:
            reasons.append('late_execution')
        if selected and (issued - required_time(selected['observed_at'])).total_seconds() / 3600 \
                > plan['max_observation_age_hours']:
            reasons.append('stale_observation')
        point = None
        if raw and raw['hours_until_start'] is not None and not reasons:
            point = raw['hours_until_start'] - (issued - required_time(available_at)).total_seconds() / 3600
            if point <= 0:
                reasons.append('estimate_expired')
                point = None
        prediction = dict(decision_id=decision_id, issued_at=issued_at, features_available_at=available_at,
            hours_until_start=point, probability_onset_within_horizon=None)
        save_artifact(folder / 'prediction.json', prediction)
        files = {p.name: digest(p) for p in folder.iterdir() if p.is_file()}
        receipt = dict(schema_version=1, kind='appearance_alarm_issue_receipt', decision_id=decision_id,
            schedule_sha256=digest(Path(schedule_path)), model_id=model['model_id'],
            dataset_kind=schedule['dataset_kind'], started_at=started_at, issued_at=issued_at,
            status='late' if 'late_execution' in reasons else 'provided' if point is not None else 'abstained',
            reasons=sorted(set(reasons)), prediction=prediction, forecast_at_observation=raw, forecast_audit=audit,
            files=files, actual_model_fit=False, biological_validation_complete=False,
            actual_model_inference=raw is not None,
            declared_real_input_inference=schedule['dataset_kind'] == 'real' and raw is not None,
            actuation_allowed=False,
            evidence='Actual local issue invocation and file integrity, not independent execution/clock attestation or biological validation.')
        save_artifact(folder / 'receipt.json', receipt)
        return receipt
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        save_artifact(folder / 'failure.json', dict(error=type(exc).__name__, message=str(exc),
            automatic_retry=False, completion_unknown=True))
        raise


def export_predictions(plan_path, schedule_path, evaluation_path, design_path, output_path):
    from .appearance_alarm_evaluation import build_design, load_predictions
    output = Path(output_path)
    require(not output.exists(), 'output already exists')
    schedule, plan, _ = verified_schedule(plan_path, schedule_path)
    design, evaluation, _, _, _ = build_design(evaluation_path)
    frozen = read_json(Path(design_path), limit=COHORT_LIMIT)
    require(without_created(frozen) == without_created(design), 'evaluation design/source binding changed')
    require(all(evaluation[key] == plan[key] for key in POLICY), 'evaluation policy differs from frozen schedule')
    require(all(evaluation[key] == schedule[key] for key in ('model_id', 'dataset_kind', 'feature_version',
                'mode', 'fit_cutoff', 'training_completed_at')), 'evaluation model/training mismatch')
    require([{key: row[key] for key in ('decision_id', 'animal_id', 'scheduled_at')}
             for row in design['decision_grid']] == schedule['decision_grid'], 'evaluation grid differs')
    journal = relative(Path(plan_path).parent, plan['journal'])
    allowed = {slot_name(slot['decision_id']) for slot in schedule['decision_grid']}
    if journal.exists():
        require(all(p.name in allowed and p.is_dir() and not p.is_symlink() for p in journal.iterdir()),
                'unexpected journal entry')
    rows, receipts, partial = [], {}, []
    for slot in schedule['decision_grid']:
        folder = journal / slot_name(slot['decision_id'])
        if not (folder / 'receipt.json').exists():
            if folder.exists():
                partial.append(slot['decision_id'])
            continue
        receipt = read_json(folder / 'receipt.json', limit=LIMIT)
        require(receipt['schedule_sha256'] == digest(Path(schedule_path))
                and receipt['model_id'] == schedule['model_id'] and receipt['decision_id'] == slot['decision_id'],
                'receipt schedule/model mismatch')
        require({'started.json', 'prediction.json'} <= set(receipt['files'])
                <= {'started.json', 'prediction.json', 'feature.json', 'input-manifest.json'}, 'invalid receipt files')
        require(all(relative(folder, name).stat().st_size <= LIMIT and digest(relative(folder, name)) == value
                    for name, value in receipt['files'].items()), 'receipt file hash mismatch')
        prediction = read_json(folder / 'prediction.json', limit=LIMIT)
        started = read_json(folder / 'started.json', limit=LIMIT)
        require(prediction == receipt['prediction'] and prediction['issued_at'] == receipt['issued_at'],
                'receipt prediction mismatch')
        require(started['decision_id'] == slot['decision_id'] and started['at'] == receipt['started_at']
                and started['schedule_sha256'] == receipt['schedule_sha256'], 'receipt start binding mismatch')
        require(required_time(receipt['issued_at']) >= required_time(receipt['started_at'])
                >= required_time(slot['scheduled_at']), 'receipt clock order mismatch')
        late = (required_time(receipt['issued_at']) - required_time(slot['scheduled_at'])).total_seconds() \
            > plan['max_lateness_seconds']
        expected_status = 'late' if late else 'abstained' if prediction['hours_until_start'] is None else 'provided'
        require(receipt['status'] == expected_status and prediction['probability_onset_within_horizon'] is None,
                'receipt status/probability mismatch')
        if prediction['hours_until_start'] is not None:
            require(not late and not receipt['reasons'] and 'feature.json' in receipt['files'],
                    'late or excluded receipt cannot supply a prediction')
            feature = read_json(folder / 'feature.json', limit=LIMIT)['row']
            require(feature is not None and 'target' not in feature
                    and receipt['forecast_audit']['feature_row_sha256'] == fingerprint(feature),
                    'receipt feature fingerprint mismatch')
        rows.append(prediction)
        receipts[slot['decision_id']] = digest(folder / 'receipt.json')
    payload = dict(schema_version=1, kind='appearance_alarm_predictions', dataset_kind=schedule['dataset_kind'],
        model_id=schedule['model_id'], design_sha256=digest(Path(design_path)), rows=rows)
    require(len(encode(payload)) <= COHORT_LIMIT, 'prediction export exceeds limit')
    output.mkdir(parents=True, exist_ok=False)
    save_artifact(output / 'predictions.json', payload)
    load_predictions(output / 'predictions.json', design_path, design, evaluation)
    evidence = dict(kind='appearance_alarm_export_review', schedule_sha256=digest(Path(schedule_path)),
        predictions_sha256=digest(output / 'predictions.json'), receipt_sha256=receipts,
        partial_slots=partial, scheduled=len(schedule['decision_grid']), recorded=len(rows),
        missing=len(schedule['decision_grid']) - len(rows), local_integrity_checked=True,
        independent_execution_attestation=False, biological_validation_complete=False, actuation_allowed=False,
        note='The existing evaluator remains a retrospective audit. This sidecar preserves local issue provenance; no biological promotion.')
    save_artifact(output / 'execution-evidence.json', evidence)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'issue', 'export'))
    for name in ('plan', 'schedule', 'execution-host'):
        parser.add_argument('--' + name, required=True)
    for name in ('inputs', 'decision', 'evaluation-plan', 'design', 'output'):
        parser.add_argument('--' + name)
    args = parser.parse_args(argv)
    try:
        if args.action == 'issue':
            require(args.inputs and args.decision, 'input manifest and decision required')
            result = issue_slot(args.plan, args.schedule, args.inputs, args.decision, args.execution_host)
        else:
            snapshot, guard = native_preflight({'execution_host': args.execution_host})
            print(encode({'preflight': snapshot}).decode(), end='', flush=True)
            if args.action == 'freeze':
                result = freeze_schedule(args.plan, args.schedule)
            else:
                require(args.evaluation_plan and args.design and args.output, 'evaluation plan/design/output required')
                result = export_predictions(args.plan, args.schedule, args.evaluation_plan, args.design, args.output)
            guard()
        print(encode({'kind': result['kind'], 'actuation_allowed': False}).decode(), end='')
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
