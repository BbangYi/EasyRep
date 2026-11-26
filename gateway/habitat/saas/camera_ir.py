"""Server-side client for the deployed Gateway camera/session and IR APIs.

Requires only Python 3.11+ and httpx. Keep this client, its key and all upstream
cookies on the SaaS server. Authenticate and authorize the SaaS user separately
before invoking it. Do not enable HTTP wire/debug logging with production keys.
An accepted IR command is not evidence of physical illumination. Closing this
client does not send OFF; continuous illumination is an explicit user choice.
"""
from collections.abc import Iterable, Mapping
from datetime import datetime
import ipaddress
import json
import math
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_MAX_SEQUENCE = 9007199254740991
_ERRORS = frozenset({
    "camera_login_required", "invalid_camera_key", "camera_control_required",
    "invalid_csrf", "camera_viewer_not_configured", "cage_not_found",
    "camera_not_found", "waiting_fresh_video", "segment_expired",
    "ir_not_configured", "ir_bridge_unavailable", "control_busy",
    "outputs_locked", "session_changed", "hello_expired", "mqtt_disconnected",
    "ack_failed", "invalid_hello", "command_rejected", "clock_unsynchronized",
    "sequence_error", "no_live_hello", "controller_error", "worker_stopping",
    "state_unavailable", "invalid_command", "cage_not_configured",
})
_CAMERA_STATUSES = frozenset({
    "live", "live_stream_disabled", "waiting_network_camera_binding",
    "waiting_usb_port_binding", "waiting_fresh_video", "waiting_video_frames",
    "waiting_camera", "preview_ready", "archive_full", "camera_frame_stale",
    "capture_failed_check_network_stream", "capture_failed_check_uvc_formats",
    "capture_failed_check_ffmpeg",
})


class CameraIRError(Exception):
    """Safe error details; never includes an upstream request, body or headers.

    outcome_unknown means a command may have reached the controller. Read its
    status and reconcile with the operator; never automatically replay it.
    """

    def __init__(self, code: str, status_code: int | None = None, *, outcome_unknown=False):
        self.code = code
        self.status_code = status_code
        self.outcome_unknown = outcome_unknown
        super().__init__(code)


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def _number(value, minimum=0, maximum=1e12):
    return type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value)


def _timestamp(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.isoformat()
    except ValueError:
        raise CameraIRError("invalid_response") from None


class CameraIRClient:
    """One configured Gateway, with an explicit set of permitted cages/cameras.

    camera_ids maps camera IDs to cage IDs. Methods serialize access to session
    state. A client may be shared within one backend process; never share it
    across untrusted tenants. HTTP is allowed only for explicitly opted-in
    loopback development, never for a store LAN or public host.
    """

    def __init__(self, base_url: str, key: str, site_id: str, gateway_id: str,
                 cage_ids: Iterable[str], camera_ids: Mapping[str, str], *,
                 timeout_s: float = 5, allow_loopback_http: bool = False,
                 transport: httpx.BaseTransport | None = None):
        if not isinstance(base_url, str):
            raise ValueError("base_url requires an HTTPS origin")
        try:
            url = urlsplit(base_url)
            host = url.hostname
            try:
                loopback = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
            except ValueError:
                loopback = False
            valid = (host and not url.username
                     and not url.password and url.path in ("", "/")
                     and not url.query and not url.fragment and url.port != 0
                     and not any(c.isspace() or ord(c) < 32 for c in base_url)
                     and (url.scheme == "https" or
                          (url.scheme == "http" and allow_loopback_http and loopback)))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("base_url requires an HTTPS origin")
        if not isinstance(key, str) or not 32 <= len(key) <= 480 or not re.fullmatch(r"[!-~]+", key):
            raise ValueError("invalid camera access key")
        if not _number(timeout_s, 0.1, 30):
            raise ValueError("timeout_s must be between 0.1 and 30")
        self._site_id, self._gateway_id = _identifier(site_id), _identifier(gateway_id)
        if isinstance(cage_ids, str) or not isinstance(camera_ids, Mapping):
            raise ValueError("invalid cage/camera scope")
        self._cages = frozenset(_identifier(c) for c in cage_ids)
        self._cameras = {_identifier(c): _identifier(g) for c, g in camera_ids.items()}
        if not self._cages or len(self._cages) > 1000 or len(self._cameras) > 2000:
            raise ValueError("invalid cage/camera scope")
        if not set(self._cameras.values()) <= self._cages:
            raise ValueError("camera outside cage scope")
        self._key = key
        self._authenticated = False
        self._closed = False
        self._lock = threading.RLock()
        self._deadline_s = timeout_s * 4
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s,
            follow_redirects=False, trust_env=False, transport=transport,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={"Accept-Encoding": "identity"})

    def __repr__(self):
        return "<CameraIRClient closed=" + str(self._closed) + ">"

    def __enter__(self):
        try:
            self.login()
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def close(self):
        """Release HTTP resources only: no logout request and no IR OFF command."""
        with self._lock:
            self._http.close()
            self._http.cookies.clear()
            self._key = ""
            self._authenticated = False
            self._closed = True

    def _request(self, method, path, *, expected=200, limit=65536, **kwargs):
        if self._closed:
            raise CameraIRError("client_closed")
        started = time.monotonic()
        try:
            with self._http.stream(method, path, **kwargs) as response:
                # Every endpoint is same-origin and uses fixed paths. No redirect
                # is followed, including a redirect from the login endpoint.
                if 300 <= response.status_code < 400:
                    raise CameraIRError("unexpected_redirect", response.status_code)
                cap = limit if response.status_code == expected else 8192
                chunks, total = [], 0
                for chunk in response.iter_bytes(chunk_size=16384):
                    total += len(chunk)
                    if total > cap:
                        raise CameraIRError("response_too_large", response.status_code)
                    if time.monotonic() - started > self._deadline_s:
                        raise CameraIRError("request_timeout")
                    chunks.append(chunk)
                content = b"".join(chunks)
                if response.status_code != expected:
                    try:
                        data = json.loads(content)
                        code = data.get("detail") if isinstance(data, dict) else None
                    except (ValueError, UnicodeError):
                        code = None
                    raise CameraIRError(code if isinstance(code, str) and code in _ERRORS
                                        else "upstream_error", response.status_code)
                return content
        except httpx.HTTPError:
            raise CameraIRError("transport_error") from None

    @staticmethod
    def _json(content):
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError, RecursionError):
            raise CameraIRError("invalid_response") from None

    def login(self):
        """Establish a session and verify the expected site, gateway and mapping."""
        with self._lock:
            self._authenticated = False
            self._http.cookies.clear()
            try:
                self._request("POST", "/camera/session",
                    headers={"Authorization": "Bearer " + self._key})
                data = self._json(self._request("GET", "/camera/api/cameras"))
                self._inventory(data)
                self._authenticated = True
            except Exception:
                self._http.cookies.clear()
                raise

    def _get(self, path, *, limit=65536):
        if not self._authenticated:
            self.login()
        try:
            return self._request("GET", path, limit=limit)
        except CameraIRError as error:
            if error.status_code != 401:
                raise
        self.login()
        return self._request("GET", path, limit=limit)

    def _inventory(self, data):
        if data.get("site_id") != self._site_id or data.get("gateway_id") != self._gateway_id:
            raise CameraIRError("gateway_identity_mismatch")
        cages, cameras = data.get("cage_ids"), data.get("cameras")
        if not isinstance(cages, list) or not all(isinstance(c, str) for c in cages) or not isinstance(cameras, list):
            raise CameraIRError("invalid_response")
        if not self._cages <= set(cages):
            raise CameraIRError("camera_mapping_mismatch")
        result, seen = [], set()
        for row in cameras:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise CameraIRError("invalid_response")
            camera_id = row["id"]
            if camera_id in seen:
                raise CameraIRError("invalid_response")
            seen.add(camera_id)
            if camera_id not in self._cameras:
                continue
            if row.get("cage_id") != self._cameras[camera_id]:
                raise CameraIRError("camera_mapping_mismatch")
            if (row.get("source_type") not in ("http_mjpeg", "rtsp_h264", "uvc")
                    or row.get("view") not in ("top", "front", None)
                    or any(type(row.get(k)) is not int or not 1 <= row[k] <= 16384 for k in ("width", "height"))
                    or not _number(row.get("configured_fps"), 0.01, 1000)
                    or any(type(row.get(k)) is not bool for k in ("live_stream", "fresh"))
                    or (row.get("age_s") is not None and not _number(row["age_s"]))):
                raise CameraIRError("invalid_response")
            clean = {k: row[k] for k in ("id", "cage_id", "source_type", "view", "width", "height",
                                         "configured_fps", "live_stream", "fresh", "age_s")}
            status = row.get("status")
            clean["status"] = status if isinstance(status, str) and status in _CAMERA_STATUSES else "unknown"
            clean["last_segment_at"] = _timestamp(row.get("last_segment_at"))
            result.append(clean)
        if not set(self._cameras) <= seen:
            raise CameraIRError("camera_mapping_mismatch")
        return {"site_id": self._site_id, "gateway_id": self._gateway_id,
                "cage_ids": sorted(self._cages), "cameras": result}

    def inventory(self):
        """Return only configured, permitted cameras and public inventory fields."""
        with self._lock:
            return self._inventory(self._json(self._get("/camera/api/cameras")))

    def _cage(self, cage_id):
        _identifier(cage_id)
        if cage_id not in self._cages:
            raise ValueError("cage outside configured scope")
        return cage_id

    def _camera(self, camera_id):
        _identifier(camera_id)
        if camera_id not in self._cameras:
            raise ValueError("camera outside configured scope")
        return camera_id

    @staticmethod
    def _ir_state(data, cage_id):
        if data.get("cage_id") != cage_id:
            raise CameraIRError("invalid_response")
        if (data.get("status") not in ("unconfigured", "offline", "locked", "off", "starting", "on", "stopping", "error")
                or any(type(data.get(k)) is not bool for k in ("configured", "online", "active"))
                or any(data.get(k) is not None and type(data[k]) is not bool for k in ("outputs_locked", "gpio_requested_on"))
                or data.get("actual_ir_on") is not None
                or data.get("mode") not in (None, "continuous", "timed")
                or (data.get("remaining_s") is not None and not _number(data["remaining_s"], 0, 900))
                or type(data.get("max_on_seconds")) is not int or not 1 <= data["max_on_seconds"] <= 900):
            raise CameraIRError("invalid_response")
        clean = {k: data.get(k) for k in ("cage_id", "configured", "status", "online", "outputs_locked",
                  "gpio_requested_on", "actual_ir_on", "active", "mode", "remaining_s", "max_on_seconds")}
        error = data.get("error")
        clean["error"] = error if isinstance(error, str) and error in _ERRORS else ("controller_error" if error else None)
        return clean

    def ir_status(self, cage_id):
        with self._lock:
            return self._ir_state(self._json(self._get("/camera/api/ir/" + self._cage(cage_id))), cage_id)

    def command_ir(self, cage_id, action, seconds=None):
        """Submit once; return the 202 state, not physical-light confirmation.

        on + None means continuous; on + 1..900 means timed. off takes no timer.
        This method NEVER retries a command POST. On an ambiguous error, fetch
        status and reconcile before an operator explicitly issues another action.
        """
        with self._lock:
            self._cage(cage_id)
            if action not in ("on", "off") or (seconds is not None and
                    (type(seconds) is not int or not 1 <= seconds <= 900)) or (action == "off" and seconds is not None):
                raise ValueError("invalid IR command")
            session = self._json(self._get("/camera/control/session"))
            if session.get("can_control") is not True:
                raise CameraIRError("camera_control_required", 403)
            csrf = session.get("csrf_token")
            if not isinstance(csrf, str) or not re.fullmatch(r"[0-9a-f]{64}", csrf):
                raise CameraIRError("invalid_response")
            body = {"action": action}
            if seconds is not None:
                body["seconds"] = seconds
            try:
                content = self._request("POST", "/camera/api/ir/" + cage_id, expected=202,
                                        headers={"X-Habitat-CSRF": csrf}, json=body)
                return self._ir_state(self._json(content), cage_id)
            except CameraIRError as error:
                if error.status_code == 401:
                    self._authenticated = False
                error.outcome_unknown = error.status_code not in (401, 403, 404, 409, 422)
                raise

    @staticmethod
    def _segment_path(session_id, sequence):
        try:
            valid = isinstance(session_id, str) and str(UUID(session_id)) == session_id
        except ValueError:
            valid = False
        if not valid or type(sequence) is not int or not 0 <= sequence <= _MAX_SEQUENCE:
            raise ValueError("invalid HLS segment identifier")
        return f"{session_id}/{sequence}.ts"

    def playlist(self, camera_id):
        """Return a validated media playlist; keep its relative segment paths.

        A SaaS proxy should expose index.m3u8 and {session_id}/{sequence}.ts under
        the same authenticated camera route. Never fetch an arbitrary playlist URL.
        """
        with self._lock:
            content = self._get("/camera/hls/" + self._camera(camera_id) + "/index.m3u8", limit=16384)
            try:
                text = content.decode("utf-8")
                lines = text.splitlines()
                if not lines or lines[0] != "#EXTM3U":
                    raise ValueError
                count = 0
                for line in lines[1:]:
                    if line in ("#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"):
                        continue
                    if re.fullmatch(r"#EXT-X-(?:TARGETDURATION|MEDIA-SEQUENCE):[0-9]{1,16}", line):
                        continue
                    if re.fullmatch(r"#EXTINF:[0-9]{1,3}\.[0-9]{6},", line):
                        continue
                    if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                        _timestamp(line.split(":", 1)[1])
                        continue
                    match = re.fullmatch(r"([0-9a-f-]{36})/([0-9]{1,16})\.ts", line)
                    if not match or self._segment_path(match[1], int(match[2])) != line:
                        raise ValueError
                    count += 1
                if not 1 <= count <= 100:
                    raise ValueError
                return text
            except (ValueError, UnicodeError, CameraIRError):
                raise CameraIRError("invalid_playlist") from None

    def segment(self, camera_id, session_id, sequence):
        with self._lock:
            path = "/camera/hls/" + self._camera(camera_id) + "/" + self._segment_path(session_id, sequence)
            data = self._get(path, limit=2 * 1024 * 1024)
            if len(data) < 188 or len(data) % 188 or any(data[i] != 0x47 for i in range(0, len(data), 188)):
                raise CameraIRError("invalid_segment")
            return data
