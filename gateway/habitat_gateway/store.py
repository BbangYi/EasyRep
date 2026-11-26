import json
import fcntl
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import utcnow


class Store:
    """Gateway owns the lock; all access is serialized by Gateway.lock."""

    def __init__(self, path: str, *, event_identity=None, now=utcnow):
        self.event_identity = event_identity
        self.now = now
        self.process_lock = None
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.process_lock = open(f"{path}.lock", "a")
            try:
                fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.process_lock.close()
                raise RuntimeError("another gateway process is using this database") from None
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS telemetry (
                cage_id TEXT NOT NULL, message_id TEXT NOT NULL,
                sampled_at TEXT NOT NULL, received_at TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(cage_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS telemetry_latest ON telemetry(cage_id, sampled_at DESC);
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY, cage_id TEXT NOT NULL,
                actuator_id TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS command_target ON commands(cage_id, actuator_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS modes (cage_id TEXT PRIMARY KEY, mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS r15_sessions (
                base TEXT NOT NULL, session_id TEXT NOT NULL,
                PRIMARY KEY(base, session_id)
            );
            CREATE TABLE IF NOT EXISTS observations (
                cage_id TEXT NOT NULL, actuator_id TEXT NOT NULL,
                body TEXT NOT NULL, PRIMARY KEY(cage_id, actuator_id)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL, cage_id TEXT, body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cloud_identity (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                site_id TEXT NOT NULL, gateway_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cloud_outbox (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cloud_conflicts (
                event_id TEXT PRIMARY KEY REFERENCES cloud_outbox(event_id) ON DELETE CASCADE,
                detected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cloud_delivery_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                acknowledged_high_watermark INTEGER NOT NULL DEFAULT 0 CHECK(acknowledged_high_watermark>=0),
                acknowledged_at TEXT, last_ack_event_id TEXT,
                server_high_watermark INTEGER, verified_at TEXT, method TEXT, evidence_ref TEXT,
                confirmed_at TEXT, blocked_reason TEXT, blocked_at TEXT
            );
            INSERT OR IGNORE INTO cloud_delivery_state(singleton) VALUES (1);
            CREATE TABLE IF NOT EXISTS enclosure_profiles (
                site_id TEXT NOT NULL, gateway_id TEXT NOT NULL, cage_id TEXT NOT NULL,
                name TEXT NOT NULL, name_key TEXT NOT NULL, species TEXT NOT NULL,
                form_factor TEXT NOT NULL CHECK(form_factor IN ('vertical', 'horizontal', 'aquatic')),
                PRIMARY KEY(site_id, gateway_id, cage_id),
                UNIQUE(site_id, gateway_id, name_key)
            );
            PRAGMA user_version=1;
        """)
        if event_identity:
            identity = self.db.execute("SELECT site_id, gateway_id FROM cloud_identity").fetchone()
            if identity and tuple(identity) != tuple(event_identity):
                self.close()
                raise ValueError("cloud database belongs to a different site/gateway; use a separate database")
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO cloud_identity VALUES (1, ?, ?)", event_identity)

    def close(self):
        self.db.close()
        if self.process_lock:
            self.process_lock.close()

    def enclosure_profiles(self, site_id, gateway_id):
        return [dict(row) for row in self.db.execute(
            "SELECT cage_id, name, species, form_factor FROM enclosure_profiles "
            "WHERE site_id=? AND gateway_id=? ORDER BY rowid", (site_id, gateway_id)
        )]

    def register_enclosure(self, site_id, gateway_id, profile):
        # Registration and its local audit commit together; no SaaS event is queued.
        with self.db:
            self.db.execute("INSERT INTO enclosure_profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
                (site_id, gateway_id, profile["cage_id"], profile["name"], profile["name"].casefold(),
                 profile["species"], profile["form_factor"]))
            self.db.execute("INSERT INTO audit(occurred_at, kind, cage_id, body) VALUES (?, ?, ?, ?)",
                (self.now().isoformat(), "enclosure_registered", profile["cage_id"],
                 json.dumps({"site_id": site_id, "gateway_id": gateway_id, **profile})))

    def telemetry(self, cage_id, body, received_at):
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO telemetry VALUES (?, ?, ?, ?, ?)",
                (cage_id, body["message_id"], body["sampled_at"], received_at, json.dumps(body)),
            )
            if cursor.rowcount == 1:
                self._enqueue("telemetry.recorded", cage_id, {**body, "received_at": received_at})
        return cursor.rowcount == 1

    def latest_telemetry(self, cage_id):
        row = self.db.execute(
            "SELECT body, received_at FROM telemetry WHERE cage_id=? ORDER BY sampled_at DESC, rowid DESC LIMIT 1",
            (cage_id,),
        ).fetchone()
        return {**json.loads(row["body"]), "received_at": row["received_at"]} if row else None

    def history(self, cage_id, limit):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM telemetry WHERE cage_id=? ORDER BY sampled_at DESC, rowid DESC LIMIT ?", (cage_id, limit)
        )]

    def save_command(self, body):
        with self.db:
            self.db.execute(
                "INSERT INTO commands VALUES (?, ?, ?, ?, ?) ON CONFLICT(command_id) DO UPDATE SET body=excluded.body",
                (body["command_id"], body["cage_id"], body["actuator_id"], body["created_at"], json.dumps(body)),
            )
            self._enqueue("command.updated", body["cage_id"], body)

    def _enqueue(self, kind, cage_id, payload):
        """Called inside the source write transaction; never acknowledge an unqueued event."""
        if not self.event_identity:
            return
        event = {
            "schema_version": 1, "event_id": str(uuid4()), "kind": kind,
            "site_id": self.event_identity[0], "gateway_id": self.event_identity[1],
            "cage_id": cage_id, "created_at": self.now().isoformat(), "payload": payload,
        }
        self.db.execute("INSERT INTO cloud_outbox(event_id, created_at, body) VALUES (?, ?, ?)",
                        (event["event_id"], event["created_at"], json.dumps(event)))

    def cloud_batch(self, limit):
        return [{**json.loads(row["body"]), "event_sequence": row["sequence"]} for row in self.db.execute(
            "SELECT sequence, body FROM cloud_outbox WHERE NOT EXISTS "
            "(SELECT 1 FROM cloud_conflicts WHERE cloud_conflicts.event_id=cloud_outbox.event_id) "
            "ORDER BY sequence LIMIT ?", (limit,)
        )]

    def quarantine_cloud_event(self, event_id):
        """Retain a single event rejected by SaaS; never rewrite its ID, sequence or body."""
        with self.db:
            if not self.db.execute("SELECT 1 FROM cloud_outbox WHERE event_id=?", (event_id,)).fetchone():
                raise ValueError("unknown_cloud_event")
            self.db.execute("INSERT OR IGNORE INTO cloud_conflicts VALUES (?, ?)",
                            (event_id, self.now().isoformat()))

    def cloud_ack(self, event_ids):
        event_ids = tuple(event_ids)
        with self.db:
            for event_id in event_ids:
                row = self.db.execute("SELECT sequence FROM cloud_outbox WHERE event_id=?", (event_id,)).fetchone()
                if row:
                    self.db.execute("""UPDATE cloud_delivery_state SET acknowledged_high_watermark=?,
                        acknowledged_at=?, last_ack_event_id=?
                        WHERE singleton=1 AND acknowledged_high_watermark<?""",
                        (row[0], self.now().isoformat(), event_id, row[0]))
            self.db.executemany("DELETE FROM cloud_outbox WHERE event_id=?", [(i,) for i in event_ids])

    def cloud_continuity(self):
        state = self.db.execute("SELECT * FROM cloud_delivery_state WHERE singleton=1").fetchone()
        sequence = self.db.execute("SELECT seq FROM sqlite_sequence WHERE name='cloud_outbox'").fetchone()
        allocated = sequence[0] if sequence else 0
        # Legacy batch conflicts did not identify which event was rejected. Re-probe
        # those unchanged events individually; retain the old evidence for diagnosis.
        reason = state["blocked_reason"]
        if reason == "cloud_event_conflict":
            reason = None
        if allocated < max(state["acknowledged_high_watermark"], state["server_high_watermark"] or 0):
            reason = "cloud_sequence_regressed"
        confirmed = state["verified_at"] is not None and state["blocked_reason"] is None
        return {"status": "blocked" if reason else "confirmed" if confirmed else "unverified",
                "blocked_reason": reason, "recorded_blocked_reason": state["blocked_reason"],
                "allocated_high_watermark": allocated,
                "acknowledged_high_watermark": state["acknowledged_high_watermark"],
                "acknowledged_at": state["acknowledged_at"],
                "server_high_watermark": state["server_high_watermark"],
                "verified_at": state["verified_at"],
                "confirmation_provenance": "operator_declared" if state["verified_at"] else None}

    def confirm_cloud_continuity(self, evidence):
        """Record an operator's server evidence; never contact SaaS or resequence an event.

        The operator must establish exclusive sending since the server check. This
        method checks local consistency, not the authenticity of that external evidence.
        """
        required = {"site_id", "gateway_id", "server_high_watermark", "verified_at",
                    "method", "evidence_ref", "exclusive_writer"}
        if not isinstance(evidence, dict) or set(evidence) != required:
            raise ValueError("invalid_cloud_continuity_evidence")
        if not self.event_identity or (evidence["site_id"], evidence["gateway_id"]) != self.event_identity:
            raise ValueError("cloud_continuity_identity_mismatch")
        high = evidence["server_high_watermark"]
        if type(high) is not int or not 0 <= high < 2**63 or evidence["exclusive_writer"] is not True:
            raise ValueError("invalid_cloud_continuity_evidence")
        if any(not isinstance(evidence[k], str) or not 1 <= len(evidence[k].strip()) <= 512
               for k in ("verified_at", "method", "evidence_ref")):
            raise ValueError("invalid_cloud_continuity_evidence")
        try:
            verified = datetime.fromisoformat(evidence["verified_at"])
            if verified.tzinfo is None or verified.utcoffset() is None or verified > self.now():
                raise ValueError()
        except ValueError:
            raise ValueError("invalid_cloud_continuity_evidence") from None
        with self.db:
            state = self.cloud_continuity()
            if high < max(state["acknowledged_high_watermark"], state["server_high_watermark"] or 0):
                raise ValueError("cloud_server_history_regressed")
            if high > state["allocated_high_watermark"]:
                raise ValueError("cloud_continuity_migration_required")
            if self.db.execute("SELECT 1 FROM cloud_outbox WHERE sequence<=? LIMIT 1", (high,)).fetchone():
                raise ValueError("cloud_pending_reconciliation_required")
            if state["blocked_reason"] == "cloud_sequence_regressed":
                raise ValueError("cloud_sequence_regressed")
            blocked_at = self.db.execute("SELECT blocked_at FROM cloud_delivery_state WHERE singleton=1").fetchone()[0]
            if blocked_at and verified < datetime.fromisoformat(blocked_at):
                raise ValueError("cloud_verification_predates_conflict")
            self.db.execute("""UPDATE cloud_delivery_state SET server_high_watermark=?, verified_at=?,
                method=?, evidence_ref=?, confirmed_at=?, blocked_reason=NULL, blocked_at=NULL WHERE singleton=1""",
                (high, verified.isoformat(), evidence["method"], evidence["evidence_ref"], self.now().isoformat()))
            self.db.execute("INSERT INTO audit(occurred_at,kind,cage_id,body) VALUES (?,?,NULL,?)",
                (self.now().isoformat(), "cloud_continuity_operator_confirmed", json.dumps(evidence)))
        return self.cloud_continuity()

    def block_cloud_continuity(self):
        with self.db:
            self.db.execute("UPDATE cloud_delivery_state SET blocked_reason='cloud_event_conflict', blocked_at=? WHERE singleton=1",
                            (self.now().isoformat(),))

    def cloud_backlog(self):
        row = self.db.execute("SELECT COUNT(*), MIN(created_at), COUNT(cloud_conflicts.event_id) "
                              "FROM cloud_outbox LEFT JOIN cloud_conflicts USING(event_id)").fetchone()
        return {"pending_events": row[0], "oldest_event_at": row[1],
                "eligible_events": row[0] - row[2], "conflicted_events": row[2]}

    def next_sequence(self):
        return self.db.execute("SELECT COALESCE(MAX(json_extract(body, '$.sequence')), 0) + 1 FROM commands").fetchone()[0]

    def claim_r15_session(self, base, session_id):
        # Never resume a session observed by a previous gateway process/connection.
        with self.db:
            return self.db.execute("INSERT OR IGNORE INTO r15_sessions(base,session_id) VALUES (?,?)",
                                   (base, session_id)).rowcount == 1

    def command(self, command_id):
        row = self.db.execute("SELECT body FROM commands WHERE command_id=?", (command_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def commands(self, cage_id=None, limit=100):
        if cage_id:
            rows = self.db.execute(
                "SELECT body FROM commands WHERE cage_id=? ORDER BY rowid DESC LIMIT ?", (cage_id, limit)
            )
        else:
            rows = self.db.execute("SELECT body FROM commands ORDER BY rowid DESC LIMIT ?", (limit,))
        return [json.loads(row[0]) for row in rows]

    def pending(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM commands WHERE json_extract(body, '$.status') IN ('publishing', 'published', 'requested')"
        )]

    def latest_command(self, cage_id, actuator_id):
        row = self.db.execute(
            "SELECT body FROM commands WHERE cage_id=? AND actuator_id=? ORDER BY rowid DESC LIMIT 1",
            (cage_id, actuator_id),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def latest_on(self, cage_id, actuator_id):
        row = self.db.execute(
            "SELECT body FROM commands WHERE cage_id=? AND actuator_id=? "
            "AND json_extract(body, '$.action')='on' "
            "AND json_extract(body, '$.status') IN ('publishing', 'published', 'applied', 'expired', 'interrupted', 'requested', 'execution_unverified') "
            "ORDER BY rowid DESC LIMIT 1", (cage_id, actuator_id),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def mode(self, cage_id):
        row = self.db.execute("SELECT mode FROM modes WHERE cage_id=?", (cage_id,)).fetchone()
        return row[0] if row else "manual"

    def set_mode(self, cage_id, mode):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO modes VALUES (?, ?)", (cage_id, mode))

    def observe(self, cage_id, actuator_id, state, occurred_at, source):
        previous = self.observation(cage_id, actuator_id)
        if previous and previous["occurred_at"] > occurred_at:
            return
        body = {"state": state, "occurred_at": occurred_at, "source": source}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO observations VALUES (?, ?, ?)",
                            (cage_id, actuator_id, json.dumps(body)))

    def observation(self, cage_id, actuator_id):
        row = self.db.execute("SELECT body FROM observations WHERE cage_id=? AND actuator_id=?",
                              (cage_id, actuator_id)).fetchone()
        return json.loads(row[0]) if row else None

    def audit(self, occurred_at, kind, cage_id=None, **body):
        with self.db:
            self.db.execute("INSERT INTO audit(occurred_at, kind, cage_id, body) VALUES (?, ?, ?, ?)",
                            (occurred_at, kind, cage_id, json.dumps(body)))

    def audit_events(self, limit=100):
        return [{**dict(row), "body": json.loads(row["body"])} for row in self.db.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        )]
