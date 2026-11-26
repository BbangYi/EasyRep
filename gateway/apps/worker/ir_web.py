"""Authenticated loopback bridge for the gateway's camera IR controls."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import re
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from apps.worker.ir_control import credential_environment
from habitat.control.ir import ControlError, credentials, load_config, unique_object
from habitat.control.ir_web import IRNode, IRService, NodeConfig, RequestError

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def load_service(path, *, environ=None):
    environment = os.environ if environ is None else environ
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, ValueError):
        raise ControlError("Cannot read IR web config") from None
    if not isinstance(data, dict) or set(data) != {"site_id", "gateway_id", "max_on_seconds", "nodes"}:
        raise ControlError("IR web config requires site_id, gateway_id, max_on_seconds and nodes")
    if any(not isinstance(data[key], str) or not IDENTIFIER.fullmatch(data[key]) for key in ("site_id", "gateway_id")):
        raise ControlError("Invalid site or gateway identifier")
    maximum = data["max_on_seconds"]
    if type(maximum) is not int or not 1 <= maximum <= 900:
        raise ControlError("max_on_seconds must be an integer from 1 to 900")
    if not isinstance(data["nodes"], list) or not 1 <= len(data["nodes"]) <= 256:
        raise ControlError("IR web config requires between 1 and 256 nodes")
    nodes, cages, devices = [], set(), set()
    for item in data["nodes"]:
        if not isinstance(item, dict) or set(item) != {"cage_id", "node_id", "config_path", "env_path"}:
            raise ControlError("Invalid IR web node fields")
        if any(not isinstance(item[key], str) or not IDENTIFIER.fullmatch(item[key]) for key in ("cage_id", "node_id")):
            raise ControlError("Invalid cage or node identifier")
        if item["cage_id"] in cages or item["node_id"] in devices:
            raise ControlError("Duplicate IR cage or node")
        if any(not isinstance(item[key], str) or not Path(item[key]).is_absolute() for key in ("config_path", "env_path")):
            raise ControlError("Private IR configuration paths must be absolute")
        config = load_config(item["config_path"])
        expected = f"habitat/v1/{data['site_id']}/cages/{item['cage_id']}/nodes/{item['node_id']}"
        if config.topic_base != expected:
            raise ControlError("IR node topic identity does not match web configuration")
        private_environment = credential_environment(config, item["env_path"], environment)
        credentials(config, private_environment)
        nodes.append(IRNode(NodeConfig(item["cage_id"], item["node_id"], config, private_environment), maximum))
        cages.add(item["cage_id"])
        devices.add(item["node_id"])
    return IRService(data["site_id"], data["gateway_id"], nodes)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["on", "off"]
    seconds: StrictInt | None = Field(default=None, ge=1, le=900)


def bridge_token(environ=None):
    token = (os.environ if environ is None else environ).get("HABITAT_IR_BRIDGE_TOKEN", "")
    if not isinstance(token, str) or len(token) < 32 or any(character.isspace() for character in token):
        raise ControlError("HABITAT_IR_BRIDGE_TOKEN requires at least 32 non-whitespace characters")
    return token


def create_app(service: IRService, token: str, *, run_worker=True):
    token = bridge_token({"HABITAT_IR_BRIDGE_TOKEN": token})

    @asynccontextmanager
    async def lifespan(app):
        if run_worker:
            service.start()
        try:
            yield
        finally:
            if run_worker:
                await asyncio.to_thread(service.close)

    app = FastAPI(title="Habitat IR loopback bridge", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def authorized(authorization: str | None = Header(default=None)):
        if authorization is None or not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return service.health()

    @app.get("/v1/ir/{cage_id}", dependencies=[Depends(authorized)])
    def status(cage_id: str):
        try:
            return service.node(cage_id).status()
        except RequestError as error:
            raise HTTPException(error.http_status, error.code) from None

    @app.post("/v1/ir/{cage_id}", status_code=202, dependencies=[Depends(authorized)])
    def command(cage_id: str, body: Command, response: Response):
        try:
            return service.node(cage_id).request(body.action, body.seconds)
        except RequestError as error:
            raise HTTPException(error.http_status, error.code) from None

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ControlError("Invalid loopback port")
        token = bridge_token()
        service = load_service(args.config)
        if args.check_config:
            print(json.dumps(service.health()))
            return 0
        import uvicorn
        uvicorn.run(create_app(service, token), host="127.0.0.1", port=args.port, access_log=False, workers=1)
        return 0
    except ControlError as error:
        parser.exit(2, f"IR web configuration error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
