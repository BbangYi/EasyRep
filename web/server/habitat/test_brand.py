from django.test import TestCase, override_settings
from habitat.models import Organization, SiteSettings


@override_settings(SECURE_SSL_REDIRECT=False)
class BrandTests(TestCase):
    def test_new_records_use_easyrep(self):
        self.assertEqual(Organization().name, 'EasyRep')
        self.assertEqual(SiteSettings().title, 'EasyRep')

    def test_login_shows_easyrep_without_old_wordmark(self):
        response = self.client.get('/login/')
        self.assertContains(response, 'EasyRep')
        self.assertNotContains(response, 'HabitatOS')
        self.assertNotContains(response, 'habitatos-logo')

    def test_migration_only_changes_legacy_names_and_is_idempotent(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        legacy = Organization.objects.create(name="HABITATOS")
        custom = Organization.objects.create(name="서울 파충류 연구실")
        site = SiteSettings.objects.create(title="HabitatOS")
        rename = importlib.import_module("habitat.migrations.0005_easyrep_brand").rename_legacy_brand
        editor = SimpleNamespace(connection=connection)
        rename(apps, editor)
        rename(apps, editor)
        legacy.refresh_from_db(); custom.refresh_from_db(); site.refresh_from_db()
        self.assertEqual(legacy.name, "EasyRep")
        self.assertEqual(custom.name, "서울 파충류 연구실")
        self.assertEqual(site.title, "EasyRep")
        site.title = "나만의 사육장"; site.save()
        rename(apps, editor)
        site.refresh_from_db()
        self.assertEqual(site.title, "나만의 사육장")
