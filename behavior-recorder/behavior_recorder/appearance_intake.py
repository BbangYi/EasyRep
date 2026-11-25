"""Explicit human-reviewed diary intake. Reuses strict collectors; never fits or controls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .analysis_features import save_artifact
from .appearance import collect, validate_metadata
from .appearance_journal import Journal, MAX_PHOTO
from .appearance_predictor import native_preflight
from .appearance_series import ARTIFACT_LIMIT, IDENTITY, build_series, write_series
from .core import RecorderError, digest, encode, identifier, now, read_json, relative, require, timestamp

MAX_ENTRIES = 24
PLAN_LIMIT = 1024**2
RAW_LIMIT = 128 * 1024**2
MASK_LIMIT = 16 * 1024**2


def moment(value):
    result = timestamp(value)
    require(result is not None, 'explicit timestamp required')
    return result


def evidence(value):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 1024, 'review evidence/reason required')


def reader(storage):
    settings = read_json(relative(Path(storage), 'journal.json'), limit=65536)
    return Journal(storage, dataset_kind=settings['dataset_kind'], read_only=True)


def source_record(journal, record_id, expected=None):
    require(isinstance(record_id, str) and re.fullmatch(r'[0-9a-f]{32}', record_id), 'invalid journal record ID')
    path = relative(journal.storage, f'records/{record_id}.json')
    record = journal.load(path)
    _, value = bounded_hash(path, 65536, lambda: None)
    require(expected is None or value == expected, 'journal record byte hash mismatch')
    require(type(record['schema_version']) is int and record['schema_version'] == 1,
            'unsupported diary schema')
    require(moment(record['received_at']) >= moment(record['input']['latest_at']),
            'journal receipt precedes observation interval')
    return record, path, value


def prepare_review(journal_path, record_ids, output_path):
    output = Path(output_path)
    require(not output.exists(), 'output already exists')
    journal = reader(journal_path)
    require(not output.resolve().is_relative_to(journal.storage), 'do not write into original journal')
    require(journal.storage.is_relative_to(output.parent.resolve()),
            'place review plan in an ancestor directory of the journal')
    require(isinstance(record_ids, list) and 1 <= len(record_ids) <= MAX_ENTRIES, 'select one to24 explicit records')
    require(len(set(record_ids)) == len(record_ids), 'duplicate journal record')
    entries, animals, enclosures = [], set(), set()
    for key in record_ids:
        record, _, byte_hash = source_record(journal, key)
        animals.add(record['input']['animal_id']); enclosures.add(record['input']['enclosure_id'])
        entries.append(dict(record_id=key, record_sha256=byte_hash, event_stage=None,
                            color_review=None, hold_reason='not_reviewed'))
    require(len(animals) == 1, 'select records for one animal only')
    require(len(enclosures - {None}) <= 1, 'conflicting declared enclosures; separate reviews required')
    plan = dict(schema_version=1, kind='appearance_reviewed_intake_plan',
        journal=journal.storage.relative_to(output.parent.resolve()).as_posix(),
        dataset_kind=journal.dataset_kind, animal_id=next(iter(animals)),
        enclosure_id=next(iter(enclosures - {None}), None),
        reviewer=None, reviewed_at=None, identity_confirmed=False, entries=entries)
    save_artifact(output, plan)
    return plan


def bounded_hash(path, limit, guard):
    size, value = 0, hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(min(1024**2, limit - size + 1)):
            size += len(chunk)
            require(size <= limit, 'media input exceeds byte limit')
            value.update(chunk); guard()
    require(size > 0, 'empty media input')
    return size, value.hexdigest()


def checked_photo(journal, record, reviewed, guard):
    key = record['input']['photo_id']
    require(key is not None, 'color review requires an attached photo')
    metadata_path = relative(journal.storage, f'photos/{key}.json')
    photo = read_json(metadata_path, limit=65536)
    require(photo == record['photo'] and photo['id'] == photo['sha256'] == key
            and photo['path'] == f'photos/{key}.source'
            and photo['status'] == 'unreviewed_attachment' and photo['decoded'] is False
            and photo['media_rights_verified'] is False, 'journal photo metadata mismatch')
    require(moment(photo['received_at']) <= reviewed, 'photo not available at review time')
    path = relative(journal.storage, photo['path'])
    size, byte_hash = bounded_hash(path, MAX_PHOTO, guard)
    require(size == photo['bytes'] and byte_hash == key, 'journal photo bytes/hash mismatch')
    return photo, path, metadata_path


def reviewed_inputs(plan_path, guard):
    plan_path = Path(plan_path)
    plan = read_json(plan_path, limit=PLAN_LIMIT)
    _, plan_hash = bounded_hash(plan_path, PLAN_LIMIT, guard)
    require(isinstance(plan, dict) and set(plan) == {'schema_version', 'kind', 'journal', 'dataset_kind',
        'animal_id', 'enclosure_id', 'reviewer', 'reviewed_at', 'identity_confirmed', 'entries'}, 'invalid intake plan fields')
    require(type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_reviewed_intake_plan', 'unsupported intake plan')
    identifier(plan['animal_id']); identifier(plan['reviewer'])
    reviewed = moment(plan['reviewed_at'])
    require(reviewed <= moment(now()), 'review cannot be in the future')
    require(type(plan['identity_confirmed']) is bool, 'explicit identity review required')
    if plan['enclosure_id'] is not None:
        identifier(plan['enclosure_id'])
    entries = plan['entries']
    require(isinstance(entries, list) and 1 <= len(entries) <= MAX_ENTRIES, 'bounded explicit entries required')
    journal = reader(relative(plan_path.parent, plan['journal']))
    require(plan['dataset_kind'] == journal.dataset_kind, 'review/journal dataset kind mismatch')
    checked, seen, frames, total = [], set(), set(), 0
    for entry in entries:
        guard()
        require(isinstance(entry, dict) and set(entry) == {'record_id', 'record_sha256', 'event_stage',
            'color_review', 'hold_reason'}, 'invalid intake entry')
        key = entry['record_id']
        require(key not in seen, 'duplicate journal record'); seen.add(key)
        require(isinstance(entry['record_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', entry['record_sha256']), 'explicit source record SHA256 required')
        record, record_path, record_hash = source_record(journal, key, entry['record_sha256'])
        source = record['input']
        require(source['animal_id'] == plan['animal_id'], 'journal/review animal mismatch')
        require(source['enclosure_id'] is None or source['enclosure_id'] == plan['enclosure_id'],
                'journal/review enclosure mismatch')
        require(moment(record['received_at']) <= reviewed, 'record unavailable at declared review time')
        stage, color = entry['event_stage'], entry['color_review']
        actions = stage is not None or color is not None
        if actions:
            require(plan['identity_confirmed'] is True, 'explicit reviewed identity required before collection')
            identifier(plan['enclosure_id'])
            require(entry['hold_reason'] is None, 'cannot collect and hold the same entry')
        else:
            evidence(entry['hold_reason'])
        item = dict(entry=entry, source=record, source_path=record_path, source_sha256=record_hash,
                    event=None, color=None, photo=None, mask=None)
        common = dict(schema_version=1, dataset_kind=plan['dataset_kind'], animal_id=plan['animal_id'],
                      enclosure_id=plan['enclosure_id'], species=record['species'])
        if stage is not None:
            require(stage in ('started', 'completed', 'uncertain') and stage == source['assessment'],
                    'event stage must match explicit source assessment; preserve uncertainty and corrections separately')
            item['event'] = {**common, 'kind': 'shedding_event', 'record_id': key + '-event',
                'stage': stage, 'earliest_at': source['earliest_at'], 'latest_at': source['latest_at'],
                'observer': source['observer'], 'evidence_reference': f'journal:{key};source-sha256:{record_hash};review:{plan["reviewer"]};plan-sha256:{plan_hash}'}
            validate_metadata(item['event'])
        if color is not None:
            require(isinstance(color, dict) and set(color) == {'observed_at', 'body_region', 'capture', 'review',
                'mask', 'mask_sha256', 'media_rights'}, 'invalid color review fields')
            rights = color['media_rights']
            require(isinstance(rights, dict) and set(rights) == {'basis', 'evidence_reference'}
                    and rights['basis'] in ('own', 'permission', 'licensed'), 'explicit image/mask rights declaration required')
            evidence(rights['evidence_reference'])
            photo, path, metadata = checked_photo(journal, record, reviewed, guard)
            observed = moment(color['observed_at'])
            require(moment(source['earliest_at']) <= observed <= moment(source['latest_at'])
                    and observed <= moment(photo['received_at']), 'capture time must be inside source interval and before photo receipt')
            require(isinstance(color['review'], dict) and color['review'].get('observer') == plan['reviewer'],
                    'color reviewer must match intake reviewer')
            frame = (photo['sha256'], color['body_region'])
            require(frame not in frames, 'duplicate image/body region in reviewed intake'); frames.add(frame)
            mask_path = relative(plan_path.parent, color['mask'])
            mask_bytes, mask_hash = bounded_hash(mask_path, MASK_LIMIT, guard)
            require(mask_hash == color['mask_sha256'], 'reviewed mask byte hash mismatch')
            total += photo['bytes'] + mask_bytes
            require(total <= RAW_LIMIT, 'selected media payload exceeds128MiB')
            item['photo'] = dict(path=path, metadata_path=metadata, metadata=photo)
            item['mask'] = dict(path=mask_path, bytes=mask_bytes, sha256=mask_hash)
            item['color'] = {**common, 'kind': 'color_observation', 'record_id': key + '-color',
                'observed_at': color['observed_at'], 'body_region': color['body_region'],
                'capture': color['capture'], 'review': color['review'],
                'image': f'sources/photos/{photo["id"]}.source', 'mask': f'masks/{key}.png'}
            validate_metadata(item['color'])
        checked.append(item)
    return plan, journal, checked, total


def copy_verified(source, target, expected_hash, limit, guard):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        require(digest(target) == expected_hash, 'retained copy differs')
        return
    count, value = 0, hashlib.sha256()
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        while chunk := incoming.read(min(1024**2, limit - count + 1)):
            count += len(chunk); require(count <= limit, 'copy exceeds input byte limit')
            outgoing.write(chunk); value.update(chunk); guard()
        outgoing.flush()
        import os
        os.fsync(outgoing.fileno())
    require(value.hexdigest() == expected_hash, 'source changed during intake copy')


def collect_review(plan_path, output_path, execution_host):
    output, plan_path = Path(output_path), Path(plan_path)
    require(not output.exists(), 'output already exists; inspect partial work before a new version')
    snapshot, guard = native_preflight({'execution_host': execution_host})
    _, plan_hash = bounded_hash(plan_path, PLAN_LIMIT, guard)
    plan, journal, entries, raw_bytes = reviewed_inputs(plan_path, guard)
    require(not output.resolve().is_relative_to(journal.storage), 'do not write into original journal')
    require(bounded_hash(plan_path, PLAN_LIMIT, guard)[1] == plan_hash, 'review plan changed during validation')
    guard()
    output.mkdir(parents=True, exist_ok=False)
    save_artifact(output / 'started.json', dict(at=now(), preflight=snapshot, plan_sha256=plan_hash))
    records, holds = [], []
    try:
        copy_verified(plan_path, output / 'review-plan.source.json', plan_hash, PLAN_LIMIT, guard)
        require(read_json(output / 'review-plan.source.json', limit=PLAN_LIMIT) == plan,
                'review plan snapshot differs from validated content')
        settings = relative(journal.storage, 'journal.json')
        copy_verified(settings, output / 'sources/journal.json', bounded_hash(settings, 65536, guard)[1], 65536, guard)
        for item in entries:
            entry = item['entry']; key = entry['record_id']
            copy_verified(item['source_path'], output / f'sources/records/{key}.json',
                          item['source_sha256'], 65536, guard)
            require(read_json(output / f'sources/records/{key}.json', limit=65536) == item['source'],
                    'journal snapshot differs from validated content')
            if item['photo']:
                photo = item['photo']; metadata = photo['metadata']
                copy_verified(photo['path'], output / item['color']['image'], metadata['sha256'], MAX_PHOTO, guard)
                copy_verified(photo['metadata_path'], output / f'sources/photos/{metadata["id"]}.json',
                              bounded_hash(photo['metadata_path'], 65536, guard)[1], 65536, guard)
                require(read_json(output / f'sources/photos/{metadata["id"]}.json', limit=65536) == metadata,
                        'photo metadata changed after review validation')
                mask = item['mask']
                copy_verified(mask['path'], output / item['color']['mask'], mask['sha256'], MASK_LIMIT, guard)
            for kind in ('event', 'color'):
                metadata = item[kind]
                if metadata is None:
                    continue
                guard()
                name = metadata['record_id']
                source_path, artifact_path = output / f'{name}.input.json', output / f'records/{name}.json'
                save_artifact(source_path, metadata)
                artifact = collect(source_path, artifact_path)
                require(moment(artifact['created_at']) >= moment(plan['reviewed_at']),
                        'collection clock precedes review; preserve partial outputs')
                records.append(dict(source_record_id=key, source_record_sha256=item['source_sha256'],
                    artifact=artifact_path.relative_to(output).as_posix(), artifact_sha256=digest(artifact_path),
                    input=source_path.relative_to(output).as_posix(), status=artifact['status'],
                    stage=metadata.get('stage'), media_rights_declaration=entry['color_review']['media_rights'] if kind == 'color' else None))
            if entry['hold_reason'] is not None:
                holds.append(dict(record_id=key, source_sha256=item['source_sha256'], reason=entry['hold_reason']))
        require(bounded_hash(plan_path, PLAN_LIMIT, guard)[1] == plan_hash, 'review plan changed during collection')
        guard()
        series_path = None
        if records:
            series = dict(schema_version=1, kind='appearance_series', dataset_kind=plan['dataset_kind'],
                animal_id=plan['animal_id'], enclosure_id=plan['enclosure_id'], species='crested_gecko',
                records=[row['artifact'] for row in records])
            save_artifact(output / 'series.json', series)
            write_series(output / 'series.json', output / 'series-report.json')
            series_path = 'series.json'
        report = dict(schema_version=1, kind='appearance_reviewed_intake', created_at=now(),
            dataset_kind=plan['dataset_kind'], reviewer=plan['reviewer'], reviewed_at=plan['reviewed_at'],
            plan_sha256=plan_hash, records=records, held=holds, series_manifest=series_path,
            code_sha256={name: digest(Path(__file__).with_name(name)) for name in (
                'appearance_intake.py', 'appearance_journal.py', 'appearance.py',
                'appearance_series.py', 'core.py', 'analysis_features.py')},
            counts=dict(human_events=sum(r['status']=='human_event_recorded' for r in records),
                measured_color=sum(r['status']=='measured' for r in records),
                excluded_color=sum(r['status']=='excluded' for r in records), held=len(holds)),
            selected_media_payload_bytes=raw_bytes,
            files={p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*')) if p.is_file()},
            actual_training=False, training_readiness='not_assessed', prediction=None, actuation_allowed=False,
            original_journal_modified=False, independently_verified_identity=False, independently_verified_rights=False,
            evidence='Reviewed declarations, immutable source copies and strict collector results; no automatic labels, cycle links, biological validation or pixel/clock attestation.',
            limits='24 selected entries/plan1MiB/photo8MiB/mask16MiB/media payload128MiB. Payload bound is not total repeated IO; CPU/RSS/time are bounded by the execution guard.')
        guard()
        save_artifact(output / 'intake-report.json', report)
        return report
    except (RecorderError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        save_artifact(output / 'failure.json', dict(at=now(), error=type(exc).__name__, message=str(exc),
            automatic_retry=False, partial_outputs_retained=True, actual_training=False,
            successfully_collected_records=records, actuation_allowed=False))
        raise


def compose_history(plan_path, output_path, execution_host):
    """Bind completed intakes to an ancestor manifest; leave source artifacts in place."""
    plan_path, output = Path(plan_path).resolve(), Path(output_path).absolute()
    snapshot, guard = native_preflight({'execution_host': execution_host})
    sidecars = {name: output.with_name(output.name + '.' + name + '.json')
                for name in ('started', 'candidate', 'receipt', 'failure')}
    require(not any(p.exists() or p.is_symlink() for p in [output, *sidecars.values()]),
            'history output or partial work already exists; choose a new version')
    budget, consumed = 32 * 1024**2, 0
    snapshots = {}
    unbound = object()

    def frozen(path, limit, expected=unbound):
        nonlocal consumed
        guard()
        with path.open('rb') as stream:
            content = stream.read(min(limit, budget - consumed) + 1)
        consumed += len(content)
        require(len(content) <= limit and consumed <= budget, 'history metadata byte limit exceeded')
        value = hashlib.sha256(content).hexdigest()
        if expected is not unbound:
            require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected), 'explicit SHA256 hash required')
            require(value == expected, 'history source hash mismatch')
        require(path not in snapshots or snapshots[path][0] == value, 'history source changed while reading')
        snapshots[path] = (value, limit)
        return json.loads(content, parse_constant=lambda _: require(False, 'invalid JSON number'))

    plan = frozen(plan_path, PLAN_LIMIT)
    require(isinstance(plan, dict) and set(plan) == {'schema_version', 'kind', 'intakes'}
            and type(plan['schema_version']) is int and plan['schema_version'] == 1
            and plan['kind'] == 'appearance_reviewed_history_plan', 'invalid history plan')
    require(isinstance(plan['intakes'], list) and 1 <= len(plan['intakes']) <= 32, 'select one to32 explicit completed intakes')
    sources, paths, held, identities, declared = [], [], [], [], []
    seen = set()
    for entry in plan['intakes']:
        require(isinstance(entry, dict) and set(entry) == {'path', 'sha256'}, 'invalid intake reference')
        require(isinstance(entry['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', entry['sha256']), 'explicit intake hash required')
        path = relative(plan_path.parent, entry['path'])
        require(path.name == 'intake-report.json', 'completed intake report required')
        require(path not in seen, 'duplicate intake report'); seen.add(path)
        require(path.parent != output.parent.resolve() and path.is_relative_to(output.parent.resolve()),
                'history manifest must have a strict ancestor of source batches as its parent')
        require(not (path.parent / 'failure.json').exists(), 'failed or partial intake cannot enter history')
        report = frozen(path, PLAN_LIMIT, entry['sha256'])
        require(report['kind'] == 'appearance_reviewed_intake' and type(report['schema_version']) is int
                and report['schema_version'] == 1 and report['actual_training'] is False
                and report['prediction'] is None and report['actuation_allowed'] is False, 'invalid completed intake')
        require(report['files']['review-plan.source.json'] == report['plan_sha256'], 'intake review plan hash mismatch')
        reviewed = frozen(relative(path.parent, 'review-plan.source.json'), PLAN_LIMIT, report['plan_sha256'])
        require(reviewed['dataset_kind'] == report['dataset_kind'] and reviewed['reviewer'] == report['reviewer']
                and reviewed['reviewed_at'] == report['reviewed_at'], 'intake review identity mismatch')
        require(moment(reviewed['reviewed_at']) <= moment(report['created_at']) <= moment(now()), 'invalid intake completion time')
        declared.append(reviewed)
        require(isinstance(report['records'], list) and len(report['records']) <= 48
                and isinstance(report['held'], list) and len(report['held']) <= MAX_ENTRIES, 'invalid intake record lists')
        require(isinstance(report['files'], dict), 'intake file hashes required')
        held.extend(dict(intake=entry['path'], **row) for row in report['held'])
        sources.append(dict(path=entry['path'], sha256=entry['sha256'], completed_at=report['created_at']))
        if not report['records']:
            require(report['series_manifest'] is None, 'empty intake cannot claim a series')
            continue
        name = report['series_manifest']
        series = frozen(relative(path.parent, name), ARTIFACT_LIMIT, report['files'][name])
        require(isinstance(series, dict) and set(series) == {'schema_version', 'kind', *IDENTITY, 'records'}
                and type(series['schema_version']) is int and series['schema_version'] == 1
                and series['kind'] == 'appearance_series', 'invalid source series schema')
        require(series['records'] == [r['artifact'] for r in report['records']], 'intake series/record list mismatch')
        identities.append({k: series[k] for k in IDENTITY})
        for row in report['records']:
            require(report['files'][row['artifact']] == row['artifact_sha256'], 'intake artifact hash mismatch')
            artifact_path = relative(path.parent, row['artifact'])
            artifact = frozen(artifact_path, ARTIFACT_LIMIT, row['artifact_sha256'])
            require(artifact['status'] == row['status'] and moment(artifact['created_at']) <= moment(report['created_at']),
                    'intake artifact status/time mismatch')
            # Existing series validation checks artifact identity, hashes, exclusion and duplicates.
            paths.append(artifact_path.relative_to(output.parent.resolve()).as_posix())
            require(len(paths) <= 512, 'history exceeds512 records')
    require(identities and all(item == identities[0] for item in identities), 'intake identity mismatch or no collected records')
    identity = identities[0]
    for item in declared:
        require(item['animal_id'] == identity['animal_id'] and item['dataset_kind'] == identity['dataset_kind']
                and item['enclosure_id'] in (None, identity['enclosure_id']), 'reviewed animal/dataset/enclosure identity mismatch')
    manifest = dict(schema_version=1, kind='appearance_series', **identity, records=paths)
    require(len(encode(manifest)) <= ARTIFACT_LIMIT, 'history manifest too large')
    # Reserve the existing validator's bounded reads in addition to our explicit metadata reads.
    consumed += (len(paths) + 1) * ARTIFACT_LIMIT
    require(consumed <= budget, 'history metadata byte limit exceeded')
    save_artifact(sidecars['started'], dict(at=now(), preflight=snapshot, plan_sha256=snapshots[plan_path][0]))
    try:
        save_artifact(sidecars['candidate'], manifest)
        series_report = build_series(sidecars['candidate'])
        require(all(row['artifact_sha256'] == snapshots[relative(output.parent, row['artifact'])][0]
                    for row in series_report['records']), 'history artifact changed during series validation')
        for path, (value, limit) in list(snapshots.items()):
            frozen(path, limit, value)
        guard()
        receipt = dict(schema_version=1, kind='appearance_reviewed_history', created_at=now(),
            plan_sha256=snapshots[plan_path][0], sources=sources, held=held, identity=identity,
            manifest=output.name, manifest_sha256=hashlib.sha256(encode(manifest)).hexdigest(),
            series_report=series_report, metadata_bytes_upper_accounting=consumed,
            actual_training=False, prediction=None, actuation_allowed=False,
            evidence='Completed-report and metadata byte bindings only. Original media/features, identity, rights and clocks are not independently reverified. No automatic cycle links or labels.')
        require(len(encode(receipt)) <= PLAN_LIMIT, 'history receipt too large')
        save_artifact(sidecars['receipt'], receipt)
        # Publish the usable manifest last; interrupted attempts leave no completed history.
        save_artifact(output, manifest)
        return receipt
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        save_artifact(sidecars['failure'], dict(at=now(), error=type(exc).__name__, message=str(exc),
            partial_outputs_retained=True, automatic_retry=False, actual_training=False, actuation_allowed=False))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'collect', 'history'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--journal'); parser.add_argument('--records', nargs='+')
    parser.add_argument('--plan'); parser.add_argument('--execution-host')
    args = parser.parse_args(argv)
    try:
        if args.action == 'prepare':
            require(args.journal and args.records, 'journal and explicit record IDs required')
            result = prepare_review(args.journal, args.records, args.output)
        else:
            require(args.plan and args.execution_host, 'review plan and execution host required')
            operation = compose_history if args.action == 'history' else collect_review
            result = operation(args.plan, args.output, args.execution_host)
        print(encode({'output': str(Path(args.output).resolve()), 'kind': result['kind']}).decode(), end='')
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
