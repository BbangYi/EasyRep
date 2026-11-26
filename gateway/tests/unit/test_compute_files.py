import struct

import pytest

from habitat.compute.errors import ComputeFailure
from habitat.compute.files import verify_gaussian_ply
from tests.contract.compute_stub import gaussian_fixture


@pytest.mark.parametrize("kind", ["ascii", "binary_little_endian", "binary_big_endian"])
def test_gaussian_ply_formats(tmp_path, kind):
    header, data = gaussian_fixture().split(b"end_header\n")
    if kind != "ascii":
        header = header.replace(b"format ascii", f"format {kind}".encode())
        data = struct.pack(("<" if kind == "binary_little_endian" else ">") + "14f", *([0.0] * 14))
    path = tmp_path / "splat.ply"
    path.write_bytes(header + b"end_header\n" + data)
    verify_gaussian_ply(path)


@pytest.mark.parametrize("failure", ["missing_gaussians", "truncated", "wrong_count", "nan", "binary_size", "extra_data"])
def test_corrupt_ply_is_not_accepted_as_gaussian_output(tmp_path, failure):
    data = gaussian_fixture()
    if failure == "missing_gaussians":
        data = data.replace(b"property float opacity", b"property float red")
    elif failure == "truncated":
        data = data[:-5]
    elif failure == "wrong_count":
        data = data.replace(b"vertex 1", b"vertex 2")
    elif failure == "nan":
        data = data[:-2] + b"nan\n"
    elif failure == "binary_size":
        data = data.replace(b"format ascii", b"format binary_little_endian")
    else:
        data += b"unexpected payload"
    path = tmp_path / "splat.ply"
    path.write_bytes(data)
    with pytest.raises(ComputeFailure, match="invalid_gaussian_ply"):
        verify_gaussian_ply(path)
