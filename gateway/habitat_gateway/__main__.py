import argparse
import asyncio
import logging
import json
import os
import sqlite3
from pathlib import Path

import uvicorn

from .api import create_app
from .cloud import run_heartbeat
from .config import api_token, cloud_token, video_token, load_settings, ServerConfig
from . import __version__


def main():
    parser = argparse.ArgumentParser(description="HabitatOS Raspberry Pi store edge gateway")
    parser.add_argument("--config", default="config/simulation.toml")
    parser.add_argument("--host")
    parser.add_argument("--port")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--check-config", action="store_true", help="Validate settings without starting devices or writing a DB")
    parser.add_argument("--heartbeat-only", action="store_true",
                        help="Send SaaS heartbeats without device transport, sensor events, a persistent DB, or an API server")
    parser.add_argument("--check-connection", action="store_true",
                        help="Send one sensor-free heartbeat, validate the SaaS ACK, and exit")
    parser.add_argument("--confirm-cloud-continuity", type=Path, metavar="EVIDENCE_JSON",
                        help="Offline operator confirmation of server sequence evidence; stop the gateway first. Never renumbers events.")
    args = parser.parse_args()
    if args.confirm_cloud_continuity and (args.check_config or args.heartbeat_only or args.check_connection or args.host or args.port):
        parser.error("--confirm-cloud-continuity cannot be combined with other operating modes")
    if args.check_connection and (args.check_config or args.heartbeat_only):
        parser.error("--check-connection cannot be combined with --check-config or --heartbeat-only")
    heartbeat_mode = args.heartbeat_only or args.check_connection
    logging.basicConfig(level=logging.INFO)
    try:
        settings = load_settings(args.config)
        server = ServerConfig(host=args.host or settings.server.host,
                              port=int(args.port) if args.port is not None else settings.server.port)
    except ValueError:
        # Validation/TOML errors can include rejected passwords, URLs or token values.
        parser.exit(2, "error: invalid_gateway_configuration\n")
    except OSError:
        parser.exit(2, "error: gateway_configuration_unreadable\n")
    if args.confirm_cloud_continuity:
        if not settings.cloud.enabled or settings.database == ":memory:":
            parser.exit(2, "error: cloud_continuity_requires_persistent_cloud_database\n")
        from .store import Store
        store = None
        try:
            if args.confirm_cloud_continuity.stat().st_size > 8192:
                raise ValueError("invalid_cloud_continuity_evidence")
            evidence = json.loads(args.confirm_cloud_continuity.read_text(encoding="utf-8"))
            store = Store(settings.database, event_identity=(settings.site_id, settings.gateway_id))
            result = store.confirm_cloud_continuity(evidence)
        except RuntimeError:
            parser.exit(2, "error: cloud_continuity_database_in_use; stop the gateway first\n")
        except (ValueError, OSError, sqlite3.Error) as error:
            known = {"cloud_continuity_identity_mismatch", "cloud_server_history_regressed",
                     "cloud_continuity_migration_required", "cloud_pending_reconciliation_required", "cloud_sequence_regressed",
                     "cloud_verification_predates_conflict"}
            code = str(error) if str(error) in known else "invalid_cloud_continuity_evidence"
            parser.exit(2, f"error: {code}\n")
        finally:
            if store is not None:
                store.close()
        print(json.dumps({"continuity": result, "events_resequenced": 0, "events_deleted": 0}))
        return
    if heartbeat_mode and not settings.cloud.enabled:
        parser.exit(2, "error: heartbeat_only_requires_cloud\n")
    try:
        if not heartbeat_mode:
            api_token(settings)
            video_token(settings)
        sync_token = cloud_token(settings)
        settings.environment.token()
    except ValueError:
        parser.exit(2, "error: invalid_gateway_credentials; check API/cloud/video token environment variables\n")
    if not heartbeat_mode and settings.transport == "mqtt" and not os.environ.get(settings.mqtt.password_env):
        parser.exit(2, "error: invalid_gateway_credentials; check MQTT password environment variable\n")
    if not heartbeat_mode and server.host not in ("127.0.0.1", "::1", "localhost"):
        if not os.environ.get("HABITAT_API_TOKEN") or len(os.environ["HABITAT_API_TOKEN"]) < 32:
            parser.error("non-loopback binding requires HABITAT_API_TOKEN (32+ characters)")
    if args.check_config:
        print(json.dumps({"site_id": settings.site_id, "gateway_id": settings.gateway_id,
                          "version": __version__, "transport": settings.transport,
                          "cloud_enabled": settings.cloud.enabled, "valid": True,
                          **({"execution_mode": "heartbeat_only"} if args.heartbeat_only else {})}))
        return
    if heartbeat_mode:
        try:
            result = asyncio.run(run_heartbeat(settings, sync_token, once=args.check_connection))
        except KeyboardInterrupt:
            return
        if args.check_connection:
            print(json.dumps(result))
            if not result["connected"]:
                parser.exit(1)
        return
    uvicorn.run(create_app(settings), host=server.host, port=server.port, workers=1)


if __name__ == "__main__":
    main()
