"""Validate the scalar, single-vertex Gaussian PLY contract without loading it all."""

from __future__ import annotations

from itertools import chain
import math
import struct
from pathlib import Path


REQUIRED = {"x", "y", "z", "opacity", *(f"f_dc_{i}" for i in range(3)),
            *(f"scale_{i}" for i in range(3)), *(f"rot_{i}" for i in range(4))}
TYPES = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}


def validate_ply(path: Path) -> dict:
    """Return a summary or raise ValueError for malformed/non-Gaussian content."""
    path = Path(path)
    with path.open("rb") as stream:
        if stream.readline(16).strip() != b"ply":
            raise ValueError("Not a PLY file")
        encoding, count, properties = None, None, []
        while stream.tell() <= 65536:
            raw = stream.readline(4097)
            if not raw or len(raw) > 4096:
                raise ValueError("Invalid PLY header")
            try:
                words = raw.decode("ascii").split()
            except UnicodeDecodeError as exc:
                raise ValueError("Non-ASCII PLY header") from exc
            if not words or words[0] in {"comment", "obj_info"}:
                continue
            if words == ["end_header"]:
                break
            if words[0] == "format" and len(words) == 3 and words[2] == "1.0" and encoding is None:
                encoding = words[1]
            elif words[0] == "element" and len(words) == 3 and words[1] == "vertex" and count is None:
                try:
                    count = int(words[2])
                except ValueError as exc:
                    raise ValueError("Invalid vertex count") from exc
            elif words[0] == "property" and len(words) == 3 and count is not None and words[1] in TYPES:
                properties.append((words[2], TYPES[words[1]]))
                if len(properties) > 256:
                    raise ValueError("Too many PLY properties")
            else:
                raise ValueError("PLY requires one vertex element with scalar properties")
        else:
            raise ValueError("PLY header exceeds limit")
        if encoding not in {"ascii", "binary_little_endian", "binary_big_endian"} or not count or count < 0:
            raise ValueError("Invalid PLY format or vertex count")
        names = [name for name, _ in properties]
        if len(names) != len(set(names)) or not REQUIRED.issubset(names):
            raise ValueError("Missing or duplicate Gaussian properties")
        if any(kind not in "fd" for name, kind in properties if name in REQUIRED):
            raise ValueError("Gaussian properties must be floating point")
        layout = struct.Struct((">" if encoding == "binary_big_endian" else "<") + "".join(t for _, t in properties))
        if encoding == "ascii":
            for _ in range(count):
                values = stream.readline(16385).split()
                if len(values) != len(properties):
                    raise ValueError("PLY vertex payload length mismatch")
                try:
                    parsed = [float(v) if kind in "fd" else int(v) for v, (_, kind) in zip(values, properties)]
                    if not all(math.isfinite(v) for v in parsed):
                        raise ValueError("Non-finite vertex value")
                    layout.pack(*parsed)  # also checks scalar type range
                except (ValueError, OverflowError, struct.error) as exc:
                    raise ValueError("Invalid PLY scalar value") from exc
            if stream.read(1):
                # The contract permits trailing whitespace, never another vertex.
                stream.seek(-1, 1)
                while block := stream.read(65536):
                    if block.strip():
                        raise ValueError("Extra PLY payload")
        else:
            if path.stat().st_size - stream.tell() != count * layout.size:
                raise ValueError("PLY vertex payload length mismatch")
            remaining = count
            while remaining:
                vertices = min(remaining, 4096)
                block = stream.read(vertices * layout.size)
                if len(block) != vertices * layout.size:
                    raise ValueError("Truncated PLY payload")
                # Stream every scalar without a Python generator per vertex.
                if not all(map(math.isfinite, chain.from_iterable(layout.iter_unpack(block)))):
                    raise ValueError("Non-finite vertex value")
                remaining -= vertices
    return {"encoding": encoding, "vertex_count": count, "properties": names, "size_bytes": path.stat().st_size}
