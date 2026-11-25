"""Time-weighted observations and reviewed, context-matched reference comparisons."""
import copy
from datetime import timedelta
import math
from statistics import median

from .analysis_features import fingerprint
from .core import RecorderError, number, require, timestamp

VERSION = "tracked-behavior-v2"
FLOORS = {"speed": 0.002, "moving_fraction": 0.05, "x_span": 0.02, "y_span": 0.02}


def window_observations(summary, observations, context, *, window_seconds=30):
    """Only intervals with two trusted observations contribute; gaps stay unknown."""
    number(window_seconds, 1, 120)
    duration = number(summary["source"]["duration_seconds"], 0.001, 600)
    require(isinstance(context, dict), "context must be an object")
    capture_time = timestamp(context.get("captured_at"))
    for key in ("animal_id", "camera_revision", "conditions"):
        require(isinstance(context.get(key, ""), str) and len(context.get(key, "")) <= 160, "invalid context")
    previous_time = -1
    for row in observations:
        current = number(row["offset_seconds"], 0, duration)
        require(current > previous_time, "observation timestamps must increase")
        previous_time = current
        if row["status"] == "observed":
            require(isinstance(row.get("center"), list) and len(row["center"]) == 2, "observed center required")
            require(row.get("track_id") is not None, "observed track ID required")
            for coordinate in row["center"]:
                number(coordinate, 0, 1)
        if row.get("speed_diagonals_per_second") is not None:
            number(row["speed_diagonals_per_second"], 0, 100)
    windows = []
    motion_withheld = str(summary.get("motion_measurement", "")).startswith("withheld")
    for index in range(math.ceil(duration / window_seconds)):
        start, end = index * window_seconds, min((index + 1) * window_seconds, duration)
        intervals, centers, zone_seconds = [], [], {}
        contributing_tracks = set()
        statuses = {}
        for row in observations:
            if start <= row["offset_seconds"] < end:
                statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        for left, right in zip(observations, observations[1:]):
            dt = right["offset_seconds"] - left["offset_seconds"]
            overlap = min(end, right["offset_seconds"]) - max(start, left["offset_seconds"])
            if motion_withheld or overlap <= 0 or dt > summary["config"]["max_gap_seconds"]:
                continue
            if (left["status"] != "observed" or right["status"] != "observed" or
                    left["track_id"] != right["track_id"] or right.get("speed_diagonals_per_second") is None):
                continue
            intervals.append((overlap, right["speed_diagonals_per_second"]))
            contributing_tracks.add(right["track_id"])
            centers.extend([left["center"], right["center"]])
            if left.get("zone") is not None and left.get("zone") == right.get("zone"):
                zone = left["zone"]
                zone_seconds[zone] = zone_seconds.get(zone, 0) + overlap
        observed_seconds = sum(dt for dt, _ in intervals)
        coverage = observed_seconds / (end - start)
        features = None
        if observed_seconds:
            features = {"speed": sum(dt * v for dt, v in intervals) / observed_seconds,
                        "moving_fraction": sum(dt for dt, v in intervals if v > 0.0025) / observed_seconds,
                        "x_span": max(c[0] for c in centers) - min(c[0] for c in centers),
                        "y_span": max(c[1] for c in centers) - min(c[1] for c in centers)}
            if summary["config"]["zones"]:
                for zone in sorted(summary["config"]["zones"]):
                    features["zone:" + zone] = zone_seconds.get(zone, 0) / observed_seconds
        observed_at = capture_time + timedelta(seconds=start) if capture_time else None
        scope = {key: context.get(key, "") for key in ("animal_id", "camera_revision", "conditions")}
        tracking_config = copy.deepcopy(summary["config"])
        # The initial body location belongs to this video, not the reusable enclosure context.
        seed = tracking_config.pop("target_seed", None)
        scope.update(model_id=summary["model_id"], feature_version=VERSION,
                     window_seconds=window_seconds, tracking_config=tracking_config,
                     target_selection_mode="initial_box_guided" if seed else "automatic",
                     time_block=observed_at.hour // 3 if observed_at else None,
                     utc_offset_seconds=observed_at.utcoffset().total_seconds() if observed_at else None)
        source_hash = summary["source"]["sha256"]
        mixed_tracks = len(contributing_tracks) > 1
        quality_reason = ("measurement_withheld" if motion_withheld else
                          "multiple_track_segments" if mixed_tracks else
                          "low_coverage" if coverage < 0.8 else
                          "short_window" if end - start < window_seconds * 0.9 else None)
        window = {"index": index, "start_seconds": start, "end_seconds": end,
                  "captured_at": observed_at.isoformat() if observed_at else None,
                  "date": observed_at.date().isoformat() if observed_at else None,
                  "source_sha256": source_hash, "recording_id": context.get("recording_id") or source_hash,
                  "provenance": summary["source"]["provenance"], "scope": scope,
                  "coverage": coverage, "observed_seconds": observed_seconds,
                  "quality": "insufficient_observation" if quality_reason else "usable",
                  "quality_reason": quality_reason,
                  "track_ids": sorted(contributing_tracks),
                  "features": None if mixed_tracks else features, "zone_observed_seconds": {} if mixed_tracks else zone_seconds, "statuses": statuses,
                  "assessment": None, "reviewer": None}
        window["window_id"] = fingerprint(window)
        windows.append(window)
    return {"feature_version": VERSION, "windows": windows, "field_validated": False,
            "interpretation": "Image motion and observed zone time; no feeding, disease or physical-distance classification."}


def checked_window(window):
    require(window.get("quality") == "usable" and number(window["coverage"], 0, 1) >= 0.8,
            "insufficient observation for reference learning")
    require(window.get("provenance") == "real_camera", "reference learning requires own camera recordings")
    require(window.get("assessment") == "normal" and window.get("review_method") == "human" and
            isinstance(window.get("reviewer"), str) and window["reviewer"].strip(),
            "human-reviewed normal windows required")
    require(timestamp(window.get("captured_at")) is not None and window.get("date"), "capture time required")
    require(all(window["scope"].get(key) for key in ("animal_id", "camera_revision", "conditions")), "complete context required")
    require(window["scope"].get("time_block") is not None, "time context required")
    require(window.get("features") and set(FLOORS) <= set(window["features"]), "behavior features missing")
    for value in window["features"].values():
        number(value, 0, 100)


def nearest(window, references, scales):
    distances = []
    for ref in references:
        parts = {key: abs(window["features"][key] - ref["features"][key]) / scales[key] for key in scales}
        distances.append((sum(parts.values()) / len(parts), ref["window_id"], parts, ref))
    neighbors = sorted(distances, key=lambda item: (item[0], item[1]))[:3]
    return {"score": median(item[0] for item in neighbors),
            "neighbors": [{"window_id": ref["window_id"], "run_id": ref.get("run_id"),
                           "start_seconds": ref["start_seconds"], "end_seconds": ref["end_seconds"],
                           "captured_at": ref["captured_at"], "distance": distance}
                          for distance, _, _, ref in neighbors],
            "differences": {key: sum(item[2][key] for item in neighbors) / len(neighbors) for key in scales}}


def fit_reference(references, calibration):
    """Hold out whole recording groups and dates; never calibrate on the references."""
    require(len(references) >= 20 and len(calibration) >= 20, "need 20 reference and 20 separate calibration windows")
    rows = references + calibration
    for row in rows:
        checked_window(row)
        require(row["scope"] == rows[0]["scope"], "reference context differs")
        require(set(row["features"]) == set(rows[0]["features"]), "feature schema differs")
    require(len({r["window_id"] for r in rows}) == len(rows), "duplicate windows")
    for key in ("recording_id", "source_sha256", "date"):
        require(not {r[key] for r in references} & {r[key] for r in calibration}, "reference/calibration overlap: " + key)
    for group in (references, calibration):
        require(len({r["date"] for r in group}) >= 2, "need at least two dates in each partition")
    require(max(timestamp(r["captured_at"]) for r in references) < min(timestamp(r["captured_at"]) for r in calibration),
            "calibration must follow reference dates")
    scales = {}
    for key in rows[0]["features"]:
        values = [r["features"][key] for r in references]
        center = median(values)
        scales[key] = max(1.4826 * median(abs(v - center) for v in values), FLOORS.get(key, 0.05))
    scores = sorted(nearest(row, references, scales)["score"] for row in calibration)
    rank = min(len(scores) - 1, math.ceil((len(scores) + 1) * 0.95) - 1)
    model = {"schema_version": 1, "algorithm": "contextual_reviewed_neighbors_v1", "scope": rows[0]["scope"],
             "references": references, "scales": scales, "threshold": max(1.0, scores[rank]),
             "seen_recordings": sorted({r["recording_id"] for r in rows}),
             "seen_sources": sorted({r["source_sha256"] for r in rows}),
             "seen_dates": sorted({r["date"] for r in rows}),
             "latest_calibration_at": max(r["captured_at"] for r in calibration),
             "calibration_windows": len(calibration), "field_validated": False,
             "limitation": "Experimental deviation score; empirical calibration is not a guaranteed false-alert rate."}
    model["model_id"] = fingerprint(model)
    return model


def compare_windows(windows, model=None):
    if model is not None:
        require(model["model_id"] == fingerprint({k: v for k, v in model.items() if k != "model_id"}), "reference model integrity failure")
        require(model.get("algorithm") == "contextual_reviewed_neighbors_v1", "unknown reference algorithm")
    result, events, streak = [], [], []
    for window in windows:
        reason = None
        if window["quality"] != "usable":
            reason = "insufficient_observation"
        elif model is None:
            reason = "no_reviewed_reference"
        elif window["provenance"] != "real_camera" or window["scope"] != model["scope"]:
            reason = "context_mismatch"
        elif (window["recording_id"] in model["seen_recordings"] or window["source_sha256"] in model["seen_sources"] or
              window["date"] in model["seen_dates"]):
            reason = "reference_data_reuse"
        elif timestamp(window["captured_at"]) <= timestamp(model["latest_calibration_at"]):
            reason = "not_after_calibration"
        row = {"window_id": window["window_id"], "status": "unknown" if reason else "within_reference", "reason": reason}
        if not reason:
            require(set(window["features"]) == set(model["scales"]), "feature schema differs")
            for value in window["features"].values():
                number(value, 0, 100)
            row.update(nearest(window, model["references"], model["scales"]))
            row["threshold"] = model["threshold"]
            if row["score"] > model["threshold"]:
                row["status"] = "change_candidate"
        if row["status"] == "change_candidate":
            if streak and (window["source_sha256"] != streak[-1]["source_sha256"] or
                           abs(window["start_seconds"] - streak[-1]["end_seconds"]) > 1e-6):
                streak = []
            streak.append(window)
            if len(streak) == 2:
                events.append({"kind": "behavior_change_candidate", "start_seconds": streak[0]["start_seconds"],
                               "end_seconds": window["end_seconds"], "window_ids": [r["window_id"] for r in streak]})
            elif len(streak) > 2:
                events[-1]["end_seconds"] = window["end_seconds"]
                events[-1]["window_ids"].append(window["window_id"])
        else:
            streak = []
        result.append(row)
    return {"windows": result, "events": events, "field_validated": False, "diagnosis": "not_performed"}


def fit_reference_bank(windows):
    groups = {}
    for row in windows:
        if row.get("assessment") == "normal" and row.get("partition") in {"reference", "calibration"}:
            group = groups.setdefault(fingerprint(row["scope"]), {"reference": [], "calibration": []})
            group[row["partition"]].append(row)
    models, pending = {}, []
    for key, group in groups.items():
        try:
            models[key] = fit_reference(group["reference"], group["calibration"])
        except RecorderError as exc:
            rows = group["reference"] + group["calibration"]
            pending.append({"scope": rows[0]["scope"], "reason": str(exc)})
    require(models, "학습 가능한 조건 묶음이 없습니다. 조건별로 사람 검토 정상 기록 20구간·2일과 별도 보정 20구간·2일이 필요합니다.")
    reviewed_ids = [row["window_id"] for key, group in groups.items() if key in models
                    for rows in group.values() for row in rows]
    bank = {"schema_version": 1, "kind": "context_reference_bank", "models": models, "pending": pending,
            "reviewed_window_ids": reviewed_ids, "field_validated": False}
    bank["model_id"] = fingerprint(bank)
    return bank


def compare_contexts(windows, bank=None):
    if bank is None:
        return compare_windows(windows)
    require(bank["model_id"] == fingerprint({k:v for k,v in bank.items() if k != "model_id"}), "reference bank integrity failure")
    require(bank.get("kind") == "context_reference_bank", "unknown reference bank")
    results, events = [], []
    chunk = []
    for row in windows:
        if chunk and row["scope"] != chunk[-1]["scope"]:
            compared = compare_windows(chunk, bank["models"].get(fingerprint(chunk[0]["scope"])))
            results.extend(compared["windows"]); events.extend(compared["events"])
            chunk = []
        chunk.append(row)
    if chunk:
        compared = compare_windows(chunk, bank["models"].get(fingerprint(chunk[0]["scope"])))
        results.extend(compared["windows"]); events.extend(compared["events"])
    return {"windows": results, "events": events, "field_validated": False, "diagnosis": "not_performed"}


def evaluate_reviewed_windows(windows, bank=None):
    """Report held-out human labels, including missed anomalies during abstention."""
    if bank is not None:
        compare_contexts([], bank)
    report = {"reviewed_windows": 0, "evaluated_windows": 0, "excluded_windows": 0,
              "true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0,
              "abstentions": 0, "reviewed_seconds": 0, "decided_seconds": 0,
              "recall": None, "precision": None, "decision_coverage": None,
              "reference_available": bank is not None, "field_validated": False,
              "unit": "human-reviewed evaluation windows, not independent events or complete camera hours"}
    seen = set()
    for window in windows:
        if (window.get("review_method") != "human" or window.get("partition") != "evaluation" or
                window.get("assessment") not in {"normal", "anomaly"} or window["provenance"] != "real_camera"):
            continue
        key = (window["source_sha256"], window["start_seconds"], window["end_seconds"], fingerprint(window["scope"]))
        if key in seen:
            continue
        seen.add(key)
        report["reviewed_windows"] += 1
        model = bank["models"].get(fingerprint(window["scope"])) if bank else None
        if (model is None or window["source_sha256"] in model["seen_sources"] or
                window["recording_id"] in model["seen_recordings"] or window["date"] in model["seen_dates"] or
                timestamp(window["captured_at"]) <= timestamp(model["latest_calibration_at"])):
            report["excluded_windows"] += 1
            continue
        compared = compare_contexts([window], bank)["windows"][0]
        duration = window["end_seconds"] - window["start_seconds"]
        report["evaluated_windows"] += 1
        report["reviewed_seconds"] += duration
        abstained = compared["status"] == "unknown"
        predicted_change = compared["status"] == "change_candidate"
        if abstained:
            report["abstentions"] += 1
        else:
            report["decided_seconds"] += duration
        if window["assessment"] == "anomaly":
            report["true_positive" if predicted_change else "false_negative"] += 1
        elif predicted_change:
            report["false_positive"] += 1
        elif not abstained:
            report["true_negative"] += 1
    positives = report["true_positive"] + report["false_negative"]
    predictions = report["true_positive"] + report["false_positive"]
    report["recall"] = report["true_positive"] / positives if positives else None
    report["precision"] = report["true_positive"] / predictions if predictions else None
    report["decision_coverage"] = report["decided_seconds"] / report["reviewed_seconds"] if report["reviewed_seconds"] else None
    return report
