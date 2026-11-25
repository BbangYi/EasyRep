"""Receive finalized clips without changing original bytes or inventing capture time."""
from datetime import timedelta
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from .core import RecorderError, clock, digest, encode, identifier, now, number, read_json, relative, require, timestamp


def camera_for(session, camera_id):
    for camera in session.manifest["config"]["cameras"]:
        if camera["camera_id"] == camera_id:
            return camera
    raise RecorderError("unknown camera ID")


def validate_origin(session, provenance):
    allowed = {"real_camera"} if session.manifest["config"]["dataset_kind"] == "real" else {"synthetic_test", "replay_test"}
    require(provenance in allowed, "provenance does not match session dataset_kind")


def validate_descriptor(session, descriptor):
    required = {"schema_version", "input_id", "camera_id", "file", "sha256", "recording_id", "sequence",
                "provenance", "captured_at", "capture_clock", "placement_revision", "calibration_revision"}
    require(isinstance(descriptor, dict) and set(descriptor) == required, "invalid clip descriptor fields")
    require(type(descriptor["schema_version"]) is int and descriptor["schema_version"] == 1, "unsupported descriptor schema")
    for key in ("input_id", "camera_id", "recording_id"):
        identifier(descriptor[key])
    require(type(descriptor["sequence"]) is int and descriptor["sequence"] >= 0, "sequence must be a nonnegative integer")
    require(isinstance(descriptor["sha256"], str) and len(descriptor["sha256"]) == 64 and all(c in "0123456789abcdef" for c in descriptor["sha256"]), "SHA-256 required for finalized input")
    validate_origin(session, descriptor["provenance"])
    camera = camera_for(session, descriptor["camera_id"])
    require(camera["connection"] == "finalized_file", "camera slot is unconfigured; confirm file producer and start a new session")
    require(camera["kind"] in {"rgb", "thermal_color"}, "numeric thermal camera requires thermal JSONL input")
    for key in ("placement_revision", "calibration_revision"):
        require(descriptor[key] == camera[key], f"{key} differs from session camera snapshot; start a new session")
    captured = timestamp(descriptor["captured_at"])
    clock(descriptor["capture_clock"])
    require((captured is None) == (descriptor["capture_clock"]["source"] == "unknown"), "capture time and clock source disagree")
    return camera


def probe(path, policy):
    base = ["ffprobe", "-v", "error", "-threads", "1", "-protocol_whitelist", "file",
            "-format_whitelist", "mov,matroska,webm,avi", "-of", "json"]
    try:
        result = subprocess.run([*base, "-show_streams", "-show_format", str(path)], capture_output=True,
                                timeout=policy["probe_timeout_seconds"], check=True)
        header = json.loads(result.stdout)
        videos = [s for s in header["streams"] if s["codec_type"] == "video"]
        require(len(videos) == 1, "exactly one video stream per camera clip is required")
        video = videos[0]
        duration = float(video.get("duration", header.get("format", {}).get("duration", 0)))
        number(duration, 0.001, policy["max_clip_seconds"])
        # Bound decode time/frames even when container metadata is corrupt.
        result = subprocess.run([*base, "-select_streams", "v:0", "-read_intervals", f"%+#{policy['max_frames'] + 1}",
                                 "-show_frames", "-show_entries", "frame=pts,best_effort_timestamp,duration,pkt_duration,key_frame",
                                 str(path)], capture_output=True, timeout=policy["probe_timeout_seconds"], check=True)
        require(not result.stderr.strip(), "decoder reported damaged frames")
        frames = json.loads(result.stdout)["frames"]
        require(0 < len(frames) <= policy["max_frames"], "decoded frame count exceeds limit or is empty")
        base_time = Fraction(video["time_base"])
        require(base_time > 0, "invalid video time_base")
        return video, frames, duration
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RecorderError("video probe failed or timed out") from exc
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise RecorderError("invalid video timing metadata") from exc


def copy_clip(session, source, target, expected_hash):
    require(source.is_file() and not source.is_symlink(), "input must be a regular finalized file")
    policy = session.manifest["config"]["storage"]
    before = source.stat()
    require(0 < before.st_size <= policy["max_clip_bytes"], "clip byte limit exceeded")
    session.space(before.st_size + 16384)
    sha = hashlib.sha256()
    count = 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        for chunk in iter(lambda: incoming.read(1024**2), b""):
            count += len(chunk)
            require(count <= before.st_size, "input changed while copying")
            session.space(len(chunk))
            outgoing.write(chunk)
            sha.update(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    after = source.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino), "input changed while copying")
    require(count == before.st_size and sha.hexdigest() == expected_hash, "input checksum mismatch")


def frame_records(frames, video, captured_at, capture_clock, expected_fps):
    time_base = Fraction(video["time_base"])
    first = frames[0].get("pts")
    previous = None
    anchor = timestamp(captured_at)
    records, anomalies = [], []
    for index, frame in enumerate(frames):
        pts = frame.get("pts")
        offset = float((pts - first) * time_base) if pts is not None and first is not None else None
        estimate = (anchor + timedelta(seconds=offset)).isoformat() if anchor is not None and offset is not None else None
        records.append({"frame_index": index, "pts": pts, "time_base": video["time_base"],
                        "best_effort_timestamp": frame.get("best_effort_timestamp"),
                        "duration_pts": frame.get("duration", frame.get("pkt_duration")), "key_frame": bool(frame.get("key_frame")),
                        "offset_seconds": offset, "captured_at": captured_at if index == 0 else None,
                        "estimated_capture_at": estimate, "estimate_method": "first_frame_anchor_plus_pts" if estimate else None,
                        "capture_clock": capture_clock, "host_frame_received_at": None})
        if pts is None:
            anomalies.append({"code": "frame_pts_missing", "frame_index": index})
        elif previous is not None:
            delta = float((pts - previous) * time_base)
            if delta <= 0:
                anomalies.append({"code": "nonmonotonic_pts", "frame_index": index, "delta_seconds": delta})
            elif expected_fps and delta > 1.5 / expected_fps:
                anomalies.append({"code": "pts_gap_possible_drop", "frame_index": index, "delta_seconds": delta,
                                  "missing_frames": None, "evidence": "expected_fps_vs_pts; not hardware drop proof"})
        if pts is not None:
            previous = pts
    return records, anomalies


def ingest(session, descriptor_path):
    session.ready(active=True)
    descriptor_path = Path(descriptor_path).resolve()
    descriptor = read_json(descriptor_path)
    camera = validate_descriptor(session, descriptor)
    source = relative(descriptor_path.parent, descriptor["file"])
    require(source.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi"}, "unsupported container; finalize MP4/MKV/MOV/AVI first")
    fingerprint = hashlib.sha256(encode(descriptor)).hexdigest()
    earlier = list(session.items("clip"))
    for old in earlier:
        if old["input_id"] == descriptor["input_id"]:
            require(old["descriptor_sha256"] == fingerprint, "input ID conflict")
            require(source.is_file() and digest(source) == descriptor["sha256"], "duplicate input checksum mismatch")
            return {"clip_id": old["clip_id"], "duplicate": True}
        if (old["camera_id"], old["recording_id"], old["sequence"]) == (descriptor["camera_id"], descriptor["recording_id"], descriptor["sequence"]):
            raise RecorderError("camera recording sequence conflict")
    received_at = now()
    folder = session.begin()
    clip_id = str(uuid4())
    target = folder / f"original{source.suffix.lower()}"
    copy_clip(session, source, target, descriptor["sha256"])
    policy = session.manifest["config"]["storage"]
    video, frames, container_duration = probe(target, policy)
    rows, anomalies = frame_records(frames, video, descriptor["captured_at"], descriptor["capture_clock"], camera["expected_fps"])
    timeline_available = all(row["pts"] is not None for row in rows) and not any(a["code"] == "nonmonotonic_pts" for a in anomalies)
    last_duration = rows[-1]["duration_pts"]
    duration = (rows[-1]["offset_seconds"] + float(last_duration * Fraction(video["time_base"]))) if timeline_available and last_duration else None
    if duration is not None:
        number(duration, 0.001, policy["max_clip_seconds"])
    # No guessed frame period: uncertain end timing prevents time-based labels.
    timeline_available = timeline_available and duration is not None
    prior = [c for c in earlier if (c["camera_id"], c["recording_id"]) == (descriptor["camera_id"], descriptor["recording_id"])]
    expected = max((c["sequence"] for c in prior), default=-1) + 1
    if descriptor["sequence"] > expected:
        anomalies.append({"code": "missing_clip_sequence", "from_sequence": expected, "to_sequence": descriptor["sequence"] - 1})
    elif descriptor["sequence"] < expected:
        anomalies.append({"code": "out_of_order_clip", "sequence": descriptor["sequence"]})
    prefix = f"entries/{folder.name}"
    record = {**{k: v for k, v in descriptor.items() if k != "file"}, "clip_id": clip_id,
              "descriptor_sha256": fingerprint, "original_video_id": f"sha256:{descriptor['sha256']}",
              "animal_ids": [a["animal_id"] for a in session.manifest["config"]["animals"]],
              "enclosure_id": camera["enclosure_id"], "camera_kind": camera["kind"],
              "media_path": f"{prefix}/{target.name}", "frames_path": f"{prefix}/frames.jsonl",
              "events_path": f"{prefix}/events.jsonl", "host_received_at": received_at,
              "host_received_meaning": "finalized_file_ingest_start; not frame capture", "indexed_at": now(),
              "duration_seconds": duration, "container_duration_seconds": container_duration,
              "timeline_available": timeline_available, "frame_count": len(rows),
              "first_pts": rows[0]["pts"], "last_pts": rows[-1]["pts"], "time_base": video["time_base"],
              "codec": video["codec_name"], "width": video["width"], "height": video["height"],
              "dropped_frames": None, "hardware_synchronized": False, "unlabeled_is_unknown": True}
    for name, items in (("frames.jsonl", rows), ("events.jsonl", anomalies)):
        data = b"".join(encode(item) for item in items)
        session.space(len(data) + len(encode(record)) + 4096)
        with (folder / name).open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    session.commit(folder, "clip", record)
    return {"clip_id": clip_id, "duplicate": False, "frames": len(rows), "anomalies": anomalies}


def replay(session, clip_id, start=0, seconds=10, window=False):
    clip = session.clip(clip_id)
    number(start)
    number(seconds, 0.01, 60)
    require(start < (clip["duration_seconds"] or clip["container_duration_seconds"]), "replay start outside clip")
    path = relative(session.root, clip["media_path"])
    require(digest(path) == clip["sha256"], "media checksum mismatch")
    base = ["-v", "error", "-threads", "1", "-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm,avi"]
    if window:
        command = ["ffplay", *base, "-autoexit", "-ss", str(start), "-t", str(seconds), str(path)]
    else:
        command = ["ffmpeg", "-nostdin", *base, "-ss", str(start), "-i", str(path), "-t", str(seconds), "-map", "0:v:0", "-threads", "1", "-f", "null", "-"]
    subprocess.run(command, check=True, timeout=seconds + 30)
    return {"clip_id": clip_id, "provenance": clip["provenance"], "replay_only": True, "window": window}
