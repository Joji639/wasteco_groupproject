from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Avg, Count

from accounts.models import CustomUser, OperatorOnboarding, OperatorProfile, OperatorAdminOnboarding
from accounts.serializers import (
    AdminLoginSerializer, get_tokens_for_user,
    AdminUserListSerializer, AdminStaffListSerializer,
    OperatorOnboardingAdminSerializer, OperatorAdminOnboardingAdminSerializer,
    RejectOnboardingSerializer, set_staff_verified,
)
from accounts.permissions import IsSuperAdminRole


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
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
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
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "identifier": email}
                },
                status=status.HTTP_200_OK
            )

        try:
            tokens = get_tokens_for_user(user)
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
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
            queryset = CustomUser.objects.filter(base_role='operator').select_related('operator_profile')
            serializer = AdminStaffListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load operators", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOperatorAdminListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admins'], responses={200: AdminStaffListSerializer(many=True)})
    def get(self, request):
        try:
            queryset = CustomUser.objects.filter(base_role='operatoradmin').select_related('operatoradmin_profile')
            serializer = AdminStaffListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load operator admins", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(
        tags=['Super Admins'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved"], description="Filter by status"),
            OpenApiParameter("role", str, description="Filter by role"),
        ],
        responses={200: OperatorOnboardingAdminSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = OperatorOnboarding.objects.select_related('user', 'approved_by').all()

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(approved=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(approved=True)

            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(user__base_role=role_filter)

            serializer = OperatorOnboardingAdminSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load onboarding requests", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ---------------------------------------------------------------------------
# Super Admin Rating Views
# ---------------------------------------------------------------------------

from pickups.models import OperatorReview
from pickups.serializers import OperatorAdminRatingSerializer


class SuperAdminOperatorRatingsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(
        tags=['Super Admins'],
        responses={200: OperatorAdminRatingSerializer(many=True)}
    )
    def get(self, request):
        operators = OperatorProfile.objects.select_related('user').all()

        results = []
        for op in operators:
            reviews = OperatorReview.objects.filter(operator=op.user)
            total = reviews.count()
            if total > 0:
                avg = reviews.aggregate(avg=Avg('rating'))['avg']
                avg_rating = round(float(avg), 1)
            else:
                avg_rating = None

            results.append({
                'operator_id': op.user.id,
                'operator_name': op.user.username or op.user.email,
                'average_rating': avg_rating,
                'total_reviews': total,
            })

        return Response(
            {"success": True, "count": len(results), "data": results},
            status=status.HTTP_200_OK,
        )


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
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load onboarding requests", "errors": str(e)},
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
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to approve onboarding", "errors": str(e)},
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
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to reject onboarding", "errors": str(e)},
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
