"""Low-resolution scene-motion features, with explicit quality and human review."""
from datetime import timedelta
import hashlib
import math
import os
from pathlib import Path
from statistics import fmean
import subprocess
from uuid import uuid4

from .core import Session, encode, identifier, number, read_json, relative, require, sync_dir, timestamp
from .records import active_labels, jsonl, saved_rows

FEATURE_VERSION = "scene-motion-v1"
IMAGE_BYTES = 64 * 48
BASE_FEATURES = ["motion_mean", "motion_peak", "changed_fraction", "brightness_mean"]


def fingerprint(value):
    return hashlib.sha256(encode(value)).hexdigest()


def save_artifact(path, value):
    path = Path(path)
    require(not path.exists(), "output already exists; choose a new versioned filename")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.partial")
    with temporary.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    # Publish once, including when two independent CLI processes race for this path.
    os.link(temporary, path)
    temporary.unlink()
    sync_dir(path.parent)


def validate_config(config):
    required = {"schema_version", "camera_id", "animal_id", "context", "roi", "window_seconds", "sample_fps", "pixel_delta", "sensors", "max_clock_error_ms"}
    require(isinstance(config, dict) and set(config) == required, "invalid feature config fields")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1, "unsupported feature config")
    for key in ("camera_id", "animal_id", "context"):
        identifier(config[key])
    number(config["window_seconds"], 1, 120)
    number(config["sample_fps"], 1, 4)
    require(type(config["sample_fps"]) is int, "sample_fps must be an integer")
    number(config["pixel_delta"], 1, 255)
    number(config["max_clock_error_ms"], 0, 10000)
    if config["roi"] is not None:
        require(isinstance(config["roi"], list) and len(config["roi"]) == 4, "roi must be [x,y,width,height] fractions")
        x, y, w, h = [number(v, 0, 1) for v in config["roi"]]
        require(w > 0 and h > 0 and x + w <= 1 and y + h <= 1, "ROI exceeds image")
    require(isinstance(config["sensors"], list) and len(config["sensors"]) <= 8, "invalid sensor feature list")
    ids = []
    for sensor in config["sensors"]:
        require(set(sensor) == {"sensor_id", "unit", "max_age_seconds", "geometry_revision", "placement_revision", "scale_floor"}, "invalid sensor feature config")
        ids.append(identifier(sensor["sensor_id"]))
        require(isinstance(sensor["unit"], str) and sensor["unit"], "sensor unit required")
        number(sensor["max_age_seconds"], 0.01, 3600)
        number(sensor["scale_floor"], 1e-9)
    require(len(ids) == len(set(ids)), "duplicate sensor feature")
    return config


def scope_for(session, config):
    cameras = [c for c in session.manifest["config"]["cameras"] if c["camera_id"] == config["camera_id"]]
    require(len(cameras) == 1 and cameras[0]["kind"] == "rgb", "feature extraction requires configured RGB camera")
    animals = session.manifest["config"]["animals"]
    require(len(animals) == 1 and animals[0]["animal_id"] == config["animal_id"], "scene baseline requires one explicitly configured animal; multi-animal tracking is not implemented")
    camera = cameras[0]
    return {"animal_id": config["animal_id"], "species": animals[0]["species"], "camera_id": camera["camera_id"],
            "enclosure_id": camera["enclosure_id"], "placement_revision": camera["placement_revision"],
            "calibration_revision": camera["calibration_revision"], "context": config["context"],
            "identity_method": "configured_single_occupant; not visual identification"}


def decode_frames(session, clip, config):
    path = relative(session.root, clip["media_path"])
    filters = ["setpts=PTS-STARTPTS"]
    if config["roi"] is not None:
        x, y, w, h = config["roi"]
        crop = [int(clip["width"] * w), int(clip["height"] * h), int(clip["width"] * x), int(clip["height"] * y)]
        require(crop[0] >= 2 and crop[1] >= 2, "ROI too small")
        filters.append("crop=" + ":".join(str(v) for v in crop))
    filters += [f"fps={config['sample_fps']}:start_time=0", "scale=64:48", "format=gray"]
    max_frames = math.ceil(clip["duration_seconds"] * config["sample_fps"]) + 1
    command = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-filter_threads", "1",
               "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm,avi", "-i", str(path),
               "-map", "0:v:0", "-an", "-vf", ",".join(filters), "-frames:v", str(max_frames),
               "-threads", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=True,
                            timeout=session.manifest["config"]["storage"]["probe_timeout_seconds"])
    require(not result.stderr.strip(), "decoder reported errors; no feature imputation")
    require(len(result.stdout) % IMAGE_BYTES == 0 and len(result.stdout) <= max_frames * IMAGE_BYTES, "invalid decoded frame payload")
    return [result.stdout[i:i + IMAGE_BYTES] for i in range(0, len(result.stdout), IMAGE_BYTES)]


def review_window(labels, animal_id, start, end):
    overlapping = [r for r in labels if r["animal_id"] in (None, animal_id) and r["start_seconds"] < end and r["end_seconds"] > start]
    if any(r["visibility"] != "visible" for r in overlapping):
        return None, ["human_visibility_incomplete"], []
    reviewed = [r for r in overlapping if r.get("assessment") is not None]
    if not reviewed:
        return None, [], []
    if any(r["certainty"] != "certain" or r.get("assessment") == "uncertain" or r["animal_id"] != animal_id for r in reviewed):
        return None, [], []
    assessments = {r["assessment"] for r in reviewed}
    if len(assessments) != 1:
        return None, ["conflicting_human_assessments"], [r["label_id"] for r in reviewed]
    covered_until = start
    for row in sorted(reviewed, key=lambda r: r["start_seconds"]):
        if row["start_seconds"] > covered_until + 1e-8:
            return None, [], []
        covered_until = max(covered_until, row["end_seconds"])
    if covered_until < end - 1e-8:
        return None, [], []
    return reviewed[0]["assessment"], [], [r["label_id"] for r in reviewed]


def sensor_feature(records, sensor, clip, target, config):
    if target is None:
        return None, None, "capture_time_unknown"
    camera_error = clip["capture_clock"]["accuracy_ms"]
    if camera_error is None:
        return None, None, "camera_clock_accuracy_unknown"
    candidates = []
    for row in records:
        if row["enclosure_id"] != clip["enclosure_id"] or row["observed_at"] is None:
            continue
        readings = [r for r in row["readings"] if r["sensor_id"] == sensor["sensor_id"]]
        if readings:
            observed = timestamp(row["observed_at"])
            if observed <= target:
                candidates.append((observed, row, readings[0]))
    if not candidates:
        return None, None, "sensor_missing"
    latest = max(row[0] for row in candidates)
    newest = [row for row in candidates if row[0] == latest]
    if len(newest) != 1:
        return None, None, "ambiguous_sensor_timestamp"
    observed, row, reading = newest[0]
    record_id = row["record_id"]
    if (target - observed).total_seconds() > sensor["max_age_seconds"]:
        return None, record_id, "sensor_stale"
    error = row["observed_clock"]["accuracy_ms"]
    if error is None or error + camera_error > config["max_clock_error_ms"]:
        return None, record_id, "clock_alignment_unverified"
    if any(row[key] != sensor[key] for key in ("geometry_revision", "placement_revision")):
        return None, record_id, "sensor_revision_mismatch"
    if reading["unit"] != sensor["unit"]:
        return None, record_id, "sensor_unit_mismatch"
    if reading["quality"] != "valid" or reading["value"] is None:
        return None, record_id, "sensor_invalid"
    return reading["value"], record_id, None


def extract_clip(session, clip, config, labels, sensors):
    duration = clip["duration_seconds"]
    require(clip["timeline_available"] and duration is not None, "clip has no reliable relative timeline")
    frames = decode_frames(session, clip, config)
    pts_events = jsonl(relative(session.root, clip["events_path"]))
    timing_issue = any(e["code"] in {"frame_pts_missing", "nonmonotonic_pts", "pts_gap_possible_drop"} for e in pts_events)
    anchor = timestamp(clip["captured_at"])
    rows = []
    window = config["window_seconds"]
    for index in range(math.ceil(duration / window)):
        start, end = index * window, min((index + 1) * window, duration)
        subset = frames[math.ceil(start * config["sample_fps"]):math.ceil(end * config["sample_fps"])]
        assessment, reasons, review_ids = review_window(labels, config["animal_id"], start, end)
        features = {name: None for name in BASE_FEATURES}
        if timing_issue:
            reasons.append("source_timing_anomaly")
        if clip["frame_count"] < math.floor(duration * config["sample_fps"]):
            reasons.append("source_sampling_below_requested_rate")
        if end - start < window - 1e-8:
            reasons.append("partial_window")
        if len(subset) < 2 or len(subset) < math.floor((end - start) * config["sample_fps"]):
            reasons.append("insufficient_frames")
        else:
            brightness = [fmean(frame) / 255 for frame in subset]
            motion, changed = [], []
            for left, right in zip(subset, subset[1:]):
                differences = [abs(a - b) for a, b in zip(left, right)]
                motion.append(fmean(differences) / 255)
                changed.append(sum(d >= config["pixel_delta"] for d in differences) / IMAGE_BYTES)
            features.update(motion_mean=fmean(motion), motion_peak=max(motion), changed_fraction=fmean(changed), brightness_mean=fmean(brightness))
            if min(brightness) < 0.02 or max(brightness) > 0.98:
                reasons.append("exposure_out_of_range")
            if any(abs(a - b) > 0.2 for a, b in zip(brightness, brightness[1:])):
                reasons.append("global_brightness_jump")
        observed_start = anchor + timedelta(seconds=start) if anchor else None
        observed_end = anchor + timedelta(seconds=end) if anchor else None
        sensor_ids = []
        for sensor in config["sensors"]:
            value, record_id, reason = sensor_feature(sensors, sensor, clip, observed_end, config)
            features[f"sensor:{sensor['sensor_id']}"] = value
            if record_id:
                sensor_ids.append(record_id)
            if reason:
                reasons.append(f"{sensor['sensor_id']}:{reason}")
        identity = {"session_id": session.manifest["session_id"], "clip_id": clip["clip_id"],
                    "original_video_id": clip["original_video_id"], "recording_id": clip["recording_id"],
                    "start_seconds": start, "end_seconds": end}
        rows.append({**identity, "row_id": fingerprint([FEATURE_VERSION, config, identity]), "provenance": clip["provenance"],
                     "observed_start": observed_start.isoformat() if observed_start else None,
                     "observed_end": observed_end.isoformat() if observed_end else None,
                     "media_path": clip["media_path"], "features": features, "quality_reasons": sorted(set(reasons)),
                     "human_assessment": assessment, "review_label_ids": review_ids, "sensor_record_ids": sensor_ids})
    return rows


def build_dataset(session_paths, config):
    config = validate_config(config)
    rows, kinds, scopes, ids = [], set(), [], set()
    require(0 < len(session_paths) <= 100, "provide 1 to 100 sessions per feature batch")
    for path in session_paths:
        session = Session(path)
        require(session.manifest["state"] != "active", "stop the session before offline feature extraction")
        require(not session.verify(), "session integrity failed; verify/recover before feature extraction")
        require(session.manifest["session_id"] not in ids, "duplicate session, possibly a relocated copy")
        ids.add(session.manifest["session_id"])
        kinds.add(session.manifest["config"]["dataset_kind"])
        scopes.append(scope_for(session, config))
        require(scopes[-1] == scopes[0], "animal/camera/revision/context scope changed; build a separate dataset")
        labels = active_labels(session)
        sensors = saved_rows(session, "sensors")
        for clip in session.items("clip"):
            if clip["camera_id"] != config["camera_id"]:
                continue
            require(clip["animal_ids"] == [config["animal_id"]], "clip animal identity differs from configuration")
            rows.extend(extract_clip(session, clip, config, [r for r in labels if r["clip_id"] == clip["clip_id"]], sensors))
            require(len(rows) <= 10000, "feature batch exceeds 10000 windows; split batches")
    require(len(kinds) == 1, "real and test data cannot be mixed")
    dataset = {"schema_version": 1, "kind": "behavior_features", "feature_version": FEATURE_VERSION,
               "dataset_kind": kinds.pop(), "config": config, "scope": scopes[0],
               "feature_names": BASE_FEATURES + [f"sensor:{s['sensor_id']}" for s in config["sensors"]], "rows": rows}
    dataset["dataset_id"] = fingerprint(dataset)
    return dataset


def validate_dataset(dataset):
    require(dataset.get("schema_version") == 1 and dataset.get("kind") == "behavior_features", "unsupported feature dataset")
    require(dataset["feature_version"] == FEATURE_VERSION, "feature version mismatch")
    require(dataset["dataset_id"] == fingerprint({k: v for k, v in dataset.items() if k != "dataset_id"}), "dataset fingerprint mismatch")
    config = validate_config(dataset["config"])
    expected = BASE_FEATURES + [f"sensor:{s['sensor_id']}" for s in config["sensors"]]
    require(dataset["feature_names"] == expected and dataset["dataset_kind"] in {"real", "test"}, "invalid dataset features/provenance")
    require(isinstance(dataset["rows"], list) and len(dataset["rows"]) <= 10000, "invalid row count")
    seen = set()
    intervals = {}
    originals = set()
    for row in dataset["rows"]:
        require(row["row_id"] not in seen, "duplicate feature row")
        seen.add(row["row_id"])
        for key in ("session_id", "clip_id", "original_video_id", "recording_id"):
            identifier(row[key])
        number(row["start_seconds"])
        number(row["end_seconds"])
        require(row["end_seconds"] > row["start_seconds"], "invalid feature window")
        original_window = (row["original_video_id"], row["start_seconds"], row["end_seconds"])
        require(original_window not in originals, "duplicate original video window, possibly reimported")
        originals.add(original_window)
        intervals.setdefault((row["session_id"], row["clip_id"]), []).append((row["start_seconds"], row["end_seconds"]))
        require(row["human_assessment"] in {None, "normal", "anomaly"}, "invalid human assessment")
        require(isinstance(row["review_label_ids"], list), "invalid review provenance")
        require(row["human_assessment"] is None or row["review_label_ids"], "human assessment requires source label IDs")
        require(isinstance(row["quality_reasons"], list) and all(isinstance(v, str) for v in row["quality_reasons"]), "invalid quality reasons")
        require(set(row["features"]) == set(expected), "feature shape mismatch")
        for key, value in row["features"].items():
            if value is not None:
                number(value, 0 if key in BASE_FEATURES else -1e12, 1 if key in BASE_FEATURES else 1e12)
        timestamps = [timestamp(row[k]) for k in ("observed_start", "observed_end")]
        require((timestamps[0] is None) == (timestamps[1] is None), "incomplete window timestamp")
        if timestamps[0] is not None:
            require(timestamps[1] > timestamps[0], "nonmonotonic window timestamp")
        allowed = {"real_camera"} if dataset["dataset_kind"] == "real" else {"synthetic_test", "replay_test"}
        require(row["provenance"] in allowed, "mixed row provenance")
    for windows in intervals.values():
        windows.sort()
        require(all(left[1] <= right[0] for left, right in zip(windows, windows[1:])), "overlapping feature windows")
    return dataset


def load_dataset(path):
    return validate_dataset(read_json(Path(path), 32 * 1024**2))
