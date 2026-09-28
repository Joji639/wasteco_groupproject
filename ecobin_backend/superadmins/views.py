import logging

from django.db.models import Avg, Count, Q
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import (
    CustomUser, OperatorOnboarding, OperatorProfile,
    OperatorAdminOnboarding, UserProfile,
)
from accounts.serializers import (
    AdminLoginSerializer, get_tokens_for_user,
    AdminUserListSerializer, AdminStaffListSerializer,
    OperatorOnboardingAdminSerializer, OperatorAdminOnboardingAdminSerializer,
    RejectOnboardingSerializer, set_staff_verified,
    SuperAdminOnboardingSerializer, SuperAdminUserProfileOnboardingSerializer,
)
from accounts.permissions import IsSuperAdminRole
from pickups.models import OperatorReview

logger = logging.getLogger(__name__)


class AdminLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Super Admins'], request=AdminLoginSerializer, responses={200: None})
    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        try:
            user = CustomUser.objects.get(email=email, base_role='superadmin')
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Invalid admin credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception:
            return Response(
                {"success": False, "message": "Login failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not user.check_password(password):
            return Response(
                {"success": False, "message": "Invalid admin credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "Admin account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.is_2fa_enabled:
            from accounts.views.public_auth import _generate_partial_token
            partial_token = _generate_partial_token(user.id)
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "partial_token": partial_token}
                },
                status=status.HTTP_200_OK
            )

        try:
            tokens = get_tokens_for_user(user)
        except Exception:
            return Response(
                {"success": False, "message": "Login failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Admin login successful",
                "data": {"tokens": tokens, "role": user.base_role},
            },
            status=status.HTTP_200_OK
        )


class AdminUserListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], responses={200: AdminUserListSerializer(many=True)})
    def get(self, request):
        try:
            queryset = CustomUser.objects.filter(base_role='user').select_related('user_profile')
            serializer = AdminUserListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load users", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOperatorListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], responses={200: AdminStaffListSerializer(many=True)})
    def get(self, request):
        try:
            operators = CustomUser.objects.filter(
                base_role='operator'
            ).select_related('operator_profile').annotate(
                avg_rating=Avg('operator_reviews_received__rating'),
                total_reviews=Count('operator_reviews_received'),
            )
            serializer = AdminStaffListSerializer(operators, many=True)
            data = []
            for i, op in enumerate(operators):
                item = serializer.data[i]
                item['average_rating'] = round(float(op.avg_rating), 1) if op.avg_rating else None
                item['total_reviews'] = op.total_reviews
                data.append(item)
            return Response(
                {"success": True, "count": len(data), "data": data},
                status=status.HTTP_200_OK
            )
        except Exception:
            return Response(
                {"success": False, "message": "Failed to load operators"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOperatorAdminListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], responses={200: AdminStaffListSerializer(many=True)})
    def get(self, request):
        try:
            admins = CustomUser.objects.filter(
                base_role='operatoradmin'
            ).select_related('operatoradmin_profile').annotate(
                avg_rating=Avg('operator_reviews_received__rating'),
                total_reviews=Count('operator_reviews_received'),
            )
            serializer = AdminStaffListSerializer(admins, many=True)
            data = []
            for i, admin in enumerate(admins):
                item = serializer.data[i]
                item['average_rating'] = round(float(admin.avg_rating), 1) if admin.avg_rating else None
                item['total_reviews'] = admin.total_reviews
                data.append(item)
            return Response(
                {"success": True, "count": len(data), "data": data},
                status=status.HTTP_200_OK
            )
        except Exception:
            return Response(
                {"success": False, "message": "Failed to load operator admins"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(
        tags=['Super Admins'],
        parameters=[
            OpenApiParameter("role", str, enum=["user", "operator", "operatoradmin"],
                             description="Filter by role (required)"),
            OpenApiParameter("status", str, enum=["pending", "approved", "rejected", "not_submitted"],
                             description="Filter by status"),
        ],
        responses={200: None}
    )
    def get(self, request):
        role = request.query_params.get('role')
        if not role:
            return Response(
                {"success": False, "message": "Query parameter 'role' is required (user, operator, operatoradmin)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        status_filter = request.query_params.get('status')

        try:
            if role == 'user':
                results = self._get_user_onboardings(status_filter)
            elif role == 'operator':
                results = self._get_operator_onboardings(status_filter)
            elif role == 'operatoradmin':
                results = self._get_operatoradmin_onboardings(status_filter)
            else:
                return Response(
                    {"success": False, "message": "Invalid role. Must be: user, operator, operatoradmin"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {"success": True, "role": role, "count": len(results), "data": results},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error("Failed to load onboardings: %s", e)
            return Response(
                {"success": False, "message": "Failed to load onboarding requests"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_user_onboardings(self, status_filter):
        qs = UserProfile.objects.select_related('user', 'verified_by').filter(
            user__base_role='user'
        )
        if status_filter == 'approved':
            qs = qs.filter(is_verified=True)
        elif status_filter == 'pending':
            qs = qs.filter(is_verified=False).exclude(address__isnull=True, current_location__isnull=True)
        elif status_filter == 'not_submitted':
            qs = qs.filter(address__isnull=True, current_location__isnull=True)
        elif status_filter == 'rejected':
            qs = qs.filter(is_verified=False).exclude(rejection_reason='')

        return SuperAdminUserProfileOnboardingSerializer(qs, many=True).data

    def _get_operator_onboardings(self, status_filter):
        qs = OperatorOnboarding.objects.select_related('user', 'approved_by').filter(
            user__base_role='operator'
        )
        if status_filter == 'approved':
            qs = qs.filter(approved=True)
        elif status_filter == 'pending':
            qs = qs.filter(approved=False, rejection_reason='')
        elif status_filter == 'rejected':
            qs = qs.filter(approved=False).exclude(rejection_reason='')

        return SuperAdminOnboardingSerializer(qs, many=True).data

    def _get_operatoradmin_onboardings(self, status_filter):
        qs = OperatorAdminOnboarding.objects.select_related('user', 'approved_by').filter(
            user__base_role='operatoradmin'
        )
        if status_filter == 'approved':
            qs = qs.filter(approved=True)
        elif status_filter == 'pending':
            qs = qs.filter(approved=False, rejection_reason='')
        elif status_filter == 'rejected':
            qs = qs.filter(approved=False).exclude(rejection_reason='')

        return SuperAdminOnboardingSerializer(qs, many=True).data


# ---------------------------------------------------------------------------
# Super Admin: Operator Admin Onboarding Management
# ---------------------------------------------------------------------------

from django.utils import timezone
from django.db import transaction
from drf_spectacular.utils import OpenApiTypes
from accounts.serializers import RejectOnboardingSerializer


class AdminOAOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(
        tags=['Super Admins'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved"], description="Filter by status"),
        ],
        responses={200: OperatorAdminOnboardingAdminSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = OperatorAdminOnboarding.objects.select_related('user', 'approved_by').all()

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(approved=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(approved=True)

            serializer = OperatorAdminOnboardingAdminSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception:
            return Response(
                {"success": False, "message": "Failed to load onboarding requests"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOAOnboardingApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], request=OpenApiTypes.OBJECT, responses={200: OperatorAdminOnboardingAdminSerializer})
    def post(self, request):
        onboarding_id = request.data.get('id')
        if not onboarding_id:
            return Response(
                {"success": False, "message": "Onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            onboarding = OperatorAdminOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorAdminOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if onboarding.approved:
            return Response(
                {"success": False, "message": "Onboarding is already approved"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                onboarding.approved = True
                onboarding.approved_by = request.user
                onboarding.approved_at = timezone.now()
                onboarding.rejection_reason = ''
                onboarding.save()

                profile = onboarding.user.operatoradmin_profile
                profile.is_verified = True
                profile.verified_by = request.user
                profile.save(update_fields=['is_verified', 'verified_by'])

                onboarding.user.is_active = True
                onboarding.user.save(update_fields=['is_active'])
        except Exception:
            return Response(
                {"success": False, "message": "Failed to approve onboarding"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Operator admin onboarding approved. Account is now active.",
                "data": OperatorAdminOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class AdminOAOnboardingRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], request=RejectOnboardingSerializer, responses={200: OperatorAdminOnboardingAdminSerializer})
    def post(self, request):
        serializer = RejectOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        onboarding_id = request.data.get('id')
        if not onboarding_id:
            return Response(
                {"success": False, "message": "Onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            onboarding = OperatorAdminOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorAdminOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if onboarding.approved:
            return Response(
                {"success": False, "message": "Approved onboarding cannot be rejected"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                onboarding.rejection_reason = serializer.validated_data['reason']
                onboarding.save(update_fields=['rejection_reason', 'updated_at'])

                profile = onboarding.user.operatoradmin_profile
                profile.is_verified = False
                profile.save(update_fields=['is_verified'])
        except Exception:
            return Response(
                {"success": False, "message": "Failed to reject onboarding"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding rejected. The operator admin can resubmit via PATCH.",
                "data": OperatorAdminOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )
