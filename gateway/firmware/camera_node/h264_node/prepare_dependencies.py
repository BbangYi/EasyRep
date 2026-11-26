#!/usr/bin/env python3
"""Fetch the pinned official RTSP dependency into an ignored Arduino build cache.

Run separately from build so ordinary rebuilds require no network. This downloads
Espressif's ESP32-P4 library and its unmodified SAL source, verifies Git blob IDs,
and never accesses device configuration, USB, or operational services.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

COMMIT = "7162d32381d6e1f8c8cba2ee5edcbfe82bc964b1"
SOURCE = "https://raw.githubusercontent.com/espressif/esp-adf-libs/" + COMMIT + "/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    destination = args.cache / "libraries" / "EspMediaProtocols"
    manifest = json.loads(Path(__file__).with_name("dependencies.lock.json").read_text())
    for item in manifest["files"]:
        path = item["path"]
        if path.endswith(".a"):
            relative = Path("src/esp32p4/libesp_media_protocols.a")
        elif path.endswith("LICENSE"):
            relative = Path(path.replace("/", "_"))
        else:
            # SAL headers use flat includes; filenames in the pinned tree are unique.
            relative = Path("src") / Path(path).name
        output = destination / relative
        data = output.read_bytes() if output.exists() else None
        def verified(value):
            return value is not None and hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest() == item["sha"]
        if not verified(data):
            with urllib.request.urlopen(SOURCE + path, timeout=60) as response:
                data = response.read(8 * 1024 * 1024)
            if not verified(data):
                raise RuntimeError("Dependency integrity mismatch: " + path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
    (destination / "library.properties").write_text(
        "name=EspMediaProtocols\nversion=1.0.3\nauthor=Espressif\n"
        "maintainer=Espressif\nsentence=Official pinned RTSP and media SAL\n"
        "paragraph=Downloaded from esp-adf-libs with Git blob integrity checks\n"
        "category=Communication\nurl=https://github.com/espressif/esp-adf-libs\n"
        "architectures=esp32\nprecompiled=true\nincludes=esp_rtsp.h\n")
    print(json.dumps({"dependency_commit": COMMIT, "verified_files": len(manifest["files"]), "library": str(destination)}))


if __name__ == "__main__":
    main()
