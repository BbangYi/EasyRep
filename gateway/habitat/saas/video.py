"""Bounded live-video upload. Only completed recent segments are eligible."""
import asyncio
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import re
import threading
import time

import httpx
from pydantic import AnyHttpUrl, Field, model_validator

from habitat.common.http import validate_service_url
from habitat.common.models import Model, utcnow
from .video_contract import (MAX_AGE_SECONDS, MAX_SEGMENT_BYTES, MAX_SEGMENT_SECONDS,
                             PLAYLIST_SEGMENTS, HLS_REPLAY_GRACE_SECONDS, HLS_RETAIN_SEGMENTS,
                             VideoAck, VideoSegment, validate_mpegts)


class VideoUploadConfig(Model):
    enabled: bool = False
    endpoint: AnyHttpUrl | None = None
    token_env: str = "HABITAT_CLOUD_TOKEN"
    timeout_s: float = Field(default=5, ge=1, le=10)
    retry_max_s: float = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def destination(self):
        if self.enabled and self.endpoint is None:
            raise ValueError("video_upload.enabled requires video_upload.endpoint")
        if self.endpoint:
            validate_service_url(self.endpoint, "video_upload.endpoint")
        return self


def read_live_segments(directory, site_id, gateway_id, camera, now=None):
    """Read atomic FFmpeg output without opening the camera or retaining a backlog."""
    now = time.time() if now is None else now
    directory = Path(directory)
    playlist = directory / "index.m3u8"
    session_file = directory / "session.json"
    if not playlist.exists() or now - playlist.stat().st_mtime > MAX_AGE_SECONDS:
        return []
    if playlist.stat().st_size > 16384 or session_file.stat().st_size > 4096:
        raise ValueError("invalid live manifest size")
    session = json.loads(session_file.read_text())
    try:
        started_at = datetime.fromisoformat(session["started_at"])
    except (KeyError, TypeError):
        raise ValueError("invalid live session timestamp") from None
    if started_at.utcoffset() is None:
        raise ValueError("invalid live session timestamp")
    text = playlist.read_text()
    segments, duration, captured = [], None, None
    segment_count = 0
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",")[0])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            captured = datetime.fromisoformat(line.split(":", 1)[1].replace("Z", "+00:00"))
        elif line and not line.startswith("#"):
            match = re.fullmatch(r"seg-(\d{16})\.ts", line)
            if not match or duration is None or captured is None or captured.utcoffset() is None:
                raise ValueError("invalid live manifest")
            segment_count += 1
            if segment_count > PLAYLIST_SEGMENTS:
                raise ValueError("too many live segments")
            segment_duration, segment_captured = duration, captured
            duration, captured = None, None
            if segment_captured < started_at:
                raise ValueError("capture precedes session")
            age = now - segment_captured.timestamp()
            if 0 <= age <= MAX_AGE_SECONDS:
                if not 0 < segment_duration <= MAX_SEGMENT_SECONDS:
                    continue
                path = directory / line
                # FFmpeg may retire an old segment while the manifest is being read.
                try:
                    with path.open("rb") as stream:
                        data = stream.read(MAX_SEGMENT_BYTES + 1)
                except FileNotFoundError:
                    continue
                try:
                    validate_mpegts(data)
                except ValueError:
                    # One completed bad segment must not hide newer good media.
                    # Manifest/session errors above still reject the whole read.
                    continue
                segments.append(VideoSegment(
                    site_id=site_id, gateway_id=gateway_id, cage_id=camera.cage_id,
                    camera_id=camera.id, session_id=session["session_id"],
                    session_started_at=session["started_at"], sequence=int(match[1]),
                    captured_at=segment_captured, duration_s=segment_duration,
                    sha256=hashlib.sha256(data).hexdigest(), data_base64=base64.b64encode(data).decode(),
                ))
    # A restart must not mix files from different capture sessions.
    if json.loads(session_file.read_text()) != session:
        return []
    return segments


class AdvertisedSegments:
    """Keep bounded metadata for advertised files that outlive a playlist entry.

    Keep at most 48 metadata entries per camera, never media bytes. Callers must
    authorize each request and require a healthy reader and a fresh (15-second)
    playlist. Same-session replay permits original capture ages up to 40 seconds
    only while the unchanged file exists; FFmpeg may delete it sooner despite
    its count-based deletion threshold. This does not guarantee file retention.
    """

    def __init__(self):
        self._rows = {}
        self._lock = threading.Lock()

    def _prune(self, camera_id, current, now):
        rows = {sequence: row for sequence, row in self._rows.get(camera_id, {}).items()
                if row["session_id"] == current.session_id
                and row["session_started_at"] == current.session_started_at
                and 0 <= now - row["captured_at"].timestamp() <= HLS_REPLAY_GRACE_SECONDS}
        self._rows[camera_id] = rows
        return rows

    def remember(self, camera_id, advertised):
        if not advertised:
            return
        with self._lock:
            rows = self._prune(camera_id, advertised[-1], time.time())
            rows.update({row.sequence: row.model_dump(exclude={"data_base64"}) for row in advertised})
            self._rows[camera_id] = {sequence: rows[sequence] for sequence in sorted(rows)[-HLS_RETAIN_SEGMENTS:]}

    def read(self, directory, camera_id, session_id, sequence, current):
        with self._lock:
            row = self._prune(camera_id, current, time.time()).get(sequence)
            if row is None or str(row["session_id"]) != session_id:
                return None
        try:
            directory = Path(directory)
            with (directory / f"seg-{sequence:016d}.ts").open("rb") as stream:
                data = stream.read(MAX_SEGMENT_BYTES + 1)
            if len(data) > MAX_SEGMENT_BYTES:
                return None
            result = VideoSegment.model_validate({**row, "data_base64": base64.b64encode(data).decode()})
            # A recorder restart during the retained-file read invalidates it.
            with (directory / "session.json").open("rb") as stream:
                encoded = stream.read(4097)
            if len(encoded) > 4096:
                return None
            session = json.loads(encoded)
            if (not isinstance(session, dict) or session.get("session_id") != str(current.session_id)
                    or datetime.fromisoformat(session["started_at"]) != current.session_started_at
                    or not 0 <= time.time() - result.captured_at.timestamp() <= HLS_REPLAY_GRACE_SECONDS):
                return None
            return result
        except (OSError, ValueError, KeyError, TypeError):
            return None


class VideoUploadFailure(Exception):
    pass


class VideoUploader:
    def __init__(self, config, cameras, directory, site_id, gateway_id, token):
        self.config, self.cameras = config, [c for c in cameras if c.live_stream]
        self.directory, self.site_id, self.gateway_id = Path(directory), site_id, gateway_id
        self.token = token
        self.states = {}
        self.acknowledged = {}

    def status(self):
        return {"enabled": self.config.enabled, "cameras": self.states}

    async def send(self, client, segment):
        async with client.stream("POST", str(self.config.endpoint), json=segment.model_dump(mode="json"),
                headers={"Authorization": f"Bearer {self.token}"}, follow_redirects=False,
                timeout=self.config.timeout_s) as response:
            if response.status_code != 200:
                raise VideoUploadFailure(f"http_{response.status_code}")
            body = bytearray()
            async for block in response.aiter_bytes():
                body.extend(block)
                if len(body) > 16384:
                    raise VideoUploadFailure("ack_too_large")
        try:
            ack = VideoAck.model_validate_json(body)
        except ValueError:
            raise VideoUploadFailure("invalid_ack") from None
        if ack != segment.acknowledgement():
            raise VideoUploadFailure("ack_mismatch")

    async def cycle(self, client, camera):
        state = self.states.setdefault(camera.id, {"cage_id": camera.cage_id,
            "last_success_at": None, "last_error": None, "consecutive_failures": 0})
        try:
            segments = await asyncio.to_thread(read_live_segments, self.directory / camera.id,
                self.site_id, self.gateway_id, camera)
            keys = {(str(s.session_id), s.sequence, s.sha256) for s in segments}
            acknowledged = self.acknowledged.setdefault(camera.id, set())
            acknowledged.intersection_update(keys)
            state["source"] = "live" if segments else "waiting_fresh_video"
            for segment in segments:
                key = (str(segment.session_id), segment.sequence, segment.sha256)
                if key in acknowledged or time.time() - segment.captured_at.timestamp() > MAX_AGE_SECONDS:
                    continue
                await asyncio.wait_for(self.send(client, segment), timeout=self.config.timeout_s)
                acknowledged.add(key)
                state.update(last_success_at=utcnow().isoformat(), last_sequence=segment.sequence,
                             last_error=None, consecutive_failures=0)
        except (OSError, ValueError, KeyError):
            code = "live_source_unavailable"
        except VideoUploadFailure as error:
            code = str(error)
        except (TimeoutError, httpx.TimeoutException):
            code = "timeout"
        except httpx.HTTPError:
            code = "network_error"
        except Exception:
            code = "video_upload_internal_error"
        else:
            return True
        state.update(last_error=code, consecutive_failures=state["consecutive_failures"] + 1)
        return False

    async def _camera_loop(self, client, camera):
        while True:
            success = await self.cycle(client, camera)
            failures = self.states[camera.id]["consecutive_failures"]
            delay = 0.5 if success else random.uniform(1, min(self.config.retry_max_s, 2 ** min(failures, 10)))
            await asyncio.sleep(delay)

    async def run(self):
        async with httpx.AsyncClient(trust_env=False) as client:
            tasks = [asyncio.create_task(self._camera_loop(client, camera)) for camera in self.cameras]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
