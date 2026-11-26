# DFR1172 native H.264 camera node

This is the native successor to `../main.py`. It runs on DFRobot FireBeetle 2
ESP32-P4 DFR1172 with silicon **before revision 3.00**, 16 MB flash and PSRAM,
an OV5647 CSI sensor, and the onboard ESP32-C6 Wi-Fi coprocessor. It does not
change any cage sensor, pump, or IR output. Existing MicroPython files remain
available for rollback; this firmware changes the P4 application and partition
layout, so back up the **whole flash and private config before installation**.

## Pipeline and contract

`OV5647 → P4 ISP packed YUV420 → P4 hardware H.264 → RTSP/TCP → Pi stream copy`

The pinned Arduino SDK enables OV5647 **800 × 800**, sensor capture at 50 fps.
The capture task drains that input continuously and encodes 20 fps at a target
2,000,000 bit/s, Baseline profile, GOP 20. It does not upscale or claim 1080p.
The hardware encoder prepends SPS/PPS at each IDR. The firmware checks those NAL
types and Baseline profile before advertising readiness. Actual optical quality,
Wi-Fi throughput, and timing must still be measured on the installed unit.

CSI output explicitly requests **limited-range BT.601 YUV** and verifies the
negotiated format. The SDK's default is full-range YUV while this hardware
encoder does not set SPS video-signal metadata; ordinary players interpret it
as limited range. In the first hardware capture, 98.6% of decoded luma samples
were below code 16 and therefore displayed as black. The explicit ISP range
conversion corrects that mismatch before H.264 encoding. It does not establish
adequate scene illumination or optical IR sensitivity. The encoder API does not
expose a VUI color-matrix setting; consumers should retain the documented BT.601
matrix instead of inferring a matrix solely from image dimensions.

Two encoded frames are the maximum queue. If the reader falls behind, the queue
is cleared and the producer waits for an IDR; it does not resume at a dependent
P-frame. The video consumer never blocks camera capture. HTTP identity remains
separate from the RTSP connection. A separate bounded latest-IDR cache supplies
SPS/PPS when RTSP DESCRIBE requests codec data before PLAY.

- HTTP `:5000/identity`: public identity schema 2, only available with HTTP 200
  after the sensor probe, negotiated format, and encoded IDR succeed. Otherwise
  HTTP 503. Existing site/gateway/cage/camera/view/device_type values are retained.
- RTSP TCP `:8554/stream`: H.264; no JPEG conversion on the Pi.
- HTTP `:5000/health`: ready/frame/drop/error counters, no credentials.
- Wi-Fi reconnect and IP change restart the RTSP listener on the new address.
- The Pi must verify the H.264 SPS dimensions and actual stream before updating
  the registered camera dimensions. This migration changes 800×640 to 800×800.

Public identity additions are `stream_transport: "rtsp_tcp"`, `codec: "h264"`,
`stream_port: 8554`, `stream_path: "/stream"`, `width: 800`, `height: 800`,
`fps: 20`, `bitrate_bps: 2000000`, `gop_frames: 20`, `profile: "baseline"`,
`sps_pps_at_idr: true`, `color_range: "limited"`, `color_matrix: "bt601"`.
The color fields attest to the verified CSI output settings; the Pi may label
the matching H.264 SPS color metadata during stream copy, without decoding or
changing encoded picture slices. Discovery must derive the URL from the probed host, not
accept arbitrary URLs from a device. Camera transport is local to the store LAN;
existing Gateway/SaaS authentication remains the external access boundary.

## Reproducible build

Install Arduino CLI and the **Espressif Arduino ESP32 core 3.3.12**. This includes
IDF v5.5.5, esp_video 2.4.1, esp_cam_sensor 2.4.0, and esp_h264 1.3.8.
The DFRobot variant configures C6 SDIO pins 14–19 and reset 54; the CSI SCCB
pins are SDA 7 / SCL 8. No store-specific pins or credentials are compiled in.

```bash
python3 firmware/camera_node/h264_node/prepare_dependencies.py --cache /tmp/habitat-camera-h264
python3 firmware/camera_node/h264_node/build.py --cache /tmp/habitat-camera-h264
```

The first command downloads only official Espressif `esp-adf-libs` at the commit
in `dependencies.lock.json`, verifies each pinned Git blob ID, and retains its
license files. The build is then offline and rechecks cached dependencies.
`esp_media_protocols` provides the RTSP server and RTP packetization;
`media_lib_sal` is compiled from the same commit. No custom RTP implementation
or dependency binary is stored in Git.

The output directory contains `flash-manifest.json` with hashes and offsets:
bootloader `0x2000`, partitions `0x8000`, OTA selection `0xe000`, app `0x10000`.
The build never opens USB or uploads. Use the manifest, verify the actual chip
and USB serial, and retain a tested full-flash rollback before a controlled
installation. Do not use the revision-3-only ESP-VISION prebuilt on revision1.3.

## Private provisioning over USB CDC

At 115200 baud, send one newline-terminated line:

```text
HABITAT_CONFIG {exact existing private schema_version:1 JSON}
```

The JSON fields remain exactly `schema_version`, `site_id`, `gateway_id`,
`cage_id`, `camera_id`, `view`, `wifi_ssid`, `wifi_password`. Maximum 4096 bytes.
Duplicate or unknown keys, invalid IDs and Wi-Fi lengths, and embedded NULs are
rejected. The private configuration is stored in NVS namespace `habitat-camera`,
key `config`; credentials are neither returned nor logged. The firmware is the
same for every store and camera.

Success response: `{"configured":true,"restarting":true}` followed by reboot.
Failure response: `{"configured":false,"error":"config_invalid_or_write_failed"}`.
`HABITAT_STATUS` reports firmware/configured/ready/frames/error without secrets.
Its `imaging` object, also returned by `/health`, reads a fixed set of OV5647
registers only while capture is healthy. `exposure_raw` combines the low four
bits of `0x3500` and bytes `0x3501`/`0x3502`; `gain_raw` combines the low two
bits of `0x350a` and byte `0x350b`. They are raw sensor codes, not measured lux
or exposure time in microseconds. `0x3503` bits 0/1/2 select manual AEC/AGC/VTS;
`0x5001` bit 0 enables sensor AWB and `0x5180` bit 3 selects manual AWB gains.
AE target, gain ceiling and HTS/VTS registers support troubleshooting without
altering exposure. Reads stop on the first error or between reads after 50 ms;
individual bus transactions retain the driver timeout. An unavailable ISP AGC
result does not itself imply disabled sensor AEC: the OV5647 profile uses the
sensor's own auto exposure. No imaging writes are exposed.
There is no network configuration endpoint. Preserve the camera's actual saved
identity even if the USB-connected board is informally called TOP or FRONT.

## Validation and sources

`tests/unit/test_camera_h264_firmware.py` executes the production C++ validation
header against host cJSON. Target build validation is separate from optical and
network hardware acceptance; a successful build does not prove a live picture.

- [Official DFR1172 board documentation](https://wiki.dfrobot.com/dfr1172/)
- [Official Arduino DFR1172 variant](https://github.com/espressif/arduino-esp32/blob/3.3.12/variants/dfrobot_firebeetle2_esp32p4/pins_arduino.h)
- [Espressif esp_video H.264 pixel-format mapping](https://github.com/espressif/esp-video-components/blob/master/esp_video/src/device/esp_video_h264_device.c)
- [Pinned official RTSP and SAL source](https://github.com/espressif/esp-adf-libs/tree/7162d32381d6e1f8c8cba2ee5edcbfe82bc964b1)
- [ESP-VISION silicon support boundary](https://docs.espressif.com/projects/esp-vision/en/latest/esp32p4/target-support/index.html)
