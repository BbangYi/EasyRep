"""Enclosure-scoped proxy for the Pi's private camera and IR API."""

import http.cookiejar
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from edge.models import Gateway

from .access import allowed_enclosures
from .models import User

_clients = {}
_clients_lock = threading.Lock()
_segment_line = re.compile(r"[0-9a-fA-F-]{36}/[0-9]+\.ts")
_identifier = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_request_identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
logger = logging.getLogger(__name__)
HLS_REQUEST_BUDGET_SECONDS = 8.0
HLS_MAX_SEGMENT_BYTES = 2 * 1024 * 1024


class CameraError(Exception):
    def __init__(self, code, status=503):
        self.code = code
        self.status = status


class HlsRequest:
    """Request-local, content-free diagnostics; never stored on a shared client."""

    def __init__(self, request, kind, camera_id, session_id=None, sequence=None):
        supplied = request.headers.get("X-Request-ID", "")
        self.request_id = supplied if _request_identifier.fullmatch(supplied) else uuid4().hex
        self.kind = kind
        self.camera_id = camera_id if isinstance(camera_id, str) and _identifier.fullmatch(camera_id) else None
        self.session_id = str(session_id) if isinstance(session_id, UUID) else None
        self.sequence = sequence if type(sequence) is int and 0 <= sequence < 2**63 else None
        self.started = time.monotonic()
        self.deadline = self.started + HLS_REQUEST_BUDGET_SECONDS
        self.upstream = []
        self.inventory_cache = None

    def timeout(self, maximum):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CameraError("camera_upstream_unavailable")
        return min(maximum, remaining)

    def record(self, kind, started, status, error):
        self.upstream.append({"kind": kind, "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 2), "error": error})

    def finish(self, status):
        logger.info("camera_hls %s", json.dumps({
            "request_id": self.request_id, "kind": self.kind, "camera_id": self.camera_id,
            "session_id": self.session_id, "sequence": self.sequence,
            "response_status": status, "duration_ms": round((time.monotonic() - self.started) * 1000, 2),
            "upstream_ms": round(sum(item["duration_ms"] for item in self.upstream), 2),
            "upstream": self.upstream, "inventory_cache": self.inventory_cache,
        }, separators=(",", ":")))


def hls_response(kind):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            trace = HlsRequest(request, kind, kwargs.get("camera_id"),
                               kwargs.get("session_id"), kwargs.get("sequence"))
            status = 500
            try:
                try:
                    response = view(request, *args, **kwargs, _hls=trace)
                except Http404:
                    response = _error(CameraError("camera_not_found", 404))
                response["X-Request-ID"] = trace.request_id
                response["Cache-Control"] = "no-store"
                response["X-Accel-Buffering"] = "no"
                status = response.status_code
                return response
            finally:
                trace.finish(status)
        return wrapped
    return decorate


class InventoryCache:
    """Small process-local cache of validated camera IDs, with one fill per key.

    It stores no frames or freshness assertions. Authorization and current
    enclosure bindings must be checked before using it on every media request.
    """

    def __init__(self, ttl=3.0, max_entries=32, clock=time.monotonic):
        self.ttl, self.max_entries, self.clock = ttl, max_entries, clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def invalidate(self, key):
        with self.lock:
            entry = self.entries.pop(key, None)
            if entry and not entry["ready"].is_set():
                entry["error"] = CameraError("camera_identity_mismatch")
                entry["ready"].set()

    def get(self, key, load, trace):
        trace.timeout(HLS_REQUEST_BUDGET_SECONDS)
        with self.lock:
            now = self.clock()
            entry = self.entries.get(key)
            if entry and entry["ready"].is_set() and entry["expires"] > now:
                self.entries.move_to_end(key)
                trace.inventory_cache = "hit"
                return entry["value"]
            if entry and not entry["ready"].is_set():
                owner = False
                trace.inventory_cache = "wait"
            else:
                self.entries.pop(key, None)
                while len(self.entries) >= self.max_entries:
                    removable = next((k for k, v in self.entries.items() if v["ready"].is_set()), None)
                    if removable is None:
                        trace.inventory_cache = "busy"
                        raise CameraError("camera_upstream_unavailable")
                    self.entries.pop(removable)
                entry = {"ready": threading.Event(), "value": None, "error": None, "expires": 0}
                self.entries[key] = entry
                owner = True
                trace.inventory_cache = "miss"
        if not owner:
            if not entry["ready"].wait(trace.timeout(HLS_REQUEST_BUDGET_SECONDS)):
                raise CameraError("camera_upstream_unavailable")
            with self.lock:
                if entry["error"] is not None:
                    raise CameraError(entry["error"].code, entry["error"].status)
                if self.entries.get(key) is not entry:
                    raise CameraError("camera_identity_mismatch")
                if entry["expires"] <= self.clock():
                    raise CameraError("camera_upstream_unavailable")
                return entry["value"]
        try:
            # Only an immutable allow-list is cached, not stale Pi status data.
            value = frozenset(load())
        except Exception as error:
            public_error = error if isinstance(error, CameraError) else CameraError("camera_response_invalid")
            with self.lock:
                if self.entries.get(key) is entry:
                    self.entries.pop(key)
                entry["error"] = public_error
                entry["ready"].set()
            if public_error is error:
                raise
            raise public_error from error
        with self.lock:
            if self.entries.get(key) is not entry:
                # An uncached identity check may have revoked this in-flight
                # fill while the upstream response was being read.
                raise CameraError("camera_identity_mismatch")
            entry["value"], entry["expires"] = value, self.clock() + self.ttl
            entry["ready"].set()
        return value


_inventory_cache = InventoryCache()


def _inventory_key(config, base, cage_id):
    # Include credentials and all mappings without retaining or logging their
    # values in the cache key. A configuration/key rotation cannot reuse a hit.
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return base, cage_id, fingerprint


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

    def _read(self, request, *, timeout, max_bytes, trace=None, kind, enforce_limit=True):
        started, status, failure = time.monotonic(), None, None
        try:
            if trace is not None:
                timeout = trace.timeout(timeout)
                request.add_header("X-Request-ID", trace.request_id)
            with self.opener.open(request, timeout=timeout) as response:
                status = response.status
                content = response.read(max_bytes + 1 if enforce_limit else max_bytes)
                if enforce_limit and len(content) > max_bytes:
                    raise CameraError("camera_response_too_large", 502)
                return status, content
        except urllib.error.HTTPError as error:
            status, failure = error.code, "upstream_http_error"
            raise
        except CameraError as error:
            failure = error.code
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            failure = "network_error"
            raise
        finally:
            if trace is not None:
                trace.record(kind, started, status, failure)

    def login(self, *, trace=None):
        if trace is None:
            self.login_lock.acquire()
        elif not self.login_lock.acquire(timeout=trace.timeout(6)):
            raise CameraError("camera_upstream_unavailable")
        try:
            if trace is not None and self.logged_in:
                return  # Another HLS request completed the same login while we waited.
            request = urllib.request.Request(
                self.base_url + "/camera/session",
                data=b"",
                headers={"Authorization": "Bearer " + self.key},
                method="POST",
            )
            try:
                self._read(request, timeout=6, max_bytes=1024, trace=trace,
                           kind="login", enforce_limit=False)
                self.logged_in = True
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self.logged_in = False
                raise CameraError("camera_login_failed") from error
        finally:
            self.login_lock.release()

    def request(self, path, *, data=None, headers=None, max_bytes=128_000, trace=None):
        if not self.logged_in:
            self.login(trace=trace)
        kind = "inventory" if path == "/camera/api/cameras" else "playlist" if path.endswith(".m3u8") else "segment"
        for attempt in range(2):
            request = urllib.request.Request(
                self.base_url + path,
                data=data,
                headers=headers or {},
                method="POST" if data is not None else "GET",
            )
            try:
                return self._read(request, timeout=8, max_bytes=max_bytes, trace=trace, kind=kind)
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self.logged_in = False
                    self.login(trace=trace)
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


def _json(client, path, *, trace=None):
    try:
        options = {} if trace is None else {"trace": trace}
        return json.loads(client.request(path, **options)[1])
    except (ValueError, UnicodeDecodeError) as error:
        raise CameraError("camera_response_invalid") from error


def _inventory(config, base, cage_id, *, trace=None):
    key = _inventory_key(config, base, cage_id)
    try:
        data = _json(_client(config, base), "/camera/api/cameras", trace=trace)
    except CameraError:
        _inventory_cache.invalidate(key)
        raise
    if (
        not isinstance(data, dict)
        or data.get("site_id") != config["gateway"]["site_id"]
        or data.get("gateway_id") != config["gateway"]["gateway_id"]
        or not isinstance(data.get("cage_ids"), list) or cage_id not in data["cage_ids"]
        or not isinstance(data.get("cameras"), list)
        or any(not isinstance(item, dict) for item in data["cameras"])
    ):
        _inventory_cache.invalidate(key)
        raise CameraError("camera_identity_mismatch", 503)
    allowed = set(config["camera_roles"][cage_id].values())
    cameras = {}
    for item in data["cameras"]:
        identifier = item.get("id")
        if not isinstance(identifier, str) or (identifier in allowed and (
                identifier in cameras or item.get("cage_id") != cage_id)):
            _inventory_cache.invalidate(key)
            raise CameraError("camera_identity_mismatch", 503)
        if identifier in allowed:
            cameras[identifier] = item
    if set(cameras) != allowed:
        _inventory_cache.invalidate(key)
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


def _media_context(request, enclosure_id, camera_id, trace):
    config, base, cage_id = _context(request, enclosure_id)
    if camera_id not in config["camera_roles"][cage_id].values():
        raise CameraError("camera_not_found", 404)
    validated = _inventory_cache.get(_inventory_key(config, base, cage_id),
        lambda: _inventory(config, base, cage_id, trace=trace), trace)
    if camera_id not in validated:
        raise CameraError("camera_not_found", 404)
    return config, base


@require_GET
@hls_response("playlist")
def playlist(request, camera_id, enclosure_id=None, *, _hls=None):
    try:
        config, base = _media_context(request, enclosure_id, camera_id, _hls)
        body = _client(config, base).request(
            f"/camera/hls/{camera_id}/index.m3u8", trace=_hls,
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
@hls_response("segment")
def segment(request, camera_id, session_id, sequence, enclosure_id=None, *, _hls=None):
    try:
        config, base = _media_context(request, enclosure_id, camera_id, _hls)
        _, body = _client(config, base).request(
            f"/camera/hls/{camera_id}/{session_id}/{sequence}.ts",
            max_bytes=HLS_MAX_SEGMENT_BYTES, trace=_hls,
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
