"""Interpretable novelty baseline, calibrated on separate human-reviewed sessions."""
import math
from statistics import fmean, median

from .analysis_features import fingerprint, validate_dataset
from .core import number, require, timestamp

GROUP_KEYS = ("session_id", "recording_id", "original_video_id")


def lineage(rows):
    return {key: sorted({r[key] for r in rows}) for key in GROUP_KEYS}


def disjoint(left, right):
    overlaps = {key: sorted(set(left[key]) & set(right[key])) for key in GROUP_KEYS}
    require(not any(overlaps.values()), "data leakage: shared session/recording/original video across splits")


def time_range(rows):
    if not rows or any(r["observed_start"] is None or r["observed_end"] is None for r in rows):
        return None
    return {"start": min(timestamp(r["observed_start"]) for r in rows).isoformat(),
            "end": max(timestamp(r["observed_end"]) for r in rows).isoformat()}


def ordered(left, right, required):
    if left is None or right is None:
        require(not required, "real within-animal evaluation requires capture timestamps for chronological splits")
        return False
    require(timestamp(left["end"]) <= timestamp(right["start"]), "chronology violation: later split overlaps or precedes earlier split")
    return True


def usable(row):
    return not row["quality_reasons"] and all(value is not None for value in row["features"].values())


def compatible(model, dataset):
    require(model["dataset_kind"] == dataset["dataset_kind"], "test model and real data cannot be mixed")
    require(model["scope"] == dataset["scope"], "model animal/camera/revision/context scope mismatch")
    require(model["feature_config"] == dataset["config"] and model["feature_names"] == dataset["feature_names"], "feature preprocessing mismatch")


def score(features, parameters):
    deviations = [{"feature": key, "value": features[key], "reference_median": value["center"],
                   "absolute_scaled_deviation": abs(features[key] - value["center"]) / value["scale"]}
                  for key, value in parameters.items()]
    # A single sustained departure is sufficient; this is not a health probability.
    return max(d["absolute_scaled_deviation"] for d in deviations), sorted(deviations, key=lambda d: d["absolute_scaled_deviation"], reverse=True)


def fit(training, calibration, false_alarm_rate=0.05, consecutive_windows=2):
    validate_dataset(training)
    validate_dataset(calibration)
    number(false_alarm_rate, 0.01, 0.25)
    require(type(consecutive_windows) is int and 1 <= consecutive_windows <= 20, "invalid persistence window count")
    model = {"schema_version": 1, "kind": "behavior_anomaly_model", "algorithm": "median_mad_max_v1",
             "dataset_kind": training["dataset_kind"], "scope": training["scope"],
             "feature_config": training["config"], "feature_names": training["feature_names"],
             "evaluation_protocol": "within_animal_chronological_unseen_sessions",
             "consecutive_windows": consecutive_windows, "false_alarm_rate_target": false_alarm_rate,
             "status": "synthetic_pipeline_only" if training["dataset_kind"] == "test" else "unvalidated_research_baseline",
             "probability_calibrated": False, "production_validated": False}
    compatible(model, calibration)
    train_groups, cal_groups = lineage(training["rows"]), lineage(calibration["rows"])
    disjoint(train_groups, cal_groups)
    train_time, cal_time = time_range(training["rows"]), time_range(calibration["rows"])
    chronological = ordered(train_time, cal_time, training["dataset_kind"] == "real")
    normal_train = [r for r in training["rows"] if usable(r) and r["human_assessment"] == "normal"]
    normal_cal = [r for r in calibration["rows"] if usable(r) and r["human_assessment"] == "normal"]
    require(len(normal_train) >= 20 and len({r["session_id"] for r in normal_train}) >= 2,
            "insufficient reviewed normal training data: need 20 windows in at least 2 sessions")
    require(len(normal_cal) >= max(20, math.ceil(1 / false_alarm_rate) - 1), "insufficient independent calibration data for requested quantile")
    floors = {"motion_mean": 0.002, "motion_peak": 0.002, "changed_fraction": 0.002, "brightness_mean": 0.01}
    floors.update({f"sensor:{s['sensor_id']}": s["scale_floor"] for s in training["config"]["sensors"]})
    parameters = {}
    for name in model["feature_names"]:
        values = [r["features"][name] for r in normal_train]
        center = median(values)
        mad = median(abs(v - center) for v in values)
        parameters[name] = {"center": center, "mad": mad, "scale": max(1.4826 * mad, floors[name]), "scale_floor": floors[name]}
    scores = sorted(score(row["features"], parameters)[0] for row in normal_cal)
    rank = math.ceil((len(scores) + 1) * (1 - false_alarm_rate))
    require(rank <= len(scores), "insufficient calibration samples")
    threshold = max(3.0, scores[rank - 1])
    model.update(parameters=parameters, threshold=threshold, minimum_threshold=3.0,
                 training={"dataset_id": training["dataset_id"], "normal_windows": len(normal_train), "excluded_windows": len(training["rows"]) - len(normal_train), "lineage": train_groups, "time_range": train_time},
                 calibration={"dataset_id": calibration["dataset_id"], "normal_windows": len(normal_cal), "excluded_windows": len(calibration["rows"]) - len(normal_cal),
                              "lineage": cal_groups, "time_range": cal_time, "quantile_rank": rank,
                              "empirical_exceedance_rate": sum(s > threshold for s in scores) / len(scores)},
                 chronology_checked=chronological,
                 limitations=["scene motion is not animal movement", "no disease/stress/sleep diagnosis",
                              "correlated windows; quantile does not guarantee field false-alarm rate",
                              "per-feature baseline cannot learn complex feature interactions"])
    model["model_id"] = fingerprint(model)
    return model


def validate_model(model):
    require(model.get("schema_version") == 1 and model.get("kind") == "behavior_anomaly_model" and model.get("algorithm") == "median_mad_max_v1", "unsupported model")
    require(model["model_id"] == fingerprint({k: v for k, v in model.items() if k != "model_id"}), "model fingerprint mismatch")
    number(model["threshold"], 0)
    require(type(model["consecutive_windows"]) is int and 1 <= model["consecutive_windows"] <= 20, "invalid persistence setting")
    require(set(model["parameters"]) == set(model["feature_names"]), "model parameter shape mismatch")
    for parameter in model["parameters"].values():
        number(parameter["center"], -1e12)
        number(parameter["scale"], 1e-12)
    return model


def apply_persistence(predictions, consecutive_windows):
    alerts = []
    run = []
    for row in predictions:
        contiguous = run and row["session_id"] == run[-1]["session_id"] and row["clip_id"] == run[-1]["clip_id"] and abs(row["start_seconds"] - run[-1]["end_seconds"]) < 1e-6
        if not contiguous:
            run = []
        if row["status"] != "elevated":
            run = []
            continue
        run.append(row)
        if len(run) < consecutive_windows:
            continue
        row["status"] = "alert"
        if len(run) == consecutive_windows:
            alerts.append({"session_id": row["session_id"], "clip_id": row["clip_id"], "recording_id": row["recording_id"],
                           "original_video_id": row["original_video_id"], "start_seconds": run[0]["start_seconds"],
                           "end_seconds": row["end_seconds"], "trigger_seconds": row["end_seconds"],
                           "row_ids": [r["row_id"] for r in run], "meaning": "sustained scene/environment deviation; review required"})
        else:
            alerts[-1]["end_seconds"] = row["end_seconds"]
            alerts[-1]["row_ids"].append(row["row_id"])
    return alerts


def predict(model, dataset):
    validate_model(model)
    validate_dataset(dataset)
    compatible(model, dataset)
    predictions = []
    for row in sorted(dataset["rows"], key=lambda r: (r["session_id"], r["clip_id"], r["start_seconds"])):
        value, explanations = score(row["features"], model["parameters"]) if usable(row) else (None, [])
        status = "insufficient_data" if value is None else "elevated" if value > model["threshold"] else "within_reference"
        predictions.append({**row, "score": value, "threshold": model["threshold"], "status": status,
                            "top_deviations": explanations[:3]})
    alerts = apply_persistence(predictions, model["consecutive_windows"])
    return {"schema_version": 1, "kind": "behavior_predictions", "model_id": model["model_id"],
            "dataset_id": dataset["dataset_id"], "dataset_kind": dataset["dataset_kind"], "scope": model["scope"],
            "production_validated": False, "predictions": predictions, "alerts": alerts}


def metrics(predictions, alerts):
    reviewed = [r for r in predictions if r["human_assessment"] in {"normal", "anomaly"}]
    scored = [r for r in reviewed if r["status"] != "insufficient_data"]
    counts = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    for row in scored:
        actual, detected = row["human_assessment"] == "anomaly", row["status"] == "alert"
        key = "true_positive" if actual and detected else "false_negative" if actual else "false_positive" if detected else "true_negative"
        counts[key] += 1
    tp, fp, fn, tn = (counts[k] for k in ("true_positive", "false_positive", "false_negative", "true_negative"))
    by_id = {r["row_id"]: r for r in predictions}
    false_alerts = sum(all(by_id[i]["human_assessment"] == "normal" for i in a["row_ids"]) for a in alerts)
    unreviewed_alerts = sum(any(by_id[i]["human_assessment"] is None for i in a["row_ids"]) for a in alerts)
    normal_hours = sum(r["end_seconds"] - r["start_seconds"] for r in scored if r["human_assessment"] == "normal") / 3600
    # Event metrics retain unscorable abnormal windows in the recall denominator.
    episodes = []
    for row in predictions:
        if row["human_assessment"] != "anomaly":
            continue
        if episodes and episodes[-1][-1]["session_id"] == row["session_id"] and episodes[-1][-1]["clip_id"] == row["clip_id"] and abs(episodes[-1][-1]["end_seconds"] - row["start_seconds"]) < 1e-6:
            episodes[-1].append(row)
        else:
            episodes.append([row])
    delays = []
    for episode in episodes:
        detections = [r for r in episode if r["status"] == "alert"]
        if detections:
            delays.append(detections[0]["end_seconds"] - episode[0]["start_seconds"])
    return {**counts, "precision": tp / (tp + fp) if tp + fp else None, "window_recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_window_rate": fp / (fp + tn) if fp + tn else None,
            "reviewed_windows": len(reviewed), "scored_reviewed_windows": len(scored),
            "unreviewed_windows": len(predictions) - len(reviewed), "abstained_windows": sum(r["status"] == "insufficient_data" for r in predictions),
            "reviewed_coverage": len(scored) / len(reviewed) if reviewed else None,
            "false_alert_events": false_alerts, "unreviewed_alert_events": unreviewed_alerts, "reviewed_normal_hours": normal_hours,
            "false_alerts_per_reviewed_normal_hour": false_alerts / normal_hours if normal_hours else None,
            "anomaly_episodes": len(episodes), "detected_episodes": len(delays),
            "event_recall": len(delays) / len(episodes) if episodes else None,
            "mean_detection_delay_seconds": fmean(delays) if delays else None}


def evaluate(model, dataset, baseline_motion_threshold=0.05):
    validate_dataset(dataset)
    validate_model(model)
    number(baseline_motion_threshold, 0, 1)
    for split in ("training", "calibration"):
        disjoint(model[split]["lineage"], lineage(dataset["rows"]))
    chronological = ordered(model["calibration"]["time_range"], time_range(dataset["rows"]), model["dataset_kind"] == "real")
    result = predict(model, dataset)
    baseline = []
    for row in result["predictions"]:
        state = "insufficient_data" if not usable(row) else "elevated" if row["features"]["motion_mean"] > baseline_motion_threshold else "within_reference"
        baseline.append({**row, "status": state})
    baseline_alerts = apply_persistence(baseline, model["consecutive_windows"])
    return {"schema_version": 1, "kind": "behavior_evaluation", "model_id": model["model_id"], "dataset_id": dataset["dataset_id"],
            "evidence_scope": "synthetic_pipeline_only" if dataset["dataset_kind"] == "test" else "reviewed_held_out_sessions_only",
            "protocol": model["evaluation_protocol"], "chronology_checked": chronological,
            "leakage_check": "passed", "model": metrics(result["predictions"], result["alerts"]),
            "fixed_motion_baseline": {"threshold": baseline_motion_threshold, **metrics(baseline, baseline_alerts)},
            "production_validated": False, "warning": "Window/event metrics are not animal health accuracy; unavailable rates are null."}
