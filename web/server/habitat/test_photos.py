from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from .models import AuditEvent, Enclosure, EnclosurePhoto
from . import tests as access_tests


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    AXES_ENABLED=False,
)
class PhotoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        access_tests.AccessTests.setUpTestData.__func__(cls)

    def login(self, user, client=None):
        self.client = client or Client()
        return access_tests.AccessTests.login(self, user, self.client)

    def upload(self, color="green", size=(1600, 900)):
        data = BytesIO()
        image = Image.new("RGB", size, color)
        exif = Image.Exif()
        exif[270] = "Private source metadata"
        image.save(data, "JPEG", exif=exif)
        return SimpleUploadedFile("source.jpg", data.getvalue(), "image/jpeg")

    @property
    def edit_url(self):
        return f"/manage/enclosures/{self.a.pk}/photo/"

    @property
    def read_url(self):
        return f"/api/enclosures/{self.a.pk}/photo/"

    def save_photo(self):
        self.login(self.owner)
        response = self.client.post(self.edit_url, {"photo": self.upload()})
        self.assertRedirects(response, self.edit_url)
        return EnclosurePhoto.objects.get(enclosure=self.a)

    def test_upload_normalizes_and_returns_private_photo(self):
        photo = self.save_photo()
        self.assertEqual((photo.width, photo.height), (1280, 720))
        self.assertLessEqual(len(photo.content), 512 * 1024)
        self.assertLessEqual(len(photo.thumbnail), 48 * 1024)
        self.assertEqual(AuditEvent.objects.filter(action="사육장 대표 사진 등록").count(), 1)
        for query, width in (("", 1280), ("?size=thumbnail", 320)):
            response = self.client.get(self.read_url + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/jpeg")
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.width, width)
                self.assertEqual(len(image.getexif()), 0)
                self.assertNotIn("comment", image.info)

    def test_photo_access_tracks_enclosure_scope_and_assignment_removal(self):
        self.save_photo()
        self.login(self.member)
        self.assertEqual(self.client.get(self.read_url).status_code, 200)
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)
        self.assertEqual(self.client.post(self.edit_url, {"action": "remove"}).status_code, 403)
        self.member.enclosures.clear()
        self.assertEqual(self.client.get(self.read_url).status_code, 404)
        self.login(self.other)
        self.assertEqual(self.client.get(self.read_url).status_code, 404)
        self.login(self.manager)
        self.assertEqual(self.client.get(self.read_url).status_code, 200)
        self.assertEqual(self.client.post(self.edit_url, {"photo": self.upload()}).status_code, 403)
        self.assertEqual(EnclosurePhoto.objects.count(), 1)

    def test_anonymous_and_csrf_requests_are_blocked(self):
        self.assertEqual(self.client.get(self.read_url).status_code, 401)
        self.assertEqual(self.client.get(self.edit_url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner, backend="django.contrib.auth.backends.ModelBackend")
        self.assertEqual(client.post(self.edit_url, {"photo": self.upload()}).status_code, 403)
        self.assertFalse(EnclosurePhoto.objects.exists())

    def test_invalid_upload_keeps_existing_photo(self):
        before = bytes(self.save_photo().content)
        for payload in (b"<svg onload='alert(1)'></svg>", b"\xff\xd8\xffbroken"):
            response = self.client.post(self.edit_url, {"photo": SimpleUploadedFile("fake.jpg", payload, "image/jpeg")})
            self.assertContains(response, "사진을 읽을 수 없습니다")
            self.assertEqual(bytes(EnclosurePhoto.objects.get(enclosure=self.a).content), before)
        self.assertContains(self.client.post(self.edit_url, {}), "필수 항목")

    def test_large_files_and_pixels_are_rejected(self):
        self.login(self.owner)
        response = self.client.post(self.edit_url, {"photo": SimpleUploadedFile("huge.jpg", b"x" * (5 * 1024 * 1024 + 1))})
        self.assertContains(response, "5 MB 이하")
        with patch("habitat.photo_processing.MAX_PIXELS", 100):
            response = self.client.post(self.edit_url, {"photo": self.upload(size=(20, 20))})
        self.assertContains(response, "2,400만 화소 이하")
        self.assertFalse(EnclosurePhoto.objects.exists())

    def test_animation_is_rejected(self):
        self.login(self.owner)
        data = BytesIO()
        Image.new("RGB", (20, 20), "red").save(data, "WEBP", save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")], duration=100, loop=0)
        response = self.client.post(self.edit_url, {"photo": SimpleUploadedFile("moving.webp", data.getvalue())})
        self.assertContains(response, "정지 사진")
        self.assertFalse(EnclosurePhoto.objects.exists())

    def test_orientation_and_transparency(self):
        self.login(self.owner)
        data = BytesIO()
        exif = Image.Exif(); exif[274] = 6
        Image.new("RGB", (80, 40), "red").save(data, "JPEG", exif=exif)
        self.client.post(self.edit_url, {"photo": SimpleUploadedFile("rotated.jpg", data.getvalue())})
        photo = EnclosurePhoto.objects.get(enclosure=self.a)
        self.assertEqual((photo.width, photo.height), (40, 80))
        data = BytesIO()
        Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(data, "PNG")
        response = self.client.post(self.edit_url, {"photo": SimpleUploadedFile("alpha.png", data.getvalue())})
        self.assertEqual(response.status_code, 302)
        with Image.open(BytesIO(self.client.get(self.read_url).content)) as image:
            self.assertEqual(image.getpixel((10, 10)), (255, 255, 255))

    def test_replace_and_delete_update_metadata(self):
        self.save_photo()
        first = self.client.get(f"/api/enclosures/{self.a.pk}/").json()["item"]["photo"]
        self.client.post(self.edit_url, {"photo": self.upload("blue")})
        second = self.client.get(f"/api/enclosures/{self.a.pk}/").json()["item"]["photo"]
        self.assertNotEqual(first["url"], second["url"])
        self.assertEqual(EnclosurePhoto.objects.count(), 1)
        self.assertEqual(self.client.post(self.edit_url, {"action": "remove"}).status_code, 302)
        self.assertEqual(self.client.get(self.read_url).status_code, 404)
        self.assertIsNone(self.client.get(f"/api/enclosures/{self.a.pk}/").json()["item"]["photo"])
        self.assertEqual(AuditEvent.objects.filter(action="사육장 대표 사진 삭제").count(), 1)

    def test_list_never_loads_photo_bytes(self):
        self.save_photo()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/enclosures/")
        self.assertEqual(response.status_code, 200)
        item = next(item for item in response.json()["items"] if item["id"] == self.a.pk)
        self.assertIn("thumbnailUrl", item["photo"])
        self.assertNotIn("content", item["photo"])
        for query in queries:
            self.assertNotIn('"habitat_enclosurephoto"."content"', query["sql"])
            self.assertNotIn('"habitat_enclosurephoto"."thumbnail"', query["sql"])

    def test_failed_audit_rolls_back_photo_replacement(self):
        before = bytes(self.save_photo().content)
        with patch("habitat.photos.AuditEvent.objects.create", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.edit_url, {"photo": self.upload("blue")})
        self.assertEqual(bytes(EnclosurePhoto.objects.get(enclosure=self.a).content), before)

    def test_first_visit_has_no_validation_errors(self):
        self.login(self.owner)
        response = self.client.get(self.edit_url)
        self.assertContains(response, "아직 대표 사진이 없습니다.")
        self.assertNotContains(response, "필수 항목")
        self.assertFalse(response.context["form"].is_bound)
