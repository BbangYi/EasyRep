# HabitatOS Store Gateway — 0.4.29

This directory contains the shared Pi gateway, cage-controller firmware and
camera firmware used by EasyRep. Run its commands from `gateway/`; the existing
SaaS application remains in `../web/` with its own dependencies and deployment.
Each store uses the same versioned source with private site/device configuration.
The Pi, SaaS host and GPU worker are separate services.
Use separate Python environments for `gateway/` and `web/server/`; both contain
an unrelated package named `habitat`, so do not install them into one interpreter.

## Source map

| Path | Responsibility |
|---|---|
| `habitat_gateway/` | Existing gateway entrypoint, MQTT ingestion, local persistence and camera UI |
| `habitat/vision/`, `habitat/saas/` | Camera discovery/capture and versioned SaaS media contracts |
| `habitat/control/`, `apps/worker/ir_*.py` | IR control worker and command client |
| `firmware/cage_node/` | Shared classic ESP32 sensor/IR firmware; no per-cage source copies |
| `firmware/camera_node/main.py` | Legacy DFR1172 MicroPython JPEG camera application |
| `firmware/camera_node/h264_node/` | Native DFR1172 P4 H264 firmware, build tools and pinned dependencies |
| `deploy/` | Release packaging, installation and explicit device provisioning |
| `configs/`, `config/` | Public examples, schemas and simulation configuration |
| `habitat/compute/`, `habitat/gpu/`, `apps/api/` | Existing external GPU service boundary; not a GPU service on the Pi |
| `experiments/environment_sim/` | Three runtime modules/configuration required by existing packaging; no weights |
| `tests/`, `docs/` | Repeatable checks, protocols and selected operational/design documentation |

## Verification status at import

The imported Python project version is **0.4.29**. On the reviewed installation,
FRONT uses native H264 and Pi stream copy, while TOP (`RGB-001`) remains on the
legacy camera firmware after a native capture timeout. Native H264 is therefore
not approved as a universal replacement for every installed board. The Pi accepts
both registered transports. Camera position comes from device registration, not
USB discovery order. No firmware upload, IR operation or service restart is part
of importing this source into EasyRep.

IR software, MQTT permissions and the local worker are included. Physical output
still requires the correct commissioned BB6 configuration and wiring. Historical
hardware records describe observations at their stated dates; they are not proof
of the current wiring or a new installation. Pumps and the R15 expansion must not
be assumed commissioned. Thermal calculations are engineering assumptions rather
than measured husbandry limits.

## Local verification

Use Python 3.11+ and a separate virtual environment. `requirements.lock` pins the
Pi runtime; the API/GPU lock files are separate environments.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[test,simulation]' --no-deps
.venv/bin/python -m pip install 'pytest>=8,<10' 'jsonschema>=4.23,<5' 'numpy>=2,<3'
.venv/bin/python -m habitat_gateway --config config/simulation.toml --check-config
.venv/bin/python -B -m pytest -q -p no:cacheprovider
python3 -B tests/hardware/check_cage_node.py
```

The final command needs a host C++ compiler and checks firmware logic with mocks.
It does not validate physical sensors or outputs. FFmpeg, a C++ compiler, cJSON
headers/library and Chromium are optional prerequisites for their corresponding
media/firmware/browser tests; see individual test skip messages.

## Board builds and deployment

- [BB6 public-example compilation](firmware/cage_node/README.md) checks the pinned
  toolchain and compiles placeholder configuration with physical outputs locked.
- [Native P4 build](firmware/camera_node/h264_node/README.md) keeps SDK/cache and
  generated binaries outside source. Generic firmware is provisioned separately.
- `deploy/camera_node.py` verifies the external manufacturer MicroPython image
  and reviewed Microdot file by hash. Those vendor files are not stored here;
  retain their source package separately. This is not an interpreter-source build.
- [New store setup](docs/operations/new-store-setup.md),
  [IR contract](docs/protocols/ir-control.md),
  [camera/IR API](docs/api/camera-ir-integration.md), and
  [Pi update](docs/operations/pi-update.md) describe their distinct steps.

Build a release on a host matching the target Pi CPU/Python only when deployment
is intended. Source packaging alone does not install or restart a service:

```bash
.venv/bin/python deploy/build_release.py --source-handoff --output /tmp/habitatos-source-release
# Matching-platform offline wheel bundle, when an actual deployment is required:
.venv/bin/python deploy/build_release.py
```

Production configuration stays outside source, currently under
`/etc/habitat-gateway/` and per-user `.config/habitatos/` paths. Keep Wi-Fi/MQTT
credentials, API/IR tokens, TLS private keys, per-node `config.h`/`config.json`,
full flash backups and credential-bearing binaries out of Git. Examples retain
placeholders. Model weights, videos, databases, caches and release artifacts are
not source inputs.

This import preserves existing relative paths and package boundaries. The old
`First_Connection_R1` 8092 receiver, dated handoff copies and installed
`/opt/habitat-gateway/current` are not additional canonical sources. Hardware
text tables and thermal sizing sources are included; historical office/archive
attachments and editable Fritzing binaries are not included in this code import.
Historical documentation may reference excluded `var/reports/` evidence or
external tools/attachments that were already absent from the source snapshot.
Those links are historical provenance, not files supplied by this repository;
use the current build entrypoints above for reproducible source checks.
