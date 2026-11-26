import hashlib
import math
import os
from pathlib import Path
import warnings

from PIL import Image

from .errors import ComputeFailure

CHUNK_BYTES = 256 * 1024


def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def verify_image(path, suffix):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                expected = "PNG" if suffix.lower() == ".png" else "JPEG"
                if image.format != expected or image.width * image.height > 20_000_000:
                    raise ComputeFailure("unsupported_image")
                image.load()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ComputeFailure("invalid_image") from None


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def verify_gaussian_ply(path):
    """Validate scalar Gaussian PLY structure/counts, not reconstruction quality/scale."""
    widths = {"char": 1, "uchar": 1, "short": 2, "ushort": 2, "int": 4, "uint": 4,
              "float": 4, "double": 8, "int8": 1, "uint8": 1, "int16": 2, "uint16": 2,
              "int32": 4, "uint32": 4, "float32": 4, "float64": 8}
    required = {"x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"}
    try:
        with Path(path).open("rb") as stream:
            lines, header_size = [], 0
            while header_size < 65536:
                raw = stream.readline(1024)
                if not raw or not raw.endswith(b"\n"):
                    raise ValueError
                header_size += len(raw)
                lines.append(raw.decode("ascii").strip())
                if lines[-1] == "end_header":
                    break
            if (header_size > 65536 or len(lines) < 4 or lines[0] != "ply"
                    or lines[-1] != "end_header"):
                raise ValueError
            formats = {"format ascii 1.0", "format binary_little_endian 1.0", "format binary_big_endian 1.0"}
            if lines[1] not in formats:
                raise ValueError
            count, properties = None, {}
            for line in lines[2:-1]:
                pieces = line.split()
                if pieces[:1] in (["comment"], ["obj_info"]):
                    continue
                if pieces[:2] == ["element", "vertex"] and len(pieces) == 3 and count is None:
                    count = int(pieces[2])
                elif (pieces[:1] == ["property"] and len(pieces) == 3 and count is not None
                      and pieces[1] in widths and pieces[2] not in properties):
                    properties[pieces[2]] = pieces[1]
                else:
                    # Gaussian exports contain one vertex element with scalar properties.
                    raise ValueError
            if count is None or count <= 0 or not required <= properties.keys():
                raise ValueError
            if any(properties[name] not in ("float", "double", "float32", "float64") for name in required):
                raise ValueError
            if lines[1] != "format ascii 1.0":
                expected = count * sum(widths[kind] for kind in properties.values())
                if Path(path).stat().st_size - stream.tell() != expected:
                    raise ValueError
            else:
                max_line = len(properties) * 128 + 1
                for _ in range(count):
                    row = stream.readline(max_line)
                    values = row.split()
                    if len(row) >= max_line or len(values) != len(properties):
                        raise ValueError
                    if not all(math.isfinite(float(value)) for value in values):
                        raise ValueError
                if stream.read(1):
                    raise ValueError
    except (ValueError, UnicodeDecodeError, OverflowError):
        raise ComputeFailure("invalid_gaussian_ply") from None
