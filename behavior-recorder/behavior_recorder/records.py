"""Explicit observations and human labels; absence never means rest or sleep."""
import csv
import hashlib
import json
import os

from .core import clock, encode, identifier, now, number, relative, require, timestamp
from .media import camera_for, validate_origin


def jsonl(path):
    require(path.stat().st_size <= 8 * 1024**2, "JSONL batch exceeds 8 MiB; split into smaller batches")
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    require(len(rows) <= 10000 and all(isinstance(r, dict) for r in rows), "invalid JSONL batch")
    # Reject NaN even in extra raw fields.
    encode(rows)
    return rows


def saved_rows(session, kind):
    rows = []
    for entry in session.items(kind):
        rows.extend(jsonl(relative(session.root, entry["rows_path"])))
    return rows


def save_rows(session, kind, rows):
    session.ready()
    key = "label_id" if kind == "labels" else "record_id"
    stored = {r[key]: r for r in saved_rows(session, kind)}
    pending = []
    for row in rows:
        identifier(row[key])
        if row[key] in stored:
            require(encode(stored[row[key]]) == encode(row), f"{kind} ID conflict")
        else:
            pending.append(row)
            stored[row[key]] = row
    if not pending:
        return {"added": 0}
    data = b"".join(encode(r) for r in pending)
    session.space(len(data) + len(encode(session.manifest)) + 4096)
    folder = session.begin()
    path = folder / f"{kind}.jsonl"
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    session.commit(folder, kind, {"rows_path": f"entries/{folder.name}/{path.name}", "count": len(pending), "imported_at": now()})
    return {"added": len(pending)}


def validate_sensor(session, row):
    required = {"record_id", "enclosure_id", "observed_at", "received_at", "observed_clock", "received_clock",
                "source", "geometry_revision", "placement_revision", "readings"}
    require(required <= row.keys(), "missing sensor fields")
    identifier(row["record_id"])
    require(row["enclosure_id"] in {c["enclosure_id"] for c in session.manifest["config"]["cameras"]}, "unknown sensor enclosure")
    for key in ("observed_at", "received_at"):
        timestamp(row[key])
    clock(row["observed_clock"])
    clock(row["received_clock"])
    require(row["source"] in {"sensor", "simulation"}, "invalid sensor source")
    require((row["source"] == "sensor") == (session.manifest["config"]["dataset_kind"] == "real"), "sensor source does not match dataset_kind")
    require(isinstance(row["readings"], list) and 0 < len(row["readings"]) <= 64, "sensor readings required")
    ids = []
    for reading in row["readings"]:
        require(set(reading) == {"sensor_id", "unit", "value", "quality"}, "invalid reading fields")
        ids.append(identifier(reading["sensor_id"]))
        require(isinstance(reading["unit"], str) and 0 < len(reading["unit"]) <= 64, "sensor unit required")
        require(reading["quality"] in {"valid", "invalid", "crc_error", "disconnected", "missing", "unknown"}, "invalid sensor quality")
        if reading["quality"] == "valid":
            number(reading["value"], -1e12)
        else:
            require(reading["value"] is None, "non-valid readings must have value=null")
    require(len(ids) == len(set(ids)), "duplicate sensor ID")


def habitat_rows(rows, units, enclosure_id):
    result = []
    for event in rows:
        require(event.get("kind") == "telemetry.recorded", "only telemetry.recorded records supported")
        body = event["payload"]
        require(set(body["readings"]) <= units.keys(), "unit mapping missing; units cannot be inferred")
        result.append({"record_id": event["id"], "enclosure_id": enclosure_id,
                       "observed_at": body["sampled_at"], "received_at": body.get("received_at"),
                       "server_received_at": event.get("serverReceivedAt"),
                       "observed_clock": {"source": "unknown", "accuracy_ms": None},
                       "received_clock": {"source": "unknown", "accuracy_ms": None},
                       "source": body["data_source"], "geometry_revision": body["geometry_revision"],
                       "placement_revision": body["placement_revision"],
                       "readings": [{"sensor_id": k, "unit": units[k], **v} for k, v in body["readings"].items()],
                       "raw_habitat_record": event})
    return result


def import_sensors(session, rows):
    for row in rows:
        validate_sensor(session, row)
    return save_rows(session, "sensors", rows)


def import_thermal(session, rows):
    for row in rows:
        required = {"record_id", "camera_id", "observed_at", "received_at", "capture_clock", "provenance", "unit",
                    "placement_revision", "calibration_revision", "calibration", "values"}
        require(required <= row.keys(), "missing thermal fields")
        camera = camera_for(session, row["camera_id"])
        require(camera["kind"] == "thermal_numeric", "color video is not measured temperature")
        validate_origin(session, row["provenance"])
        timestamp(row["observed_at"])
        timestamp(row["received_at"])
        clock(row["capture_clock"])
        for key in ("placement_revision", "calibration_revision"):
            require(row[key] == camera[key], f"thermal {key} differs from camera snapshot")
        require(row["unit"] in {"degC", "K", "raw_count"}, "preserve raw_count, degC or K; no automatic conversion")
        require(row["calibration"] is None or isinstance(row["calibration"], dict), "calibration must be object or null")
        values = row["values"]
        require(isinstance(values, list) and 0 < len(values) <= 512, "invalid thermal height")
        require(isinstance(values[0], list) and 0 < len(values[0]) <= 640, "invalid thermal width")
        for line in values:
            require(isinstance(line, list) and len(line) == len(values[0]), "thermal array must be rectangular")
            for value in line:
                if value is not None:
                    number(value, -1e12)
    return save_rows(session, "thermal", rows)


def validate_label(session, row):
    required = {"label_id", "clip_id", "animal_id", "start_seconds", "end_seconds", "behavior", "visibility",
                "certainty", "annotator", "note", "supersedes"}
    require(required <= row.keys(), "missing label fields")
    require(row.get("assessment") in {None, "normal", "anomaly", "uncertain"}, "invalid human assessment")
    clip = session.clip(row["clip_id"])
    require(clip["timeline_available"], "clip timing is incomplete; cannot attach timed labels")
    require(row["animal_id"] is None or row["animal_id"] in clip["animal_ids"], "unknown animal ID")
    number(row["start_seconds"])
    number(row["end_seconds"])
    require(0 <= row["start_seconds"] <= row["end_seconds"] <= clip["duration_seconds"] + 1e-6, "label range outside clip")
    require(row["visibility"] in {"visible", "partial", "unobservable"}, "invalid visibility")
    require(row["certainty"] in {"certain", "uncertain"}, "invalid certainty")
    require(row["behavior"] is None or (isinstance(row["behavior"], str) and 0 < len(row["behavior"]) <= 128), "invalid behavior")
    require(row["visibility"] != "unobservable" or row["behavior"] is None, "unobservable behavior must be null")
    require(isinstance(row["annotator"], str) and 0 < len(row["annotator"]) <= 128, "annotator required")
    require(isinstance(row["note"], str) and len(row["note"]) <= 2048, "invalid label note")


def import_labels(session, rows):
    existing = {r["label_id"]: r for r in saved_rows(session, "labels")}
    replaced = {r["supersedes"] for r in existing.values() if r["supersedes"]}
    for row in rows:
        validate_label(session, row)
        if row["label_id"] in existing:
            require(encode(existing[row["label_id"]]) == encode(row), "labels ID conflict")
            continue
        previous = row["supersedes"]
        if previous:
            require(previous in existing and previous not in replaced, "supersedes must reference one active label")
            require(existing[previous]["clip_id"] == row["clip_id"], "replacement cannot change clip")
            replaced.add(previous)
        existing[row["label_id"]] = row
    return save_rows(session, "labels", rows)


def active_labels(session):
    rows = saved_rows(session, "labels")
    superseded = {row["supersedes"] for row in rows if row["supersedes"]}
    return [row for row in rows if row["label_id"] not in superseded]


def boris_labels(path, clip_id, animal_id, annotator, visibility, certainty):
    # One observation / one media file / zero offset only; reject ambiguous concatenations.
    require(path.stat().st_size <= 8 * 1024**2, "BORIS export exceeds size limit")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"Observation id", "Subject", "Behavior", "Start (s)", "Stop (s)", "Behavior type"}
        require(required <= set(reader.fieldnames or []), "expected BORIS aggregated TSV headers (see README)")
        source = list(reader)
    require(len({row["Observation id"] for row in source}) <= 1 and len({row["Subject"] for row in source}) <= 1, "select one BORIS observation and subject")
    require(len({row.get("Media file name", "") for row in source}) <= 1, "select one BORIS media file")
    result = []
    for index, row in enumerate(source):
        require(row["Behavior type"] in {"STATE", "POINT"}, "unsupported BORIS behavior type")
        start = float(row["Start (s)"])
        end = float(row["Stop (s)"]) if row["Behavior type"] == "STATE" else start
        fingerprint = hashlib.sha256(encode([row, index, clip_id, animal_id, annotator, visibility, certainty])).hexdigest()
        result.append({"label_id": f"boris:{fingerprint}", "clip_id": clip_id, "animal_id": animal_id,
                       "start_seconds": start, "end_seconds": end, "behavior": row["Behavior"] if visibility != "unobservable" else None,
                       "visibility": visibility, "certainty": certainty, "annotator": annotator,
                       "note": "BORIS import; visibility and certainty provided by operator", "supersedes": None,
                       "raw_boris_row": row})
    return result
