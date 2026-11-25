import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

from behavior_recorder.appearance_journal import Journal
from behavior_recorder.core import RecorderError
from behavior_recorder.vision_lab import Handler, ThreadingHTTPServer


def entry(**changes):
    return dict(record_id="a" * 32, animal_id="crested-01", enclosure_id=None,
                observer="owner", earliest_at="2026-11-01T20:00:00+09:00",
                latest_at="2026-11-01T20:30:00+09:00", assessment="uncertain",
                note="직접 관찰한 상태를 기록", identity_confirmed=True, photo_id=None, **changes)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="easyrep-appearance-journal-test-"))
        self.journal = Journal(self.root, dataset_kind="test")

    def test_manual_record_needs_no_camera_photo_or_enclosure_and_never_predicts(self):
        self.journal.record(entry())
        state = Journal(self.root, dataset_kind="test").state()
        self.assertEqual(len(state["records"]), 1)
        row = state["records"][0]
        self.assertIsNone(row["input"]["photo_id"])
        self.assertIsNone(row["input"]["enclosure_id"])
        self.assertEqual(row["dataset_kind"], "test")
        self.assertIsNone(state["prediction"])
        self.assertFalse(state["actuation_allowed"])
        self.assertFalse(row["training_admitted"])

    def test_retries_are_idempotent_but_conflicting_record_ids_are_rejected(self):
        row = entry()
        first = self.journal.record(row)
        self.assertEqual(self.journal.record(copy.deepcopy(row)), first)
        row["assessment"] = "completed"
        with self.assertRaises(RecorderError):
            self.journal.record(row)
        self.assertEqual(len(self.journal.state()["records"]), 1)
        with self.assertRaises(RecorderError):
            Journal(self.root, dataset_kind="real")

    def test_invalid_dates_identity_paths_and_prediction_fields_leave_no_record(self):
        for changes in [dict(latest_at="2026-10-31T20:00:00+09:00"),
                        dict(earliest_at="2026-11-01T20:00:00"), dict(earliest_at=None),
                        dict(identity_confirmed=False), dict(animal_id="../escape"),
                        dict(photo_id="b" * 64), dict(prediction=0.9), dict(assessment="normal_forever")]:
            row = entry(); row.update(changes)
            with self.subTest(changes=changes), self.assertRaises((RecorderError, ValueError)):
                self.journal.record(row)
        self.assertEqual(self.journal.state()["records"], [])

    def test_optional_photo_retains_exact_bytes_and_stays_unreviewed(self):
        # Signature-only synthetic fixture, not a decoded or biological image.
        data = b"\x89PNG\r\n\x1a\nsynthetic fixture"
        photo = self.journal.photo(data, "fixture.png")
        self.assertEqual(self.journal.photo(data, "fixture.png"), photo)
        row = entry(); row["photo_id"] = photo["id"]
        self.journal.record(row)
        self.assertEqual((self.root / photo["path"]).read_bytes(), data)
        self.assertEqual(photo["status"], "unreviewed_attachment")
        self.assertFalse(self.journal.state()["records"][0]["training_admitted"])
        for payload, name in [(b"<script>bad</script>", "photo.png"), (data, "../photo.png")]:
            with self.assertRaises(RecorderError): self.journal.photo(payload, name)
        (self.root / photo["path"]).write_bytes(b"tampered")
        row["record_id"] = "b" * 32
        with self.assertRaises(RecorderError): self.journal.record(row)

    def test_order_uses_observation_time_not_upload_time(self):
        late = entry(); late.update(record_id="b" * 32, earliest_at="2026-11-02T00:00:00Z", latest_at="2026-11-02T01:00:00Z")
        self.journal.record(late); self.journal.record(entry())
        self.assertEqual([r["input"]["record_id"] for r in self.journal.state()["records"]], ["a" * 32, "b" * 32])

    def test_local_http_manual_save_readback_guards_and_analysis_routes_disabled(self):
        lab = SimpleNamespace(storage=self.root, appearance_only=True, token="test-token", journal=self.journal)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler); server.lab = lab
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def request(method, path, data=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse(); body = response.read(); conn.close()
            return response.status, body
        try:
            self.assertEqual(request("GET", "/")[0], 200)
            headers = {"Content-Type": "application/json", "X-Lab-Token": "test-token"}
            self.assertEqual(request("POST", "/api/appearance/records", json.dumps(entry()), {"Content-Type":"application/json"})[0], 400)
            self.assertEqual(request("POST", "/api/appearance/records", json.dumps(entry()), {**headers, "Origin":"https://other.example"})[0], 400)
            self.assertEqual(request("POST", "/api/appearance/records", json.dumps(entry()), headers)[0], 201)
            code, body = request("GET", "/api/appearance")
            self.assertEqual(code, 200)
            self.assertEqual(len(json.loads(body)["records"]), 1)
            code, body = request("POST", "/api/appearance/photo", b"\x89PNG\r\n\x1a\nfixture",
                                 {"X-Lab-Token":"test-token", "X-Filename":"fixture.png"})
            self.assertEqual(code, 201)
            row = entry(); row.update(record_id="b" * 32, photo_id=json.loads(body)["id"])
            self.assertEqual(request("POST", "/api/appearance/records", json.dumps(row), headers)[0], 201)
            code, body = request("GET", "/api/appearance")
            self.assertEqual(len(json.loads(body)["records"]), 2)
            self.assertEqual(json.loads(body)["records"][1]["photo"]["status"], "unreviewed_attachment")
            self.assertEqual(request("POST", "/api/appearance/photo", b"not a photo",
                                     {"X-Lab-Token":"test-token", "X-Filename":"fixture.png"})[0], 400)
            self.assertEqual(request("POST", "/api/jobs", "{}", headers)[0], 404)
            self.assertEqual(request("GET", "/api/state")[0], 404)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
