import copy
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from behavior_recorder.bundle import export_bundle, import_bundle
from behavior_recorder.cli import main, record
from behavior_recorder.core import RecorderError, Session, atomic_json, create_session, digest, read_json, relative, validate_config
from behavior_recorder.media import frame_records, ingest, replay
from behavior_recorder.records import active_labels, boris_labels, habitat_rows, import_labels, import_sensors, import_thermal, jsonl, saved_rows

ROOT = Path(__file__).resolve().parents[1]


class RecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.video = Path(cls.fixture.name) / "test.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5",
                        "-t", "2", "-c:v", "mpeg4", "-threads", "1", "-q:v", "8", str(cls.video)], check=True, timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "session"
        self.inbox = self.base / "inbox"
        self.inbox.mkdir()
        shutil.copyfile(self.video, self.inbox / "test.mp4")
        self.config = read_json(ROOT / "examples/config.test.json")
        self.config["input"].update(inbox="inbox", poll_seconds=0.1, idle_warning_seconds=1)
        self.config_path = self.base / "config.json"
        atomic_json(self.config_path, self.config)
        create_session(self.root, self.config)
        self.descriptor = {"schema_version": 1, "input_id": "input-1", "camera_id": "rgb-01", "file": "test.mp4",
                           "sha256": digest(self.video), "recording_id": "recording-1", "sequence": 0,
                           "provenance": "synthetic_test", "captured_at": None,
                           "capture_clock": {"source": "unknown", "accuracy_ms": None},
                           "placement_revision": None, "calibration_revision": None}
        self.descriptor_path = self.inbox / "test.capture.json"
        atomic_json(self.descriptor_path, self.descriptor)

    def ingest(self):
        with Session(self.root) as session:
            return ingest(session, self.descriptor_path)["clip_id"]

    def label(self, clip_id):
        return {"label_id": "label-1", "clip_id": clip_id, "animal_id": "test-subject", "start_seconds": 0.2,
                "end_seconds": 1.2, "behavior": None, "visibility": "unobservable", "certainty": "uncertain",
                "annotator": "test-operator", "note": "synthetic fixture; not animal behavior", "supersedes": None}

    def test_end_to_end_relocation_and_replay(self):
        self.assertEqual(record(self.root, self.config_path, 1, once=True)["added"], 1)
        with Session(self.root) as session:
            clip = next(session.items("clip"))
            self.assertEqual(clip["frame_count"], 10)
            self.assertEqual(clip["duration_seconds"], 2)
            self.assertIsNone(clip["captured_at"])
            self.assertEqual(digest(relative(self.root, clip["media_path"])), digest(self.video))
            frames = jsonl(relative(self.root, clip["frames_path"]))
            self.assertEqual(frames[-1]["offset_seconds"], 1.8)
            self.assertIsNone(frames[-1]["host_frame_received_at"])
            import_labels(session, [self.label(clip["clip_id"])])
            import_sensors(session, jsonl(ROOT / "examples/sensors.test.jsonl"))
            import_thermal(session, jsonl(ROOT / "examples/thermal.test.jsonl"))
            session.event("session_stopped", updates={"state": "stopped", "ended_at": "2026-01-01T00:00:00Z"})
            bundle = self.base / "recording.zip"
            export_bundle(session, bundle)
            expected_id = session.manifest["session_id"]
        imported = self.base / "imported"
        import_bundle(bundle, imported)
        relocated = self.base / "another-pc" / "different-name"
        relocated.parent.mkdir()
        shutil.move(str(imported), str(relocated))
        loaded = Session(relocated)
        self.assertEqual(loaded.manifest["session_id"], expected_id)
        self.assertEqual(loaded.verify(), [])
        self.assertEqual(active_labels(loaded)[0]["clip_id"], clip["clip_id"])
        self.assertEqual(saved_rows(loaded, "thermal")[0]["values"][1][0], None)
        self.assertEqual(saved_rows(loaded, "sensors")[0]["readings"][1]["quality"], "missing")
        self.assertTrue(replay(loaded, clip["clip_id"], seconds=0.4)["replay_only"])
        self.assertNotIn(str(self.base), json.dumps(loaded.manifest))
        with loaded:
            updated_label = {**self.label(clip["clip_id"]), "label_id": "label-after-move", "supersedes": "label-1", "note": "edited after relocation"}
            import_labels(loaded, [updated_label])
            export_bundle(loaded, self.base / "export-after-move.zip")
        self.assertEqual(active_labels(Session(relocated))[0]["label_id"], "label-after-move")

    def test_h264_bframes_nonzero_pts_preserved(self):
        video = self.inbox / "bframes.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5",
                        "-t", "2", "-c:v", "libx264", "-threads", "1", "-bf", "2", "-g", "5", "-output_ts_offset", "7", str(video)], check=True, timeout=15)
        self.descriptor.update(file=video.name, sha256=digest(video))
        atomic_json(self.descriptor_path, self.descriptor)
        clip_id = self.ingest()
        loaded = Session(self.root)
        clip = loaded.clip(clip_id)
        self.assertEqual(clip["frame_count"], 10)
        self.assertGreater(clip["first_pts"], 0)
        self.assertEqual(clip["duration_seconds"], 2)
        rows = jsonl(relative(loaded.root, clip["frames_path"]))
        self.assertEqual(rows[0]["offset_seconds"], 0)
        self.assertEqual(rows[-1]["offset_seconds"], 1.8)
        self.assertEqual(digest(relative(loaded.root, clip["media_path"])), digest(video))

    def test_empty_session_and_test_filter(self):
        self.assertEqual(list(Session(self.root).items("clip")), [])
        self.ingest()
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(main(["status", str(self.root), "--real-only"]), 0)
        self.assertEqual(json.loads(output.getvalue())["clips"], [])

    def test_idempotency_and_identity_conflicts(self):
        clip_id = self.ingest()
        with Session(self.root) as session:
            self.assertEqual(ingest(session, self.descriptor_path), {"clip_id": clip_id, "duplicate": True})
            self.descriptor["sequence"] = 1
            atomic_json(self.descriptor_path, self.descriptor)
            with self.assertRaisesRegex(RecorderError, "ID conflict"):
                ingest(session, self.descriptor_path)

    def test_multiple_cameras_keep_identity_and_same_original_group(self):
        self.ingest()
        with Session(self.root) as session:
            # Create a separate session configuration before capture; no in-session revision edits.
            other = self.base / "multi"
            config = copy.deepcopy(self.config)
            second = {**config["cameras"][0], "camera_id": "rgb-02"}
            config["cameras"].append(second)
            create_session(other, config)
        with Session(other) as session:
            ingest(session, self.descriptor_path)
            self.descriptor.update(input_id="input-2", camera_id="rgb-02")
            atomic_json(self.descriptor_path, self.descriptor)
            ingest(session, self.descriptor_path)
            clips = list(session.items("clip"))
            self.assertEqual({c["camera_id"] for c in clips}, {"rgb-01", "rgb-02"})
            self.assertEqual(len({c["original_video_id"] for c in clips}), 1)
            self.assertFalse(session.manifest["hardware_synchronized"])

    def test_revision_provenance_and_path_validation(self):
        for changes in ({"provenance": "real_camera"}, {"placement_revision": "v2"}, {"file": "../escape.mp4"}, {"camera_id": "missing"}, {"captured_at": "2026-01-01T00:00:00"}):
            with self.subTest(changes=changes), Session(self.root) as session:
                atomic_json(self.descriptor_path, {**self.descriptor, **changes})
                with self.assertRaises(RecorderError):
                    ingest(session, self.descriptor_path)
                self.assertEqual(list(session.items("clip")), [])

    def test_interruption_preserves_partial_and_recovery(self):
        with Session(self.root) as session:
            with patch("behavior_recorder.media.probe", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    ingest(session, self.descriptor_path)
            self.assertEqual(list(session.items("clip")), [])
            self.assertTrue(any("uncommitted" in f for f in session.verify()))
            quarantined = session.recover()
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(session.manifest["state"], "interrupted")
            self.assertEqual(session.verify(), [])
            self.assertTrue(list((self.root / "quarantine").rglob("original.mp4")))

    def test_manifest_commit_failure_does_not_publish_orphan(self):
        with Session(self.root) as session:
            with patch("behavior_recorder.core.atomic_json", side_effect=OSError("simulated power loss")):
                with self.assertRaises(OSError):
                    ingest(session, self.descriptor_path)
        reloaded = Session(self.root)
        self.assertEqual(list(reloaded.items("clip")), [])
        self.assertTrue(reloaded.unresolved())
        with reloaded:
            reloaded.recover()
        self.assertEqual(reloaded.verify(), [])

    def test_quota_failure_stops_and_logs_without_deleting_original(self):
        tiny = self.base / "tiny"
        config = copy.deepcopy(self.config)
        limit = self.video.stat().st_size + 8192
        config["storage"].update(max_session_bytes=limit, max_clip_bytes=limit)
        create_session(tiny, config)
        with patch("sys.stderr", io.StringIO()):
            self.assertEqual(main(["ingest", str(tiny), str(self.descriptor_path)]), 1)
        loaded = Session(tiny)
        self.assertEqual(loaded.manifest["state"], "failed")
        self.assertTrue(any(e["code"] == "collection_failed" for e in loaded.items("event")))
        self.assertIn("storage_limit", list(loaded.items("event"))[-1]["details"]["reason"])
        self.assertTrue((self.inbox / "test.mp4").exists())
        self.assertEqual(list(loaded.items("clip")), [])

    def test_low_disk_and_write_error(self):
        with Session(self.root) as session:
            with patch("behavior_recorder.core.shutil.disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 0)):
                with self.assertRaisesRegex(RecorderError, "insufficient free"):
                    ingest(session, self.descriptor_path)
            session.recover()
            session.event("session_resumed", updates={"state": "active", "ended_at": None})
            with patch("behavior_recorder.media.copy_clip", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(OSError):
                    ingest(session, self.descriptor_path)
            self.assertTrue(session.unresolved())

    def test_corrupted_original_detected(self):
        clip_id = self.ingest()
        session = Session(self.root)
        path = relative(self.root, session.clip(clip_id)["media_path"])
        with path.open("r+b") as stream:
            stream.write(b"BAD")
        self.assertTrue(session.verify())
        with self.assertRaisesRegex(RecorderError, "checksum"):
            replay(session, clip_id, seconds=0.1)

    def test_checksum_failure_and_missing_video(self):
        self.descriptor["sha256"] = "0" * 64
        atomic_json(self.descriptor_path, self.descriptor)
        with Session(self.root) as session:
            with self.assertRaisesRegex(RecorderError, "checksum"):
                ingest(session, self.descriptor_path)
            session.recover()
            session.event("session_resumed", updates={"state": "active"})
            self.descriptor["file"] = "missing.mp4"
            atomic_json(self.descriptor_path, self.descriptor)
            with self.assertRaisesRegex(RecorderError, "regular finalized"):
                ingest(session, self.descriptor_path)

    def test_missing_sequence_and_frame_timing_anomalies(self):
        self.descriptor["sequence"] = 2
        atomic_json(self.descriptor_path, self.descriptor)
        clip_id = self.ingest()
        session = Session(self.root)
        events = jsonl(relative(self.root, session.clip(clip_id)["events_path"]))
        self.assertEqual(events[0]["code"], "missing_clip_sequence")
        frames = [{"pts": 0}, {"pts": 1}, {"pts": 4}, {}, {"pts": 3}]
        rows, errors = frame_records(frames, {"time_base": "1/5"}, "2026-01-01T00:00:00Z", {"source": "device", "accuracy_ms": 20}, 5)
        self.assertEqual({e["code"] for e in errors}, {"pts_gap_possible_drop", "frame_pts_missing", "nonmonotonic_pts"})
        self.assertEqual(rows[2]["estimated_capture_at"], "2026-01-01T00:00:00.800000+00:00")
        self.assertIsNone(rows[2]["captured_at"])

    def test_labels_validation_revisions_and_duplicate(self):
        clip_id = self.ingest()
        label = self.label(clip_id)
        with Session(self.root) as session:
            import_labels(session, [label])
            self.assertEqual(import_labels(session, [label])["added"], 0)
            for changes in ({"end_seconds": 9}, {"animal_id": "unknown"}, {"behavior": "sleep"}, {"start_seconds": float("nan")}):
                with self.subTest(changes=changes), self.assertRaises((RecorderError, ValueError)):
                    import_labels(session, [{**label, **changes, "label_id": "bad"}])
            revised = {**label, "label_id": "label-2", "supersedes": "label-1", "note": "corrected"}
            import_labels(session, [revised])
            self.assertEqual([r["label_id"] for r in active_labels(session)], ["label-2"])
            with self.assertRaisesRegex(RecorderError, "active label"):
                import_labels(session, [{**revised, "label_id": "forked"}])

    def test_boris_aggregated_import(self):
        clip_id = self.ingest()
        path = self.base / "boris.tsv"
        path.write_text("Observation id\tSubject\tBehavior\tStart (s)\tStop (s)\tBehavior type\nobs-1\ttest-subject\tmoving\t0.2\t0.8\tSTATE\n", encoding="utf-8")
        rows = boris_labels(path, clip_id, "test-subject", "tester", "partial", "uncertain")
        with Session(self.root) as session:
            import_labels(session, rows)
            self.assertEqual(import_labels(session, rows)["added"], 0)
            self.assertEqual(active_labels(session)[0]["visibility"], "partial")

    def test_habitat_units_and_raw_payload_preserved(self):
        event = {"id": "event-1", "kind": "telemetry.recorded", "serverReceivedAt": "2026-01-01T00:00:01Z",
                 "payload": {"sampled_at": "2026-01-01T00:00:00Z", "received_at": "2026-01-01T00:00:00.100Z", "data_source": "simulation",
                             "geometry_revision": 1, "placement_revision": 3, "readings": {"T1": {"value": None, "quality": "crc_error"}}}}
        rows = habitat_rows([event], {"T1": "degC"}, "enclosure-01")
        with Session(self.root) as session:
            import_sensors(session, rows)
            loaded = saved_rows(session, "sensors")[0]
            self.assertEqual(loaded["raw_habitat_record"], event)
            self.assertEqual(loaded["placement_revision"], 3)
            self.assertNotEqual(loaded["received_at"], loaded["server_received_at"])
        with self.assertRaisesRegex(RecorderError, "unit mapping"):
            habitat_rows([event], {}, "enclosure-01")

    def test_numeric_thermal_never_from_color_video(self):
        row = jsonl(ROOT / "examples/thermal.test.jsonl")[0]
        with Session(self.root) as session:
            with self.assertRaisesRegex(RecorderError, "not measured temperature"):
                import_thermal(session, [{**row, "camera_id": "rgb-01"}])
            with self.assertRaisesRegex(RecorderError, "rectangular"):
                import_thermal(session, [{**row, "values": [[1, 2], [None]]}])

    def test_archive_traversal_and_size_limit(self):
        archive = self.base / "evil.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("bundle.json", "{}")
            output.writestr("manifest.json", "{}")
            output.writestr("../escaped", "bad")
        with self.assertRaisesRegex(RecorderError, "unsafe relative"):
            import_bundle(archive, self.base / "new")
        self.assertFalse((self.base / "escaped").exists())
        with self.assertRaisesRegex(RecorderError, "extraction byte"):
            import_bundle(archive, self.base / "new2", max_bytes=1)

    def test_wrong_config_and_closed_session(self):
        with self.assertRaises(RecorderError):
            validate_config({**self.config, "surprise": True})
        invalid = copy.deepcopy(self.config)
        invalid["cameras"][0]["expected_fps"] = float("nan")
        with self.assertRaises(RecorderError):
            validate_config(invalid)
        with Session(self.root) as session:
            session.event("session_stopped", updates={"state": "stopped"})
            with self.assertRaisesRegex(RecorderError, "not active"):
                ingest(session, self.descriptor_path)

    def test_pi_unconfigured_camera_rejects_ingestion(self):
        root = self.base / "pi"
        create_session(root, read_json(ROOT / "examples/config.pi.json"))
        self.descriptor["provenance"] = "real_camera"
        atomic_json(self.descriptor_path, self.descriptor)
        with Session(root) as session:
            with self.assertRaisesRegex(RecorderError, "unconfigured"):
                ingest(session, self.descriptor_path)
            self.assertEqual(list(session.items("clip")), [])

    def test_sigterm_stops_real_collector_process(self):
        process = subprocess.Popen([sys.executable, "-m", "behavior_recorder", "record", str(self.root), "--config", str(self.config_path), "--seconds", "30"],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = list(Session(self.root).items("event"))
            if any(e["code"] == "source_idle" for e in events):
                break
            time.sleep(0.05)
        else:
            self.fail("collector did not become idle")
        self.descriptor.update(input_id="input-after-idle", sequence=1)
        atomic_json(self.inbox / "second.capture.json", self.descriptor)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = list(Session(self.root).items("event"))
            if any(e["code"] == "source_resumed" for e in events):
                break
            time.sleep(0.05)
        else:
            self.fail("collector did not detect resumed file source")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 130, stderr)
        loaded = Session(self.root)
        self.assertEqual(loaded.manifest["state"], "interrupted")
        self.assertEqual(loaded.verify(), [])
        self.assertTrue(any(e["code"] == "collection_interrupted" for e in loaded.items("event")))


if __name__ == "__main__":
    unittest.main()
