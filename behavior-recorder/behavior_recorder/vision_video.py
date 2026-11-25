"""Real-frame extraction and conservative single-occupant tracking evidence."""
from contextlib import closing, ExitStack
from fractions import Fraction
import json
import math
from pathlib import Path
from time import perf_counter

from .analysis_features import save_artifact
from .core import Session, digest, encode, number, read_json, relative, require
from .media import frame_records, probe
from .vision_data import DETECTION_TARGETS, SPECIES, output_directory
from .vision_benchmark import intersection_over_union
from .vision_model import check_device, load_model_card, runtime
from .vision_tracking import TRACKING_REVISION, BackgroundMotion, SeededTarget, VideoTracker, tracking_options
from .vision_scene import SceneBoundary
from .worker_power import keep_awake

FRAME_SAMPLING_METHOD = "pts-buckets-v2"


def source_video(video=None, session_path=None, clip_id=None, *, provenance=None):
    if session_path is not None:
        require(video is None and clip_id is not None, "use either video or session plus clip")
        session = Session(session_path)
        require(session.manifest["state"] in {"stopped", "interrupted"}, "close the recording session before analysis")
        require(not session.verify(), "recorder session failed integrity verification")
        require(session.manifest["config"]["dataset_kind"] == "real", "vision analysis requires real footage")
        animals = session.manifest["config"]["animals"]
        require(len(animals) == 1 and animals[0]["species"] == SPECIES, "configure one crested gecko occupant")
        clip = session.clip(clip_id)
        require(clip["camera_kind"] == "rgb", "RGB video is required")
        path = relative(session.root, clip["media_path"])
        meta = {k: clip[k] for k in ("clip_id", "recording_id", "original_video_id", "captured_at", "capture_clock", "camera_id", "placement_revision", "calibration_revision")}
        meta.update(session_id=session.manifest["session_id"], animal_id=animals[0]["animal_id"], provenance="real_camera",
                    identity_method="configured_single_occupant; not visual identification")
        require(provenance is None or provenance == meta["provenance"], "provenance differs from recorder session")
    else:
        require(video is not None and clip_id is None, "video input or recorder session required")
        path = Path(video).resolve()
        require(provenance in {None, "unverified_file", "public_real", "real_camera", "synthetic_test"}, "invalid video provenance")
        meta = {"provenance": provenance or "unverified_file", "animal_id": None, "captured_at": None,
                "provenance_basis": "operator_declaration" if provenance else "unverified",
                "capture_clock": {"source": "unknown", "accuracy_ms": None}, "identity_method": "unidentified_video_subject"}
    require(path.is_file() and 0 < path.stat().st_size <= 1024**3, "missing/oversized video (limit 1 GiB)")
    metadata, frames, duration = probe(path, {"max_clip_seconds": 600, "max_frames": 36000, "probe_timeout_seconds": 120})
    require(0 < metadata["width"] * metadata["height"] <= 12_000_000, "video pixel limit exceeded")
    # OpenCV exposes stored pixels without applying the display aspect ratio.
    require(metadata.get("sample_aspect_ratio") in (None, "N/A", "0:1", "1:1"),
            "non-square video pixels; normalize sample_aspect_ratio to 1:1 before vision ingestion")
    rows, anomalies = frame_records(frames, metadata, meta["captured_at"], meta["capture_clock"], None)
    require(not anomalies and all(r["offset_seconds"] is not None for r in rows), "video has missing/nonmonotonic original timestamps")
    require(rows[-1]["duration_pts"] is not None and rows[-1]["duration_pts"] > 0, "video end timing unavailable")
    duration = rows[-1]["offset_seconds"] + rows[-1]["duration_pts"] * float(Fraction(metadata["time_base"]))
    meta.update(sha256=digest(path), width=metadata["width"], height=metadata["height"], duration_seconds=duration,
                frame_count=len(rows), time_base=metadata["time_base"])
    meta.setdefault("original_video_id", "sha256:" + meta["sha256"])
    return path, meta, rows


def decoded_frames(path, metadata, timeline):
    """Yield every real frame with its original timing; keep decoder lifetime bounded."""
    import cv2
    # OpenCV's compute-thread setting does not bound FFmpeg's decoder workers.
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    require(capture.isOpened(), "video decoder could not open input")
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            require(count < len(timeline), "decoder returned more frames than original timestamp index")
            row = timeline[count]
            require(frame.shape[:2] == (metadata["height"], metadata["width"]), "decoded dimensions differ; normalize rotation before ingestion")
            count += 1
            yield frame, row
        require(count == len(timeline), "decode ended before all indexed frames; output is incomplete")
    finally:
        capture.release()


def sampled_frames(path, metadata, timeline, sample_fps, *, scene=None):
    """Choose the first actual frame per source-time interval without accumulating drift."""
    number(sample_fps, 0.1, 30)
    tick = float(Fraction(metadata.get("time_base", "0")))
    require(math.isfinite(tick) and tick >= 0, "invalid sampling time base")
    last_bucket = -1
    pending_boundaries = []
    with closing(decoded_frames(path, metadata, timeline)) as frames:
        for frame, row in frames:
            if scene is not None:
                boundary = scene.update(frame)
                if boundary["cut"]:
                    pending_boundaries.append({**boundary, "frame_index": row["frame_index"],
                                               "offset_seconds": row["offset_seconds"]})
            # Half a timestamp tick accounts for container rounding, not missing frames.
            bucket = math.floor((row["offset_seconds"] + tick / 2) * sample_fps + 1e-9)
            if bucket <= last_bucket:
                continue
            last_bucket = bucket
            if scene is not None:
                row = {**row, "scene_boundary": {**boundary, "cut": bool(pending_boundaries),
                                                "native_events": pending_boundaries}}
                pending_boundaries = []
            yield frame, row


def extract_frames(output, *, video=None, session_path=None, clip_id=None, sample_fps=0.2,
                   source_url, license_name, attribution, provenance=None):
    import cv2
    path, metadata, timeline = source_video(video, session_path, clip_id)
    if video is not None:
        require(provenance in {"public_real", "real_camera"}, "declare --provenance public_real or real_camera for external video")
        metadata.update(provenance=provenance, provenance_basis="operator_declaration")
    else:
        require(provenance is None or provenance == metadata["provenance"], "provenance differs from recorder session")
    with output_directory(output, "extract_frames_for_review") as run:
        image_dir = run / "images" / "train"
        image_dir.mkdir(parents=True)
        rows = []
        group_id = metadata.get("recording_id", metadata["original_video_id"])
        for frame, timing in sampled_frames(path, metadata, timeline, sample_fps):
            key = f"frame-{timing['frame_index']:06d}"
            image_path = image_dir / (key + ".png")
            require(cv2.imwrite(str(image_path), frame), "failed to save review image")
            rows.append({"id": key, "image": image_path.relative_to(run).as_posix(), "label": f"labels/train/{key}.txt",
                         "source_id": "recording-1", "group_id": group_id, "split": "train", "reviewer": None, "review_method": None,
                         "species_confirmed": False, "original_frame": timing})
        require(digest(path) == metadata["sha256"], "source video changed during extraction")
        plan = {"schema_version": 1, "species": SPECIES, "dataset_kind": "real", "split_policy": "source_group_disjoint",
                "sources": [{"id": "recording-1", "url": source_url, "license": license_name, "attribution": attribution,
                             "provenance": metadata["provenance"]}], "records": rows}
        save_artifact(run / "plan.json", plan)
        save_artifact(run / "source.json", {**metadata, "sampling_method": FRAME_SAMPLING_METHOD,
                                            "sample_fps": sample_fps})
    return {"frames": len(rows), "group_id": group_id, "ready_for_training": False,
            "next": "Annotate exported images; keep this original recording together when creating train/val/test groups."}


def validate_tracking_config(config):
    require(config.get("schema_version") == 1 and config.get("species") in DETECTION_TARGETS, "invalid tracking config")
    require(config.get("tracking_revision", TRACKING_REVISION) == TRACKING_REVISION, "unsupported tracking revision")
    require(config.get("inference_slicing", "off") in ("off", "overlap-640-v1", "full-preserving-640-v1"), "unsupported inference slicing")
    if "inference_image_size" in config:
        size = config["inference_image_size"]
        require(type(size) is int and 64 <= size <= 1280 and size % 32 == 0,
                "inference_image_size must be a multiple of 32 from 64 to 1280")
    for key, low, high in (("sample_fps", 0.1, 30), ("confidence", 0.05, 0.95),
                           ("max_step_diagonals", 0.001, 1), ("max_gap_seconds", 0.01, 60)):
        number(config[key], low, high)
    if config.get("inference_slicing") == "full-preserving-640-v1":
        number(config.get("sliced_new_confidence"), config["confidence"], 0.95)
    else:
        require("sliced_new_confidence" not in config, "new-box confidence requires full-preserving slicing")
    require(isinstance(config["zones"], dict), "zones must be a name-to-normalized-rectangle object")
    tracking_options(config)
    for key, rectangle in config["zones"].items():
        require(isinstance(key, str) and key and isinstance(rectangle, list) and len(rectangle) == 4, "invalid zone")
        x, y, w, h = [number(v, 0, 1) for v in rectangle]
        require(w > 0 and h > 0 and x + w <= 1 and y + h <= 1, "zone outside image")
    return config


def selected_boxes(boxes, config):
    """Use one threshold for observation logic, visible boxes, and counts."""
    return [box for box in boxes if box["confidence"] >= config["confidence"]]


def sliced_windows(width, height):
    """640px tiles, at least 20% overlap, covering the last pixel without padding."""
    require(type(width) is int and type(height) is int and width > 0 and height > 0 and
            width * height <= 12_000_000, "invalid slicing dimensions")
    def starts(extent):
        last = max(0, extent - 640)
        return sorted(set(range(0, last + 1, 512)) | {last})
    xs, ys = starts(width), starts(height)
    require(len(xs) * len(ys) <= 64, "slicing exceeds 64 tiles per frame")
    return [(x, y, min(x + 640, width), min(y + 640, height)) for y in ys for x in xs]


def merge_sliced_boxes(full, sliced, *, anchor_confidence, new_confidence, nms_iou):
    """Preserve full-image strong proposals; add only distinct confident tile proposals.

    Containment suppresses partial-body duplicates, not evidence of identity. A new
    animal inside another predicted box can be suppressed; full-image detections
    are never combined with one another.
    """
    number(anchor_confidence, 0.05, 0.95)
    number(new_confidence, anchor_confidence, 0.95)
    number(nms_iou, 0.1, 0.9)
    require(len(full) <= 100 and len(sliced) <= 100, "too many merge candidates")
    def overlaps(a, b):
        a, b = a["xyxy"], b["xyxy"]
        intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
        smaller = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
        return intersection_over_union(a, b) >= nms_iou or (smaller > 0 and intersection / smaller >= 0.8)
    anchors = [box for box in full if box["confidence"] >= anchor_confidence]
    added = []
    for box in sorted(sliced, key=lambda box: -box["confidence"]):
        if len(anchors) + len(added) == 100:
            break
        if box["confidence"] >= new_confidence and not any(overlaps(box, kept) for kept in anchors + added):
            added.append(box)
    if not added:
        return list(full)
    weak = [box for box in full if box["confidence"] < anchor_confidence and
            not any(overlaps(box, strong) for strong in added)]
    weak = sorted(weak, key=lambda box: -box["confidence"])[:100-len(anchors)-len(added)]
    return [box for box in full if box in anchors or box in weak] + added


def predict_frame(model, frame, *, device, confidence, nms_iou, image_size, slicing="off",
                  anchor_confidence=None, new_confidence=None):
    """Keep the full-image pass; optionally add tiles and suppress duplicate boxes."""
    require(slicing in ("off", "overlap-640-v1", "full-preserving-640-v1"), "unsupported inference slicing")
    if slicing == "full-preserving-640-v1":
        number(anchor_confidence, confidence, 0.95)
        number(new_confidence, anchor_confidence, 0.95)
    height, width = frame.shape[:2]
    full = (0, 0, width, height)
    windows = [full]
    if slicing != "off":
        windows += [window for window in sliced_windows(width, height) if window != full]
    started = perf_counter()
    boxes = []
    for x1, y1, x2, y2 in windows:
        result = model.predict(frame[y1:y2, x1:x2], device=device, conf=confidence,
                               iou=nms_iou, max_det=100, imgsz=image_size, verbose=False)[0]
        for box in result.boxes:
            coords = [float(v) for v in box.xyxy[0].cpu().tolist()]
            score = float(box.conf[0].cpu())
            number(score, 0, 1)
            require(len(coords) == 4, "invalid detector coordinates")
            for value, bound in zip(coords, (x2-x1, y2-y1, x2-x1, y2-y1)):
                number(value, 0, bound)
            require(coords[2] > coords[0] and coords[3] > coords[1], "invalid detector box area")
            boxes.append({"xyxy": [v + shift for v, shift in zip(coords, (x1, y1, x1, y1))],
                          "confidence": score})
        if (x1, y1, x2, y2) == full:
            full_boxes = list(boxes)
    candidates = len(boxes)
    if len(windows) > 1:
        merged = []
        for box in sorted(boxes, key=lambda box: -box["confidence"]):
            if all(intersection_over_union(box["xyxy"], kept["xyxy"]) <= nms_iou for kept in merged):
                merged.append(box)
                if len(merged) == 100:
                    break
        boxes = merged
    evidence = {"mode": slicing, "passes": len(windows), "candidates_before_merge": candidates,
                "actual_device": str(result.boxes.data.device)}
    if slicing == "full-preserving-640-v1":
        boxes = merge_sliced_boxes(full_boxes, boxes, anchor_confidence=anchor_confidence,
                                   new_confidence=new_confidence, nms_iou=nms_iou)
        evidence.update(anchor_confidence=anchor_confidence, new_confidence=new_confidence)
    evidence["seconds"] = perf_counter() - started
    return boxes, evidence


def preview_geometry(width, height):
    scale = min(1280 / max(width, height), max(1, 640 / width))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def render_review_frame(frame, row, config):
    import cv2
    import numpy as np
    height, width = frame.shape[:2]
    preview_width, preview_height = preview_geometry(width, height)
    banner = 112
    canvas = np.zeros((preview_height + banner, max(640, preview_width), 3), dtype=np.uint8)
    left = (canvas.shape[1] - preview_width) // 2
    canvas[banner:, left:left + preview_width] = cv2.resize(frame, (preview_width, preview_height))
    predictions = selected_boxes(row["detections"], config)
    memory_masks = (row.get("inference") or {}).get("model") == "sam2-hybrid"
    orange = (20, 165, 255)
    labels = []
    for index, box in enumerate(predictions, 1):
        x1, y1, x2, y2 = box["xyxy"]
        x1, x2 = (round(x * preview_width / width) + left for x in (x1, x2))
        y1, y2 = (round(y * preview_height / height) + banner for y in (y1, y2))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), orange, 3)
        label = (f"T{box['track_id']}" if box.get("track_id") is not None else f"pending#{index}") if "identity_status" in box else f"#{index}"
        if memory_masks and box.get("identity_status") != "active":
            label += " pending"
        elif box.get("identity_status") in {"ambiguous_association", "implausible_jump"}:
            label += " ?"
        labels.append(label)
        (text_width, text_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        label_x = max(0, min(x1, canvas.shape[1] - text_width - 12))
        label_y = max(banner + text_height + 9, y1)
        cv2.rectangle(canvas, (label_x, label_y - text_height - 7), (label_x + text_width + 10, label_y + 5), (25, 25, 25), -1)
        cv2.putText(canvas, label, (label_x + 5, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, orange, 2)
    state = {"observed": "ONE TRACK - correctness not verified",
             "ambiguous_multiple_detections": "MULTIPLE PREDICTIONS - motion withheld",
             "no_confident_track": "NO TRACK - correctness not verified",
             "implausible_track_jump": "TRACK JUMP - motion withheld",
             "ambiguous_association": "IDENTITY UNCERTAIN - motion withheld",
             "track_pending": "TRACK PENDING - motion withheld"}[row["status"]]
    if row.get("lost_tracks"):
        state += f" | {len(row['lost_tracks'])} lost"
    if config.get("camera_motion", "off") != "off":
        state += " | ACTIVITY WITHHELD"
    scores = " ".join(f"{label}={box['confidence']:.2f}" for label, box in zip(labels[:6], predictions[:6]))
    if len(predictions) > 6:
        scores += f" (+{len(predictions)-6} more)"
    heading = f"Source {row['offset_seconds']:.3f}s | {len(predictions)} predictions, score >= {config['confidence']:.2f}"
    footer = "NOT anomaly markers | scores: " + (scores or "none")
    if memory_masks:
        heading = f"Source {row['offset_seconds']:.3f}s | {len(predictions)} object masks"
        footer = "NOT anomaly markers | binary mask presence; no probability"
    for y, text in ((26, heading), (58, state), (90, footer)):
        text_width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 1)[0][0]
        font_size = min(0.65, 0.65 * (canvas.shape[1] - 20) / max(1, text_width))
        cv2.putText(canvas, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, font_size, (255, 255, 255), 1)
    if row.get("target_selection"):
        text = f"GUIDED TARGET | raw candidates: {len(row['detector_candidates'])} | {row['target_selection']}"
        cv2.putText(canvas, text, (10, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 225, 180), 1)
    return canvas


def observation(boxes, previous, offset, width, height, config):
    """No movement or occupancy is invented across missing/ambiguous observations."""
    row = {"offset_seconds": offset, "status": "no_confident_track", "track_id": None, "center": None,
           "zone": None, "step_diagonals": None, "speed_diagonals_per_second": None, "behavior": None}
    confident = selected_boxes(boxes, config)
    if not confident:
        return row
    if len(confident) != 1:
        row["status"] = "ambiguous_multiple_detections"
        return row
    box = confident[0]
    if "identity_status" in box and not box.get("motion_allowed"):
        row["status"] = {"ambiguous_association": "ambiguous_association",
                         "implausible_jump": "implausible_track_jump"}.get(box["identity_status"], "track_pending")
        return row
    if box["track_id"] is None:
        return row
    x1, y1, x2, y2 = box["xyxy"]
    center = [(x1 + x2) / (2 * width), (y1 + y2) / (2 * height)]
    row.update(status="observed", track_id=box["track_id"], center=center)
    if config.get("camera_motion", "off") != "off":
        # This mode verifies identity continuity only; moving image coordinates cannot define enclosure activity.
        row["motion_status"] = "withheld_moving_camera"
        return row
    zones = [name for name, (x, y, w, h) in config["zones"].items() if x <= center[0] < x + w and y <= center[1] < y + h]
    if len(zones) == 1:
        row["zone"] = zones[0]
    elif len(zones) > 1:
        row["zone_status"] = "overlapping_zones"
    if previous and previous["status"] == "observed" and previous["track_id"] == row["track_id"]:
        dt = offset - previous["offset_seconds"]
        if 0 < dt <= config["max_gap_seconds"]:
            distance = math.hypot((center[0] - previous["center"][0]) * width,
                                  (center[1] - previous["center"][1]) * height) / math.hypot(width, height)
            if distance <= config["max_step_diagonals"]:
                row.update(step_diagonals=distance, speed_diagonals_per_second=distance / dt)
            else:
                row.update(status="implausible_track_jump", zone=None)
    return row


def infer_video(model_directory, output, config, *, video=None, session_path=None, clip_id=None, device="cpu", threads=2,
                provenance=None, backend="yolo"):
    require(backend in {"yolo", "hybrid", "sam3-hybrid", "sam2-hybrid"}, "unsupported detector backend")
    if backend == "sam2-hybrid":
        from .vision_memory import MemoryHybridPredictor, load_memory_bundle
        bundle = load_memory_bundle(model_directory)
        card = bundle[0]
    elif backend == "sam3-hybrid":
        from .vision_sam3 import Sam3HybridPredictor, load_sam3_bundle
        bundle = load_sam3_bundle(model_directory)
        card = bundle[0]
    elif backend == "hybrid":
        from .vision_hybrid import HybridPredictor, load_hybrid_bundle, validate_hybrid_config
        bundle = load_hybrid_bundle(model_directory)
        card = bundle[0]
    else:
        card = load_model_card(model_directory)
    config = validate_tracking_config({**config, "inference_image_size":
                                      config.get("inference_image_size", card["recipe"]["image_size"])})
    if backend in {"hybrid", "sam3-hybrid", "sam2-hybrid"}:
        from .vision_hybrid import validate_hybrid_config
        validate_hybrid_config(config)
    require(card["species"] == config["species"], "model and tracking detection targets differ")
    path, metadata, timeline = source_video(video, session_path, clip_id, provenance=provenance)
    require(not config.get("target_seed") or config["target_seed"]["source_sha256"] == metadata["sha256"],
            "target seed belongs to another source video")
    with keep_awake(), output_directory(output, "infer_video") as run, ExitStack() as cleanup:
        YOLO = runtime(run / "runtime", threads)
        check_device(device)
        import cv2
        if backend == "sam2-hybrid":
            model = MemoryHybridPredictor(model_directory,bundle,device,run / "memory",
                                          max_gap_seconds=config["max_gap_seconds"])
            cleanup.callback(model.close)
        elif backend == "sam3-hybrid":
            model = Sam3HybridPredictor(model_directory, bundle, device, run / "segmentation")
            cleanup.callback(model.close)
        elif backend == "hybrid":
            model = HybridPredictor(model_directory, bundle, device)
        else:
            model = YOLO(str(relative(Path(model_directory), card["weights"]["path"])), task="detect")
            require(list(model.names.values()) == card["class_names"], "checkpoint classes differ from model card")
        tracker = VideoTracker(config, metadata["width"], metadata["height"],
                               fuse_confirmation_score=backend == "yolo",
                               memory_association=backend == "sam2-hybrid" and card['recipe'].get('memory_slot_association')==1,
                               memory_pending_association=backend == "sam2-hybrid" and card['recipe'].get('memory_pending_association')==1)
        scene = SceneBoundary()
        camera = BackgroundMotion(config["confidence"], config["max_gap_seconds"]) if config.get("camera_motion", "off") != "off" else None
        withhold_motion = camera is not None or backend == "sam2-hybrid"
        target = SeededTarget(config, metadata["width"], metadata["height"]) if config.get("target_seed") else None
        # Reserve a readable banner even for small/portrait inputs. This is only a preview;
        # detections and original PTS continue to use source pixels and source timestamps.
        preview_width, preview_height = preview_geometry(metadata["width"], metadata["height"])
        canvas_width, canvas_height = max(640, preview_width), preview_height + 112
        writer = cv2.VideoWriter(str(run / "review.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                 config["sample_fps"], (canvas_width, canvas_height))
        require(writer.isOpened(), "review video encoder could not open output")
        previous, observed, count, distance = None, 0, 0, 0.0
        previous_tracks = {}
        review_queue, zone_samples = [], {name: 0 for name in config["zones"]}
        try:
            with (run / "observations.jsonl").open("xb") as stream:
                for frame, timing in sampled_frames(path, metadata, timeline, config["sample_fps"], scene=scene):
                    boundary = timing["scene_boundary"]
                    boundary_events = []
                    if boundary["cut"]:
                        boundary_events = tracker.reset_for_scene_change()
                        previous, previous_tracks = None, {}
                        if target:
                            target.expired = True
                    if backend == "sam2-hybrid":
                        boxes, detection_evidence = model.predict_frame(frame,offset_seconds=timing["offset_seconds"],
                                                                        scene_cut=boundary["cut"])
                    elif backend in {"hybrid", "sam3-hybrid"}:
                        boxes, detection_evidence = model.predict_frame(frame)
                    else:
                        boxes, detection_evidence = predict_frame(model, frame, device=device,
                            confidence=tracker.detector_confidence, nms_iou=tracker.options["nms_iou"],
                            image_size=config["inference_image_size"], slicing=config.get("inference_slicing", "off"),
                            anchor_confidence=config["confidence"], new_confidence=config.get("sliced_new_confidence"))
                    detector_candidates = boxes
                    camera_motion = camera.update(frame, boxes, timing["offset_seconds"], cut=boundary["cut"]) if camera else None
                    selection = None
                    if target:
                        boxes, selection = target.select(boxes, timing["offset_seconds"])
                    boxes, lost, events = tracker.update(boxes, timing["offset_seconds"], camera_motion=camera_motion)
                    events = boundary_events + events
                    tracks = [observation([box], previous_tracks.get(box["track_id"]), timing["offset_seconds"],
                                          metadata["width"], metadata["height"], config)
                              for box in boxes if box["track_id"] is not None]
                    for track, box in zip(tracks, (box for box in boxes if box["track_id"] is not None)):
                        track.update(segment_id=box["track_id"], identity_status=box["identity_status"])
                    previous_tracks = {track["track_id"]: track for track in tracks if track["track_id"] is not None}
                    row = observation(boxes, previous, timing["offset_seconds"], metadata["width"], metadata["height"], config)
                    if backend == "sam2-hybrid":
                        for observation_row in [row, *tracks]:
                            observation_row.update(step_diagonals=None,speed_diagonals_per_second=None,zone=None,
                                                   motion_status="withheld_experimental_memory")
                    row.update(frame_index=timing["frame_index"], pts=timing["pts"], time_base=timing["time_base"],
                               estimated_capture_at=timing["estimated_capture_at"], detections=boxes,
                               tracks=tracks, lost_tracks=lost, tracking_events=events,
                               target_selection=selection, detector_candidates=detector_candidates,
                               inference=detection_evidence,
                               scene_boundary=boundary,
                               review_offset_seconds=count / config["sample_fps"])
                    if camera:
                        row["camera_motion"] = camera_motion
                    stream.write(encode(row))
                    observed += row["status"] == "observed"
                    distance += row["step_diagonals"] or 0
                    if row["zone"] is not None:
                        zone_samples[row["zone"]] += 1
                    if row["status"] != "observed" or events or count % 30 == 0:
                        review_queue.append({"frame_index": row["frame_index"], "offset_seconds": row["offset_seconds"],
                                             "reason": row["status"] if row["status"] != "observed" else "periodic_audit",
                                             "tracking_events": events,
                                             "reviewed": False})
                    writer.write(render_review_frame(frame, row, config))
                    previous = row
                    count += 1
        finally:
            writer.release()
        require(count > 0, "no frames analyzed")
        require(digest(path) == metadata["sha256"], "source video changed during inference")
        _, review_frames, _ = probe(run / "review.mp4", {"max_clip_seconds": 610,
            "max_frames": 36000, "probe_timeout_seconds": 120})
        require(len(review_frames) == count, "review video encoder dropped frames; output is incomplete")
        report = {"schema_version": 1, "model_id": card["model_id"], "model_status": card["status"],
                  "source": metadata, "config": config, "sampled_frames": count,
                  "sampling_method": FRAME_SAMPLING_METHOD,
                  "observed_samples": observed, "observed_sample_fraction": observed / count,
                  "observed_path_diagonals": None if withhold_motion else distance,
                  "zone_observed_samples": None if withhold_motion else zone_samples,
                  "motion_measurement": "withheld_experimental_memory" if backend == "sam2-hybrid" else
                                        "withheld_moving_camera" if camera else "image_coordinates",
                  "units": "2D image-diagonal distance; not physical distance or 3D climbing height",
                  "coverage": "Missing/ambiguous intervals are unknown, never inactivity or normal behavior.",
                  "review_video_timing": "Derived constant-rate preview; original source frame/PTS mapping is in observations.jsonl.",
                  "review_video_dimensions": {"width": canvas_width, "height": canvas_height,
                                              "source_image_resized_for_preview_only": True},
                  "review_render_version": 4, "tracking": tracker.summary(),
                  "scene_continuity": scene.summary(),
                  "actual_inference_device": detection_evidence["actual_device"], "detector_backend": backend,
                  "expected_occupants": 1,
                  "target_selection_mode": "initial_box_guided" if target else "automatic",
                  "production_validated": False, "behavior_classification": "not_performed", "anomaly_detection": "not_performed"}
        if backend == "hybrid":
            report["model_package_id"] = card["package_id"]
        elif backend in {"sam3-hybrid", "sam2-hybrid"}:
            report["model_package_id"] = card["model_id"]
        save_artifact(run / "summary.json", report)
        save_artifact(run / "review-queue.json", review_queue)
    return report


def render_saved_review(analysis, video, output):
    """Redraw stored predictions without changing weights, observations, or metrics."""
    import cv2
    import subprocess
    cv2.setNumThreads(2)
    analysis = Path(analysis)
    summary = read_json(analysis / "summary.json")
    observation_hash = digest(analysis / "observations.jsonl")
    rows = [json.loads(line) for line in (analysis / "observations.jsonl").read_text().splitlines()]
    saved_indices = {row["frame_index"] for row in rows}
    require(len(saved_indices) == len(rows), "duplicate saved prediction frame")
    path, metadata, timeline = source_video(video=video, provenance=summary["source"]["provenance"])
    require(metadata["sha256"] == summary["source"]["sha256"], "preview source differs from inference")
    config = validate_tracking_config(summary["config"])
    width, height = preview_geometry(metadata["width"], metadata["height"])
    with output_directory(output, "render_saved_review") as run:
        writer = cv2.VideoWriter(str(run / "review.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                 config["sample_fps"], (max(640, width), height + 112))
        require(writer.isOpened(), "review encoder could not open output")
        count = 0
        try:
            with closing(decoded_frames(path, metadata, timeline)) as frames:
                for frame, timing in frames:
                    if timing["frame_index"] not in saved_indices:
                        continue
                    require(count < len(rows), "saved observation count differs")
                    row = rows[count]
                    require(row["frame_index"] == timing["frame_index"] and row["pts"] == timing["pts"] and
                            row["offset_seconds"] == timing["offset_seconds"], "saved prediction frame differs")
                    writer.write(render_review_frame(frame, row, config))
                    count += 1
        finally:
            writer.release()
        require(count == len(rows), "saved observations were not all rendered")
        require(digest(path) == metadata["sha256"] and digest(analysis / "observations.jsonl") == observation_hash,
                "preview inputs changed during render")
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(run / "review.mp4"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart",
                        str(run / "review-browser.mp4")], check=True, timeout=180)
        _, frames, _ = probe(run / "review-browser.mp4", {"max_clip_seconds":610, "max_frames":36000, "probe_timeout_seconds":120})
        require(len(frames) == count, "preview encoder dropped frames")
        manifest = {"render_version":4, "source_sha256":metadata["sha256"], "observations_sha256":observation_hash,
                    "model_id":summary["model_id"], "confidence":config["confidence"], "frames":count,
                    "model_rerun":False, "metrics_changed":False, "preview_sha256":digest(run / "review-browser.mp4")}
        save_artifact(run / "render.json", manifest)
    return manifest


def export_tracking_review(analysis, video, output, *, limit=40, spacing_seconds=1.0, selection="failures"):
    """Export unlabeled frames; distinguish failure mining from uniform and consecutive samples."""
    import cv2
    number(limit, 1, 100)
    require(type(limit) is int, "review limit must be an integer")
    number(spacing_seconds, 0.1, 60)
    require(selection in {"failures", "uniform", "consecutive"}, "unknown review selection")
    analysis = Path(analysis)
    require(read_json(analysis / "status.json")["state"] == "complete", "analysis must be complete")
    summary = read_json(analysis / "summary.json")
    path, metadata, timeline = source_video(video, provenance=summary["source"]["provenance"])
    require(metadata["sha256"] == summary["source"]["sha256"], "review source differs from analysis")
    observations_hash = digest(analysis / "observations.jsonl")
    rows = [json.loads(line) for line in (analysis / "observations.jsonl").read_text().splitlines()]
    priority = {"ambiguous_association": 0, "implausible_track_jump": 1,
                "ambiguous_multiple_detections": 2, "track_pending": 3, "no_confident_track": 4, "observed": 5}
    require(bool(rows), "analysis has no observations")
    if selection == "consecutive":
        chosen = rows[:limit]
    elif selection == "uniform":
        count = min(limit, len(rows))
        chosen = [rows[round(i * (len(rows)-1) / (count-1))] for i in range(count)] if count > 1 else rows[:1]
    else:
        chosen = []
        for row in sorted(rows, key=lambda row: (priority[row["status"]], row["offset_seconds"])):
            if all(abs(row["offset_seconds"] - other["offset_seconds"]) >= spacing_seconds for other in chosen):
                chosen.append(row)
            if len(chosen) >= limit:
                break
    selected = {row["frame_index"]: row for row in chosen}
    with output_directory(output, "export_unreviewed_tracking_examples") as run:
        (run / "images").mkdir()
        records = []
        with closing(decoded_frames(path, metadata, timeline)) as frames:
            for frame, timing in frames:
                if timing["frame_index"] not in selected:
                    continue
                row = selected[timing["frame_index"]]
                require(row["pts"] == timing["pts"] and row["offset_seconds"] == timing["offset_seconds"], "review timestamp differs")
                image_name = f"images/frame-{timing['frame_index']:06d}.png"
                require(cv2.imwrite(str(run / image_name), frame), "review frame could not be saved")
                records.append({"image": image_name, "sha256": digest(run / image_name),
                                "original_frame": timing, "reason": row["status"],
                                "prediction_suggestions": row.get("detector_candidates", row["detections"]), "tracking_events": row.get("tracking_events", []),
                                "group_id": metadata["original_video_id"], "reference_boxes": None,
                                "reference_identity": None, "review_method": None, "reviewed": False})
        require(len(records) == len(chosen), "selected review frames were not all decoded")
        require(digest(path) == metadata["sha256"] and digest(analysis / "observations.jsonl") == observations_hash,
                "review inputs changed during export")
        manifest = {"schema_version": 1, "source": summary["source"], "model_id": summary["model_id"],
                    "observations_sha256": observations_hash, "records": records, "ready_for_training": False,
                    "purpose": "Review body boxes and within-video identity; predictions are not reference labels.",
                    "split_policy": "Keep every frame from this original recording in one split."}
        save_artifact(run / "review.json", manifest)
        references = {"schema_version": 1, "source_sha256": metadata["sha256"],
                      "evaluation_target": "visible_lizard_extent",
                      "selection": "failure_mining" if selection == "failures" else selection,
                      "records": [{"frame_index": r["original_frame"]["frame_index"],
                                   "pts": r["original_frame"]["pts"], "offset_seconds": r["original_frame"]["offset_seconds"],
                                   "image": r["image"], "image_sha256": r["sha256"],
                                   "visibility": None, "reference_boxes": None, "reference_identity": None,
                                   "reviewed": False, "review_method": None, "reviewer": None} for r in records]}
        save_artifact(run / "references.json", references)
    return {"frames": len(records), "ready_for_training": False, "source_sha256": metadata["sha256"]}
