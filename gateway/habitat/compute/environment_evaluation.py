"""Action-conditioned forecast scores; no model execution or field validation.

Each horizon uses only windows whose proposed action prefix matches the recorded
execution. Retrospective results are separate from caller-declared forecasts.
Caller-supplied timestamps do not prove issuance before outcomes were known;
this evaluator does not verify an immutable prediction journal.
Input records may contain additional provenance fields; required fields are
validated, and inputs are never modified.
"""
import math
import re


HORIZONS = (5, 10, 30, 60)
CHANNELS = ("air_C", "humidity_pct", "surface_hot_C", "surface_cool_C")
KINDS = ("prospective", "retrospective_action_conditioned")
SPLITS = ("train", "validation", "test")
ACTION_TOLERANCE_SECONDS = 1e-6


def _record(value, fields, label):
    if not isinstance(value, dict) or not set(fields) <= value.keys():
        raise ValueError(f"{label}: required record fields are missing")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected a nonempty string")
    return value


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{label}: expected a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{label}: expected a finite number")
    return result


def _vector(value, length, label, *, durations=False):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label}: expected {length} values")
    numbers = [_number(v, label) for v in value]
    if durations and any(v < 0 for v in numbers):
        raise ValueError(f"{label}: execution duration cannot be negative")
    return numbers


def _matrix(value, rows, columns, label):
    if not isinstance(value, list) or len(value) != rows:
        raise ValueError(f"{label}: expected {rows} rows")
    return [_vector(row, columns, label) for row in value]


def _window_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("window_id: expected a lowercase SHA-256")
    return value


def _metrics(errors):
    if not errors:
        return {"mae": None, "rmse": None, "bias": None}
    scale = max(abs(e) for e in errors)
    if scale == 0:
        return {"mae": 0.0, "rmse": 0.0, "bias": 0.0}
    # Scale first: squaring otherwise finite large residuals can overflow.
    normalized = [e / scale for e in errors]
    n = len(errors)
    return {
        "mae": scale * (math.fsum(abs(e) for e in normalized) / n),
        "rmse": scale * math.sqrt(math.fsum(e * e for e in normalized) / n),
        "bias": scale * (math.fsum(normalized) / n),
    }


def evaluate_predictions(windows, predictions, *, split="test"):
    """Evaluate iterable window/prediction dictionaries on exactly one split.

    At most one model per prediction kind and one prediction per (window, kind)
    are accepted. All supplied records are validated, including other splits.
    Declared prospective issuance must be in [origin, origin + 60] seconds.
    Retrospective issuance has no time bound. Neither kind establishes
    prospective evidence: timestamps are caller-declared, not authenticated
    against an immutable prediction journal.
    No selected windows or submitted predictions raises ValueError. A submitted
    but entirely mismatched action plan produces a non-pass report with null
    scores. Bias is prediction minus measured target, in each channel's unit.
    """
    if split not in SPLITS:
        raise ValueError("split must be train, validation or test")
    indexed, sources = {}, set()
    for item in windows:
        _record(item, ("window_id", "split", "session_id", "cage_id", "data_source",
                       "origin_epoch", "history", "targets", "future_executed_seconds"), "window")
        identity = _window_id(item["window_id"])
        if identity in indexed:
            raise ValueError("duplicate window_id")
        if item["split"] not in SPLITS or item["data_source"] not in ("sensor", "simulation"):
            raise ValueError("window: invalid split or data_source")
        for key in ("session_id", "cage_id"):
            _text(item[key], key)
        origin = _number(item["origin_epoch"], "window origin_epoch")
        history = _matrix(item["history"], 30, 5, "history")
        if any(row[4] < 0 for row in history):
            raise ValueError("history: execution duration cannot be negative")
        targets = _matrix(item["targets"], 60, 4, "targets")
        actions = _vector(item["future_executed_seconds"], 60, "future_executed_seconds", durations=True)
        indexed[identity] = {"split": item["split"], "origin": origin,
                             "baseline": history[-1][:4], "targets": targets, "actions": actions}
        sources.add(item["data_source"])
    if len(sources) > 1:
        raise ValueError("sensor and simulation windows cannot be mixed")
    selected_count = sum(w["split"] == split for w in indexed.values())
    if not selected_count:
        raise ValueError(f"no windows in selected split: {split}")

    models = {kind: set() for kind in KINDS}
    selected = {kind: [] for kind in KINDS}
    seen, ignored = set(), 0
    for item in predictions:
        _record(item, ("window_id", "model_id", "generated_at_epoch", "origin_epoch",
                       "planned_seconds", "prediction_kind", "values"), "prediction")
        identity = _window_id(item["window_id"])
        if identity not in indexed:
            raise ValueError("prediction references unknown window_id")
        kind = item["prediction_kind"]
        if kind not in KINDS:
            raise ValueError("unknown prediction_kind")
        if (identity, kind) in seen:
            raise ValueError("duplicate prediction for window and prediction_kind")
        seen.add((identity, kind))
        model = _text(item["model_id"], "model_id")
        models[kind].add(model)
        if len(models[kind]) != 1:
            raise ValueError("multiple model IDs in one prediction_kind")
        window = indexed[identity]
        origin = _number(item["origin_epoch"], "prediction origin_epoch")
        if origin != window["origin"]:
            raise ValueError("prediction origin_epoch does not match its window")
        issued = _number(item["generated_at_epoch"], "generated_at_epoch")
        if kind == "prospective" and not 0 <= issued - origin <= 60:
            raise ValueError("prospective prediction issued outside origin..origin+60")
        plan = _vector(item["planned_seconds"], 60, "planned_seconds", durations=True)
        if not isinstance(item["values"], dict) or set(item["values"]) != {str(h) for h in HORIZONS}:
            raise ValueError("values must contain exactly horizons 5, 10, 30 and 60")
        values = {h: _vector(item["values"][str(h)], 4, f"values[{h}]") for h in HORIZONS}
        if window["split"] != split:
            ignored += 1
            continue
        selected[kind].append((window, plan, values))
    submitted = sum(len(items) for items in selected.values())
    if not submitted:
        raise ValueError(f"no predictions submitted for selected split: {split}")

    modes = {}
    for kind in KINDS:
        records = selected[kind]
        horizons = {}
        for horizon in HORIZONS:
            errors = {c: {"model": [], "persistence": []} for c in CHANNELS}
            eligible = 0
            for window, plan, values in records:
                if any(abs(a - b) > ACTION_TOLERANCE_SECONDS
                       for a, b in zip(plan[:horizon], window["actions"][:horizon])):
                    continue
                eligible += 1
                for j, channel in enumerate(CHANNELS):
                    target = window["targets"][horizon - 1][j]
                    for label, prediction in (("model", values[horizon][j]),
                                              ("persistence", window["baseline"][j])):
                        error = prediction - target
                        if not math.isfinite(error):
                            raise ValueError("non-finite residual")
                        errors[channel][label].append(error)
            horizons[str(horizon)] = {
                "eligible_windows": eligible,
                "excluded_action_mismatch": len(records) - eligible,
                "missing_predictions": selected_count - len(records),
                "metrics": {channel: {name: _metrics(values) for name, values in groups.items()}
                            for channel, groups in errors.items()},
            }
        scored = any(h["eligible_windows"] for h in horizons.values())
        modes[kind] = {
            "model_id": next(iter(models[kind])) if records else None,
            "status": "evaluated" if scored else "no_eligible_predictions" if records else "no_predictions",
            "issuance_provenance": "caller_declared_unverified" if kind == "prospective"
                                   else "retrospective_declared",
            "prospective_evidence": False,
            "submitted_windows": len(records),
            "missing_prediction_windows": selected_count - len(records),
            "horizons": horizons,
        }
    prospective = modes["prospective"]["status"] == "evaluated"
    retrospective = modes["retrospective_action_conditioned"]["status"] == "evaluated"
    return {
        "schema_version": 1,
        "status": "declared_prospective_evaluated" if prospective else "retrospective_only" if retrospective
                  else "no_eligible_predictions",
        "split": split,
        "data_source": next(iter(sources)),
        "field_validated": False,
        "window_count": selected_count,
        "excluded_other_split_windows": len(indexed) - selected_count,
        "prediction_count": submitted,
        "ignored_other_split_predictions": ignored,
        "action_match_tolerance_seconds": ACTION_TOLERANCE_SECONDS,
        "bias_definition": "prediction_minus_target",
        "modes": modes,
    }
