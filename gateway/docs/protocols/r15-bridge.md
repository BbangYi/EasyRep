# R15 N1 request bridge, protocol 1

Status (2026-10-07): the 5000ms ESP request limit and separate GPU request/RUN
contract are implemented in source 0.4.14. Both ESP32 target roles compiled with
request outputs locked. The Pi gateway and GPU service use the same source;
360 actual CUDA responses and 75 virtual pump runs completed in the schema 2
integration fixture. The independent Pico RUN limit remains 3000ms. These software
checks do not prove physical timing or delivery. No ESP/Pico flash, wiring,
electrical timing or water-flow validation has been performed. The original R15 ZIP and Pico BENCH
firmware remain unchanged. `HYDRAULIC_COMMISSIONED=0` still prevents Pico load outputs.

Evidence: [Linux and isolated MQTT checks](../../var/reports/commissioning/software-r15-20261007-checks.json),
[ESP32 target builds](../../var/reports/commissioning/esp32-target-build-20261007.json),
[Pi–GPU virtual integration](../../var/reports/commissioning/software-r15-20261007-integration.json).

The existing N1 sensor sketch can additionally serve as the central request bridge.
Private `config.h` opts in with `HABITAT_R15_CENTRAL=1`.
`HABITAT_R15_REQUEST_OUTPUTS` defaults to **0** independently: all three request lines
remain LOW. Enabling the role alone does not enable requests or commission hardware.
Other cage nodes keep both options at zero. This is one shared firmware, not a copy
per store. Existing sensor telemetry contains no invented actuator observations.

## Existing hardware contract

Source: supplied ZIP `outputs/HabitatOS_R15_PCB_배선_예산_합격기준.pdf`, page 3,
and `circuit/r15_safety_pin_netlist.json`. No new UART or PCB connection is introduced.

| N1 GPIO | J112 | Direction / meaning |
|---|---|---|
| 25 / 32 / 23 | 4 / 5 / 6 | ESP output: REQ1 / REQ2 / REQ3 |
| 26 | 7 | ESP output: heartbeat |
| 19 / 33 | 8 / 9 | ESP input: raw ARMED / LEVEL pin level |
| GND | 3 | SAFE_GND reference |
| none | 1 / 2 | NC; no power wires |

Inputs use ESP-domain internal pull-ups. Their adequacy with the actual cable and
interference remains an electrical test item; no second 3.3V supply is tied to Pico.
U124/U125 are open-drain: HIGH also occurs when SAFE is unpowered or the line is
open. A HIGH reading therefore **does not prove ARM, health, successful execution,
or a powered Pico**. A LOW inhibits/removes requests. Firmware never drives ARM.

The existing Pico uses 20ms request qualification, 1000ms preopen, up to 3000ms RUN,
1000ms drain and a 1000ms ESP-heartbeat timeout. These are design values, not measured
hydraulic values. `request_hold_ms` below is the duration of the ESP request signal,
**not a promise of pump RUN time or delivered water**. No guessed preopen compensation
is added. A 7000ms bridge cycle guard exceeds the documented preopen plus modelled
5.2054s maximum hardware window; it does not replace measured hydraulic cooldown.

### Native ESP/Pico source check (2026-10-06)

`tests/hardware/check_cage_node.py --r15-archive <reviewed-original.zip>` optionally
compiles the actual ESP request header with the original ZIP's `sequencer.c` and
`host_bridge.c`. The archive and four reviewed source hashes are verified before
use; extracted sources and binaries are temporary. The factory BENCH mode is tested
as output-locked. An explicit host-only commissioning override exercises the
sequencer; it does not alter the ZIP, firmware settings, UF2 or any device.

Sixteen coupled scenarios passed with 1ms virtual Pico ticks, 20ms ESP task ticks
and an ideal 5000ms external WINDOW. For ON received at 400ms, REQ first rises at
420ms and qualifies into PREOPEN at 440ms. With 2000/3000ms holds, TRIG is at 1440ms
and the fixture raises WINDOW at 1441ms. REQ falls at 2400/3400ms; the original RUN
state then enters DRAIN. The resulting virtual pump intervals are 959/1959ms. A
1000ms hold falls during PREOPEN and never enters RUN. A separate stuck-HIGH REQ
wire scenario confirms the native 3000ms RUN maximum. These concrete fixture
values are not physical timing bounds, a calibration or a measured flow rate.

The earlier GPU comparison uses desired virtual pump RUN seconds; mapped R15 API
`duration_s` uses REQ hold seconds. Equal numbers do not make those two operations
equivalent. This earlier check did not validate a conversion between them. The
request/RUN forward fixture below was subsequently verified in software on
2026-10-07; actual RUN/execution feedback remains a commissioning requirement.
Synthetic forecasts remain unable to drive physical outputs. Main/SDK execution,
the analogue WINDOW circuit, real GPIO scheduling and hydraulics are not tested.
See the [native-source log](../../var/reports/commissioning/software-r15-20261006-native-esp-pico.log).

### Request/RUN revision (source check 2026-10-06; integration 2026-10-07)

The original Pico `run_max_ms=3000` remains unchanged. The revision raises only
the limit introduced by our ESP request bridge, from 3000ms to 5000ms. It does not
increase pump RUN to five seconds, change the supplied Pico firmware, or enable
physical outputs. A new host run of `tests/hardware/check_cage_node.py
--r15-archive <reviewed-original.zip>` passed 59 protocol, 2 GPIO-task, 1 hello,
12 sensor and 123 coupled native-source cases (exit 0). The original ZIP remained
unchanged, and the temporary compilation files were removed. This is a new host
check; the sixteen scenarios above and the ESP32 target build below are older
evidence for the three-second request limit.

The new native oracle swept receipt phases 0..19 on the 20ms ESP task grid. With
the fixture's 1ms WINDOW response, 2000/3000/4000ms REQ produced respectively
959–979/1959–1979/2959–2979ms of virtual RUN; 4500/5000ms REQ produced 3000ms in
every tested phase. The phase-0 values are 959/1959/2959/3000/3000ms. These are
source-level fixture results, not measured GPIO or pump timing. On 2026-10-07,
both revised ESP32 target roles compiled with request outputs disabled, and the
same-source 0.4.14 Pi/GPU schema-2 integration completed. Device flashing and
physical commissioning remain pending; compilation is not device deployment.

Command TTL remains at most 5000ms and is an **admission deadline**: it determines
whether a newly received command is fresh enough to accept. It is not the REQ
hold duration or the pump RUN duration. The accepted request uses its local hold
timer and remains subject to OFF/STOP, status inhibition and lease loss. Gateway
heartbeat freshness remains 1000ms and the bridge recycle guard remains 7000ms;
the request-limit revision does not extend either protection.

The revised GPU contract separates request duration from expected virtual RUN:

| GPU contract | Timing meaning |
|---|---|
| `schema_version=1`, `timing_mode=desired_run_ideal` | Historical ideal-RUN simulation; a requested virtual RUN is applied directly. It is not an ESP request plan. |
| `schema_version=2`, `timing_mode=r15_request_fixture` | An ESP request plan is evaluated through the source-checked timing fixture before the environment model sees its expected virtual RUN. |

Schema 2 uses `timing_profile=r15_esp20_pico_window1ms_phase0_v1`. Its
`selected_plan.request_hold_ms` contains exactly 60 integer values in `0..5000`
(zero means no request), and `selected_plan.expected_virtual_run_s` contains
exactly 60 finite values in `0..3`. Positive request candidates are
`[2000, 3000, 4000, 4500, 5000]`ms. Each candidate request plan is forward-mapped
through the fixture; the resulting RUN plan, not the REQ plan, is supplied to the
learned environment model. This is not an inverse formula that adds a fixed
preopen allowance to the desired RUN.

`misting_proposal.request_hold_ms` and `misting_proposal.expected_virtual_run_s`
must equal the first entries of their selected-plan arrays. In schema 2 the
legacy `misting_proposal.pulse_seconds` must also equal that first expected RUN;
it must never be used as the request hold. Every expected RUN must also respect
the proposal's declared `max_pulse_seconds`. Validation must reject wrong lengths,
non-integer request holds, non-finite or out-of-range values, inconsistent first
entries, unknown timing profiles and a RUN plan that differs from the fixture's
forward result. The API-schema change does not change the `R15/1` ASCII wire
frame or the MQTT hello/ACK `schema_version=1`.

Observed history aggregates elapsed RUN intervals from the relevant execution
source, never requested hold seconds or future expected RUN. Fixture executions
remain tagged as virtual and cannot become measured physical history. The
schema-2 implementation and end-to-end software checks completed on 2026-10-07,
using 360 actual CUDA responses and 75 virtual executions. The old schema-1
Pi/GPU evidence remains separate from that result. Environment
responses remain `field_validated=false` and `hardware_execution_allowed=false`.

The expected RUN is conditional on the fixture's Pico readiness, heartbeat,
WINDOW response and clock/task timing. The named profile fixes the request
phase to 0 on the 20ms ESP task grid and WINDOW response to 1ms; request phases
0..19 may produce different RUN durations and are separate oracle cases, not
alternative names for the phase-0 prediction. RUN can reach its 3000ms limit
while REQ is still HIGH; the later REQ-LOW event must remain separate from pump
stop and drain completion. Raw ARMED/LEVEL HIGH does not establish
those conditions on hardware: power loss or an open line can also read HIGH.
Expected RUN is neither execution feedback nor a calibrated water dose.

The revised ESP hello advertises `max_request_hold_ms=5000`. The Pi uses a strict
integer capability in `1..5000`; a hello without this field defaults to 3000 for
old firmware. Before publication, the Pi rejects a hold exceeding the observed
node capability as `r15_request_hold_unsupported_by_node`. Deploying the Pi
first therefore does not grant an old ESP five-second requests. Old ESP firmware
also rejects an ON hold above 3000ms. A revised Pi/GPU must not treat
that rejection, a parse failure or a missing ACK as successful execution, silently
clamp the hold, or retry ON with a fresh identity. Existing three-second test and
target-build evidence does not establish that the five-second revision is deployed
to a physical ESP32. The 2026-10-07 target build also was not flashed.
Physical commissioning still requires actual REQ/HB/WINDOW/RUN traces, loss and
STOP behavior, pump/valve timing, delivered volume and enclosure response. All
output locks, the original ZIP and physical-test count of zero remain unchanged.

## MQTT scope and fresh session

`BASE` is the N1 private `TOPIC_BASE`, currently the existing sensor-node pattern:
`habitat/v1/{site_id}/cages/{central_cage_id}/nodes/{central_node_id}`.
Gateway configuration must explicitly map zone 1/2/3 to cage and actuator IDs.
List order is not a physical wiring map. Only the authenticated configured central
node may publish its hello/ACK; only the authorised store gateway may send commands.
Broker TLS certificate validation and per-node topic ACLs remain required.

- ESP publishes `BASE/r15/hello` every 500ms, **retain=false**.
- On every MQTT connection ESP creates a random UUID session and subscribes only to
  `BASE/r15/command/{session_id}` (QoS 1, clean session).
- ESP publishes `BASE/r15/ack`, **retain=false**. PubSubClient publishes QoS 0, so
  hello/ACK delivery is not guaranteed. Lost ACK must not cause a fresh ON.
- Gateway sends all command/heartbeat publications with **retain=false**, QoS 1.
  It rejects retained hello/ACK and stale sessions before changing command state.
- PubSubClient does not expose the incoming RETAIN bit. A new unpredictable topic
  plus payload session prevents an old retained command from executing after a
  reconnect. This is not a claim that the ESP inspects that bit. Broker policy and
  gateway non-retained publication complete the retention contract.
- A gateway restart must obtain a fresh ESP session before sending new ON requests;
  it must not guess the sequence from a previously observed hello. Reconnecting the
  ESP changes session and clears old wire requests. No persisted command is replayed.

Hello fields:

```json
{"schema_version":1,"session_id":"11111111-1111-4111-8111-111111111111","command_topic":"BASE/r15/command/11111111-1111-4111-8111-111111111111","outputs_locked":true,"max_request_hold_ms":5000,"request_mask":0,"active_command_id":"","gateway_lease_valid":false,"stop_latched":false,"heartbeat_output":false,"status_pin_levels":{"armed":true,"level":true},"execution_status":"unverified","actual_state":null,"observed_at_ms":1800000000000}
```

These raw levels are illustrative protocol values, not device measurements.
Gateway validates the topic against its configured BASE and the UUID, rather than
publishing to an arbitrary `command_topic` supplied by a message.

## Pi adapter configuration and recovery

`Settings.r15_bridge` defaults to `enabled=false`, `outputs_locked=true`, no central
node and no mappings. To configure the route, select an existing `central_cage_id`
(its `node_id` determines the authenticated MQTT namespace) and explicitly list
`zones=[{zone:1..3,cage_id,actuator_id}, ...]`. Cage/actuator pairs and zone numbers
must each be unique and must reference existing configuration. Array position is
never used as a zone. No production mapping or output lock is changed automatically.
`hardware_outputs_enabled`, the Pi bridge lock, the ESP request-output flag and the
Pico BENCH interlock are separate; configuring MQTT is not hardware commissioning.

The Pi control worker calls `step()` every 250ms when the bridge is enabled. The
adapter sends a fresh heartbeat every 500ms, expiring after 1000ms. It stops sending
heartbeats when the worker is unhealthy, hello is stale or STOP has been requested.
This does not guarantee scheduling latency; the ESP/Pico must enforce their timers.

The existing SQLite database records seen ESP sessions. After Pi process restart
or broker reconnection, a previously seen session cannot resume ON or heartbeat.
A new session must first report no active request and no gateway lease, and the Pi
must then see its heartbeat lease reflected in a fresh hello before considering ON.
The Pi does not reboot or reconnect ESP automatically to clear this gate. An observed
current session remains usable for fail-OFF/STOP even when it cannot be used for ON.
Sequence allocation is in memory under the gateway lock; no session is resumed after
restart, so 500ms heartbeats do not require repeated database counter writes.

Before publishing, the Pi persists the exact wire payload, session, sequence, zone
and request duration with the command. A repeated API request ID returns that stored
result; it never publishes a new ON or extends an expiry. An uncertain publication
remains `interrupted` with its lease reserved. Broker QoS retransmission may resend
the original packet; ESP payload binding and deadlines still apply.

The 0.4.14 API `duration_s` is bounded to 0.001..5 seconds for mapped ON and converted down to
whole milliseconds for `request_hold_ms`, subject to the node capability. This preserves the request plan, not an
assertion of equal Pico RUN time. Command TTL is capped at 5 seconds. For shared
station reservation the Pi conservatively uses command expiry plus the 7-second
cycle guard, and also retains the actuator's configured cooldown.
The earlier 0.001..3-second request limit is retained for a node whose hello does
not advertise the revised capability. The 2026-10-07 Linux/MQTT checks cover both
capabilities and reject an unsupported hold before publication.

A normal active request or shared-station reservation blocks admission of an
**additional ON**. It is not itself an unsafe condition for the request that owns
the reservation. The 250ms `step()` → `tick()` safety check must not cancel that
request merely because its own station/actuator is busy. New-command admission
checks remain separate from the ongoing safety check. Stale/invalid sensors, LOW
status inputs, session/lease loss, disconnection and STOP remain stop conditions;
request deadlines and cooldown/reservation limits are not extended by this distinction.

**A `/stop` request for any mapped enclosure sends station-wide `stop` (zone 0):
it may interrupt another enclosure's active shared misting cycle.** Ordinary OFF
uses only its mapped zone. Station STOP switches all mapped enclosures to manual
mode so another enclosure's automatic policy cannot resume after reconnection.
STOP disables Pi heartbeats immediately; shutdown also
makes one best-effort STOP publication. Network delivery is never assumed successful.

The Pi accepts R15 ACKs only from the configured central node topic and only when
session, command ID, wire sequence, zone and hold match the persisted delivery.
`requested` and `execution_unverified` never call the actuator-observation store;
generic node ACK/telemetry cannot populate physical state for mapped R15 targets.
Their displayed observation is always unknown, including when old database history
contains a state from another transport. These statuses still reserve ON leases.
New status/metadata support is required in any SaaS event consumer before enabling
their upload; they must never be relabelled `applied` for schema compatibility.

Offline adapter checks: `pytest -q tests/test_r15_bridge.py tests/test_mqtt.py
tests/test_control.py`. They use synthetic protocol packets and mocked MQTT, not an
ESP connection, electrical measurements or proof of water flow.

## Bounded command frame

UTF-8/ASCII payload, at most 256 bytes, exactly nine fields separated by one ASCII
space, no newline or trailing whitespace:

```text
R15/1 SESSION_UUID COMMAND_UUID SEQUENCE ZONE ACTION REQUEST_HOLD_MS ISSUED_AT_MS EXPIRES_AT_MS
```

- UUIDs: canonical 36-character lowercase hexadecimal with hyphens.
- Sequence: integer 1..4294967295, strictly increasing across commands **and**
  heartbeats within the session. Session and sequence allocation are serialised on
  the gateway. Do not reuse a live session counter after gateway restart.
- Zone: `1`, `2`, `3` for `on`/`off`; `0` for `stop`/`heartbeat`.
- Actions: `on`, `off`, `stop`, `heartbeat` only; no ARM/unlock command exists.
- Hold: `1..5000`ms for ON in the revised bridge; old firmware retains
  `1..3000`ms, and the Pi enforces the observed node capability. Zero
  otherwise. No signs, decimals or leading zeros.
- Times: integer Unix UTC milliseconds, at most 9007199254740991.
  ON/heartbeat require valid ESP time, issued <= now < expiry, positive TTL <=5000ms.
  Commands issued in the future are rejected; clock tolerance does not extend TTL.
- Heartbeat: fresh command UUID/sequence every 500ms, suggested TTL 1000ms. Its age
  must be <1000ms. Lease is at most the remaining TTL and at most 1000ms.
  Duplicate/reordered packets never extend the lease.
- ON requires fresh gateway heartbeat, no active request, cycle guard elapsed,
  unlocked request outputs and both status inputs HIGH (inhibit check only).
- OFF removes the addressed active request. STOP removes every request and latches
  heartbeat OFF until a new ESP MQTT connection. The bridge never sends ARM. Pico's
  existing physical-button ARM procedure still applies after it disarms. A rapid
  reconnect can precede Pico's heartbeat timeout, so disarm is not inferred from STOP
  or MQTT reconnection. The cycle guard survives MQTT reconnects within the ESP boot.
- Current-session, syntactically valid OFF/STOP acts even with expired time, invalid
  UTC or an older sequence. The sequence high-water mark never moves backwards.
  Wrong-session messages are rejected. Local physical STOP is independent of MQTT.

Recent command IDs (including heartbeats) have a bounded 16-entry payload-bound duplicate cache; the
session-wide monotonic sequence remains the replay barrier after eviction. A
duplicate gets its recorded result without extending a request or lease. Reusing
an ID with changed fields is rejected while cached. The gateway retains permanent
request-ID deduplication and, if inspecting delivery, resends only the exact same
frame. It must never create a new ID/sequence/expiry to retry an ambiguous ON.

## Receipt is not execution confirmation

```json
{"schema_version":1,"session_id":"11111111-1111-4111-8111-111111111111","command_id":"22222222-2222-4222-8222-222222222222","sequence":2,"zone":1,"status":"requested","reason":"physical_execution_unverified","requested_state":true,"duplicate":false,"request_hold_ms":500,"execution_status":"unverified","actual_state":null,"observed_at_ms":1800000000000}
```

- `requested`: ESP accepted a request-line change, not evidence of Pico acceptance
  or a pump/valve switching. GPIO task applies it within its next scheduled tick.
- `rejected`: no ON was accepted; reason specifies lock, expired command, busy,
  stale sequence, conflicting ID, missing lease or LOW status input.
- `execution_unverified`: previous ON request was removed by hold deadline,
  OFF/STOP, status LOW or connection/lease loss. Physical execution remains unknown.
- Heartbeat receipt is reflected in hello; it normally has no separate ACK.
- `requested_state` is the recorded request outcome; duplicate ACK is historical.
  `request_mask` in a fresh hello describes the bridge's current software request.
  Neither is physical actuator feedback. `actual_state` is always null.

An OFF command acknowledged as `requested` confirms only acceptance of request
removal; it does not confirm physical pump/valve OFF. Likewise,
`execution_unverified` after OFF/STOP is not a physical-OFF observation.
`requested_state=false` must still retain `actual_state=null`.

An independent 20ms FreeRTOS safety task clears request pins on deadline/link loss
while TLS, MQTT or sensor operations block the main loop. It changes the heartbeat
only with a fresh gateway lease. GPIO updates share the command-state critical section,
so STOP cannot be followed by a stale GPIO snapshot. Output latches are set LOW before
enabling output drivers. This is software scheduling design, not measured
worst-case latency. Pico's independent protection is unchanged. The gateway must
keep actual actuator observations unknown and must reserve uncertain ON leases and
cooldown; an unverified ACK must not bypass those protections.

Host verification: `python -B tests/hardware/check_cage_node.py` compiles the actual
bridge and sensor functions using an existing C++ compiler. It does not establish
an ESP32 target build, deployment, electrical operation or commissioning.

Separate target verification on 2026-10-05: both `HABITAT_R15_CENTRAL=0` and `=1`
compiled successfully for `esp32:esp32:esp32`, each with
`HABITAT_R15_REQUEST_OUTPUTS=0`. Arduino CLI 1.5.1, ESP32 core 3.3.12,
PubSubClient 2.8.0, Adafruit SHT31 2.2.2, Adafruit BusIO 1.17.4 and OneWire 2.3.8
were pinned. Program storage was 1,049,497 / 1,056,365 bytes; global RAM was
50,556 / 53,188 bytes (sensor / central). The first build reported upstream
OneWire/ESP GPIO unsigned-comparison warnings; no firmware source changes were
needed for successful compilation. This is not an uploaded or operated device.
The isolated Pi toolchain and binaries were removed. Source hashes and build results
are in `var/reports/commissioning/esp32-target-build-20261005.json` (runtime evidence).

GPIO implementation references: [Espressif GPIO API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html)
and [Arduino ESP32 GPIO API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/gpio.html).
These define the software API; boot-time pin voltage still requires physical measurement.
