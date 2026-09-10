"""Tests for Operator Review & Rating APIs, Geocoding, and Live Tracking."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, OperatorProfile, OperatorAdminProfile
from accounts.serializers import get_tokens_for_user
from pickups.models import PickupRequest, OperatorReview

USER_API = "/users/"
OPERATOR_API = "/operators/"
OPADMIN_API = "/operator-admins/"
SUPERADMIN_API = "/superadmins/"


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


def _create_pickup(user, status='COMPLETED', assigned_operator=None):
    return PickupRequest.objects.create(
        user=user,
        pickup_type='ON_DEMAND',
        latitude=Decimal('8.5241'),
        longitude=Decimal('76.9366'),
        description='Test waste pickup',
        status=status,
        assigned_operator=assigned_operator,
    )


# ===========================================================================
# USER REVIEW TESTS
# ===========================================================================

class UserReviewCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='user1@test.com')
        self.operator = _create_operator(email='op1@test.com')
        self.pickup = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)

    def test_create_review_success_with_comment(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5, 'comment': 'Very good service.'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['rating'], 5)
        self.assertEqual(resp.data['data']['comment'], 'Very good service.')
        self.assertIn('id', resp.data['data'])
        self.assertIn('pickup_request_id', resp.data['data'])
        self.assertIn('operator_id', resp.data['data'])

    def test_create_review_success_without_comment(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 4},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['data']['rating'], 4)
        self.assertIsNone(resp.data['data']['comment'])

    def test_create_review_rating_1(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['data']['rating'], 1)

    def test_create_review_rating_5(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5, 'comment': 'Excellent!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['data']['rating'], 5)

    def test_review_before_completion_rejected(self):
        pickup2 = _create_pickup(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{pickup2.id}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('completed', resp.data['message'].lower())

    def test_review_another_users_pickup_rejected(self):
        other_user = _create_user(email='user2@test.com')
        pickup2 = _create_pickup(other_user, status='COMPLETED', assigned_operator=self.operator)
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{pickup2.id}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_review_rejected(self):
        _auth(self.client, self.user)
        self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5},
            format='json',
        )
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 4},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already', resp.data['message'].lower())

    def test_invalid_rating_below_1(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 0},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_rating_above_5(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 6},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_integer_rating_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 4.5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_comment_too_long_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5, 'comment': 'x' * 501},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_rejected(self):
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_user_role_rejected(self):
        _auth(self.client, self.operator)
        resp = self.client.post(
            f'{USER_API}pickups/{self.pickup.id}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_review_no_assigned_operator_rejected(self):
        pickup2 = _create_pickup(self.user, status='COMPLETED', assigned_operator=None)
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{pickup2.id}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('operator', resp.data['message'].lower())

    def test_pickup_not_found(self):
        _auth(self.client, self.user)
        resp = self.client.post(
            f'{USER_API}pickups/{uuid.uuid4()}/review/',
            {'rating': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class UserReviewDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='user3@test.com')
        self.operator = _create_operator(email='op3@test.com')
        self.pickup = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)
        self.review = OperatorReview.objects.create(
            pickup_request=self.pickup,
            user=self.user,
            operator=self.operator,
            rating=5,
            comment='Great service.',
        )

    def test_get_review_success(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{USER_API}pickups/{self.pickup.id}/review/detail/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['rating'], 5)
        self.assertEqual(resp.data['data']['comment'], 'Great service.')

    def test_get_review_not_found(self):
        pickup2 = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)
        _auth(self.client, self.user)
        resp = self.client.get(f'{USER_API}pickups/{pickup2.id}/review/detail/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_review_wrong_user(self):
        other_user = _create_user(email='user4@test.com')
        _auth(self.client, other_user)
        resp = self.client.get(f'{USER_API}pickups/{self.pickup.id}/review/detail/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_review_pickup_not_found(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{USER_API}pickups/{uuid.uuid4()}/review/detail/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# OPERATOR REVIEW TESTS
# ===========================================================================

class OperatorReviewsViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op4@test.com')
        self.user = _create_user(email='user5@test.com')
        self.user2 = _create_user(email='user6@test.com')
        self.pickup1 = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)
        self.pickup2 = _create_pickup(self.user2, status='COMPLETED', assigned_operator=self.operator)
        OperatorReview.objects.create(
            pickup_request=self.pickup1, user=self.user, operator=self.operator,
            rating=5, comment='Excellent.',
        )
        OperatorReview.objects.create(
            pickup_request=self.pickup2, user=self.user2, operator=self.operator,
            rating=4, comment='Good.',
        )

    def test_operator_gets_own_reviews(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{OPERATOR_API}reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)

    def test_operator_cannot_see_other_operators_reviews(self):
        other_op = _create_operator(email='op5@test.com')
        _auth(self.client, other_op)
        resp = self.client.get(f'{OPERATOR_API}reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)

    def test_operator_reviews_no_pii(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{OPERATOR_API}reviews/')
        for review in resp.data['data']:
            self.assertNotIn('user', review)
            self.assertNotIn('email', review)
            self.assertNotIn('phone', review)

    def test_non_operator_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{OPERATOR_API}reviews/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class OperatorRatingSummaryViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op6@test.com')
        self.user = _create_user(email='user7@test.com')

    def test_operator_with_reviews(self):
        pickup = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)
        ratings = [5, 4, 5, 5, 3]
        emails = [f'u{i}r@test.com' for i in range(len(ratings))]
        for idx, rating in enumerate(ratings):
            user = _create_user(email=emails[idx])
            p = _create_pickup(user, status='COMPLETED', assigned_operator=self.operator)
            OperatorReview.objects.create(
                pickup_request=p, user=user, operator=self.operator, rating=rating,
            )
        _auth(self.client, self.operator)
        resp = self.client.get(f'{OPERATOR_API}reviews/summary/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['total_reviews'], 5)
        self.assertEqual(resp.data['data']['average_rating'], 4.4)
        self.assertEqual(resp.data['data']['rating_distribution']['5'], 3)
        self.assertEqual(resp.data['data']['rating_distribution']['4'], 1)
        self.assertEqual(resp.data['data']['rating_distribution']['3'], 1)

    def test_operator_no_reviews(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{OPERATOR_API}reviews/summary/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['total_reviews'], 0)
        self.assertIsNone(resp.data['data']['average_rating'])
        self.assertEqual(resp.data['data']['rating_distribution'], {'5': 0, '4': 0, '3': 0, '2': 0, '1': 0})

    def test_non_operator_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{OPERATOR_API}reviews/summary/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# OPERATOR ADMIN RATING TESTS
# ===========================================================================

class OperatorAdminRatingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa1@test.com', panchayath='TVM')
        self.operator1 = _create_operator(email='op7@test.com')
        self.operator2 = _create_operator(email='op8@test.com')
        self.user = _create_user(email='user8@test.com')
        self.user2 = _create_user(email='user9@test.com')

        self.operator1.operator_profile.assigned_admin = self.admin.operatoradmin_profile
        self.operator1.operator_profile.save()
        self.operator2.operator_profile.assigned_admin = self.admin.operatoradmin_profile
        self.operator2.operator_profile.save()

        pickup1 = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator1)
        pickup2 = _create_pickup(self.user2, status='COMPLETED', assigned_operator=self.operator1)
        OperatorReview.objects.create(
            pickup_request=pickup1, user=self.user, operator=self.operator1,
            rating=5, comment='Great.',
        )
        OperatorReview.objects.create(
            pickup_request=pickup2, user=self.user2, operator=self.operator1,
            rating=4, comment='Good.',
        )

    def test_admin_gets_operator_ratings(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/ratings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)
        op1_data = next(r for r in resp.data['data'] if r['operator_id'] == self.operator1.id)
        self.assertEqual(op1_data['total_reviews'], 2)
        self.assertEqual(op1_data['average_rating'], 4.5)

    def test_admin_cannot_see_unassigned_operators(self):
        unassigned_op = _create_operator(email='op9@test.com')
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/ratings/')
        op_ids = [r['operator_id'] for r in resp.data['data']]
        self.assertNotIn(str(unassigned_op.id), op_ids)

    def test_admin_gets_specific_operator_reviews(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/{self.operator1.id}/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['total_reviews'], 2)
        self.assertEqual(len(resp.data['data']['reviews']), 2)
        self.assertIn('rating_distribution', resp.data['data'])

    def test_admin_cannot_access_unauthorized_operator(self):
        unassigned_op = _create_operator(email='op10@test.com')
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/{unassigned_op.id}/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_operator_not_found(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/{uuid.uuid4()}/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_opadmin_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{OPADMIN_API}operators/ratings/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_rating_distribution_correct(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{OPADMIN_API}operators/{self.operator1.id}/reviews/')
        dist = resp.data['data']['rating_distribution']
        self.assertEqual(dist['5'], 1)
        self.assertEqual(dist['4'], 1)
        self.assertEqual(dist['3'], 0)
        self.assertEqual(dist['2'], 0)
        self.assertEqual(dist['1'], 0)


# ===========================================================================
# SUPER ADMIN RATING TESTS
# ===========================================================================

class SuperAdminRatingsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superadmin = _create_superuser(email='sa1@test.com')
        self.operator = _create_operator(email='op11@test.com')
        self.user = _create_user(email='user10@test.com')
        pickup = _create_pickup(self.user, status='COMPLETED', assigned_operator=self.operator)
        OperatorReview.objects.create(
            pickup_request=pickup, user=self.user, operator=self.operator,
            rating=5, comment='Excellent.',
        )

    def test_superadmin_gets_all_ratings(self):
        _auth(self.client, self.superadmin)
        resp = self.client.get(f'{SUPERADMIN_API}operators/ratings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(resp.data['count'], 1)
        op_data = next(r for r in resp.data['data'] if r['operator_id'] == self.operator.id)
        self.assertEqual(op_data['total_reviews'], 1)
        self.assertEqual(op_data['average_rating'], 5.0)

    def test_non_superadmin_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{SUPERADMIN_API}operators/ratings/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# GEOCODING TESTS
# ===========================================================================

class PickupGeocodingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='geo_user@test.com')
        from accounts.models import UserProfile
        UserProfile.objects.get_or_create(user=self.user, is_verified=True)

    def test_pickup_with_place_geocoded(self):
        _auth(self.client, self.user)
        with patch('pickups.serializers.geocode_place') as mock_geocode:
            mock_geocode.return_value = (9.9312, 76.2673)
            resp = self.client.post('/users/pickups/', {
                'place': 'MG Road, Kochi, Kerala',
                'description': 'Waste near home.',
            }, format='json')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertEqual(resp.data['data']['latitude'], '9.931200')
            self.assertEqual(resp.data['data']['longitude'], '76.267300')
            mock_geocode.assert_called_once_with('MG Road, Kochi, Kerala')

    def test_pickup_with_lat_lng_no_place(self):
        _auth(self.client, self.user)
        resp = self.client.post('/users/pickups/', {
            'latitude': '9.931200',
            'longitude': '76.267300',
            'description': 'Direct coordinates.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_pickup_with_place_and_lat_lng_uses_place(self):
        _auth(self.client, self.user)
        with patch('pickups.serializers.geocode_place') as mock_geocode:
            mock_geocode.return_value = (10.0000, 77.0000)
            resp = self.client.post('/users/pickups/', {
                'place': 'Chennai, Tamil Nadu',
                'latitude': '9.931200',
                'longitude': '76.267300',
                'description': 'Place overrides lat/lng.',
            }, format='json')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertEqual(resp.data['data']['latitude'], '10.000000')
            self.assertEqual(resp.data['data']['longitude'], '77.000000')

    def test_pickup_place_geocoding_fails_rejected(self):
        _auth(self.client, self.user)
        with patch('pickups.serializers.geocode_place') as mock_geocode:
            mock_geocode.return_value = None
            resp = self.client.post('/users/pickups/', {
                'place': 'XYZNONEXISTENT12345',
                'description': 'Bad place.',
            }, format='json')
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pickup_no_place_no_lat_lng_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.post('/users/pickups/', {
            'description': 'Missing location.',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ===========================================================================
# LIVE TRACKING TESTS (Redis)
# ===========================================================================

class OperatorLocationTrackingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='track_op@test.com')
        self.user = _create_user(email='track_user@test.com')
        self.pickup = _create_pickup(self.user, status='ON_THE_WAY', assigned_operator=self.operator)

    def test_operator_update_location_success(self):
        _auth(self.client, self.operator)
        resp = self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['success'])

    def test_user_get_operator_location(self):
        _auth(self.client, self.operator)
        self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')

        _auth(self.client, self.user)
        resp = self.client.get(f'/operators/location/{self.pickup.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data['data'])
        self.assertEqual(resp.data['data']['lat'], '9.9312')

    def test_operator_get_own_location(self):
        _auth(self.client, self.operator)
        self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')

        resp = self.client.get(f'/operators/location/{self.pickup.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data['data'])

    def test_unauthorized_user_cannot_see_location(self):
        _auth(self.client, self.operator)
        self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')

        other_user = _create_user(email='other@test.com')
        _auth(self.client, other_user)
        resp = self.client.get(f'/operators/location/{self.pickup.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_location_not_available_when_not_updated(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'/operators/location/{self.pickup.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data['data'])

    def test_wrong_operator_cannot_update_location(self):
        other_op = _create_operator(email='other_op@test.com')
        _auth(self.client, other_op)
        resp = self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_location_missing_fields(self):
        _auth(self.client, self.operator)
        resp = self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_location_invalid_coordinates(self):
        _auth(self.client, self.operator)
        resp = self.client.post('/operators/location/update/', {
            'pickup_id': str(self.pickup.id),
            'latitude': 999,
            'longitude': 76.2673,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_location_pickup_not_found(self):
        _auth(self.client, self.operator)
        resp = self.client.post('/operators/location/update/', {
            'pickup_id': str(uuid.uuid4()),
            'latitude': 9.9312,
            'longitude': 76.2673,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_location_pickup_not_found(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'/operators/location/{uuid.uuid4()}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
