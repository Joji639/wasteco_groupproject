"""Tests for ecobinusers app."""

from datetime import date, time, timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import CustomUser, UserProfile
from .models import (
    WastePickupRequest, PickupSchedule, Review,
    WasteCollection, Complaint,
)

API = "/ecobinusers/"


def _create_user(email="user@test.com", password="Test1234!", **kw):
    return CustomUser.objects.create_user(email=email, password=password, base_role="user", **kw)


def _tokens(user):
    from accounts.serializers import get_tokens_for_user
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


# ---------------------------------------------------------------------------
# 1. WASTE PICKUP REQUEST
# ---------------------------------------------------------------------------

class WastePickupRequestCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "requests/"
        self.user = _create_user(email="wr@test.com", phone="+919000000100")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_create_request(self):
        r = self.client.post(self.url, {
            "complaint_type": "household",
            "description": "Weekly pickup",
            "location": "123 Main St",
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(WastePickupRequest.objects.filter(user=self.user).exists())

    def test_create_request_unverified_user(self):
        UserProfile.objects.filter(user=self.user).update(is_verified=False)
        r = self.client.post(self.url, {
            "complaint_type": "household",
            "description": "Test",
            "location": "123 St",
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_request_unauthenticated(self):
        self.client.credentials()
        r = self.client.post(self.url, {
            "complaint_type": "household",
            "description": "Test",
            "location": "123 St",
        })
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_request_invalid_type(self):
        r = self.client.post(self.url, {
            "complaint_type": "invalid",
            "description": "Test",
            "location": "123 St",
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class WastePickupRequestListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "requests/list/"
        self.user = _create_user(email="wrl@test.com", phone="+919000000101")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_list_empty(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_list_with_requests(self):
        WastePickupRequest.objects.create(
            user=self.user, complaint_type="household",
            description="Test", location="123 St"
        )
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)

    def test_list_only_own_requests(self):
        other_user = _create_user(email="other@test.com", phone="+919000000102")
        WastePickupRequest.objects.create(
            user=other_user, complaint_type="household",
            description="Other", location="456 St"
        )
        r = self.client.get(self.url)
        self.assertEqual(r.data["count"], 0)


# ---------------------------------------------------------------------------
# 2. PICKUP DATE
# ---------------------------------------------------------------------------

class PickupDateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "pickup-date/"
        self.user = _create_user(email="pd@test.com", phone="+919000000103")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        PickupSchedule.objects.filter(user=self.user).delete()
        _auth(self.client, self.user)

    def test_no_schedule_returns_default(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("next_pickup_date", r.data["data"])

    def test_future_schedule(self):
        today = timezone.now().date()
        future_date = today + timedelta(days=10)
        PickupSchedule.objects.create(user=self.user, scheduled_date=future_date)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["data"]["next_pickup_date"], str(future_date))

    def test_past_schedule_switches_to_next(self):
        today = timezone.now().date()
        past_date = today - timedelta(days=1)
        PickupSchedule.objects.create(user=self.user, scheduled_date=past_date)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("Switched to next", r.data["data"]["message"])


# ---------------------------------------------------------------------------
# 3. REVIEWS
# ---------------------------------------------------------------------------

class ReviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "reviews/"
        self.user = _create_user(email="rv@test.com", phone="+919000000104")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        self.waste_request = WastePickupRequest.objects.create(
            user=self.user, complaint_type="household",
            description="Test", location="123 St"
        )
        _auth(self.client, self.user)

    def test_create_review(self):
        r = self.client.post(self.url, {
            "waste_request": str(self.waste_request.id),
            "rating": 5,
            "review_text": "Great service!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_create_review_invalid_rating(self):
        r = self.client.post(self.url, {
            "waste_request": str(self.waste_request.id),
            "rating": 6,
            "review_text": "Good",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_review_rating_zero(self):
        r = self.client.post(self.url, {
            "waste_request": str(self.waste_request.id),
            "rating": 0,
            "review_text": "Bad",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_reviews(self):
        Review.objects.create(user=self.user, waste_request=self.waste_request, rating=5)
        r = self.client.get(API + "reviews/list/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)


# ---------------------------------------------------------------------------
# 4. WASTE COLLECTIONS
# ---------------------------------------------------------------------------

class WasteCollectionHistoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = API + "collections/"
        self.user = _create_user(email="wc@test.com", phone="+919000000107")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_empty_collections(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 0)

    def test_list_collections(self):
        WasteCollection.objects.create(
            user=self.user, waste_type="Household",
            date=date.today(), time=time(10, 0), status="completed"
        )
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 1)

    def test_only_own_collections(self):
        other = _create_user(email="other_wc@test.com", phone="+919000000108")
        WasteCollection.objects.create(
            user=other, waste_type="Recyclable",
            date=date.today(), time=time(14, 0)
        )
        r = self.client.get(self.url)
        self.assertEqual(r.data["count"], 0)


# ---------------------------------------------------------------------------
# 5. COMPLAINTS
# ---------------------------------------------------------------------------

class ComplaintTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.list_url = API + "complaints/"
        self.create_url = API + "complaints/create/"
        self.user = _create_user(email="comp@test.com", phone="+919000000109")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)
        _auth(self.client, self.user)

    def test_create_complaint(self):
        r = self.client.post(self.create_url, {
            "subject": "Late pickup",
            "description": "Operator was 2 hours late",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_create_complaint_with_location(self):
        r = self.client.post(self.create_url, {
            "subject": "Overflowing bin",
            "description": "The bin near my house is overflowing",
            "location": "123 Main Street, Ward 5",
            "latitude": "10.012345",
            "longitude": "76.345678",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["data"]["location"], "123 Main Street, Ward 5")
        self.assertEqual(r.data["data"]["latitude"], "10.012345")
        self.assertEqual(r.data["data"]["longitude"], "76.345678")

    def test_create_complaint_with_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from io import BytesIO
        img = Image.new("RGB", (10, 10), color="red")
        buf = BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)
        uploaded = SimpleUploadedFile("test.jpg", buf.read(), content_type="image/jpeg")
        r = self.client.post(self.create_url, {
            "subject": "Illegal dumping",
            "description": "Someone dumped waste illegally",
            "location": "Park Avenue",
            "image": uploaded,
        }, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, msg=r.data)
        self.assertIn("image", r.data["data"])

    def test_create_complaint_without_image(self):
        r = self.client.post(self.create_url, {
            "subject": "Noise complaint",
            "description": "Collection truck is too loud",
            "location": "456 Oak Street",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(r.data["data"]["image"])

    def test_list_all_complaints(self):
        Complaint.objects.create(user=self.user, subject="A", description="D", status="open")
        Complaint.objects.create(user=self.user, subject="B", description="D", status="resolved")
        r = self.client.get(self.list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["count"], 2)

    def test_only_own_complaints(self):
        other = _create_user(email="other_comp@test.com", phone="+919000000110")
        Complaint.objects.create(user=other, subject="X", description="D")
        r = self.client.get(self.list_url)
        self.assertEqual(r.data["count"], 0)


# ---------------------------------------------------------------------------
# 6. PERMISSIONS
# ---------------------------------------------------------------------------

class PermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email="perm@test.com", phone="+919000000111")
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)

    def test_unauthenticated_all_endpoints(self):
        urls = [
            (API + "requests/", "get"),
            (API + "pickup-date/", "get"),
            (API + "reviews/", "get"),
            (API + "collections/", "get"),
            (API + "complaints/", "get"),
        ]
        for url, method in urls:
            r = getattr(self.client, method)(url)
            self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED, f"Failed for {url}")
