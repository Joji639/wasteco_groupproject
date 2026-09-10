import logging
from django.db import transaction
from django.db.models import Q
from rest_framework import status, permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from accounts.permissions import _in_group
from accounts.models import CustomUser, OperatorProfile
from .models import Community, CommunityMember, Message
from .serializers import (
    CommunityCreateSerializer, CommunityDetailSerializer,
    CommunityListSerializer, MemberDetailSerializer,
    MemberAddSerializer, PermissionUpdateSerializer,
    MessageSerializer,
)
from .permissions import (
    IsOperatorOrAdmin, IsOperatorAdminRole,
    is_community_member, get_community_membership, is_community_admin,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class MessagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


# ---------------------------------------------------------------------------
# Community CRUD — OperatorAdmin creates, both can view
# ---------------------------------------------------------------------------

class CommunityCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminRole]

    @extend_schema(
        tags=['Chat - Communities'],
        request=CommunityCreateSerializer,
        responses={201: CommunityDetailSerializer},
    )
    def post(self, request):
        serializer = CommunityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            community = Community.objects.create(
                name=serializer.validated_data['name'],
                description=serializer.validated_data.get('description', ''),
                created_by=request.user,
            )
            CommunityMember.objects.create(
                community=community,
                user=request.user,
                added_by=None,
                is_group_admin=True,
                can_add_members=True,
            )

        return Response(
            {
                'success': True,
                'message': 'Community created successfully.',
                'data': CommunityDetailSerializer(community).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CommunityListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrAdmin]

    @extend_schema(tags=['Chat - Communities'], responses={200: CommunityListSerializer(many=True)})
    def get(self, request):
        memberships = CommunityMember.objects.filter(
            user=request.user,
            is_active=True,
        ).select_related('community', 'community__created_by')

        communities = [m.community for m in memberships]

        serializer = CommunityListSerializer(communities, many=True)
        return Response(
            {
                'success': True,
                'count': len(serializer.data),
                'data': serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class CommunityDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrAdmin]

    @extend_schema(tags=['Chat - Communities'], responses={200: CommunityDetailSerializer})
    def get(self, request, community_id):
        try:
            community = Community.objects.get(id=community_id, is_active=True)
        except Community.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Community not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not is_community_member(request.user, community_id):
            return Response(
                {'success': False, 'message': 'You are not a member of this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {'success': True, 'data': CommunityDetailSerializer(community).data},
            status=status.HTTP_200_OK,
        )


class CommunityUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminRole]

    @extend_schema(tags=['Chat - Communities'], request=CommunityCreateSerializer)
    def patch(self, request, community_id):
        try:
            community = Community.objects.get(id=community_id, is_active=True)
        except Community.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Community not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not is_community_admin(request.user, community_id):
            return Response(
                {'success': False, 'message': 'Only the group admin can modify this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CommunityCreateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        if 'name' in serializer.validated_data:
            community.name = serializer.validated_data['name']
        if 'description' in serializer.validated_data:
            community.description = serializer.validated_data['description']
        community.save()

        return Response(
            {
                'success': True,
                'message': 'Community updated successfully.',
                'data': CommunityDetailSerializer(community).data,
            },
            status=status.HTTP_200_OK,
        )


class CommunityDeactivateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminRole]

    @extend_schema(tags=['Chat - Communities'])
    def post(self, request, community_id):
        try:
            community = Community.objects.get(id=community_id, is_active=True)
        except Community.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Community not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not is_community_admin(request.user, community_id):
            return Response(
                {'success': False, 'message': 'Only the group admin can deactivate this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        community.is_active = False
        community.save(update_fields=['is_active', 'updated_at'])

        CommunityMember.objects.filter(community=community, is_active=True).update(is_active=False)

        return Response(
            {'success': True, 'message': 'Community deactivated successfully.'},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------

class MemberAddView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrAdmin]

    @extend_schema(tags=['Chat - Members'], request=MemberAddSerializer)
    def post(self, request, community_id):
        membership = get_community_membership(request.user, community_id)
        if membership is None:
            return Response(
                {'success': False, 'message': 'You are not a member of this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not membership.is_group_admin and not membership.can_add_members:
            return Response(
                {'success': False, 'message': 'You do not have permission to add members.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = MemberAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        operator_id = serializer.validated_data['operator_id']

        try:
            operator_user = CustomUser.objects.get(id=operator_id, base_role='operator')
        except CustomUser.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Operator not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        existing = CommunityMember.objects.filter(
            community_id=community_id,
            user=operator_user,
            is_active=True,
        ).exists()
        if existing:
            return Response(
                {'success': False, 'message': 'User is already an active member of this community.'},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            member = CommunityMember.objects.create(
                community_id=community_id,
                user=operator_user,
                added_by=request.user,
                is_group_admin=False,
                can_add_members=False,
                is_active=True,
            )

        return Response(
            {
                'success': True,
                'message': 'Member added successfully.',
                'data': MemberDetailSerializer(member).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MemberRemoveView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminRole]

    @extend_schema(tags=['Chat - Members'])
    def delete(self, request, community_id, member_id):
        if not is_community_admin(request.user, community_id):
            return Response(
                {'success': False, 'message': 'Only the group admin can remove members.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            membership = CommunityMember.objects.get(
                id=member_id,
                community_id=community_id,
                is_active=True,
            )
        except CommunityMember.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.user_id == request.user.id:
            return Response(
                {'success': False, 'message': 'The group admin cannot remove themselves.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.is_active = False
        membership.can_add_members = False
        membership.save(update_fields=['is_active', 'can_add_members', 'updated_at'])

        return Response(
            {'success': True, 'message': 'Member removed successfully.'},
            status=status.HTTP_200_OK,
        )


class MemberListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrAdmin]

    @extend_schema(tags=['Chat - Members'], responses={200: MemberDetailSerializer(many=True)})
    def get(self, request, community_id):
        if not is_community_member(request.user, community_id):
            return Response(
                {'success': False, 'message': 'You are not a member of this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        members = CommunityMember.objects.filter(
            community_id=community_id,
            is_active=True,
        ).select_related('user', 'added_by')

        serializer = MemberDetailSerializer(members, many=True)
        return Response(
            {
                'success': True,
                'count': len(serializer.data),
                'data': serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class MemberPermissionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminRole]

    @extend_schema(tags=['Chat - Members'], request=PermissionUpdateSerializer)
    def patch(self, request, community_id, member_id):
        if not is_community_admin(request.user, community_id):
            return Response(
                {'success': False, 'message': 'Only the group admin can modify permissions.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            membership = CommunityMember.objects.get(
                id=member_id,
                community_id=community_id,
                is_active=True,
            )
        except CommunityMember.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Member not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.user.base_role != 'operator':
            return Response(
                {'success': False, 'message': 'Permission can only be granted to operators.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PermissionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        membership.can_add_members = serializer.validated_data['can_add_members']
        membership.save(update_fields=['can_add_members', 'updated_at'])

        action = 'granted' if membership.can_add_members else 'revoked'
        return Response(
            {
                'success': True,
                'message': f'Add-member permission {action} successfully.',
                'data': MemberDetailSerializer(membership).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Message history (REST)
# ---------------------------------------------------------------------------

class MessageHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorOrAdmin]
    pagination_class = MessagePagination

    @extend_schema(tags=['Chat - Messages'], responses={200: MessageSerializer(many=True)})
    def get(self, request, community_id):
        if not is_community_member(request.user, community_id):
            return Response(
                {'success': False, 'message': 'You are not a member of this community.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        messages = Message.objects.filter(
            community_id=community_id,
        ).select_related('sender', 'community').order_by('-created_at')

        paginator = MessagePagination()
        page = paginator.paginate_queryset(messages, request)
        serializer = MessageSerializer(page, many=True)

        return paginator.get_paginated_response(serializer.data)
