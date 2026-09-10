"""Tests for Group Chat API."""

from django.test import TestCase, TransactionTestCase
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import CustomUser, OperatorProfile, OperatorAdminProfile
from accounts.serializers import get_tokens_for_user
from .models import Community, CommunityMember, Message
from .consumers import CommunityChatConsumer

API = '/'


def _create_operator_admin(email='oa@test.com', password='Test1234!', panchayath='TVM', **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role='operatoradmin', **kw,
    )
    OperatorAdminProfile.objects.create(user=user, panchayath=panchayath)
    return user


def _create_operator(email='op@test.com', password='Test1234!', ward_no='5', is_verified=True, **kw):
    user = CustomUser.objects.create_user(
        email=email, password=password, base_role='operator', **kw,
    )
    OperatorProfile.objects.create(user=user, ward_no=ward_no, is_verified=is_verified)
    return user


def _create_user(email='u@test.com', password='Test1234!', **kw):
    return CustomUser.objects.create_user(
        email=email, password=password, base_role='user', **kw,
    )


def _create_superadmin(email='sa@test.com', password='Test1234!', **kw):
    return CustomUser.objects.create_superuser(
        email=email, password=password, base_role='superadmin', **kw,
    )


def _tokens(user):
    return get_tokens_for_user(user)


def _auth(client, user):
    tokens = _tokens(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}')
    return tokens


def _make_community(admin, name='Test Community', desc='A test community'):
    community = Community.objects.create(
        name=name, description=desc, created_by=admin,
    )
    CommunityMember.objects.create(
        community=community, user=admin, added_by=None,
        is_group_admin=True, can_add_members=True,
    )
    return community


def _add_member(community, operator, added_by=None, can_add=False):
    return CommunityMember.objects.create(
        community=community, user=operator, added_by=added_by,
        can_add_members=can_add,
    )


# ===========================================================================
# COMMUNITY CREATION TESTS
# ===========================================================================

class CommunityCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_create@test.com')
        self.operator = _create_operator(email='op_create@test.com')
        self.user = _create_user(email='u_create@test.com')

    def test_admin_create_community(self):
        _auth(self.client, self.admin)
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'name': 'Kochi Zone 1',
            'description': 'Operations chat',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['name'], 'Kochi Zone 1')
        self.assertEqual(resp.data['data']['member_count'], 1)
        self.assertTrue(
            CommunityMember.objects.filter(
                community_id=resp.data['data']['id'],
                user=self.admin,
                is_group_admin=True,
            ).exists()
        )

    def test_operator_cannot_create_community(self):
        _auth(self.client, self.operator)
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'name': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_cannot_create_community(self):
        _auth(self.client, self.user)
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'name': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_community_empty_name(self):
        _auth(self.client, self.admin)
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'name': '   ',
            'description': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_community_missing_name(self):
        _auth(self.client, self.admin)
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'description': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_community_unauthenticated(self):
        resp = self.client.post(f'{API}operator-admin/communities/', {
            'name': 'Test',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ===========================================================================
# COMMUNITY LISTING & DETAIL TESTS
# ===========================================================================

class CommunityListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_list@test.com')
        self.op1 = _create_operator(email='op_list1@test.com')
        self.op2 = _create_operator(email='op_list2@test.com')
        self.user = _create_user(email='u_list@test.com')
        self.community = _make_community(self.admin, name='List Community')
        _add_member(self.community, self.op1, added_by=self.admin)

    def test_admin_sees_own_communities(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}communities/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_member_sees_joined_communities(self):
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_non_member_sees_nothing(self):
        _auth(self.client, self.op2)
        resp = self.client.get(f'{API}communities/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)

    def test_user_cannot_list_communities(self):
        _auth(self.client, self.user)
        resp = self.client.get(f'{API}communities/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class CommunityDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_detail@test.com')
        self.op1 = _create_operator(email='op_detail1@test.com')
        self.op2 = _create_operator(email='op_detail2@test.com')
        self.community = _make_community(self.admin, name='Detail Community')
        _add_member(self.community, self.op1, added_by=self.admin)

    def test_member_can_view_detail(self):
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/{self.community.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['data']['name'], 'Detail Community')

    def test_non_member_cannot_view_detail(self):
        _auth(self.client, self.op2)
        resp = self.client.get(f'{API}communities/{self.community.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_community_not_found(self):
        _auth(self.client, self.admin)
        resp = self.client.get(f'{API}communities/99999/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# COMMUNITY UPDATE TESTS
# ===========================================================================

class CommunityUpdateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_update@test.com')
        self.op1 = _create_operator(email='op_update@test.com')
        self.community = _make_community(self.admin)
        _add_member(self.community, self.op1, added_by=self.admin)

    def test_admin_can_rename(self):
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/',
            {'name': 'Renamed Community'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.community.refresh_from_db()
        self.assertEqual(self.community.name, 'Renamed Community')

    def test_operator_cannot_rename(self):
        _auth(self.client, self.op1)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/',
            {'name': 'Hacked'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_community_not_found_update(self):
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/99999/',
            {'name': 'X'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# COMMUNITY DEACTIVATION TESTS
# ===========================================================================

class CommunityDeactivateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_deact@test.com')
        self.op1 = _create_operator(email='op_deact@test.com')
        self.community = _make_community(self.admin)
        _add_member(self.community, self.op1, added_by=self.admin)

    def test_admin_can_deactivate(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}operator-admin/communities/{self.community.id}/deactivate/',
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.community.refresh_from_db()
        self.assertFalse(self.community.is_active)
        self.assertFalse(
            CommunityMember.objects.filter(
                community=self.community, is_active=True,
            ).exists()
        )

    def test_operator_cannot_deactivate(self):
        _auth(self.client, self.op1)
        resp = self.client.post(
            f'{API}operator-admin/communities/{self.community.id}/deactivate/',
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# MEMBER ADDITION TESTS
# ===========================================================================

class MemberAddTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_add@test.com')
        self.op1 = _create_operator(email='op_add1@test.com')
        self.op2 = _create_operator(email='op_add2@test.com')
        self.op3 = _create_operator(email='op_add3@test.com')
        self.user = _create_user(email='u_add@test.com')
        self.superadmin = _create_superadmin(email='sa_add@test.com')
        self.community = _make_community(self.admin)
        _add_member(self.community, self.op1, added_by=self.admin)

    def test_admin_can_add_operator(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.op2.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            CommunityMember.objects.filter(
                community=self.community, user=self.op2, is_active=True,
            ).exists()
        )

    def test_operator_with_permission_can_add(self):
        _add_member(self.community, self.op3, added_by=self.admin, can_add=True)
        _auth(self.client, self.op3)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.op2.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_operator_without_permission_cannot_add(self):
        _auth(self.client, self.op1)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.op2.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_add_user_role(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.user.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_superadmin(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.superadmin.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_add_operatoradmin(self):
        other_admin = _create_operator_admin(email='oa_other@test.com')
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(other_admin.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_membership_rejected(self):
        _auth(self.client, self.admin)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.op1.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_non_member_cannot_add(self):
        _auth(self.client, self.op2)
        resp = self.client.post(
            f'{API}communities/{self.community.id}/members/add/',
            {'operator_id': str(self.op3.id)},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# MEMBER REMOVAL TESTS
# ===========================================================================

class MemberRemoveTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_rm@test.com')
        self.op1 = _create_operator(email='op_rm1@test.com')
        self.op2 = _create_operator(email='op_rm2@test.com')
        self.community = _make_community(self.admin)
        self.member1 = _add_member(self.community, self.op1, added_by=self.admin)
        self.member2 = _add_member(self.community, self.op2, added_by=self.admin)

    def test_admin_can_remove(self):
        _auth(self.client, self.admin)
        resp = self.client.delete(
            f'{API}operator-admin/communities/{self.community.id}/members/{self.member2.id}/',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.member2.refresh_from_db()
        self.assertFalse(self.member2.is_active)

    def test_operator_cannot_remove(self):
        _auth(self.client, self.op1)
        resp = self.client.delete(
            f'{API}operator-admin/communities/{self.community.id}/members/{self.member2.id}/',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_remove_self(self):
        admin_member = CommunityMember.objects.get(
            community=self.community, user=self.admin,
        )
        _auth(self.client, self.admin)
        resp = self.client.delete(
            f'{API}operator-admin/communities/{self.community.id}/members/{admin_member.id}/',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_nonexistent_member(self):
        _auth(self.client, self.admin)
        resp = self.client.delete(
            f'{API}operator-admin/communities/{self.community.id}/members/99999/',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# MEMBER LISTING TESTS
# ===========================================================================

class MemberListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_mlist@test.com')
        self.op1 = _create_operator(email='op_mlist1@test.com')
        self.op2 = _create_operator(email='op_mlist2@test.com')
        self.community = _make_community(self.admin)
        _add_member(self.community, self.op1, added_by=self.admin)
        _add_member(self.community, self.op2, added_by=self.admin)

    def test_member_can_list(self):
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/{self.community.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 3)

    def test_non_member_cannot_list(self):
        outsider = _create_operator(email='op_out@test.com')
        _auth(self.client, outsider)
        resp = self.client.get(f'{API}communities/{self.community.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# PERMISSION GRANT/REVOKE TESTS
# ===========================================================================

class PermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_perm@test.com')
        self.op1 = _create_operator(email='op_perm1@test.com')
        self.op2 = _create_operator(email='op_perm2@test.com')
        self.community = _make_community(self.admin)
        self.member1 = _add_member(self.community, self.op1, added_by=self.admin)
        self.member2 = _add_member(self.community, self.op2, added_by=self.admin)

    def test_admin_can_grant(self):
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/members/{self.member1.id}/permissions/',
            {'can_add_members': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.member1.refresh_from_db()
        self.assertTrue(self.member1.can_add_members)

    def test_admin_can_revoke(self):
        self.member1.can_add_members = True
        self.member1.save()
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/members/{self.member1.id}/permissions/',
            {'can_add_members': False},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.member1.refresh_from_db()
        self.assertFalse(self.member1.can_add_members)

    def test_operator_cannot_grant(self):
        _auth(self.client, self.op1)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/members/{self.member2.id}/permissions/',
            {'can_add_members': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_grant_to_non_operator(self):
        admin_member = CommunityMember.objects.get(
            community=self.community, user=self.admin,
        )
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/members/{admin_member.id}/permissions/',
            {'can_add_members': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permission_nonexistent_member(self):
        _auth(self.client, self.admin)
        resp = self.client.patch(
            f'{API}operator-admin/communities/{self.community.id}/members/99999/permissions/',
            {'can_add_members': True},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# MESSAGE HISTORY TESTS
# ===========================================================================

class MessageHistoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = _create_operator_admin(email='oa_msg@test.com')
        self.op1 = _create_operator(email='op_msg1@test.com')
        self.op2 = _create_operator(email='op_msg2@test.com')
        self.community = _make_community(self.admin)
        _add_member(self.community, self.op1, added_by=self.admin)
        for i in range(5):
            Message.objects.create(
                community=self.community,
                sender=self.op1,
                content=f'Message {i}',
            )

    def test_member_can_get_history(self):
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/{self.community.id}/messages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 5)

    def test_non_member_cannot_get_history(self):
        _auth(self.client, self.op2)
        resp = self.client.get(f'{API}communities/{self.community.id}/messages/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_pagination_works(self):
        for i in range(60):
            Message.objects.create(
                community=self.community,
                sender=self.admin,
                content=f'Admin message {i}',
            )
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/{self.community.id}/messages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 65)
        self.assertEqual(len(resp.data['results']), 50)

    def test_empty_history(self):
        new_community = Community.objects.create(
            name='Empty', created_by=self.admin,
        )
        _add_member(new_community, self.op1, added_by=self.admin)
        _auth(self.client, self.op1)
        resp = self.client.get(f'{API}communities/{new_community.id}/messages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)


# ===========================================================================
# WEBSOCKET TESTS
# ===========================================================================

class WebSocketTests(TransactionTestCase):
    @database_sync_to_async
    def _setup_admin_op_community(self, email_admin, email_op, community_name):
        admin = _create_operator_admin(email=email_admin)
        op = _create_operator(email=email_op)
        community = _make_community(admin, name=community_name)
        _add_member(community, op, added_by=admin)
        return admin, op, community

    @database_sync_to_async
    def _create_community_only(self, email_admin, community_name):
        admin = _create_operator_admin(email=email_admin)
        community = _make_community(admin, name=community_name)
        return admin, community

    def _make_communicator(self, community_id):
        communicator = WebsocketCommunicator(
            CommunityChatConsumer.as_asgi(),
            f'/ws/communities/{community_id}/',
        )
        communicator.scope['url_route'] = {'kwargs': {'community_id': community_id}}
        return communicator

    async def test_authenticated_member_connects(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws@test.com', 'op_ws@test.com', 'WS Community',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_unauthenticated_user_rejected(self):
        admin, community = await self._create_community_only(
            'oa_ws2@test.com', 'WS Community 2',
        )
        from django.contrib.auth.models import AnonymousUser
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = AnonymousUser()
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_non_member_rejected(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws3@test.com', 'op_ws3@test.com', 'WS Community 3',
        )
        outsider = await self._create_operator_async('op_ws3_out@test.com')
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = outsider
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    async def test_send_message_persists_and_broadcasts(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws4@test.com', 'op_ws4@test.com', 'WS Community 4',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.send_json_to({
            'type': 'message',
            'content': 'Vehicle 12 has arrived.',
        })

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'new_message')
        self.assertEqual(response['message']['content'], 'Vehicle 12 has arrived.')
        self.assertEqual(response['message']['sender']['id'], str(op.id))
        self.assertEqual(response['message']['community_id'], community.id)

        msg_exists = await self._message_exists(community.id, op.id, 'Vehicle 12 has arrived.')
        self.assertTrue(msg_exists)

        await communicator.disconnect()

    async def test_empty_message_rejected(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws5@test.com', 'op_ws5@test.com', 'WS Community 5',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        await communicator.connect()

        await communicator.send_json_to({
            'type': 'message',
            'content': '   ',
        })

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'error')
        self.assertIn('empty', response['message'].lower())

        await communicator.disconnect()

    async def test_invalid_json_rejected(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws6@test.com', 'op_ws6@test.com', 'WS Community 6',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        await communicator.connect()

        await communicator.send_to(text_data='not json')

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'error')
        self.assertIn('Invalid JSON', response['message'])

        await communicator.disconnect()

    async def test_non_message_type_rejected(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws7@test.com', 'op_ws7@test.com', 'WS Community 7',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        await communicator.connect()

        await communicator.send_json_to({
            'type': 'typing',
            'content': 'hello',
        })

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'error')

        await communicator.disconnect()

    async def test_oversized_message_rejected(self):
        admin, op, community = await self._setup_admin_op_community(
            'oa_ws8@test.com', 'op_ws8@test.com', 'WS Community 8',
        )
        communicator = self._make_communicator(community.id)
        communicator.scope['user'] = op
        await communicator.connect()

        await communicator.send_json_to({
            'type': 'message',
            'content': 'x' * 5001,
        })

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'error')
        self.assertIn('maximum length', response['message'].lower())

        await communicator.disconnect()

    @database_sync_to_async
    def _create_operator_async(self, email):
        return _create_operator(email=email)

    @database_sync_to_async
    def _message_exists(self, community_id, sender_id, content):
        return Message.objects.filter(
            community_id=community_id,
            sender_id=sender_id,
            content=content,
        ).exists()
