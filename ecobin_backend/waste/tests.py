import io
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import CustomUser


def _make_image(fmt="JPEG", size=(100, 100)):
    buf = io.BytesIO()
    from PIL import Image

    img = Image.new("RGB", size, color="red")
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf


def _make_user(role="user"):
    user = CustomUser.objects.create_user(
        email=f"{role}@test.com",
        phone=f"9000000001",
        password="testpass123",
        base_role=role,
    )
    group_name = {"user": "User", "operator": "Operator", "operatoradmin": "OperatorAdmin", "superadmin": "SuperAdmin"}[role]
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    return user


@override_settings(
    GROQ_API_KEY="test-key",
    GROQ_MODEL="test-model",
    CONFIDENCE_THRESHOLD=60,
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
        "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
        "DEFAULT_THROTTLE_RATES": {"waste_scan": "1000/min"},
    },
)
class WasteScanPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/waste/scan/"
        self.image = SimpleUploadedFile("test.jpg", _make_image().read(), content_type="image/jpeg")

    @patch("waste.views.call_groq")
    def test_user_gets_200(self, mock_groq):
        mock_groq.return_value = json.dumps({"category": "plastic", "percentage": 87, "item": "water bottle"})
        user = _make_user("user")
        self.client.force_authenticate(user=user)
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["success"])
        self.assertEqual(resp.data["data"]["category"], "plastic")

    def test_operator_gets_403(self):
        user = _make_user("operator")
        self.client.force_authenticate(user=user)
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_operatoradmin_gets_403(self):
        user = _make_user("operatoradmin")
        self.client.force_authenticate(user=user)
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_gets_403(self):
        user = _make_user("superadmin")
        self.client.force_authenticate(user=user)
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_gets_401(self):
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(
    GROQ_API_KEY="test-key",
    GROQ_MODEL="test-model",
    CONFIDENCE_THRESHOLD=60,
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
        "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
        "DEFAULT_THROTTLE_RATES": {"waste_scan": "1000/min"},
    },
)
class WasteScanValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/waste/scan/"
        self.user = _make_user("user")
        self.client.force_authenticate(user=self.user)

    def test_missing_image_returns_400(self):
        resp = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["success"])

    def test_wrong_file_type_returns_400(self):
        txt = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        resp = self.client.post(self.url, {"image": txt}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_file_returns_400(self):
        big = SimpleUploadedFile("big.jpg", b"\x00" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
        resp = self.client.post(self.url, {"image": big}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    GROQ_API_KEY="test-key",
    GROQ_MODEL="test-model",
    CONFIDENCE_THRESHOLD=60,
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
        "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
        "DEFAULT_THROTTLE_RATES": {"waste_scan": "1000/min"},
    },
)
class WasteScanResultTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/waste/scan/"
        self.user = _make_user("user")
        self.client.force_authenticate(user=self.user)
        self.image = SimpleUploadedFile("test.jpg", _make_image().read(), content_type="image/jpeg")

    @patch("waste.views.call_groq")
    def test_plastic_result(self, mock_groq):
        mock_groq.return_value = json.dumps({"category": "plastic", "percentage": 87, "item": "water bottle"})
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["category"], "plastic")
        self.assertEqual(data["percentage"], 87)
        self.assertIn("87%", data["message"])

    @patch("waste.views.call_groq")
    def test_ewaste_result(self, mock_groq):
        mock_groq.return_value = json.dumps({"category": "e-waste", "percentage": 92, "item": "old phone"})
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["category"], "e-waste")
        self.assertIn("92%", data["message"])

    @patch("waste.views.call_groq")
    def test_neither_result(self, mock_groq):
        mock_groq.return_value = json.dumps({"category": "neither", "percentage": 40, "item": "banana peel"})
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["category"], "neither")

    @patch("waste.views.call_groq")
    def test_low_percentage_becomes_neither(self, mock_groq):
        mock_groq.return_value = json.dumps({"category": "plastic", "percentage": 45, "item": "bottle"})
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, 200)
        data = resp.data["data"]
        self.assertEqual(data["category"], "neither")
        self.assertIn("Try a clearer photo", data["message"])

    @patch("waste.views.call_groq")
    def test_malformed_output_gives_502(self, mock_groq):
        mock_groq.return_value = "this is not json at all"
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch("waste.views.call_groq")
    def test_groq_rate_limit_gives_503(self, mock_groq):
        mock_groq.side_effect = Exception("429 Too Many Requests: rate limit exceeded")
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("busy", resp.data["message"])

    @patch("waste.views.call_groq")
    def test_groq_unreachable_gives_500(self, mock_groq):
        mock_groq.side_effect = ConnectionError("network unreachable")
        resp = self.client.post(self.url, {"image": self.image}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
