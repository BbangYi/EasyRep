from urllib.parse import parse_qs, urlsplit

from django.test import TestCase, override_settings

from . import test_husbandry as husbandry_tests
from .models import AuditEvent, CareRecord


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    AXES_ENABLED=False,
)
class CareNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        husbandry_tests.HusbandryTests.setUpTestData.__func__(cls)

    # Reuse established fixtures without inheriting and duplicating their test cases.
    login = husbandry_tests.HusbandryTests.login
    payload = husbandry_tests.HusbandryTests.payload
    record = husbandry_tests.HusbandryTests.record
    create_url = husbandry_tests.HusbandryTests.create_url

    def assert_care_destination(self, target, saved=False):
        url = urlsplit(target)
        self.assertEqual((url.scheme, url.netloc, url.path), ("", "", "/"))
        self.assertEqual(url.fragment.partition("?")[0], f"history/{self.a.pk}")
        self.assertEqual(parse_qs(url.fragment.partition("?")[2]), {"section": ["care"]})
        self.assertEqual(parse_qs(url.query), {"care_saved": [self.a.pk]} if saved else {})

    def assert_back(self, response):
        self.assertEqual(response.status_code, 200)
        self.assert_care_destination(response.context["back"])
        self.assertContains(response, f'<a class="back" href="{response.context["back"]}">돌아가기</a>', html=True)

    def test_create_back_preserves_draft_and_validation_states(self):
        self.login(self.manager)
        form = self.client.get(self.create_url)
        self.assert_back(form)
        self.assertContains(form, f"habitatos:care-draft:{self.manager.pk}:{self.a.pk}")
        for changes in ({"kind": "weight", "weight_g": ""}, {"submission": "expired-or-tampered"}):
            with self.subTest(changes=changes):
                data = self.payload(note="보존할 내용", **changes)
                response = self.client.post(self.create_url, data)
                self.assert_back(response)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(response.context["form"]["note"].value(), data["note"])
        self.assertFalse(CareRecord.objects.exists())

    def test_create_success_and_replay_keep_saved_query_marker(self):
        self.login(self.manager)
        data = self.payload()
        locations = []
        for _ in range(2):
            response = self.client.post(self.create_url, data)
            self.assertEqual(response.status_code, 302)
            self.assert_care_destination(response["Location"], saved=True)
            locations.append(response["Location"])
        self.assertEqual(locations[0], locations[1])
        self.assertEqual(CareRecord.objects.count(), 1)
        self.assertEqual(CareRecord.objects.get().note, data["note"])
        self.assertEqual(AuditEvent.objects.filter(action="사육 관리 기록 작성").count(), 1)

    def test_void_forms_success_and_replay_return_to_care(self):
        row = self.record()
        original = (row.note, row.kind, row.occurred_at, row.created_by_id)
        self.login(self.manager)
        url = f"/manage/enclosures/{self.a.pk}/care/{row.pk}/void/"
        self.assert_back(self.client.get(url))
        invalid = self.client.post(url, {"reason": " "})
        self.assert_back(invalid)
        self.assertTrue(invalid.context["form"].errors)
        row.refresh_from_db()
        self.assertIsNone(row.voided_at)
        first_voided_at = None
        for reason in ("중복 입력", "덮어쓰기 시도"):
            response = self.client.post(url, {"reason": reason})
            self.assertEqual(response.status_code, 302)
            self.assert_care_destination(response["Location"])
            row.refresh_from_db()
            self.assertEqual((row.note, row.kind, row.occurred_at, row.created_by_id), original)
            self.assertEqual(row.void_reason, "중복 입력")
            self.assertEqual(row.voided_by, self.manager)
            self.assertIsNotNone(row.voided_at)
            if first_voided_at is not None:
                self.assertEqual(row.voided_at, first_voided_at)
            first_voided_at = row.voided_at
        already_voided = self.client.get(url)
        self.assert_back(already_voided)
        self.assertContains(already_voided, "이미 취소된 기록입니다.")
        self.assertNotContains(already_voided, '<form method="post"')
        self.assertEqual(AuditEvent.objects.filter(action="사육 관리 기록 취소").count(), 1)

    def test_login_return_and_form_scope_remain_unchanged(self):
        row = self.record()
        urls = [self.create_url, f"/manage/enclosures/{self.a.pk}/care/{row.pk}/void/"]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(parse_qs(urlsplit(response["Location"]).query), {"next": [url]})
        self.login(self.member)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.other.role = "manager"
        self.other.save(update_fields=["role"])
        self.login(self.other)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.manager)
        self.assertEqual(self.client.get(f"/manage/enclosures/{self.b.pk}/care/{row.pk}/void/").status_code, 404)

    def test_enclosure_registration_back_is_unchanged(self):
        self.login(self.owner)
        response = self.client.get("/manage/enclosures/new/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["back"], "/manage/")
