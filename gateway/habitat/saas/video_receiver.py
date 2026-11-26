"""Bounded reference HLS receiver. Production must use its own web session ACL."""
import math
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from habitat.common.models import utcnow
from .video_contract import (MAX_AGE_SECONDS, PLAYLIST_SEGMENTS, RETAIN_SEGMENTS,
                             VIDEO_PATH, VideoAck, VideoSegment)


def mount_video_receiver(app, db, lock, authorize_pi, authorize_viewer):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS video_streams (
            site_id TEXT NOT NULL, gateway_id TEXT NOT NULL, camera_id TEXT NOT NULL,
            cage_id TEXT NOT NULL, session_id TEXT NOT NULL, started_at TEXT NOT NULL,
            sequence INTEGER NOT NULL, captured_at TEXT NOT NULL,
            PRIMARY KEY(site_id, gateway_id, camera_id)
        );
        CREATE TABLE IF NOT EXISTS video_segments (
            site_id TEXT NOT NULL, gateway_id TEXT NOT NULL, camera_id TEXT NOT NULL,
            session_id TEXT NOT NULL, sequence INTEGER NOT NULL, captured_at TEXT NOT NULL,
            duration REAL NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL,
            PRIMARY KEY(site_id, gateway_id, camera_id, session_id, sequence)
        );
    """)

    def check_scope(registration, site_id, gateway_id, camera_id, cage_id=None):
        cage = registration.camera_cages.get(camera_id)
        if ((registration.site_id, registration.gateway_id) != (site_id, gateway_id)
                or cage is None or cage not in registration.cage_ids or (cage_id is not None and cage != cage_id)):
            raise HTTPException(403, "video_scope_denied")

    @app.post(VIDEO_PATH, response_model=VideoAck, tags=["Live video"], operation_id="uploadLiveVideoSegment")
    def upload(segment: VideoSegment, registration=Depends(authorize_pi)):
        check_scope(registration, segment.site_id, segment.gateway_id, segment.camera_id, segment.cage_id)
        age = (utcnow() - segment.captured_at).total_seconds()
        if not -5 <= age <= MAX_AGE_SECONDS:
            raise HTTPException(409, "video_expired_or_future")
        identity = (segment.site_id, segment.gateway_id, segment.camera_id)
        session = str(segment.session_id)
        started = segment.session_started_at.isoformat()
        captured = segment.captured_at.isoformat()
        data = segment.media_bytes()
        with lock, db:
            previous = db.execute("SELECT * FROM video_streams WHERE site_id=? AND gateway_id=? AND camera_id=?", identity).fetchone()
            if previous and previous["session_id"] != session:
                if started <= previous["started_at"]:
                    raise HTTPException(409, "superseded_video_session")
                db.execute("DELETE FROM video_segments WHERE site_id=? AND gateway_id=? AND camera_id=?", identity)
                previous = None
            if previous and started != previous["started_at"]:
                raise HTTPException(409, "video_session_conflict")
            if previous and segment.sequence <= previous["sequence"] - RETAIN_SEGMENTS:
                raise HTTPException(409, "video_segment_retired")
            if previous and ((segment.sequence > previous["sequence"] and captured < previous["captured_at"])
                             or (segment.sequence < previous["sequence"] and captured > previous["captured_at"])):
                raise HTTPException(409, "video_time_order_conflict")
            key = (*identity, session, segment.sequence)
            existing = db.execute("SELECT * FROM video_segments WHERE site_id=? AND gateway_id=? AND camera_id=? AND session_id=? AND sequence=?", key).fetchone()
            if existing:
                if (existing["sha256"], existing["captured_at"], existing["duration"]) != (segment.sha256, captured, segment.duration_s):
                    raise HTTPException(409, "video_segment_conflict")
            else:
                db.execute("INSERT INTO video_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (*key, captured, segment.duration_s, segment.sha256, data))
            if previous is None or segment.sequence > previous["sequence"]:
                db.execute("INSERT OR REPLACE INTO video_streams VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (*identity, segment.cage_id, session, started, segment.sequence, captured))
            high = max(segment.sequence, previous["sequence"] if previous else 0)
            db.execute("DELETE FROM video_segments WHERE site_id=? AND gateway_id=? AND camera_id=? AND sequence<=?",
                       (*identity, high - RETAIN_SEGMENTS))
        return segment.acknowledgement()

    prefix = "/v1/video/{site_id}/{gateway_id}/{camera_id}"

    @app.get(prefix + "/index.m3u8", tags=["Live video"], operation_id="readLiveVideoPlaylist")
    def playlist(site_id: str, gateway_id: str, camera_id: str, registration=Depends(authorize_viewer)):
        check_scope(registration, site_id, gateway_id, camera_id)
        identity = (site_id, gateway_id, camera_id)
        with lock:
            rows = db.execute("SELECT * FROM video_segments WHERE site_id=? AND gateway_id=? AND camera_id=? ORDER BY sequence DESC LIMIT ?",
                              (*identity, PLAYLIST_SEGMENTS)).fetchall()
        if not rows:
            raise HTTPException(503, "waiting_live_video")
        if (utcnow() - datetime.fromisoformat(rows[0]["captured_at"])).total_seconds() > MAX_AGE_SECONDS:
            raise HTTPException(503, "live_video_stale")
        # A network outage may leave gaps. Publish only the newest contiguous tail.
        tail = [rows[0]]
        for row in rows[1:]:
            if row["sequence"] != tail[-1]["sequence"] - 1:
                break
            tail.append(row)
        rows = list(reversed(tail))
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS",
                 f"#EXT-X-TARGETDURATION:{max(2, math.ceil(max(r['duration'] for r in rows)))}",
                 f"#EXT-X-MEDIA-SEQUENCE:{rows[0]['sequence']}"]
        for row in rows:
            lines += ["#EXT-X-PROGRAM-DATE-TIME:" + row["captured_at"], f"#EXTINF:{row['duration']:.6f},",
                      f"{row['session_id']}/{row['sequence']}.ts"]
        return Response("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-store"})

    @app.get(prefix + "/{session_id}/{sequence}.ts", tags=["Live video"], operation_id="readLiveVideoSegment")
    def media(site_id: str, gateway_id: str, camera_id: str, session_id: UUID, sequence: int,
              registration=Depends(authorize_viewer)):
        check_scope(registration, site_id, gateway_id, camera_id)
        with lock:
            row = db.execute("SELECT data FROM video_segments WHERE site_id=? AND gateway_id=? AND camera_id=? AND session_id=? AND sequence=?",
                             (site_id, gateway_id, camera_id, str(session_id), sequence)).fetchone()
        if row is None:
            raise HTTPException(404, "video_segment_unavailable")
        return Response(row["data"], media_type="video/mp2t", headers={"Cache-Control": "no-store"})
