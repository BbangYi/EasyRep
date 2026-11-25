"""Conservative supervised behavior-state classification after tracking.

This module classifies only human-labeled, fully observed temporal windows.
It never turns a missing detection, partial visibility, or missing label into rest.
"""
from collections import Counter
import math
from statistics import fmean, pstdev

from .analysis_features import fingerprint
from .core import number, require


KIND = "tracked_behavior_centroid_classifier"
ALGORITHM = "fit_standardized_nearest_centroid_v1"


def _behavior(value):
    require(isinstance(value, str) and 0 < len(value) <= 128 and value.strip() == value,
            "behavior label required")
    return value


def _overlaps(window, label):
    return (label["start_seconds"] < window["end_seconds"] and
            window["start_seconds"] < label["end_seconds"])


def _covers(window, label):
    return (label["start_seconds"] <= window["start_seconds"] and
            label["end_seconds"] >= window["end_seconds"])


def examples_from_windows(windows, labels, *, clip_id, dataset_kind):
    """Admit only windows fully covered by one certain, visible behavior label."""
    require(dataset_kind in {"real", "test"}, "invalid dataset kind")
    require(isinstance(clip_id, str) and clip_id, "clip ID required")
    rows, excluded = [], {"no_full_certain_visible_label": [], "ambiguous_or_unobservable_label": []}
    relevant_labels = [label for label in labels if label.get("clip_id") == clip_id]
    for window in windows:
        require(isinstance(window, dict) and isinstance(window.get("window_id"), str), "window ID required")
        number(window.get("start_seconds"), 0)
        number(window.get("end_seconds"), 0)
        require(window["start_seconds"] < window["end_seconds"], "window duration required")
        if window.get("quality") != "usable" or not isinstance(window.get("features"), dict):
            excluded["no_full_certain_visible_label"].append(window["window_id"])
            continue
        animal_id = window.get("scope", {}).get("animal_id")
        overlaps = [label for label in relevant_labels if _overlaps(window, label) and
                    label.get("animal_id") == animal_id]
        invalid = [label for label in overlaps if label.get("visibility") != "visible" or
                   label.get("certainty") != "certain" or label.get("behavior") is None]
        complete = [label for label in overlaps if _covers(window, label) and
                    label.get("visibility") == "visible" and label.get("certainty") == "certain" and
                    label.get("behavior") is not None]
        behaviors = {_behavior(label["behavior"]) for label in complete}
        if invalid or len(behaviors) > 1:
            excluded["ambiguous_or_unobservable_label"].append(window["window_id"])
            continue
        if not behaviors:
            excluded["no_full_certain_visible_label"].append(window["window_id"])
            continue
        features = dict(window["features"])
        require(features, "behavior features required")
        for value in features.values():
            number(value, -1e12)
        group_id = window.get("recording_id") or window.get("source_sha256")
        require(isinstance(group_id, str) and group_id, "recording or source group required")
        rows.append({"window_id": window["window_id"], "clip_id": clip_id,
                     "animal_id": animal_id, "group_id": group_id,
                     "source_sha256": window.get("source_sha256"),
                     "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"],
                     "behavior": next(iter(behaviors)), "features": features,
                     "dataset_kind": dataset_kind,
                     "label_ids": sorted(label["label_id"] for label in complete)})
    return {"schema_version": 1, "kind": "behavior_labeled_windows", "dataset_kind": dataset_kind,
            "rows": rows, "excluded": {key: value for key, value in excluded.items() if value}}


def _rows(rows, *, labels_required):
    require(isinstance(rows, list) and rows, "behavior rows required")
    names = None
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("window_id"), str), "window ID required")
        require(isinstance(row.get("group_id"), str) and row["group_id"], "group ID required")
        features = row.get("features")
        require(isinstance(features, dict) and features, "behavior features required")
        current = tuple(sorted(features))
        names = current if names is None else names
        require(current == names, "behavior feature schema differs")
        for value in features.values():
            number(value, -1e12)
        if labels_required:
            _behavior(row.get("behavior"))
    return names


def fit(rows, *, dataset_kind):
    """Fit class centroids using training rows only; no evaluation groups enter model state."""
    require(dataset_kind in {"real", "test"}, "invalid dataset kind")
    names = _rows(rows, labels_required=True)
    require(all(row.get("dataset_kind", dataset_kind) == dataset_kind for row in rows), "mixed dataset kinds")
    counts = Counter(row["behavior"] for row in rows)
    require(len(counts) >= 2, "need at least two behavior classes")
    require(all(count >= 2 for count in counts.values()), "need at least two windows per behavior")
    require(len({row["group_id"] for row in rows}) >= 2, "need at least two recording groups")
    means = {name: fmean(row["features"][name] for row in rows) for name in names}
    scales = {name: max(pstdev(row["features"][name] for row in rows), 1e-6) for name in names}
    centroids = {}
    for behavior in sorted(counts):
        class_rows = [row for row in rows if row["behavior"] == behavior]
        centroids[behavior] = {name: fmean((row["features"][name] - means[name]) / scales[name]
                                            for row in class_rows) for name in names}
    model = {"schema_version": 1, "kind": KIND, "algorithm": ALGORITHM,
             "dataset_kind": dataset_kind, "feature_names": list(names),
             "preprocessing": {"means": means, "scales": scales}, "centroids": centroids,
             "training_groups": sorted({row["group_id"] for row in rows}),
             "training_window_ids": sorted(row["window_id"] for row in rows),
             "class_counts": dict(sorted(counts.items())),
             "status": "synthetic_pipeline_only" if dataset_kind == "test" else "unvalidated_real_classifier",
             "probability_calibrated": False, "production_validated": False,
             "limitations": ["Motion-window state classifier, not pose or health diagnosis.",
                             "Missing or ambiguous observations remain unclassified.",
                             "Distances are not calibrated probabilities."]}
    model["model_id"] = fingerprint(model)
    return model


def validate_model(model):
    require(model.get("schema_version") == 1 and model.get("kind") == KIND and
            model.get("algorithm") == ALGORITHM, "unsupported behavior classifier")
    require(model.get("model_id") == fingerprint({key: value for key, value in model.items() if key != "model_id"}),
            "behavior classifier fingerprint mismatch")
    names = tuple(model["feature_names"])
    require(names and set(model["preprocessing"]["means"]) == set(names) and
            set(model["preprocessing"]["scales"]) == set(names), "invalid behavior preprocessing")
    require(set(model["centroids"]) == set(model["class_counts"]), "invalid behavior classes")
    for name in names:
        number(model["preprocessing"]["means"][name], -1e12)
        number(model["preprocessing"]["scales"][name], 1e-6)
    return model


def _prediction_identity(row):
    require(isinstance(row, dict) and isinstance(row.get("window_id"), str), "window ID required")
    require(isinstance(row.get("group_id"), str) and row["group_id"], "group ID required")


def predict(model, rows):
    validate_model(model)
    require(isinstance(rows, list) and rows, "behavior rows required")
    names = tuple(model["feature_names"])
    results = []
    for row in rows:
        _prediction_identity(row)
        if row.get("quality") != "usable" or not isinstance(row.get("features"), dict):
            results.append({**row, "predicted_behavior": None, "distance": None,
                            "distance_margin": None, "status": "unobserved"})
            continue
        current = tuple(sorted(row["features"]))
        require(current == names, "behavior feature schema differs")
        for value in row["features"].values():
            number(value, -1e12)
        distances = {}
        for behavior, centroid in model["centroids"].items():
            distances[behavior] = math.sqrt(sum(
                ((row["features"][name] - model["preprocessing"]["means"][name]) /
                 model["preprocessing"]["scales"][name] - centroid[name]) ** 2 for name in names))
        ordered = sorted(distances.items(), key=lambda item: (item[1], item[0]))
        predicted, distance = ordered[0]
        margin = None if len(ordered) == 1 else ordered[1][1] - distance
        results.append({**row, "predicted_behavior": predicted, "distance": distance,
                        "distance_margin": margin, "status": "classified"})
    return {"schema_version": 1, "kind": "behavior_class_predictions", "model_id": model["model_id"],
            "dataset_kind": model["dataset_kind"], "probability_calibrated": False,
            "production_validated": False, "rows": results}


def evaluate(model, rows):
    validate_model(model)
    require(isinstance(rows, list) and rows, "behavior rows required")
    for row in rows:
        _prediction_identity(row)
        _behavior(row.get("behavior"))
    require(all(row.get("dataset_kind", model["dataset_kind"]) == model["dataset_kind"] for row in rows),
            "mixed dataset kinds")
    groups = sorted({row["group_id"] for row in rows})
    require(not set(groups) & set(model["training_groups"]), "evaluation recording overlap")
    predictions = predict(model, rows)["rows"]
    counts = {"correct": 0, "incorrect": 0, "abstained": 0}
    confusion = {}
    for row in predictions:
        actual, predicted = row["behavior"], row["predicted_behavior"]
        if predicted is None:
            counts["abstained"] += 1
            predicted = "unobserved"
        else:
            counts["correct" if actual == predicted else "incorrect"] += 1
        confusion.setdefault(actual, {})[predicted] = confusion.setdefault(actual, {}).get(predicted, 0) + 1
    classified = counts["correct"] + counts["incorrect"]
    return {"schema_version": 1, "kind": "behavior_class_evaluation", "model_id": model["model_id"],
            "dataset_kind": model["dataset_kind"], "evaluation_groups": groups,
            "counts": counts, "confusion": confusion, "accuracy": counts["correct"] / len(predictions),
            "classified_accuracy": None if not classified else counts["correct"] / classified,
            "coverage": classified / len(predictions),
            "production_validated": False,
            "limitation": "Evaluation is only valid for explicitly human-labeled held-out recording groups."}
