import copy
from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import patch
import uuid
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from .ingestion import token_digest
from .models import Binding, CommandState, CurrentState, Event, Gateway, Measurement
from habitat.models import Enclosure, Organization, SiteSettings, Store, User

FIXTURE = json.loads((Path(__file__).parent / "fixtures/sync-request.json").read_text())
TOKEN = "edge-test-credential-" + "a" * 40


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class EdgeTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="검증 매장", edge_site_id="STORE-001")
        self.cage = Enclosure.objects.create(
            id="received-cage",
            name="수신 사육장",
            store=self.store,
            edge_cage_id="CAGE-001",
        )
        self.gateway = Gateway.objects.create(
            store=self.store,
            edge_gateway_id="PI-001",
            token_digest=token_digest(TOKEN),
            allow_simulation=True,
        )
        Binding.objects.create(gateway=self.gateway, enclosure=self.cage)
        SiteSettings.objects.create(pk=1)
        self.body = copy.deepcopy(FIXTURE)
        self.browser = Client(enforce_csrf_checks=True)

    def send(self, body=None, token=TOKEN):
        return self.browser.post(
            "/v1/edge/sync",
            json.dumps(body if body is not None else self.body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def login(self, role="owner", store=None):
        user = User.objects.create_user(
            username=f"{role}@example.com",
            password="fixture-password-only",
            display_name=role,
            role=role,
            store=store,
        )
        self.browser.force_login(user)
        return user

    def test_reference_fixture_ack_and_retry(self):
        response = self.send()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["accepted_event_ids"],
            [e["event_id"] for e in self.body["events"]],
        )
        self.assertEqual(self.send().json(), response.json())
        self.assertEqual(Event.objects.count(), len(self.body["events"]))

    def test_heartbeat_has_empty_ack_and_does_not_freshen_sensor(self):
        self.send()
        measured = CurrentState.objects.get().sampled_at
        self.body["events"] = []
        self.body["sent_at"] = timezone.now().isoformat()
        self.assertEqual(self.send().json()["accepted_event_ids"], [])
        self.assertEqual(CurrentState.objects.get().sampled_at, measured)
        self.login()
        value = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertTrue(value["stale"])
        self.assertEqual(value["gateway"]["status"], "connected")

    def test_missing_wrong_and_browser_credentials_rejected(self):
        self.assertEqual(self.send(token="b" * 50).status_code, 401)
        self.login()
        self.assertEqual(
            self.browser.post(
                "/v1/edge/sync", self.body, content_type="application/json"
            ).status_code,
            401,
        )

    def test_wrong_identity_and_cage_rejected(self):
        self.body["site_id"] = "OTHER"
        self.body["events"] = []
        self.assertEqual(self.send().status_code, 403)
        self.body = copy.deepcopy(FIXTURE)
        Binding.objects.all().delete()
        self.assertEqual(self.send().status_code, 403)

    def test_wrong_node_rejected(self):
        Binding.objects.update(node_id="OTHER")
        self.assertEqual(self.send().status_code, 403)

    def test_simulation_disabled_in_snapshot_or_event(self):
        Gateway.objects.update(allow_simulation=False)
        self.assertEqual(self.send().status_code, 403)
        self.body["gateway"]["transport"] = "mqtt"
        for cage in self.body["gateway"]["cages"]:
            cage["state"]["transport"] = "mqtt"
            cage["state"]["telemetry"] = None
        self.assertEqual(self.send().status_code, 403)

    def test_revoked_token_denied(self):
        Gateway.objects.update(active=False)
        self.assertEqual(self.send().status_code, 401)

    def test_conflict_rolls_back_whole_batch_and_heartbeat(self):
        self.send()
        count = Event.objects.count()
        receipt = Gateway.objects.get().last_received_at
        self.body["events"][0]["created_at"] = "2026-09-18T00:00:00Z"
        self.assertEqual(self.send().status_code, 409)
        self.assertEqual(Event.objects.count(), count)
        self.assertEqual(Gateway.objects.get().last_received_at, receipt)

    def test_sequence_reuse_with_new_id_conflicts(self):
        self.send()
        self.body["events"][0]["event_id"] = str(uuid.uuid4())
        self.assertEqual(self.send().status_code, 409)

    def test_duplicate_or_unordered_batch_rejected(self):
        self.body["events"].reverse()
        self.assertEqual(self.send().status_code, 422)
        self.body["events"] = [self.body["events"][0]] * 2
        self.assertEqual(self.send().status_code, 422)

    def test_strict_primitives(self):
        for mutation in (
            lambda b: b.update(schema_version=True),
            lambda b: b["events"][0].update(event_sequence="1"),
            lambda b: b["gateway"].update(healthy="true"),
            lambda b: b["gateway"]["cages"][0]["state"]["telemetry"]["readings"][
                "T1"
            ].update(value=True),
        ):
            body = copy.deepcopy(FIXTURE)
            mutation(body)
            self.assertEqual(self.send(body).status_code, 422)

    def test_invalid_reading_must_be_null(self):
        reading = self.body["gateway"]["cages"][0]["state"]["telemetry"]["readings"][
            "T1"
        ]
        reading.update(quality="crc_error", value=0)
        self.assertEqual(self.send().status_code, 422)
        reading["value"] = None
        self.assertEqual(self.send().status_code, 200)

    def test_unknown_event_and_timezone_missing_rejected(self):
        self.body["events"][0]["kind"] = "gpu.completed"
        self.assertEqual(self.send().status_code, 422)
        self.body = copy.deepcopy(FIXTURE)
        self.body["sent_at"] = "2026-09-18T12:00:00"
        self.assertEqual(self.send().status_code, 422)

    def test_body_limit_and_bad_json(self):
        response = self.browser.post(
            "/v1/edge/sync",
            b"x" * (8 * 1024 * 1024 + 1),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {TOKEN}",
        )
        self.assertEqual(response.status_code, 413)
        for body in (b'{"schema_version":1,"schema_version":1}', b"broken-json"):
            self.assertEqual(
                self.browser.post(
                    "/v1/edge/sync",
                    body,
                    content_type="application/json",
                    HTTP_AUTHORIZATION=f"Bearer {TOKEN}",
                ).status_code,
                422,
            )

    def test_event_count_limit(self):
        self.body["events"] = [self.body["events"][0]] * 1001
        self.assertEqual(self.send().status_code, 422)

    def test_storage_failure_no_ack_and_rollback(self):
        with patch.object(
            CurrentState.objects,
            "get_or_create",
            side_effect=OperationalError("test failure"),
        ):
            response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("accepted_event_ids", response.json())
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Measurement.objects.count(), 0)

    def test_old_snapshot_does_not_replace_latest(self):
        self.send()
        old = CurrentState.objects.get().telemetry
        self.body["events"] = []
        self.body["sent_at"] = "2020-01-01T00:00:00Z"
        self.body["gateway"]["cages"][0]["state"]["telemetry"][
            "sampled_at"
        ] = "2020-01-01T00:00:00Z"
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(CurrentState.objects.get().telemetry, old)

    def test_command_latest_uses_gateway_sequence(self):
        commands = [e for e in self.body["events"] if e["kind"] == "command.updated"]
        self.assertTrue(commands)
        self.send()
        for command in CommandState.objects.all():
            self.assertEqual(
                command.event_sequence,
                max(
                    e["event_sequence"]
                    for e in commands
                    if e["payload"]["command_id"] == str(command.command_id)
                ),
            )

    def test_current_and_history_use_stored_values(self):
        self.send()
        self.login()
        items = self.browser.get("/api/enclosures/").json()["items"]
        self.assertEqual(items[0]["id"], "received-cage")
        self.assertEqual(items[0]["source"], "simulation")
        response = self.browser.get(
            f"/api/enclosures/{self.cage.pk}/history/",
            {"hours": 24, "end": self.body["sent_at"]},
        )
        self.assertEqual(response.status_code, 200)
        expected = [e for e in self.body["events"] if e["kind"] == "telemetry.recorded"]
        self.assertEqual(len(response.json()["points"]), len(expected))
        for point, event in zip(
            response.json()["points"],
            sorted(expected, key=lambda e: e["payload"]["sampled_at"]),
        ):
            self.assertEqual(point["readings"], event["payload"]["readings"])

    def test_account_scope_applies_to_all_queries(self):
        other = Store.objects.create(name="다른 매장")
        self.login("manager", other)
        self.assertEqual(self.browser.get("/api/enclosures/").json()["items"], [])
        for suffix in ("", "history/", "records/", "commands/"):
            self.assertEqual(
                self.browser.get(
                    f"/api/enclosures/{self.cage.pk}/{suffix}"
                ).status_code,
                404,
            )

    def test_same_external_ids_in_other_organization_do_not_share_data(self):
        org = Organization.objects.create(name="다른 조직")
        store = Store.objects.create(
            organization=org, name="다른 조직 매장", edge_site_id="STORE-001"
        )
        cage = Enclosure.objects.create(
            id="other", name="별도", store=store, edge_cage_id="CAGE-001"
        )
        other = Gateway.objects.create(
            store=store,
            edge_gateway_id="PI-001",
            token_digest=token_digest("b" * 50),
            allow_simulation=True,
        )
        Binding.objects.create(gateway=other, enclosure=cage)
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.send(token="b" * 50).status_code, 200)
        self.assertEqual(Event.objects.count(), len(self.body["events"]) * 2)

    def test_no_frontend_redirect_or_html_on_pi_routes(self):
        self.assertEqual(self.browser.get("/v1/edge/health").json(), {"status": "ok"})
        for url in ("/v1/edge/sync/", "/v1/edge/missing"):
            response = self.browser.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(self.browser.get("/v1/edge/sync").status_code, 405)

    def test_maintenance_does_not_stop_pi(self):
        SiteSettings.objects.update(maintenance=True)
        self.assertEqual(self.send().status_code, 200)

    def test_records_filter_and_query_validation(self):
        self.send()
        self.login()
        url = f"/api/enclosures/{self.cage.pk}/records/"
        rows = self.browser.get(url, {"kind": "command.updated"}).json()["items"]
        self.assertTrue(all(row["kind"] == "command.updated" for row in rows))
        self.assertEqual(self.browser.get(url, {"before": "invalid"}).status_code, 400)
        self.assertEqual(self.browser.get(url, {"kind": "gpu"}).status_code, 400)
        self.assertEqual(
            self.browser.get(
                f"/api/enclosures/{self.cage.pk}/history/", {"hours": "3"}
            ).status_code,
            400,
        )

    def test_timestamp_numbers_rejected(self):
        self.body["sent_at"] = 1726620000
        self.assertEqual(self.send().status_code, 422)

    def test_registration_private_token_and_no_implicit_simulation(self):
        import tempfile, os
        from django.core.management import call_command
        from io import StringIO

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "registration.json"
            secret = Path(directory) / "pi.token"
            config.write_text(
                json.dumps(
                    {
                        "site_id": "STORE-002",
                        "gateway_id": "PI-002",
                        "store_name": "추가 매장",
                        "cages": [{"id": "CAGE-002", "name": "추가 사육장"}],
                    }
                )
            )
            output = StringIO()
            call_command(
                "register_gateway", str(config), token_file=str(secret), stdout=output
            )
            token = secret.read_text().strip()
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(os.stat(secret).st_mode & 0o777, 0o600)
            registered = Gateway.objects.get(edge_gateway_id="PI-002")
            self.assertFalse(registered.allow_simulation)
            self.assertNotIn(token, output.getvalue())
            new_secret = Path(directory) / "rotated.token"
            call_command(
                "rotate_gateway_token",
                str(registered.pk),
                token_file=str(new_secret),
                stdout=output,
            )
            registered.refresh_from_db()
            self.assertNotEqual(registered.token_digest, token_digest(token))
            self.assertEqual(
                registered.token_digest, token_digest(new_secret.read_text().strip())
            )

    def test_bound_cage_cannot_move_store(self):
        from habitat.forms import EnclosureForm

        other = Store.objects.create(name="다른 매장")
        form = EnclosureForm(
            {"name": self.cage.name, "store": other.pk}, instance=self.cage
        )
        self.assertFalse(form.is_valid())

    def test_disabled_gateway_setting_is_owner_only(self):
        self.login("manager", self.store)
        response = self.browser.get(f"/manage/gateways/{self.gateway.pk}/")
        self.assertEqual(response.status_code, 403)

    def test_new_configuration_never_relabels_old_readings(self):
        self.send()
        self.body["events"] = []
        self.body["sent_at"] = timezone.now().isoformat()
        self.body["gateway"]["cages"][0]["configuration"]["placement_revision"] += 1
        self.body["gateway"]["cages"][0]["state"]["telemetry"] = None
        self.assertEqual(self.send().status_code, 200)
        self.login()
        item = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertTrue(item["configurationChanged"])
        self.assertTrue(all(sensor["value"] is None for sensor in item["sensors"]))

    def test_korean_record_search_combines_labels_and_preserves_scope(self):
        self.send()
        self.login()
        url = f"/api/enclosures/{self.cage.pk}/records/"
        for word, field, value in [("조명", "actuator_id", "light"), ("장치 적용 확인", "status", "applied"), ("장치적용확인", "status", "applied")]:
            with self.subTest(word=word):
                rows = self.browser.get(url, {"q": word}).json()["items"]
                self.assertTrue(rows)
                self.assertTrue(all(row["kind"] == "command.updated" and row["payload"][field] == value for row in rows))
        rows = self.browser.get(url, {"q": "조명 장치 적용 확인"}).json()["items"]
        self.assertTrue(rows)
        self.assertTrue(all(row["payload"]["actuator_id"] == "light" and row["payload"]["status"] == "applied" for row in rows))
        self.assertEqual(self.browser.get(url, {"q": "조명", "kind": "telemetry.recorded"}).json()["items"], [])
        self.assertTrue(self.browser.get(url, {"q": "T1"}).json()["items"])
        other = Store.objects.create(name="권한 밖 매장")
        self.login(role="manager", store=other)
        self.assertEqual(self.browser.get(url, {"q": "조명"}).status_code, 404)

    def test_korean_record_search_cursor_retains_filter(self):
        self.send()
        self.login()
        original = Event.objects.filter(kind="command.updated", body__payload__actuator_id="light").first()
        for index in range(55):
            Event.objects.create(gateway=self.gateway, enclosure=self.cage, event_id=uuid.uuid4(), event_sequence=1000+index,
                kind=original.kind, created_at=original.created_at + timedelta(seconds=index+1), digest="test", body=original.body)
        url = f"/api/enclosures/{self.cage.pk}/records/"
        first = self.browser.get(url, {"q": "조명"}).json()
        second = self.browser.get(url, {"q": "조명", "before": first["next"]}).json()
        self.assertEqual(len(first["items"]), 50)
        self.assertTrue(second["items"])
        self.assertFalse({row["id"] for row in first["items"]} & {row["id"] for row in second["items"]})
        self.assertTrue(all(row["payload"]["actuator_id"] == "light" for row in second["items"]))

    def test_snapshot_without_event_is_saved_as_history(self):
        self.body["events"] = []
        self.assertEqual(self.send().status_code, 200)
        self.login()
        item = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertEqual(item["historyReceipt"]["sampledAt"], "2026-09-18T08:00:00+00:00")
        self.assertFalse(item["historyReceipt"]["behindCurrent"])
        self.assertTrue(item["stale"])
        self.assertEqual(item["gateway"]["status"], "connected")
        self.assertEqual(Event.objects.count(), 0)

    def test_history_receipt_tracks_measurement_not_command_or_heartbeat(self):
        self.send()
        self.login()
        row = Event.objects.filter(kind="telemetry.recorded").order_by("-sampled_at", "-event_sequence").first()
        item = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertEqual(item["historyReceipt"]["sampledAt"], row.sampled_at.isoformat())
        self.assertEqual(item["historyReceipt"]["receivedAt"], row.received_at.isoformat())
        self.assertFalse(item["historyReceipt"]["behindCurrent"])
        before = item["historyReceipt"]
        self.body["events"] = []
        self.body["sent_at"] = timezone.now().isoformat()
        self.send()
        item = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertEqual(item["historyReceipt"], before)

    def test_empty_cage_has_no_false_history_warning(self):
        self.login()
        item = self.browser.get(f"/api/enclosures/{self.cage.pk}/").json()["item"]
        self.assertFalse(item["historyReceipt"]["behindCurrent"])
        self.assertIsNone(item["historyReceipt"]["receivedAt"])

    def history_points(self, end=None):
        return self.browser.get(f"/api/enclosures/{self.cage.pk}/history/",
            {"hours": 24, "end": end or self.body["sent_at"]}).json()["points"]

    def test_fresh_snapshots_accumulate_once_and_keep_first_receipt(self):
        self.body["events"] = []
        start = timezone.now() - timedelta(seconds=20)
        for index in range(3):
            stamp = start + timedelta(seconds=index)
            self.body["sent_at"] = (stamp + timedelta(seconds=1)).isoformat()
            telemetry = self.body["gateway"]["cages"][0]["state"]["telemetry"]
            telemetry.update(message_id=str(uuid.uuid4()), sampled_at=stamp.isoformat(), received_at=stamp.isoformat())
            telemetry["readings"]["T1"]["value"] = 18.6 + index
            self.assertEqual(self.send().json()["accepted_event_ids"], [])
        self.login()
        points = self.history_points()
        self.assertEqual(len(points), 3)
        self.assertEqual([p["readings"]["T1"]["value"] for p in points], [18.6, 19.6, 20.6])
        self.assertTrue(all(p["receiptSource"] == "snapshot" and p["piEventId"] is None for p in points))
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.history_points(), points)
        self.assertEqual(Event.objects.count(), 0)

    def test_late_event_reconciles_snapshot_without_duplicate_or_changed_receipt(self):
        event = copy.deepcopy(self.body["events"][-1])
        self.assertEqual(event["kind"], "telemetry.recorded")
        self.body["events"] = []
        self.assertEqual(self.send().status_code, 200)
        self.login()
        before = self.history_points()
        self.assertEqual(len(before), 1)
        self.body["events"] = [event]
        self.assertEqual(self.send().json()["accepted_event_ids"], [event["event_id"]])
        after = self.history_points()
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["id"], before[0]["id"])
        self.assertEqual(after[0]["serverReceivedAt"], before[0]["serverReceivedAt"])
        self.assertEqual(after[0]["receiptSource"], "event")
        self.assertEqual(after[0]["piEventId"], event["event_id"])
        self.assertEqual(Event.objects.count(), 1)

    def test_late_snapshot_does_not_overwrite_event_measurement(self):
        self.send()
        self.login()
        before = self.history_points()
        self.body["events"] = []
        self.body["gateway"]["cages"][0]["state"]["telemetry"]["readings"]["T1"]["value"] = 99.0
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.history_points(), before)

    def test_late_older_measurement_fills_history_without_rewinding_current(self):
        self.body["events"] = []
        self.send()
        current = CurrentState.objects.get().sampled_at
        telemetry = self.body["gateway"]["cages"][0]["state"]["telemetry"]
        telemetry.update(message_id=str(uuid.uuid4()), sampled_at=(current-timedelta(hours=1)).isoformat())
        self.assertEqual(self.send().status_code, 200)
        self.login()
        self.assertEqual(len(self.history_points()), 2)
        self.assertEqual(CurrentState.objects.get().sampled_at, current)

    def test_measurement_storage_failure_rolls_back_events_and_current_without_ack(self):
        with patch.object(Measurement.objects, "select_related", side_effect=OperationalError("history storage failure")):
            response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("accepted_event_ids", response.json())
        self.assertEqual(Measurement.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(CurrentState.objects.count(), 0)
        self.assertIsNone(Gateway.objects.get().last_received_at)

    def test_snapshot_history_is_scoped_to_account(self):
        self.body["events"] = []
        self.send()
        self.login("manager", Store.objects.create(name="Other"))
        self.assertEqual(self.browser.get(f"/api/enclosures/{self.cage.pk}/history/").status_code, 404)
        self.assertEqual(Measurement.objects.count(), 1)
