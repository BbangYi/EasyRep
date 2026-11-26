"""Camera viewing sessions and separately authorized, bounded IR control."""
import hashlib
import hmac
import math
import os
from pathlib import Path
import secrets
import time
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from habitat.saas.video import AdvertisedSegments, read_live_segments
from habitat.common.http import bearer_token
from habitat.control.ir_web_client import IRWebClient, IRBridgeError

COOKIE = "habitat_camera_session"
CONTROL_COOKIE = "habitat_camera_control_session"
SESSION_SECONDS = 12 * 3600
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer"}


class IRCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["on", "off"]
    seconds: StrictInt | None = Field(default=None, ge=1, le=900)


def mount_camera_viewer(app, settings, worker):
    advertised_segments = AdvertisedSegments()
    token = os.environ.get("HABITAT_CAMERA_VIEWER_TOKEN", "")
    control_token = os.environ.get("HABITAT_CAMERA_CONTROL_TOKEN", "")
    if token and len(token) < 32:
        raise ValueError("HABITAT_CAMERA_VIEWER_TOKEN must have at least 32 characters")
    if control_token and (len(control_token) < 32 or control_token == token):
        raise ValueError("Camera control needs a distinct key with at least 32 characters")
    bridge = (IRWebClient(settings.camera_ir.endpoint,
        bearer_token(settings.camera_ir.token_env, usage="camera IR bridge"))
        if settings.camera_ir.enabled else None)

    def signature(value, key=token):
        return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def valid_cookie(cookie, key):
        if key and len(cookie) <= 160:
            try:
                expiry, nonce, digest = cookie.split(".")
                remaining = int(expiry) - time.time()
                if 0 < remaining <= SESSION_SECONDS and secrets.compare_digest(
                        digest.encode(), signature(expiry + "." + nonce, key).encode()):
                    return True
            except ValueError:
                pass
        return False

    def authorize(request: Request):
        if not token:
            raise HTTPException(503, "camera_viewer_not_configured")
        if valid_cookie(request.cookies.get(COOKIE, ""), token):
            return
        raise HTTPException(401, "camera_login_required", headers=HEADERS)

    def can_control(request):
        return valid_cookie(request.cookies.get(CONTROL_COOKIE, ""), control_token)

    def csrf(request):
        return signature("csrf:" + request.cookies.get(CONTROL_COOKIE, ""), control_token)

    def authorize_control(request: Request):
        authorize(request)
        if not can_control(request):
            raise HTTPException(403, "camera_control_required", headers=HEADERS)
        supplied = request.headers.get("X-Habitat-CSRF", "")
        origin = request.headers.get("Origin")
        if (len(supplied) > 128 or not secrets.compare_digest(supplied.encode(), csrf(request).encode()) or
                (origin is not None and origin != str(request.base_url).rstrip("/"))):
            raise HTTPException(403, "invalid_csrf", headers=HEADERS)

    def ir_configured(cage_id):
        if cage_id not in {c.id for c in settings.cages}:
            raise HTTPException(404, "cage_not_found", headers=HEADERS)
        return bridge is not None and cage_id in settings.camera_ir.cage_ids

    def ir_request(cage_id, command=None):
        try:
            return bridge.request(cage_id, command)
        except IRBridgeError as error:
            raise HTTPException(error.status, error.code, headers=HEADERS) from None

    def camera(camera_id):
        found = next((c for c in settings.cameras if c.id == camera_id and c.live_stream), None)
        if found is None:
            raise HTTPException(404, "camera_not_found")
        return found

    def bound(config, state):
        if config.source_type in ("http_mjpeg", "rtsp_h264") and settings.camera_discovery.enabled:
            return state.get("identity_verified") is True and state.get("reader_running") is True
        return bool(config.url if config.source_type in ("http_mjpeg", "rtsp_h264") else config.device)

    def recent_segments(config, state):
        if not config.live_stream or not bound(config, state):
            return []
        if config.source_type == "rtsp_h264" and state.get("media_verified") is not True:
            return []
        if ((config.source_type in ("http_mjpeg", "rtsp_h264") and not state.get("reader_running"))
                or state.get("reader_running") is False):
            return []
        # Fresh cached media must not conceal a known failed or stopped reader.
        if state.get("status") not in (None, "preview_ready", "waiting_video_frames"):
            return []
        try:
            return read_live_segments(worker.directory / "live" / config.id,
                settings.site_id, settings.gateway_id, config)
        except (OSError, ValueError, KeyError):
            return []

    def segments(camera_id):
        config = camera(camera_id)
        state = worker.status()["cameras"].get(camera_id, {})
        result = recent_segments(config, state)
        if not result:
            raise HTTPException(503, "waiting_fresh_video", headers=HEADERS)
        return result

    @app.get("/camera", include_in_schema=False)
    def page():
        return FileResponse(Path(__file__).with_name("camera.html"), media_type="text/html",
            headers={**HEADERS, "Content-Security-Policy": "default-src 'none'; "
                "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "media-src 'self' blob:; worker-src 'self' blob:; connect-src 'self'; "
                "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})

    @app.get("/camera/hls.js", include_in_schema=False)
    def library():
        return FileResponse(Path(__file__).with_name("assets") / "hls-1.7.3.min.js",
            media_type="text/javascript", headers={"X-Content-Type-Options": "nosniff"})

    @app.post("/camera/session", include_in_schema=False)
    def login(request: Request):
        supplied = request.headers.get("Authorization", "")
        if not token:
            raise HTTPException(503, "camera_viewer_not_configured")
        control = bool(control_token) and secrets.compare_digest(supplied.encode(), ("Bearer " + control_token).encode())
        if len(supplied) > 512 or not (control or secrets.compare_digest(supplied.encode(), ("Bearer " + token).encode())):
            raise HTTPException(401, "invalid_camera_key", headers=HEADERS)
        value = str(int(time.time()) + SESSION_SECONDS) + "." + secrets.token_hex(16)
        response = JSONResponse({"expires_in": SESSION_SECONDS}, headers=HEADERS)
        response.set_cookie(COOKIE, value + "." + signature(value), max_age=SESSION_SECONDS,
            httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/camera")
        if control:
            response.set_cookie(CONTROL_COOKIE, value + "." + signature(value, control_token),
                max_age=SESSION_SECONDS, httponly=True, secure=request.url.scheme == "https",
                samesite="strict", path="/camera")
        else:
            response.delete_cookie(CONTROL_COOKIE, path="/camera", httponly=True, samesite="strict")
        return response

    @app.delete("/camera/session", include_in_schema=False)
    def logout():
        response = Response(status_code=204, headers=HEADERS)
        response.delete_cookie(COOKIE, path="/camera", httponly=True, samesite="strict")
        response.delete_cookie(CONTROL_COOKIE, path="/camera", httponly=True, samesite="strict")
        return response

    @app.get("/camera/control/session", dependencies=[Depends(authorize)])
    def control_session(request: Request):
        allowed = can_control(request)
        return JSONResponse({"can_control": allowed, "csrf_token": csrf(request) if allowed else None}, headers=HEADERS)

    @app.get("/camera/api/ir/{cage_id}", dependencies=[Depends(authorize)])
    def ir_status(cage_id: str):
        if not ir_configured(cage_id):
            return JSONResponse({"cage_id": cage_id, "configured": False, "status": "unconfigured",
                "online": False, "outputs_locked": None, "gpio_requested_on": None,
                "actual_ir_on": None, "active": False, "mode": None, "remaining_s": 0,
                "max_on_seconds": 900, "error": None}, headers=HEADERS)
        return JSONResponse(ir_request(cage_id), headers=HEADERS)

    @app.post("/camera/api/ir/{cage_id}", dependencies=[Depends(authorize_control)])
    def ir_command(cage_id: str, body: IRCommand):
        if not ir_configured(cage_id):
            raise HTTPException(409, "ir_not_configured", headers=HEADERS)
        return JSONResponse(ir_request(cage_id, body.model_dump()), status_code=202, headers=HEADERS)

    @app.get("/camera/api/cameras", dependencies=[Depends(authorize)])
    def listing():
        states = worker.status()["cameras"]
        entries = []
        for config in settings.cameras:
            state = states.get(config.id, {})
            rows = recent_segments(config, state)
            latest = max((row.captured_at for row in rows), default=None)
            if not config.live_stream:
                status = "live_stream_disabled"
            elif not bound(config, state):
                status = ("waiting_network_camera_binding" if config.source_type in ("http_mjpeg", "rtsp_h264")
                          else "waiting_usb_port_binding")
            elif latest is not None:
                status = "live"
            elif state.get("status") not in (None, "preview_ready", "waiting_video_frames"):
                status = state["status"]
            else:
                status = "waiting_fresh_video"
            entries.append({
                "id": config.id, "cage_id": config.cage_id,
                "source_type": config.source_type, "view": config.view,
                "width": config.width, "height": config.height, "configured_fps": config.fps,
                "live_stream": config.live_stream, "status": status, "fresh": latest is not None,
                "age_s": round(max(0, time.time() - latest.timestamp()), 2) if latest else None,
                "last_segment_at": latest.isoformat() if latest else None,
            })
        return JSONResponse({"site_id": settings.site_id, "gateway_id": settings.gateway_id,
            "cage_ids": [cage.id for cage in settings.cages], "cameras": entries}, headers=HEADERS)

    @app.get("/camera/hls/{camera_id}/index.m3u8", dependencies=[Depends(authorize)])
    def playlist(camera_id: str):
        rows = segments(camera_id)
        tail = [rows[-1]]
        for row in reversed(rows[:-1]):
            if row.sequence != tail[-1].sequence - 1:
                break
            tail.append(row)
        rows = list(reversed(tail))
        advertised_segments.remember(camera_id, rows)
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS",
            f"#EXT-X-TARGETDURATION:{max(2, math.ceil(max(r.duration_s for r in rows)))}",
            f"#EXT-X-MEDIA-SEQUENCE:{rows[0].sequence}"]
        for row in rows:
            lines += ["#EXT-X-PROGRAM-DATE-TIME:" + row.captured_at.isoformat(),
                f"#EXTINF:{row.duration_s:.6f},", f"{row.session_id}/{row.sequence}.ts"]
        return Response("\n".join(lines) + "\n", media_type="application/vnd.apple.mpegurl", headers=HEADERS)

    @app.get("/camera/hls/{camera_id}/{session_id}/{sequence}.ts", dependencies=[Depends(authorize)])
    def media(camera_id: str, session_id: str, sequence: int):
        current = segments(camera_id)
        row = next((s for s in current
                    if str(s.session_id) == session_id and s.sequence == sequence), None)
        if row is None:
            row = advertised_segments.read(worker.directory / "live" / camera_id,
                camera_id, session_id, sequence, current[-1])
        if row is None:
            raise HTTPException(404, "segment_expired", headers=HEADERS)
        return Response(row.media_bytes(), media_type="video/mp2t", headers=HEADERS)

    return bridge
