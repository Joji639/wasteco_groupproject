"""Tests for superadmins app."""

import pyotp
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import (
    CustomUser, UserProfile, OperatorProfile,
    OperatorAdminProfile, OperatorOnboarding,
)
from accounts.serializers import get_tokens_for_user

API = "/api/superadmins/"


def _create_user(email="u@test.com", password="Test1234!", **kw):
    return CustomUser.objects.create_user(email=email, password=password, base_role="user", **kw)


def _create_operator(email="op@test.com", password="Test1234!", ward_no="5", **kw):
    user = CustomUser.objects.create_user(email=email, password=password, base_role="operator", **kw)
    OperatorProfile.objects.create(user=user, ward_no=ward_no)
    return user


def _create_operator_admin(email="oa@test.com", password="Test1234!", panchayath="TVM", **kw):
    user = CustomUser.objects.create_user(email=email, password=password, base_role="operatoradmin", **kw)
    OperatorAdminProfile.objects.create(user=user, panchayath=panchayath)
    return user


def _create_superuser(email="sa@test.com", password="Test1234!"):
    return CustomUser.objects.create_superuser(email=email, password=password)


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


class AdminLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "login/"
        self.sa = _create_superuser(email="sa_login@test.com", password="Sa1234!")

    def test_admin_login_success(self):
        r = self.client.post(self.url, {"email": "sa_login@test.com", "password": "Sa1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("tokens", r.data["data"])

    def test_admin_login_wrong_password(self):
        r = self.client.post(self.url, {"email": "sa_login@test.com", "password": "Wrong"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_login_nonexistent(self):
        r = self.client.post(self.url, {"email": "ghost@test.com", "password": "Sa1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_login_inactive(self):
        self.sa.is_active = False
        self.sa.save()
        r = self.client.post(self.url, {"email": "sa_login@test.com", "password": "Sa1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_login_2fa_required(self):
        self.sa.is_2fa_enabled = True
        self.sa.totp_secret = pyotp.random_base32()
        self.sa.save()
        r = self.client.post(self.url, {"email": "sa_login@test.com", "password": "Sa1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["data"]["requires_2fa"])

    def test_non_superadmin_login_rejected(self):
        _create_user(email="user_sa@test.com", password="Sa1234!")
        r = self.client.post(self.url, {"email": "user_sa@test.com", "password": "Sa1234!"}, format="json")
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
        r = self.client.get(API + "users/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_operators_list(self):
        r = self.client.get(API + "operators/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_operatoradmins_list(self):
        r = self.client.get(API + "operator-admins/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_admin_onboardings_list(self):
        r = self.client.get(API + "onboardings/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_user_cannot_access_admin_list(self):
        _auth(self.client, self.user)
        r = self.client.get(API + "users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_cannot_access_admin_list(self):
        _auth(self.client, self.operator)
        r = self.client.get(API + "users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_opadmin_cannot_access_superadmin_list(self):
        _auth(self.client, self.opadmin)
        r = self.client.get(API + "users/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_onboardings_filter_pending(self):
        r = self.client.get(API + "onboardings/?status=pending")
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.regular_user = _create_user(email="perm_user@test.com", password="P1234!")
        UserProfile.objects.get_or_create(user=self.regular_user)
        self.operator = _create_operator(email="perm_op@test.com", password="P1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        self.opadmin = _create_operator_admin(email="perm_oa@test.com", password="P1234!")
        self.opadmin.operatoradmin_profile.is_verified = True
        self.opadmin.operatoradmin_profile.save()
        self.sa = _create_superuser(email="perm_sa@test.com", password="P1234!")
        self.pending_op = _create_operator(email="perm_pending@test.com", password="P1234!")
        self.pending_onb = OperatorOnboarding.objects.create(
            user=self.pending_op, pan_number="ABCDE1234F", aadhaar_number="123456789012"
        )
        self.pending_user = _create_user(email="perm_pending_user@test.com", password="P1234!")
        self.pending_profile = UserProfile.objects.create(
            user=self.pending_user, address="St", current_location="City", is_verified=False,
        )

    def test_superadmin_list_allowed(self):
        _auth(self.client, self.sa)
        self.assertEqual(self.client.get(API + "users/").status_code, 200)
        self.assertEqual(self.client.get(API + "operators/").status_code, 200)
        self.assertEqual(self.client.get(API + "operator-admins/").status_code, 200)
        self.assertEqual(self.client.get(API + "onboardings/").status_code, 200)

    def test_superadmin_list_denied_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get(API + "users/").status_code, 403)

    def test_superadmin_list_denied_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get(API + "users/").status_code, 403)

    def test_superadmin_list_denied_for_opadmin(self):
        _auth(self.client, self.opadmin)
        self.assertEqual(self.client.get(API + "users/").status_code, 403)

    def test_user_endpoints_allowed_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get("/api/users/account-info/").status_code, 200)

    def test_user_endpoints_denied_for_unauthenticated(self):
        self.assertEqual(self.client.get("/api/users/account-info/").status_code, 401)

    def test_staff_onboarding_allowed_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get("/api/operators/onboarding/").status_code, 200)

    def test_staff_onboarding_denied_for_user(self):
        _auth(self.client, self.regular_user)
        self.assertEqual(self.client.get("/api/operators/onboarding/").status_code, 403)

    def test_opadmin_list_allowed_for_opadmin(self):
        _auth(self.client, self.opadmin)
        self.assertEqual(self.client.get("/api/operator-admins/onboardings/").status_code, 200)

    def test_opadmin_list_denied_for_operator(self):
        _auth(self.client, self.operator)
        self.assertEqual(self.client.get("/api/operator-admins/onboardings/").status_code, 403)

    def test_opadmin_approve_denied_for_operator(self):
        _auth(self.client, self.operator)
        r = self.client.post("/api/operator-admins/onboardings/approve/",
                             {"id": self.pending_onb.id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_superadmin_approve_user_onboarding(self):
        _auth(self.client, self.sa)
        r = self.client.post("/api/operator-admins/user-onboardings/approve/",
                             {"id": self.pending_profile.id}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_user_cannot_approve_user_onboarding(self):
        _auth(self.client, self.regular_user)
        r = self.client.post("/api/operator-admins/user-onboardings/approve/",
                             {"id": self.pending_profile.id}, format="json")
        self.assertEqual(r.status_code, 403)
