"""Bounded loopback adapter; browser APIs never receive MQTT or bridge secrets."""
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class IRBridgeError(Exception):
    def __init__(self, code="ir_bridge_unavailable", status=503):
        self.code, self.status = code, status
        super().__init__(code)


class IRState(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)
    cage_id: str
    configured: bool
    status: Literal["offline", "locked", "off", "starting", "on", "stopping", "error"]
    online: bool
    outputs_locked: bool | None
    gpio_requested_on: bool | None
    actual_ir_on: None
    active: bool
    mode: Literal["continuous", "timed"] | None = None
    remaining_s: float | None = Field(ge=0, le=900)
    max_on_seconds: int = Field(ge=1, le=900)
    error: str | None


ERRORS = {"control_busy", "outputs_locked", "session_changed", "hello_expired",
    "mqtt_disconnected", "ack_failed", "invalid_hello", "command_rejected",
    "clock_unsynchronized", "sequence_error", "no_live_hello", "controller_error",
    "worker_stopping", "state_unavailable", "invalid_command", "cage_not_configured"}


class IRWebClient:
    def __init__(self, endpoint, token, *, transport=None):
        self.client = httpx.Client(base_url=endpoint.rstrip("/"),
            headers={"Authorization": "Bearer " + token}, timeout=3,
            follow_redirects=False, trust_env=False, transport=transport,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4))

    def request(self, cage_id, command=None):
        try:
            response = (self.client.get(f"/v1/ir/{cage_id}") if command is None else
                        self.client.post(f"/v1/ir/{cage_id}", json=command))
            if len(response.content) > 8192:
                raise IRBridgeError()
            data = response.json()
            if response.status_code not in (200, 202):
                code = data.get("detail") if isinstance(data, dict) else None
                if isinstance(code, str) and code in ERRORS:
                    raise IRBridgeError(code, response.status_code if response.status_code in (404, 409, 422, 503) else 503)
                raise IRBridgeError()
            state = IRState.model_validate(data)
            if state.cage_id != cage_id or not state.configured:
                raise IRBridgeError()
            state.error = state.error if state.error in ERRORS else ("controller_error" if state.error else None)
            return state.model_dump()
        except (httpx.HTTPError, ValueError, ValidationError):
            raise IRBridgeError() from None

    def close(self):
        self.client.close()
