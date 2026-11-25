"""Fixed operating-point detection metrics, including verified negative images."""
from pathlib import Path

from .analysis_features import save_artifact
from .core import number, relative, require
from .vision_data import dataset_summary, load_dataset, output_directory, read_boxes
from .vision_model import assert_unseen, check_device, environment, load_model_card, runtime
from .worker_power import keep_awake


def intersection_over_union(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def detection_matches(references, predictions, *, confidence=0.4, iou=0.5):
    """Return (reference index, prediction index) pairs with one-to-one matching."""
    number(confidence, 0, 1)
    number(iou, 0.01, 1)
    remaining = set(range(len(references)))
    chosen = sorted((index for index, p in enumerate(predictions) if number(p["confidence"], 0, 1) >= confidence),
                    key=lambda index: -predictions[index]["confidence"])
    matches = []
    for prediction_index in chosen:
        prediction = predictions[prediction_index]
        scores = [(intersection_over_union(prediction["xyxy"], references[index]), index) for index in sorted(remaining)]
        score, index = max(scores, default=(0, -1))
        if score >= iou:
            remaining.remove(index)
            matches.append((index, prediction_index))
    return matches


def match_detections(references, predictions, *, confidence=0.4, iou=0.5):
    """Confidence-ordered one-to-one matching; duplicate boxes remain false positives."""
    tp = len(detection_matches(references, predictions, confidence=confidence, iou=iou))
    chosen = [p for p in predictions if p["confidence"] >= confidence]
    return {"true_positive": tp, "false_positive": len(chosen) - tp, "false_negative": len(references) - tp,
            "negative_image": not references, "negative_image_false_positive": not references and bool(chosen)}


def summarize(rows):
    counts = {key: sum(row[key] for row in rows) for key in
              ("true_positive", "false_positive", "false_negative", "negative_image", "negative_image_false_positive")}
    tp, fp, fn = (counts[k] for k in ("true_positive", "false_positive", "false_negative"))
    negatives = counts["negative_image"]
    return {**counts, "images": len(rows), "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "negative_image_false_positive_rate": counts["negative_image_false_positive"] / negatives if negatives else None}


def benchmark(dataset, model_directory, output, *, split="val", confidence=0.4, iou=0.5, device="cpu", nms_iou=0.7):
    require(split in {"val", "test"}, "benchmark requires val or test")
    number(confidence, 0.01, 0.99)
    number(iou, 0.1, 0.95)
    number(nms_iou, 0.1, 0.95)
    manifest, card = load_dataset(dataset), load_model_card(model_directory)
    require(card["class_names"] == manifest["class_names"], "model and dataset detection targets differ")
    rows = [r for r in manifest["records"] if r["split"] == split]
    if split == "test":
        assert_unseen(card, rows)
    with keep_awake(), output_directory(output, "fixed_threshold_detector_benchmark") as run:
        YOLO = runtime(run / "runtime", 2)
        check_device(device)
        model = YOLO(str(relative(Path(model_directory), card["weights"]["path"])), task="detect")
        require(list(model.names.values()) == card["class_names"], "checkpoint classes differ from model card")
        results = []
        for row in rows:
            prediction = model.predict(str(relative(Path(dataset), row["image"])), conf=confidence,
                                       imgsz=card["recipe"]["image_size"], device=device, iou=nms_iou, verbose=False)[0]
            boxes = [{"xyxy": [float(v) for v in b.xyxy[0].cpu().tolist()], "confidence": float(b.conf[0].cpu())}
                     for b in prediction.boxes]
            references = [[(x-w/2)*row["width"], (y-h/2)*row["height"], (x+w/2)*row["width"], (y+h/2)*row["height"]]
                          for x,y,w,h in read_boxes(relative(Path(dataset), row["label"]))]
            results.append({"image_id": row["id"], "group_id": row["group_id"], "reference_boxes": references,
                            "predictions": boxes, **match_detections(references, boxes, confidence=confidence, iou=iou)})
        report = {"schema_version": 1, "dataset_id": manifest["dataset_id"], "model_id": card["model_id"],
                  "device": device, "environment": environment(),
                  "split": split, "confidence": confidence, "iou": iou, "nms_iou": nms_iou, "metrics": summarize(results),
                  "per_image": results, "evidence_scope": "development" if split == "val" else manifest["split_policy"],
                  "grouping_limit": dataset_summary(manifest)["grouping_limit"],
                  "label_review_methods": sorted({r["review_method"] for r in rows}),
                  "field_performance_verified": False,
                  "limitation": "Image metrics are not event false-alerts/hour; unknown animal identities are not independent subjects."}
        save_artifact(run / "benchmark.json", report)
    return report


def select_candidate(reports, *, preserve_baseline_recall=False):
    """Select only on development data, with identical thresholds and evaluation inventory."""
    require(bool(reports), "no candidate reports")
    reference = next(iter(reports.values()))
    image_ids = [row.get("image_id") for row in reference["per_image"]]
    require(all(isinstance(key, str) and key.strip() for key in image_ids), "benchmark image IDs required")
    require(len(set(image_ids)) == len(image_ids), "duplicate benchmark image IDs")
    reference_boxes = [row.get("reference_boxes") for row in reference["per_image"]]
    require(all(isinstance(boxes, list) for boxes in reference_boxes), "benchmark reference boxes required")
    for report in reports.values():
        require(report["split"] == "val", "test results cannot select candidates")
        for key in ("dataset_id", "confidence", "iou"):
            require(report[key] == reference[key], "incomparable benchmark settings")
        require(report.get("nms_iou", 0.7) == reference.get("nms_iou", 0.7), "incomparable NMS settings")
        require([r.get("image_id") for r in report["per_image"]] == image_ids,
                "incomparable benchmark inventory")
        require([row.get("reference_boxes") for row in report["per_image"]] == reference_boxes,
                "incomparable benchmark reference boxes")
        scored = []
        for row in report["per_image"]:
            require(isinstance(row.get("predictions"), list), "benchmark predictions required")
            counts = match_detections(row["reference_boxes"], row["predictions"],
                                      confidence=report["confidence"], iou=report["iou"])
            require(all(row.get(key) == value for key, value in counts.items()),
                    "inconsistent per-image benchmark metrics")
            scored.append(counts)
        require(all(report["metrics"].get(key) == value for key, value in summarize(scored).items()),
                "inconsistent aggregate benchmark metrics")
        require(report["metrics"]["f1"] is not None and report["metrics"]["negative_image"] > 0,
                "selection requires positive and negative validation examples")
    # Baseline inserted first wins an exact tie. No claim is based on the test split.
    eligible = reports
    if preserve_baseline_recall:
        require("baseline" in reports and reports["baseline"]["metrics"]["recall"] is not None, "baseline recall required")
        minimum = reports["baseline"]["metrics"]["recall"]
        eligible = {name: r for name, r in reports.items() if r["metrics"]["recall"] >= minimum}
    return max(eligible, key=lambda name: (reports[name]["metrics"]["f1"],
                                         -reports[name]["metrics"]["negative_image_false_positive_rate"]))
