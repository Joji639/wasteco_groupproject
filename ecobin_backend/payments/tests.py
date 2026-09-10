"""Tests for payments app — Waste collection recording, Razorpay integration, and payment status APIs."""

import uuid
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.test import TestCase, RequestFactory
from django.test.utils import override_settings
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, OperatorProfile, OperatorAdminProfile
from accounts.serializers import get_tokens_for_user
from pickups.models import PickupRequest
from .models import WasteCollection, Payment
from .views import razorpay_webhook

API = "/api/payments/"


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


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


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


class OperatorAssignedPickupsViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op1@test.com')
        self.user = _create_user(email='user1@test.com')

    def test_list_assigned_pickups(self):
        pickup = _create_pickup(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/assigned-pickups/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['data'][0]['pickup_id'], str(pickup.id))

    def test_list_assigned_pickups_filter_status(self):
        _create_pickup(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _create_pickup(self.user, status='ON_THE_WAY', assigned_operator=self.operator)
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/assigned-pickups/?status=ASSIGNED')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_list_assigned_pickups_unauthenticated(self):
        resp = self.client.get(f'{API}operator/assigned-pickups/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_assigned_pickups_wrong_role(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}operator/assigned-pickups/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class OperatorStartTaskViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op2@test.com')
        self.user = _create_user(email='user2@test.com')
        self.pickup = _create_pickup(self.user, status='ASSIGNED', assigned_operator=self.operator)

    def test_start_task_success(self):
        _auth(self.client, self.operator)
        resp = self.client.patch(f'{API}operator/pickups/{self.pickup.id}/start/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['success'])
        self.pickup.refresh_from_db()
        self.assertEqual(self.pickup.status, 'ON_THE_WAY')

    def test_start_task_wrong_status(self):
        self.pickup.status = 'COLLECTED'
        self.pickup.save()
        _auth(self.client, self.operator)
        resp = self.client.patch(f'{API}operator/pickups/{self.pickup.id}/start/')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_start_task_not_assigned(self):
        other_operator = _create_operator(email='op3@test.com')
        _auth(self.client, other_operator)
        resp = self.client.patch(f'{API}operator/pickups/{self.pickup.id}/start/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_start_task_not_found(self):
        _auth(self.client, self.operator)
        fake_id = uuid.uuid4()
        resp = self.client.patch(f'{API}operator/pickups/{fake_id}/start/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class OperatorRecordCollectionViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op4@test.com')
        self.user = _create_user(email='user3@test.com')
        self.pickup = _create_pickup(self.user, status='ON_THE_WAY', assigned_operator=self.operator)

    def test_record_collection_cash_success(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '2.5',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['plastic_amount'], '12.50')
        self.assertEqual(resp.data['data']['total_amount'], '12.50')
        self.pickup.refresh_from_db()
        self.assertEqual(self.pickup.status, 'COLLECTED')

    def test_record_collection_online_success(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '1',
            'e_waste_kg': '0.5',
            'payment_method': 'ONLINE',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['data']['plastic_amount'], '5.00')
        self.assertEqual(resp.data['data']['e_waste_amount'], '10.00')
        self.assertEqual(resp.data['data']['total_amount'], '15.00')

    def test_record_collection_both_waste_types(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '3',
            'e_waste_kg': '1',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['data']['plastic_amount'], '15.00')
        self.assertEqual(resp.data['data']['e_waste_amount'], '20.00')
        self.assertEqual(resp.data['data']['total_amount'], '35.00')

    def test_record_collection_zero_waste_rejected(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '0',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_record_collection_duplicate_rejected(self):
        WasteCollection.objects.create(
            pickup_request=self.pickup,
            operator=self.operator,
            plastic_kg=Decimal('1'),
            e_waste_kg=Decimal('0'),
            payment_method='CASH',
            status='PAID',
        )
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '1',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_record_collection_wrong_operator(self):
        other_operator = _create_operator(email='op5@test.com')
        _auth(self.client, other_operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '1',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_record_collection_pickup_wrong_status(self):
        self.pickup.status = 'COMPLETED'
        self.pickup.save()
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '1',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_record_collection_unauthenticated(self):
        resp = self.client.post(f'{API}operator/collections/create/', {
            'pickup_request_id': str(self.pickup.id),
            'plastic_kg': '1',
            'e_waste_kg': '0',
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class OperatorCollectionViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op6@test.com')
        self.user = _create_user(email='user4@test.com')

    def test_list_collections(self):
        pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        WasteCollection.objects.create(
            pickup_request=pickup, operator=self.operator,
            plastic_kg=Decimal('2'), e_waste_kg=Decimal('0'),
            payment_method='CASH', status='PAID',
        )
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/collections/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_list_collections_empty(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/collections/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)


class OperatorCollectionDetailViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op7@test.com')
        self.user = _create_user(email='user5@test.com')
        self.pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        self.collection = WasteCollection.objects.create(
            pickup_request=self.pickup, operator=self.operator,
            plastic_kg=Decimal('2'), e_waste_kg=Decimal('1'),
            payment_method='CASH', status='PAID',
        )

    def test_get_collection_detail(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/collections/{self.collection.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['plastic_amount'], '10.00')
        self.assertEqual(resp.data['data']['e_waste_amount'], '20.00')
        self.assertEqual(resp.data['data']['total_amount'], '30.00')

    def test_get_collection_not_found(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/collections/{uuid.uuid4()}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class OperatorInitiatePaymentViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op8@test.com')
        self.user = _create_user(email='user6@test.com')
        self.pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        self.collection = WasteCollection.objects.create(
            pickup_request=self.pickup, operator=self.operator,
            plastic_kg=Decimal('2'), e_waste_kg=Decimal('0'),
            payment_method='ONLINE', status='PENDING',
        )

    @patch('payments.views.create_razorpay_order')
    def test_initiate_payment_success(self, mock_order):
        mock_order.return_value = {'id': 'order_test123'}
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/{self.collection.id}/payment/')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['order_id'], 'order_test123')
        self.assertEqual(resp.data['data']['key_id'], settings.RAZORPAY_KEY_ID)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.status, 'AMOUNT_DUE')
        payment = Payment.objects.get(collection=self.collection)
        self.assertEqual(payment.payment_status, 'CREATED')

    def test_initiate_payment_cash_collection_rejected(self):
        self.collection.payment_method = 'CASH'
        self.collection.save()
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/{self.collection.id}/payment/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_initiate_payment_already_paid(self):
        self.collection.status = 'PAID'
        self.collection.save()
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/{self.collection.id}/payment/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('payments.views.create_razorpay_order')
    def test_initiate_payment_razorpay_failure(self, mock_order):
        mock_order.side_effect = Exception("Razorpay API error")
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/{self.collection.id}/payment/')
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_initiate_payment_not_found(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator/collections/{uuid.uuid4()}/payment/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class PaymentStatusViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op9@test.com')
        self.user = _create_user(email='user7@test.com')
        self.pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        self.collection = WasteCollection.objects.create(
            pickup_request=self.pickup, operator=self.operator,
            plastic_kg=Decimal('2'), e_waste_kg=Decimal('0'),
            payment_method='ONLINE', status='AMOUNT_DUE',
        )
        self.payment = Payment.objects.create(
            collection=self.collection,
            amount=Decimal('10.00'),
            currency='INR',
            payment_method='ONLINE',
            payment_status='CREATED',
            razorpay_order_id='order_test456',
        )

    def test_payment_status_success(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/pickups/{self.pickup.id}/payment/status/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['payment_status'], 'CREATED')
        self.assertIn('checkout_url', resp.data['data'])

    def test_payment_status_wrong_user(self):
        other_user = _create_user(email='user8@test.com')
        _auth(self.client, other_user)
        resp = self.client.get(f'{API}user/pickups/{self.pickup.id}/payment/status/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_payment_status_no_collection(self):
        pickup2 = _create_pickup(self.user, status='PENDING')
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/pickups/{pickup2.id}/payment/status/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_payment_status_no_payment(self):
        pickup2 = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        WasteCollection.objects.create(
            pickup_request=pickup2, operator=self.operator,
            plastic_kg=Decimal('1'), e_waste_kg=Decimal('0'),
            payment_method='CASH', status='PAID',
        )
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/pickups/{pickup2.id}/payment/status/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_payment_status_pickup_not_found(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/pickups/{uuid.uuid4()}/payment/status/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RazorpayWebhookTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.operator = _create_operator(email='op10@test.com')
        self.user = _create_user(email='user9@test.com')
        self.pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        self.collection = WasteCollection.objects.create(
            pickup_request=self.pickup, operator=self.operator,
            plastic_kg=Decimal('2'), e_waste_kg=Decimal('0'),
            payment_method='ONLINE', status='AMOUNT_DUE',
        )
        self.payment = Payment.objects.create(
            collection=self.collection,
            amount=Decimal('10.00'),
            currency='INR',
            payment_method='ONLINE',
            payment_status='CREATED',
            razorpay_order_id='order_webhook_test',
        )

    @override_settings(RAZORPAY_KEY_SECRET='test_webhook_secret')
    @patch('payments.views.verify_razorpay_signature')
    def test_webhook_payment_captured(self, mock_verify):
        mock_verify.return_value = True
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_captured_123',
                        'order_id': 'order_webhook_test',
                        'signature': 'sig_123',
                    }
                }
            }
        }
        request = self.factory.post(
            f'{API}razorpay/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='valid_sig',
        )
        resp = razorpay_webhook(request)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, 'CAPTURED')
        self.assertEqual(self.payment.razorpay_payment_id, 'pay_captured_123')
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.status, 'PAID')

    @override_settings(RAZORPAY_KEY_SECRET='test_webhook_secret')
    @patch('payments.views.verify_razorpay_signature')
    def test_webhook_payment_failed(self, mock_verify):
        mock_verify.return_value = True
        payload = {
            'event': 'payment.failed',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_failed_123',
                        'order_id': 'order_webhook_test',
                    }
                }
            }
        }
        request = self.factory.post(
            f'{API}razorpay/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='valid_sig',
        )
        resp = razorpay_webhook(request)
        self.assertEqual(resp.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, 'FAILED')

    @override_settings(RAZORPAY_KEY_SECRET='test_webhook_secret')
    @patch('payments.views.verify_razorpay_signature')
    def test_webhook_invalid_signature(self, mock_verify):
        mock_verify.return_value = False
        payload = {'event': 'payment.captured', 'payload': {}}
        request = self.factory.post(
            f'{API}razorpay/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='invalid_sig',
        )
        resp = razorpay_webhook(request)
        self.assertEqual(resp.status_code, 400)

    @override_settings(RAZORPAY_KEY_SECRET='test_webhook_secret')
    @patch('payments.views.verify_razorpay_signature')
    def test_webhook_unknown_order_ignored(self, mock_verify):
        mock_verify.return_value = True
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_unknown',
                        'order_id': 'order_nonexistent',
                    }
                }
            }
        }
        request = self.factory.post(
            f'{API}razorpay/webhook/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='valid_sig',
        )
        resp = razorpay_webhook(request)
        self.assertEqual(resp.status_code, 200)


class WasteCollectionModelTests(TestCase):
    def setUp(self):
        self.operator = _create_operator(email='op11@test.com')
        self.user = _create_user(email='user10@test.com')

    def test_calculate_amounts_plastic_only(self):
        pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        collection = WasteCollection.objects.create(
            pickup_request=pickup, operator=self.operator,
            plastic_kg=Decimal('5'), e_waste_kg=Decimal('0'),
            payment_method='CASH',
        )
        self.assertEqual(collection.plastic_amount, Decimal('25.00'))
        self.assertEqual(collection.e_waste_amount, Decimal('0.00'))
        self.assertEqual(collection.total_amount, Decimal('25.00'))

    def test_calculate_amounts_both(self):
        pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        collection = WasteCollection.objects.create(
            pickup_request=pickup, operator=self.operator,
            plastic_kg=Decimal('3'), e_waste_kg=Decimal('2'),
            payment_method='ONLINE',
        )
        self.assertEqual(collection.plastic_amount, Decimal('15.00'))
        self.assertEqual(collection.e_waste_amount, Decimal('40.00'))
        self.assertEqual(collection.total_amount, Decimal('55.00'))

    def test_calculate_amounts_e_waste_only(self):
        pickup = _create_pickup(self.user, status='COLLECTED', assigned_operator=self.operator)
        collection = WasteCollection.objects.create(
            pickup_request=pickup, operator=self.operator,
            plastic_kg=Decimal('0'), e_waste_kg=Decimal('1.5'),
            payment_method='CASH',
        )
        self.assertEqual(collection.e_waste_amount, Decimal('30.00'))
        self.assertEqual(collection.total_amount, Decimal('30.00'))
