from urllib.parse import urlparse, parse_qs, urlencode
from django.test import Client, TestCase, override_settings
from .models import User, Store, Enclosure, SiteSettings, AuditEvent
from .views import activation_link


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    AXES_ENABLED=False,
)
class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.store_a = Store.objects.create(name="A")
        cls.store_b = Store.objects.create(name="B")
        cls.a = Enclosure.objects.create(
            id="crested-01", name="A 사육장", store=cls.store_a
        )
        cls.b = Enclosure.objects.create(
            id="python-03", name="B 사육장", store=cls.store_b
        )
        cls.owner = User.objects.create_user(
            username="habitatosdevel",
            password="Testing-password-7382",
            display_name="총괄",
            role="owner",
        )
        cls.manager = User.objects.create_user(
            username="manager@example.com",
            password="Testing-password-7382",
            display_name="관리자",
            role="manager",
            store=cls.store_a,
        )
        cls.member = User.objects.create_user(
            username="member@example.com",
            password="Testing-password-7382",
            display_name="사용자",
            role="user",
            store=cls.store_a,
        )
        cls.member.enclosures.add(cls.a)
        cls.other = User.objects.create_user(
            username="other@example.com",
            password="Testing-password-7382",
            display_name="다른 매장",
            role="user",
            store=cls.store_b,
        )
        SiteSettings.objects.create(pk=1)

    def login(self, user, client=None):
        client = client or self.client
        response = client.post(
            "/login/", {"username": user.username, "password": "Testing-password-7382"}
        )
        self.assertEqual(response.status_code, 302)
        return client

    def test_anonymous_html_and_api_are_blocked(self):
        for path in ("/", "/index.html", "/manage/", "/profile/", "/manage/site/"):
            self.assertRedirects(
                self.client.get(path), "/login/?" + urlencode({"next": path}), fetch_redirect_response=False
            )
        for path in ("/api/session/", "/api/enclosures/crested-01/"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertNotContains(self.client.get("/login/"), "manager@example.com")

    def test_devices_stay_signed_in_and_logout_only_ends_this_device(self):
        older = self.login(self.owner, Client())
        newer = self.login(self.owner, Client())
        self.assertEqual(older.get("/api/session/").status_code, 200)
        self.assertEqual(newer.get("/api/session/").status_code, 200)
        self.assertEqual(older.post("/logout/").status_code, 302)
        self.assertEqual(older.get("/api/session/").status_code, 401)
        self.assertEqual(newer.get("/api/session/").status_code, 200)

    def test_remember_device_survives_restart_but_expires(self):
        from django.conf import settings
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from datetime import timedelta
        response = self.client.post("/login/", {
            "username": self.owner.username, "password": "Testing-password-7382",
            "remember_device": "on",
        })
        self.assertEqual(response.status_code, 302)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertIn(str(cookie["max-age"]), ("2591999", "2592000"))
        self.assertTrue(cookie["httponly"])
        reopened = Client()
        reopened.cookies[settings.SESSION_COOKIE_NAME] = cookie.value
        self.assertEqual(reopened.get("/api/session/").status_code, 200)
        Session.objects.filter(session_key=cookie.value).update(expire_date=timezone.now()-timedelta(seconds=1))
        self.assertEqual(reopened.get("/api/session/").status_code, 401)

    def test_unchecked_remember_device_keeps_browser_session(self):
        from django.conf import settings
        self.login(self.owner)
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME]["expires"], "")

    def test_revocation_ends_every_remembered_device(self):
        import uuid
        first, second = Client(), Client()
        for client in (first, second):
            client.post("/login/", {"username": self.owner.username,
                "password": "Testing-password-7382", "remember_device": "on"})
        User.objects.filter(pk=self.owner.pk).update(session_generation=uuid.uuid4())
        self.assertEqual(first.get("/api/session/").status_code, 401)
        self.assertEqual(second.get("/api/session/").status_code, 401)

    def test_other_accounts_keep_single_device_policy(self):
        older = self.login(self.manager, Client())
        newer = self.login(self.manager, Client())
        self.assertEqual(older.get("/api/session/").status_code, 401)
        self.assertEqual(newer.get("/api/session/").status_code, 200)

    def test_shared_browser_tabs_keep_same_session(self):
        self.login(self.owner)
        for _ in range(3):
            self.assertEqual(self.client.get("/api/session/").status_code, 200)

    def test_scope_and_object_access_are_server_enforced(self):
        self.login(self.manager)
        data = self.client.get("/api/session/").json()
        self.assertEqual([x["id"] for x in data["enclosures"]], [self.a.pk])
        self.assertEqual(
            self.client.get(f"/api/enclosures/{self.b.pk}/").status_code, 404
        )
        self.assertNotContains(self.client.get("/manage/"), self.other.username)
        for target in (self.owner, self.other, self.manager):
            self.assertEqual(
                self.client.get(f"/manage/accounts/{target.pk}/").status_code, 404
            )
            self.assertEqual(
                self.client.post(f"/manage/accounts/{target.pk}/reset/").status_code,
                404,
            )
        self.assertEqual(self.client.get("/manage/site/").status_code, 403)
        self.assertEqual(self.client.get("/manage/stores/new/").status_code, 403)

    def test_user_cannot_manage_accounts(self):
        self.login(self.member)
        self.assertEqual(self.client.get("/manage/accounts/new/").status_code, 403)
        self.assertEqual(
            self.client.post(f"/manage/accounts/{self.other.pk}/reset/").status_code,
            403,
        )
        self.assertEqual(len(self.client.get("/api/session/").json()["enclosures"]), 1)
        self.member.enclosures.clear()
        self.assertEqual(self.client.get("/api/session/").json()["enclosures"], [])

    def account_data(self, **overrides):
        return {
            "display_name": "새 사용자",
            "username": "new@example.com",
            "role": "user",
            "store": self.store_a.pk,
            "enclosures": [self.a.pk],
            "is_active": "on",
            **overrides,
        }

    def test_manager_cannot_promote_or_assign_foreign_scope(self):
        self.login(self.manager)
        for data in (
            self.account_data(role="owner"),
            self.account_data(role="manager"),
            self.account_data(store=self.store_b.pk),
            self.account_data(enclosures=[self.b.pk]),
        ):
            self.client.post("/manage/accounts/new/", data)
            self.assertFalse(User.objects.filter(username="new@example.com").exists())
        response = self.client.post("/manage/accounts/new/", self.account_data())
        user = User.objects.get(username="new@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertContains(response, "/activate/#uid=")
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.store_id, self.store_a.pk)

    def test_role_changes_revoke_session_and_enforce_updated_scope(self):
        member_client = self.login(self.member, Client())
        self.login(self.owner)
        response = self.client.post(
            f"/manage/accounts/{self.member.pk}/",
            self.account_data(
                username=self.member.username,
                store=self.store_b.pk,
                enclosures=[self.b.pk],
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(member_client.get("/api/session/").status_code, 401)
        self.member.refresh_from_db()
        self.login(self.member, member_client)
        self.assertEqual(
            [x["id"] for x in member_client.get("/api/session/").json()["enclosures"]],
            [self.b.pk],
        )

    def test_account_pause_blocks_existing_and_new_login(self):
        member_client = self.login(self.member, Client())
        self.login(self.owner)
        data = self.account_data(username=self.member.username)
        data.pop("is_active")
        self.client.post(f"/manage/accounts/{self.member.pk}/", data)
        self.assertEqual(member_client.get("/api/session/").status_code, 401)
        response = member_client.post(
            "/login/",
            {"username": self.member.username, "password": "Testing-password-7382"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(member_client.get("/api/session/").status_code, 401)

    def test_activation_is_single_use_and_password_is_hashed(self):
        self.member.set_unusable_password()
        self.member.save()
        query = {
            k: v[0]
            for k, v in parse_qs(
                urlparse(activation_link(self.member)).fragment
            ).items()
        }
        weak = self.client.post(
            "/activate/", {**query, "new_password1": "123", "new_password2": "123"}
        )
        self.assertContains(weak, "12")
        password = "Distinct-test-password-5721"
        response = self.client.post(
            "/activate/",
            {**query, "new_password1": password, "new_password2": password},
        )
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertNotEqual(self.member.password, password)
        self.assertTrue(self.member.check_password(password))
        self.assertEqual(
            self.client.post(
                "/activate/",
                {**query, "new_password1": password, "new_password2": password},
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get("/api/session/").status_code, 401)

    def test_expired_and_tampered_activation_are_rejected(self):
        query = {
            k: v[0]
            for k, v in parse_qs(
                urlparse(activation_link(self.member)).fragment
            ).items()
        }
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            self.assertEqual(self.client.post("/activate/", query).status_code, 400)
        for changes in ({"uid": "invalid"}, {"token": "wrong"}, {"uid": "0"}):
            self.assertEqual(
                self.client.post("/activate/", {**query, **changes}).status_code, 400
            )

    def test_reset_invalidates_password_sessions_and_older_links(self):
        active = self.login(self.member, Client())
        old_link = activation_link(self.member)
        old_query = {k: v[0] for k, v in parse_qs(urlparse(old_link).fragment).items()}
        self.login(self.manager)
        self.assertEqual(
            self.client.post(f"/manage/accounts/{self.member.pk}/reset/").status_code,
            200,
        )
        self.assertEqual(active.get("/api/session/").status_code, 401)
        self.assertEqual(active.post("/activate/", old_query).status_code, 400)
        self.member.refresh_from_db()
        self.assertFalse(self.member.has_usable_password())

    def test_csrf_and_logout_method(self):
        secure_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            secure_client.post(
                "/login/",
                {"username": self.owner.username, "password": "Testing-password-7382"},
            ).status_code,
            403,
        )
        secure_client.force_login(self.owner)
        self.assertEqual(
            secure_client.post("/manage/site/", {"title": "bad"}).status_code, 403
        )
        self.assertEqual(secure_client.post("/logout/").status_code, 403)
        self.assertEqual(secure_client.get("/logout/").status_code, 405)

    def test_site_maintenance_blocks_lower_roles_and_api(self):
        manager = self.login(self.manager, Client())
        self.login(self.owner)
        self.client.post(
            "/manage/site/",
            {"title": "EasyRep", "notice": "점검", "maintenance": "on"},
        )
        self.assertEqual(manager.get("/api/session/").status_code, 503)
        self.assertEqual(manager.get("/manage/").status_code, 503)
        self.assertEqual(self.client.get("/api/session/").status_code, 200)
        self.client.post("/manage/site/", {"title": "EasyRep", "notice": ""})
        self.assertEqual(manager.get("/api/session/").status_code, 200)

    def test_owner_username_can_change_with_password_confirmation(self):
        self.login(self.owner)
        self.client.post(
            "/profile/",
            {
                "display_name": "총괄",
                "username": "changed",
                "current_password": "wrong",
            },
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "habitatosdevel")
        self.assertEqual(
            self.client.post(
                "/profile/",
                {
                    "display_name": "총괄",
                    "username": "changed",
                    "current_password": "Testing-password-7382",
                },
            ).status_code,
            302,
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "changed")
        self.assertEqual(self.client.get("/api/session/").status_code, 401)

    def test_case_insensitive_login_and_unique_email(self):
        self.assertEqual(
            self.client.post(
                "/login/",
                {"username": "  HABITATOSDEVEL  ", "password": "Testing-password-7382"},
            ).status_code,
            302,
        )
        self.client.post(
            "/manage/accounts/new/", self.account_data(username="MEMBER@example.com")
        )
        self.assertEqual(
            User.objects.filter(username__iexact="member@example.com").count(), 1
        )

    def test_owner_can_move_enclosure_and_remove_old_assignments(self):
        self.login(self.owner)
        self.assertEqual(
            self.client.post(
                f"/manage/enclosures/{self.a.pk}/",
                {"name": "이동된 사육장", "store": self.store_b.pk},
            ).status_code,
            302,
        )
        self.assertFalse(self.member.enclosures.exists())

    def test_forms_and_management_render_without_template_errors(self):
        self.login(self.owner)
        for path in (
            "/manage/",
            "/manage/accounts/new/",
            f"/manage/accounts/{self.member.pk}/",
            "/profile/",
            "/manage/stores/new/",
            "/manage/site/",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("no-store", response.headers["Cache-Control"])

    @override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
    def test_repeated_failed_login_is_limited(self):
        for _ in range(3):
            response = self.client.post(
                "/login/", {"username": self.owner.username, "password": "incorrect"}
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            self.client.post(
                "/login/",
                {"username": self.owner.username, "password": "Testing-password-7382"},
            ).status_code,
            429,
        )

    def test_management_pages_match_role_and_assignment(self):
        for actor, title in (
            (self.owner, "사이트·계정 관리"),
            (self.manager, "매장·사용자 관리"),
            (self.member, "내 배정 정보"),
        ):
            client = self.login(actor, Client())
            response = client.get("/manage/")
            self.assertContains(response, f"<h1>{title}</h1>", html=True)
            self.assertContains(response, f'href="/#home/{self.a.pk}"')
            if actor.role != "owner":
                self.assertNotContains(response, 'href="/manage/site/"')
                self.assertNotContains(response, 'href="/manage/stores/new/"')
                self.assertNotContains(response, self.other.username)
                self.assertNotContains(response, f'href="/#home/{self.b.pk}"')
            if actor.role == "user":
                self.assertNotContains(response, "계정 추가")
                self.assertNotContains(response, "Pi 등록 정보")
                self.assertNotContains(response, 'aria-label="계정 필터"')

    def test_account_directory_filters_keep_authorized_scope(self):
        pending = User.objects.create_user(
            username="pending@example.com", display_name="설정 대기 사용자",
            role="user", store=self.store_a,
        )
        paused = User.objects.create_user(
            username="paused@example.com", display_name="중지 사용자",
            role="user", store=self.store_a, is_active=False,
        )
        self.login(self.manager)
        response = self.client.get("/manage/", {"q": "example.com", "status": "pending"})
        self.assertEqual([a.pk for a in response.context["accounts"]], [pending.pk])
        response = self.client.get("/manage/", {"status": "inactive"})
        self.assertEqual([a.pk for a in response.context["accounts"]], [paused.pk])
        response = self.client.get("/manage/", {"role": "user", "status": "active"})
        self.assertEqual([a.pk for a in response.context["accounts"]], [self.member.pk])
        response = self.client.get("/manage/", {"q": self.other.username, "store": self.store_b.pk})
        self.assertEqual(response.context["account_page"].paginator.count, 0)
        self.assertNotContains(response, self.other.display_name)
        self.assertEqual(self.client.get("/manage/", {"role": "owner"}).context["accounts"], [])

    def test_account_directory_pagination_preserves_filters(self):
        for index in range(25):
            User.objects.create_user(
                username=f"page-{index}@example.com", display_name=f"페이지 사용자 {index:02}",
                role="user", store=self.store_a,
            )
        self.login(self.owner)
        params = {"q": "페이지", "role": "user", "store": self.store_a.pk, "status": "pending"}
        first = self.client.get("/manage/", params)
        second = self.client.get("/manage/", {**params, "page": 2})
        self.assertEqual(first.context["account_page"].paginator.count, 25)
        self.assertEqual(len(first.context["accounts"]), 20)
        self.assertEqual(len(second.context["accounts"]), 5)
        first_ids = [a.pk for a in first.context["accounts"]]
        second_ids = [a.pk for a in second.context["accounts"]]
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertEqual(first_ids + second_ids, sorted(first_ids + second_ids, reverse=True))
        self.assertEqual(dict(parse_qs(first.context["account_query"])), {k: [str(v)] for k, v in params.items()})
        self.assertContains(first, "page=2#accounts")

    def test_account_directory_invalid_filters_and_empty_results(self):
        self.login(self.owner)
        response = self.client.get("/manage/", {"store": "9" * 100, "page": "bad", "role": "invalid", "status": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["account_page"].number, 1)
        self.assertEqual(response.context["account_filters"]["store"], "")
        response = self.client.get("/manage/", {"q": '<script>alert("x")</script>'})
        self.assertEqual(response.context["account_page"].paginator.count, 0)
        self.assertContains(response, "조건에 맞는 계정이 없습니다.")
        self.assertNotContains(response, '<script>alert("x")</script>')
