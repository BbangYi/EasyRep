"""Enclosure-scoped proxy for the Pi's private camera and IR API."""

import http.cookiejar
import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from edge.models import Gateway

from .access import allowed_enclosures
from .models import User

_clients = {}
_clients_lock = threading.Lock()
_segment_line = re.compile(r"[0-9a-fA-F-]{36}/[0-9]+\.ts")


class CameraError(Exception):
    def __init__(self, code, status=503):
        self.code = code
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise CameraError("camera_upstream_redirect", 502)


class PiClient:
    def __init__(self, base_url, key):
        self.base_url = base_url
        self.key = key
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
        )
        self.login_lock = threading.Lock()
        self.logged_in = False

    def login(self):
        with self.login_lock:
            request = urllib.request.Request(
                self.base_url + "/camera/session",
                data=b"",
                headers={"Authorization": "Bearer " + self.key},
                method="POST",
            )
            try:
                with self.opener.open(request, timeout=6) as response:
                    response.read(1024)
                    self.logged_in = True
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self.logged_in = False
                raise CameraError("camera_login_failed") from error

    def request(self, path, *, data=None, headers=None, max_bytes=128_000):
        if not self.logged_in:
            self.login()
        for attempt in range(2):
            request = urllib.request.Request(
                self.base_url + path,
                data=data,
                headers=headers or {},
                method="POST" if data is not None else "GET",
            )
            try:
                with self.opener.open(request, timeout=8) as response:
                    content = response.read(max_bytes + 1)
                    if len(content) > max_bytes:
                        raise CameraError("camera_response_too_large", 502)
                    return response.status, content
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self.logged_in = False
                    self.login()
                    continue
                raise CameraError("camera_upstream_unavailable", 404 if error.code == 404 else 503) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise CameraError("camera_upstream_unavailable") from error
        raise CameraError("camera_upstream_unavailable")


def _config():
    path = os.environ.get("HABITAT_CAMERA_IR_CONFIG", "/etc/habitatos-camera-ir.json")
    if not Path(path).is_file():
        raise CameraError("camera_not_configured", 404)
    try:
        config = json.loads(Path(path).read_text())
        base = config["gateway"]["base_url"].rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query:
            raise ValueError("invalid camera gateway URL")
        return config, base
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CameraError("camera_configuration_invalid", 503) from error


def _context(request, enclosure_id):
    if enclosure_id is None:
        # CAGE-001 currently has no EasyRep enclosure. Keep its physical feed
        # separate from CAGE-002 until the physical installation is verified.
        if request.user.role != User.Role.OWNER:
            raise CameraError("permission_denied", 403)
        config, base = _config()
        cage_ids = config["gateway"].get("cage_ids", [])
        if len(cage_ids) != 1 or cage_ids[0] not in config.get("camera_roles", {}):
            raise CameraError("camera_configuration_invalid")
        gateway = Gateway.objects.filter(
            store__edge_site_id=config["gateway"].get("site_id"),
            edge_gateway_id=config["gateway"].get("gateway_id"), active=True,
        ).first()
        if not gateway:
            raise CameraError("camera_not_configured", 404)
        return config, base, cage_ids[0]
    enclosure = get_object_or_404(
        allowed_enclosures(request.user).select_related("store", "edge_binding__gateway"),
        pk=enclosure_id,
    )
    config, base = _config()
    gateway = getattr(getattr(enclosure, "edge_binding", None), "gateway", None)
    cage_id = enclosure.edge_cage_id
    if (
        not gateway or not gateway.active or not cage_id
        or enclosure.store.edge_site_id != config["gateway"].get("site_id")
        or gateway.edge_gateway_id != config["gateway"].get("gateway_id")
        or cage_id not in config["gateway"].get("cage_ids", [])
        or cage_id not in config.get("camera_roles", {})
    ):
        raise CameraError("camera_not_configured", 404)
    return config, base, cage_id


def _client(config, base, role="viewer"):
    key = config.get("credentials", {}).get(role + "_key")
    if not isinstance(key, str) or not key:
        raise CameraError("camera_credentials_missing")
    with _clients_lock:
        identity = (base, role)
        client = _clients.get(identity)
        if client is None or client.key != key:
            client = PiClient(base, key)
            _clients[identity] = client
        return client


def _json(client, path):
    try:
        return json.loads(client.request(path)[1])
    except (ValueError, UnicodeDecodeError) as error:
        raise CameraError("camera_response_invalid") from error


def _inventory(config, base, cage_id):
    data = _json(_client(config, base), "/camera/api/cameras")
    if (
        data.get("site_id") != config["gateway"]["site_id"]
        or data.get("gateway_id") != config["gateway"]["gateway_id"]
        or cage_id not in data.get("cage_ids", [])
    ):
        raise CameraError("camera_identity_mismatch", 503)
    allowed = set(config["camera_roles"][cage_id].values())
    cameras = {
        item["id"]: item for item in data.get("cameras", [])
        if item.get("id") in allowed and item.get("cage_id") == cage_id
    }
    if set(cameras) != allowed:
        raise CameraError("camera_identity_mismatch", 503)
    return cameras


def _error(error):
    return JsonResponse({"error": error.code}, status=error.status)


@require_GET
def cameras(request, enclosure_id=None):
    try:
        config, base, cage_id = _context(request, enclosure_id)
        inventory = _inventory(config, base, cage_id)
        prefix = f"/api/enclosures/{enclosure_id}/camera" if enclosure_id else "/api/camera"
        return JsonResponse({"cageId": cage_id, "cameras": [
            {
                "id": camera_id,
                "view": role,
                "fresh": inventory[camera_id].get("fresh") is True,
                "status": inventory[camera_id].get("status"),
                "playlist": f"{prefix}/hls/{camera_id}/index.m3u8",
            }
            for role, camera_id in config["camera_roles"][cage_id].items()
        ]})
    except CameraError as error:
        return _error(error)


def _media_context(request, enclosure_id, camera_id):
    config, base, cage_id = _context(request, enclosure_id)
    if camera_id not in config["camera_roles"][cage_id].values():
        raise CameraError("camera_not_found", 404)
    _inventory(config, base, cage_id)
    return config, base


@require_GET
def playlist(request, camera_id, enclosure_id=None):
    try:
        config, base = _media_context(request, enclosure_id, camera_id)
        body = _client(config, base).request(
            f"/camera/hls/{camera_id}/index.m3u8"
        )[1].decode("utf-8")
        if not body.startswith("#EXTM3U") or any(
            (line and not line.startswith("#") and not _segment_line.fullmatch(line))
            or (line.startswith("#") and "URI=" in line)
            for line in body.splitlines()
        ):
            raise CameraError("camera_playlist_invalid", 502)
        return HttpResponse(body, content_type="application/vnd.apple.mpegurl")
    except (UnicodeDecodeError, CameraError) as error:
        return _error(error if isinstance(error, CameraError) else CameraError("camera_playlist_invalid", 502))


@require_GET
def segment(request, camera_id, session_id, sequence, enclosure_id=None):
    try:
        config, base = _media_context(request, enclosure_id, camera_id)
        _, body = _client(config, base).request(
            f"/camera/hls/{camera_id}/{session_id}/{sequence}.ts", max_bytes=4_000_000
        )
        return HttpResponse(body, content_type="video/mp2t")
    except CameraError as error:
        return _error(error)


@require_GET
def ir_status(request, enclosure_id=None):
    try:
        config, base, cage_id = _context(request, enclosure_id)
        _inventory(config, base, cage_id)
        data = _json(_client(config, base), f"/camera/api/ir/{cage_id}")
        if data.get("cage_id") != cage_id:
            raise CameraError("camera_identity_mismatch", 503)
        return JsonResponse({"status": data.get("status"), "online": data.get("online"),
                             "remainingSeconds": data.get("remaining_s"), "error": data.get("error")})
    except CameraError as error:
        return _error(error)


@require_POST
def ir_command(request, enclosure_id=None):
    if request.user.role not in (User.Role.OWNER, User.Role.MANAGER):
        return JsonResponse({"error": "permission_denied"}, status=403)
    try:
        config, base, cage_id = _context(request, enclosure_id)
        _inventory(config, base, cage_id)
        if len(request.body) > 128:
            raise CameraError("invalid_command", 400)
        command = json.loads(request.body)
        if command == {"action": "on"}:
            command["seconds"] = 300
        elif command != {"action": "off"}:
            raise CameraError("invalid_command", 400)
        client = _client(config, base, "control")
        control = _json(client, "/camera/control/session")
        token = control.get("csrf_token")
        if control.get("can_control") is not True or not token:
            raise CameraError("camera_control_unavailable")
        _, body = client.request(
            f"/camera/api/ir/{cage_id}",
            data=json.dumps(command).encode(),
            headers={"Content-Type": "application/json", "X-Habitat-CSRF": token},
        )
        data = json.loads(body)
        if data.get("cage_id") != cage_id:
            raise CameraError("camera_identity_mismatch", 503)
        return JsonResponse({"accepted": True, "status": data.get("status")}, status=202)
    except (ValueError, TypeError):
        return _error(CameraError("invalid_command", 400))
    except CameraError as error:
        return _error(error)
