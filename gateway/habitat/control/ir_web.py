"""Bounded web IR leases sharing the local CLI's sequence and cancellation files.

Only observers reconnect. Each ON owns a fresh, non-reconnecting Controller and
the existing process lock; a lost session always ends that request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import threading
import time
from typing import Mapping

from habitat.control.ir import (
    Config, ControlError, ControlLock, Controller, Monitor, SequenceStore,
    cancellation_token, make_client, request_local_off,
)


@dataclass(frozen=True)
class NodeConfig:
    cage_id: str
    node_id: str
    mqtt: Config
    environment: Mapping[str, str] = field(repr=False)


class RequestError(ControlError):
    def __init__(self, code: str, http_status: int):
        super().__init__(code)
        self.code, self.http_status = code, http_status


def state_path(config: Config) -> Path:
    """Same user, XDG root and filename as apps.worker.ir_control."""
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return root / "habitat-ir" / (hashlib.sha256(config.topic_base.encode()).hexdigest()[:24] + ".json")


def _error_code(error: Exception) -> str:
    # Never return exception text from network clients or credential loaders.
    message = str(error).lower() if isinstance(error, ControlError) else ""
    for fragment, code in (("another local", "control_busy"), ("locked", "outputs_locked"),
                           ("session changed", "session_changed"), ("hello expired", "hello_expired"),
                           ("disconnected", "mqtt_disconnected"), ("acknowledgment", "ack_failed"),
                           ("malformed", "invalid_hello"), ("rejected", "command_rejected"),
                           ("clock", "clock_unsynchronized"), ("sequence", "sequence_error"),
                           ("hello", "no_live_hello")):
        if fragment in message:
            return code
    return "controller_error"


def _disconnect(client):
    if client is not None:
        try:
            client.disconnect()
        finally:
            client.loop_stop()


class IRNode:
    """One configured cage; MQTT callbacks and HTTP commands never share leases."""
    def __init__(self, config: NodeConfig, max_on_seconds=900, *, client_factory=make_client,
                 controller_factory=Controller, monotonic=time.monotonic, reconnect_s=2.0):
        if type(max_on_seconds) is not int or not 1 <= max_on_seconds <= 900:
            raise ControlError("max_on_seconds must be an integer from 1 to 900")
        self.config, self.max_on_seconds = config, max_on_seconds
        self.path = state_path(config.mqtt)
        self.client_factory, self.controller_factory = client_factory, controller_factory
        self.clock, self.reconnect_s = monotonic, reconnect_s
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._cancel_on = threading.Event()
        self._observer = None
        self._monitor = None
        self._on_thread = self._off_thread = None
        self._deadline = None
        self._mode = None
        self._error = None
        self._observer_error = "no_live_hello"

    @staticmethod
    def _running(thread):
        return thread is not None and thread.is_alive()

    def start(self):
        with self._lock:
            if self._closed.is_set():
                raise ControlError("IR worker is closed")
            if not self._running(self._observer):
                self._observer = threading.Thread(target=self._observe, name=f"ir-observe-{self.config.cage_id}", daemon=True)
                self._observer.start()

    def _client(self, monitor):
        client = self.client_factory(self.config.mqtt, monitor, environ=self.config.environment)
        try:
            client.connect(self.config.mqtt.broker_host, self.config.mqtt.broker_port, keepalive=10)
            client.loop_start()
        except Exception:
            _disconnect(client)
            raise
        return client

    def _observe(self):
        while not self._closed.is_set():
            client = None
            monitor = Monitor(self.config.mqtt.topic_base, self.clock)
            with self._lock:
                self._monitor = monitor
            try:
                client = self._client(monitor)
                initial_deadline = self.clock() + 10.0
                while not self._closed.wait(0.1):
                    try:
                        monitor.checked()
                    except ControlError:
                        with monitor.lock:
                            if not monitor.fault and monitor.hello is None and self.clock() < initial_deadline:
                                continue
                        raise
                    with self._lock:
                        self._observer_error = None
            except Exception as error:
                with self._lock:
                    self._observer_error = _error_code(error)
                    if self._running(self._on_thread) and not self._cancel_on.is_set():
                        self._error = self._observer_error
                    self._cancel_on.set()
            finally:
                with self._lock:
                    if self._monitor is monitor:
                        self._monitor = None
                try:
                    _disconnect(client)
                except Exception:
                    pass
            self._closed.wait(self.reconnect_s)

    def _hello(self):
        if self._monitor is None:
            return None
        try:
            return self._monitor.checked()
        except ControlError as error:
            self._observer_error = _error_code(error)
            if self._running(self._on_thread) and not self._cancel_on.is_set():
                self._error = self._observer_error
            self._cancel_on.set()
            return None

    def status(self):
        with self._lock:
            hello = self._hello()
            active = self._running(self._on_thread) and self._mode is not None
            stopping = self._running(self._off_thread) or (active and self._cancel_on.is_set())
            if hello is None:
                status = "offline"
            elif stopping:
                status = "stopping"
            elif hello["outputs_locked"]:
                status = "locked"
            elif hello["gpio_requested_on"]:
                status = "on"
            elif active:
                status = "starting"
            elif self._error:
                status = "error"
            else:
                status = "off"
            remaining = max(0, math.ceil(self._deadline - self.clock())) if active and self._deadline and not stopping else 0
            if active and self._mode == "continuous":
                remaining = None
            return {"cage_id": self.config.cage_id, "configured": True, "status": status,
                    "online": hello is not None,
                    "outputs_locked": hello["outputs_locked"] if hello else None,
                    "gpio_requested_on": hello["gpio_requested_on"] if hello else None,
                    "actual_ir_on": None, "active": active, "mode": self._mode if active else None,
                    "remaining_s": remaining,
                    "max_on_seconds": self.max_on_seconds,
                    "error": self._error or (self._observer_error if hello is None else None)}

    def request(self, action: str, seconds=None):
        if action not in ("on", "off") or (seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 900 or (action == "on" and seconds > self.max_on_seconds))):
            raise RequestError("invalid_command", 422)
        with self._lock:
            if self._closed.is_set():
                raise RequestError("worker_stopping", 503)
            if action == "off":
                try:
                    # Cancel a local CLI lease BEFORE waiting for its process lock.
                    request_local_off(self.path)
                except OSError:
                    raise RequestError("state_unavailable", 503) from None
                self._cancel_on.set()
                if not self._running(self._off_thread):
                    self._error = None
                    self._off_thread = threading.Thread(target=self._turn_off, name=f"ir-off-{self.config.cage_id}", daemon=True)
                    self._off_thread.start()
                return self.status()
            if self._running(self._on_thread) or self._running(self._off_thread):
                raise RequestError("control_busy", 409)
            hello = self._hello()
            if hello is None:
                raise RequestError("no_live_hello", 503)
            if hello["outputs_locked"]:
                raise RequestError("outputs_locked", 409)
            # No network waits in the API. The existing nonblocking lock rejects
            # a simultaneous CLI owner before accepting a web ON.
            lock = ControlLock(self.path)
            try:
                lock.__enter__()
                initial_cancel = cancellation_token(self.path)
            except ControlError:
                raise RequestError("control_busy", 409) from None
            except OSError:
                lock.__exit__()
                raise RequestError("state_unavailable", 503) from None
            self._cancel_on.clear()
            self._error, self._deadline = None, None
            self._mode = "continuous" if seconds is None else "timed"
            self._on_thread = threading.Thread(target=self._turn_on,
                args=(seconds, hello["session_id"], initial_cancel, lock), name=f"ir-on-{self.config.cage_id}", daemon=True)
            try:
                self._on_thread.start()
            except Exception:
                self._mode = None
                lock.__exit__()
                raise
            return self.status()

    def _turn_on(self, seconds, expected_session, initial_cancel, lock):
        client = None
        cancelled = lambda: (self._closed.is_set() or self._cancel_on.is_set()
                              or cancellation_token(self.path) != initial_cancel)
        try:
            monitor = Monitor(self.config.mqtt.topic_base, self.clock)
            client = self._client(monitor)
            control = self.controller_factory(client, monitor, SequenceStore(self.path, self.config.mqtt.topic_base),
                monotonic=self.clock, cancelled=cancelled)
            hello = control.wait_hello()
            if hello["session_id"] != expected_session:
                raise ControlError("MCU session changed; automatic resume is disabled")
            with self._lock:
                self._deadline = None if seconds is None else self.clock() + seconds
            control.run("on", seconds)
        except Exception as error:
            try:
                external_cancel = cancellation_token(self.path) != initial_cancel
            except OSError:
                external_cancel = False
            with self._lock:
                if not self._cancel_on.is_set() and not self._closed.is_set() and not external_cancel:
                    self._error = _error_code(error)
        finally:
            try:
                _disconnect(client)
            except Exception:
                pass
            lock.__exit__()
            with self._lock:
                self._deadline = None
                self._mode = None

    def _turn_off(self):
        client = None
        try:
            with ControlLock(self.path, wait_s=5.0):
                monitor = Monitor(self.config.mqtt.topic_base, self.clock)
                client = self._client(monitor)
                control = self.controller_factory(client, monitor, SequenceStore(self.path, self.config.mqtt.topic_base),
                    monotonic=self.clock)
                control.run("off")
        except Exception as error:
            with self._lock:
                self._error = _error_code(error)
        finally:
            try:
                _disconnect(client)
            except Exception:
                pass

    def close(self):
        self._closed.set()
        self._cancel_on.set()
        with self._lock:
            if self._running(self._on_thread):
                try:
                    request_local_off(self.path)
                except OSError:
                    pass
            threads = (self._on_thread, self._off_thread, self._observer)
        deadline = time.monotonic() + 12.0
        for thread in threads:
            if thread is not None:
                thread.join(max(0, deadline - time.monotonic()))


class IRService:
    def __init__(self, site_id, gateway_id, nodes):
        self.site_id, self.gateway_id = site_id, gateway_id
        self.nodes = {node.config.cage_id: node for node in nodes}

    def health(self):
        return {"status": "ok", "site_id": self.site_id, "gateway_id": self.gateway_id,
                "configured_cages": sorted(self.nodes)}

    def node(self, cage_id):
        try:
            return self.nodes[cage_id]
        except KeyError:
            raise RequestError("cage_not_configured", 404) from None

    def start(self):
        for node in self.nodes.values():
            node.start()

    def close(self):
        for node in self.nodes.values():
            node.close()
