from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.conf import settings


@override_settings(SECURE_SSL_REDIRECT=False)
class PublicDemoTests(TestCase):
    def test_login_offers_public_demo_without_credentials(self):
        response = self.client.get('/login/')
        self.assertContains(response, 'href="/demo/"')
        self.assertContains(response, '데모 둘러보기')

    def test_anonymous_demo_serves_only_the_demo_document_without_session(self):
        with TemporaryDirectory() as directory:
            Path(directory, 'index.html').write_text('PRIVATE APP ENTRY')
            Path(directory, 'demo.html').write_text('PUBLIC DEMO ENTRY')
            with override_settings(FRONTEND_DIR=Path(directory)):
                response = self.client.get('/demo/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b''.join(response.streaming_content), b'PUBLIC DEMO ENTRY')
                self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
                self.assertEqual(self.client.get('/').status_code, 302)
                self.assertEqual(self.client.get('/index.html').status_code, 302)

    def test_demo_does_not_open_operating_api_or_write_routes(self):
        self.client.get('/demo/')
        for path in ('/api/session/', '/api/enclosures/', '/api/enclosures/unknown/history/', '/api/enclosures/unknown/records/'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ('/manage/', '/manage/site/', '/profile/'):
            self.assertEqual(self.client.get(path).status_code, 302, path)
            self.assertEqual(self.client.post(path, {}).status_code, 302, path)
        self.assertEqual(self.client.post('/demo/', {}).status_code, 405)

    def test_demo_normalizes_trailing_slash_and_missing_build_returns_503(self):
        self.assertRedirects(self.client.get('/demo'), '/demo/', status_code=301, fetch_redirect_response=False)
        with TemporaryDirectory() as directory, override_settings(FRONTEND_DIR=Path(directory)):
            self.assertEqual(self.client.get('/demo/').status_code, 503)
