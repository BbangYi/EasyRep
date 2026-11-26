"""Read-only gateway logs -> explicit, action-conditioned offline learning windows.

No Store, device transport, network client, training or hardware authorization.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from habitat.common.models import Identifier, Model, Timestamp, aware_timestamp
from habitat_gateway.models import Telemetry
from .environment import minute_history
from .errors import ComputeFailure

HISTORY = 30
HORIZON = 60


class Session(Model):
    session_id: Identifier
    episode_id: Identifier
    database: str = Field(min_length=1)
    cage_id: Identifier
    split: Literal['train', 'validation', 'test']
    start: Timestamp
    end: Timestamp
    geometry_revision: int = Field(strict=True, ge=1)
    placement_revision: int = Field(strict=True, ge=1)
    mist_history: Literal['declared_zero', 'execution_log']
    declared_by: str = Field(min_length=1, max_length=120)
    coverage_note: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def time_order(self):
        if self.end <= self.start:
            raise ValueError('session end must follow start')
        return self


class DatasetManifest(Model):
    schema_version: Literal[1]
    data_source: Literal['sensor', 'simulation']
    site_id: Identifier
    gateway_id: Identifier
    sensor_ids: list[Identifier] = Field(min_length=4, max_length=4)
    sessions: list[Session] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def partitions(self):
        if len(set(self.sensor_ids)) != 4:
            raise ValueError('four distinct sensor IDs required: temperature, RH, temperature, temperature')
        if len({s.session_id for s in self.sessions}) != len(self.sessions):
            raise ValueError('duplicate session_id')
        episodes = {}
        for session in self.sessions:
            previous = episodes.setdefault(session.episode_id, session.split)
            if previous != session.split:
                raise ValueError('an episode cannot cross dataset splits')
        for i, first in enumerate(self.sessions):
            for second in self.sessions[i+1:]:
                if first.cage_id == second.cage_id and max(first.start, second.start) <= min(first.end, second.end):
                    raise ValueError('overlapping cage sessions, including database copies')
                rank = {'train': 0, 'validation': 1, 'test': 2}
                if first.cage_id == second.cage_id and first.split != second.split:
                    earlier, later = sorted((first, second), key=lambda s: s.start)
                    if rank[earlier.split] > rank[later.split]:
                        raise ValueError('cage splits must follow train/validation/test time order')
        return self


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def epoch(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a timezone-aware ISO string')
    return aware_timestamp(datetime.fromisoformat(value)).timestamp()


def read_session(database, session, manifest):
    """Use a SQLite read transaction, including WAL; never create a missing database."""
    path = Path(database).resolve(strict=True)
    start, end = session.start.timestamp(), session.end.timestamp()
    samples, executions, seen, counters = [], [], {}, Counter()
    digest = hashlib.sha256()
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        identity = db.execute('SELECT site_id,gateway_id FROM cloud_identity').fetchone()
        if identity and tuple(identity) != (manifest.site_id, manifest.gateway_id):
            raise ValueError('database site/gateway mismatch')
        for message_id, sampled_at, received_at, body in db.execute(
            'SELECT message_id,sampled_at,received_at,body FROM telemetry WHERE cage_id=? ORDER BY rowid', (session.cage_id,)):
            stamp = epoch(sampled_at)
            if not start <= stamp <= end:
                continue
            counters['source_rows'] += 1
            sample = Telemetry.model_validate_json(body)
            received = epoch(received_at)
            if sample.message_id != UUID(message_id) or sample.sampled_at.timestamp() != stamp:
                raise ValueError('SQL and telemetry identity/time differ')
            if sample.data_source != manifest.data_source:
                raise ValueError('mixed sensor/simulation source')
            if (sample.geometry_revision, sample.placement_revision) != (
                session.geometry_revision, session.placement_revision):
                raise ValueError('revision changed inside session')
            normalized = sample.model_dump(mode='json')
            old = seen.setdefault(stamp, normalized)
            if old != normalized:
                raise ValueError('conflicting measurements at same timestamp')
            if received < stamp:
                raise ValueError('received_at precedes sampled_at; check clocks')
            if session.mist_history == 'declared_zero' and any(sample.actuators.values()):
                raise ValueError('declared_zero contradicts active actuator observation')
            digest.update(encoded([message_id, sampled_at, received_at, normalized]).encode())
            samples.append({**normalized, 'received_epoch': received})
        for occurred_at, body in db.execute(
            "SELECT occurred_at,body FROM audit WHERE kind='mist_execution' AND cage_id=? ORDER BY rowid", (session.cage_id,)):
            event = json.loads(body)
            required = {'started_at', 'ended_at', 'duration_s', 'data_source', 'command_id'}
            if not isinstance(event, dict) or not required <= event.keys():
                raise ValueError('incomplete mist execution record')
            a, b = epoch(event['started_at']), epoch(event['ended_at'])
            if type(event['duration_s']) not in (int, float) or not math.isfinite(event['duration_s']) or b < a or abs(b-a-event['duration_s']) > 1e-6:
                raise ValueError('invalid mist execution interval')
            if b <= start or a >= end:
                continue
            if session.mist_history == 'declared_zero':
                raise ValueError('declared_zero contradicts execution log')
            if event['data_source'] != manifest.data_source:
                raise ValueError('mist execution source mismatch')
            recorded = epoch(occurred_at)
            if recorded < b:
                raise ValueError('execution was recorded before its end')
            UUID(event['command_id'])
            event.update(cage_id=session.cage_id, recorded_epoch=recorded,
                         started_at=aware_timestamp(datetime.fromisoformat(event['started_at'])).isoformat(),
                         ended_at=aware_timestamp(datetime.fromisoformat(event['ended_at'])).isoformat())
            digest.update(encoded([occurred_at, event]).encode())
            executions.append(event)
        executions.sort(key=lambda e: epoch(e['started_at']))
        prior = float('-inf')
        ids = set()
        for event in executions:
            if epoch(event['started_at']) < prior or event['command_id'] in ids:
                raise ValueError('overlapping or duplicated mist executions')
            prior = epoch(event['ended_at'])
            ids.add(event['command_id'])
    finally:
        db.rollback()
        db.close()
    samples.sort(key=lambda s: s['sampled_at'])
    return samples, executions, {
        'session_id': session.session_id, 'episode_id': session.episode_id,
        'source_rows': counters['source_rows'],
        'execution_count': len(executions), 'selected_records_sha256': digest.hexdigest(),
        'identity_evidence': 'database_cloud_identity' if identity else 'manifest_declaration_only',
        'mist_history': session.mist_history, 'declared_by': session.declared_by,
        'coverage_note': session.coverage_note, 'water_volume_measured': False,
    }


def session_windows(samples, executions, session, manifest, skipped):
    # ponytail: session-sized in-memory scans; bin once if real logs make this slow.
    # The first action interval must also be inside declared session coverage.
    first = math.ceil(session.start.timestamp()/60)*60 + HISTORY*60
    last = math.floor(session.end.timestamp()/60)*60 - HORIZON*60

    def rows(boundary, *, available_only=False):
        available = [s for s in samples if not available_only or s['received_epoch'] <= boundary]
        events = [e for e in executions if epoch(e['ended_at']) <= boundary]
        return minute_history(available, manifest.sensor_ids, boundary,
                              data_source=manifest.data_source, executions=events)

    for origin in range(first, last+1, 60):
        relevant = [e for e in executions if epoch(e['ended_at']) > origin-HISTORY*60
                    and epoch(e['started_at']) < origin]
        if any(epoch(e['ended_at']) > origin or e['recorded_epoch'] > origin for e in relevant):
            skipped['execution_unavailable_at_origin'] += 1
            continue
        try:
            times, history = rows(origin, available_only=True)
            _, future1 = rows(origin+30*60)
            _, future2 = rows(origin+60*60)
        except ComputeFailure as error:
            skipped['missing_or_invalid_minutes' if error.code.startswith('waiting_history_') else error.code] += 1
            continue
        future = future1+future2
        # A pulse crossing a target boundary must contribute its elapsed part as well.
        for i, row in enumerate(future, 1):
            boundary = origin+i*60
            row[4] = sum(max(0., min(epoch(e['ended_at']), boundary)-max(epoch(e['started_at']), boundary-60))
                         for e in executions)
        if any(r[4] > 6.000001 for r in future):
            skipped['mist_history_outside_current_model_domain'] += 1
            continue
        record = {
            'kind': 'window', 'schema_version': 1, 'session_id': session.session_id,
            'episode_id': session.episode_id, 'split': session.split,
            'site_id': manifest.site_id, 'gateway_id': manifest.gateway_id, 'cage_id': session.cage_id,
            'data_source': manifest.data_source, 'sensor_ids': manifest.sensor_ids,
            'geometry_revision': session.geometry_revision, 'placement_revision': session.placement_revision,
            'origin_epoch': float(origin), 'history_times': times, 'history': history,
            'target_times': [float(origin+i*60) for i in range(1, 61)],
            'targets': [r[:4] for r in future], 'future_executed_seconds': [r[4] for r in future],
            'action_label_scope': 'retrospective_executed_actions_not_known_future_inputs',
            'mist_history': session.mist_history,
        }
        record['window_id'] = hashlib.sha256(encoded(record).encode()).hexdigest()
        yield record


def build_dataset(manifest_path, output):
    manifest_path, output = Path(manifest_path).resolve(strict=True), Path(output).resolve()
    raw = manifest_path.read_bytes()
    manifest = DatasetManifest.model_validate_json(raw)
    if output.exists():
        raise FileExistsError('output already exists; no overwrite')
    output.parent.mkdir(parents=True, exist_ok=True)
    totals, skipped, receipts, digest = Counter(), Counter(), [], hashlib.sha256()
    header = {'kind': 'manifest', 'schema_version': 1,
        'source_manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'source': manifest.model_dump(mode='json', exclude={'sessions'}),
        'history_minutes': HISTORY, 'horizon_minutes': HORIZON,
        'field_validated': False, 'hardware_execution_allowed': False,
        'target_kind': 'future_sensor_observations_not_hidden_truth',
        'feature_units': ['degC', 'percent_rh', 'degC', 'degC', 'seconds'],
        'normalization': 'none; fit transforms on training split only'}
    created = False
    try:
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            created = True
            stream.write(encoded(header)+'\n')
            for session in manifest.sessions:
                database = (manifest_path.parent/session.database).resolve(strict=True)
                samples, executions, receipt = read_session(database, session, manifest)
                count = 0
                for window in session_windows(samples, executions, session, manifest, skipped):
                    line = encoded(window)+'\n'
                    stream.write(line)
                    digest.update(line.encode())
                    totals[session.split] += 1
                    count += 1
                receipts.append({**receipt, 'split': session.split, 'windows': count})
            if not totals:
                raise ValueError('no complete 30+60 minute windows; no dataset was created')
            summary = {'kind': 'summary', 'status': 'DATASET_CREATED', 'windows': sum(totals.values()),
                'windows_by_split': dict(totals), 'skipped': dict(skipped), 'sessions': receipts,
                'windows_sha256': digest.hexdigest(),
                'all_splits_present': all(totals[k] for k in ('train', 'validation', 'test')),
                'declared_episode_count': len({s.episode_id for s in manifest.sessions}),
                'exported_episode_count': len({r['episode_id'] for r in receipts if r['windows']}),
                'field_validated': False, 'hardware_execution_allowed': False}
            stream.write(encoded(summary)+'\n')
        return summary
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise


def read_dataset(path):
    """Require a complete export and verify the window hash before evaluation."""
    windows, digest, summary = [], hashlib.sha256(), None
    with Path(path).open(encoding='utf-8') as stream:
        header = json.loads(next(stream, 'null'))
        if (not isinstance(header, dict) or header.get('kind') != 'manifest'
                or header.get('schema_version') != 1 or not isinstance(header.get('source'), dict)
                or not {'data_source', 'site_id', 'gateway_id', 'sensor_ids'} <= header['source'].keys()
                or not isinstance(header.get('source_manifest_sha256'), str)):
            raise ValueError('invalid dataset header')
        for line in stream:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('dataset records must be objects')
            if summary is not None:
                raise ValueError('data after dataset summary')
            if row.get('kind') == 'window':
                if row.get('split') not in ('train', 'validation', 'test'):
                    raise ValueError('invalid window split')
                identity = {k: v for k, v in row.items() if k != 'window_id'}
                if row.get('window_id') != hashlib.sha256(encoded(identity).encode()).hexdigest():
                    raise ValueError('modified window identity')
                if any(row.get(k) != header['source'][k]
                       for k in ('data_source', 'site_id', 'gateway_id', 'sensor_ids')):
                    raise ValueError('window/header source mismatch')
                windows.append(row)
                digest.update(line.encode())
            elif row.get('kind') == 'summary':
                summary = row
            else:
                raise ValueError('invalid dataset record')
    if (not summary or not windows or len(windows) != summary.get('windows')
            or digest.hexdigest() != summary.get('windows_sha256')):
        raise ValueError('incomplete or modified dataset')
    if dict(Counter(w['split'] for w in windows)) != summary.get('windows_by_split'):
        raise ValueError('dataset split count mismatch')
    return header, windows, summary
