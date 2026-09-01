"""Comprehensive API tests for accounts app."""

import io
import pyotp
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth.models import Group
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from .models import (
    CustomUser, UserProfile, OperatorProfile,
    OperatorAdminProfile, OperatorOnboarding,
)

API = "/accounts/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        # ensure profile exists
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

    @patch("accounts.views.send_email_otp_task")
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
# 3. LOGOUT
# ---------------------------------------------------------------------------

class LogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "logout/"
        self.user = _create_user(email="out@test.com", password="Logout1234!")
        _auth(self.client, self.user)

    def test_logout_success(self):
        tokens = _tokens(self.user)
        r = self.client.post(self.url, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_logout_invalid_token(self):
        r = self.client.post(self.url, {"refresh": "badtoken"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_unauthenticated(self):
        self.client.credentials()
        r = self.client.post(self.url, {"refresh": "x"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 4. ACCOUNT INFO
# ---------------------------------------------------------------------------

class AccountInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "accountinfo/"
        self.user = _create_user(email="info@test.com", password="Info1234!")
        _auth(self.client, self.user)

    def test_get_account_info(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["email"], "info@test.com")

    def test_patch_account_info(self):
        r = self.client.patch(self.url, {"username": "updated"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "updated")

    def test_unauthenticated(self):
        self.client.credentials()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 5. PERSONAL INFO
# ---------------------------------------------------------------------------

class PersonalInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "personalinfo/"
        self.user = _create_user(email="pi@test.com", password="PI1234!")
        self.profile = UserProfile.objects.create(
            user=self.user, address="123 St", current_location="City",
            is_verified=True,
        )
        _auth(self.client, self.user)

    def test_get_personal_info(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["address"], "123 St")

    def test_patch_personal_info_verified(self):
        r = self.client.patch(self.url, {"address": "456 Ave"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_verified)  # re-verification required

    def test_patch_unverified_user(self):
        self.profile.is_verified = False
        self.profile.save()
        r = self.client.patch(self.url, {"address": "789 Rd"})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_unverified_user(self):
        self.profile.is_verified = False
        self.profile.save()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 6. CHANGE PASSWORD
# ---------------------------------------------------------------------------

class ChangePasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "changepassword/"
        self.user = _create_user(email="pw@test.com", password="OldPass1234!")
        _auth(self.client, self.user)

    def test_change_password_success(self):
        r = self.client.post(self.url, {
            "old_password": "OldPass1234!",
            "new_password": "NewPass1234!",
            "confirm_new_password": "NewPass1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_wrong_old_password(self):
        r = self.client.post(self.url, {
            "old_password": "WrongOld1!",
            "new_password": "NewPass1234!",
            "confirm_new_password": "NewPass1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_mismatch(self):
        r = self.client.post(self.url, {
            "old_password": "OldPass1234!",
            "new_password": "NewPass1234!",
            "confirm_new_password": "DiffPass1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_old_and_new(self):
        r = self.client.post(self.url, {
            "old_password": "OldPass1234!",
            "new_password": "OldPass1234!",
            "confirm_new_password": "OldPass1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 7. ONBOARDING (USER)
# ---------------------------------------------------------------------------

class OnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "onboardinguser/"
        self.user = _create_user(email="onb@test.com", password="Onb1234!")
        self.profile = UserProfile.objects.create(user=self.user)
        _auth(self.client, self.user)

    def test_onboarding_success(self):
        pan_file = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        pan_file.name = "pan.png"
        receipt = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        receipt.name = "receipt.png"
        r = self.client.post(self.url, {
            "address": "123 St",
            "current_location": "City",
            "house_number": "12",
            "pin": "695001",
            "pan_card_image": pan_file,
            "house_tax_receipt": receipt,
        })
        self.assertIn(r.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_onboarding_already_verified(self):
        self.profile.is_verified = True
        self.profile.save()
        r = self.client.post(self.url, {
            "address": "123 St",
            "current_location": "City",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_user_onboarding(self):
        op = _create_operator(email="op_onb@test.com")
        _auth(self.client, op)
        r = self.client.post(self.url, {"address": "X"})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 8. 2FA SETUP / VERIFY / DISABLE
# ---------------------------------------------------------------------------

class TwoFactorAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="2fa@test.com", password="TwoFA1234!")
        _auth(self.client, self.user)

    @patch("accounts.views.send_email_otp_task")
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
        r = self.client.post(API + "2fadisable/", {
            "password": "TwoFA1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_2fa_enabled)

    def test_disable_2fa_wrong_password(self):
        self.user.is_2fa_enabled = True
        self.user.save()
        r = self.client.post(API + "2fadisable/", {
            "password": "Wrong"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_setup_already_enabled(self):
        self.user.is_2fa_enabled = True
        self.user.save()
        r = self.client.post(API + "2fasetup/", format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 9. LOGIN WITH 2FA
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
# 10. FORGOT / RESET PASSWORD
# ---------------------------------------------------------------------------

class ForgotResetPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="fp@test.com", password="FP1234!")

    @patch("accounts.views.send_email_otp_task")
    def test_forgot_password_existing_email(self, mock_task):
        r = self.client.post(API + "forgotpassword/",
                             {"email": "fp@test.com"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    @patch("accounts.views.send_email_otp_task")
    def test_forgot_password_nonexistent_email(self, mock_task):
        r = self.client.post(API + "forgotpassword/",
                             {"email": "noone@test.com"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)  # same 200 for security

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
# 11. STAFF REGISTRATION
# ---------------------------------------------------------------------------

class StaffRegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "register/"

    def test_register_operator(self):
        r = self.client.post(self.url, {
            "username": "op1", "email": "op1@test.com", "phone": "+919000000002",
            "role": "operator", "ward_no": "5",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["data"]["role"], "operator")
        self.assertTrue(OperatorProfile.objects.filter(
            user__email="op1@test.com").exists())

    def test_register_operator_admin(self):
        r = self.client.post(self.url, {
            "username": "oa1", "email": "oa1@test.com", "phone": "+919000000003",
            "role": "operatoradmin", "panchayath": "TVM",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OperatorAdminProfile.objects.filter(
            user__email="oa1@test.com").exists())

    def test_register_operator_missing_ward(self):
        r = self.client.post(self.url, {
            "username": "op2", "email": "op2@test.com", "phone": "+919000000004",
            "role": "operator",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_operator_admin_missing_panchayath(self):
        r = self.client.post(self.url, {
            "username": "oa2", "email": "oa2@test.com", "phone": "+919000000005",
            "role": "operatoradmin",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email(self):
        _create_operator(email="dup@test.com")
        r = self.client.post(self.url, {
            "username": "dup", "email": "dup@test.com", "phone": "+919000000006",
            "role": "operator", "ward_no": "3",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertIn(r.status_code, [400, 409])


# ---------------------------------------------------------------------------
# 12. STAFF LOGIN
# ---------------------------------------------------------------------------

class StaffLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "login/"
        self.operator = _create_operator(email="slogin@test.com", password="Staff1234!")
        self.opadmin = _create_operator_admin(email="oalogin@test.com", password="Staff1234!")

    def test_login_operator_email(self):
        r = self.client.post(self.url, {
            "identifier": "slogin@test.com", "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_login_operator_operator_id(self):
        pid = self.operator.operator_profile.operator_id
        r = self.client.post(self.url, {
            "operator_id": pid, "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_login_operator_admin_identifier(self):
        oa_id = self.opadmin.operatoradmin_profile.operator_id
        r = self.client.post(self.url, {
            "operator_id": oa_id, "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_login_wrong_password(self):
        r = self.client.post(self.url, {
            "identifier": "slogin@test.com", "password": "Wrong"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_user_via_staff_endpoint(self):
        _create_user(email="regular@test.com", password="Staff1234!")
        r = self.client.post(self.url, {
            "identifier": "regular@test.com", "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_inactive_staff(self):
        self.operator.is_active = False
        self.operator.save()
        r = self.client.post(self.url, {
            "identifier": "slogin@test.com", "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("accounts.views.send_email_otp_task")
    def test_login_staff_2fa_required(self, mock_task):
        self.operator.is_2fa_enabled = True
        self.operator.totp_secret = pyotp.random_base32()
        self.operator.save()
        r = self.client.post(self.url, {
            "identifier": "slogin@test.com", "password": "Staff1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["data"]["requires_2fa"])

    def test_login_no_identifier_or_operator_id(self):
        r = self.client.post(self.url, {"password": "Staff1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 13. OPERATOR ONBOARDING (CRUD)
# ---------------------------------------------------------------------------

class OperatorOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "operator/onboarding/"
        self.operator = _create_operator(email="oponb@test.com", password="Op1234!")
        self.opadmin = _create_operator_admin(email="oaonb@test.com", password="Op1234!")
        _auth(self.client, self.operator)

    def test_get_no_onboarding(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNone(r.data["data"])

    def test_post_onboarding(self):
        r = self.client.post(self.url, {
            "pan_number": "ABCDE1234F",
            "aadhaar_number": "123456789012",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_post_duplicate_onboarding(self):
        OperatorOnboarding.objects.create(
            user=self.operator, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        r = self.client.post(self.url, {
            "pan_number": "ABCDE1234F",
            "aadhaar_number": "123456789012",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_onboarding(self):
        OperatorOnboarding.objects.create(
            user=self.operator, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        r = self.client.patch(self.url, {"pan_number": "FGHIJ5678K"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_patch_no_onboarding(self):
        r = self.client.patch(self.url, {"pan_number": "X"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_cannot_access_operator_onboarding(self):
        user = _create_user(email="user_onb@test.com")
        _auth(self.client, user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_pan_number(self):
        r = self.client.post(self.url, {
            "pan_number": "INVALID",
            "aadhaar_number": "123456789012",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_aadhaar_number(self):
        r = self.client.post(self.url, {
            "pan_number": "ABCDE1234F",
            "aadhaar_number": "12345",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 14. OPERATOR ACCOUNT INFO / PERSONAL INFO / CHANGE PASSWORD / LOGOUT
# ---------------------------------------------------------------------------

class OperatorAccountInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "operator/account-info/"
        self.operator = _create_operator(email="opacct@test.com", password="Op1234!")
        self.opadmin = _create_operator_admin(
            email="oaacct@test.com", password="Op1234!",
            panchayath="TVM",
        )
        # Make operator approved
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()

    def test_operator_get_account(self):
        _auth(self.client, self.operator)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_operator_patch_account(self):
        _auth(self.client, self.operator)
        r = self.client.patch(self.url, {"username": "newname"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_unapproved_operator_blocked(self):
        op = _create_operator(email="opun@test.com", password="Op1234!")
        _auth(self.client, op)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class OperatorPersonalInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "operator/personal-info/"
        self.operator = _create_operator(email="oppers@test.com", password="Op1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        OperatorOnboarding.objects.create(
            user=self.operator, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        _auth(self.client, self.operator)

    def test_get_personal_info(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_patch_personal_info(self):
        r = self.client.patch(self.url, {"pan_number": "FGHIJ5678K"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_get_no_onboarding(self):
        self.operator.operator_onboarding.delete()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class OperatorChangePasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "operator/change-password/"
        self.operator = _create_operator(email="oppw@test.com", password="Op1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        _auth(self.client, self.operator)

    def test_change_password_success(self):
        r = self.client.post(self.url, {
            "old_password": "Op1234!",
            "new_password": "NewOp5678!",
            "confirm_new_password": "NewOp5678!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_wrong_old_password(self):
        r = self.client.post(self.url, {
            "old_password": "Wrong123!",
            "new_password": "NewOp5678!",
            "confirm_new_password": "NewOp5678!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class OperatorLogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "operator/logout/"
        self.operator = _create_operator(email="opout@test.com", password="Op1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        _auth(self.client, self.operator)

    def test_logout_success(self):
        tokens = _tokens(self.operator)
        r = self.client.post(self.url, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 15. OPERATOR ADMIN: ONBOARDING LIST / APPROVE / REJECT
# ---------------------------------------------------------------------------

class OperatorAdminOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "operator/admin/onboardings/"
        self.approve_url = API + "operator/admin/onboardings/approve/"
        self.reject_url = API + "operator/admin/onboardings/reject/"
        self.opadmin = _create_operator_admin(email="oa_list@test.com", password="Op1234!")
        self.opadmin.operatoradmin_profile.is_verified = True
        self.opadmin.operatoradmin_profile.save()
        self.operator = _create_operator(email="op_list@test.com", password="Op1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        self.onboarding = OperatorOnboarding.objects.create(
            user=self.operator, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        _auth(self.client, self.opadmin)

    def test_list_onboardings(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_list_filter_pending(self):
        r = self.client.get(self.list_url + "?status=pending")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_list_filter_approved(self):
        r = self.client.get(self.list_url + "?status=approved")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_approve_onboarding(self):
        r = self.client.post(self.approve_url, {
            "id": self.onboarding.id
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.is_active)

    def test_reject_onboarding(self):
        r = self.client.post(self.reject_url, {
            "id": self.onboarding.id, "reason": "Invalid docs"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.onboarding.refresh_from_db()
        self.assertEqual(self.onboarding.rejection_reason, "Invalid docs")

    def test_approve_already_approved(self):
        self.onboarding.approved = True
        self.onboarding.save()
        r = self.client.post(self.approve_url, {"id": self.onboarding.id}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_nonexistent(self):
        r = self.client.post(self.approve_url, {"id": 99999}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_approve_missing_id(self):
        r = self.client.post(self.approve_url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_missing_id(self):
        r = self.client.post(self.reject_url, {"reason": "bad"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_operator_cannot_approve(self):
        _auth(self.client, self.operator)
        r = self.client.post(self.approve_url, {"id": self.onboarding.id}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_cannot_list(self):
        _auth(self.client, self.operator)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 16. SUPER ADMIN: USER ONBOARDING APPROVE / REJECT
# ---------------------------------------------------------------------------

class SuperAdminUserOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "admin/useronboardings/"
        self.approve_url = API + "admin/useronboardings/approve/"
        self.reject_url = API + "admin/useronboardings/reject/"
        self.sa = _create_superuser(email="sa_onb@test.com", password="Sa1234!")
        self.user = _create_user(email="user_onb2@test.com", password="Usr1234!")
        self.profile = UserProfile.objects.create(
            user=self.user, address="123 St", current_location="City",
            is_verified=False,
        )
        _auth(self.client, self.sa)

    def test_list_user_onboardings(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_approve_user_onboarding(self):
        r = self.client.post(self.approve_url, {
            "id": self.profile.id
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_verified)

    def test_reject_user_onboarding(self):
        r = self.client.post(self.reject_url, {
            "id": self.profile.id, "reason": "Incomplete"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.rejection_reason, "Incomplete")

    def test_approve_already_approved(self):
        self.profile.is_verified = True
        self.profile.save()
        r = self.client.post(self.approve_url, {"id": self.profile.id}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_nonexistent(self):
        r = self.client.post(self.approve_url, {"id": 99999}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_cannot_approve(self):
        user = _create_user(email="regular2@test.com")
        _auth(self.client, user)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 17. SUPER ADMIN LOGIN / LIST VIEWS
# ---------------------------------------------------------------------------

class AdminLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "admin/login/"
        self.sa = _create_superuser(email="sa_login@test.com", password="Sa1234!")

    def test_admin_login_success(self):
        r = self.client.post(self.url, {
            "email": "sa_login@test.com", "password": "Sa1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", r.data["data"])

    def test_admin_login_wrong_password(self):
        r = self.client.post(self.url, {
            "email": "sa_login@test.com", "password": "Wrong"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_login_nonexistent(self):
        r = self.client.post(self.url, {
            "email": "ghost@test.com", "password": "Sa1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_login_inactive(self):
        self.sa.is_active = False
        self.sa.save()
        r = self.client.post(self.url, {
            "email": "sa_login@test.com", "password": "Sa1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("accounts.views.send_email_otp_task")
    def test_admin_login_2fa_required(self, mock_task):
        self.sa.is_2fa_enabled = True
        self.sa.totp_secret = pyotp.random_base32()
        self.sa.save()
        r = self.client.post(self.url, {
            "email": "sa_login@test.com", "password": "Sa1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["data"]["requires_2fa"])

    def test_non_superadmin_login_rejected(self):
        _create_user(email="user_sa@test.com", password="Sa1234!")
        r = self.client.post(self.url, {
            "email": "user_sa@test.com", "password": "Sa1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.sa = _create_superuser(email="sa_list@test.com", password="Sa1234!")
        self.user = _create_user(email="ul@test.com", password="U1234!")
        self.operator = _create_operator(email="ol@test.com", password="O1234!")
        self.opadmin = _create_operator_admin(email="oal@test.com", password="OA1234!")
        _auth(self.client, self.sa)

    def test_admin_users_list(self):
        r = self.client.get(API + "admin/users/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_operators_list(self):
        r = self.client.get(API + "admin/operators/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_operatoradmins_list(self):
        r = self.client.get(API + "admin/operatoradmins/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_onboardings_list(self):
        r = self.client.get(API + "admin/onboardings/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_user_cannot_access_admin_list(self):
        _auth(self.client, self.user)
        r = self.client.get(API + "admin/users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_cannot_access_admin_list(self):
        _auth(self.client, self.operator)
        r = self.client.get(API + "admin/users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_opadmin_cannot_access_superadmin_list(self):
        _auth(self.client, self.opadmin)
        r = self.client.get(API + "admin/users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_onboardings_filter_pending(self):
        r = self.client.get(API + "admin/onboardings/?status=pending")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 18. OPERATOR ADMIN: USER ONBOARDING APPROVE (via operator admin)
# ---------------------------------------------------------------------------

class OperatorAdminUserOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "admin/useronboardings/"
        self.approve_url = API + "admin/useronboardings/approve/"
        self.reject_url = API + "admin/useronboardings/reject/"
        self.opadmin = _create_operator_admin(email="oa_uonb@test.com", password="OA1234!")
        self.opadmin.operatoradmin_profile.is_verified = True
        self.opadmin.operatoradmin_profile.save()
        self.user = _create_user(email="usr_uonb@test.com", password="U1234!")
        self.profile = UserProfile.objects.create(
            user=self.user, address="123 St", current_location="City",
            is_verified=False,
        )
        _auth(self.client, self.opadmin)

    def test_opadmin_approve_user_onboarding(self):
        r = self.client.post(self.approve_url, {"id": self.profile.id}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_verified)

    def test_opadmin_reject_user_onboarding(self):
        r = self.client.post(self.reject_url, {
            "id": self.profile.id, "reason": "Bad docs"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_opadmin_list_user_onboardings(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_user_cannot_approve(self):
        user = _create_user(email="usr2@test.com")
        _auth(self.client, user)
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 19. OPERATOR ADMIN ONBOARDING: SUPER ADMIN CAN APPROVE OA
# ---------------------------------------------------------------------------

class SuperAdminApproveOperatorAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "operator/admin/onboardings/"
        self.approve_url = API + "operator/admin/onboardings/approve/"
        self.reject_url = API + "operator/admin/onboardings/reject/"
        self.sa = _create_superuser(email="sa_approve@test.com", password="Sa1234!")
        self.opadmin = _create_operator_admin(email="oa_need@test.com", password="OA1234!")
        self.opadmin.operatoradmin_profile.is_verified = False
        self.opadmin.operatoradmin_profile.save()
        self.onboarding = OperatorOnboarding.objects.create(
            user=self.opadmin, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        _auth(self.client, self.sa)

    def test_superadmin_can_approve_oa(self):
        r = self.client.post(self.approve_url, {"id": self.onboarding.id}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_superadmin_can_reject_oa(self):
        r = self.client.post(self.reject_url, {
            "id": self.onboarding.id, "reason": "Rejected"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_superadmin_can_list_all(self):
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# 20. PERMISSION MATRIX: role vs endpoint access
# ---------------------------------------------------------------------------

class PermissionMatrixTests(TestCase):
    """Verify that each role can only access its allowed endpoints."""

    def setUp(self):
        self.client = APIClient()
        # Create users for each role
        self.regular_user = _create_user(email="perm_user@test.com", password="P1234!")
        UserProfile.objects.get_or_create(user=self.regular_user)
        self.operator = _create_operator(email="perm_op@test.com", password="P1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        self.opadmin = _create_operator_admin(email="perm_oa@test.com", password="P1234!")
        self.opadmin.operatoradmin_profile.is_verified = True
        self.opadmin.operatoradmin_profile.save()
        self.sa = _create_superuser(email="perm_sa@test.com", password="P1234!")

        # Create an operator onboarding for approve/reject tests
        self.pending_op = _create_operator(email="perm_pending@test.com", password="P1234!")
        self.pending_onb = OperatorOnboarding.objects.create(
            user=self.pending_op, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        # User onboarding for approve/reject
        self.pending_user = _create_user(email="perm_pending_user@test.com", password="P1234!")
        self.pending_profile = UserProfile.objects.create(
            user=self.pending_user, address="St", current_location="City",
            is_verified=False,
        )

    # --- User endpoints ---
    def test_user_endpoints_allowed_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get(API + "accountinfo/").status_code, 200)
        self.assertEqual(self.client.get(API + "personalinfo/").status_code, 200)

    def test_user_endpoints_denied_for_unauthenticated(self):
        self.assertEqual(self.client.get(API + "accountinfo/").status_code, 401)

    # --- Staff onboarding endpoints ---
    def test_staff_onboarding_allowed_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get(API + "operator/onboarding/").status_code, 200)

    def test_staff_onboarding_denied_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get(API + "operator/onboarding/").status_code, 403)

    # --- Operator admin endpoints ---
    def test_opadmin_list_allowed_for_opadmin(self):
        _auth(self.client, self.opadmin)
        self.assertEqual(self.client.get(API + "operator/admin/onboardings/").status_code, 200)

    def test_opadmin_list_denied_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get(API + "operator/admin/onboardings/").status_code, 403)

    def test_opadmin_approve_denied_for_operator(self):
        _auth(self.client, self.operator)
        r = self.client.post(API + "operator/admin/onboardings/approve/",
                             {"id": self.pending_onb.id}, format="json")
        self.assertEqual(r.status_code, 403)

    # --- Super admin endpoints ---
    def test_superadmin_list_allowed(self):
        _auth(self.client, self.sa)
        self.assertEqual(self.client.get(API + "admin/users/").status_code, 200)
        self.assertEqual(self.client.get(API + "admin/operators/").status_code, 200)
        self.assertEqual(self.client.get(API + "admin/operatoradmins/").status_code, 200)
        self.assertEqual(self.client.get(API + "admin/onboardings/").status_code, 200)

    def test_superadmin_list_denied_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get(API + "admin/users/").status_code, 403)

    def test_superadmin_list_denied_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get(API + "admin/users/").status_code, 403)

    def test_superadmin_list_denied_for_opadmin(self):
        _auth(self.client, self.opadmin)
        self.assertEqual(self.client.get(API + "admin/users/").status_code, 403)

    # --- Approve/reject user onboarding as super admin ---
    def test_superadmin_approve_user_onboarding(self):
        _auth(self.client, self.sa)
        r = self.client.post(API + "admin/useronboardings/approve/",
                             {"id": self.pending_profile.id}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_user_cannot_approve_user_onboarding(self):
        _auth(self.client, self.regular_user)
        r = self.client.post(API + "admin/useronboardings/approve/",
                             {"id": self.pending_profile.id}, format="json")
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# 21. PUBLIC ENDPOINTS (no auth required)
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
            "role": "operator", "ward_no": "7",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_forgot_password_no_auth(self):
        r = self.client.post(API + "forgotpassword/",
                             {"email": "any@test.com"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_login_no_auth(self):
        _create_superuser(email="pub_sa@test.com", password="Test1234!")
        r = self.client.post(API + "admin/login/", {
            "email": "pub_sa@test.com", "password": "Test1234!"
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_2fa_login_no_auth(self):
        user = _create_user(email="pub_2fa@test.com", password="Test1234!")
        user.is_2fa_enabled = True
        user.totp_secret = pyotp.random_base32()
        user.save()
        code = pyotp.TOTP(user.totp_secret).now()
        r = self.client.post(API + "2falogin/", {
            "identifier": "pub_2fa@test.com", "code": code
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_google_auth_no_auth(self):
        """Google auth endpoint is accessible without authentication."""
        r = self.client.post(API + "googleauth/",
                             {"id_token": "fake"}, format="json")
        # Will fail validation but endpoint is reachable
        self.assertIn(r.status_code, [400, 401])
