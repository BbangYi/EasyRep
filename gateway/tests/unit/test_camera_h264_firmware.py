"""Host checks execute the production config and Annex-B validation header.

They verify provisioning/stream boundary rejection, not sensor or radio operation.
The target compiler build is separate: firmware/camera_node/h264_node/build.py.
"""
import ctypes
import ctypes.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture(scope="module")
def contract(tmp_path_factory):
    compiler = shutil.which("g++")
    library = ctypes.util.find_library("cjson")
    headers = [Path("/usr/include/cjson")]
    headers.extend((Path.home() / ".arduino15/packages/esp32/tools").glob("esp32p4_es-libs/*/include/json/cJSON"))
    include = next((item for item in headers if (item / "cJSON.h").is_file()), None)
    if not compiler or not library or include is None:
        pytest.skip("Host compiler, cJSON library and headers are required")
    directory = tmp_path_factory.mktemp("camera-h264-contract")
    source = directory / "contract.cpp"
    source.write_text('''#include "camera_contract.h"
extern "C" bool config_valid(const char *data, size_t size) {
  auto *value = habitat_camera::parseConfig(data, size);
  bool valid = value != nullptr;
  cJSON_Delete(value);
  return valid;
}
extern "C" unsigned inspect(const unsigned char *data, size_t size) {
  auto value = habitat_camera::inspectAnnexB(data, size);
  return value.sps | value.pps << 1 | value.idr << 2 | value.baseline << 3;
}
''')
    repo = Path(__file__).resolve().parents[2]
    output = directory / "contract.so"
    result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", str(source),
                             "-I", str(include), "-I", str(repo / "firmware/camera_node/h264_node"),
                             "-Wl,--no-undefined", "-l:" + library, "-o", str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    loaded = ctypes.CDLL(str(output))
    loaded.config_valid.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    loaded.config_valid.restype = ctypes.c_bool
    loaded.inspect.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
    loaded.inspect.restype = ctypes.c_uint
    return loaded


def config(**updates):
    value = dict(schema_version=1, site_id="TEST-SITE", gateway_id="TEST-GATEWAY", cage_id="TEST-CAGE",
                 camera_id="TEST-FRONT", view="front", wifi_ssid="test-only", wifi_password="test-only-password")
    value.update(updates)
    return value


@pytest.mark.parametrize("updates,valid", [
    ({}, True), ({"view": "top"}, True), ({"schema_version": True}, False), ({"schema_version": 2}, False),
    ({"camera_id": "a" * 64}, True), ({"camera_id": "a" * 65}, False), ({"camera_id": "../../private"}, False),
    ({"view": "unknown"}, False), ({"wifi_ssid": "한" * 10}, True), ({"wifi_ssid": "한" * 11}, False),
    ({"wifi_password": "short"}, False), ({"wifi_password": "a" * 64}, True), ({"wifi_password": "x" * 64}, False),
    ({"wifi_password": "test\x00password"}, False), ({"stream_url": "http://other-host"}, False),
])
def test_private_config_contract(contract, updates, valid):
    encoded = json.dumps(config(**updates), ensure_ascii=False).encode()
    assert contract.config_valid(encoded, len(encoded)) is valid


@pytest.mark.parametrize("transform", [
    lambda value: value[:-1] + b',"schema_version":1}',
    lambda value: value + b'{}',
    lambda value: value.replace(b'"schema_version": 1, ', b''),
    lambda value: value + b' ' * 4096,
    lambda value: value + b'\0',
])
def test_malformed_config_is_rejected(contract, transform):
    encoded = transform(json.dumps(config()).encode())
    assert not contract.config_valid(encoded, len(encoded))


@pytest.mark.parametrize("data,flags", [
    (b"", 0), (b"\x00\x00\x01", 0), (b"\x00\x00\x00\x01", 0),
    (b"\x00\x00\x01\x65\x88", 4),
    (b"\x00\x00\x00\x01\x67\x42\x00\x00\x01\x68\xff\x00\x00\x01\x65\x88", 15),
    (b"\x00\x00\x01\x67\x64\x00\x00\x01\x68\xff\x00\x00\x01\x65\x88", 7),
    (b"\x67\x42\x68\x65", 0),
])
def test_annex_b_requires_sps_pps_idr_and_baseline(contract, data, flags):
    assert contract.inspect(data, len(data)) == flags
