from rest_framework import permissions
from .models import CommunityMember


class IsOperatorOrAdmin(permissions.BasePermission):
    """Allow users whose group holds `chat.can_view_communities`."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.has_perm('chat.can_view_communities')
        )


class IsOperatorAdminRole(permissions.BasePermission):
    """Allow users whose group holds `chat.can_manage_community`."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.has_perm('chat.can_manage_community')
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
