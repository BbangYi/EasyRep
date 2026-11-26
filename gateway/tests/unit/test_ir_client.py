"""No broker, Pi, GPIO, credentials or device commands: deterministic local mocks."""
from pathlib import Path
import json
import ssl
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from habitat.control import ir
from apps.worker import ir_control as cli

BASE = "habitat/v1/STORE-TEST/cages/CAGE-001/nodes/ESP32-TEST"
S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"


def hello(session=S1, **changes):
    value = {"schema_version": 1, "session_id": session,
             "command_topic": f"{BASE}/ir/command/{session}",
             "outputs_locked": False, "gpio_requested_on": False,
             "actual_ir_on": None, "max_lease_ms": 5000}
    value.update(changes)
    return json.dumps(value).encode()


class Clock:
    def __init__(self): self.now = 0.0; self.hook = None
    def __call__(self): return self.now
    def wall(self): return 1800000000.0 + self.now
    def sleep(self, seconds):
        self.now += seconds
        if self.hook: self.hook(self.now)


class Sequences:
    def __init__(self): self.count = 0
    def next(self, session): self.count += 1; return self.count


class Client:
    def __init__(self): self.sent = []; self.monitor = None; self.auto_ack = True; self.ack_changes = {}
    def publish(self, topic, payload, **kwargs):
        self.sent.append((topic, payload, kwargs))
        if self.monitor and self.auto_ack:
            fields = payload.split()
            ack = {"schema_version": 1, "session_id": fields[1], "command_id": fields[2],
                   "sequence": int(fields[3]), "reason": "ir_requested_on" if fields[5] == "on" else "off_requested",
                   "gpio_requested_on": fields[5] == "on", "actual_ir_on": None}
            ack.update(self.ack_changes)
            self.monitor.accept(BASE + "/ir/ack", json.dumps(ack).encode())
        return types.SimpleNamespace(rc=0, wait_for_publish=lambda **k: None)


class IrClientTest(unittest.TestCase):
    def fixture(self, locked=False):
        clock = Clock(); client = Client(); sequence = Sequences()
        monitor = ir.Monitor(BASE, clock)
        client.monitor = monitor
        monitor.connection(True); monitor.accept(BASE + "/ir/hello", hello(outputs_locked=locked))
        control = ir.Controller(client, monitor, sequence, monotonic=clock, wall_clock=clock.wall, sleep=clock.sleep)
        return control, client, monitor, clock, sequence

    def test_status_never_publishes_or_allocates_sequence(self):
        control, client, monitor, clock, sequence = self.fixture(locked=True)
        result = control.run()
        self.assertTrue(result["outputs_locked"])
        self.assertIsNone(result["actual_ir_on"])
        self.assertEqual(client.sent, [])
        self.assertEqual(sequence.count, 0)

    def test_locked_output_never_sends_on(self):
        control, client, *_ = self.fixture(locked=True)
        with self.assertRaisesRegex(ir.ControlError, "locked"): control.run("on", 2)
        self.assertFalse(any(x[1].split()[5] == "on" for x in client.sent))

    def test_each_renewal_has_new_uuid_sequence_and_no_retention(self):
        control, client, monitor, clock, _ = self.fixture()
        clock.hook = lambda now: monitor.accept(BASE + "/ir/hello", hello())
        control.run("on", 3)
        frames = [x[1].split() for x in client.sent]
        on = [x for x in frames if x[5] == "on"]
        self.assertEqual(len(on), 3)
        self.assertEqual(len({x[2] for x in frames}), len(frames))
        self.assertEqual([int(x[3]) for x in frames], list(range(1, len(frames) + 1)))
        self.assertTrue(all(x[0] == "IR/1" and x[4] == "1" and 1 <= int(x[6]) <= 5000 for x in on))
        self.assertTrue(all(int(x[8]) - int(x[7]) == int(x[6]) for x in on))
        self.assertEqual(frames[-1][5], "off")
        self.assertTrue(all(x[2] == {"qos": 1, "retain": False} for x in client.sent))

    def test_stale_hello_stops_without_automatic_resume(self):
        control, client, monitor, clock, _ = self.fixture()
        with self.assertRaisesRegex(ir.ControlError, "expired"): control.run("on", 10)
        self.assertLess(clock.now, 5.2)
        self.assertEqual(client.sent[-1][1].split()[5], "off")
        monitor.accept(BASE + "/ir/hello", hello())
        with self.assertRaises(ir.ControlError): monitor.checked(True)

    def test_continuous_lease_has_no_total_deadline_and_off_cleans_up(self):
        control, client, monitor, clock, _ = self.fixture()
        # Jump between boundary samples without wall-clock waiting. Each sample
        # refreshes a live hello, as the ongoing broker stream normally does.
        samples = iter((1.0, 901.0, 43201.0, 86401.0))
        def advance(unused_seconds):
            clock.now = next(samples)
            monitor.accept(BASE + "/ir/hello", hello())
        control.sleep = advance
        control.cancelled = lambda: clock.now >= 86401.0
        with self.assertRaisesRegex(ir.ControlError, "Local OFF"):
            control.run("on", None)
        frames = [entry[1].split() for entry in client.sent]
        on = [entry for entry in frames if entry[5] == "on"]
        self.assertEqual(len(on), 4)
        self.assertTrue(all(int(entry[6]) == 5000 for entry in on))
        self.assertEqual(frames[-1][5], "off")
        self.assertGreater(int(on[-1][7]), int(on[0][7]) + 43200 * 1000)

    def test_session_change_stops_on_and_cleans_current_session_off(self):
        control, client, monitor, clock, _ = self.fixture()
        clock.hook = lambda now: monitor.accept(BASE + "/ir/hello", hello(S2)) if now >= 0.2 else None
        with self.assertRaisesRegex(ir.ControlError, "session changed"): control.run("on", 10)
        self.assertEqual([x[1].split()[5] for x in client.sent], ["on", "off"])
        self.assertTrue(client.sent[-1][0].endswith(S2))

    def test_disconnect_does_not_publish_or_reconnect_after_loss(self):
        control, client, monitor, clock, _ = self.fixture()
        clock.hook = lambda now: monitor.connection(False) if now >= 0.2 else None
        with self.assertRaisesRegex(ir.ControlError, "disconnected"): control.run("on", 10)
        self.assertEqual(len(client.sent), 1)
        monitor.connection(True)
        with self.assertRaises(ir.ControlError): monitor.checked(True)

    def test_keyboard_interrupt_attempts_off(self):
        control, client, monitor, clock, _ = self.fixture()
        def interrupt(now): raise KeyboardInterrupt
        clock.hook = interrupt
        with self.assertRaises(KeyboardInterrupt): control.run("on", 10)
        self.assertEqual([x[1].split()[5] for x in client.sent], ["on", "off"])

    def test_separate_off_request_cancels_owner_before_next_renewal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            initial = ir.cancellation_token(path)
            control, client, monitor, clock, _ = self.fixture()
            control.cancelled = lambda: ir.cancellation_token(path) != initial
            clock.hook = lambda now: ir.request_local_off(path) if now >= 0.2 else None
            with self.assertRaisesRegex(ir.ControlError, "Local OFF"):
                control.run("on", 43200)
            self.assertEqual([x[1].split()[5] for x in client.sent], ["on", "off"])

    def test_cancel_before_hello_never_sends_on(self):
        control, client, *_ = self.fixture()
        control.cancelled = lambda: True
        with self.assertRaisesRegex(ir.ControlError, "Local OFF"):
            control.run("on", 10)
        self.assertEqual(client.sent, [])

    def test_mismatched_or_retained_hello_cannot_start(self):
        monitor = ir.Monitor(BASE, Clock()); monitor.connection(True)
        monitor.accept(BASE + "/ir/hello", hello(), retained=True)
        monitor.accept(BASE.replace("CAGE-001", "CAGE-002") + "/ir/hello", hello())
        self.assertIsNone(monitor.hello)
        with self.assertRaises(ir.ControlError): monitor.checked()

    def test_hello_trust_boundaries(self):
        bad = [hello(command_topic="evil/topic"), hello(schema_version=True), hello(outputs_locked=0),
               hello(max_lease_ms=True), hello(max_lease_ms=6000), hello(actual_ir_on=True),
               hello(session_id="../../other"), b"[1]", b"x" * 2049,
               hello().replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')]
        for payload in bad:
            with self.subTest(payload=payload[:80]), self.assertRaises(ir.ControlError): ir.parse_hello(payload, BASE)

    def test_malformed_live_hello_aborts_active_request(self):
        control, client, monitor, clock, _ = self.fixture()
        clock.hook = lambda now: monitor.accept(BASE + "/ir/hello", b"{}")
        with self.assertRaisesRegex(ir.ControlError, "Malformed"): control.run("on", 2)
        self.assertEqual(client.sent[-1][1].split()[5], "off")

    def test_duration_bounds_reject_before_any_publish(self):
        for duration in (0, 0.99, 43201, float("nan"), float("inf"), True):
            control, client, *_ = self.fixture()
            with self.subTest(duration=duration), self.assertRaises(ir.ControlError): control.run("on", duration)
            self.assertEqual(client.sent, [])

    def test_off_allowed_while_outputs_locked(self):
        control, client, *_ = self.fixture(locked=True)
        control.run("off")
        self.assertTrue(all(x[1].split()[5] == "off" for x in client.sent))

    def test_sequence_persists_across_invocations_and_resets_per_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with ir.ControlLock(path):
                self.assertEqual(ir.SequenceStore(path, BASE).next(S1), 1)
            with ir.ControlLock(path):
                self.assertEqual(ir.SequenceStore(path, BASE).next(S1), 2)
                self.assertEqual(ir.SequenceStore(path, BASE).next(S2), 1)

    def test_concurrent_local_control_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with ir.ControlLock(path):
                with self.assertRaisesRegex(ir.ControlError, "active"):
                    with ir.ControlLock(path): pass

    def test_invalid_sequence_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"; path.write_text("{}")
            with self.assertRaises(ir.ControlError): ir.SequenceStore(path, BASE).next(S1)

    def test_tls_keeps_ca_and_hostname_verification(self):
        config = ir.Config("habitat-pi", 8883, "/example/ca.crt", BASE, "IR_USER", "IR_PASSWORD")
        context = Mock()
        with patch.object(ir.ssl, "create_default_context", return_value=context) as build:
            self.assertIs(ir.tls_context(config), context)
            build.assert_called_once_with(cafile="/example/ca.crt")
        self.assertIs(context.check_hostname, True)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_config_rejects_plaintext_password_topic_wildcards_and_non_tls_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            ca = Path(tmp) / "ca.crt"; ca.write_text("test-only; not a real certificate")
            config = {"broker_host": "habitat-pi", "broker_port": 8883, "ca_file": str(ca),
                      "topic_base": BASE, "username_env": "IR_USER", "password_env": "IR_PASSWORD"}
            path = Path(tmp) / "config.json"
            for changed in ({**config, "password": "not-permitted"}, {**config, "broker_port": 1883}, {**config, "topic_base": "habitat/#"}):
                path.write_text(json.dumps(changed))
                with self.assertRaises(ir.ControlError): ir.load_config(path)

    def test_missing_credentials_are_not_echoed(self):
        config = ir.Config("habitat-pi", 8883, "unused", BASE, "IR_USER", "IR_PASSWORD")
        with self.assertRaisesRegex(ir.ControlError, "not set"):
            ir.credentials(config, {"IR_USER": "example-only"})

    def test_unsynchronized_clock_cannot_create_on(self):
        with self.assertRaisesRegex(ir.ControlError, "clock"):
            ir.command_frame(S1, 1, "on", 5000, wall_clock=lambda: 0)

    def test_off_still_possible_with_unsynchronized_clock(self):
        frame = ir.command_frame(S1, 1, "off", wall_clock=lambda: 0).split()
        self.assertEqual(frame[4:7], ["1", "off", "0"])

    def test_missing_mcu_ack_stops_renewals(self):
        control, client, monitor, clock, _ = self.fixture()
        client.auto_ack = False
        clock.hook = lambda now: monitor.accept(BASE + "/ir/hello", hello())
        with self.assertRaisesRegex(ir.ControlError, "acknowledgment expired"):
            control.run("on", 10)
        self.assertLess(clock.now, 2.2)
        self.assertEqual(client.sent[-1][1].split()[5], "off")

    def test_rejected_or_mismatched_ack_stops_without_retry(self):
        for changes in ({"reason": "invalid_time", "gpio_requested_on": False},
                        {"session_id": S2}, {"sequence": True}, {"actual_ir_on": True}):
            control, client, *_ = self.fixture()
            client.ack_changes = changes
            with self.subTest(changes=changes), self.assertRaisesRegex(ir.ControlError, "MCU rejected"):
                control.run("on", 10)
            self.assertEqual([x[1].split()[5] for x in client.sent], ["on", "off"])

    def test_client_disables_reconnect_and_uses_only_configured_hello_topic(self):
        config = ir.Config("habitat-pi", 8883, "unused", BASE, "IR_USER", "IR_PASSWORD")
        monitor = ir.Monitor(BASE, Clock())
        fake = Mock(); fake.subscribe.return_value = (0, 1)
        module = types.SimpleNamespace(Client=Mock(return_value=fake),
                    CallbackAPIVersion=types.SimpleNamespace(VERSION2=2), MQTTv311=4)
        with patch.object(ir, "credentials", return_value=("test-user", "test-secret")), patch.object(ir, "tls_context") as tls:
            self.assertIs(ir.make_client(config, monitor, mqtt_module=module), fake)
            self.assertFalse(module.Client.call_args.kwargs["reconnect_on_failure"])
            fake.tls_set_context.assert_called_once_with(tls.return_value)
            fake.on_connect(fake, None, None, 0, None)
            self.assertEqual([call.args[0] for call in fake.subscribe.call_args_list],
                             [BASE + "/ir/hello", BASE + "/ir/ack"])
            fake.on_disconnect(fake, None, None, 1, None)
            self.assertFalse(monitor.connected)
            self.assertIn("disconnected", monitor.fault)


class IrCliTest(unittest.TestCase):
    def config(self):
        return ir.Config("habitat-pi", 8883, "unused", BASE, "IR_USER", "IR_PASSWORD")

    def test_private_file_supplies_only_configured_credentials_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ir.env"
            path.write_text("# Test credentials only\nIR_USER=test-user\nIR_PASSWORD='$(never-execute); literal#value'\n")
            path.chmod(0o600)
            original = {"IR_USER": "old-user", "UNCHANGED": "yes"}
            result = cli.credential_environment(self.config(), path, original)
            self.assertEqual(result["IR_USER"], "test-user")
            self.assertEqual(result["IR_PASSWORD"], "$(never-execute); literal#value")
            self.assertEqual(result["UNCHANGED"], "yes")
            self.assertEqual(original, {"IR_USER": "old-user", "UNCHANGED": "yes"})

    def test_credential_file_rejects_public_permissions_and_unexpected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ir.env"
            path.write_text("IR_USER=test-user\nIR_PASSWORD=test-secret\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(ir.ControlError, "private"):
                cli.credential_environment(self.config(), path)
            path.chmod(0o600)
            for contents in (
                "IR_USER=x\nIR_PASSWORD=secret\nUNRELATED=secret\n",
                "IR_USER=x\nIR_PASSWORD=secret\nIR_PASSWORD=duplicate\n",
                "IR_USER=x\n", "IR_USER=x\nIR_PASSWORD=\n",
                'IR_USER=x\nIR_PASSWORD="unclosed-secret\n',
            ):
                path.write_text(contents)
                with self.subTest(contents=contents), self.assertRaises(ir.ControlError) as caught:
                    cli.credential_environment(self.config(), path)
                self.assertNotIn("secret", str(caught.exception))

    def test_cli_status_does_not_lock_or_publish_and_cleans_up_client(self):
        fake = Mock()
        status = {"outputs_locked": True, "actual_ir_on": None}
        with patch.object(cli, "load_config", return_value=self.config()), \
             patch.object(cli, "credential_environment", return_value={"IR_USER": "test-user", "IR_PASSWORD": "test-only"}), \
             patch.object(cli, "make_client", return_value=fake) as make, \
             patch.object(cli, "Controller") as controller, \
             patch.object(cli, "ControlLock") as lock, \
             patch.object(cli, "request_local_off") as cancel, \
             patch("builtins.print"):
            controller.return_value.run.return_value = status
            self.assertEqual(cli.main(["--config", "unused.json"]), 0)
            controller.return_value.run.assert_called_once_with("status", 10.0)
            lock.assert_not_called()
            cancel.assert_not_called()
            fake.publish.assert_not_called()
            fake.disconnect.assert_called_once()
            fake.loop_stop.assert_called_once()
            self.assertEqual(make.call_args.kwargs["environ"]["IR_USER"], "test-user")


if __name__ == "__main__":
    unittest.main()
