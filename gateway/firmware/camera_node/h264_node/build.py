#!/usr/bin/env python3
"""Build generic DFR1172 firmware offline; never upload or read private config."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BOARD = "esp32:esp32:dfrobot_firebeetle2_esp32p4:ChipVariant=prev3,PartitionScheme=app3M_fat9M_16MB"
CORE_VERSION = "3.3.12"
FLAGS = "-DCONFIG_MEDIA_LIB_SOCKET_ENABLE=1 -DCONFIG_MEDIA_LIB_NETIF_ENABLE=1 -DCONFIG_MEDIA_LIB_CRYPT_ENABLE=1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--arduino-cli", default=shutil.which("arduino-cli") or str(Path.home() / ".local/share/habitat-toolchain/bin/arduino-cli"))
    args = parser.parse_args()
    cache = args.cache.resolve()
    source = Path(__file__).resolve().parent
    library = cache / "libraries/EspMediaProtocols"
    if not library.is_dir():
        raise SystemExit("Run prepare_dependencies.py --cache PATH first")
    core = json.loads(subprocess.check_output([args.arduino_cli, "core", "list", "--format", "json"], text=True))
    platforms = core.get("platforms", core) if isinstance(core, dict) else core
    if not any(item.get("id") == "esp32:esp32" and item.get("installed_version") == CORE_VERSION for item in platforms):
        raise SystemExit("Pinned esp32 Arduino core 3.3.12 is required")
    # Verify every cached dependency before compiler execution, offline.
    dependencies = json.loads((source / "dependencies.lock.json").read_text())
    for item in dependencies["files"]:
        path = item["path"]
        relative = Path("src/esp32p4/libesp_media_protocols.a") if path.endswith(".a") else Path(path.replace("/", "_")) if path.endswith("LICENSE") else Path("src") / Path(path).name
        data = (library / relative).read_bytes()
        if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != item["sha"]:
            raise SystemExit("Cached dependency integrity mismatch: " + path)
    build = cache / "build"
    command = [args.arduino_cli, "compile", "--fqbn", BOARD, "--libraries", str(cache / "libraries"), "--build-path", str(build),
               "--build-property", "compiler.c.extra_flags=" + FLAGS, "--build-property", "compiler.cpp.extra_flags=" + FLAGS, str(source)]
    subprocess.run(command, check=True)
    segments = []
    for offset, name in [(0x2000, "h264_node.ino.bootloader.bin"), (0x8000, "h264_node.ino.partitions.bin"), (0x10000, "h264_node.ino.bin")]:
        path = build / name
        data = path.read_bytes()
        segments.append({"offset": hex(offset), "file": str(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    # Arduino supplies OTA-select initialization at 0xe000. Include its exact bytes
    # copied by the build so an operator does not guess offsets during migration.
    core_path = Path.home() / ".arduino15/packages/esp32/hardware/esp32" / CORE_VERSION
    ota = core_path / "tools/partitions/boot_app0.bin"
    data = ota.read_bytes()
    copied = build / "boot_app0.bin"
    copied.write_bytes(data)
    segments.append({"offset": "0xe000", "file": str(copied), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"schema_version": 1, "firmware": "habitatos_dfr1172_h264", "board": BOARD, "arduino_core": CORE_VERSION,
                "chip": "esp32p4", "chip_revision_max_exclusive": 300, "flash_size": "16MB", "flash_mode": "dio", "flash_freq": "80m",
                "http_identity_port": 5000, "rtsp_port": 8554, "rtsp_path": "/stream", "width": 800, "height": 800, "fps": 20,
                "bitrate_bps": 2000000, "gop_frames": 20, "contains_store_secrets": False, "hardware_verified": False,
                "segments": sorted(segments, key=lambda item: int(item["offset"], 16))}
    (build / "flash-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"build": str(build), "manifest": str(build / "flash-manifest.json"), "hardware_verified": False}))


if __name__ == "__main__":
    main()
