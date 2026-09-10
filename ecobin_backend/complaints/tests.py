"""Tests for Complaint Management API."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, OperatorProfile, OperatorAdminProfile
from accounts.serializers import get_tokens_for_user
from .models import Complaint, ComplaintStatusHistory

API = "/api/"


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


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens


def _create_complaint(user, status='PENDING', assigned_operator=None):
    return Complaint.objects.create(
        user=user,
        place='MG Road, Kochi',
        latitude=Decimal('9.931200'),
        longitude=Decimal('76.267300'),
        description='Garbage dumped near road.',
        status=status,
        assigned_operator=assigned_operator,
    )


# ===========================================================================
# USER COMPLAINT TESTS
# ===========================================================================

class UserComplaintCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='cu1@test.com')

    def test_create_complaint_success(self):
        _auth(self.client, self.user)
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = (9.9312, 76.2673)
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'MG Road, Kochi',
                'description': 'Garbage dumped near road.',
            }, format='multipart')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertTrue(resp.data['success'])
            self.assertEqual(resp.data['data']['status'], 'PENDING')
            self.assertEqual(resp.data['data']['latitude'], '9.931200')

    def test_create_complaint_geocoding_fails(self):
        _auth(self.client, self.user)
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = None
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'XYZNONEXISTENT',
                'description': 'Bad place.',
            }, format='multipart')
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_complaint_empty_place_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.post(f'{API}user/complaints/', {
            'place': '   ',
            'description': 'Test.',
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_complaint_empty_description_rejected(self):
        _auth(self.client, self.user)
        resp = self.client.post(f'{API}user/complaints/', {
            'place': 'MG Road, Kochi',
            'description': '   ',
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_complaint_unauthenticated(self):
        resp = self.client.post(f'{API}user/complaints/', {
            'place': 'MG Road, Kochi',
            'description': 'Test.',
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_complaint_non_user_rejected(self):
        op = _create_operator(email='cu_op@test.com')
        _auth(self.client, op)
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = (9.9312, 76.2673)
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'MG Road, Kochi',
                'description': 'Test.',
            }, format='multipart')
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_client_cannot_set_status(self):
        _auth(self.client, self.user)
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = (9.9312, 76.2673)
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'MG Road, Kochi',
                'description': 'Test.',
                'status': 'RESOLVED',
            }, format='multipart')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertEqual(resp.data['data']['status'], 'PENDING')

    def test_client_cannot_set_assigned_operator(self):
        _auth(self.client, self.user)
        op = _create_operator(email='cu_op2@test.com')
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = (9.9312, 76.2673)
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'MG Road, Kochi',
                'description': 'Test.',
                'assigned_operator': str(op.id),
            }, format='multipart')
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertIsNone(resp.data['data']['assigned_operator'])

    def test_status_history_created(self):
        _auth(self.client, self.user)
        with patch('complaints.views.geocode_place') as mock_geo:
            mock_geo.return_value = (9.9312, 76.2673)
            resp = self.client.post(f'{API}user/complaints/', {
                'place': 'MG Road, Kochi',
                'description': 'Test.',
            }, format='multipart')
            complaint_id = resp.data['data']['id']
            history = ComplaintStatusHistory.objects.filter(complaint_id=complaint_id)
            self.assertEqual(history.count(), 1)
            self.assertEqual(history.first().status, 'PENDING')


class UserComplaintListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='cu2@test.com')
        self.other_user = _create_user(email='cu3@test.com')

    def test_list_own_complaints(self):
        _create_complaint(self.user)
        _create_complaint(self.user)
        _create_complaint(self.other_user)
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/complaints/list/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)

    def test_list_filter_by_status(self):
        _create_complaint(self.user, status='PENDING')
        _create_complaint(self.user, status='RESOLVED')
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/complaints/list/?status=RESOLVED')
        self.assertEqual(resp.data['count'], 1)

    def test_list_excludes_other_users(self):
        _create_complaint(self.other_user)
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/complaints/list/')
        self.assertEqual(resp.data['count'], 0)


class UserComplaintDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _create_user(email='cu4@test.com')
        self.other_user = _create_user(email='cu5@test.com')
        self.complaint = _create_complaint(self.user)

    def test_get_own_complaint(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/complaints/{self.complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['id'], self.complaint.id)

    def test_cannot_access_other_users_complaint(self):
        _auth(self.client, self.other_user)
        resp = self.client.get(f'{API}user/complaints/{self.complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_complaint_not_found(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}user/complaints/99999/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# OPERATOR ADMIN COMPLAINT TESTS
# ===========================================================================

class OperatorAdminComplaintTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_cmp@test.com')
        self.operator = _create_operator(email='op_cmp@test.com')
        self.operator.operator_profile.assigned_admin = self.admin.operatoradmin_profile
        self.operator.operator_profile.save()
        self.user = _create_user(email='u_cmp@test.com')

    def test_admin_list_complaints(self):
        _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}operator-admin/complaints/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_admin_list_filter_status(self):
        _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _create_complaint(self.user, status='RESOLVED', assigned_operator=self.operator)
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}operator-admin/complaints/?status=RESOLVED')
        self.assertEqual(resp.data['count'], 1)

    def test_admin_detail_complaint(self):
        complaint = _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.operator)
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}operator-admin/complaints/{complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('history', resp.data['data'])

    def test_admin_cannot_access_unrelated_complaint(self):
        other_op = _create_operator(email='op_other@test.com')
        complaint = _create_complaint(self.user, status='ASSIGNED', assigned_operator=other_op)
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}operator-admin/complaints/{complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class OperatorAdminAssignComplaintTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_asg@test.com')
        self.operator = _create_operator(email='op_asg@test.com')
        self.operator.operator_profile.assigned_admin = self.admin.operatoradmin_profile
        self.operator.operator_profile.save()
        self.user = _create_user(email='u_asg@test.com')
        self.complaint = _create_complaint(self.user, status='PENDING')

    def test_assign_operator_success(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(self.operator.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, 'ASSIGNED')
        self.assertEqual(self.complaint.assigned_operator, self.operator)
        self.assertIsNotNone(self.complaint.assigned_at)

    def test_assign_operator_wrong_status(self):
        self.complaint.status = 'ASSIGNED'
        self.complaint.save()
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(self.operator.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_assign_inactive_operator(self):
        inactive_op = _create_operator(email='op_inactive@test.com', is_verified=True)
        inactive_op.is_active = False
        inactive_op.save()
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(inactive_op.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_out_of_scope_operator(self):
        out_op = _create_operator(email='op_out@test.com')
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(out_op.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_nonexistent_operator(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(uuid.uuid4())},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_history_recorded(self):
        _auth(self.client, self.admin)
        self.client.post(
            f'{API}operator-admin/complaints/{self.complaint.id}/assign/',
            {'operator_id': str(self.operator.id)},
            format='json',
        )
        history = ComplaintStatusHistory.objects.filter(complaint=self.complaint)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().status, 'ASSIGNED')


# ===========================================================================
# OPERATOR COMPLAINT TESTS
# ===========================================================================

class OperatorComplaintTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op_lst@test.com')
        self.other_op = _create_operator(email='op_other2@test.com')
        self.user = _create_user(email='u_lst@test.com')
        self.complaint = _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.operator)

    def test_operator_list_assigned(self):
        _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.other_op)
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/complaints/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_operator_list_filter_status(self):
        _create_complaint(self.user, status='IN_PROGRESS', assigned_operator=self.operator)
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/complaints/?status=IN_PROGRESS')
        self.assertEqual(resp.data['count'], 1)

    def test_operator_detail(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/complaints/{self.complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_operator_cannot_access_other_complaint(self):
        _auth(self.client, self.other_op)
        resp = self.client.get(f'{API}operator/complaints/{self.complaint.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_operator_not_found(self):
        _auth(self.client, self.operator)
        resp = self.client.get(f'{API}operator/complaints/99999/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class OperatorComplaintStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = _create_operator(email='op_sts@test.com')
        self.user = _create_user(email='u_sts@test.com')
        self.complaint = _create_complaint(self.user, status='ASSIGNED', assigned_operator=self.operator)

    def test_transition_to_in_progress(self):
        _auth(self.client, self.operator)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, 'IN_PROGRESS')

    def test_transition_to_resolved(self):
        self.complaint.status = 'IN_PROGRESS'
        self.complaint.save()
        _auth(self.client, self.operator)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'RESOLVED'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, 'RESOLVED')
        self.assertIsNotNone(self.complaint.resolved_at)

    def test_invalid_transition_rejected(self):
        _auth(self.client, self.operator)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'RESOLVED'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_transition_from_resolved(self):
        self.complaint.status = 'RESOLVED'
        self.complaint.save()
        _auth(self.client, self.operator)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_status_history_recorded(self):
        _auth(self.client, self.operator)
        self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        history = ComplaintStatusHistory.objects.filter(complaint=self.complaint)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.first().status, 'IN_PROGRESS')

    def test_operator_cannot_update_other_complaint(self):
        other_op = _create_operator(email='op_sts2@test.com')
        _auth(self.client, other_op)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'IN_PROGRESS'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_status_choice(self):
        _auth(self.client, self.operator)
        resp = self.client.patch(
            f'{API}operator/complaints/{self.complaint.id}/status/',
            {'status': 'PENDING'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
