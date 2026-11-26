"""Run explicit, time-limited IR commands using the configured cage's MQTT lease."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

from habitat.control.ir import (
    ControlError, ControlLock, Controller, Monitor, SequenceStore,
    cancellation_token, load_config, make_client, request_local_off,
)


def credential_environment(config, path=None, environ=None):
    """Load only the two configured credential names, without evaluating shell text."""
    environment = dict(os.environ if environ is None else environ)
    if path is None:
        return environment
    try:
        with Path(path).open(encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ControlError("Credential file must be private (owner permissions only)")
            contents = stream.read(16385)
    except (OSError, UnicodeError):
        raise ControlError("Cannot read private credential file") from None
    if len(contents) > 16384:
        raise ControlError("Credential file is too large")
    expected = {config.username_env, config.password_env}
    values = {}
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or name not in expected or name in values:
            raise ControlError("Credential file must contain each configured credential name once")
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ControlError("Invalid credential file quoting")
            value = value[1:-1]
        if not value or "\x00" in value:
            raise ControlError("Credential file contains an empty or invalid value")
        values[name] = value
    if set(values) != expected:
        raise ControlError("Credential file is missing a configured credential name")
    environment.update(values)
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, help="Private credential file; literal KEY=value, never shell evaluated")
    parser.add_argument("--action", choices=("status", "on", "off"), default="status")
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args(argv)
    client = None
    try:
        config = load_config(args.config)
        environment = credential_environment(config, args.env_file)
        if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 43200:
            raise ControlError("--seconds must be between 1 and 43200")
        state_root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        state_path = state_root / "habitat-ir" / (hashlib.sha256(config.topic_base.encode()).hexdigest()[:24] + ".json")
        if args.action == "off":
            request_local_off(state_path)
        with ControlLock(state_path, wait_s=5.0 if args.action == "off" else 0.0) if args.action != "status" else nullcontext():
            initial_cancel = cancellation_token(state_path) if args.action == "on" else None
            monitor = Monitor(config.topic_base)
            client = make_client(config, monitor, environ=environment)
            control = Controller(client, monitor, SequenceStore(state_path, config.topic_base),
                                 cancelled=(lambda: cancellation_token(state_path) != initial_cancel) if args.action == "on" else (lambda: False))
            client.connect(config.broker_host, config.broker_port, keepalive=10)
            client.loop_start()
            try:
                print(json.dumps(control.run(args.action, args.seconds), ensure_ascii=False))
            finally:
                client.disconnect(); client.loop_stop(); client = None
        return 0
    except KeyboardInterrupt:
        print("Interrupted; OFF attempted, no automatic resume.", file=sys.stderr)
        return 130
    except (ControlError, OSError, ValueError, RuntimeError) as error:
        print(f"IR control stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.disconnect(); client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
