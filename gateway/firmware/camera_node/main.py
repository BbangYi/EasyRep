"""HabitatOS DFR1172 camera node; private identity/Wi-Fi live in config.json.

Uses the DFRobot ESP32-P4 MicroPython camera and supplied Microdot API.
One Pi reader consumes /video_feed. Query /identity before opening the stream:
the supplied Microdot server is synchronous on this MicroPython build.
No sensor, actuator, IR, reconstruction or inference control is performed here.
"""
import gc
import json
import time

from microdot import Microdot


IDENTITY_FIELDS = ("site_id", "gateway_id", "cage_id", "camera_id", "view")
CONFIG_FIELDS = IDENTITY_FIELDS + ("schema_version", "wifi_ssid", "wifi_password")
IDENTIFIER_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(CONFIG_FIELDS):
        raise ValueError("invalid camera configuration fields")
    if not isinstance(config["schema_version"], int) or isinstance(config["schema_version"], bool) or config["schema_version"] != 1:
        raise ValueError("unsupported camera configuration version")
    for key in IDENTITY_FIELDS[:-1]:
        value = config[key]
        if (not isinstance(value, str) or not 1 <= len(value) <= 64
                or any(character not in IDENTIFIER_CHARACTERS for character in value)):
            raise ValueError("invalid camera identity")
    if config["view"] not in ("top", "front"):
        raise ValueError("camera view must be top or front")
    ssid = config["wifi_ssid"]
    password = config["wifi_password"]
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("invalid Wi-Fi SSID length")
    if not isinstance(password, str):
        raise ValueError("invalid Wi-Fi password")
    encoded_length = len(password.encode("utf-8"))
    hex_key = encoded_length == 64 and all(c in "0123456789abcdefABCDEF" for c in password)
    if not (8 <= encoded_length <= 63 or hex_key):
        raise ValueError("invalid Wi-Fi password length")
    if "\x00" in ssid or "\x00" in password:
        raise ValueError("invalid Wi-Fi configuration")
    return config


def load_config(path="config.json"):
    with open(path) as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("camera configuration is too large")
    return validate_config(json.loads(data))


def connect_wifi(config, wlan, attempts=3, timeout_s=15):
    """Bound each association wait; never print credentials or exception contents."""
    wlan.active(True)
    try:
        previous_pm = wlan.config("pm")
        wlan.config(pm=wlan.PM_NONE)
        current_pm = wlan.config("pm")
        if type(previous_pm) is int and type(current_pm) is int:
            print("CAMERA_WIFI pm={} previous={}".format(current_pm, previous_pm))
        else:
            print("CAMERA_WIFI pm_unavailable")
    except (OSError, ValueError, AttributeError):
        print("CAMERA_WIFI pm_unavailable")
    for attempt in range(1, attempts + 1):
        if wlan.isconnected():
            return True
        print("CAMERA_WIFI connecting attempt={}".format(attempt))
        try:
            wlan.connect(config["wifi_ssid"], config["wifi_password"])
            started = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), started) < timeout_s * 1000:
                if wlan.isconnected():
                    return True
                time.sleep_ms(250)
        except Exception:
            print("CAMERA_WIFI connection_error")
        try:
            wlan.disconnect()
        except Exception:
            pass
    print("CAMERA_WIFI unavailable")
    return False


def create_app(config, camera, wlan):
    app = Microdot()
    identity = {key: config[key] for key in IDENTITY_FIELDS}
    identity.update(schema_version=1, device_type="dfr1172_camera", stream_path="/video_feed")

    @app.route("/identity")
    def get_identity(request):
        return identity, 200, {"Cache-Control": "no-store"}

    @app.route("/")
    def index(request):
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<title>HabitatOS camera</title></head><body><h1>"
                + config["cage_id"] + " / " + config["view"].upper()
                + "</h1><img src='/video_feed' style='max-width:100%'></body></html>"), 200, {
                    "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}

    @app.route("/video_feed")
    def video_feed(request):
        def stream():
            while wlan.isconnected():
                try:
                    frame = camera.capture()
                    if not frame or frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
                        print("CAMERA_FRAME invalid_jpeg")
                        return
                except Exception:
                    print("CAMERA_FRAME capture_failed")
                    return
                yield ("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {}\r\n\r\n"
                       .format(len(frame))).encode()
                yield frame
                yield b"\r\n"
                gc.collect()
                time.sleep_ms(100)
            print("CAMERA_WIFI stream_disconnected")

        return stream(), 200, {"Content-Type": "multipart/x-mixed-replace; boundary=frame",
                              "Cache-Control": "no-store"}

    return app


def main():
    try:
        config = load_config()
    except Exception:
        print("CAMERA_ERROR config_invalid")
        return
    import camera
    import jpeg  # DFRobot camera example loads the firmware's JPEG module.
    import network
    wlan = network.WLAN(network.STA_IF)
    while not connect_wifi(config, wlan):
        print("CAMERA_WIFI retry_in_s=10")
        time.sleep(10)
    try:
        camera.init()
    except Exception:
        print("CAMERA_ERROR camera_init_failed")
        return
    print("CAMERA_READY camera_id={} view={} ip={} port=5000".format(
        config["camera_id"], config["view"], wlan.ifconfig()[0]))
    try:
        create_app(config, camera, wlan).run(host="0.0.0.0", port=5000, debug=False)
    except Exception:
        print("CAMERA_ERROR server_stopped")
    finally:
        camera.deinit()


if __name__ == "__main__":
    main()
