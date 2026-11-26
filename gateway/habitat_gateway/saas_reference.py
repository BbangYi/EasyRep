"""Local reference receiver for the SaaS implementer; independent of the Pi control API."""
import argparse
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import tomllib

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, model_validator
import uvicorn

from .config import ServerConfig
from .models import Identifier, Model, utcnow
from .sync_contract import SYNC_PATH, SyncAck, SyncRequest
from habitat.saas.video_contract import VIDEO_PATH, MAX_VIDEO_BODY
from habitat.saas.video_receiver import mount_video_receiver
from habitat.saas.air_contract import AIR_PATH, MAX_AIR_BODY, AirRegistrationBinding
from habitat.saas.air_receiver import mount_air_receiver


class Registration(Model):
    site_id: Identifier
    gateway_id: Identifier
    cage_ids: list[Identifier] = Field(min_length=1)
    token_env: str
    allow_simulation: bool = False
    camera_cages: dict[Identifier, Identifier] = Field(default_factory=dict, max_length=16)
    air_cages: dict[Identifier, AirRegistrationBinding] = Field(default_factory=dict, max_length=256)

    @model_validator(mode="after")
    def camera_scope(self):
        if not set(self.camera_cages.values()) <= set(self.cage_ids):
            raise ValueError("camera mapping references an unregistered cage")
        if not self.air_cages.keys() <= set(self.cage_ids):
            raise ValueError("air mapping references an unregistered cage")
        if len({item.enclosure_id for item in self.air_cages.values()}) != len(self.air_cages):
            raise ValueError("duplicate air enclosure mapping")
        return self


class ErrorDetail(Model):
    code: str
    message: str


class ErrorResponse(Model):
    detail: ErrorDetail


def failure(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message},
                         headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


class BodyLimit:
    """Bound JSON bodies before FastAPI parses them, including chunked requests."""
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in (SYNC_PATH, VIDEO_PATH, AIR_PATH):
            return await self.app(scope, receive, send)
        limit = {VIDEO_PATH: MAX_VIDEO_BODY, AIR_PATH: MAX_AIR_BODY}.get(scope["path"], self.limit)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                response = JSONResponse(status_code=413, content={"detail": {
                    "code": "body_too_large", "message": f"Maximum request size is {limit} bytes",
                }})
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def create_receiver(database, registrations, *, environ=None, body_limit=8 * 1024 * 1024, viewers=()):
    registrations = tuple(registrations)
    environment = os.environ if environ is None else environ
    credentials = {}
    owners = set()
    identities = set()
    air_enclosures = set()
    for entry in registrations:
        token = environment.get(entry.token_env, "")
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError(f"{entry.token_env} requires 32+ ASCII characters without whitespace")
        digest = hashlib.sha256(token.encode()).hexdigest()
        identity = (entry.site_id, entry.gateway_id)
        cages = {(entry.site_id, c) for c in entry.cage_ids}
        if digest in credentials or identity in identities or owners & cages:
            raise ValueError("duplicate token, gateway or cage ownership in registry")
        mapped_enclosures = {binding.enclosure_id for binding in entry.air_cages.values()}
        if air_enclosures & mapped_enclosures:
            raise ValueError("duplicate air enclosure ownership in registry")
        air_enclosures.update(mapped_enclosures)
        credentials[digest] = entry
        identities.add(identity)
        owners.update(cages)
    viewer_credentials = {}
    for entry in viewers:
        token = environment.get(entry.token_env, "")
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("invalid viewer credentials")
        digest = hashlib.sha256(token.encode()).hexdigest()
        if digest in credentials or digest in viewer_credentials:
            raise ValueError("viewer and Pi credentials must be distinct")
        viewer_credentials[digest] = entry
    if str(database) != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS edge_events (
            site_id TEXT NOT NULL, gateway_id TEXT NOT NULL, event_id TEXT NOT NULL,
            event_sequence INTEGER NOT NULL, cage_id TEXT NOT NULL,
            kind TEXT NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(site_id, gateway_id, event_id),
            UNIQUE(site_id, gateway_id, event_sequence)
        );
        CREATE TABLE IF NOT EXISTS edge_gateways (
            site_id TEXT NOT NULL, gateway_id TEXT NOT NULL,
            sent_at TEXT NOT NULL, last_received_at TEXT NOT NULL, body TEXT NOT NULL,
            PRIMARY KEY(site_id, gateway_id)
        );
    """)
    lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            db.close()

    app = FastAPI(
        title="HabitatOS Pi → SaaS ingestion contract", version="1.0.0", lifespan=lifespan,
        description="Reference implementation. The production URL requires deployment by the SaaS operator.",
        servers=[{"url": "http://127.0.0.1:9000", "description": "Local reference receiver"},
                 {"url": "https://easyrep.kro.kr", "description": "SaaS deployment target; this reference does not verify production deployment"}],
    )
    app.add_middleware(BodyLimit, limit=body_limit)
    app.state.db = db
    security = HTTPBearer(auto_error=False, scheme_name="PiBearerToken")

    def authorize(auth: HTTPAuthorizationCredentials | None = Depends(security)):
        digest = hashlib.sha256(auth.credentials.encode()).hexdigest() if auth else ""
        entry = credentials.get(digest)
        if entry is None:
            raise failure(401, "invalid_token", "A registered Pi bearer token is required")
        return entry

    viewer_security = HTTPBearer(auto_error=False, scheme_name="DevelopmentViewerToken")

    def authorize_viewer(auth: HTTPAuthorizationCredentials | None = Depends(viewer_security)):
        digest = hashlib.sha256(auth.credentials.encode()).hexdigest() if auth else ""
        entry = viewer_credentials.get(digest)
        if entry is None:
            raise failure(401, "invalid_viewer", "A scoped viewer credential is required")
        return entry

    mount_video_receiver(app, db, lock, authorize, authorize_viewer)
    mount_air_receiver(app, db, lock, authorize, authorize_viewer, registrations=registrations)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse(status_code=503, content={"detail": {
            "code": "storage_unavailable", "message": "Batch was not acknowledged; retry with the same event IDs",
        }})

    @app.get("/v1/edge/health", operation_id="edgeIngestHealth", tags=["Operations"])
    def health():
        with lock:
            db.execute("SELECT 1")
        return {"status": "ok"}

    @app.post(SYNC_PATH, response_model=SyncAck, operation_id="syncGatewayEvents", tags=["Pi ingestion"],
              summary="Store sensor/command events and acknowledge durable event IDs",
              description="All-or-nothing transaction. Retries with identical events return the same ACK. "
                          "Empty events are valid heartbeats. Maximum JSON body: 8 MiB.",
              responses={code: {"model": ErrorResponse, "description": description} for code, description in {
                  401: "Missing or invalid Pi token", 403: "Gateway/cage scope denied or simulation disabled",
                  409: "Event ID or sequence reused with different content", 413: "JSON body exceeds 8 MiB",
                  503: "Persistence failed; no ACK",
              }.items()})
    def sync(payload: SyncRequest, registration: Registration = Depends(authorize)):
        identity = (payload.site_id, payload.gateway_id)
        if identity != (registration.site_id, registration.gateway_id):
            raise failure(403, "gateway_scope_denied", "Token does not own this site/gateway")
        cages = {c.configuration.id for c in payload.gateway.cages} | {e.cage_id for e in payload.events}
        if not cages <= set(registration.cage_ids):
            raise failure(403, "cage_scope_denied", "Token does not own every submitted cage")
        simulation = payload.gateway.transport == "simulated" or any(
            c.state.telemetry and c.state.telemetry.data_source == "simulation" for c in payload.gateway.cages
        ) or any(e.kind == "telemetry.recorded" and e.payload.data_source == "simulation" for e in payload.events)
        if simulation and not registration.allow_simulation:
            raise failure(403, "simulation_disabled", "Simulation is not allowed for this registration")
        with lock, db:
            for event in payload.events:
                # Preserve legacy event bytes for retry comparison: adding optional R15
                # fields must not add null defaults to already accepted command events.
                absent = ({"r15", "execution_status", "actual_state"} - event.payload.model_fields_set
                          if event.kind == "command.updated" else set())
                body = json.dumps(event.model_dump(mode="json", exclude={"payload": absent}),
                                  sort_keys=True, separators=(",", ":"))
                previous = db.execute(
                    "SELECT event_id, body FROM edge_events WHERE site_id=? AND gateway_id=? "
                    "AND (event_id=? OR event_sequence=?)", (*identity, str(event.event_id), event.event_sequence),
                ).fetchall()
                if previous:
                    if len(previous) != 1 or previous[0]["event_id"] != str(event.event_id) or previous[0]["body"] != body:
                        raise failure(409, "event_conflict", "An event ID or sequence has different stored content")
                    continue
                db.execute("INSERT INTO edge_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (*identity, str(event.event_id), event.event_sequence, event.cage_id, event.kind, body))
            sent_at = payload.sent_at.isoformat()
            snapshot = payload.gateway.model_dump_json()
            db.execute("""INSERT INTO edge_gateways VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(site_id, gateway_id) DO UPDATE SET
                last_received_at=excluded.last_received_at,
                sent_at=MAX(edge_gateways.sent_at, excluded.sent_at),
                body=CASE WHEN excluded.sent_at >= edge_gateways.sent_at THEN excluded.body ELSE edge_gateways.body END
            """, (*identity, sent_at, utcnow().isoformat(), snapshot))
        return SyncAck(schema_version=1, site_id=payload.site_id, gateway_id=payload.gateway_id,
                       accepted_event_ids=[e.event_id for e in payload.events])

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/saas-reference.toml")
    parser.add_argument("--port", default="9000")
    args = parser.parse_args()
    try:
        with open(args.config, "rb") as stream:
            config = tomllib.load(stream)
        registrations = [Registration.model_validate(entry) for entry in config["gateways"]]
        database = config["database"]
        if not registrations or not isinstance(database, str) or not database or "\x00" in database:
            raise ValueError("registered gateways and a database path are required")
        server = ServerConfig(port=int(args.port))
    except (ValueError, KeyError, TypeError):
        # TOML and validation errors can include rejected secrets or environment names.
        parser.exit(2, "error: invalid_reference_configuration\n")
    except OSError:
        parser.exit(2, "error: reference_configuration_unreadable\n")
    try:
        viewers = [Registration.model_validate(entry) for entry in config.get("viewers", [])]
        app = create_receiver(database, registrations, viewers=viewers)
    except ValueError:
        parser.exit(2, "error: invalid_reference_credentials; check registered token environment variables\n")
    uvicorn.run(app, host=server.host, port=server.port, workers=1)


if __name__ == "__main__":
    main()
