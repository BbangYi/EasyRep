"""Index explicit local appearance artifacts; no pixels, predictions or control."""
import argparse
from collections import Counter
from datetime import timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from .analysis_features import fingerprint, save_artifact
from .appearance import validate_metadata
from .core import RecorderError, identifier, now, read_json, relative, require, timestamp

IDENTITY = ("dataset_kind", "animal_id", "species", "enclosure_id")
ARTIFACT_LIMIT = 64 * 1024


def load_artifact(path):
    with path.open("rb") as stream:
        content = stream.read(ARTIFACT_LIMIT + 1)
    require(len(content) <= ARTIFACT_LIMIT, "appearance artifact exceeds 64 KiB")

    def reject_constant(value):
        raise RecorderError("invalid JSON number: " + value)

    value = json.loads(content, parse_constant=reject_constant)
    return value, hashlib.sha256(content).hexdigest()


def validate_artifact(artifact):
    require(isinstance(artifact, dict) and set(artifact) == {
        "schema_version", "feature_version", "created_at", "metadata", "metadata_sha256",
        "features", "comparison_group", "files", "reasons", "shedding_prediction",
        "actuation_allowed", "evidence", "status"}, "invalid appearance artifact fields")
    require(type(artifact["schema_version"]) is int and artifact["schema_version"] == 1
            and artifact["feature_version"] == "reviewed-srgb-v1", "unsupported appearance artifact")
    require(timestamp(artifact["created_at"]) is not None, "artifact creation time required")
    require(artifact["shedding_prediction"] is None and artifact["actuation_allowed"] is False,
            "only collection artifacts without predictions or actuation are accepted")
    metadata = artifact["metadata"]
    reasons = validate_metadata(metadata)
    require(artifact["metadata_sha256"] == fingerprint(metadata), "metadata fingerprint mismatch")
    require(artifact["reasons"] == reasons, "exclusion reasons disagree with metadata")
    if metadata["kind"] == "shedding_event":
        require(artifact["status"] == "human_event_recorded" and artifact["files"] == {}
                and artifact["features"] is None and artifact["comparison_group"] is None,
                "invalid human event artifact")
        return metadata, reasons
    require(artifact["status"] == ("excluded" if reasons else "measured"),
            "color status disagrees with metadata")
    files = artifact["files"]
    require(isinstance(files, dict) and set(files) == {"image", "mask"}, "image/mask provenance required")
    for kind in ("image", "mask"):
        item = files[kind]
        require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}, "invalid media provenance")
        require(item["path"] == metadata[kind], "media provenance path mismatch")
        require(type(item["bytes"]) is int and 0 < item["bytes"] <= 16 * 1024**2, "invalid media byte count")
        require(isinstance(item["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                "invalid media fingerprint")
    if reasons:
        require(artifact["features"] is None and artifact["comparison_group"] is None,
                "excluded observation cannot supply features")
    else:
        expected = fingerprint({key: metadata[key] for key in (*IDENTITY, "body_region", "capture")})
        require(isinstance(artifact["features"], dict) and bool(artifact["features"])
                and artifact["comparison_group"] == expected, "invalid measured observation group/features")
    return metadata, reasons


def build_series(manifest_path):
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path, limit=ARTIFACT_LIMIT)
    require(isinstance(manifest, dict) and set(manifest) == {
        "schema_version", "kind", *IDENTITY, "records"}, "invalid series manifest fields")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["kind"] == "appearance_series", "unsupported series manifest")
    require(manifest["dataset_kind"] in {"test", "real"}, "dataset_kind must be test or real")
    require(manifest["species"] in {"crested_gecko", "leopard_gecko"}, "confirmed supported species required")
    identifier(manifest["animal_id"])
    identifier(manifest["enclosure_id"])
    paths = manifest["records"]
    require(isinstance(paths, list) and len(paths) <= 512, "records must be a list of at most 512 artifact paths")
    seen_paths, seen_ids, seen_frames = set(), set(), set()
    records, groups, days = [], {}, set()
    counts = {key: 0 for key in ("records", "measured", "excluded", "started", "completed", "uncertain")}
    excluded_reasons = Counter()
    for name in paths:
        path = relative(manifest_path.parent, name)
        require(path not in seen_paths, "duplicate artifact path")
        seen_paths.add(path)
        artifact, digest = load_artifact(path)
        metadata, reasons = validate_artifact(artifact)
        require(all(metadata[key] == manifest[key] for key in IDENTITY), "record does not belong to this series")
        record_id = metadata["record_id"]
        require(record_id not in seen_ids, "duplicate record_id")
        seen_ids.add(record_id)
        entry = {"record_id": record_id, "kind": metadata["kind"], "artifact": name,
                 "artifact_sha256": digest, "status": artifact["status"], "reasons": reasons}
        if metadata["kind"] == "color_observation":
            frame_key = (artifact["files"]["image"]["sha256"], metadata["body_region"])
            require(frame_key not in seen_frames, "same image/body region repeated under another record")
            seen_frames.add(frame_key)
            entry.update(observed_at=metadata["observed_at"], comparison_group=artifact["comparison_group"])
            counts[artifact["status"]] += 1
            excluded_reasons.update(reasons)
        else:
            entry.update(stage=metadata["stage"], earliest_at=metadata["earliest_at"], latest_at=metadata["latest_at"])
            counts[metadata["stage"]] += 1
        records.append(entry)
    records.sort(key=lambda row: (timestamp(row.get("observed_at", row.get("earliest_at"))), row["record_id"]))
    for row in records:
        if row["status"] == "measured":
            groups.setdefault(row["comparison_group"], []).append(row["record_id"])
            days.add(timestamp(row["observed_at"]).astimezone(timezone.utc).date().isoformat())
    counts["records"] = len(records)
    missing = [message for key, message in (
        ("measured", "no_measured_color_observations"), ("started", "no_confirmed_shedding_start"),
        ("completed", "no_confirmed_shedding_completion")) if not counts[key]]
    return {"schema_version": 1, "kind": "appearance_series_report", "created_at": now(),
            "identity": {key: manifest[key] for key in IDENTITY}, "manifest_sha256": fingerprint(manifest),
            "counts": counts, "records": records, "comparison_groups": groups,
            "measured_observation_days_utc": sorted(days), "excluded_reasons": dict(excluded_reasons),
            "missing_evidence": missing, "cycle_pairing": "not_performed", "training_readiness": "not_assessed",
            "shedding_prediction": None, "actuation_allowed": False,
            "evidence": "Structural checks of operator-declared collection artifacts only. Media and feature values "
                        "are not reverified. Event counts are not completed cycles. Unobserved periods are not negatives. "
                        "Sensor alignment, cycle/time/animal splits and biological validation remain separate."}


def write_series(manifest_path, output_path):
    require(not Path(output_path).exists(), "output already exists; choose a new versioned filename")
    report = build_series(manifest_path)
    save_artifact(output_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize one animal's explicit appearance records; no predictions or control")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = write_series(args.manifest, args.output)
        print(json.dumps({"output": str(args.output.resolve()), "counts": result["counts"],
                          "missing_evidence": result["missing_evidence"], "actuation_allowed": False}, ensure_ascii=False))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
