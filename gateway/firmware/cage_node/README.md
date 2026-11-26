# BB6 cage controller

One shared classic ESP32 sketch reads SHT31 and two DS18B20 probes. The reviewed
BB6 IR option uses GPIO4; the camera boards are separate ESP32-P4 devices. Pin,
identity, Wi-Fi and MQTT differences belong in a private per-node configuration.
Pump outputs remain disabled. See [IR protocol](../../docs/protocols/ir-control.md)
and [hardware commissioning](../../docs/operations/hardware-arrival.md).

## Repeatable example compilation

`dependencies.lock.json` records the tested CLI versions, exact core/library
versions and classic ESP32 board options. Install these dependencies in a separate
Arduino toolchain beforehand; the helper performs no downloads or USB access:

```bash
arduino-cli core install esp32:esp32@3.3.12
arduino-cli lib install 'Adafruit SHT31 Library@2.2.2' 'Adafruit BusIO@1.17.4' \
  'OneWire@2.3.8' 'PubSubClient@2.8'
python3 firmware/cage_node/build.py --profile sensor --output /tmp/bb6-sensor-build
python3 firmware/cage_node/build.py --profile ir-locked --output /tmp/bb6-ir-build
```

Run from `gateway/`. Arduino CLI 1.5.1 was used in the recorded sensor commissioning;
1.5.2-rc.1 is also supported by this helper. Add the official Espressif board index
to the Arduino CLI configuration when installing its core on a clean machine.
These are version pins, not a claim of bit-for-bit identical builds across host
OSes or cryptographically verified toolchain downloads.

The helper copies only public source and `config.example.h` into a temporary
sketch. It **never reads the adjacent private `config.h`**. `ir-locked` compiles
the IR protocol with physical outputs still disabled. Generated binaries contain
placeholder connection settings, are marked `deployable: false`, and must not be
uploaded to an installed node. A build manifest records output hashes and the
selected toolchain. Existing output directories are not overwritten.

Real commissioning remains a separate, explicit operation: preserve the existing
private configuration and rollback image, verify the board identity and wiring,
then build in a private staging directory. Keep configuration and those binaries
outside this repository. The repository contains no upload helper for this step.
