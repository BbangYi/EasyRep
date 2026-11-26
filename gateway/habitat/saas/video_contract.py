"""HLS media ingestion v1; independent of the sensor event sequence/outbox."""
import base64
import hashlib
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from habitat.common.models import Identifier, Model, Timestamp

VIDEO_PATH = "/v1/edge/video"
SEGMENT_SECONDS = 2
PLAYLIST_SEGMENTS = 6
RETAIN_SEGMENTS = 12
MAX_SEGMENT_BYTES = 2 * 1024 * 1024
MAX_SEGMENT_SECONDS = 4
MAX_VIDEO_BODY = 3 * 1024 * 1024
MAX_AGE_SECONDS = 15
HLS_REPLAY_GRACE_SECONDS = 40
HLS_RETAIN_SEGMENTS = 48
HLS_DELETE_THRESHOLD = 40


def validate_mpegts(data):
    """Validate the bounded transport framing shared by capture and delivery."""
    if not 188 <= len(data) <= MAX_SEGMENT_BYTES or len(data) % 188:
        raise ValueError("invalid MPEG-TS length")
    if any(data[index] != 0x47 for index in range(0, len(data), 188)):
        raise ValueError("invalid MPEG-TS framing")


class VideoAck(Model):
    schema_version: Literal[1]
    site_id: Identifier
    gateway_id: Identifier
    cage_id: Identifier
    camera_id: Identifier
    session_id: UUID
    sequence: int = Field(strict=True, ge=0, le=9007199254740991)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VideoSegment(VideoAck):
    schema_version: Literal[1] = 1
    session_started_at: Timestamp
    captured_at: Timestamp
    duration_s: float = Field(gt=0, le=MAX_SEGMENT_SECONDS)
    content_type: Literal["video/mp2t"] = "video/mp2t"
    data_base64: str = Field(min_length=1, max_length=4 * ((MAX_SEGMENT_BYTES + 2) // 3))

    def media_bytes(self):
        try:
            data = base64.b64decode(self.data_base64, validate=True)
        except ValueError:
            raise ValueError("invalid video encoding") from None
        validate_mpegts(data)
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("video digest mismatch")
        return data

    @model_validator(mode="after")
    def valid_media(self):
        if self.captured_at < self.session_started_at:
            raise ValueError("capture precedes session")
        self.media_bytes()
        return self

    def acknowledgement(self):
        return VideoAck.model_validate(self.model_dump(include=set(VideoAck.model_fields)))
