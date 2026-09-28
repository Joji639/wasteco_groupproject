"""Tests for operators app — Operator onboarding and profile APIs."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding
from accounts.serializers import get_tokens_for_user
from pickups.models import PickupRequest, PickupTracking

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


# ---------------------------------------------------------------------------
# 8. TRACKING START
# ---------------------------------------------------------------------------

def _create_pickup(user, status='ASSIGNED', assigned_operator=None, **kw):
    return PickupRequest.objects.create(
        user=user,
        pickup_type='ON_DEMAND',
        latitude=Decimal('8.5241'),
        longitude=Decimal('76.9366'),
        description='Test waste pickup',
        status=status,
        assigned_operator=assigned_operator,
        **kw,
    )


class PickupTrackingStartTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "tracking/start/"
        self.operator = _create_operator(email="trackop@test.com", password="Op1234!")
        self.user = _create_user(email="trackuser@test.com")
        self.pickup = _create_pickup(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _auth(self.client, self.operator)

    @patch("operators.views.start_simulation")
    @patch("operators.views.calculate_route")
    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_success(self, mock_geocode, mock_route, mock_sim):
        mock_geocode.return_value = (9.9312, 76.2673)
        mock_route.return_value = ([[9.9312, 76.2673], [8.5241, 76.9366]], 600)
        mock_sim.return_value = None

        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
            "start_location": "MG Road, Kochi",
        }, format="json")

        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data["success"])
        mock_geocode.assert_called_once_with("MG Road, Kochi")
        self.assertEqual(Decimal(str(r.data["data"]["start_latitude"])), Decimal("9.9312"))
        self.assertEqual(Decimal(str(r.data["data"]["start_longitude"])), Decimal("76.2673"))
        self.assertEqual(r.data["data"]["start_place"], "MG Road, Kochi")
        self.pickup.refresh_from_db()
        self.assertEqual(self.pickup.status, "ON_THE_WAY")

    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_geocode_fails(self, mock_geocode):
        mock_geocode.return_value = None
        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
            "start_location": "Nowhere Land",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_location", str(r.data))

    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_blank_location(self, mock_geocode):
        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
            "start_location": "",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        mock_geocode.assert_not_called()

    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_missing_location(self, mock_geocode):
        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        mock_geocode.assert_not_called()

    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_not_assigned(self, mock_geocode):
        mock_geocode.return_value = (9.9312, 76.2673)
        other_op = _create_operator(email="trackop2@test.com", password="Op1234!")
        _auth(self.client, other_op)
        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
            "start_location": "MG Road, Kochi",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_pickup_not_found(self, mock_geocode):
        import uuid as _uuid
        r = self.client.post(self.url, {
            "pickup_request_id": str(_uuid.uuid4()),
            "start_location": "MG Road, Kochi",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("operators.views.start_simulation")
    @patch("operators.views.calculate_route")
    @patch("pickups.serializers.geocode_place")
    def test_tracking_start_wrong_status(self, mock_geocode, mock_route, mock_sim):
        self.pickup.status = 'COLLECTED'
        self.pickup.save()
        r = self.client.post(self.url, {
            "pickup_request_id": str(self.pickup.id),
            "start_location": "MG Road, Kochi",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 9. TRACKING DETAIL & ACTIVE LIST (regression: _in_group import bug)
# ---------------------------------------------------------------------------

class PickupTrackingDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email="detailop@test.com", password="Op1234!")
        self.user = _create_user(email="detailuser@test.com")
        self.pickup = _create_pickup(self.user, status='ON_THE_WAY', assigned_operator=self.operator)
        self.tracking = PickupTracking.objects.create(
            pickup_request=self.pickup,
            operator=self.operator,
            start_place="Ernakulam",
            start_latitude=9.98,
            start_longitude=76.30,
            current_latitude=9.99,
            current_longitude=76.31,
            status='EN_ROUTE',
            progress=0.5,
        )
        self.detail_url = f"{API}tracking/{self.tracking.id}/"

    def test_tracking_detail_as_user(self):
        _auth(self.client, self.user)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.data["success"])
        self.assertEqual(r.data["data"]["status"], "EN_ROUTE")

    def test_tracking_detail_as_operator(self):
        _auth(self.client, self.operator)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_tracking_detail_as_admin(self):
        admin = _create_operator_admin(email="detailadmin@test.com")
        _auth(self.client, admin)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_tracking_detail_unrelated_user_403(self):
        stranger = _create_user(email="stranger@test.com")
        _auth(self.client, stranger)
        r = self.client.get(self.detail_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_tracking_detail_not_found(self):
        _auth(self.client, self.user)
        r = self.client.get(f"{API}tracking/{uuid.uuid4()}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_tracking_active_list_operator(self):
        _auth(self.client, self.operator)
        r = self.client.get(f"{API}tracking/active/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)

    def test_tracking_active_list_user(self):
        _auth(self.client, self.user)
        r = self.client.get(f"{API}tracking/active/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)

    def test_tracking_active_list_excludes_completed(self):
        self.tracking.status = 'COMPLETED'
        self.tracking.save()
        _auth(self.client, self.operator)
        r = self.client.get(f"{API}tracking/active/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)
