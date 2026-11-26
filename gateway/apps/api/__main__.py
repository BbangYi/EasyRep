"""Configuration, secrets and service lifecycle entrypoint."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys


def main():
    parser = argparse.ArgumentParser(description="HabitatOS GPU service")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--init-secrets", type=Path)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--export-openapi", type=Path)
    args = parser.parse_args()
    try:
        if args.init_secrets:
            target = args.init_secrets.resolve()
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("HABITAT_GPU_TOKEN=" + secrets.token_urlsafe(48) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps({"token_configured": True, "token_value_included": False}))
            return
        if args.env_file:
            for line in args.env_file.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if not re.fullmatch(r"HABITAT_[A-Z0-9_]+", key):
                    raise ValueError("invalid_secret_name")
                os.environ[key] = value
        if not args.config:
            parser.error("--config is required")
        from habitat.gpu.config import load_config
        config = load_config(args.config)
        if args.check_config:
            print(json.dumps({"valid": True, "contract_version": "1.0.0", "credentials": len(config.credentials)}))
            return
        from habitat.gpu.api import create_app
        app = create_app(config)
        if args.export_openapi:
            args.export_openapi.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
            return
    except Exception:
        print("invalid_gpu_configuration_or_credentials", file=sys.stderr)
        raise SystemExit(2) from None
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port, workers=1, access_log=False,
                timeout_graceful_shutdown=35)


if __name__ == "__main__":
    main()
