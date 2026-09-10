"""Tests for accounts app — Auth endpoints only."""

import io
import pyotp
from unittest.mock import patch
from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from .models import (
    CustomUser, UserProfile, OperatorProfile,
    OperatorAdminProfile, OperatorOnboarding,
)

API = "/accounts/"


def _create_user(email="u@test.com", password="Test1234!", role="user", **kw):
    return CustomUser.objects.create_user(
        email=email, password=password, base_role=role, **kw
    )


def _create_operator_admin(email="oa@test.com", password="Test1234!", panchayath="TVM"):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operatoradmin",
    )
    OperatorAdminProfile.objects.create(user=user, panchayath=panchayath)
    return user


def _create_operator(email="op@test.com", password="Test1234!", ward_no="5"):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operator",
    )
    OperatorProfile.objects.create(user=user, ward_no=ward_no)
    return user


def _create_superuser(email="sa@test.com", password="Test1234!"):
    return CustomUser.objects.create_superuser(email=email, password=password)


def _tokens(user):
    from .serializers import get_tokens_for_user
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


# ---------------------------------------------------------------------------
# 1. USER REGISTRATION
# ---------------------------------------------------------------------------

class UserRegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "registeruser/"
        self.data = {
            "username": "newuser",
            "email": "new@test.com",
            "phone": "+919000000001",
            "password": "StrongPass1!",
            "confirm_password": "StrongPass1!",
        }

    def test_register_success(self):
        r = self.client.post(self.url, self.data, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(CustomUser.objects.filter(email="new@test.com").exists())

    def test_register_duplicate_email(self):
        _create_user(email="new@test.com")
        r = self.client.post(self.url, self.data, format="json")
        self.assertIn(r.status_code, [400, 409])

    def test_register_password_mismatch(self):
        self.data["confirm_password"] = "WrongPass1!"
        r = self.client.post(self.url, self.data, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password(self):
        self.data["password"] = "123"
        self.data["confirm_password"] = "123"
        r = self.client.post(self.url, self.data, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_email(self):
        del self.data["email"]
        r = self.client.post(self.url, self.data, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 2. USER LOGIN
# ---------------------------------------------------------------------------

class UserLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "loginuser/"
        self.user = _create_user(email="login@test.com", password="Login1234!", phone="+919000000099")
        UserProfile.objects.get_or_create(user=self.user)

    def test_login_success(self):
        r = self.client.post(self.url, {
            "identifier": "login@test.com", "password": "Login1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", r.data["data"])

    def test_login_wrong_password(self):
        r = self.client.post(self.url, {
            "identifier": "login@test.com", "password": "Wrong"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_user(self):
        r = self.client.post(self.url, {
            "identifier": "noone@test.com", "password": "Login1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_with_phone(self):
        r = self.client.post(self.url, {
            "identifier": str(self.user.phone), "password": "Login1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        r = self.client.post(self.url, {
            "identifier": "login@test.com", "password": "Login1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("accounts.views.public_auth.send_email_otp_task")
    def test_login_2fa_required(self, mock_task):
        self.user.is_2fa_enabled = True
        self.user.totp_secret = pyotp.random_base32()
        self.user.save()
        r = self.client.post(self.url, {
            "identifier": "login@test.com", "password": "Login1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["data"]["requires_2fa"])


# ---------------------------------------------------------------------------
# 3. 2FA SETUP / VERIFY / DISABLE
# ---------------------------------------------------------------------------

class TwoFactorAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="2fa@test.com", password="TwoFA1234!")
        _auth(self.client, self.user)

    @patch("accounts.views.public_auth.send_email_otp_task")
    def test_setup_2fa(self, mock_task):
        r = self.client.post(API + "2fasetup/", format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("qr_code_base64", r.data["data"])
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.totp_secret)

    def test_verify_2fa(self):
        self.user.totp_secret = pyotp.random_base32()
        self.user.save()
        code = pyotp.TOTP(self.user.totp_secret).now()
        r = self.client.post(API + "2faverify/", {"code": code}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_2fa_enabled)

    def test_verify_2fa_invalid_code(self):
        self.user.totp_secret = pyotp.random_base32()
        self.user.save()
        r = self.client.post(API + "2faverify/", {"code": "000000"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_2fa_no_secret(self):
        r = self.client.post(API + "2faverify/", {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_disable_2fa(self):
        self.user.is_2fa_enabled = True
        self.user.totp_secret = pyotp.random_base32()
        self.user.save()
        r = self.client.post(API + "2fadisable/", {"password": "TwoFA1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_2fa_enabled)

    def test_disable_2fa_wrong_password(self):
        self.user.is_2fa_enabled = True
        self.user.save()
        r = self.client.post(API + "2fadisable/", {"password": "Wrong"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_setup_already_enabled(self):
        self.user.is_2fa_enabled = True
        self.user.save()
        r = self.client.post(API + "2fasetup/", format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 4. LOGIN WITH 2FA
# ---------------------------------------------------------------------------

class LoginWith2FATests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "2falogin/"
        self.user = _create_user(email="2falog@test.com", password="Login2FA!")
        self.user.is_2fa_enabled = True
        self.user.totp_secret = pyotp.random_base32()
        self.user.save()

    def test_login_2fa_success(self):
        code = pyotp.TOTP(self.user.totp_secret).now()
        r = self.client.post(self.url, {
            "identifier": "2falog@test.com", "code": code
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", r.data["data"])

    def test_login_2fa_invalid_code(self):
        r = self.client.post(self.url, {
            "identifier": "2falog@test.com", "code": "000000"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_2fa_not_enabled(self):
        self.user.is_2fa_enabled = False
        self.user.save()
        code = pyotp.TOTP(self.user.totp_secret).now()
        r = self.client.post(self.url, {
            "identifier": "2falog@test.com", "code": code
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_2fa_nonexistent_user(self):
        r = self.client.post(self.url, {
            "identifier": "nope@test.com", "code": "123456"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 5. FORGOT / RESET PASSWORD
# ---------------------------------------------------------------------------

class ForgotResetPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="fp@test.com", password="FP1234!")

    @patch("accounts.views.public_auth.send_email_otp_task")
    def test_forgot_password_existing_email(self, mock_task):
        r = self.client.post(API + "forgotpassword/", {"email": "fp@test.com"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    @patch("accounts.views.public_auth.send_email_otp_task")
    def test_forgot_password_nonexistent_email(self, mock_task):
        r = self.client.post(API + "forgotpassword/", {"email": "noone@test.com"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_reset_password_success(self):
        cache.set("forgot_password_otp_fp@test.com", "123456", timeout=300)
        r = self.client.post(API + "resetpassword/", {
            "email": "fp@test.com", "code": "123456",
            "new_password": "Reset1234!", "confirm_new_password": "Reset1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Reset1234!"))

    def test_reset_password_wrong_code(self):
        cache.set("forgot_password_otp_fp@test.com", "123456", timeout=300)
        r = self.client.post(API + "resetpassword/", {
            "email": "fp@test.com", "code": "999999",
            "new_password": "Reset1234!", "confirm_new_password": "Reset1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_password_nonexistent_email(self):
        r = self.client.post(API + "resetpassword/", {
            "email": "ghost@test.com", "code": "123456",
            "new_password": "Reset1234!", "confirm_new_password": "Reset1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_password_mismatch(self):
        r = self.client.post(API + "resetpassword/", {
            "email": "fp@test.com", "code": "123456",
            "new_password": "Reset1234!", "confirm_new_password": "Other1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 6. PUBLIC ENDPOINTS
# ---------------------------------------------------------------------------

class PublicEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_user_no_auth(self):
        r = self.client.post(API + "registeruser/", {
            "email": "pub@test.com", "phone": "+919000000010",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_user_login_no_auth(self):
        user = _create_user(email="pub_login@test.com", password="Test1234!")
        UserProfile.objects.get_or_create(user=user)
        r = self.client.post(API + "loginuser/", {
            "identifier": "pub_login@test.com", "password": "Test1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_staff_login_no_auth(self):
        _create_operator(email="pub_staff@test.com", password="Test1234!")
        r = self.client.post(API + "login/", {
            "identifier": "pub_staff@test.com", "password": "Test1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_staff_register_no_auth(self):
        r = self.client.post(API + "register/", {
            "username": "pub_reg", "email": "pub_reg@test.com",
            "phone": "+919000000011",
            "role": "operator", "ward_no": "5",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
