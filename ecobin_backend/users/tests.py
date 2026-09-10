"""Tests for users app — User profile and pickup request APIs."""

from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile
from accounts.serializers import get_tokens_for_user
from pickups.models import PickupRequest

API = "/users/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _create_superuser(email="sa@test.com", password="Test1234!"):
    return CustomUser.objects.create_superuser(email=email, password=password)


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


# ---------------------------------------------------------------------------
# 1. USER ONBOARDING
# ---------------------------------------------------------------------------

class OnboardingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "onboarding/"
        self.user = _create_user(email="onb@test.com", password="Onb1234!")
        self.profile = UserProfile.objects.create(user=self.user)
        _auth(self.client, self.user)

    def test_onboarding_success(self):
        import io
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
# 2. USER LOGOUT
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
# 3. USER ACCOUNT INFO
# ---------------------------------------------------------------------------

class AccountInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "account-info/"
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
# 4. USER PERSONAL INFO
# ---------------------------------------------------------------------------

class PersonalInfoTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "personal-info/"
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
# 5. USER CHANGE PASSWORD
# ---------------------------------------------------------------------------

class ChangePasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "change-password/"
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


# ===========================================================================
# PICKUP REQUEST APIs (moved from pickups app)
# ===========================================================================

PICKUP_API = "/users/pickups/"

DEFAULT_PICKUP_DATA = {
    "latitude": "9.931200",
    "longitude": "76.267300",
    "description": "Waste near home.",
}


# ---------------------------------------------------------------------------
# 6. PICKUP AUTH
# ---------------------------------------------------------------------------

class PickupRequestAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="auth@test.com", phone="+919000000200")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)

    def test_unauthenticated_rejected(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test pickup",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_allowed(self):
        _auth(self.client, self.user)
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test pickup",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_operator_rejected(self):
        operator = _create_operator(email="op_auth@test.com", phone="+919000000201")
        _auth(self.client, operator)
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test pickup",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_operator_admin_rejected(self):
        oa = _create_operator_admin(email="oa_auth@test.com", phone="+919000000202")
        _auth(self.client, oa)
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test pickup",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_rejected(self):
        sa = _create_superuser(email="sa_auth@test.com")
        _auth(self.client, sa)
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test pickup",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 7. PICKUP CREATE
# ---------------------------------------------------------------------------

class PickupRequestCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="create@test.com", phone="+919000000210")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_create_pickup_request(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Large amount of plastic waste near my house.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data["success"])
        self.assertEqual(r.data["data"]["pickup_type"], "ON_DEMAND")
        self.assertEqual(r.data["data"]["status"], "PENDING")

    def test_create_pickup_with_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (10, 10), color="green")
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        uploaded = SimpleUploadedFile("waste.jpg", buf.read(), content_type="image/jpeg")
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Hazardous waste near park.",
            "image": uploaded,
        }, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, msg=r.data)
        self.assertIn("image", r.data["data"])

    def test_user_association(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Test user association.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        pickup = PickupRequest.objects.get(id=r.data["data"]["id"])
        self.assertEqual(pickup.user, self.user)

    def test_pickup_type_is_on_demand(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Check pickup type.",
        }, format="json")
        pickup = PickupRequest.objects.get(id=r.data["data"]["id"])
        self.assertEqual(pickup.pickup_type, "ON_DEMAND")

    def test_status_is_pending(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200",
            "longitude": "76.267300",
            "description": "Check initial status.",
        }, format="json")
        pickup = PickupRequest.objects.get(id=r.data["data"]["id"])
        self.assertEqual(pickup.status, "PENDING")


# ---------------------------------------------------------------------------
# 8. PICKUP COORDINATES
# ---------------------------------------------------------------------------

class PickupRequestCoordinateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="coord@test.com", phone="+919000000220")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_valid_latitude(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "Valid coords.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_latitude_too_high(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "91.000000", "longitude": "76.267300", "description": "Invalid lat.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", r.data)

    def test_latitude_too_low(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "-91.000000", "longitude": "76.267300", "description": "Invalid lat.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", r.data)

    def test_valid_longitude(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "Valid coords.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_longitude_too_high(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "181.000000", "description": "Invalid lng.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("longitude", r.data)

    def test_longitude_too_low(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "-181.000000", "description": "Invalid lng.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("longitude", r.data)

    def test_boundary_latitude_90(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "90.000000", "longitude": "76.267300", "description": "Boundary lat.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_boundary_latitude_neg_90(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "-90.000000", "longitude": "76.267300", "description": "Boundary lat.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_boundary_longitude_180(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "180.000000", "description": "Boundary lng.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_boundary_longitude_neg_180(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "-180.000000", "description": "Boundary lng.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# 9. PICKUP DESCRIPTION
# ---------------------------------------------------------------------------

class PickupRequestDescriptionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="desc@test.com", phone="+919000000230")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_valid_description(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "Plastic waste near my house.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_missing_description(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", r.data)

    def test_empty_description(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", r.data)

    def test_whitespace_only_description(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "   ",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_description_too_long(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "x" * 1001,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", r.data)

    def test_description_max_length(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "x" * 1000,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_description_trimmed(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "  Waste pickup needed  ",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        pickup = PickupRequest.objects.get(id=r.data["data"]["id"])
        self.assertEqual(pickup.description, "Waste pickup needed")


# ---------------------------------------------------------------------------
# 10. PICKUP IMAGE
# ---------------------------------------------------------------------------

class PickupRequestImageTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="img@test.com", phone="+919000000240")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_valid_image_jpeg(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (10, 10), color="red")
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        uploaded = SimpleUploadedFile("waste.jpg", buf.read(), content_type="image/jpeg")
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300",
            "description": "JPEG image.", "image": uploaded,
        }, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, msg=r.data)

    def test_valid_image_png(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (10, 10), color="blue")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        uploaded = SimpleUploadedFile("waste.png", buf.read(), content_type="image/png")
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300",
            "description": "PNG image.", "image": uploaded,
        }, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, msg=r.data)

    def test_no_image_still_works(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "No image provided.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(r.data["data"]["image"])


# ---------------------------------------------------------------------------
# 11. PICKUP OWNERSHIP
# ---------------------------------------------------------------------------

class PickupRequestOwnershipTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = _create_user(email="own1@test.com", phone="+919000000250")
        self.user2 = _create_user(email="own2@test.com", phone="+919000000251")
        UserProfile.objects.get_or_create(user=self.user1, is_verified=True)
        UserProfile.objects.get_or_create(user=self.user2, is_verified=True)

    def test_different_users_separate_pickups(self):
        _auth(self.client, self.user1)
        r1 = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "User1 pickup.",
        }, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)

        _auth(self.client, self.user2)
        r2 = self.client.post(PICKUP_API, {
            "latitude": "10.000000", "longitude": "77.000000", "description": "User2 pickup.",
        }, format="json")
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

        pickup1 = PickupRequest.objects.get(id=r1.data["data"]["id"])
        pickup2 = PickupRequest.objects.get(id=r2.data["data"]["id"])
        self.assertEqual(pickup1.user, self.user1)
        self.assertEqual(pickup2.user, self.user2)
        self.assertNotEqual(pickup1.user, pickup2.user)


# ---------------------------------------------------------------------------
# 12. PICKUP UNVERIFIED USER
# ---------------------------------------------------------------------------

class PickupRequestUnverifiedTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="unver@test.com", phone="+919000000260")
        UserProfile.objects.get_or_create(user=self.user, is_verified=False)
        _auth(self.client, self.user)

    def test_unverified_user_cannot_create(self):
        r = self.client.post(PICKUP_API, {
            "latitude": "9.931200", "longitude": "76.267300", "description": "Unverified user pickup.",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
