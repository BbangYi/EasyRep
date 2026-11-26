"""Prepare DFR1172 files or provision native firmware; never flash or print secrets.

The legacy P4 binary is pinned to the manufacturer's supplied image. Microdot is pinned
to the reviewed First_Connection_R1 package, not claimed as a vendor checksum.
Keep the external 8 MB firmware package outside the source repository.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


FIRMWARE_NAME = "DFRobot_ESP32P4_MicroPython.bin"
FIRMWARE_SIZE = 8267920
FIRMWARE_SHA256 = "4ecbb6d5bd6ce82083acbee91413a6583ce8d0aa07aa02fd1c501f1c9d9e8689"
MICRODOT_SHA256 = "7cb6d3f53da01a358bbabda9ac3c7a795534d01ae66314d934029dad2be07e5c"
FLASH_ADDRESS = "0x2000"
IDENTITY_FIELDS = ("site_id", "gateway_id", "cage_id", "camera_id", "view")


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(package):
    package = Path(package).resolve()
    firmware = package / "firmware" / FIRMWARE_NAME
    microdot = package / "camera" / "microdot.py"
    if not firmware.is_file() or firmware.stat().st_size != FIRMWARE_SIZE:
        raise ValueError("P4 firmware file is missing or has an unexpected size")
    if checksum(firmware) != FIRMWARE_SHA256:
        raise ValueError("P4 firmware SHA-256 does not match the pinned image")
    if not microdot.is_file() or checksum(microdot) != MICRODOT_SHA256:
        raise ValueError("Microdot SHA-256 does not match the reviewed package")
    return firmware, microdot


def load_wifi(path):
    path = Path(path)
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Wi-Fi JSON must be a private file with mode 0600 or stricter")
    if path.stat().st_size > 4096:
        raise ValueError("Wi-Fi JSON is too large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Wi-Fi file must contain valid JSON") from None
    if not isinstance(value, dict) or set(value) != {"wifi_ssid", "wifi_password"}:
        raise ValueError("Wi-Fi JSON must contain only wifi_ssid and wifi_password")
    return validate_wifi(value)


def validate_wifi(value):
    ssid, password = value["wifi_ssid"], value["wifi_password"]
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("invalid Wi-Fi SSID length")
    if not isinstance(password, str):
        raise ValueError("invalid Wi-Fi password")
    length = len(password.encode("utf-8"))
    if not (8 <= length <= 63 or (length == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", password))):
        raise ValueError("invalid Wi-Fi password length")
    if "\x00" in ssid or "\x00" in password:
        raise ValueError("invalid Wi-Fi configuration")
    return value


def load_native_config(path):
    """Read the same private v1 configuration used by deployed MicroPython nodes."""
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
            or path.stat().st_size > 4096):
        raise ValueError("native configuration must be a private regular file of at most 4096 bytes")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("invalid native camera configuration") from None
    fields = {"schema_version", *IDENTITY_FIELDS, "wifi_ssid", "wifi_password"}
    if (not isinstance(config, dict) or set(config) != fields
            or type(config["schema_version"]) is not int or config["schema_version"] != 1
            or config["view"] not in ("top", "front")
            or any(not isinstance(config[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", config[k])
                   for k in IDENTITY_FIELDS[:-1])):
        raise ValueError("invalid native camera identity")
    validate_wifi({key: config[key] for key in ("wifi_ssid", "wifi_password")})
    return config


def provision_h264(config_path, port, *, serial_factory=None, timeout_s=45):
    """Send private configuration once, after confirming native firmware over USB.

    An acknowledgement is not proof of camera capture or Wi-Fi connectivity.
    A timeout never replays provisioning automatically and never exposes UART text.
    Cold boot may spend about 18 seconds in the C6 handshake and sensor probe.
    """
    config = load_native_config(config_path)
    path = Path(port)
    if path.parent != Path("/dev/serial/by-id") or not path.name.startswith("usb-"):
        raise ValueError("select the verified camera's stable /dev/serial/by-id USB port")
    payload = json.dumps(config, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(payload) > 4096:
        raise ValueError("encoded native camera configuration is too large")
    if serial_factory is None:
        try:
            import serial
        except ImportError:
            raise ValueError("pyserial is required in the separate camera deployment environment") from None
        serial_factory = serial.Serial

    def reply(link, predicate):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = link.read_until(b"\n", 1024)
            if not line.endswith(b"\n"):
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict) and predicate(value):
                return value
        raise ValueError("native camera acknowledgement timed out; provisioning was not retried")

    try:
        with serial_factory(port=None, baudrate=115200, timeout=0.2, write_timeout=3) as link:
            link.dtr = False
            link.rts = False
            link.port = str(path)
            link.open()
            link.reset_input_buffer()
            link.write(b"HABITAT_STATUS\n")
            link.flush()
            status = reply(link, lambda row: "firmware" in row)
            if status.get("firmware") != "habitatos_dfr1172_h264":
                raise ValueError("connected firmware is not the HabitatOS H.264 camera")
            link.write(b"HABITAT_CONFIG " + payload + b"\n")
            link.flush()
            ack = reply(link, lambda row: "configured" in row and "firmware" not in row)
            if ack.get("configured") is not True or ack.get("restarting") is not True:
                raise ValueError("native camera configuration was not accepted")
    except ValueError:
        raise
    except Exception:
        raise ValueError("native camera serial provisioning failed; result requires verification") from None
    return {"identity": {key: config[key] for key in IDENTITY_FIELDS},
            "configuration_acknowledged": True, "firmware_uploaded": False,
            "live_verification": "pending"}


def program_path():
    here = Path(__file__).resolve().parent
    for base in (here, here.parent):
        candidate = base / "firmware/camera_node/main.py"
        if candidate.is_file():
            return candidate
    raise ValueError("public camera_node/main.py is missing from this release")


def prepare(package, wifi_file, output, *, site_id, gateway_id, cage_id, camera_id, view):
    identity = dict(site_id=site_id, gateway_id=gateway_id, cage_id=cage_id, camera_id=camera_id, view=view)
    if any(not isinstance(identity[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity[key])
           for key in IDENTITY_FIELDS[:-1]):
        raise ValueError("identity fields need 1 to 64 letters, digits, underscores or hyphens")
    if view not in ("top", "front"):
        raise ValueError("view must be top or front")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; existing node files were preserved")
    firmware, microdot = validate_package(package)
    config = dict(schema_version=1, **identity, **load_wifi(wifi_file))
    files = {"main.py": program_path().read_bytes(), "microdot.py": microdot.read_bytes(),
             "config.json": (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    written = []
    try:
        for name, data in files.items():
            target = output / name
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            written.append(target)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
    except Exception:
        for target in written:
            target.unlink(missing_ok=True)
        output.rmdir()
        raise
    return {"identity": identity, "directory": str(output),
            "files": {name: {"path": str(output / name), "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in files.items()},
            "firmware": {"path": str(firmware), "sha256": FIRMWARE_SHA256,
                         "bytes": FIRMWARE_SIZE, "chip": "esp32p4", "address": FLASH_ADDRESS,
                         # Both pinned image headers declare revisions 1..199
                         # using Espressif's major * 100 + minor encoding.
                         "min_chip_revision": "0.1", "max_chip_revision": "1.99",
                         "requires_chip_verification": True},
            "firmware_uploaded": False, "program_uploaded": False,
            "physical_verification": "not_performed"}


def main():
    if "--provision-h264" in sys.argv[1:]:
        parser = argparse.ArgumentParser(description="Provision an already flashed native H.264 camera over verified USB")
        parser.add_argument("--provision-h264", action="store_true", required=True)
        parser.add_argument("--config-file", type=Path, required=True)
        parser.add_argument("--port", required=True)
        args = parser.parse_args()
        try:
            result = provision_h264(args.config_file, args.port)
        except (OSError, ValueError) as error:
            parser.exit(1, "Camera configuration failed: " + str(error) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--wifi-file", type=Path, required=True,
                        help="Private JSON containing wifi_ssid and wifi_password; never put credentials in arguments")
    parser.add_argument("--output", type=Path, required=True, help="New private directory for board files")
    for key in IDENTITY_FIELDS[:-1]:
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--view", choices=("top", "front"), required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.package, args.wifi_file, args.output,
                         **{key: getattr(args, key) for key in IDENTITY_FIELDS})
    except (OSError, ValueError) as error:
        parser.exit(1, "Camera node preparation failed: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
