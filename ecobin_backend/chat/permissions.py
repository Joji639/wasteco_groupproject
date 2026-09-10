from rest_framework import permissions
from accounts.permissions import _in_group
from .models import CommunityMember


class IsOperatorOrAdmin(permissions.BasePermission):
    """Allow only Operator or OperatorAdmin roles."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'Operator', 'OperatorAdmin')
        )


class IsOperatorAdminRole(permissions.BasePermission):
    """Allow only OperatorAdmin role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'OperatorAdmin')
        )


def is_community_member(user, community_id):
    """Check if user is an active member of the community."""
    return CommunityMember.objects.filter(
        community_id=community_id,
        user=user,
        is_active=True,
    ).exists()


def get_community_membership(user, community_id):
    """Return the CommunityMember record if user is an active member, else None."""
    try:
        return CommunityMember.objects.get(
            community_id=community_id,
            user=user,
            is_active=True,
        )
    except CommunityMember.DoesNotExist:
        return None


def is_community_admin(user, community_id):
    """Check if user is the group admin of the community."""
    membership = get_community_membership(user, community_id)
    return membership is not None and membership.is_group_admin
