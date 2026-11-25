from datetime import datetime, timedelta, timezone
import uuid
from django.test import TestCase, override_settings
from habitat.models import CareRecord, Enclosure, Store, User
from .models import CurrentState, Event, Gateway, Measurement
from .overview import KstBucket


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OverviewTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="Overview test")
        self.cage = Enclosure.objects.create(id="overview", name="Overview", store=self.store)
        self.gateway = Gateway.objects.create(store=self.store, edge_gateway_id="PI-TEST", token_digest="test")
        self.user = User.objects.create_user(username="overview", role="owner")
        self.client.force_login(self.user)
        self.end = datetime(2026, 10, 25, 6, tzinfo=timezone.utc)
        self.at = self.end - timedelta(hours=2)
        CurrentState.objects.create(enclosure=self.cage, configuration={"geometry_revision": 1, "placement_revision": 1, "sensors": [{"id": "T1", "unit": "degC"}]})
        self.url = f"/api/enclosures/{self.cage.pk}/overview/"

    def row(self, value=20, source="sensor", revision=1, quality="valid", at=None):
        return Measurement(gateway=self.gateway, enclosure=self.cage, message_id=uuid.uuid4(), sampled_at=at or self.at, payload={"data_source": source, "geometry_revision": revision, "placement_revision": 1, "readings": {"T1": {"value": value, "quality": quality}}})

    def get(self, **params):
        return self.client.get(self.url, {"days": 1, "end": self.end.isoformat(), **params})

    def test_aggregates_all_samples_beyond_raw_history_limit_and_preserves_gaps(self):
        Measurement.objects.bulk_create([self.row(20) for _ in range(2001)] + [self.row(24)])
        response = self.get()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["period"]["sensorCount"], 2002)
        self.assertEqual(data["lifetime"]["sensorCount"], 2002)
        sensor = data["sensors"][0]
        self.assertEqual(sensor["count"], 2002)
        self.assertAlmostEqual(sensor["avg"], (2001 * 20 + 24) / 2002)
        self.assertEqual((sensor["min"], sensor["max"]), (20, 24))
        self.assertEqual(len([b for b in data["buckets"] if b["readings"].get("T1")]), 1)
        self.assertTrue(any(not b["readings"] for b in data["buckets"]))
        self.assertLessEqual(len(data["buckets"]), 25)

    def test_separates_simulation_old_configuration_and_invalid_readings(self):
        Measurement.objects.bulk_create([self.row(20), self.row(999, source="simulation"), self.row(888, revision=2), self.row(None, quality="missing"), self.row(10, at=self.at-timedelta(days=40))])
        data = self.get().json()
        self.assertEqual(data["period"]["sensorCount"], 3)
        self.assertEqual(data["period"]["otherSourceCount"], 1)
        self.assertEqual(data["period"]["otherConfigurationCount"], 1)
        self.assertEqual(data["sensors"][0]["count"], 1)
        self.assertEqual(data["sensors"][0]["invalidCount"], 1)
        self.assertEqual(data["sensors"][0]["avg"], 20)
        self.assertEqual(data["lifetime"]["sensorCount"], 4)
        self.assertEqual(data["period"]["start"], (self.end-timedelta(days=1)).isoformat())

    def test_comprehensive_counts_separate_command_updates_and_active_care(self):
        command_id = str(uuid.uuid4())
        for i, status in enumerate(["published", "applied"]):
            Event.objects.create(gateway=self.gateway, enclosure=self.cage, event_id=uuid.uuid4(), event_sequence=i+1, kind="command.updated", created_at=self.at, digest="test", body={"payload": {"command_id": command_id, "status": status}})
        CareRecord.objects.create(enclosure=self.cage, kind="feeding", occurred_at=self.at, note="test", created_by=self.user)
        CareRecord.objects.create(enclosure=self.cage, kind="cleaning", occurred_at=self.at, created_by=self.user, voided_at=self.end, voided_by=self.user, void_reason="test")
        data = self.get().json()
        self.assertEqual(data["commands"], {"count": 1, "updates": 2})
        self.assertEqual(data["care"], {"count": 1, "kinds": {"feeding": 1}})
        self.assertEqual(sum(b["careCount"] for b in data["buckets"]), 1)

    def test_period_validation_empty_and_account_scope(self):
        self.assertEqual(self.get(days=30).status_code, 200)
        self.assertEqual(self.get(days=30).json()["sensors"][0]["avg"], None)
        for params in [{"days": 2}, {"end": "invalid"}, {"end": "2026-10-25T00:00:00"}]:
            self.assertEqual(self.get(**params).status_code, 400)
        self.user.role = "manager"
        self.user.store = Store.objects.create(name="Other")
        self.user.save()
        self.client.force_login(self.user)
        self.assertEqual(self.get().status_code, 404)
        self.client.logout()
        self.assertEqual(self.get().status_code, 401)

    def test_boundaries_kst_days_and_future_records(self):
        Measurement.objects.bulk_create([self.row(at=self.end-timedelta(days=7)), self.row(at=self.end), self.row(at=self.end+timedelta(seconds=1))])
        data = self.get(days=7).json()
        self.assertEqual(data["period"]["sensorCount"], 2)
        self.assertEqual(sum(b["sensorCount"] for b in data["buckets"]), 2)
        self.assertTrue(all(datetime.fromisoformat(b["at"]).hour == 0 for b in data["buckets"]))
        self.assertEqual(data["lifetime"]["sensorCount"], 2)

    def test_kst_bucket_uses_database_datetime_and_keeps_kst_offset(self):
        row = self.row(at=datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc))
        row.save()
        buckets = list(Measurement.objects.filter(enclosure=self.cage).annotate(bucket=KstBucket("sampled_at", hourly=False)).values_list("bucket", flat=True))
        self.assertEqual(buckets, ["2026-10-25T00:00:00+09:00"])
