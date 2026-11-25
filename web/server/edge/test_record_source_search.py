import copy
from datetime import datetime
import uuid

from django.test import TestCase, override_settings

from habitat.models import Enclosure, Store, User
from .contracts import TelemetryEvent
from .models import Event, Gateway
from .tests import FIXTURE


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class RecordSourceSearchTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="검색 검증 매장")
        self.cage = Enclosure.objects.create(id="source-search", name="검색 검증", store=self.store)
        self.gateway = Gateway.objects.create(
            store=self.store, edge_gateway_id="SEARCH-TEST", token_digest="local-search-fixture",
        )
        self.user = User.objects.create_user(username="source-search", role="manager", store=self.store)
        self.client.force_login(self.user)
        self.url = f"/api/enclosures/{self.cage.pk}/records/"
        self.sequence = 0

    def telemetry(self, source, sensor="T1", cage=None):
        self.sequence += 1
        body = copy.deepcopy(next(e for e in FIXTURE["events"] if e["kind"] == "telemetry.recorded"))
        body["event_id"] = str(uuid.uuid4())
        body["event_sequence"] = self.sequence
        body["payload"]["message_id"] = str(uuid.uuid4())
        body["payload"]["data_source"] = source
        body["payload"]["readings"] = {sensor: {"value": 24.0, "quality": "valid"}}
        TelemetryEvent.model_validate(body)
        return Event.objects.create(
            gateway=self.gateway, enclosure=cage or self.cage,
            event_id=body["event_id"], event_sequence=self.sequence,
            kind=body["kind"], created_at=datetime.fromisoformat(body["created_at"]),
            digest="search-fixture", body=body,
        )

    def search(self, keyword="", **params):
        response = self.client.get(self.url, {"q": keyword, **params})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def assert_ids(self, keyword, expected, **params):
        page = self.search(keyword, **params)
        self.assertCountEqual([row["id"] for row in page["items"]], [str(e.event_id) for e in expected])
        self.assertIsNone(page["next"])

    def test_visible_source_labels_and_existing_keywords(self):
        sensor = self.telemetry("sensor")
        simulation = self.telemetry("simulation")
        for keyword, expected in [
            ("", [sensor, simulation]), ("환경 측정", [sensor, simulation]),
            ("T1", [sensor, simulation]), ("가상 데이터", [simulation]),
            ("센서 데이터", [sensor]), ("센서", [sensor]), ("데이터", [sensor, simulation]),
        ]:
            with self.subTest(keyword=keyword):
                self.assert_ids(keyword, expected)

    def test_source_labels_preserve_and_combinations_and_kind(self):
        sensor_t1 = self.telemetry("sensor")
        sensor_t9 = self.telemetry("sensor", sensor="T9")
        simulation = self.telemetry("simulation")
        for keyword, expected in [
            ("환경 측정 센서 데이터", [sensor_t1, sensor_t9]),
            ("센서 데이터 T1", [sensor_t1]), ("데이터 T1", [sensor_t1, simulation]),
            ("환경 · 측정 · 센서 데이터 T9", [sensor_t9]),
            ("가상 데이터 T1", [simulation]), ("센서 가상 데이터", []),
            ("센서 데이터 T99", []), ("명령 처리 센서 데이터", []),
        ]:
            with self.subTest(keyword=keyword):
                self.assert_ids(keyword, expected)
        self.assert_ids("센서 데이터", [sensor_t1, sensor_t9], kind="telemetry.recorded")
        self.assert_ids("센서 데이터", [], kind="command.updated")

    def test_source_aliases_exclude_unknown_missing_and_nontelemetry_rows(self):
        sensor = self.telemetry("sensor")
        simulation = self.telemetry("simulation")
        # Deliberately stored legacy/invalid rows test lookup boundaries, not ingestion acceptance.
        for source in ("unverified", None):
            row = self.telemetry("sensor")
            if source is None:
                del row.body["payload"]["data_source"]
            else:
                row.body["payload"]["data_source"] = source
            row.save(update_fields=["body"])
        for source in ("sensor", "simulation"):
            row = self.telemetry(source)
            row.kind = "command.updated"
            row.body["kind"] = row.kind
            row.save(update_fields=["kind", "body"])
        self.assertEqual(len(self.search()["items"]), 6)
        self.assert_ids("센서", [sensor])
        self.assert_ids("센서 데이터", [sensor])
        self.assert_ids("가상 데이터", [simulation])
        self.assert_ids("데이터", [sensor, simulation])

    def test_source_search_keeps_enclosure_and_account_scope(self):
        own = self.telemetry("sensor")
        sibling = Enclosure.objects.create(id="sibling-search", name="같은 매장", store=self.store)
        self.telemetry("sensor", cage=sibling)
        outside = Enclosure.objects.create(
            id="outside-search", name="다른 매장", store=Store.objects.create(name="외부 매장"),
        )
        self.telemetry("sensor", cage=outside)
        self.assert_ids("센서 데이터", [own])
        self.assertEqual(self.client.get(f"/api/enclosures/{outside.pk}/records/", {"q": "센서 데이터"}).status_code, 404)
        self.user.store = outside.store
        self.user.save(update_fields=["store"])
        self.assertEqual(self.client.get(self.url, {"q": "센서 데이터"}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url, {"q": "센서 데이터"}).status_code, 401)

    def test_source_cursor_keeps_filter_and_equal_timestamp_boundary(self):
        expected = []
        for _ in range(55):
            expected.append(self.telemetry("sensor"))
            self.telemetry("simulation")
        first = self.search("센서 데이터 T1", kind="telemetry.recorded")
        self.assertEqual(len(first["items"]), 50)
        self.assertIsNotNone(first["next"])
        stamp, key = first["next"].rsplit("|", 1)
        self.assertIsNotNone(datetime.fromisoformat(stamp).utcoffset())
        self.assertEqual(int(key), expected[5].pk)
        second = self.search("센서 데이터 T1", kind="telemetry.recorded", before=first["next"])
        self.assertEqual(len(second["items"]), 5)
        self.assertIsNone(second["next"])
        rows = first["items"] + second["items"]
        ids = [row["id"] for row in rows]
        self.assertEqual(ids, [str(row.event_id) for row in reversed(expected)])
        self.assertEqual(len(set(ids)), 55)
        self.assertTrue(all(row["payload"]["data_source"] == "sensor" for row in rows))
        self.assert_ids("명령 처리 센서 데이터", [], before=first["next"])
