import argparse
from datetime import datetime
import json
import logging
import signal
import sqlite3
import threading
import time
from uuid import UUID, uuid4

from pydantic import ValidationError

from habitat.compute.config import load_compute_config
from habitat.compute.contracts import CONTRACT_VERSION
from habitat.compute.errors import ComputeFailure
from habitat.compute.http_client import HTTPComputeClient
from habitat.compute.environment import EnvironmentHealth, predict
from habitat.compute.livescene import LiveSceneHealth, render
from habitat.compute.service import ComputeWorker
from habitat.persistence.compute import ComputeRepository
from habitat_gateway.config import load_settings


def summary(task):
    return {k: task[k] for k in ("job_id", "capture_id", "state", "attempts", "next_attempt_at", "error")}


def main():
    parser = argparse.ArgumentParser(description="HabitatOS Pi Compute client (separate from local control)")
    parser.add_argument("--config", default="configs/examples/compute.toml")
    parser.add_argument("--gateway-config", default="config/simulation.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config", help="Validate without opening a DB or network connection")
    enqueue = commands.add_parser("enqueue", help="Stage existing multi-view JPEG/PNG photos without networking")
    enqueue.add_argument("--cage-id", required=True)
    enqueue.add_argument("--folder", required=True)
    enqueue.add_argument("--captured-at", required=True, type=datetime.fromisoformat,
                         help="Actual capture time with timezone, e.g. 2026-09-19T09:00:00+09:00")
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("job_id", type=UUID)
    retry = commands.add_parser("retry", help="Retry a blocked/transient client task with the same IDs")
    retry.add_argument("job_id", type=UUID)
    commands.add_parser("health", help="Query GPU API/CUDA readiness")
    commands.add_parser("livescene-health", help="List registered LiveScene models and actual capabilities")
    view = commands.add_parser("livescene-render", help="Request one GPU-rendered PNG; does not train or operate hardware")
    view.add_argument("--cage-id", required=True)
    view.add_argument("--model-id", required=True)
    view.add_argument("--camera-index", type=int, default=0)
    view.add_argument("--state", type=float)
    view.add_argument("--max-width", type=int, default=320)
    view.add_argument("--output", required=True)
    commands.add_parser("environment-health", help="Query the separate environment model readiness")
    probe = commands.add_parser("environment-probe", help="Synthetic round trip from this Pi; never records telemetry or runs actuators")
    probe.add_argument("--cage-id", required=True)
    work = commands.add_parser("work")
    work.add_argument("--once", action="store_true", help="Advance each due job once, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # HTTP libraries can log URLs. Keep normal operation to controlled diagnostic codes.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    repository = client = None
    try:
        gateway = load_settings(args.gateway_config)
        config = gateway.environment if args.command.startswith("environment-") else load_compute_config(args.config)
        if args.command.startswith('livescene-'):
            if not config.enabled:
                raise ComputeFailure('compute_disabled')
            client = HTTPComputeClient(config, config.token())
            if args.command == 'livescene-health':
                print(client.json('GET', '/v1/livescene/health', LiveSceneHealth).model_dump_json(indent=2))
            else:
                if args.cage_id not in {c.id for c in gateway.cages}:
                    raise ComputeFailure('cage_not_configured')
                request = {'schema_version': 1, 'request_id': str(uuid4()),
                    'site_id': gateway.site_id, 'gateway_id': gateway.gateway_id, 'cage_id': args.cage_id,
                    'model_id': args.model_id, 'camera_index': args.camera_index,
                    'state': args.state, 'max_width': args.max_width}
                print(json.dumps(render(client, request, args.output), allow_nan=False))
            return
        if args.command.startswith("environment-"):
            if not config.enabled:
                raise ComputeFailure("environment_disabled")
            client = HTTPComputeClient(config, config.token())
            if args.command == "environment-health":
                print(client.json("GET", "/v1/environment/health", EnvironmentHealth).model_dump_json(indent=2))
            else:
                target = next((t for t in config.targets if t.cage_id == args.cage_id), None)
                if target is None:
                    raise ComputeFailure("cage_not_configured")
                now = time.time()
                request = {"schema_version": 1, "mode": "simulation", "request_id": str(uuid4()),
                    "site_id": gateway.site_id, "gateway_id": gateway.gateway_id, "cage_id": target.cage_id,
                    "sample_times": [now-(29-i)*60 for i in range(30)],
                    "history": [[25., sum(target.humidity_band)/2, 26., 24., 0.] for _ in range(30)],
                    "humidity_band": target.humidity_band, "temperature_band": target.temperature_band,
                    "water_ok": True, "leak": False}
                result = predict(client, request)
                print(json.dumps({"status": "PASS", "client": "Raspberry Pi", "synthetic_input": True,
                    "saas_data_sent": False, "hardware_operated": False,
                    "round_trip_s": round(time.time()-now, 3), "result": result.model_dump(mode="json")}))
            return
        if args.command == "check-config":
            config.token()
            print(json.dumps({"valid": True, "enabled": config.enabled,
                "site_id": gateway.site_id, "gateway_id": gateway.gateway_id,
                "cage_ids": [c.id for c in gateway.cages], "contract_version": CONTRACT_VERSION}))
            return
        if args.command in ("health", "work") and not config.enabled:
            print(json.dumps({"enabled": False, "status": "disabled"}))
            return
        if args.command in ("health", "work"):
            client = HTTPComputeClient(config, config.token())
        if args.command == "health":
            print(client.health().model_dump_json(indent=2))
            return
        repository = ComputeRepository(config.storage_dir, gateway.site_id, gateway.gateway_id,
                                       max_storage_bytes=config.max_storage_bytes, worker=args.command == "work")
        if args.command == "enqueue":
            cage = next((c for c in gateway.cages if c.id == args.cage_id), None)
            if cage is None:
                raise ComputeFailure("cage_not_configured")
            print(json.dumps(summary(repository.enqueue(args.folder, cage, args.captured_at))))
        elif args.command == "list":
            print(json.dumps([summary(t) for t in repository.tasks()]))
        elif args.command == "show":
            print(json.dumps(repository.task(args.job_id), indent=2))
        elif args.command == "retry":
            repository.retry(args.job_id)
            print(json.dumps(summary(repository.task(args.job_id))))
        else:
            worker = ComputeWorker(repository, client, config, gateway.cages)
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            while not stop.is_set():
                results = worker.cycle()
                if results or args.once:
                    print(json.dumps([summary(t) for t in results]), flush=True)
                if args.once:
                    break
                stop.wait(config.poll_interval_s)
    except ComputeFailure as error:
        print(json.dumps({"error": error.code, "retryable": error.retryable}))
        raise SystemExit(1) from None
    except (ValidationError, ValueError):
        print(json.dumps({"error": "invalid_compute_configuration_or_input"}))
        raise SystemExit(1) from None
    except (OSError, sqlite3.Error):
        print(json.dumps({"error": "compute_local_io_error"}))
        raise SystemExit(1) from None
    finally:
        if client:
            client.close()
        if repository:
            repository.close()
