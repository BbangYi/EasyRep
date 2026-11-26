"""One UVC, MJPEG or native H.264 reader sharing preview, live and archive."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import Field, ValidationInfo, field_validator, model_validator
from habitat.common.models import Identifier, Model
from habitat.saas.video_contract import MAX_SEGMENT_BYTES, SEGMENT_SECONDS, PLAYLIST_SEGMENTS, HLS_DELETE_THRESHOLD


CAMERA_LAN_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in
                          ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"))
RTSP_H264_PORT = 8554
RTSP_H264_PATH = "/stream"
RTSP_H264_METADATA_BSF = ("h264_metadata=video_full_range_flag=0:colour_primaries=6:"
                          "transfer_characteristics=6:matrix_coefficients=6")
RTSP_H264_IDENTITY = {
    "schema_version": 2, "stream_transport": "rtsp_tcp", "codec": "h264",
    "stream_port": RTSP_H264_PORT, "stream_path": RTSP_H264_PATH,
    "profile": "baseline", "sps_pps_at_idr": True,
    "color_range": "limited", "color_matrix": "bt601",
}


class CameraConfig(Model):
    id: Identifier
    cage_id: Identifier
    expected_model: str | None = Field(default=None, min_length=1, max_length=160)
    source_type: Literal["uvc", "http_mjpeg", "rtsp_h264"] = "uvc"
    view: Literal["top", "front"] | None = None
    device: str | None = None
    url: str | None = None
    width: int = Field(default=640, ge=160, le=1920)
    height: int = Field(default=480, ge=120, le=1080)
    interval_s: int = Field(default=30, ge=10, le=3600)
    record_video: bool = False
    live_stream: bool = False
    fps: int = Field(default=10, ge=1, le=30)
    segment_s: int = Field(default=60, ge=10, le=300)
    archive_max_mb: int = Field(default=2048, ge=64, le=102400)
    min_free_mb: int = Field(default=1024, ge=256, le=102400)

    @field_validator("device")
    @classmethod
    def stable_device(cls, value):
        if value is not None:
            p = Path(value)
            if (str(p.parent) not in ("/dev/v4l/by-id", "/dev/v4l/by-path")
                    or not p.name.endswith("-video-index0") or "usb-" not in p.name):
                raise ValueError("camera needs stable /dev/v4l/by-id or by-path video-index0 mapping")
        return value

    @field_validator("url")
    @classmethod
    def local_stream(cls, value, info: ValidationInfo):
        if value in (None, ""):
            return None
        try:
            parsed = urlsplit(value)
            address = ipaddress.ip_address(parsed.hostname or "")
            port = parsed.port
        except ValueError:
            raise ValueError("camera URL needs a literal LAN IP address and valid port") from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        rtsp = info.data.get("source_type") == "rtsp_h264"
        scheme = "rtsp" if rtsp else "http"
        if (parsed.scheme != scheme or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                or "%" in (parsed.hostname or "")
                or not (address.is_private or address.is_loopback)
                or address.is_unspecified or address.is_multicast
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError("camera URL must use its local transport without credentials, query or fragment")
        if rtsp and (address.version != 4 or not any(address in net for net in CAMERA_LAN_NETWORKS)
                     or port != RTSP_H264_PORT or parsed.path != RTSP_H264_PATH):
            raise ValueError("RTSP H264 requires an RFC1918/loopback IPv4 address, port 8554 and /stream")
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        authority = host + (f":{port}" if port not in (None, 80) else "")
        return urlunsplit((scheme, authority, parsed.path or "/", "", ""))

    @model_validator(mode="after")
    def coherent_source(self):
        if self.source_type == "uvc" and self.url is not None:
            raise ValueError("UVC cameras use device, not url")
        if self.is_network and self.device is not None:
            raise ValueError("network cameras use url, not device")
        if self.source_type == "rtsp_h264" and (self.width % 2 or self.height % 2 or self.view is None):
            raise ValueError("RTSP H264 requires even dimensions and an explicit top/front view")
        return self

    @property
    def is_network(self):
        return self.source_type in ("http_mjpeg", "rtsp_h264")


def discover():
    return [{"device": str(path), "node": str(path.resolve())}
            for path in sorted(Path("/dev/v4l/by-path").glob("*usb-*-video-index0"))]


def video_command(camera, directory, preview, *, live=None, record=None):
    """One input; native H.264 is copied while legacy inputs retain encoding."""
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-threads", "1"]
    if camera.source_type == "http_mjpeg":
        # No internal reconnect: each failed connection becomes a visible stopped
        # reader, then CameraWorker starts a fresh session after bounded backoff.
        # Allow bounded Wi-Fi pauses without restarting a still-recoverable stream.
        command += ["-rw_timeout", "10000000", "-protocol_whitelist", "http,tcp",
            "-http_proxy", "", "-max_redirects", "0",
            "-f", "mpjpeg", "-use_wallclock_as_timestamps", "1",
            "-analyzeduration", "100000", "-probesize", "262144", "-i", camera.url]
    elif camera.source_type == "rtsp_h264":
        # Discard startup probe packets rather than stamp buffered media with
        # the later HLS initialization clock. Keep the camera's RTP timestamps.
        command += ["-fflags", "+nobuffer", "-rtsp_transport", "tcp", "-timeout", "10000000",
            "-allowed_media_types", "video", "-protocol_whitelist", "tcp",
            "-analyzeduration", "1000000", "-probesize", "1048576", "-i", camera.url]
    else:
        command += ["-f", "v4l2", "-input_format", "mjpeg",
            "-framerate", str(camera.fps), "-video_size", f"{camera.width}x{camera.height}",
            "-i", camera.device]
    if (camera.record_video if record is None else record):
        command += ["-map", "0:v:0", "-c:v", "copy", "-an"]
        if camera.source_type == "rtsp_h264":
            command += ["-bsf:v", RTSP_H264_METADATA_BSF]
        command += ["-f", "segment", "-segment_time", str(camera.segment_s), "-reset_timestamps", "1",
            "-segment_list", str(directory / "segments.csv"), "-segment_list_type", "csv",
            str(directory / "clip-%06d.mkv")]
    if live is not None:
        if camera.source_type == "rtsp_h264":
            # The camera owns codec, resolution, bitrate, SPS/PPS and IDR cadence.
            # Identity v2 guarantees limited-range BT.601 pixels. Label their
            # SPS VUI without changing VCL payloads or decoding the live output.
            command += ["-map", "0:v:0", "-an", "-c:v", "copy",
                        "-bsf:v", RTSP_H264_METADATA_BSF]
        else:
            command += ["-map", "0:v:0", "-an", "-vf", f"fps={camera.fps}",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-threads", "1",
                "-pix_fmt", "yuv420p", "-g", str(camera.fps * SEGMENT_SECONDS),
                "-keyint_min", str(camera.fps * SEGMENT_SECONDS), "-sc_threshold", "0",
                "-b:v", "1000k", "-maxrate", "1000k", "-bufsize", "2000k"]
        command += ["-f", "hls", "-hls_time", str(SEGMENT_SECONDS), "-hls_list_size", str(PLAYLIST_SEGMENTS),
            "-hls_start_number_source", "epoch_us",
            "-hls_delete_threshold", str(HLS_DELETE_THRESHOLD), "-hls_flags",
            "delete_segments+temp_file+independent_segments+program_date_time",
            "-hls_segment_filename", str(live / "seg-%016d.ts"), str(live / "index.m3u8")]
    command += ["-map", "0:v:0", "-an",
            "-vf", f"fps=1/{camera.interval_s}", "-threads", "1", "-f", "image2",
            "-update", "1", "-atomic_writing", "1", str(preview)]
    return command


def verify_h264_segment(path, camera):
    """Check bounded local media, never open another camera connection.

    Identity alone cannot prove the bytes are independently decodable Baseline
    H.264. Run off the gateway cycle because malformed input may hit a timeout.
    """
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_SEGMENT_BYTES + 1)
        if not 188 <= len(data) <= MAX_SEGMENT_BYTES:
            return False
        probe = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "pipe",
            "-f", "mpegts", "-i", "pipe:0", "-select_streams", "v:0",
            "-read_intervals", "%+#1", "-show_entries",
            "stream=codec_name,profile,width,height:packet=flags", "-of", "json"],
            input=data, capture_output=True, timeout=3, check=True)
        info = json.loads(probe.stdout)
        streams, packets = info.get("streams", []), info.get("packets", [])
        if (not streams or streams[0].get("codec_name") != "h264"
                or streams[0].get("profile") not in ("Baseline", "Constrained Baseline")
                or (streams[0].get("width"), streams[0].get("height")) != (camera.width, camera.height)
                or not packets or "K" not in packets[0].get("flags", "")):
            return False
        decoded = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-xerror", "-err_detect", "explode", "-protocol_whitelist", "pipe",
            "-threads", "1", "-f", "mpegts", "-i", "pipe:0", "-map", "0:v:0",
            "-frames:v", "1", "-f", "null", "-"], input=data, capture_output=True, timeout=3)
        return decoded.returncode == 0 and not decoded.stderr
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return False


class CameraWorker:
    def __init__(self, configs, directory, *, discovery=None):
        self.configs = configs
        self.directory = Path(directory)
        self.discovery = discovery
        self.states = {}
        self.next_capture = {}
        self.recorders = {}
        self.archive_enabled = {}
        self.stopping = {}
        # Runtime addresses never mutate the registered configuration. Keep a
        # stopping reader's address reserved until its process is actually gone.
        self.network_sources = {}
        self.verified_sources = set()
        self.verified_h264 = set()
        self.h264_checks = {}
        self._media_executor = None

    @staticmethod
    def _endpoint(camera):
        if not camera.is_network or not camera.url:
            return None
        parsed = urlsplit(camera.url)
        return parsed.hostname, parsed.port or 80

    def _occupied_network_endpoints(self, *, except_id=None):
        configs = {camera.id: camera for camera in self.configs}
        return {endpoint for camera_id in set(self.recorders) | set(self.stopping)
                if camera_id != except_id
                and (camera := self.network_sources.get(camera_id, configs.get(camera_id))) is not None
                and (endpoint := self._endpoint(camera)) is not None}

    def _invalidate_source(self, camera_id):
        self.verified_sources.discard(camera_id)
        self.verified_h264.discard(camera_id)
        check = self.h264_checks.pop(camera_id, None)
        if check is not None:
            check.cancel()
        if self.discovery is not None:
            self.discovery.invalidate(camera_id)

    def _release_source(self, camera_id):
        self._invalidate_source(camera_id)
        self.network_sources.pop(camera_id, None)

    @staticmethod
    def _finish_session(process, directory, started):
        if directory is None:
            return
        try:
            metadata = json.loads((directory / "session.json").read_text())
            metadata.update(stopped_at=datetime.now(timezone.utc).isoformat(), returncode=process.returncode,
                            elapsed_seconds=time.monotonic()-started)
            (directory / "session.json").write_text(json.dumps(metadata, indent=2))
        except OSError:
            pass  # Disk-full shutdown must still stop every camera.

    def _reap_stopping(self):
        for camera_id, (process, directory, started, deadline) in list(self.stopping.items()):
            if process.poll() is None:
                if time.monotonic() >= deadline:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                continue
            self.stopping.pop(camera_id)
            self._finish_session(process, directory, started)
            self._release_source(camera_id)

    def _stop(self, camera_id, *, wait=True):
        self._invalidate_source(camera_id)
        active = self.recorders.pop(camera_id, None)
        self.archive_enabled.pop(camera_id, None)
        if active is None and wait:
            pending = self.stopping.pop(camera_id, None)
            active = pending[:3] if pending else None
        if active is None:
            return
        process, directory, started = active
        if process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            if not wait:
                self.stopping[camera_id] = (*active, time.monotonic() + 3)
                return
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self._finish_session(process, directory, started)
        self.network_sources.pop(camera_id, None)

    def close(self):
        try:
            for camera_id in set(self.recorders) | set(self.stopping):
                self._stop(camera_id)
        finally:
            if self.discovery is not None:
                self.discovery.close()
            if self._media_executor is not None:
                self._media_executor.shutdown(wait=True, cancel_futures=True)

    def _check_h264(self, camera):
        if camera.id in self.verified_h264 or not camera.live_stream:
            return True
        check = self.h264_checks.get(camera.id)
        if check is not None:
            if not check.done():
                return None
            self.h264_checks.pop(camera.id)
            if check.result():
                self.verified_h264.add(camera.id)
                return True
            return False
        # At most two bounded local probes run concurrently. Other cameras keep
        # receiving; they remain unavailable to viewers until their probe passes.
        if len(self.h264_checks) < 2:
            segments = sorted((self.directory / "live" / camera.id).glob("seg-*.ts"))
            if segments:
                if self._media_executor is None:
                    self._media_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="camera-media-check")
                self.h264_checks[camera.id] = self._media_executor.submit(verify_h264_segment, segments[0], camera)
        return None

    def _video_cycle(self, camera, state):
        network = camera.is_network
        archive = self.directory / "recordings" / camera.id
        archive.mkdir(parents=True, exist_ok=True)
        # ponytail: scan this bounded archive every cycle; index it if measured IO warrants it.
        used = sum(p.stat().st_size for p in archive.rglob("*") if p.is_file())
        full = used >= camera.archive_max_mb*1024**2 or shutil.disk_usage(archive).free < camera.min_free_mb*1024**2
        record = camera.record_video and not full
        if camera.record_video and full and not camera.live_stream:
            self._stop(camera.id, wait=not network)
            self.states[camera.id] = {**state, "status": "archive_full", "recording": "paused_preserving_clips"}
            return
        if camera.id in self.recorders and self.archive_enabled.get(camera.id) != record:
            self._stop(camera.id, wait=not network)
            if network and self.discovery is not None:
                self.states[camera.id] = {**state, "status": "waiting_network_camera_binding", "recording": "retry_pending"}
                return
        if camera.id in self.stopping:
            self.states[camera.id] = {**state, "status": "waiting_video_frames", "recording": "retry_pending"}
            return
        active = self.recorders.get(camera.id)
        preview = self.directory / f"{camera.id}.jpg"
        if active:
            process, directory, started = active
            age = time.time() - preview.stat().st_mtime if preview.exists() else time.monotonic()-started
            if process.poll() is not None or age > max(30, camera.interval_s*3):
                self._stop(camera.id, wait=not network)
                self.next_capture[camera.id] = time.time() + 30
                failure = "capture_failed_check_network_stream" if network else "capture_failed_check_uvc_formats"
                self.states[camera.id] = {**state, "status": failure, "recording": "retry_pending"}
                return
        elif time.time() >= self.next_capture.get(camera.id, 0):
            live = self.directory / "live" / camera.id if camera.live_stream else None
            session_id = uuid4()
            if live is not None:
                live.mkdir(parents=True, exist_ok=True)
                # This cache contains only disposable output from the stopped reader.
                for path in live.iterdir():
                    if path.name in ("index.m3u8", "index.m3u8.tmp", "session.json") or path.name.startswith("seg-"):
                        path.unlink()
                (live / "session.json").write_text(json.dumps({"session_id": str(session_id),
                    "started_at": datetime.now(timezone.utc).isoformat()}))
            directory = archive / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + session_id.hex[:8]) if record else live
            if directory is not None:
                directory.mkdir(exist_ok=True)
            metadata = {"camera": camera.model_dump(exclude={"url"}),
                        "source": "network_" + camera.source_type if network else "physical_usb_uvc",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "clock_note": "process launch UTC; segments.csv stores relative stream PTS, not calibrated sensor alignment",
                        "subject_id": None, "species": None, "labels_reviewed": False}
            if record:
                (directory / "session.json").write_text(json.dumps(metadata, indent=2))
            try:
                preview.unlink(missing_ok=True)
                # Only one process opens the device; preview and archive share its input.
                command = (video_command(camera, directory, preview, live=live, record=record)
                           if live is not None or network else video_command(camera, directory, preview))
                process = subprocess.Popen(command,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.recorders[camera.id] = (process, directory, time.monotonic())
                self.archive_enabled[camera.id] = record
            except OSError:
                self._release_source(camera.id)
                self.next_capture[camera.id] = time.time() + 30
                self.states[camera.id] = {**state, "status": "capture_failed_check_ffmpeg", "recording": "retry_pending"}
                return
        current = self.recorders.get(camera.id)
        if current and camera.source_type == "rtsp_h264" and self._check_h264(camera) is False:
            self._stop(camera.id, wait=False)
            self.next_capture[camera.id] = time.time() + 30
            self.states[camera.id] = {**state, "status": "capture_failed_check_network_stream",
                                     "recording": "retry_pending", "media_verified": False}
            return
        ready = bool(current and current[0].poll() is None and preview.exists()
                     and 0 <= time.time()-preview.stat().st_mtime <= camera.interval_s*2+10)
        self.states[camera.id] = {**state, "status": "preview_ready" if ready else "waiting_video_frames",
                                 "recording": ("running" if current and record else
                                     "paused_preserving_clips" if camera.record_video and full else
                                     "disabled" if not camera.record_video else "retry_pending"), "archive_bytes": used,
                                 "captured_at_epoch": preview.stat().st_mtime if ready else None,
                                 "behavior_model": "not_trained"}

    def cycle(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self._reap_stopping()
        if self.discovery is not None:
            # An unexpected pre-launch filesystem failure may leave a prepared
            # source without a reader. Its consumed identity is not reusable.
            for camera_id in set(self.network_sources) - self.recorders.keys() - self.stopping.keys():
                self._release_source(camera_id)
        bindings = {}
        if self.discovery is not None:
            idle = {camera.id for camera in self.configs
                    if camera.is_network
                    and camera.id not in self.recorders and camera.id not in self.stopping
                    and time.time() >= self.next_capture.get(camera.id, 0)}
            # Discovery only schedules/collects bounded background probes. The
            # camera cycle must keep serving healthy readers during a LAN scan.
            bindings = self.discovery.poll(self.configs, idle, self._occupied_network_endpoints())
        for camera in self.configs:
            now = time.time()
            state = {"camera_id": camera.id, "cage_id": camera.cage_id,
                     "expected_model": camera.expected_model, "checked_at_epoch": now,
                     "source_type": camera.source_type, "view": camera.view,
                     "record_video": camera.record_video, "live_stream": camera.live_stream}
            if camera.is_network:
                effective = self.network_sources.get(camera.id)
                if self.discovery is not None and camera.id not in self.recorders and camera.id not in self.stopping:
                    effective = None
                    url = bindings.get(camera.id)
                    if url is not None:
                        effective = CameraConfig.model_validate({**camera.model_dump(), "url": url})
                        if self._endpoint(effective) in self._occupied_network_endpoints(except_id=camera.id):
                            self._invalidate_source(camera.id)
                            effective = None
                        else:
                            self.network_sources[camera.id] = effective
                            self.verified_sources.add(camera.id)
                elif self.discovery is None:
                    effective = effective or camera
                if camera.id in self.stopping:
                    self.states[camera.id] = {**state, "status": "waiting_video_frames", "recording": "retry_pending"}
                elif effective is None or effective.url is None:
                    if camera.id in self.recorders:
                        self._stop(camera.id, wait=False)
                    self.states[camera.id] = {**state, "status": "waiting_network_camera_binding"}
                elif (self.discovery is not None and camera.id not in self.recorders
                      and self._endpoint(effective) in self._occupied_network_endpoints(except_id=camera.id)):
                    self._release_source(camera.id)
                    self.states[camera.id] = {**state, "status": "waiting_network_camera_binding"}
                else:
                    self.network_sources[camera.id] = effective
                    self._video_cycle(effective, state)
                    if camera.id not in self.recorders and camera.id not in self.stopping:
                        self._release_source(camera.id)
                continue
            if camera.device is None:
                self._stop(camera.id)
                self.states[camera.id] = {**state, "status": "waiting_usb_port_binding"}
                continue
            if not Path(camera.device).exists():
                self._stop(camera.id)
                self.states[camera.id] = {**state, "status": "waiting_camera"}
                continue
            if camera.record_video or camera.live_stream:
                self._video_cycle(camera, state)
                continue
            if now < self.next_capture.get(camera.id, 0):
                continue
            self.next_capture[camera.id] = now + camera.interval_s
            temporary = self.directory / f"{camera.id}.tmp.jpg"
            try:
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "v4l2", "-video_size", f"{camera.width}x{camera.height}", "-i", camera.device,
                    "-frames:v", "1", "-threads", "1", str(temporary)],
                    check=True, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not 100 < temporary.stat().st_size <= 10*1024*1024:
                    raise ValueError("invalid snapshot size")
                temporary.replace(self.directory / f"{camera.id}.jpg")
                self.states[camera.id] = {**state, "status": "preview_ready", "captured_at_epoch": time.time(),
                                         "reconstruction": "requires_multi_view_scan_and_calibration"}
            except (OSError, subprocess.SubprocessError, ValueError):
                self.states[camera.id] = {**state, "status": "capture_failed_check_uvc_formats"}
            finally:
                temporary.unlink(missing_ok=True)

    def status(self):
        states = {key: dict(value) for key, value in self.states.copy().items()}
        for camera in self.configs:
            state = states.get(camera.id)
            if not state:
                continue
            current = self.recorders.get(camera.id)
            state["reader_running"] = current is not None and current[0].poll() is None
            if camera.source_type == "rtsp_h264":
                state["media_verified"] = camera.id in self.verified_h264 and state["reader_running"]
            if camera.is_network:
                state["network_bound"] = bool(self.network_sources.get(camera.id))
                state["identity_verified"] = camera.id in self.verified_sources and state["reader_running"]
                if self.discovery is not None:
                    state["discovery_status"] = self.discovery.status(camera.id)
            if state.get("status") != "preview_ready":
                continue
            try:
                age = time.time() - (self.directory / f"{camera.id}.jpg").stat().st_mtime
                fresh = 0 <= age <= camera.interval_s*2+10
            except OSError:
                fresh = False
            if camera.is_network or camera.live_stream or camera.record_video:
                fresh = fresh and state["reader_running"]
            if not fresh:
                state.update(status="camera_frame_stale", captured_at_epoch=None)
        return {"cameras": states, "available_usb_ports": discover()}
