# Local IR lease control

The ESP32 cage node owns GPIO4 and the fail-OFF timer. The Pi CLI requests a
short lease over the existing authenticated TLS MQTT connection. Camera capture,
sensor ingestion and SaaS are independent. `/camera` retains a viewing-only role;
the optional IR controls require a separate control session.
This command does not prove that an IR lamp emitted light; optical confirmation
is a separate commissioning observation.

## Firmware profile

The reviewed 30-pin BB6 profile uses SHT31 SDA/SCL 21/22 and DS18B20 18/19.
IR GPIO4 is supported only with this profile. The existing external 10kΩ
pull-down is required during reset, before firmware runs.

Public defaults disable IR. A private commissioned node config opts in with
`HABITAT_IR_CONTROL=1`, initially `HABITAT_IR_OUTPUTS=0`. Output unlock changes
only the latter to 1 after wiring verification and a locked-output trial.
`HABITAT_R11_PUMP`, `HABITAT_R11_PUMP_OUTPUTS`, and both R15 options stay 0.
This implementation includes no pump module; nonzero pump options are rejected
at compile time. Preserve the node's existing Wi-Fi, broker CA, MQTT credentials,
identity, and sensor settings. Never upload an example credential configuration.

## Wire contract

The base remains the existing sensor topic
`habitat/v1/{site_id}/cages/{cage_id}/nodes/{node_id}` for compatibility.
IR adds three scoped topics without changing sensor telemetry:

| Topic suffix | Publisher | Purpose |
| --- | --- | --- |
| `/ir/hello` | Node | Non-retained schema 1 status and current session |
| `/ir/ack` | Node | Non-retained schema 1 acknowledgement |
| `/ir/command/{session_id}` | Dedicated controller | Non-retained QoS 1 command |

A command contains nine space-separated ASCII fields:

```text
IR/1 session_uuid command_uuid sequence zone action hold_ms issued_ms expires_ms
```

UUIDs are canonical lowercase. Sequences increase within each node session.
`on` and `off` use zone 1; `stop` uses zone 0. The CLI offers status/on/off.
The node generates a fresh session on each MQTT connection and starts OFF.
Duplicates and stale ON sequences cannot renew a lease. A valid current-session
OFF remains effective with an old sequence or unsynchronized clock.

ON requires output unlock, a valid current session, synchronized UTC and an
unexpired command, and a lease of at most 5,000 ms. IR allows the issuing clock
to lead the node by at most 1,000 ms; larger future timestamps are rejected.
This tolerance never extends the expiry deadline or the monotonic lease, which
is capped at the smaller of the requested hold and the remaining validity.
Already-expired commands and a validity interval over 5,000 ms remain rejected.
The existing R15 parser and admission policy are unchanged.
A separate 20 ms RTOS task
checks lease expiry and network state using monotonic time. The cadence is a
code/test target, not a measured physical latency guarantee. Wi-Fi loss,
lease expiry, and a malformed command on the active command topic turn the
requested output OFF. Reconnection does not resume ON.

The CLI renews with a new UUID/sequence each second, requires a live non-retained
hello, and checks matching ON acknowledgements. Exit/error/interruption attempts
OFF; node lease expiry is the fallback if that message cannot arrive.
`gpio_requested_on` reports a requested output. `actual_ir_on` remains null,
and `physical_ir_verified` remains false.

## Installation and credentials

Use the common versioned release and its existing installer in `--user-ir`
mode. This installs the CLI under `~/.local/share/habitatos/ir/current` without
restarting Gateway, Air Viewer, or their camera readers. The release includes
public firmware sources; actual node configuration and backup flash remain
outside source control.

`provision_ir.py` prepares the dedicated account and adds only the three node
rules and matching controller rules to the existing broker ACL. Dry-run is the
default. Applying requires administrator access and rechecks the plan's input
files before changing them; `--expect-state` can pin a prior reviewed state hash.
existing broker credentials and other cages' rules must be preserved. The broker
reloads the files without a restart. The provisioner keeps rollback copies and
never writes passwords into arguments or diagnostic output.

Runtime config and credentials belong in `~/.config/habitatos/ir/{cage_id}/`.
Use the same Unix user for all commands, because the lock and durable sequence
state reside in `~/.local/state/habitat-ir/`. Do not delete sequence files during
a live node session. Concurrent control from another host/user is unsupported.

```bash
~/.local/share/habitatos/ir/current/venv/bin/habitat-ir \
  --config ~/.config/habitatos/ir/CAGE-001/ir.json \
  --env-file ~/.config/habitatos/ir/CAGE-001/ir.env --action status

~/.local/share/habitatos/ir/current/venv/bin/habitat-ir \
  --config ~/.config/habitatos/ir/CAGE-001/ir.json \
  --env-file ~/.config/habitatos/ir/CAGE-001/ir.env --action on --seconds 10

~/.local/share/habitatos/ir/current/venv/bin/habitat-ir \
  --config ~/.config/habitatos/ir/CAGE-001/ir.json \
  --env-file ~/.config/habitatos/ir/CAGE-001/ir.env --action off
```

`status` only subscribes. The credential file is owner-readable only and contains
the two configured variable names as literal `KEY=value`; it is not a shell
script. TLS certificate and hostname verification remain enabled. Camera viewer
keys grant no IR command privileges. There is no automatic lighting schedule.

## Optional camera web controls

From 0.4.24, the existing `/camera` page provides cage-scoped IR ON/OFF with
**continuous ON by default** and an optional automatic OFF timer. An ON request
with `seconds` omitted or null is continuous; an explicit integer from 1 to 900
selects timed operation. The worker's `max_on_seconds` can lower the timer limit
and does not impose a duration on continuous operation.

Both modes use the existing controller to renew firmware leases of at most
5 seconds and verify acknowledgements. Continuous ON depends on those renewals;
it never installs an indefinite MCU output. Closing the browser or logging out
does not stop an accepted request. Use OFF to stop continuous operation or end
a timer early. Worker restart, MQTT/Wi-Fi disconnection and node-session change
terminate renewal; the node turns OFF when its current lease expires if an OFF
command cannot arrive. Reconnection does not resume ON. Page reload and login
only show the current state and do not issue an ON command.

The Gateway forwards requests to a separate loopback worker on
`127.0.0.1:8093`; it does not access the IR MQTT account or sequence files.
`apps.worker.ir_web` wires configuration and HTTP lifecycle to
`habitat.control.ir_web`, which reuses the existing local IR controller.
The worker runs as the commissioned CLI user and shares
`~/.local/state/habitat-ir/` locks, cancellation markers and durable sequences.
Only one ON controller can hold a cage's lock. OFF can cancel an active local
CLI or web request. Separate cages retain independent control and status.

| Boundary | Authentication and scope |
| --- | --- |
| Browser → Gateway viewing | Existing `HABITAT_CAMERA_VIEWER_TOKEN`; camera and IR status only |
| Browser → Gateway control | Distinct `HABITAT_CAMERA_CONTROL_TOKEN`; viewing plus configured cage IR commands |
| Gateway → loopback worker | `HABITAT_IR_BRIDGE_TOKEN`; configured IR nodes only |
| Worker → node | Existing cage-specific TLS MQTT account, topic and ACL |

Control login creates a separate HttpOnly, SameSite=Strict cookie; HTTPS sessions
also set Secure. Commands require that session plus `X-Habitat-CSRF`; a supplied
Origin must match the Gateway origin. A viewer key cannot acquire a control
session. Keys are not query parameters and are not stored in browser localStorage.
The private launcher uses `#control_key=...`; the page removes the fragment and
exchanges the key for session cookies. Logging out clears both sessions.

| API | Result |
| --- | --- |
| `GET /camera/control/session` | Viewer-authenticated control eligibility and CSRF token |
| `GET /camera/api/ir/{cage_id}` | Viewer-authenticated fresh node/request status |
| `POST /camera/api/ir/{cage_id}` | Control-authenticated `{"action":"on"}` or `{"action":"on","seconds":null}` for continuous ON; `{"action":"on","seconds":300}` for a timer; `{"action":"off"}` to stop. 202 means request accepted |
| Loopback `GET /health` | Worker identity and configured cages; no hardware command |
| Loopback `GET/POST /v1/ir/{cage_id}` | Bearer-authenticated internal status/command boundary |

The internal loopback command accepts the same omitted/null/integer `seconds`
contract. Status includes `mode`: `continuous`, `timed`, or null when no run is
active. An active continuous request has `remaining_s: null`; the UI shows
continuous operation without a countdown. A timed request reports the remaining
seconds. Idle state has no mode and zero remaining seconds. These fields describe
the controller request, independently of the node's requested GPIO state.

Unregistered cages, disabled configurations, missing/stale hello, locked outputs,
busy controllers and transport failures are explicit unavailable/error states.
`gpio_requested_on` is a node-reported request; `actual_ir_on` remains null and
`physical_ir_verified` false. HTTP 202, MQTT ACK and an active countdown do not
prove light emission. Verify the image or inspect the lamp during commissioning.

The optional Gateway configuration is disabled by default:

```toml
[camera_ir]
enabled = false
endpoint = "http://127.0.0.1:8093"
token_env = "HABITAT_IR_BRIDGE_TOKEN"
cage_ids = []
```

Commissioned deployments enable it and explicitly enumerate registered cages.
The worker JSON contains `site_id`, `gateway_id`, `max_on_seconds`, and `nodes`
with `cage_id`, `node_id`, `config_path`, `env_path`. These paths point to existing
private IR configuration; credentials are never copied into public examples.
The 0.4.24 continuous mode uses this same configuration schema, key files and
existing cage scope. `max_on_seconds` still bounds explicit timers only.

`deploy/provision_ir_web.py --user USER --cage CAGE_ID` defaults to dry-run.
Repeat `--cage` for the complete desired scope; `--apply` requires root. It checks
Gateway identities and existing IR provisioning receipts, preserves Gateway env
bytes/owner/mode, generates the two new keys once, and retains protected backups
and an ownership receipt. Repeated application reuses keys. A changed versioned
IR runtime or worker configuration restarts only `habitat-ir-web.service`;
an unchanged healthy worker is left running. Failed activation restores the
previous files and worker state. No ON is sent during provisioning.

The generated unit reads root-private `/etc/habitat-ir/web.env`, with a user-owned
0600 `/etc/habitat-ir/web.json`. Its root-owned 0755 parent permits traversal but
not reading either private file as another user. The service uses
NoNewPrivileges, PrivateTmp, a read-only home/system and a write exception only
for the existing IR state directory. Gateway TOML and Gateway/Air activation
remain the common versioned installer's responsibility.

This addition requires no firmware change on already commissioned IR nodes and
does not enable pumps or change the existing sensor/camera firmware.

### 0.4.23 to 0.4.24 compatibility

In 0.4.23, omitting `seconds` selected a 300-second timer. In 0.4.24 it selects
continuous operation. API clients that require the old timer behavior must send
an explicit `seconds: 300`; existing explicit 1–900-second requests remain timed.
The 0.4.23 UI always sent a numeric duration, so it retains timed behavior while
the worker is upgraded. No new credential or configuration fields are required.
The MCU wire protocol and five-second lease limit do not change.

Install the new user IR runtime and reapply the existing worker provisioner
before activating the new Gateway release. The old Gateway continues to send
explicit timed requests while the worker is upgraded. Provisioning reuses keys,
identities and sequence files, and detects the changed runtime release so it
restarts the worker. Any active request ends during that restart and is not
automatically restored. The Gateway update then exposes the new default UI/API
behavior. See [Pi activation and control-key handling](../operations/pi-update.md).
