import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deploy import camera_node


@pytest.fixture
def package(tmp_path, monkeypatch):
    package = tmp_path / "package"
    (package / "firmware").mkdir(parents=True)
    (package / "camera").mkdir()
    firmware = b"p4-fixture-only-not-real-firmware"
    microdot = b"# fixture from external package\n"
    (package / "firmware" / camera_node.FIRMWARE_NAME).write_bytes(firmware)
    (package / "camera/microdot.py").write_bytes(microdot)
    monkeypatch.setattr(camera_node, "FIRMWARE_SIZE", len(firmware))
    monkeypatch.setattr(camera_node, "FIRMWARE_SHA256", hashlib.sha256(firmware).hexdigest())
    monkeypatch.setattr(camera_node, "MICRODOT_SHA256", hashlib.sha256(microdot).hexdigest())
    return package


@pytest.fixture
def wifi_file(tmp_path):
    path = tmp_path / "wifi.json"
    path.write_text(json.dumps({"wifi_ssid": "PRIVATE-STORE-WIFI", "wifi_password": "private-password-value"}))
    path.chmod(0o600)
    return path


def identity(view="top"):
    return dict(site_id="STORE-TEST", gateway_id="PI-TEST", cage_id="CAGE-TEST",
                camera_id="CAGE-TEST-" + view.upper(), view=view)


@pytest.fixture
def native_config(tmp_path):
    path = tmp_path / "native.json"
    path.write_text(json.dumps({"schema_version": 1, **identity(),
                               "wifi_ssid": "PRIVATE-NETWORK", "wifi_password": "private-wifi-secret"}))
    path.chmod(0o600)
    return path


class NativeSerial:
    def __init__(self, firmware="habitatos_dfr1172_h264", acknowledge=True):
        self.writes = []
        self.lines = []
        self.firmware = firmware
        self.acknowledge = acknowledge
        self.closed = False

    def __call__(self, **kwargs):
        assert kwargs["port"] is None and kwargs["write_timeout"] == 3
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def open(self):
        assert self.dtr is False and self.rts is False

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass

    def write(self, data):
        self.writes.append(data)
        if data == b"HABITAT_STATUS\n":
            self.lines.append(json.dumps({"firmware": self.firmware, "configured": False}).encode() + b"\n")
        elif self.acknowledge:
            self.lines.append(b'{"configured":true,"restarting":true}\n')

    def read_until(self, terminator, limit):
        assert terminator == b"\n" and limit == 1024
        return self.lines.pop(0) if self.lines else b""


def test_native_provision_sends_once_only_after_firmware_check_and_redacts_secrets(native_config):
    link = NativeSerial()
    result = camera_node.provision_h264(native_config, "/dev/serial/by-id/usb-P4-test", serial_factory=link)
    assert link.closed and result["configuration_acknowledged"]
    assert result["identity"] == identity() and result["live_verification"] == "pending"
    assert len(link.writes) == 2 and link.writes[0] == b"HABITAT_STATUS\n"
    assert json.loads(link.writes[1][15:]) == json.loads(native_config.read_text())
    assert "PRIVATE-NETWORK" not in json.dumps(result) and "private-wifi-secret" not in json.dumps(result)


def test_native_provision_rejects_other_firmware_before_sending_private_config(native_config):
    link = NativeSerial(firmware="sensor-node")
    with pytest.raises(ValueError, match="not the HabitatOS"):
        camera_node.provision_h264(native_config, "/dev/serial/by-id/usb-P4-test", serial_factory=link)
    assert link.writes == [b"HABITAT_STATUS\n"] and link.closed


def test_native_provision_ack_timeout_never_replays_private_write(native_config):
    link = NativeSerial(acknowledge=False)
    with pytest.raises(ValueError, match="not retried"):
        camera_node.provision_h264(native_config, "/dev/serial/by-id/usb-P4-test",
                                  serial_factory=link, timeout_s=0.01)
    assert len(link.writes) == 2 and link.closed


def test_native_provision_rejects_public_secrets_and_automatic_serial_path(native_config):
    link = NativeSerial()
    with pytest.raises(ValueError, match="stable"):
        camera_node.provision_h264(native_config, "/dev/ttyUSB0", serial_factory=link)
    native_config.chmod(0o644)
    with pytest.raises(ValueError, match="private regular"):
        camera_node.provision_h264(native_config, "/dev/serial/by-id/usb-P4-test", serial_factory=link)
    assert link.writes == []


@pytest.fixture
def node(monkeypatch):
    class App:
        def __init__(self):
            self.routes = {}

        def route(self, path):
            def register(function):
                self.routes[path] = function
                return function
            return register

    monkeypatch.setitem(sys.modules, "microdot", SimpleNamespace(Microdot=App))
    source = Path("firmware/camera_node/main.py")
    spec = importlib.util.spec_from_file_location("test_camera_node_program", source)
    program = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(program)
    clock = SimpleNamespace(now=0)
    clock.ticks_ms = lambda: clock.now
    clock.ticks_diff = lambda a, b: a - b
    clock.sleep_ms = lambda n: setattr(clock, "now", clock.now + n)
    monkeypatch.setattr(program, "time", clock)
    return program


def test_prepare_two_nodes_uses_identical_program_and_private_configs(package, wifi_file, tmp_path, node):
    original_firmware = (package / "firmware" / camera_node.FIRMWARE_NAME).read_bytes()
    before_wifi = wifi_file.read_bytes()
    outputs = []
    for view in ("top", "front"):
        output = tmp_path / view
        result = camera_node.prepare(package, wifi_file, output, **identity(view))
        assert output.stat().st_mode & 0o777 == 0o700
        assert set(p.name for p in output.iterdir()) == {"main.py", "microdot.py", "config.json"}
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir())
        assert node.load_config(output / "config.json")["view"] == view
        assert result["identity"] == identity(view)
        assert not result["firmware_uploaded"] and not result["program_uploaded"]
        assert result["firmware"]["chip"] == "esp32p4" and result["firmware"]["address"] == "0x2000"
        assert result["firmware"]["min_chip_revision"] == "0.1"
        assert result["firmware"]["max_chip_revision"] == "1.99"
        assert result["firmware"]["requires_chip_verification"] is True
        assert "PRIVATE-STORE-WIFI" not in json.dumps(result)
        assert "private-password-value" not in json.dumps(result)
        outputs.append(output)
    assert (outputs[0] / "main.py").read_bytes() == (outputs[1] / "main.py").read_bytes()
    assert (package / "firmware" / camera_node.FIRMWARE_NAME).read_bytes() == original_firmware
    assert wifi_file.read_bytes() == before_wifi


@pytest.mark.parametrize("file, change", [
    ("firmware", "size"), ("firmware", "hash"), ("microdot", "hash")])
def test_unverified_package_does_not_create_node_files(package, wifi_file, tmp_path, file, change):
    path = package / ("firmware/" + camera_node.FIRMWARE_NAME if file == "firmware" else "camera/microdot.py")
    original = path.read_bytes()
    path.write_bytes(original + b"x" if change == "size" else b"X" + original[1:])
    output = tmp_path / "prepared"
    with pytest.raises(ValueError):
        camera_node.prepare(package, wifi_file, output, **identity())
    assert not output.exists()


@pytest.mark.parametrize("existing", ["empty", "configured", "symlink"])
def test_existing_output_is_never_replaced(package, wifi_file, tmp_path, existing):
    output = tmp_path / "prepared"
    if existing == "symlink":
        output.symlink_to(tmp_path / "missing")
    else:
        output.mkdir()
        if existing == "configured":
            (output / "config.json").write_text("preserve")
    with pytest.raises(ValueError, match="preserved"):
        camera_node.prepare(package, wifi_file, output, **identity())
    if existing == "configured":
        assert (output / "config.json").read_text() == "preserve"
    elif existing == "symlink":
        assert output.is_symlink()
    else:
        assert not list(output.iterdir())


@pytest.mark.parametrize("change", ["public", "unexpected_key", "short_password", "bad_json"])
def test_wifi_input_validation_never_exposes_secret(package, wifi_file, tmp_path, change):
    if change == "public":
        wifi_file.chmod(0o644)
    elif change == "unexpected_key":
        value = json.loads(wifi_file.read_text())
        value["unexpected"] = "private-password-value"
        wifi_file.write_text(json.dumps(value))
    elif change == "short_password":
        wifi_file.write_text(json.dumps(dict(wifi_ssid="private", wifi_password="short")))
    else:
        wifi_file.write_text("private-password-value malformed")
    with pytest.raises(ValueError) as error:
        camera_node.prepare(package, wifi_file, tmp_path / "prepared", **identity())
    assert "private-password-value" not in str(error.value)
    assert not (tmp_path / "prepared").exists()


@pytest.mark.parametrize("field, value", [("camera_id", "bad/identity"), ("cage_id", "C" * 65),
                                           ("view", "left"), ("site_id", "")])
def test_invalid_identity_is_rejected_without_output(package, wifi_file, tmp_path, field, value):
    mapping = identity()
    mapping[field] = value
    with pytest.raises(ValueError):
        camera_node.prepare(package, wifi_file, tmp_path / "prepared", **mapping)
    assert not (tmp_path / "prepared").exists()


def test_cli_outputs_only_identity_paths_and_hashes(package, wifi_file, tmp_path, monkeypatch, capsys):
    command = ["camera_node.py", "--package", str(package), "--wifi-file", str(wifi_file),
               "--output", str(tmp_path / "prepared")]
    for key, value in identity().items():
        command.extend(["--" + key.replace("_", "-"), value])
    monkeypatch.setattr(sys, "argv", command)
    camera_node.main()
    output = capsys.readouterr()
    receipt = json.loads(output.out)
    assert receipt["physical_verification"] == "not_performed"
    assert "PRIVATE-STORE-WIFI" not in output.out + output.err
    assert "private-password-value" not in output.out + output.err


def test_program_discovery_supports_standalone_release(tmp_path, monkeypatch):
    release = tmp_path / "release"
    source = release / "firmware/camera_node/main.py"
    source.parent.mkdir(parents=True)
    source.write_text("# shipped public program")
    monkeypatch.setattr(camera_node, "__file__", str(release / "camera_node.py"))
    assert camera_node.program_path() == source


def test_wifi_attempts_are_bounded_and_logs_do_not_include_credentials(node, capsys):
    config = dict(schema_version=1, **identity(), wifi_ssid="PRIVATE-STORE-WIFI", wifi_password="private-password-value")
    calls = []
    wlan = SimpleNamespace(active=lambda state: None, isconnected=lambda: False,
                           connect=lambda *args: calls.append(args), disconnect=lambda: None)
    assert not node.connect_wifi(config, wlan, attempts=2, timeout_s=1)
    assert len(calls) == 2 and node.time.now == 2000
    output = capsys.readouterr().out
    assert "attempt=1" in output and "attempt=2" in output and "unavailable" in output
    assert "PRIVATE-STORE-WIFI" not in output and "private-password-value" not in output


def test_wifi_disables_power_save_before_association_and_logs_readback(node, capsys):
    config = dict(schema_version=1, **identity(), wifi_ssid="PRIVATE-STORE-WIFI", wifi_password="private-password-value")
    state = {"pm": 1, "connected": False}
    calls = []

    def configure(key=None, **values):
        if key == "pm":
            calls.append(("read_pm", state["pm"]))
            return state["pm"]
        calls.append(("set_pm", values["pm"]))
        state["pm"] = values["pm"]

    def connect(*credentials):
        calls.append(("connect",))
        state["connected"] = True

    wlan = SimpleNamespace(PM_NONE=0, config=configure,
                           active=lambda active: calls.append(("active", active)),
                           isconnected=lambda: state["connected"], connect=connect)
    assert node.connect_wifi(config, wlan)
    assert calls == [("active", True), ("read_pm", 1), ("set_pm", 0),
                     ("read_pm", 0), ("connect",)]
    output = capsys.readouterr().out
    assert "CAMERA_WIFI pm=0 previous=1" in output
    assert "PRIVATE-STORE-WIFI" not in output and "private-password-value" not in output


@pytest.mark.parametrize("error_type", [OSError, ValueError, AttributeError])
def test_unsupported_wifi_power_save_setting_still_connects_without_error_details(node, capsys, error_type):
    config = dict(schema_version=1, **identity(), wifi_ssid="PRIVATE-STORE-WIFI", wifi_password="private-password-value")
    state = {"connected": False}

    def configure(key=None, **values):
        if key == "pm":
            return 1
        raise error_type("PRIVATE-STORE-WIFI private-password-value")

    def connect(ssid, password):
        assert (ssid, password) == (config["wifi_ssid"], config["wifi_password"])
        state["connected"] = True

    wlan = SimpleNamespace(PM_NONE=0, config=configure, active=lambda active: None,
                           isconnected=lambda: state["connected"], connect=connect)
    assert node.connect_wifi(config, wlan)
    output = capsys.readouterr().out
    assert "CAMERA_WIFI pm_unavailable" in output
    assert "PRIVATE-STORE-WIFI" not in output and "private-password-value" not in output


def test_wifi_power_save_logs_do_not_echo_nonnumeric_driver_values(node, capsys):
    wlan = SimpleNamespace(PM_NONE=0, active=lambda active: None,
                           config=lambda *args, **kwargs: "private-password-value",
                           isconnected=lambda: True)
    assert node.connect_wifi({}, wlan)
    assert capsys.readouterr().out == "CAMERA_WIFI pm_unavailable\n"


def test_identity_has_no_wifi_credentials_and_stream_uses_real_capture(node):
    config = dict(schema_version=1, **identity(), wifi_ssid="PRIVATE-STORE-WIFI", wifi_password="private-password-value")
    state = {"connected": True, "captures": 0}
    jpeg = b"\xff\xd8actual-frame\xff\xd9"

    def capture():
        state["captures"] += 1
        return jpeg

    app = node.create_app(config, SimpleNamespace(capture=capture),
                          SimpleNamespace(isconnected=lambda: state["connected"]))
    body, code, headers = app.routes["/identity"](None)
    assert code == 200 and body["camera_id"] == "CAGE-TEST-TOP"
    assert "wifi_ssid" not in body and "wifi_password" not in body
    stream, code, headers = app.routes["/video_feed"](None)
    assert next(stream).startswith(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length:")
    assert next(stream) == jpeg and next(stream) == b"\r\n"
    state["connected"] = False
    with pytest.raises(StopIteration):
        next(stream)
    assert state["captures"] == 1


def test_invalid_camera_capture_is_not_served_as_a_frame(node, capsys):
    config = dict(schema_version=1, **identity(), wifi_ssid="private", wifi_password="private-password-value")
    app = node.create_app(config, SimpleNamespace(capture=lambda: b"broken"),
                          SimpleNamespace(isconnected=lambda: True))
    stream, _, _ = app.routes["/video_feed"](None)
    with pytest.raises(StopIteration):
        next(stream)
    assert "invalid_jpeg" in capsys.readouterr().out
