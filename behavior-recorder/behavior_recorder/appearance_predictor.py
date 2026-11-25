"""Bounded colour/elapsed-time ridge baseline; biological use needs reviewed real data."""
import argparse
from collections import Counter
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from .analysis_features import fingerprint, save_artifact
from .appearance_evaluation import COHORT_LIMIT, FEATURE_VERSION, FEATURE_VERSIONS, evaluate_predictions, required_time
from .appearance_texture_timeline import TEXTURE_FEATURES, TEXTURE_VERSIONS
from .core import RecorderError, digest, encode, identifier, now, number, read_json, relative, require

ALGORITHM = 'cycle-weighted-ridge-v1'
FEATURES = ('elapsed_hours', 'red_delta', 'green_delta', 'blue_delta', 'saturation_delta',
            'value_delta', 'red_rate', 'green_rate', 'blue_rate', 'history_hours',
            'temperature_c', 'humidity_percent', 'activity_fraction', 'behaviour_coverage') + TEXTURE_FEATURES
SETTING_KEYS = ('features', 'regularization', 'max_target_interval_hours', 'minimum_train_rows',
                'max_abs_z', 'max_prediction_hours', 'seed')


def validate_settings(settings):
    require(isinstance(settings, dict) and set(settings) == {
        'schema_version', 'kind', 'experiment_id', 'cohort', 'cohort_sha256', 'algorithm',
        *SETTING_KEYS, 'execution_host', 'observer', 'evidence_reference'}, 'invalid fit plan fields')
    require(type(settings['schema_version']) is int and settings['schema_version'] == 1
            and settings['kind'] == 'appearance_fit_plan' and settings['algorithm'] == ALGORITHM,
            'unsupported fitting algorithm or plan')
    identifier(settings['experiment_id'])
    identifier(settings['execution_host'])
    identifier(settings['observer'])
    require(isinstance(settings['evidence_reference'], str)
            and 0 < len(settings['evidence_reference'].strip()) <= 1024, 'fixed fitting rationale required')
    names = settings['features']
    require(isinstance(names, list) and 2 <= len(names) <= len(FEATURES)
            and all(isinstance(name, str) and name in FEATURES for name in names)
            and len(set(names)) == len(names) and 'elapsed_hours' in names
            and any(name not in ('elapsed_hours', 'history_hours') for name in names),
            'declare elapsed time and at least one supported colour/context/texture feature without duplicates')
    number(settings['regularization'], 1e-6, 1e6)
    number(settings['max_target_interval_hours'], 0, 8760)
    number(settings['max_abs_z'], 1, 100)
    number(settings['max_prediction_hours'], 1e-6, 8760)
    require(type(settings['minimum_train_rows']) is int and 1 <= settings['minimum_train_rows'] <= 8192,
            'declare minimum training rows')
    require(settings['seed'] is None, 'closed-form deterministic solver uses no random seed')


def validate_mode(cohort, software_test):
    require(type(software_test) is bool, 'software test mode must be explicit')
    require(isinstance(cohort, dict) and type(cohort['schema_version']) is int
            and cohort['schema_version'] == 1 and cohort['kind'] == 'appearance_frozen_cohort'
            and cohort['feature_version'] in FEATURE_VERSIONS, 'unsupported frozen cohort')
    require(cohort['mode'] in ('future_cycle', 'held_out_animal'), 'invalid evaluation mode')
    require(cohort['actuation_allowed'] is False and cohort['biological_validation_complete'] is False,
            'only unpromoted frozen cohorts are accepted')
    if software_test:
        require(cohort['dataset_kind'] == 'test', 'software mode requires test data only')
    else:
        require(cohort['dataset_kind'] == 'real', 'synthetic data cannot be used for biological fitting')
        require(cohort['model_fitting_allowed'] is True and cohort['gate_reasons'] == [],
                'real cohort fitting gates have not passed')
    for key in ('train_cycles', 'train_animals', 'evaluation_cycles', 'evaluation_animals'):
        require(type(cohort['minimums'][key]) is int and cohort['minimums'][key] > 0, 'invalid sample minimum')
    for key in ('evaluation_cycles', 'evaluation_animals'):
        require(type(cohort['counts'][key]) is int and cohort['counts'][key] >= cohort['minimums'][key],
                'confirmed evaluation sample gate not met')


def feature_vector(features, names):
    if features is None:
        return None, ['excluded_colour_observation']
    require(isinstance(features, dict), 'invalid feature object')
    values, reasons = [], []
    for name in names:
        if name == 'elapsed_hours':
            pair = features.get('hours_since_previous_completion')
            if pair is None:
                value = None
            else:
                require(isinstance(pair, list) and len(pair) == 2, 'invalid elapsed-time interval')
                for item in pair:
                    number(item, 0, 8760)
                require(pair[0] <= pair[1], 'reversed elapsed-time interval')
                value = math.fsum(pair) / 2
        elif name in ('red_delta', 'green_delta', 'blue_delta', 'red_rate', 'green_rate', 'blue_rate'):
            raw = features.get('rgb_delta' if name.endswith('delta') else 'rgb_change_per_hour')
            if raw is None:
                value = None
            else:
                require(isinstance(raw, list) and len(raw) == 3, 'invalid RGB change vector')
                bound = 255 if name.endswith('delta') else 1e6
                for item in raw:
                    number(item, -bound, bound)
                value = raw[('red', 'green', 'blue').index(name.split('_')[0])]
        elif name in ('temperature_c', 'humidity_percent', 'activity_fraction', 'behaviour_coverage'):
            value = features.get(name)
            if value is not None:
                bounds = {'temperature_c': (-100, 150), 'humidity_percent': (0, 100),
                          'activity_fraction': (0, 1), 'behaviour_coverage': (0, 1)}
                number(value, *bounds[name])
        elif name in TEXTURE_FEATURES:
            value = features.get(name)
            if value is not None:
                if name.endswith('_rate'):
                    number(value, -1e6, 1e6)
                elif name.endswith('_delta'):
                    number(value, -1, 1)
                else:
                    number(value, 0, 8760 if name.endswith('_hours') else 1)
        else:
            value = features.get(name)
            if value is not None:
                number(value, 0 if name == 'history_hours' else -1,
                       8760 if name == 'history_hours' else 1)
        if value is None:
            reasons.append('missing_' + name)
        values.append(value)
    return (None if reasons else values), reasons


def no_op():
    pass


def ridge_fit(matrix, targets, weights, regularization, guard=no_op):
    """Minimize weighted mean squared error plus lambda*||beta||^2; free intercept."""
    number(regularization, 1e-6, 1e6)
    require(1 <= len(matrix) <= 8192 and len(matrix) == len(targets) == len(weights), 'invalid training matrix size')
    width = len(matrix[0])
    require(1 <= width <= len(FEATURES), 'invalid feature width')
    for row, target, weight in zip(matrix, targets, weights):
        require(len(row) == width, 'ragged training matrix')
        for value in row:
            number(value, -1e6, 1e6)
        number(target, 0, 8760)
        number(weight, 1e-12, 1)
    total = math.fsum(weights)
    weights = [weight / total for weight in weights]
    means = [math.fsum(weight * row[col] for row, weight in zip(matrix, weights)) for col in range(width)]
    variance = [math.fsum(weight * (row[col] - means[col])**2 for row, weight in zip(matrix, weights))
                for col in range(width)]
    constant = [value <= 1e-24 for value in variance]
    scales = [1. if fixed else math.sqrt(value) for fixed, value in zip(constant, variance)]
    standardized = [[0. if constant[col] else (row[col] - means[col]) / scales[col]
                     for col in range(width)] for row in matrix]
    intercept = math.fsum(weight * value for weight, value in zip(weights, targets))
    normal = [[0.] * width for _ in range(width)]
    rhs = [0.] * width
    for col in range(width):
        guard()
        rhs[col] = math.fsum(weight * row[col] * (target - intercept)
                            for row, target, weight in zip(standardized, targets, weights))
        for other in range(width):
            normal[col][other] = math.fsum(weight * row[col] * row[other]
                                           for row, weight in zip(standardized, weights))
        normal[col][col] += regularization
    # Positive regularization makes this small symmetric system positive definite.
    lower = [[0.] * width for _ in range(width)]
    for i in range(width):
        for j in range(i + 1):
            value = normal[i][j] - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                require(math.isfinite(value) and value > 0, 'ridge system is not positive definite')
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    forward = [0.] * width
    for i in range(width):
        forward[i] = (rhs[i] - math.fsum(lower[i][j] * forward[j] for j in range(i))) / lower[i][i]
    coefficients = [0.] * width
    for i in reversed(range(width)):
        coefficients[i] = (forward[i] - math.fsum(lower[j][i] * coefficients[j] for j in range(i + 1, width))) / lower[i][i]
    guard()
    return dict(means=means, scales=scales, constant=constant, coefficients=coefficients, intercept=intercept)


def code_hashes():
    root = Path(__file__).parent
    return {name: digest(root / name) for name in (
        'appearance_predictor.py', 'appearance_evaluation.py', 'appearance_timeline.py',
        'appearance_context.py', 'appearance_texture_timeline.py', 'appearance_texture.py',
        'appearance.py', 'analysis_features.py', 'core.py')}


def model_fingerprint(model):
    return fingerprint({key: model[key] for key in (
        'algorithm', 'feature_version', 'dataset_kind', 'features', 'settings', 'parameters', 'training', 'code_sha256')})


def train_artifact(cohort, settings, software_test=False, guard=no_op):
    validate_settings(settings)
    validate_mode(cohort, software_test)
    require(cohort['experiment_id'] == settings['experiment_id'], 'experiment mismatch')
    if cohort['feature_version'] not in ('past-only-reviewed-srgb-context-v1', 'past-only-reviewed-srgb-context-texture-v1'):
        require(not set(settings['features']) & {'temperature_c', 'humidity_percent', 'activity_fraction', 'behaviour_coverage'},
                'context features require a context-bound cohort')
    if cohort['feature_version'] not in TEXTURE_VERSIONS:
        require(not set(settings['features']) & set(TEXTURE_FEATURES), 'texture features require a texture-bound cohort')
    rows = cohort['training_rows']
    require(isinstance(rows, list) and 1 <= len(rows) <= 8192, 'bounded nonempty training rows required')
    fit_cutoff = required_time(cohort['fit_cutoff'])
    selected, excluded, seen = [], [], set()
    for index, row in enumerate(rows):
        if index % 256 == 0:
            guard()
        key = (identifier(row['animal_id']), identifier(row['record_id']))
        require(key not in seen, 'duplicate training record')
        seen.add(key)
        identifier(row['cycle_id'])
        require(row['role'] == 'train' and row['reasons'] == [], 'only eligible train-role rows may be fitted')
        as_of = required_time(row['as_of'])
        require(required_time(row['observed_at']) <= as_of <= fit_cutoff, 'training feature after fit cutoff')
        target = row['target']
        require(isinstance(target, dict) and target['kind'] == 'interval_until_confirmed_start', 'confirmed interval target required')
        bounds = target['hours_until_start']
        require(isinstance(bounds, list) and len(bounds) == 2, 'invalid target interval')
        for value in bounds:
            number(value, 0, 8760)
        require(bounds[0] <= bounds[1], 'reversed target interval')
        require(as_of + timedelta(hours=bounds[1]) <= required_time(target['available_at']) <= fit_cutoff,
                'training label unavailable at fit cutoff or before confirmed start')
        vector, reasons = feature_vector(row['features'], settings['features'])
        if bounds[1] - bounds[0] > settings['max_target_interval_hours']:
            reasons.append('target_interval_too_wide')
        if reasons:
            excluded.append(dict(animal_id=key[0], record_id=key[1], cycle_id=row['cycle_id'], reasons=reasons))
        else:
            selected.append((row, vector, math.fsum(bounds) / 2))
    require(len(selected) >= settings['minimum_train_rows'], 'insufficient eligible training rows')
    counts = Counter((row['animal_id'], row['cycle_id']) for row, _, _ in selected)
    animals = {animal for animal, _ in counts}
    require(len(counts) >= cohort['minimums']['train_cycles'], 'insufficient eligible training cycles')
    require(len(animals) >= cohort['minimums']['train_animals'], 'insufficient eligible training animals')
    weights = [1. / (len(counts) * counts[(row['animal_id'], row['cycle_id'])]) for row, _, _ in selected]
    parameters = ridge_fit([vector for _, vector, _ in selected], [target for _, _, target in selected],
                           weights, settings['regularization'], guard)
    used = [dict(animal_id=row['animal_id'], record_id=row['record_id'], cycle_id=row['cycle_id'],
                 weight=weight, row_sha256=fingerprint(row)) for (row, _, _), weight in zip(selected, weights)]
    model = dict(schema_version=1, kind='appearance_ridge_model', created_at=now(), algorithm=ALGORITHM,
        feature_version=cohort['feature_version'], dataset_kind=cohort['dataset_kind'],
        status='software_test_only' if software_test else 'fitted_real_reviewed_data',
        actual_biological_fit=not software_test, biological_validation_complete=False, actuation_allowed=False,
        features=settings['features'], settings={key: settings[key] for key in SETTING_KEYS}, parameters=parameters,
        training=dict(row_count=len(selected), cycle_count=len(counts), animal_count=len(animals),
                      source_sha256=fingerprint(rows), fit_cutoff=cohort['fit_cutoff'],
                      mode=cohort['mode'], used=used, excluded=excluded),
        code_sha256=code_hashes(), cohort_sha256=settings['cohort_sha256'],
        randomness=dict(seed=None, used=False),
        evidence='Fixed, cycle-balanced weighted ridge with train-only centering/scaling; interval midpoint targets '
                 'are an explicit approximation, not exact biological onset times. No feature/parameter search. '
                 'Model identity binds learned parameters and training inputs, not future forecast values. '
                 'Declared real data is not independent proof of identity, source truth or clock accuracy.')
    model['model_id'] = model_fingerprint(model)
    guard()
    return model


def forecast(model, forecasts, guard=no_op):
    require(model['model_id'] == model_fingerprint(model), 'model fingerprint mismatch')
    require(isinstance(forecasts, list) and 1 <= len(forecasts) <= 2048, 'bounded forecast rows required')
    parameters, names, settings = model['parameters'], model['features'], model['settings']
    train_animals = {row['animal_id'] for row in model['training']['used']}
    training_cycles = {(row['animal_id'], row['cycle_id']) for row in model['training']['used']}
    result, audit, seen = [], [], set()
    for index, row in enumerate(forecasts):
        if index % 256 == 0:
            guard()
        key = (identifier(row['animal_id']), identifier(row['record_id']))
        require(key not in seen, 'duplicate forecast record')
        seen.add(key)
        require('target' not in row and row['role'] in ('validation', 'test', None), 'label-free evaluation rows required')
        require(required_time(row['as_of']) > required_time(model['training']['fit_cutoff']), 'forecast before fit cutoff')
        require((key[0], row['cycle_id']) not in training_cycles, 'forecast cycle overlaps training')
        if model['training']['mode'] == 'future_cycle':
            require(key[0] in train_animals, 'personalized forecast lacks eligible animal history')
        else:
            require(key[0] not in train_animals, 'held-out forecast animal overlaps training')
        vector, reasons = feature_vector(row['features'], names)
        predicted, floored = None, False
        if not reasons:
            standardized = []
            for value, center, scale, constant in zip(vector, parameters['means'], parameters['scales'], parameters['constant']):
                if constant and not math.isclose(value, center, rel_tol=1e-12, abs_tol=1e-12):
                    reasons.append('changed_constant_feature')
                z = 0. if constant else (value - center) / scale
                if abs(z) > settings['max_abs_z']:
                    reasons.append('outside_training_support')
                standardized.append(z)
            if not reasons:
                value = parameters['intercept'] + math.fsum(a * b for a, b in zip(standardized, parameters['coefficients']))
                if not math.isfinite(value) or value > settings['max_prediction_hours']:
                    reasons.append('outside_prediction_horizon')
                else:
                    predicted, floored = max(0., float(value)), value < 0
        result.append(dict(animal_id=key[0], record_id=key[1], hours_until_start=predicted))
        audit.append(dict(animal_id=key[0], record_id=key[1], reasons=sorted(set(reasons)),
                          floor_at_zero_applied=floored, feature_row_sha256=fingerprint(row)))
    guard()
    return result, audit


def load_plan(path):
    path = Path(path)
    settings = read_json(path, limit=64 * 1024)
    validate_settings(settings)
    cohort_path = relative(path.parent, settings['cohort'])
    require(cohort_path.stat().st_size <= COHORT_LIMIT, 'cohort exceeds size limit')
    require(digest(cohort_path) == settings['cohort_sha256'], 'frozen cohort byte hash mismatch')
    cohort = read_json(cohort_path, limit=COHORT_LIMIT)
    require(cohort['experiment_id'] == settings['experiment_id'], 'experiment mismatch')
    return settings, cohort, cohort_path


def native_preflight(settings):
    require(platform.node().upper() == settings['execution_host'].upper(),
            'native fitting/scoring must run on the declared execution host')
    system = platform.system()
    require(system in ('Windows', 'Darwin'), 'unsupported native execution platform')
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    import psutil
    process = psutil.Process()
    gpu, affinity = None, None
    if system == 'Windows':
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        process.cpu_affinity([0])
        result = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=8)
        require(result.returncode == 0, 'GPU/resource snapshot failed')
        gpu, affinity = result.stdout, process.cpu_affinity()
    else:
        process.nice(max(10, process.nice()))
    deadline = time.monotonic() + 60

    def guard():
        require(time.monotonic() < deadline, 'bounded attempt deadline exceeded')
        require(psutil.virtual_memory().available >= 3 * 1024**3, 'insufficient free RAM; existing work takes priority')
        require(process.memory_info().rss <= 512 * 1024**2, 'runner RSS limit exceeded')

    guard()
    snapshot = dict(at=now(), host=platform.node(), pid=process.pid, created=process.create_time(),
        free_ram=psutil.virtual_memory().available, rss=process.memory_info().rss, gpu=gpu,
        cpu_affinity=affinity, priority=int(process.nice()), gpu_allocation_bytes=0, execution_device='cpu',
        workload=[item.info for item in psutil.process_iter(['pid', 'name', 'create_time'])
                  if 'python' in (item.info.get('name') or '').lower()
                  or 'ffmpeg' in (item.info.get('name') or '').lower()],
        limits=('CPU1 affinity/BelowNormal' if system == 'Windows' else 'CPU thread environment1/nice>=10; affinity unavailable')
        + '; no GPU allocation; freeRAM3GiB/RSS512MiB sampled; cooperative 60s guard; no peak or thermal certification')
    return snapshot, guard


def fit_run(plan_path, output_path, software_test=False):
    output = Path(output_path)
    require(not output.exists(), 'run output already exists; never overwrite or automatically restart')
    settings, cohort, _ = load_plan(plan_path)
    validate_mode(cohort, software_test)
    snapshot, guard = native_preflight(settings)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    save_artifact(output / 'started.json', dict(at=now(), preflight=snapshot,
        plan_sha256=digest(Path(plan_path)), cohort_sha256=settings['cohort_sha256'], software_test=software_test))
    fit_completed, forecast_completed, fit_seconds = False, False, None
    try:
        model = train_artifact(cohort, settings, software_test, guard)
        fit_completed, fit_seconds = True, time.monotonic() - started
        require(len(encode(model)) <= COHORT_LIMIT, 'model artifact too large')
        # Preserve the fitted parameters even if the subsequent forecast input is rejected.
        save_artifact(output / 'model.json', model)
        rows, audit = forecast(model, cohort['forecast_rows'], guard)
        forecast_completed = True
        predictions = dict(schema_version=1, kind='appearance_point_predictions', dataset_kind=model['dataset_kind'],
            feature_version=model['feature_version'], model_id=model['model_id'], cohort_sha256=settings['cohort_sha256'], rows=rows)
        for name, value in [('predictions.json', predictions), ('forecast-review.json', audit)]:
            require(len(encode(value)) <= COHORT_LIMIT, 'runner artifact too large')
            save_artifact(output / name, value)
        guard()
        result = dict(schema_version=1, kind='appearance_fit_run', created_at=now(), status=model['status'],
            model_id=model['model_id'], dataset_kind=model['dataset_kind'], actual_biological_fit=not software_test,
            biological_validation_complete=False, actuation_allowed=False,
            plan_sha256=digest(Path(plan_path)), cohort_sha256=settings['cohort_sha256'],
            code_sha256=model['code_sha256'], training_sha256=model['training']['source_sha256'],
            forecast_sha256=fingerprint(cohort['forecast_rows']), elapsed_seconds=time.monotonic() - started,
            preflight=snapshot, fit_attempts=1, forecast_passes=1, fit_seconds=fit_seconds,
            files={name: digest(output / name) for name in ('model.json', 'predictions.json', 'forecast-review.json', 'started.json')},
            evidence='Local execution receipt and integrity hashes, not trusted remote attestation or biological validation.')
        save_artifact(output / 'run.json', result)
        return result
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        save_artifact(output / 'failure.json', dict(at=now(), error=type(exc).__name__, message=str(exc),
            elapsed_seconds=time.monotonic() - started, automatic_retry=False,
            fit_completed=fit_completed, forecast_completed=forecast_completed, fit_seconds=fit_seconds,
            actual_biological_fit=False if software_test else True if fit_completed else None,
            note='Partial outputs retained; no completed run claimed. Inspect before a separate authorized attempt.'))
        raise


def verify_run(plan_path, run_path):
    settings, cohort, _ = load_plan(plan_path)
    root = Path(run_path)
    run = read_json(root / 'run.json', limit=COHORT_LIMIT)
    require(run['kind'] == 'appearance_fit_run' and run['plan_sha256'] == digest(Path(plan_path))
            and run['cohort_sha256'] == settings['cohort_sha256'], 'run/plan binding mismatch')
    require(set(run['files']) == {'model.json', 'predictions.json', 'forecast-review.json', 'started.json'},
            'incomplete run artifacts')
    require(all(digest(root / name) == expected for name, expected in run['files'].items()), 'run artifact hash mismatch')
    require(run['code_sha256'] == code_hashes(), 'runner implementation changed; use the recorded revision')
    require(run['training_sha256'] == fingerprint(cohort['training_rows'])
            and run['forecast_sha256'] == fingerprint(cohort['forecast_rows']), 'run input binding mismatch')
    model = read_json(root / 'model.json', limit=COHORT_LIMIT)
    predictions = read_json(root / 'predictions.json', limit=COHORT_LIMIT)
    validate_mode(cohort, model['status'] == 'software_test_only')
    require(model_fingerprint(model) == model['model_id'] == run['model_id'] == predictions['model_id'],
            'model identity mismatch')
    require(model['settings'] == {key: settings[key] for key in SETTING_KEYS}
            and model['training']['source_sha256'] == run['training_sha256'], 'model settings/training mismatch')
    require(model['dataset_kind'] == predictions['dataset_kind'] == run['dataset_kind'] == cohort['dataset_kind']
            and model['status'] == run['status']
            and model['actual_biological_fit'] == run['actual_biological_fit'] == (cohort['dataset_kind'] == 'real'),
            'real/test fitting status mismatch')
    require(run['biological_validation_complete'] is False and run['actuation_allowed'] is False,
            'run must not claim biological promotion or actuation')
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fit or score the fixed appearance ridge model on the declared CPU host')
    commands = parser.add_subparsers(dest='command', required=True)
    fit = commands.add_parser('fit')
    fit.add_argument('--plan', type=Path, required=True)
    fit.add_argument('--output', type=Path, required=True)
    fit.add_argument('--software-test', action='store_true')
    score = commands.add_parser('score')
    score.add_argument('--plan', type=Path, required=True)
    score.add_argument('--run', type=Path, required=True)
    score.add_argument('--evaluation-plan', type=Path, required=True)
    score.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fit':
            result = fit_run(args.plan, args.output, args.software_test)
        else:
            require(not args.output.exists(), 'score output already exists')
            settings, _, cohort_path = load_plan(args.plan)
            _, guard = native_preflight(settings)
            run = verify_run(args.plan, args.run)
            result = evaluate_predictions(args.evaluation_plan, cohort_path, args.run / 'predictions.json')
            guard()
            result.update(runner_integrity_verified=True, run_sha256=digest(args.run / 'run.json'),
                          actual_biological_fit=run['actual_biological_fit'])
            save_artifact(args.output, result)
        print(json.dumps(dict(output=str(args.output.resolve()), kind=result['kind'],
                              actual_biological_fit=result['actual_biological_fit'], biological_validation_complete=False)))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.TimeoutExpired) as exc:
        print(json.dumps(dict(error=type(exc).__name__, message=str(exc))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
