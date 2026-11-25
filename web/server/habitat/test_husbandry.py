from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import uuid
from django.db import connection, IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from . import tests as access_tests
from .husbandry import new_submission
from .models import AuditEvent, CareRecord, Enclosure


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    AXES_ENABLED=False,
)
class HusbandryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        access_tests.AccessTests.setUpTestData.__func__(cls)

    def login(self, user, client=None):
        self.client = client or Client()
        return access_tests.AccessTests.login(self, user, self.client)

    @property
    def create_url(self):
        return f"/manage/enclosures/{self.a.pk}/care/new/"

    @property
    def list_url(self):
        return f"/api/enclosures/{self.a.pk}/care/"

    def payload(self, **changes):
        return {
            "submission": new_submission(self.manager, self.a.pk),
            "kind": "feeding",
            "occurred_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "note": "먹이 교체",
            "weight_g": "",
            **changes,
        }

    def record(self, **changes):
        return CareRecord.objects.create(
            enclosure=self.a,
            created_by=self.manager,
            kind="feeding",
            occurred_at=timezone.now(),
            note="급여 확인",
            **changes,
        )

    def test_register_without_device_and_duplicate_submission(self):
        self.login(self.owner)
        data = {
            "name": "장치 없는 사육장",
            "store": self.store_a.pk,
            "species": "크레스티드 게코",
            "location": "상단",
            "submission": new_submission(self.owner, "enclosure"),
            "edge_cage_id": "FORGED",
        }
        first = self.client.post("/manage/enclosures/new/", data)
        second = self.client.post("/manage/enclosures/new/", data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first["Location"], second["Location"])
        item = Enclosure.objects.get(name=data["name"])
        self.assertIsNone(item.edge_cage_id)
        result = self.client.get(f"/api/enclosures/{item.pk}/").json()["item"]
        self.assertEqual(result["gateway"]["status"], "unregistered")
        self.assertEqual(result["sensors"], [])
        self.assertIsNone(result["sampledAt"])
        self.assertEqual(result["species"], data["species"])
        self.assertEqual(AuditEvent.objects.filter(action="사육장 등록").count(), 1)
        self.login(self.manager)
        self.assertEqual(
            self.client.post("/manage/enclosures/new/", data).status_code, 403
        )

    def test_scope_and_read_only_member(self):
        record = self.record()
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.assertEqual(self.client.get(self.create_url).status_code, 302)
        self.login(self.member)
        self.assertEqual(len(self.client.get(self.list_url).json()["items"]), 1)
        self.assertEqual(
            self.client.post(self.create_url, self.payload()).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                f"/manage/enclosures/{self.a.pk}/care/{record.pk}/void/",
                {"reason": "bad"},
            ).status_code,
            403,
        )
        self.member.enclosures.clear()
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        self.login(self.manager)
        self.assertEqual(
            self.client.post(
                f"/manage/enclosures/{self.b.pk}/care/new/", self.payload()
            ).status_code,
            404,
        )
        self.login(self.other)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)

    def test_create_replay_and_server_owned_fields(self):
        self.login(self.manager)
        data = self.payload(
            enclosure=self.b.pk,
            created_by=self.other.pk,
            source="sensor",
            void_reason="forged",
        )
        for _ in range(2):
            self.assertEqual(self.client.post(self.create_url, data).status_code, 302)
        row = CareRecord.objects.get()
        self.assertEqual(row.enclosure, self.a)
        self.assertEqual(row.created_by, self.manager)
        self.assertEqual(row.void_reason, "")
        self.assertEqual(
            AuditEvent.objects.filter(action="사육 관리 기록 작성").count(), 1
        )
        response = self.client.get(self.list_url)
        self.assertIn("no-store", response["Cache-Control"])

    def test_invalid_input_and_tampered_submission(self):
        self.login(self.manager)
        invalid = [
            {"kind": "unknown"},
            {"kind": "weight"},
            {"kind": "weight", "weight_g": "0"},
            {"kind": "weight", "weight_g": "NaN"},
            {"kind": "weight", "weight_g": "1000001"},
            {"weight_g": "12"},
            {"note": " "},
            {"note": "x" * 2001},
            {"occurred_at": "wrong"},
            {
                "occurred_at": (timezone.localtime() + timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                )
            },
            {"submission": "forged"},
            {"submission": new_submission(self.owner, self.a.pk)},
        ]
        for changes in invalid:
            with self.subTest(changes=list(changes)):
                response = self.client.post(self.create_url, self.payload(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertFalse(CareRecord.objects.exists())
        self.assertEqual(
            self.client.post(
                self.create_url, self.payload(kind="weight", weight_g="42.35", note="")
            ).status_code,
            302,
        )
        self.assertEqual(CareRecord.objects.get().weight_g, Decimal("42.35"))

    def test_csrf_all_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(
            self.owner, backend="django.contrib.auth.backends.ModelBackend"
        )
        row = self.record()
        for url in (
            self.create_url,
            "/manage/enclosures/new/",
            f"/manage/enclosures/{self.a.pk}/care/{row.pk}/void/",
        ):
            self.assertEqual(client.post(url, {}).status_code, 403)

    def test_void_preserves_original_and_is_idempotent(self):
        row = self.record()
        self.login(self.manager)
        url = f"/manage/enclosures/{self.a.pk}/care/{row.pk}/void/"
        self.assertTrue(self.client.post(url, {"reason": " "}).context["form"].errors)
        self.assertEqual(
            self.client.post(url, {"reason": "중복 입력"}).status_code, 302
        )
        self.client.post(url, {"reason": "overwrite"})
        row.refresh_from_db()
        self.assertEqual(row.note, "급여 확인")
        self.assertEqual(row.void_reason, "중복 입력")
        self.assertEqual(row.voided_by, self.manager)
        self.assertEqual(len(self.client.get(self.list_url).json()["items"]), 0)
        self.assertEqual(
            len(self.client.get(self.list_url + "?status=voided").json()["items"]), 1
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="사육 관리 기록 취소").count(), 1
        )

    def test_filters_kst_day_and_stable_cursor(self):
        self.login(self.manager)
        stamp = timezone.now() - timedelta(days=2)
        rows = [
            CareRecord(
                enclosure=self.a,
                created_by=self.manager,
                kind="cleaning",
                note="바닥 청소",
                occurred_at=stamp,
            )
            for _ in range(23)
        ]
        CareRecord.objects.bulk_create(rows)
        CareRecord.objects.create(
            enclosure=self.b,
            created_by=self.owner,
            kind="cleaning",
            note="비공개",
            occurred_at=stamp,
        )
        day = timezone.localtime(stamp).date().isoformat()
        filters = {"kind": "cleaning", "q": "청소", "from": day, "to": day}
        first = self.client.get(self.list_url, filters).json()
        second = self.client.get(
            self.list_url, {**filters, "before": first["next"]}
        ).json()
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 3)
        self.assertFalse(
            {row["id"] for row in first["items"]}
            & {row["id"] for row in second["items"]}
        )
        self.assertIsNone(second["next"])
        for filters in (
            {"kind": "invalid"},
            {"status": "invalid"},
            {"q": "a" * 81},
            {"from": "bad"},
            {"from": "2026-09-30", "to": "2026-09-01"},
            {"before": "bad"},
            {"before": f"2026-09-01T00:00:00|{uuid.uuid4()}"},
        ):
            self.assertEqual(self.client.get(self.list_url, filters).status_code, 400)

    def test_query_cost_is_constant_and_index_exists(self):
        self.login(self.manager)
        self.record()
        with CaptureQueriesContext(connection) as first:
            self.client.get(self.list_url)
        for _ in range(24):
            self.record()
        with CaptureQueriesContext(connection) as second:
            response = self.client.get(self.list_url)
        self.assertEqual(len(first), len(second))
        self.assertEqual(len(response.json()["items"]), 20)
        sql = " ".join(q["sql"] for q in second)
        self.assertIn("LIMIT 21", sql)
        self.assertNotIn("COUNT(", sql)
        with connection.cursor() as cursor:
            indexes = connection.introspection.get_constraints(
                cursor, CareRecord._meta.db_table
            )
        self.assertTrue(indexes["care_enclosure_time"]["index"])
        self.assertTrue(indexes["care_kind_time"]["index"])

    def test_audit_failure_rolls_back_and_history_blocks_store_move(self):
        self.login(self.manager)
        with patch(
            "habitat.husbandry.AuditEvent.objects.create",
            side_effect=RuntimeError("fixture"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(self.create_url, self.payload())
        self.assertFalse(CareRecord.objects.exists())
        self.record()
        self.login(self.owner)
        response = self.client.post(
            f"/manage/enclosures/{self.a.pk}/",
            {"name": self.a.name, "store": self.store_b.pk},
        )
        self.assertContains(response, "기존 이력을 보존")
        self.a.refresh_from_db()
        self.assertEqual(self.a.store, self.store_a)

    def test_html_escaping_and_database_validation(self):
        row = self.record()
        row.note = '<script>alert("x")</script>'
        row.save()
        self.login(self.manager)
        response = self.client.get(
            f"/manage/enclosures/{self.a.pk}/care/{row.pk}/void/"
        )
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CareRecord.objects.filter(pk=row.pk).update(kind="weight", weight_g=None)

    def test_old_enclosure_insert_remains_compatible(self):
        # A code rollback must still allow the prior registration command to write.
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO habitat_enclosure (id, name, store_id, edge_cage_id) VALUES (%s, %s, %s, NULL)",
                ["old-writer", "기존 등록 방식", self.store_a.pk],
            )
        item = Enclosure.objects.get(pk="old-writer")
        self.assertEqual((item.species, item.location), ("", ""))

    def test_form_expiry_preserves_content_and_reissues_submission(self):
        self.login(self.manager)
        data = self.payload(submission="expired-or-tampered", note="보존할 관리 내용")
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form["note"].value(), data["note"])
        self.assertNotEqual(form["submission"].value(), data["submission"])
        self.assertFalse(CareRecord.objects.exists())
        data["submission"] = form["submission"].value()
        saved = self.client.post(self.create_url, data)
        self.assertEqual(saved["Location"], f"/?care_saved={self.a.pk}#history/{self.a.pk}?section=care")
        self.assertEqual(CareRecord.objects.get().note, data["note"])

    def test_signed_out_form_returns_after_login_and_scopes_draft(self):
        from urllib.parse import parse_qs, urlsplit
        response = self.client.get(self.create_url)
        self.assertEqual(parse_qs(urlsplit(response["Location"]).query)["next"], [self.create_url])
        self.login(self.manager)
        response = self.client.get(self.create_url)
        self.assertContains(response, f"habitatos:care-draft:{self.manager.pk}:{self.a.pk}")
        self.assertContains(response, 'id="care-form"')
