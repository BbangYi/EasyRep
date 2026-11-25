"""Review detector outputs against attributed reference labels without changing the model."""
from pathlib import Path

from .analysis_features import save_artifact
from .core import number, relative, require
from .vision_data import load_dataset, output_directory, read_boxes
from .vision_model import assert_unseen, check_device, load_model_card, runtime
from .worker_power import keep_awake


def review_images(dataset, model_directory, output, *, split="test", limit=20, confidence=0.4, device="cpu"):
    require(split in {"train", "val", "test"}, "unknown split")
    require(type(limit) is int and 1 <= limit <= 50, "review limit must be 1-50 images")
    number(confidence, 0.01, 0.99)
    manifest = load_dataset(dataset)
    card = load_model_card(model_directory)
    require(card["class_names"] == manifest["class_names"], "model and dataset detection targets differ")
    candidates = [r for r in manifest["records"] if r["split"] == split]
    rows = candidates[:limit]  # Deterministic inventory order, never select by prediction quality.
    if split == "test":
        assert_unseen(card, rows)
    sources = {s["id"]: s for s in manifest["sources"]}
    with keep_awake(), output_directory(output, "review_image_predictions") as run:
        YOLO = runtime(run / "runtime", 2)
        check_device(device)
        import cv2
        model = YOLO(str(relative(Path(model_directory), card["weights"]["path"])), task="detect")
        require(list(model.names.values()) == card["class_names"], "checkpoint classes differ from model card")
        observations = []
        for row in rows:
            image_path = relative(Path(dataset), row["image"])
            result = model.predict(str(image_path), conf=confidence, imgsz=card["recipe"]["image_size"],
                                   device=device, verbose=False)[0]
            canvas = result.orig_img.copy()
            height, width = canvas.shape[:2]
            labels = read_boxes(relative(Path(dataset), row["label"]))
            for x, y, w, h in labels:
                p1 = (int((x - w / 2) * width), int((y - h / 2) * height))
                p2 = (int((x + w / 2) * width), int((y + h / 2) * height))
                cv2.rectangle(canvas, p1, p2, (0, 255, 0), 2)
            detections = []
            for box in result.boxes:
                coordinates = [float(v) for v in box.xyxy[0].cpu().tolist()]
                score = float(box.conf[0].cpu())
                x1, y1, x2, y2 = [int(v) for v in coordinates]
                cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 165, 255), 3)
                cv2.putText(canvas, f"prediction {score:.2f}", (max(0, x1), max(45, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
                detections.append({"xyxy": coordinates, "confidence": score})
            cv2.putText(canvas, f"Green: {row['review_method']} reference | Orange: model | not field validated",
                        (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1)
            name = row["id"] + ".png"
            require(cv2.imwrite(str(run / name), canvas), "review image write failed")
            observations.append({"image_id": row["id"], "source": sources[row["source_id"]],
                                 "image_sha256": row["image_sha256"], "reference_labels": labels,
                                 "review_method": row["review_method"], "detections": detections, "overlay": name})
        report = {"model_id": card["model_id"], "dataset_id": manifest["dataset_id"], "split": split,
                  "model_status": card["status"], "confidence": confidence,
                  "selection": "first images in immutable dataset inventory", "available_images": len(candidates),
                  "reviewed_images": len(rows), "observations": observations, "production_validated": False}
        save_artifact(run / "predictions.json", report)
    return {"reviewed_images": len(rows), "available_images": len(candidates),
            "output": str(Path(output).resolve()), "production_validated": False}
