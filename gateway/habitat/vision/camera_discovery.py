"""Bounded LAN identity discovery; a verified binding authorizes one reader start.

Configured addresses and persisted bindings are candidates, never identities.
Only an exact registered /identity response permits a new reader. Discovery
never opens video streams or probes hosts already occupied by a camera reader.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, model_validator

from habitat.common.models import Model
from habitat.vision.cameras import CAMERA_LAN_NETWORKS, RTSP_H264_IDENTITY, RTSP_H264_PATH, RTSP_H264_PORT


MAX_IDENTITY_BYTES = 4096
MAX_CACHE_BYTES = 512 * 1024
_ALLOWED_NETWORKS = CAMERA_LAN_NETWORKS


class CameraDiscoveryConfig(Model):
    enabled: bool = False
    networks: list[str] = Field(default_factory=list, max_length=1024)
    port: StrictInt = Field(default=5000, ge=1, le=65535)
    interval_s: float = Field(default=60, ge=30, le=3600)
    timeout_s: float = Field(default=1.5, ge=0.1, le=5)
    max_workers: StrictInt = Field(default=16, ge=1, le=32)

    @model_validator(mode="after")
    def bounded_networks(self):
        parsed, count = [], 0
        for value in self.networks:
            try:
                if "/" not in value:
                    raise ValueError
                network = ipaddress.IPv4Network(value, strict=True)
            except ValueError:
                raise ValueError("camera discovery requires explicit IPv4 network CIDRs") from None
            if not any(network.subnet_of(allowed) for allowed in _ALLOWED_NETWORKS):
                raise ValueError("camera discovery permits only RFC1918 or loopback networks")
            if any(network.overlaps(previous) for previous in parsed):
                raise ValueError("camera discovery networks must not overlap")
            count += network.num_addresses - (2 if network.prefixlen < 31 else 0)
            if count > 1024:
                raise ValueError("camera discovery may probe at most 1024 hosts")
            parsed.append(network)
        if self.enabled and not parsed:
            raise ValueError("enabled camera discovery requires explicit networks")
        self.networks = [str(network) for network in parsed]
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate identity field")
        result[key] = value
    return result


def probe_identity(host, port, timeout_s):
    """GET only /identity at a literal IP, with a total socket lifetime limit.

    A per-read timeout alone permits an endless trickle of header/body bytes.
    The watchdog shuts down the socket at the total deadline, including headers.
    http.client does not use environment proxies or follow redirects.
    """
    try:
        address = ipaddress.IPv4Address(host)
    except (ValueError, TypeError):
        return None
    if not any(address in network for network in _ALLOWED_NETWORKS):
        return None
    deadline = time.monotonic() + timeout_s
    connection = None
    timer = None
    raw = None
    try:
        raw = socket.create_connection((str(address), port), timeout=timeout_s)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        def expire():
            try:
                raw.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        raw.settimeout(remaining)
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection = http.client.HTTPConnection(str(address), port, timeout=remaining)
        connection.sock = raw
        connection.request("GET", "/identity", headers={"Accept": "application/json",
                           "Accept-Encoding": "identity", "Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            return None
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            return None
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return None
        length = response.getheader("Content-Length")
        if length is not None and (not length.isascii() or not length.isdigit()
                                   or int(length) > MAX_IDENTITY_BYTES):
            return None
        body = response.read(MAX_IDENTITY_BYTES + 1)
        if len(body) > MAX_IDENTITY_BYTES or time.monotonic() >= deadline:
            return None
        result = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object)
        return result if isinstance(result, dict) else None
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, RecursionError):
        return None
    finally:
        if timer:
            timer.cancel()
        if connection:
            connection.close()
        elif raw:
            raw.close()


@dataclass(frozen=True)
class _Target:
    camera_id: str
    cage_id: str
    view: str
    seed: str | None
    cache_key: str
    generation: int
    source_type: str
    width: int
    height: int
    fps: int


class CameraDiscovery:
    def __init__(self, config, site_id, gateway_id, directory, *,
                 monotonic=time.monotonic, probe=None):
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value)
                   for value in (site_id, gateway_id)):
            raise ValueError("invalid discovery site or gateway identity")
        self.config, self.site_id, self.gateway_id = config, site_id, gateway_id
        self.path = Path(directory) / "camera-bindings.json"
        self.clock, self.probe = monotonic, probe or probe_identity
        self.hosts = tuple(str(host) for network in config.networks
                           for host in ipaddress.IPv4Network(network).hosts())
        self._host_set = frozenset(self.hosts)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._next_scan = 0.0
        self._generations, self._targets, self._ready, self._statuses = {}, {}, {}, {}
        self._idle, self._occupied = set(), set()
        self._cache = self._load_cache()

    def _source(self, value):
        try:
            parsed = urlsplit(value)
            host = str(ipaddress.IPv4Address(parsed.hostname or ""))
            legacy = (parsed.scheme == "http" and parsed.path == "/video_feed"
                      and parsed.port == self.config.port)
            h264 = (parsed.scheme == "rtsp" and parsed.path == RTSP_H264_PATH
                    and parsed.port == RTSP_H264_PORT)
            if (not (legacy or h264) or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                    or host not in self._host_set):
                return None
            return host, parsed.port
        except (ValueError, TypeError):
            return None

    def _load_cache(self):
        try:
            if self.path.is_symlink():
                return {}
            with self.path.open("rb") as stream:
                body = stream.read(MAX_CACHE_BYTES + 1)
            if len(body) > MAX_CACHE_BYTES:
                return {}
            data = json.loads(body, object_pairs_hook=_unique_object)
            if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                    or data["schema_version"] != 1 or not isinstance(data.get("bindings"), dict)):
                return {}
            return {key: value for key, value in data["bindings"].items()
                    if re.fullmatch(r"[0-9a-f]{64}", key) and isinstance(value, str)
                    and self._source(value)}
        except (OSError, ValueError, TypeError, RecursionError):
            return {}

    def _save_cache(self, cache):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".camera-bindings-", dir=self.path.parent)
            with os.fdopen(descriptor, "w") as stream:
                json.dump({"schema_version": 1, "bindings": cache}, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError:
            # Persistence improves discovery ordering; identity checks still gate starts.
            pass
        finally:
            if temporary:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def _target(self, camera):
        if not camera.is_network or camera.view not in ("top", "front"):
            return None
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value)
                   for value in (camera.id, camera.cage_id)):
            return None
        identity = (self.site_id, self.gateway_id, camera.cage_id, camera.id, camera.view, camera.url)
        if camera.source_type == "rtsp_h264":
            identity += (camera.source_type, camera.width, camera.height, camera.fps)
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return _Target(camera.id, camera.cage_id, camera.view, camera.url, key,
                       self._generations.get(camera.id, 0), camera.source_type,
                       camera.width, camera.height, camera.fps)

    @staticmethod
    def _occupied_sources(values):
        result = set()
        for value in values:
            try:
                if isinstance(value, str):
                    result.add((str(ipaddress.IPv4Address(value)), None))
                elif len(value) == 2:
                    result.add((str(ipaddress.IPv4Address(value[0])), int(value[1])))
            except (ValueError, TypeError):
                continue
        return result

    def _busy(self, host):
        # The identity and RTSP services share one physical camera, even though
        # their TCP ports differ. Never probe any occupied camera host.
        return any(address == host for address, _ in self._occupied)

    def poll(self, cameras, idle_ids, occupied_hosts):
        """Return one-shot bindings only for idle readers eligible to start now.

        A returned URL must be consumed in this cycle, not retained by the caller
        for future starts. All following starts require another identity round.
        """
        with self._lock:
            if not self.config.enabled or self._stop.is_set():
                return {}
            self._occupied = self._occupied_sources(occupied_hosts)
            targets = {}
            for camera in cameras:
                target = self._target(camera)
                if target is not None:
                    targets[camera.id] = target
            self._targets = targets
            self._idle = set(idle_ids) & targets.keys()
            result = {}
            for camera_id, (target, url) in list(self._ready.items()):
                self._ready.pop(camera_id)
                source = self._source(url)
                if (camera_id in self._idle and targets[camera_id] == target
                        and source and not self._busy(source[0]) and url not in result.values()):
                    result[camera_id] = url
            # Do not schedule any probes on a host returned for a reader start.
            # The next poll supplies the actual updated occupied reader set.
            if result:
                return result
            if self._thread is not None and self._thread.is_alive():
                return {}
            if not self._idle or self.clock() < self._next_scan:
                return {}
            selected = {key: targets[key] for key in self._idle}
            self._next_scan = self.clock() + self.config.interval_s
            for key in selected:
                self._statuses[key] = "scanning"
            self._thread = threading.Thread(target=self._scan, args=(selected,),
                                             name="camera-identity-discovery", daemon=True)
            self._thread.start()
            return {}

    def _fetch(self, host):
        with self._lock:
            if self._stop.is_set() or self._busy(host):
                return None
        try:
            return self.probe(host, self.config.port, self.config.timeout_s)
        except Exception:
            return None  # A peer or probe failure cannot stop the gateway cycle.

    def _match(self, data, targets):
        if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                or data.get("device_type") != "dfr1172_camera"
                or data.get("site_id") != self.site_id or data.get("gateway_id") != self.gateway_id
                ):
            return None
        camera_id = data.get("camera_id")
        if not isinstance(camera_id, str):
            return None
        target = targets.get(camera_id)
        if not target or data.get("cage_id") != target.cage_id or data.get("view") != target.view:
            return None
        if target.source_type == "http_mjpeg":
            return target if data["schema_version"] == 1 and data.get("stream_path") == "/video_feed" else None
        # Ignore peer-supplied addresses: only the probed LAN host can be bound.
        # Require the exact wire contract and registered dimensions/frame rate.
        for key, expected in RTSP_H264_IDENTITY.items():
            if type(data.get(key)) is not type(expected) or data[key] != expected:
                return None
        for key in ("width", "height", "fps"):
            if type(data.get(key)) is not int or data[key] != getattr(target, key):
                return None
        if (type(data.get("bitrate_bps")) is not int or not 256000 <= data["bitrate_bps"] <= 4000000
                or type(data.get("gop_frames")) is not int or not 1 <= data["gop_frames"] <= target.fps * 2):
            return None
        return target

    def _scan(self, targets):
        with self._lock:
            candidates = []
            for target in targets.values():
                for url in (self._cache.get(target.cache_key), target.seed):
                    source = self._source(url) if url else None
                    if source:
                        candidates.append(source[0])
            hosts = iter(dict.fromkeys([*candidates, *self.hosts]))
        matches = {key: set() for key in targets}
        executor = ThreadPoolExecutor(max_workers=self.config.max_workers, thread_name_prefix="camera-identity")
        pending = {}
        exhausted = False
        try:
            while not self._stop.is_set():
                while not exhausted and len(pending) < self.config.max_workers and not self._stop.is_set():
                    try:
                        host = next(hosts)
                    except StopIteration:
                        exhausted = True
                        break
                    with self._lock:
                        busy = self._busy(host)
                    if not busy:
                        pending[executor.submit(self._fetch, host)] = host
                if not pending:
                    break
                completed, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in completed:
                    host = pending.pop(future)
                    target = self._match(future.result(), targets)
                    if target:
                        matches[target.camera_id].add(host)
            if self._stop.is_set():
                return
            with self._lock:
                # A full round is necessary to reject duplicate device identities.
                valid_keys = {value.cache_key for value in self._targets.values()}
                self._cache = {key: value for key, value in self._cache.items() if key in valid_keys}
                for camera_id, target in targets.items():
                    if self._targets.get(camera_id) != target or camera_id not in self._idle:
                        continue
                    found = matches[camera_id]
                    if len(found) != 1:
                        self._cache.pop(target.cache_key, None)
                        self._statuses[camera_id] = "identity_ambiguous" if found else "identity_not_found"
                        continue
                    host = next(iter(found))
                    if self._busy(host):
                        continue
                    url = (f"rtsp://{host}:{RTSP_H264_PORT}{RTSP_H264_PATH}"
                           if target.source_type == "rtsp_h264"
                           else f"http://{host}:{self.config.port}/video_feed")
                    self._cache[target.cache_key] = url
                    self._ready[camera_id] = (target, url)
                    self._statuses[camera_id] = "identity_verified"
                cache = dict(self._cache)
            if not self._stop.is_set():
                self._save_cache(cache)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def invalidate(self, camera_id):
        with self._lock:
            self._generations[camera_id] = self._generations.get(camera_id, 0) + 1
            self._ready.pop(camera_id, None)
            self._targets.pop(camera_id, None)
            self._statuses[camera_id] = "waiting_scan"

    def status(self, camera_id):
        with self._lock:
            return "disabled" if not self.config.enabled else self._statuses.get(camera_id, "waiting_scan")

    def close(self):
        self._stop.set()
        with self._lock:
            self._ready.clear()
            thread = self._thread
        if thread:
            thread.join(timeout=self.config.timeout_s + 0.5)
