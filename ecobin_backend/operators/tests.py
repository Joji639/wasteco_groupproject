"""Tests for operators app — Operator onboarding and profile APIs."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding
from accounts.serializers import get_tokens_for_user

API = "/operators/"


def _create_user(email="u@test.com", password="Test1234!", **kw):
    return CustomUser.objects.create_user(
        email=email, password=password, base_role="user", **kw
    )


def _create_operator(email="op@test.com", password="Test1234!", ward_no="5", **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operator", **kw,
    )
    OperatorProfile.objects.create(user=user, ward_no=ward_no)
    return user


def _create_operator_admin(email="oa@test.com", password="Test1234!", panchayath="TVM", **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operatoradmin", **kw,
    )
    OperatorAdminProfile.objects.create(user=user, panchayath=panchayath)
    return user


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


# ---------------------------------------------------------------------------
# 1. STAFF REGISTRATION
# ---------------------------------------------------------------------------

class StaffRegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/accounts/register/"

    def test_register_operator(self):
        r = self.client.post(self.url, {
            "username": "op1", "email": "op1@test.com", "phone": "+919000000002",
            "role": "operator", "ward_no": "5",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["data"]["role"], "operator")
        self.assertTrue(OperatorProfile.objects.filter(user__email="op1@test.com").exists())

    def test_register_operator_admin(self):
        r = self.client.post(self.url, {
            "username": "oa1", "email": "oa1@test.com", "phone": "+919000000003",
            "role": "operatoradmin", "panchayath": "TVM",
            "password": "Test1234!", "confirm_password": "Test1234!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OperatorAdminProfile.objects.filter(user__email="oa1@test.com").exists())

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
# 2. STAFF LOGIN
# ---------------------------------------------------------------------------

class StaffLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/accounts/login/"
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

    def test_login_no_identifier_or_operator_id(self):
        r = self.client.post(self.url, {"password": "Staff1234!"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 3. OPERATOR ONBOARDING
# ---------------------------------------------------------------------------

class OperatorOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "onboarding/"
        self.operator = _create_operator(email="oponb@test.com", password="Op1234!")
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
# 4. OPERATOR ACCOUNT INFO
# ---------------------------------------------------------------------------

class OperatorAccountInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "account-info/"
        self.operator = _create_operator(email="opacct@test.com", password="Op1234!")
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


# ---------------------------------------------------------------------------
# 5. OPERATOR PERSONAL INFO
# ---------------------------------------------------------------------------

class OperatorPersonalInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "personal-info/"
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


# ---------------------------------------------------------------------------
# 6. OPERATOR CHANGE PASSWORD
# ---------------------------------------------------------------------------

class OperatorChangePasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "change-password/"
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


# ---------------------------------------------------------------------------
# 7. OPERATOR LOGOUT
# ---------------------------------------------------------------------------

class OperatorLogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "logout/"
        self.operator = _create_operator(email="opout@test.com", password="Op1234!")
        self.operator.operator_profile.is_verified = True
        self.operator.operator_profile.save()
        _auth(self.client, self.operator)

    def test_logout_success(self):
        tokens = _tokens(self.operator)
        r = self.client.post(self.url, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
