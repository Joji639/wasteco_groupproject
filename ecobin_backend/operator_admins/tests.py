"""Tests for operator_admins app — Operator admin onboarding and pickup management APIs."""

import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding
from accounts.serializers import get_tokens_for_user
from pickups.models import PickupRequest

API = "/api/operator-admins/"


def _create_user(email="u@test.com", password="Test1234!", **kw):
    return CustomUser.objects.create_user(
        email=email, password=password, base_role="user", **kw
    )


def _create_operator(email="op@test.com", password="Test1234!", ward_no="5", is_verified=True, **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operator", **kw,
    )
    OperatorProfile.objects.create(user=user, ward_no=ward_no, is_verified=is_verified)
    return user


def _create_operator_admin(email="oa@test.com", password="Test1234!", panchayath="TVM", **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role="operatoradmin", **kw,
    )
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


def _create_pickup(user, **overrides):
    data = {
        "latitude": "9.931200",
        "longitude": "76.267300",
        "description": "Waste near home.",
    }
    data.update(overrides)
    return PickupRequest.objects.create(user=user, **data)


# ---------------------------------------------------------------------------
# 1. OPERATOR ONBOARDING MANAGEMENT
# ---------------------------------------------------------------------------

class OperatorAdminOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "onboardings/"
        self.approve_url = API + "onboardings/approve/"
        self.reject_url = API + "onboardings/reject/"
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
        r = self.client.post(self.approve_url, {"id": self.onboarding.id}, format="json")
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
# 2. USER ONBOARDING MANAGEMENT (via operator admin)
# ---------------------------------------------------------------------------

class SuperAdminUserOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "user-onboardings/"
        self.approve_url = API + "user-onboardings/approve/"
        self.reject_url = API + "user-onboardings/reject/"
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
        r = self.client.post(self.approve_url, {"id": self.profile.id}, format="json")
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


class OperatorAdminUserOnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "user-onboardings/"
        self.approve_url = API + "user-onboardings/approve/"
        self.reject_url = API + "user-onboardings/reject/"
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


class SuperAdminApproveOperatorAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "onboardings/"
        self.approve_url = API + "onboardings/approve/"
        self.reject_url = API + "onboardings/reject/"
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
# 3. OPERATOR ADMIN PICKUP MANAGEMENT
# ---------------------------------------------------------------------------

class OperatorAdminAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="ua_user@test.com", phone="+919000000300")
        self.operator = _create_operator(email="ua_op@test.com", phone="+919000000301")
        self.oa = _create_operator_admin(email="ua_oa@test.com", phone="+919000000302")
        self.sa = _create_superuser(email="ua_sa@test.com")

    def test_unauthenticated_list(self):
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_role_list_forbidden(self):
        _auth(self.client, self.user)
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_role_list_forbidden(self):
        _auth(self.client, self.operator)
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_role_list_forbidden(self):
        _auth(self.client, self.sa)
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_admin_list_allowed(self):
        _auth(self.client, self.oa)
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_unauthenticated_accept(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_role_accept_forbidden(self):
        pickup = _create_pickup(self.user)
        _auth(self.client, self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_admin_accept_allowed(self):
        pickup = _create_pickup(self.user)
        _auth(self.client, self.oa)
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_unauthenticated_reject(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "x"})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_role_reject_forbidden(self):
        pickup = _create_pickup(self.user)
        _auth(self.client, self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "x"})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_admin_reject_allowed(self):
        pickup = _create_pickup(self.user)
        _auth(self.client, self.oa)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "x"})
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_unauthenticated_assign(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {"operator_id": str(self.operator.id)})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_role_assign_forbidden(self):
        pickup = _create_pickup(self.user)
        _auth(self.client, self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {"operator_id": str(self.operator.id)})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_admin_assign_allowed(self):
        pickup = _create_pickup(self.user, status='ACCEPTED')
        _auth(self.client, self.oa)
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {"operator_id": str(self.operator.id)})
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class OperatorAdminPickupListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="list_user@test.com", phone="+919000000310")
        self.oa = _create_operator_admin(email="list_oa@test.com", phone="+919000000311")
        _auth(self.client, self.oa)

    def test_empty_list(self):
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_returns_pickups(self):
        _create_pickup(self.user)
        _create_pickup(self.user, description="Second pickup")
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 2)

    def test_list_includes_user_info(self):
        _create_pickup(self.user)
        r = self.client.get(API + "pickups/")
        item = r.data["data"][0]
        self.assertEqual(item["user_email"], self.user.email)

    def test_only_on_demand_pickups(self):
        _create_pickup(self.user)
        r = self.client.get(API + "pickups/")
        self.assertTrue(all(p["pickup_type"] == "ON_DEMAND" for p in r.data["data"]))

    def test_ordered_by_created_at_desc(self):
        _create_pickup(self.user, description="First")
        _create_pickup(self.user, description="Second")
        r = self.client.get(API + "pickups/")
        self.assertEqual(r.data["count"], 2)


class OperatorAdminPickupDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="det_user@test.com", phone="+919000000320")
        self.oa = _create_operator_admin(email="det_oa@test.com", phone="+919000000321")
        _auth(self.client, self.oa)

    def test_detail_not_found(self):
        r = self.client.get(API + "pickups/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_returns_pickup(self):
        pickup = _create_pickup(self.user)
        r = self.client.get(API + f"pickups/{pickup.id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["id"], str(pickup.id))

    def test_detail_includes_user_email(self):
        pickup = _create_pickup(self.user)
        r = self.client.get(API + f"pickups/{pickup.id}/")
        self.assertEqual(r.data["data"]["user_email"], self.user.email)


class OperatorAdminPickupAcceptTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="acc_user@test.com", phone="+919000000330")
        self.oa = _create_operator_admin(email="acc_oa@test.com", phone="+919000000331")
        _auth(self.client, self.oa)

    def test_accept_pending_pickup(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'ACCEPTED')
        self.assertEqual(pickup.accepted_by, self.oa)

    def test_accept_already_accepted_fails(self):
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_accept_already_rejected_fails(self):
        pickup = _create_pickup(self.user, status='REJECTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/accept/")
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_accept_not_found(self):
        r = self.client.patch(API + "pickups/00000000-0000-0000-0000-000000000000/accept/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class OperatorAdminPickupRejectTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="rej_user@test.com", phone="+919000000340")
        self.oa = _create_operator_admin(email="rej_oa@test.com", phone="+919000000341")
        _auth(self.client, self.oa)

    def test_reject_pending_pickup(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "Inaccessible location."})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'REJECTED')
        self.assertEqual(pickup.rejection_reason, "Inaccessible location.")

    def test_reject_without_reason_fails(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_empty_reason_fails(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": ""})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_whitespace_only_reason_fails(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "   "})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_already_rejected_fails(self):
        pickup = _create_pickup(self.user, status='REJECTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/reject/", {"reason": "Already rejected."})
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_reject_not_found(self):
        r = self.client.patch(API + "pickups/00000000-0000-0000-0000-000000000000/reject/", {"reason": "x"})
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class OperatorAdminPickupAssignTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="asgn_user@test.com", phone="+919000000350")
        self.oa = _create_operator_admin(email="asgn_oa@test.com", phone="+919000000351")
        self.operator = _create_operator(email="asgn_op@test.com", phone="+919000000352")
        _auth(self.client, self.oa)

    def test_assign_operator_to_accepted_pickup(self):
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'ASSIGNED')
        self.assertEqual(pickup.assigned_operator, self.operator)

    def test_assign_operator_to_pending_pickup_fails(self):
        pickup = _create_pickup(self.user)
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_assign_operator_to_rejected_pickup_fails(self):
        pickup = _create_pickup(self.user, status='REJECTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)

    def test_assign_nonexistent_operator_fails(self):
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": "00000000-0000-0000-0000-000000000000"
        })
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_user_role_fails(self):
        user = _create_user(email="asgn_other@test.com", phone="+919000000353")
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(user.id)
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_inactive_operator_fails(self):
        self.operator.is_active = False
        self.operator.save(update_fields=['is_active'])
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_unverified_operator_fails(self):
        self.operator.operator_profile.is_verified = False
        self.operator.operator_profile.save(update_fields=['is_verified'])
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_not_found(self):
        r = self.client.patch(API + "pickups/00000000-0000-0000-0000-000000000000/assign-operator/", {
            "operator_id": str(self.operator.id)
        })
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_missing_operator_id(self):
        pickup = _create_pickup(self.user, status='ACCEPTED')
        r = self.client.patch(API + f"pickups/{pickup.id}/assign-operator/")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
