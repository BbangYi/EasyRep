"""Independent latest-air protocol, durable ACKs and scoped browser projection."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
import struct
from uuid import UUID, uuid4
import zlib

from fastapi.testclient import TestClient
import pytest

from habitat.saas import air_receiver
from habitat.saas.air_contract import (AIR_PATH, FIELD_BYTES, FIELD_VALUES, MAX_AIR_BODY,
                                      RETAIN_RECEIPTS, AirEstimate, decode_field, encode_field)
from habitat_gateway.saas_reference import Registration, create_receiver

NOW = datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)
ENCLOSURE = UUID("507a8d53-a6b1-49d7-aab3-1becba7a0451")
OTHER_ENCLOSURE = UUID("70000000-0000-0000-0000-000000000002")
PI_TOKEN = "test-air-pi-token-of-more-than-thirty-two-characters"
VIEW_TOKEN = "test-air-view-token-of-more-than-thirty-two-characters"
PI_HEADERS = {"Authorization": "Bearer " + PI_TOKEN}
VIEW_HEADERS = {"Authorization": "Bearer " + VIEW_TOKEN}
VIEW_PATH = f"/v1/enclosures/{ENCLOSURE}/air"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(air_receiver, "utcnow", lambda: clock[0])
    return clock


def registration(**updates):
    return Registration.model_validate(dict(
        site_id="STORE-001", gateway_id="PI-001", cage_ids=["CAGE-001", "CAGE-002"], token_env="PI",
        air_cages={
            "CAGE-001": dict(node_id="ESP-001", enclosure_id=str(ENCLOSURE), geometry_revision=1, placement_revision=1),
            "CAGE-002": dict(node_id="ESP-002", enclosure_id=str(OTHER_ENCLOSURE), geometry_revision=1, placement_revision=1),
        },
    ) | updates)


def app(database=":memory:", *, pi=None, viewer=None):
    pi = registration() if pi is None else pi
    # Viewers use the existing site/gateway/cage ACL, not a caller-supplied UUID mapping.
    viewer = registration(token_env="VIEW", air_cages={}) if viewer is None else viewer
    return create_receiver(database, [pi], viewers=[viewer], environ={"PI": PI_TOKEN, "VIEW": VIEW_TOKEN})


def estimate(**updates):
    encoded, digest = encode_field([23.25] * FIELD_VALUES)
    value = dict(
        estimate_id=str(uuid4()), source_message_id=str(uuid4()), site_id="STORE-001", gateway_id="PI-001",
        cage_id="CAGE-001", node_id="ESP-001", sampled_at=NOW - timedelta(seconds=2), generated_at=NOW,
        geometry_revision=1, placement_revision=1, config_sha256="c" * 64,
        sensors=[dict(id=key, label=key, xyz_m=xyz, value_c=value) for key, xyz, value in (
            ("T1", [.1, .1, .28], 23.25), ("T2", [.02, .02, .08], 23.), ("T3", [.18, .18, .08], 24.))],
        color_range_c=[20., 30.], source_accepted_samples=71, source_gap_resets=2,
        field_base64=encoded, field_sha256=digest,
    )
    return AirEstimate.model_validate(value | updates)


def send(client, item):
    payload = item.model_dump(mode="json") if isinstance(item, AirEstimate) else item
    return client.post(AIR_PATH, json=payload, headers=PI_HEADERS)


def test_exact_ack_durable_field_uuid_mapping_and_restart(tmp_path):
    item = estimate()
    database = tmp_path / "receiver.sqlite3"
    for expected in ("stored", "duplicate"):
        with TestClient(app(database)) as client:
            response = send(client, item)
            assert response.status_code == 200
            assert response.json() == item.acknowledgement(expected).model_dump(mode="json")
            # An independent connection must see the commit before the ACK is returned.
            with sqlite3.connect(database) as observer:
                assert observer.execute("SELECT estimate_id FROM air_latest").fetchone()[0] == str(item.estimate_id)
            response = client.get(VIEW_PATH, headers=VIEW_HEADERS)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            snap = response.json()
            assert snap["enclosure_id"] == str(ENCLOSURE)
            assert (snap["site_id"], snap["gateway_id"], snap["cage_id"], snap["node_id"]) == (
                item.site_id, item.gateway_id, item.cage_id, item.node_id)
            assert snap["message_id"] == str(item.source_message_id)
            assert snap["estimate_id"] == str(item.estimate_id)
            assert snap["field_sha256"] == item.field_sha256
            assert snap["model_id"] == item.model_id and snap["model_version"] == item.model_version
            assert snap["field"]["values_c"] == item.field_values()
            assert snap["baseline"] is None
            assert snap["color_range_c"] == [20., 30.]
            assert snap["accepted_samples"] == 71 and snap["gap_resets"] == 2
            assert snap["fresh"] and not snap["held"] and snap["status"] == "live"
            assert client.get(f"/v1/enclosures/{OTHER_ENCLOSURE}/air", headers=VIEW_HEADERS).status_code == 404
            assert client.app.state.db.execute("SELECT COUNT(*) FROM air_latest").fetchone()[0] == 1
            assert client.app.state.db.execute("SELECT COUNT(*) FROM air_receipts").fetchone()[0] == 1
            assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_events").fetchone()[0] == 0
            assert client.app.state.db.execute("SELECT COUNT(*) FROM edge_gateways").fetchone()[0] == 0


def test_pi_credentials_cannot_read_view_and_viewer_cannot_publish():
    item = estimate().model_dump(mode="json")
    with TestClient(app()) as client:
        for headers in ({}, VIEW_HEADERS):
            assert client.post(AIR_PATH, json=item, headers=headers).status_code == 401
        for headers in ({}, PI_HEADERS):
            assert client.get(VIEW_PATH, headers=headers).status_code == 401
        assert client.get(f"/v1/enclosures/{uuid4()}/air", headers=VIEW_HEADERS).status_code == 404


@pytest.mark.parametrize("changes,status", [
    ({"site_id": "OTHER"}, 403), ({"gateway_id": "OTHER"}, 403),
    ({"cage_id": "OTHER"}, 403), ({"node_id": "OTHER"}, 403),
    ({"geometry_revision": 2}, 409), ({"placement_revision": 2}, 409),
    ({"sampled_at": (NOW-timedelta(seconds=31)).isoformat()}, 409),
    ({"sampled_at": (NOW+timedelta(seconds=6)).isoformat(), "generated_at": (NOW+timedelta(seconds=6)).isoformat()}, 409),
    ({"generated_at": (NOW+timedelta(seconds=6)).isoformat()}, 409),
    ({"schema_version": True}, 422), ({"geometry_revision": True}, 422),
    ({"source_message_id": "not-a-uuid"}, 422), ({"config_sha256": "bad"}, 422),
    ({"model_id": "other-model"}, 422), ({"dimensions_m": [.3, .2, .3]}, 422),
    ({"sampled_at": "2026-10-25T02:00:00"}, 422),
    ({"enclosure_id": str(ENCLOSURE)}, 422),
    ({"color_range_c": [25., 26.]}, 422), ({"color_range_c": [23.25, 23.25]}, 422),
    ({"source_accepted_samples": -1}, 422), ({"source_gap_resets": True}, 422),
])
def test_scope_provenance_and_freshness_reject_before_storage(changes, status):
    with TestClient(app()) as client:
        assert send(client, estimate().model_dump(mode="json") | changes).status_code == status
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_latest").fetchone()[0] == 0
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_receipts").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["site", "gateway", "cage"])
def test_viewer_scope_cannot_cross_registered_enclosure(change):
    updates = {"token_env": "VIEW", "air_cages": {}}
    updates.update({"site": {"site_id": "OTHER"}, "gateway": {"gateway_id": "OTHER"},
                    "cage": {"cage_ids": ["CAGE-002"]}}[change])
    with TestClient(app(viewer=registration(**updates))) as client:
        assert send(client, estimate()).status_code == 200
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).status_code == 403


def test_explicit_air_registration_required_and_duplicate_uuid_rejected():
    with TestClient(app(pi=registration(air_cages={}))) as client:
        assert send(client, estimate()).status_code == 403
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).status_code == 404
    duplicated = registration().model_dump(mode="json")
    duplicated["air_cages"]["CAGE-002"]["enclosure_id"] = str(ENCLOSURE)
    with pytest.raises(ValueError):
        Registration.model_validate(duplicated)
    other = registration(site_id="STORE-OTHER", gateway_id="PI-OTHER", token_env="OTHER")
    with pytest.raises(ValueError, match="duplicate air enclosure ownership"):
        create_receiver(":memory:", [registration(), other], environ={"PI": PI_TOKEN, "OTHER": "x" * 40})


def test_new_revision_hides_old_frame_until_matching_estimate(tmp_path):
    database = tmp_path / "receiver.sqlite3"
    with TestClient(app(database)) as client:
        assert send(client, estimate()).status_code == 200
    cfg = registration().model_dump(mode="json")
    cfg["air_cages"]["CAGE-001"]["placement_revision"] = 2
    with TestClient(app(database, pi=Registration.model_validate(cfg))) as client:
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).status_code == 404
        assert send(client, estimate()).status_code == 409
        assert send(client, estimate(placement_revision=2)).json()["outcome"] == "stored"
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).json()["placement_revision"] == 2


def test_duplicate_and_reads_never_refresh_source_or_receipt_age(fixed_clock):
    item = estimate()
    with TestClient(app()) as client:
        assert send(client, item).status_code == 200
        initial = client.get(VIEW_PATH, headers=VIEW_HEADERS).json()
        fixed_clock[0] = NOW + timedelta(seconds=29)
        assert send(client, item).json()["outcome"] == "duplicate"
        stale = client.get(VIEW_PATH, headers=VIEW_HEADERS).json()
        assert stale["status"] == "stale" and stale["held"] and not stale["fresh"]
        assert stale["sampled_at"] == initial["sampled_at"]
        assert stale["received_at_utc"] == initial["received_at_utc"]
        assert stale["source_age_seconds"] == 31 and stale["age_seconds"] == 29
        fixed_clock[0] += timedelta(minutes=1)
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).json()["source_age_seconds"] == 91


def test_conflicting_id_and_out_of_order_estimates_preserve_latest():
    item = estimate()
    with TestClient(app()) as client:
        assert send(client, item).json()["outcome"] == "stored"
        changed = item.model_dump(mode="json") | {"config_sha256": "d" * 64}
        assert send(client, changed).status_code == 409
        older = estimate(sampled_at=NOW-timedelta(seconds=5))
        assert send(client, older).json()["outcome"] == "superseded"
        assert send(client, older).json()["outcome"] == "duplicate"
        assert send(client, estimate(sampled_at=item.sampled_at)).json()["outcome"] == "superseded"
        latest = client.get(VIEW_PATH, headers=VIEW_HEADERS).json()
        assert latest["estimate_id"] == str(item.estimate_id)
        assert latest["accepted_samples"] == item.source_accepted_samples
        assert send(client, older.model_dump(mode="json") | {"config_sha256": "e" * 64}).status_code == 409


def test_unknown_older_source_with_future_generation_is_rejected_before_superseding():
    item = estimate()
    with TestClient(app()) as client:
        assert send(client, item).json()["outcome"] == "stored"
        invalid = estimate(sampled_at=NOW-timedelta(seconds=5), generated_at=NOW+timedelta(seconds=6))
        response = send(client, invalid)
        assert response.status_code == 409
        assert response.json()["detail"] == "air_expired_or_future"
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_receipts").fetchone()[0] == 1
        latest = client.get(VIEW_PATH, headers=VIEW_HEADERS).json()
        assert latest["estimate_id"] == str(item.estimate_id)


def test_storage_failure_rolls_back_and_does_not_acknowledge():
    with TestClient(app()) as client:
        db = client.app.state.db
        db.execute("""CREATE TRIGGER reject_air BEFORE INSERT ON air_latest
                      BEGIN SELECT RAISE(ABORT, 'fixture persistence failure'); END""")
        response = send(client, estimate())
        assert response.status_code == 503
        assert "estimate_id" not in response.json()
        assert db.execute("SELECT COUNT(*) FROM air_latest").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM air_receipts").fetchone()[0] == 0


@pytest.mark.parametrize("case", ["bad_base64", "truncated", "trailing", "concatenated", "short", "bomb", "nan", "range", "digest"])
def test_compressed_fields_are_framed_bounded_finite_and_digest_checked(case):
    item = estimate().model_dump(mode="json")
    data = struct.pack(f"<{FIELD_VALUES}f", *([23.25] * FIELD_VALUES))
    compressed = zlib.compress(data)
    if case == "bad_base64": item["field_base64"] = "!"
    if case == "truncated": compressed = compressed[:-1]
    if case == "trailing": compressed += b"trailing"
    if case == "concatenated": compressed += zlib.compress(data)
    if case == "short": compressed = zlib.compress(data[:-4])
    if case == "bomb": compressed = zlib.compress(bytes(FIELD_BYTES * 100))
    if case in ("nan", "range"):
        data = struct.pack("<f", float("nan") if case == "nan" else 126.) + data[4:]
        item["field_sha256"] = hashlib.sha256(data).hexdigest()
        compressed = zlib.compress(data)
    if case == "digest": item["field_sha256"] = "0" * 64
    if case != "bad_base64": item["field_base64"] = base64.b64encode(compressed).decode()
    with TestClient(app()) as client:
        assert send(client, item).status_code == 422
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_latest").fetchone()[0] == 0


def test_encoder_shape_and_sensor_contracts():
    for values in ([1.] * 10, [True] * FIELD_VALUES, [float("inf")] * FIELD_VALUES):
        with pytest.raises(ValueError):
            encode_field(values)
    payload = estimate().model_dump(mode="json")
    payload["sensors"][0]["xyz_m"] = [.3, .1, .1]
    with pytest.raises(ValueError):
        AirEstimate.model_validate(payload)
    payload = estimate().model_dump(mode="json")
    payload["sensors"][1] = dict(payload["sensors"][0])
    with pytest.raises(ValueError):
        AirEstimate.model_validate(payload)
    with pytest.raises(ValueError):
        decode_field("", "0" * 64)


def test_body_limit_applies_to_chunked_uploads():
    with TestClient(app()) as client:
        response = client.post(AIR_PATH, headers=PI_HEADERS,
            content=(b"x" * 1024 for _ in range(MAX_AIR_BODY // 1024 + 1)))
        assert response.status_code == 413


def test_latest_storage_and_recent_receipts_are_bounded(fixed_clock):
    first = estimate()
    with TestClient(app()) as client:
        assert send(client, first).status_code == 200
        for i in range(1, RETAIN_RECEIPTS + 2):
            fixed_clock[0] = NOW + timedelta(seconds=i)
            item = estimate(sampled_at=fixed_clock[0]-timedelta(seconds=2), generated_at=fixed_clock[0])
            assert send(client, item).json()["outcome"] == "stored"
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_latest").fetchone()[0] == 1
        assert client.app.state.db.execute("SELECT COUNT(*) FROM air_receipts").fetchone()[0] == RETAIN_RECEIPTS
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).json()["estimate_id"] == str(item.estimate_id)
        # An evicted old receipt is not a historical duplicate claim. Its sample
        # is obsolete and cannot replace the latest field or refresh freshness.
        assert send(client, first).json()["outcome"] == "superseded"
        assert client.get(VIEW_PATH, headers=VIEW_HEADERS).json()["estimate_id"] == str(item.estimate_id)
