from rest_framework.permissions import BasePermission, SAFE_METHODS


def _in_group(user, *group_names):
    return user.groups.filter(name__in=group_names).exists()


class IsVerifiedForActions(BasePermission):
    """
    Allows any authenticated user to VIEW data (GET, HEAD, OPTIONS)
    regardless of verification status.

    Blocks WRITE actions (POST, PUT, PATCH, DELETE) until the user's
    profile is verified by the operator admin.
    """
    message = "Your profile is under verification. This action will be available once approved."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        if _in_group(request.user, 'User'):
            try:
                return request.user.user_profile.is_verified
            except AttributeError:
                return False

        return True


class IsStaffRole(BasePermission):
    message = "Operator or operator admin privileges required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'Operator', 'OperatorAdmin')
        )


class IsApprovedStaff(BasePermission):
    message = "Your account is still pending approval. Wait for the admin to approve your onboarding."

    def has_permission(self, request, view):
        if not (
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'Operator', 'OperatorAdmin')
        ):
            return False
        profile = (
            request.user.operatoradmin_profile
            if _in_group(request.user, 'OperatorAdmin')
            else getattr(request.user, 'operator_profile', None)
        )
        return bool(profile and profile.is_verified)


class IsOperatorAdminOrSuperAdmin(BasePermission):
    message = "Operator admin or super admin privileges required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'OperatorAdmin', 'SuperAdmin')
        )


class IsSuperAdminRole(BasePermission):
    message = "Super admin privileges required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'SuperAdmin')
        )


class IsOperatorRole(BasePermission):
    message = "Operator privileges required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'Operator')
        )
