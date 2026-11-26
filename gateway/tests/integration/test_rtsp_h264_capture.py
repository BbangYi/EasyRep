"""Real loopback RTSP/TCP passthrough checks; no physical camera claims."""
import base64
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import re
import shutil
import socket
import socketserver
import struct
import subprocess
import threading
import time

import pytest

from habitat.vision.cameras import CameraConfig, video_command, verify_h264_segment
from habitat.saas.video_contract import MAX_SEGMENT_BYTES


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")


def _nals(data):
    return [nal.rstrip(b"\0") for nal in re.split(rb"\x00\x00(?:\x00)?\x01", data)
            if nal.rstrip(b"\0")]


def _vcl_hashes(data):
    return [hashlib.sha256(nal).hexdigest() for nal in _nals(data) if nal[0] & 31 in (1, 5)]


def _encode(path, *, profile="baseline", codec="libx264", seconds=2):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
               "-i", "testsrc2=size=320x240:rate=10", "-t", str(seconds), "-an",
               "-c:v", codec, "-threads", "1"]
    if codec == "libx264":
        command += ["-profile:v", profile, "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-g", "20", "-keyint_min", "20", "-sc_threshold", "0", "-bf", "0",
                    "-x264-params", "aud=1:repeat-headers=1",
                    "-color_range", "0", "-colorspace", "2", "-color_trc", "2", "-color_primaries", "2"]
        if profile == "main":
            command += ["-coder", "1"]
    subprocess.run(command + [str(path)], check=True, capture_output=True, timeout=15)


def _elementary_stream(path):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"],
        check=True, capture_output=True, timeout=10).stdout


def _color_metadata(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=color_range,color_space,color_transfer,color_primaries",
        "-of", "json", str(path)], check=True, capture_output=True, timeout=10)
    return json.loads(result.stdout)["streams"][0]


class _RTSPHandler(socketserver.StreamRequestHandler):
    """Only the RTSP/TCP-interleaved subset exercised by the production reader."""

    def handle(self):
        server = self.server
        server.connections.append(self.request)
        self.stopped = threading.Event()
        self.send_lock = threading.Lock()
        sender = None
        try:
            while not self.stopped.is_set():
                first = self.rfile.read(1)
                if not first:
                    break
                if first == b"$":  # Client RTCP on the interleaved control channel.
                    header = self.rfile.read(3)
                    if len(header) != 3:
                        break
                    self.rfile.read(struct.unpack("!H", header[1:])[0])
                    continue
                request = (first + self.rfile.readline()).decode("ascii").strip().split()
                if len(request) != 3:
                    break
                method, uri, _ = request
                headers = {}
                while line := self.rfile.readline().strip():
                    key, value = line.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                self.rfile.read(int(headers.get("content-length", "0")))
                server.requests.append((method, uri, headers))
                response = ["RTSP/1.0 200 OK", "CSeq: " + headers["cseq"]]
                body = b""
                if method == "OPTIONS":
                    response += ["Public: OPTIONS, DESCRIBE, SETUP, PLAY, GET_PARAMETER, TEARDOWN"]
                elif method == "DESCRIBE":
                    response += ["Content-Type: application/sdp", "Content-Base: " + server.url + "/"]
                    body = server.sdp
                elif method == "SETUP":
                    assert "RTP/AVP/TCP" in headers["transport"]
                    response += ["Transport: RTP/AVP/TCP;unicast;interleaved=0-1",
                                 "Session: 12345678;timeout=60"]
                elif method in ("PLAY", "GET_PARAMETER", "TEARDOWN"):
                    response += ["Session: 12345678"]
                response += ["Content-Length: " + str(len(body))]
                with self.send_lock:
                    self.request.sendall(("\r\n".join(response) + "\r\n\r\n").encode() + body)
                if method == "PLAY":
                    sender = threading.Thread(target=self._stream, daemon=True)
                    sender.start()
                elif method == "TEARDOWN":
                    break
        except (OSError, ValueError):
            pass  # Reader shutdown closes this bounded fixture connection.
        finally:
            self.stopped.set()
            if sender:
                sender.join(timeout=2)

    def _stream(self):
        sequence, started = 0, time.monotonic()
        try:
            for index, access_unit in enumerate(self.server.access_units):
                if self.stopped.wait(max(0, started + index / 10 - time.monotonic())):
                    return
                for nal_index, nal in enumerate(access_unit):
                    if len(nal) <= 1200:
                        payloads = [nal]
                    else:
                        chunks = [nal[pos:pos + 1198] for pos in range(1, len(nal), 1198)]
                        payloads = [bytes(((nal[0] & 0xE0) | 28,
                            (nal[0] & 31) | (0x80 if part == 0 else 0)
                            | (0x40 if part == len(chunks) - 1 else 0))) + chunk
                            for part, chunk in enumerate(chunks)]
                    for part, payload in enumerate(payloads):
                        marker = nal_index == len(access_unit) - 1 and part == len(payloads) - 1
                        rtp = struct.pack("!BBHII", 0x80, 96 | (0x80 if marker else 0),
                                          sequence % 65536, 90000 + index * 9000, 0x12345678) + payload
                        with self.send_lock:
                            self.request.sendall(b"$\0" + struct.pack("!H", len(rtp)) + rtp)
                        sequence += 1
            self.request.shutdown(socket.SHUT_WR)
        except OSError:
            pass


@contextmanager
def _rtsp_camera(data):
    units, current = [], []
    nals = _nals(data)
    for nal in nals:
        if nal[0] & 31 == 9 and current:
            units.append(current)
            current = []
        current.append(nal)
    if current:
        units.append(current)
    sps = next(nal for nal in nals if nal[0] & 31 == 7)
    pps = next(nal for nal in nals if nal[0] & 31 == 8)
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), _RTSPHandler) as server:
        server.daemon_threads = True
        server.connections, server.requests = [], []
        server.access_units = units
        server.url = f"rtsp://127.0.0.1:{server.server_address[1]}/stream"
        server.sdp = ("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=synthetic camera\r\n"
            "c=IN IP4 127.0.0.1\r\nt=0 0\r\na=control:*\r\nm=video 0 RTP/AVP 96\r\n"
            "a=rtpmap:96 H264/90000\r\na=fmtp:96 packetization-mode=1;profile-level-id="
            + sps[1:4].hex() + ";sprop-parameter-sets=" + base64.b64encode(sps).decode()
            + "," + base64.b64encode(pps).decode() + "\r\na=control:trackID=0\r\n").encode()
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            for connection in server.connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            server.shutdown()
            thread.join(timeout=2)


def _camera():
    return CameraConfig(id="TOP", cage_id="CAGE-A", source_type="rtsp_h264", view="top",
        url="rtsp://127.0.0.1:8554/stream", width=320, height=240, fps=10,
        live_stream=True, record_video=True, interval_s=10, segment_s=10)


def test_rtsp_tcp_h264_preserves_bitstream_and_independent_hls(tmp_path):
    fixture = tmp_path / "source.h264"
    _encode(fixture, seconds=12)
    source = fixture.read_bytes()
    expected_color = {"color_range": "tv", "color_space": "smpte170m",
                      "color_transfer": "smpte170m", "color_primaries": "smpte170m"}
    # Source pixels have deliberately unspecified signaling. The output must add
    # limited-range BT.601 metadata without recompressing any coded picture NAL.
    source_color = _color_metadata(fixture)
    assert all(source_color.get(key) in (None, "unknown") for key in expected_color)
    live = tmp_path / "live"
    live.mkdir()
    with _rtsp_camera(source) as server:
        # Only the test fixture substitutes an ephemeral port; production is fixed at 8554.
        camera = _camera().model_copy(update={"url": server.url})
        command = video_command(camera, tmp_path, tmp_path / "preview.jpg", live=live)
        assert command.count("-i") == 1 and "libx264" not in command
        assert command[command.index("-rtsp_transport") + 1] == "tcp"
        process = subprocess.run(command, capture_output=True, timeout=25)
        assert process.returncode == 0, process.stderr.decode()
        assert len(server.connections) == 1
        assert Counter(method for method, _, _ in server.requests)["PLAY"] == 1

    segments = sorted(live.glob("seg-*.ts"))
    assert len(segments) >= 4
    source_hashes = _vcl_hashes(source)
    copied_hls = []
    for segment in segments:
        assert verify_h264_segment(segment, camera)
        assert _color_metadata(segment) == expected_color
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror",
            "-err_detect", "explode", "-i", str(segment), "-f", "null", "-"],
            check=True, capture_output=True, timeout=10)
        elementary = _elementary_stream(segment)
        assert next(nal[0] & 31 for nal in _nals(elementary) if nal[0] & 31 in (1, 5)) == 5
        copied_hls.extend(_vcl_hashes(elementary))
    # The startup probe GOP is deliberately discarded. Thereafter, all coded
    # pictures must be an uninterrupted, unchanged suffix of the camera stream.
    assert 0 < len(source_hashes) - len(copied_hls) <= 40
    assert copied_hls == source_hashes[-len(copied_hls):]
    copied_archive = []
    for clip in sorted(tmp_path.glob("clip-*.mkv")):
        assert _color_metadata(clip) == expected_color
        copied_archive.extend(_vcl_hashes(_elementary_stream(clip)))
    assert copied_archive == copied_hls
    # Completed frames must not be labeled with future wall-clock times because
    # probe-buffered packets predate HLS initialization. No timestamp clamping.
    duration, captured = None, None
    offsets = []
    for line in (live / "index.m3u8").read_text().splitlines():
        if line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",")[0])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            captured = datetime.fromisoformat(line.split(":", 1)[1]).timestamp()
        elif line and not line.startswith("#"):
            offsets.append(captured + duration - (live / line).stat().st_mtime)
    assert offsets and max(offsets) <= 0.25
    assert max(offsets) - min(offsets) < 0.5
    assert (tmp_path / "preview.jpg").stat().st_size > 100


@pytest.mark.parametrize("profile,codec,valid", [
    ("baseline", "libx264", True), ("main", "libx264", False),
    ("baseline", "mpeg2video", False),
])
def test_h264_media_validation_checks_actual_codec_profile_and_size(tmp_path, profile, codec, valid):
    segment = tmp_path / "sample.ts"
    _encode(segment, profile=profile, codec=codec)
    camera = _camera()
    assert verify_h264_segment(segment, camera) is valid
    assert verify_h264_segment(segment, camera.model_copy(update={"width": 640})) is False
    segment.write_bytes(b"corrupt" * 100)
    assert verify_h264_segment(segment, camera) is False


def test_h264_media_validation_bounds_file_before_external_probe(tmp_path, monkeypatch):
    segment = tmp_path / "oversized.ts"
    segment.write_bytes(b"\x47" * (MAX_SEGMENT_BYTES + 1))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("oversized media must not launch FFmpeg"))
    assert verify_h264_segment(segment, _camera()) is False
