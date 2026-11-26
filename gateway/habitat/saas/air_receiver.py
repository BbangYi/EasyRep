"""Bounded reference air receiver; production uses its existing web session ACL.

Only the latest field and 256 recent compact receipts per enclosure are retained.
This is a live derived view, not a historical ledger. Conflicting IDs are detected
while their receipts (or latest field) remain; evicted receipts are not recoverable.
"""
from datetime import datetime
import hashlib
import json
import math
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from habitat.common.models import utcnow
from .air_contract import (AIR_PATH, MAX_AGE_SECONDS, MAX_FUTURE_SECONDS,
                           RETAIN_RECEIPTS, AirAck, AirEstimate)


def _body_digest(estimate):
    # Compression settings may change without changing the decoded field.
    value = estimate.model_dump(mode="json", exclude={"field_base64"})
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mount_air_receiver(app, db, lock, authorize_pi, authorize_viewer, *, registrations):
    bindings = {}
    for registration in registrations:
        for cage_id, binding in registration.air_cages.items():
            enclosure_id = str(binding.enclosure_id)
            if enclosure_id in bindings:
                raise ValueError("duplicate air enclosure registration")
            bindings[enclosure_id] = (registration.site_id, registration.gateway_id, cage_id, binding)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS air_latest (
            enclosure_id TEXT PRIMARY KEY,
            body TEXT NOT NULL, body_sha256 TEXT NOT NULL,
            sampled_at TEXT NOT NULL, estimate_id TEXT NOT NULL,
            received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS air_receipts (
            receipt_order INTEGER PRIMARY KEY AUTOINCREMENT,
            enclosure_id TEXT NOT NULL, estimate_id TEXT NOT NULL,
            body_sha256 TEXT NOT NULL,
            UNIQUE(enclosure_id, estimate_id)
        );
    """)

    def check_upload_scope(registration, estimate):
        binding = registration.air_cages.get(estimate.cage_id)
        if ((registration.site_id, registration.gateway_id) != (estimate.site_id, estimate.gateway_id)
                or estimate.cage_id not in registration.cage_ids or binding is None):
            raise HTTPException(403, "air_scope_denied")
        if binding.node_id != estimate.node_id:
            raise HTTPException(403, "air_node_scope_denied")
        if (binding.geometry_revision, binding.placement_revision) != (
                estimate.geometry_revision, estimate.placement_revision):
            raise HTTPException(409, "air_revision_mismatch")
        return str(binding.enclosure_id)

    @app.post(AIR_PATH, response_model=AirAck, tags=["Air estimates"], operation_id="uploadAirEstimate")
    def upload(estimate: AirEstimate, registration=Depends(authorize_pi)):
        enclosure_id = check_upload_scope(registration, estimate)
        digest = _body_digest(estimate)
        estimate_id = str(estimate.estimate_id)
        now = utcnow()
        with lock, db:
            receipt = db.execute("SELECT body_sha256 FROM air_receipts WHERE enclosure_id=? AND estimate_id=?",
                                 (enclosure_id, estimate_id)).fetchone()
            previous = db.execute("SELECT * FROM air_latest WHERE enclosure_id=?", (enclosure_id,)).fetchone()
            if receipt and receipt["body_sha256"] != digest:
                raise HTTPException(409, "air_estimate_conflict")
            if previous and previous["estimate_id"] == estimate_id and previous["body_sha256"] != digest:
                raise HTTPException(409, "air_estimate_conflict")
            if receipt or (previous and previous["estimate_id"] == estimate_id):
                outcome = "duplicate"
            else:
                source_age = (now - estimate.sampled_at).total_seconds()
                generated_age = (now - estimate.generated_at).total_seconds()
                if source_age < -MAX_FUTURE_SECONDS or generated_age < -MAX_FUTURE_SECONDS:
                    raise HTTPException(409, "air_expired_or_future")
                old = AirEstimate.model_validate_json(previous["body"]) if previous else None
                same_scope = old is not None and (
                    old.site_id, old.gateway_id, old.cage_id, old.node_id,
                    old.geometry_revision, old.placement_revision) == (
                    estimate.site_id, estimate.gateway_id, estimate.cage_id, estimate.node_id,
                    estimate.geometry_revision, estimate.placement_revision)
                if same_scope and estimate.sampled_at <= old.sampled_at:
                    outcome = "superseded"
                else:
                    if (not -MAX_FUTURE_SECONDS <= source_age <= MAX_AGE_SECONDS
                            or not -MAX_FUTURE_SECONDS <= generated_age <= MAX_AGE_SECONDS):
                        raise HTTPException(409, "air_expired_or_future")
                    db.execute("INSERT OR REPLACE INTO air_latest VALUES (?, ?, ?, ?, ?, ?)",
                               (enclosure_id, estimate.model_dump_json(), digest,
                                estimate.sampled_at.isoformat(), estimate_id, now.isoformat()))
                    outcome = "stored"
                db.execute("INSERT INTO air_receipts(enclosure_id, estimate_id, body_sha256) VALUES (?, ?, ?)",
                           (enclosure_id, estimate_id, digest))
                db.execute("""DELETE FROM air_receipts WHERE enclosure_id=? AND receipt_order NOT IN
                    (SELECT receipt_order FROM air_receipts WHERE enclosure_id=? ORDER BY receipt_order DESC LIMIT ?)
                    """, (enclosure_id, enclosure_id, RETAIN_RECEIPTS))
        # The transaction has committed before an acceptance response is built.
        return estimate.acknowledgement(outcome)

    @app.get("/v1/enclosures/{enclosure_id}/air", tags=["Air estimates"], operation_id="readAirEstimate")
    def latest(enclosure_id: UUID, registration=Depends(authorize_viewer)):
        binding = bindings.get(str(enclosure_id))
        if binding is None:
            raise HTTPException(404, "air_enclosure_unregistered")
        site_id, gateway_id, cage_id, configured = binding
        if ((registration.site_id, registration.gateway_id) != (site_id, gateway_id)
                or cage_id not in registration.cage_ids):
            raise HTTPException(403, "air_viewer_scope_denied")
        with lock:
            row = db.execute("SELECT * FROM air_latest WHERE enclosure_id=?", (str(enclosure_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "waiting_air_estimate")
        estimate = AirEstimate.model_validate_json(row["body"])
        if (estimate.site_id, estimate.gateway_id, estimate.cage_id, estimate.node_id,
                estimate.geometry_revision, estimate.placement_revision) != (
                site_id, gateway_id, cage_id, configured.node_id,
                configured.geometry_revision, configured.placement_revision):
            raise HTTPException(404, "waiting_current_air_revision")
        now = utcnow()
        age = (now - datetime.fromisoformat(row["received_at"])).total_seconds()
        source_age = (now - estimate.sampled_at).total_seconds()
        fresh = -MAX_FUTURE_SECONDS <= source_age <= MAX_AGE_SECONDS
        values = estimate.field_values()
        if estimate.color_range_c is not None:
            color_range = list(estimate.color_range_c)
        else:
            measured = [sensor.value_c for sensor in estimate.sensors]
            low = math.floor(min(*values, *measured) * 2) / 2
            high = math.ceil(max(*values, *measured) * 2) / 2
            color_range = [low - .5, high + .5] if high - low < 1 else [low, high]
        payload = dict(
            schema_version=1, source_mode="live", site_id=site_id, gateway_id=gateway_id,
            enclosure_id=str(enclosure_id), cage_id=cage_id, node_id=estimate.node_id,
            message_id=str(estimate.source_message_id), source_message_id=str(estimate.source_message_id),
            estimate_id=str(estimate.estimate_id), field_sha256=estimate.field_sha256,
            model_id=estimate.model_id, model_version=estimate.model_version,
            config_sha256=estimate.config_sha256, geometry_revision=estimate.geometry_revision,
            placement_revision=estimate.placement_revision,
            sampled_at=estimate.sampled_at.isoformat(), generated_at=estimate.generated_at.isoformat(),
            received_at_utc=row["received_at"], age_seconds=round(max(0, age), 3),
            source_age_seconds=round(source_age, 3), stale_after_s=MAX_AGE_SECONDS,
            status="live" if fresh else "stale",
            status_reason="accepted_air_estimate" if fresh else "source_measurement_expired_or_clock_mismatch",
            fresh=fresh, held=not fresh, accepted_samples=estimate.source_accepted_samples or 0,
            rejected_samples=0, last_rejection=None, gap_resets=estimate.source_gap_resets,
            dimensions_m=list(estimate.dimensions_m), grid=estimate.grid.model_dump(mode="json"),
            sensors=[dict(sensor.model_dump(mode="json"), sampled_at=estimate.sampled_at.isoformat())
                     for sensor in sorted(estimate.sensors, key=lambda item: item.id)],
            field=dict(method="flow_sensor", values_c=values), baseline=None,
            color_range_c=color_range, field_precision_c=.0001,
            assumptions=["점은 센서 실측값, 공간 색은 Pi가 계산한 추정 온도입니다.",
                         "20 × 20 × 30 cm 사육장과 센서 좌표는 모델 설정이며 기본 위치는 가정입니다.",
                         "순환 흐름과 벽 열교환은 가정이며 물리적 정확도를 검증한 결과가 아닙니다."],
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
