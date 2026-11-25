import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

from .bundle import export_bundle, import_bundle
from .core import RecorderError, Session, atomic_json, create_session, encode, lock, now, number, read_json, require, validate_config
from .media import ingest, replay
from .records import active_labels, boris_labels, habitat_rows, import_labels, import_sensors, import_thermal, jsonl, saved_rows


def report_failure(root, exc):
    if isinstance(exc, RecorderError) and str(exc) == "another writer is active":
        return
    try:
        with Session(root) as session:
            if session.manifest["state"] != "active":
                return
            code = "collection_interrupted" if isinstance(exc, KeyboardInterrupt) else "collection_failed"
            # Reserve a small control write outside the data quota so failure stays visible.
            session.event(code, {"error_type": type(exc).__name__, "reason": str(exc)[:256]},
                          {"state": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", "ended_at": now()}, control=True)
    except (OSError, ValueError, KeyError, RecorderError):
        print("failure event could not be saved; preserve partial files and run recover", file=sys.stderr)


def record(root, config_path, seconds, once=False):
    number(seconds, 0.1, 3600)
    config_path = config_path.resolve()
    config = validate_config(read_json(config_path))
    initial = Session(root)
    require({k: v for k, v in config.items() if k != "input"} == initial.manifest["config"], "record config differs from session snapshot")
    inbox = Path(config["input"]["inbox"])
    inbox = (config_path.parent / inbox).resolve() if not inbox.is_absolute() else inbox.resolve()
    require(inbox.is_dir(), "inbox does not exist")
    deadline = time.monotonic() + seconds
    checked = {}
    added = 0
    idle_since = time.monotonic()
    idle_reported = False
    with lock(Path(root) / ".record.lock"):
        with Session(root) as session:
            session.ready(active=True)
            session.event("collector_started", {"adapter": "finalized_file"})
        while time.monotonic() < deadline:
            with Session(root) as session:
                if session.manifest["state"] != "active":
                    return {"added": added, "reason": "session_stopped"}
            for descriptor in sorted(inbox.glob("*.capture.json")):
                if not once and time.monotonic() >= deadline:
                    break
                require(not descriptor.is_symlink(), "descriptor symlinks are not supported")
                stamp = (descriptor.stat().st_size, descriptor.stat().st_mtime_ns)
                if checked.get(descriptor.name) == stamp:
                    continue
                with Session(root) as session:
                    if session.manifest["state"] != "active":
                        return {"added": added, "reason": "session_stopped"}
                    result = ingest(session, descriptor)
                    if not result["duplicate"]:
                        added += 1
                        if idle_reported:
                            session.event("source_resumed", {"camera_id": read_json(descriptor)["camera_id"], "meaning": "new finalized file; not hardware reconnection proof"})
                        idle_since = time.monotonic()
                        idle_reported = False
                checked[descriptor.name] = stamp
            if once:
                break
            if not idle_reported and time.monotonic() - idle_since >= config["input"]["idle_warning_seconds"]:
                with Session(root) as session:
                    session.event("source_idle", {"meaning": "no new finalized clip; camera connection unknown"})
                idle_reported = True
            time.sleep(min(config["input"]["poll_seconds"], max(0, deadline - time.monotonic())))
        with Session(root) as session:
            session.event("collector_stopped", {"reason": "once" if once else "duration_limit", "added": added})
    return {"added": added, "session_state": "active", "reason": "once" if once else "duration_limit"}


def behavior_dataset(path):
    payload = read_json(path)
    require(isinstance(payload, dict) and payload.get("dataset_kind") in {"real", "test"} and
            isinstance(payload.get("rows"), list), "behavior dataset needs dataset_kind and rows")
    return payload


def behavior_windows(path):
    payload = read_json(path)
    require(isinstance(payload, dict) and isinstance(payload.get("windows"), list),
            "behavior windows file needs windows")
    return payload["windows"]


def active_behavior_labels(path):
    rows = jsonl(path)
    ids = set()
    replaced = set()
    for row in rows:
        require(isinstance(row.get("label_id"), str) and row["label_id"], "label ID required")
        require(row["label_id"] not in ids, "duplicate label ID")
        ids.add(row["label_id"])
        supersedes = row.get("supersedes")
        require(supersedes is None or isinstance(supersedes, str), "invalid supersedes label ID")
        if supersedes:
            replaced.add(supersedes)
    require(replaced <= ids, "superseded label is missing")
    return [row for row in rows if row["label_id"] not in replaced]


def parser():
    p = argparse.ArgumentParser(description="Offline portable behavior recorder (Python + FFmpeg)")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("start", "ingest", "record", "status", "stop", "resume", "verify", "recover", "replay", "label", "labels-import", "labels-export", "sensors", "thermal", "event", "export"):
        command = commands.add_parser(name)
        command.add_argument("session", type=Path)
        if name in {"start", "record"}:
            command.add_argument("--config", type=Path, required=True)
        if name in {"ingest", "labels-import", "labels-export", "sensors", "thermal", "export"}:
            command.add_argument("path", type=Path)
        if name == "record":
            command.add_argument("--seconds", type=float, default=30)
            command.add_argument("--once", action="store_true")
        if name == "status":
            command.add_argument("--real-only", action="store_true")
        if name in {"label", "replay"}:
            command.add_argument("clip_id")
            command.add_argument("--start", type=float, default=0)
        if name == "replay":
            command.add_argument("--seconds", type=float, default=10)
            command.add_argument("--window", action="store_true")
        if name in {"label", "labels-import"}:
            command.add_argument("--animal")
            command.add_argument("--annotator", required=name == "label")
            command.add_argument("--visibility", choices=["visible", "partial", "unobservable"], required=name == "label")
            command.add_argument("--certainty", choices=["certain", "uncertain"], required=name == "label")
        if name == "label":
            command.add_argument("--assessment", choices=["normal", "anomaly", "uncertain"])
            command.add_argument("--end", type=float, required=True)
            command.add_argument("--behavior")
            command.add_argument("--note", default="")
            command.add_argument("--supersedes")
        if name == "labels-import":
            command.add_argument("--format", choices=["native", "boris"], default="native")
            command.add_argument("--clip")
            command.add_argument("--boris-zero-offset", action="store_true")
        if name == "sensors":
            command.add_argument("--format", choices=["native", "habitat"], default="native")
            command.add_argument("--units", type=Path)
            command.add_argument("--enclosure")
        if name == "event":
            command.add_argument("code", choices=["camera_disconnected", "camera_reconnected", "frame_drop_reported", "clock_changed", "observation_note"])
            command.add_argument("--camera", required=True)
            command.add_argument("--note", required=True)
            command.add_argument("--observed-at")
    command = commands.add_parser("import")
    command.add_argument("bundle", type=Path)
    command.add_argument("destination", type=Path)
    command.add_argument("--max-bytes", type=int, default=10 * 1024**3)
    command = commands.add_parser("behavior-fit", help="fit behavior classifier from reviewed temporal windows")
    command.add_argument("training", type=Path)
    command.add_argument("output", type=Path)
    command = commands.add_parser("behavior-evaluate", help="evaluate behavior classifier on held-out recording groups")
    command.add_argument("model", type=Path)
    command.add_argument("evaluation", type=Path)
    command.add_argument("output", type=Path)
    command = commands.add_parser("behavior-examples", help="join tracked windows with active human behavior labels")
    command.add_argument("windows", type=Path)
    command.add_argument("labels", type=Path)
    command.add_argument("clip_id")
    command.add_argument("output", type=Path)
    command.add_argument("--dataset-kind", choices=["real", "test"], required=True)
    return p


def run(args):
    if args.command == "start":
        return {"session_id": create_session(args.session, read_json(args.config)), "session": str(args.session)}
    if args.command == "import":
        return import_bundle(args.bundle, args.destination, args.max_bytes)
    if args.command == "behavior-fit":
        from .behavior_classifier import fit
        dataset = behavior_dataset(args.training)
        require(not args.output.exists(), "behavior model output already exists")
        model = fit(dataset["rows"], dataset_kind=dataset["dataset_kind"])
        atomic_json(args.output, model)
        return {"model_id": model["model_id"], "status": model["status"], "output": str(args.output)}
    if args.command == "behavior-evaluate":
        from .behavior_classifier import evaluate
        dataset = behavior_dataset(args.evaluation)
        require(not args.output.exists(), "behavior evaluation output already exists")
        report = evaluate(read_json(args.model), dataset["rows"])
        atomic_json(args.output, report)
        return report
    if args.command == "behavior-examples":
        from .behavior_classifier import examples_from_windows
        require(not args.output.exists(), "behavior examples output already exists")
        examples = examples_from_windows(behavior_windows(args.windows), active_behavior_labels(args.labels),
                                         clip_id=args.clip_id, dataset_kind=args.dataset_kind)
        atomic_json(args.output, examples)
        return {"rows": len(examples["rows"]), "excluded": {key: len(value) for key, value in examples["excluded"].items()},
                "output": str(args.output)}
    if args.command == "record":
        return record(args.session, args.config, args.seconds, args.once)
    # Readers use an immutable manifest snapshot; writers hold a filesystem lock.
    if args.command in {"status", "verify", "replay"}:
        session = Session(args.session)
        if args.command == "verify":
            failures = session.verify()
            require(not failures, "; ".join(failures))
            return {"ok": True, "session_id": session.manifest["session_id"], "entries": len(session.manifest["entries"])}
        if args.command == "replay":
            return replay(session, args.clip_id, args.start, args.seconds, args.window)
        clips = list(session.items("clip"))
        if args.real_only:
            clips = [c for c in clips if c["provenance"] == "real_camera"]
        return {"session_id": session.manifest["session_id"], "state": session.manifest["state"],
                "dataset_kind": session.manifest["config"]["dataset_kind"], "clips": clips,
                "active_labels": active_labels(session), "sensor_records": len(saved_rows(session, "sensors")),
                "thermal_records": len(saved_rows(session, "thermal")),
                "uncommitted": [p.relative_to(session.root).as_posix() for p in session.unresolved()],
                "events": list(session.items("event"))}
    with Session(args.session) as session:
        if args.command == "recover":
            return {"quarantined": session.recover(), "state": session.manifest["state"]}
        session.ready()
        if args.command in {"stop", "resume"}:
            active = args.command == "resume"
            if active:
                require(session.manifest["state"] in {"failed", "interrupted"}, "resume requires failed/interrupted session; stopped session is final")
                require(not session.verify(), "repair corrupt/missing data before resume")
            session.event("session_resumed" if active else "session_stopped", updates={"state": "active" if active else "stopped", "ended_at": None if active else now()})
            return {"state": session.manifest["state"]}
        if args.command == "ingest":
            return ingest(session, args.path)
        if args.command == "sensors":
            rows = jsonl(args.path)
            if args.format == "habitat":
                require(args.units is not None and args.enclosure is not None, "Habitat import requires --units and --enclosure")
                rows = habitat_rows(rows, read_json(args.units), args.enclosure)
            return import_sensors(session, rows)
        if args.command == "thermal":
            return import_thermal(session, jsonl(args.path))
        if args.command == "label":
            row = {"label_id": str(uuid4()), "clip_id": args.clip_id, "animal_id": args.animal,
                   "start_seconds": args.start, "end_seconds": args.end, "behavior": args.behavior,
                   "visibility": args.visibility, "certainty": args.certainty, "annotator": args.annotator,
                   "note": args.note, "supersedes": args.supersedes}
            if args.assessment is not None:
                row["assessment"] = args.assessment
            return {**import_labels(session, [row]), "label_id": row["label_id"]}
        if args.command == "labels-import":
            if args.format == "boris":
                require(args.clip and args.annotator and args.boris_zero_offset and args.visibility and args.certainty,
                        "BORIS requires --clip, --annotator, --visibility, --certainty and --boris-zero-offset")
                rows = boris_labels(args.path, args.clip, args.animal, args.annotator, args.visibility, args.certainty)
            else:
                rows = jsonl(args.path)
            return import_labels(session, rows)
        if args.command == "labels-export":
            with args.path.open("xb") as stream:
                # Include history so a round trip preserves supersedes links.
                for row in saved_rows(session, "labels"):
                    stream.write(encode(row))
            return {"labels": str(args.path)}
        if args.command == "event":
            from .core import timestamp
            from .media import camera_for
            camera_for(session, args.camera)
            timestamp(args.observed_at)
            session.add("event", {"event_id": str(uuid4()), "code": args.code, "observed_at": args.observed_at,
                                  "received_at": now(), "details": {"camera_id": args.camera, "note": args.note,
                                                                      "evidence": "operator_report"}})
            return {"recorded": args.code}
        if args.command == "export":
            return export_bundle(session, args.path)


def main(argv=None):
    args = parser().parse_args(argv)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (RecorderError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile, KeyboardInterrupt) as exc:
        if args.command in {"ingest", "record"} and (args.session / "manifest.json").exists():
            report_failure(args.session, exc)
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
