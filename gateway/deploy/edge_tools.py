"""Local operator commands. Read protected credentials in place, never display them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.request

from pydantic import ValidationError

try:
    from .install import read_environment, write_atomic
    from .provision import add_cage, array_table
except ImportError:  # Standalone copy inside a release bundle.
    from install import read_environment, write_atomic
    from provision import add_cage, array_table
from habitat_gateway.config import Settings, load_settings
from habitat.vision.cameras import CameraConfig, discover


def _camera_sections(text):
    """Locate camera tables without absorbing subsequent unrelated TOML tables."""
    headers = list(re.finditer(r"(?m)^[ \t]*(\[\[?)([^\]\r\n]+)\]\]?[ \t]*(?:#[^\r\n]*)?(?:\r?\n|$)", text))
    for index, header in enumerate(headers):
        if header[1] == "[[" and header[2].strip() in ("cameras", '"cameras"', "'cameras'"):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            section = text[header.start():end]
            yield header.start(), end, tomllib.loads(section)["cameras"][0]


def _pair_id(cage_id, view):
    suffix = "-" + view.upper()
    if len(cage_id + suffix) <= 64:
        return cage_id + suffix
    return cage_id[:45] + "-" + hashlib.sha256(cage_id.encode()).hexdigest()[:10] + suffix


def bind_camera_pair(original, cage_id, top, front):
    """Render only: keep legacy cameras and every unrelated setting unchanged."""
    raw = tomllib.loads(original)
    config = Settings.model_validate(raw)
    if cage_id not in {cage.id for cage in config.cages}:
        raise ValueError("unknown cage ID")
    if top == front:
        raise ValueError("TOP and FRONT must have different camera URLs")
    replacements = {}
    for view, url in (("top", top), ("front", front)):
        current = next((camera for camera in config.cameras
                        if camera.cage_id == cage_id and camera.view == view), None)
        camera_id = current.id if current is not None else _pair_id(cage_id, view)
        if current is None and any(camera.id == camera_id for camera in config.cameras):
            raise ValueError("generated camera ID conflicts with an existing camera")
        values = dict(next(camera for camera in raw["cameras"] if camera["id"] == current.id)) if current is not None else {
            "id": camera_id, "cage_id": cage_id}
        values.pop("device", None)
        values.update(source_type="http_mjpeg", url=url, view=view, live_stream=True)
        CameraConfig.model_validate(values)
        replacements[camera_id] = values
    parts = []
    cursor = 0
    updated = set()
    for start, end, values in _camera_sections(original):
        parts.append(original[cursor:start])
        if values["id"] in replacements:
            ending = re.search(r"(?:\r?\n[ \t]*)+$", original[start:end])
            parts.append(array_table("cameras", replacements[values["id"]]).rstrip("\n")
                         + (ending[0] if ending is not None else "\n"))
            updated.add(values["id"])
        else:
            parts.append(original[start:end])
        cursor = end
    parts.append(original[cursor:])
    for camera_id, values in replacements.items():
        if camera_id not in updated:
            if any(camera.id == camera_id for camera in config.cameras):
                raise ValueError("unsupported camera table formatting")
            parts.append("\n" + array_table("cameras", values))
    proposed = "".join(parts)
    Settings.model_validate(tomllib.loads(proposed))
    return proposed, list(replacements)


def apply_config(config_path, original, proposed):
    """Apply a validated config with the service's existing access policy and rollback."""
    Settings.model_validate(tomllib.loads(proposed))
    if config_path.read_text() != original:
        raise ValueError("configuration changed during preparation; retry with the current file")
    if proposed == original:
        return False
    previous = config_path.stat()
    mode = stat.S_IMODE(previous.st_mode)
    fd, name = tempfile.mkstemp(prefix=".gateway-camera-", suffix=".toml", dir=config_path.parent)
    temporary = Path(name)
    changed = False
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
            stream.write(proposed)
            stream.flush()
            os.fsync(stream.fileno())
        load_settings(temporary)
        write_atomic(config_path.with_suffix(".before-camera.toml"), original, 0o600)
        temporary.replace(config_path)
        changed = True
        subprocess.run(["systemctl", "restart", "habitat-gateway"], check=True)
    except Exception:
        if changed:
            write_atomic(config_path, original, mode)
            os.chown(config_path, previous.st_uid, previous.st_gid)
            subprocess.run(["systemctl", "restart", "habitat-gateway"], check=False)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _save_candidate(path, proposed):
    # Exclusive creation preserves an earlier prepared deployment.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(proposed)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _pair_arguments(parser):
    parser.add_argument("cage_id")
    parser.add_argument("--top", required=True, help="TOP camera HTTP MJPEG URL")
    parser.add_argument("--front", required=True, help="FRONT camera HTTP MJPEG URL")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output", type=Path, help="Write a new validated candidate without changing the running service")
    mode.add_argument("--apply", action="store_true", help="Apply configuration and restart the gateway with rollback on failure")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default="/etc/habitat-gateway/gateway.toml")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("cameras")
    sub.add_parser("gpu-test")
    binding = sub.add_parser("bind-camera")
    binding.add_argument("camera_id")
    binding.add_argument("device")
    pair = sub.add_parser("bind-camera-pair", help="Register TOP and FRONT Wi-Fi cameras for an existing cage")
    _pair_arguments(pair)
    cage = sub.add_parser("add-cage", help="Reuse explicit inventory and add a camera pair; node credentials require provisioning")
    _pair_arguments(cage)
    cage.add_argument("--node-id", required=True)
    cage.add_argument("--template-cage", required=True)
    args = parser.parse_args()
    if args.action == "cameras":
        print(json.dumps(discover(), indent=2)); return
    config_path = args.config
    config = load_settings(config_path)
    if args.action in ("bind-camera-pair", "add-cage"):
        original = config_path.read_text()
        base = original
        try:
            if args.action == "add-cage":
                base = add_cage(original, args.cage_id, args.node_id, args.template_cage)
            proposed, camera_ids = bind_camera_pair(base, args.cage_id, args.top, args.front)
            changed = False
            if args.output is not None:
                _save_candidate(args.output, proposed)
            elif args.apply:
                changed = apply_config(config_path, original, proposed)
        except ValidationError as error:
            parser.error("; ".join(".".join(map(str, item["loc"])) + ": " + item["msg"]
                                   for item in error.errors(include_input=False, include_url=False)))
        except (OSError, ValueError) as error:
            parser.error(str(error))
        result = {"site_id": config.site_id, "gateway_id": config.gateway_id,
                  "cage_id": args.cage_id, "camera_ids": camera_ids,
                  "validated": True, "applied": bool(args.apply), "restarted": changed,
                  "candidate": str(args.output) if args.output is not None else None,
                  "physical_camera_verification": "not_performed",
                  "hardware_outputs_enabled": config.hardware_outputs_enabled}
        if args.action == "add-cage":
            result.update(node_id=args.node_id, policies_enabled=False,
                          sensor_credentials_provisioned=False)
        print(json.dumps(result, ensure_ascii=False)); return
    env = read_environment(config_path.with_name("gateway.env"))
    if args.action == "gpu-test":
        for cage in config.cages:
            result = subprocess.run([sys.executable, "-m", "apps.worker", "--gateway-config", str(config_path),
                "environment-probe", "--cage-id", cage.id], env={**os.environ, **env}, capture_output=True, text=True)
            print(result.stdout.strip())
            if result.returncode:
                raise SystemExit(result.returncode)
        return
    if args.action == "bind-camera":
        camera = next((c for c in config.cameras if c.id == args.camera_id), None)
        if camera is None:
            parser.error("unknown camera_id")
        CameraConfig.model_validate({**camera.model_dump(), "device": args.device})
        if not Path(args.device).exists():
            parser.error("camera is not connected at that persistent USB path")
        original = config_path.read_text()
        sections = re.split(r"(?m)^\[\[cameras\]\]\s*$", original)
        found = False
        for i in range(1, len(sections)):
            if re.search(r'(?m)^id\s*=\s*"'+re.escape(args.camera_id)+r'"\s*$', sections[i]):
                sections[i] = re.sub(r"(?m)^device\s*=.*\n?", "", sections[i])
                sections[i] = "\ndevice = "+json.dumps(args.device)+"\n"+sections[i].lstrip("\n")
                found = True
        if not found:
            parser.error("unsupported camera config formatting")
        proposed = "[[cameras]]".join(sections)
        apply_config(config_path, original, proposed)
        print(json.dumps({"bound": args.camera_id, "device": args.device})); return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ("/health", "/v1/cloud", "/v1/cages", "/v1/environment", "/v1/cameras"):
        req = urllib.request.Request(f"http://127.0.0.1:{config.server.port}"+path,
            headers={"Authorization":"Bearer "+env["HABITAT_API_TOKEN"]})
        with opener.open(req, timeout=5) as response:
            print(json.dumps({"path":path, "result":json.load(response)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
