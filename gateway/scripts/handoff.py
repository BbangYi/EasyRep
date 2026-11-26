"""Write curated developer handoffs with a manifest and an archive checksum."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


def write_bundle(destination, files):
    destination = Path(destination)
    manifest = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}
    contents = {**files, "manifest.sha256.json": (json.dumps(manifest, indent=2) + "\n").encode()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, body in sorted(contents.items()):
                archive.writestr(name, body)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    destination.with_name(destination.name + ".sha256").write_text(
        f"{hashlib.sha256(destination.read_bytes()).hexdigest()}  {destination.name}\n")
    return len(contents)
