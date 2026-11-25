from datetime import datetime, timedelta, timezone
import uuid
from django.test import TestCase, override_settings
from habitat.models import Enclosure, Store, User
from .models import Gateway, Measurement


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class HistoryPaginationTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="Pagination test")
        self.cage = Enclosure.objects.create(id="pagination", name="Pagination", store=self.store)
        self.gateway = Gateway.objects.create(store=self.store, edge_gateway_id="TEST", token_digest="local-fixture")
        self.user = User.objects.create_user(username="pagination", role="owner")
        self.client.force_login(self.user)
        self.end = datetime(2026, 11, 4, 6, 0, 0, 123456, tzinfo=timezone.utc)
        self.at = self.end - timedelta(minutes=5)
        self.url = f"/api/enclosures/{self.cage.pk}/history/"

    def row(self, number, at=None, received=None, cage=None):
        return Measurement(id=uuid.UUID(int=number), message_id=uuid.UUID(int=number), gateway=self.gateway,
            enclosure=cage or self.cage, sampled_at=at or self.at, received_at=received or self.at,
            payload={"data_source": "sensor", "geometry_revision": 1, "placement_revision": 1,
                "readings": {"T1": {"value": 24, "quality": "valid"}}})

    def get(self, **params):
        return self.client.get(self.url, {"hours": 6, "end": self.end.isoformat(), **params})

    def pages(self):
        pages, cursor, seen = [], None, set()
        for _ in range(8):
            response = self.get(**({"before": cursor} if cursor else {}))
            self.assertEqual(response.status_code, 200, response.content)
            page = response.json()
            pages.append(page)
            self.assertLessEqual(len(page["points"]), 2000)
            self.assertEqual(page["start"], (self.end - timedelta(hours=6)).isoformat())
            self.assertEqual(page["end"], self.end.isoformat())
            cursor = page.get("next")
            if not cursor:
                self.assertFalse(page["truncated"])
                return pages
            self.assertNotIn(cursor, seen)
            seen.add(cursor)
        self.fail("pagination did not terminate")

    def test_2002_equal_timestamps_are_each_reachable_once(self):
        Measurement.objects.bulk_create([self.row(i) for i in range(1, 2003)])
        first = self.get().json()
        # Current old-client request demonstrates the reported omission at the endpoint.
        legacy_end = datetime.fromisoformat(first["olderThan"]) - timedelta(milliseconds=1)
        self.assertEqual(len(self.get(end=legacy_end.isoformat()).json()["points"]), 0)
        self.assertTrue(first.get("next"), "2000 returned, but same-time remaining two need a complete cursor")
        pages = self.pages()
        self.assertEqual([len(p["points"]) for p in pages], [2000, 2])
        ids = [point["id"] for page in pages for point in page["points"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {str(uuid.UUID(int=i)) for i in range(1, 2003)})
        self.assertEqual([p["id"] for p in pages[0]["points"]], [str(uuid.UUID(int=i)) for i in range(3, 2003)])
        self.assertEqual(pages[0]["olderThan"], self.at.isoformat())
        self.assertIsNone(pages[-1]["next"])

    def test_mixed_microseconds_receive_ties_and_multiple_pages(self):
        rows = [self.row(i, self.at + timedelta(microseconds=i // 1700), self.at + timedelta(microseconds=(i // 5) % 3)) for i in range(1, 4004)]
        Measurement.objects.bulk_create(rows)
        expected = sorted(rows, key=lambda r: (r.sampled_at, r.received_at, r.pk), reverse=True)
        pages = self.pages()
        self.assertEqual([len(p["points"]) for p in pages], [2000, 2000, 3])
        flattened = [point["id"] for p in pages for point in reversed(p["points"])]
        self.assertEqual(flattened, [str(r.pk) for r in expected])
        self.assertIn(".123457", pages[0]["next"])

    def test_empty_exact_limit_and_limit_plus_one(self):
        self.assertEqual(self.get().json()["points"], [])
        self.assertIsNone(self.get().json().get("next"))
        Measurement.objects.bulk_create([self.row(i) for i in range(1, 2001)])
        exact = self.get().json()
        self.assertEqual(len(exact["points"]), 2000)
        self.assertFalse(exact["truncated"])
        self.assertIsNone(exact["olderThan"])
        self.assertIsNone(exact.get("next"))
        self.row(2001).save()
        self.assertEqual([len(p["points"]) for p in self.pages()], [2000, 1])

    def test_cursor_keeps_explicit_time_window_and_timezone_precision(self):
        start = self.end - timedelta(hours=6)
        Measurement.objects.bulk_create([self.row(1, start - timedelta(microseconds=1)), self.row(2, start), self.row(3, self.end), self.row(4, self.end + timedelta(microseconds=1))])
        cursor = f"{self.end.isoformat()}|{self.at.isoformat()}|{uuid.UUID(int=3)}"
        data = self.get(before=cursor).json()
        self.assertEqual([p["id"] for p in data["points"]], [str(uuid.UUID(int=2))])
        self.assertEqual(self.get(hours=1, before=cursor).json()["points"], [])
        korean = self.end.astimezone(timezone(timedelta(hours=9))).isoformat()
        self.assertEqual(self.get(end=korean, before=cursor).json()["points"], data["points"])

    def test_invalid_cursor_period_and_aware_timestamps(self):
        valid_id = str(uuid.UUID(int=1))
        for cursor in ["", "garbage", "a|b|c", f"{self.at.isoformat()}|{self.at.isoformat()}|bad", f"2026-11-04|{self.at.isoformat()}|{valid_id}", f"{self.at.isoformat()}|2026-11-04|{valid_id}", f"{self.at.isoformat()}|{self.at.isoformat()}|{valid_id}|extra"]:
            with self.subTest(cursor=cursor):
                response = self.get(before=cursor)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "invalid_cursor")
        for params in [{"hours": 2}, {"end": "bad"}, {"end": "2026-11-04"}, {"end": "0001-01-01T00:00:00+00:00"}]:
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 400)

    def test_cursor_never_bypasses_login_or_enclosure_scope(self):
        other_store = Store.objects.create(name="Other")
        other = Enclosure.objects.create(id="other-pagination", name="Other", store=other_store)
        Measurement.objects.bulk_create([self.row(1), self.row(2, cage=other)])
        cursor = f"{self.at.isoformat()}|{self.at.isoformat()}|{uuid.UUID(int=2)}"
        own = self.get(before=cursor).json()
        self.assertEqual([p["id"] for p in own["points"]], [str(uuid.UUID(int=1))])
        self.user.role = "manager"
        self.user.store = other_store
        self.user.save()
        self.client.force_login(self.user)
        self.assertEqual(self.get(before=cursor).status_code, 404)
        self.client.logout()
        self.assertEqual(self.get(before=cursor).status_code, 401)

    def test_moving_window_preserves_ties_and_older_window_access(self):
        older = self.row(2003, at=self.end - timedelta(hours=6, minutes=1))
        Measurement.objects.bulk_create([self.row(i) for i in range(1, 2003)] + [older])
        first = self.get().json()
        fixed = self.get(before=first["next"], end=first["end"]).json()
        self.assertEqual([p["id"] for p in fixed["points"]], [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))])
        moving = self.get(before=first["next"], end=first["olderThan"]).json()
        self.assertEqual([p["id"] for p in moving["points"]], [str(older.pk), str(uuid.UUID(int=1)), str(uuid.UUID(int=2))])
        self.assertEqual(moving["end"], self.at.isoformat())
        self.assertIsNone(moving["next"])
        ids = [p["id"] for page in [first, moving] for p in page["points"]]
        self.assertEqual(len(ids), 2003)
        self.assertEqual(len(set(ids)), 2003)
