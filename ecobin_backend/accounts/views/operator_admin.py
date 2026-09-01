from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import UserProfile, OperatorOnboarding
from ..serializers import (
    OperatorOnboardingAdminSerializer, OperatorPersonalInfoSerializer,
    RejectOnboardingSerializer, AdminUserOnboardingSerializer,
    set_staff_verified,
)
from ..permissions import IsOperatorAdminOrSuperAdmin
from .utils import can_approve


class OperatorOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved"], description="Filter by status"),
            OpenApiParameter("role", str, description="Filter by role"),
        ],
        responses={200: OperatorOnboardingAdminSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = OperatorOnboarding.objects.select_related(
                'user', 'approved_by'
            ).all()

            if request.user.base_role == 'operatoradmin':
                queryset = queryset.filter(user__base_role='operator')

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


class OperatorOnboardingApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        request=OpenApiTypes.OBJECT,
        responses={200: OperatorOnboardingAdminSerializer}
    )
    def post(self, request):
        onboarding_id = request.data.get('id')
        if not onboarding_id:
            return Response(
                {"success": False, "message": "Onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            onboarding = OperatorOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_approve(request, onboarding):
            return Response(
                {"success": False, "message": "You are not authorized to approve this request"},
                status=status.HTTP_403_FORBIDDEN
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

                user = onboarding.user
                user.is_active = True
                user.save(update_fields=['is_active'])
                set_staff_verified(user, True)
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to approve onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding approved. Account is now active.",
                "data": OperatorOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class OperatorOnboardingRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(tags=['Operator Admin'], request=RejectOnboardingSerializer, responses={200: OperatorOnboardingAdminSerializer})
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
            onboarding = OperatorOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not can_approve(request, onboarding):
            return Response(
                {"success": False, "message": "You are not authorized to reject this request"},
                status=status.HTTP_403_FORBIDDEN
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

                user = onboarding.user
                set_staff_verified(user, False)
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to reject onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding rejected. The staff member can resubmit via PATCH.",
                "data": OperatorOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class AdminUserOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved", "not_submitted"], description="Filter by status"),
        ],
        responses={200: AdminUserOnboardingSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = UserProfile.objects.select_related('user', 'verified_by').filter(
                user__base_role='user'
            )

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(is_verified=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(is_verified=True)
            elif filter_param == 'not_submitted':
                queryset = queryset.filter(address__isnull=True, current_location__isnull=True)

            serializer = AdminUserOnboardingSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load user onboarding requests", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminUserOnboardingApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        request=OpenApiTypes.OBJECT,
        responses={200: AdminUserOnboardingSerializer}
    )
    def post(self, request):
        profile_id = request.data.get('id')
        if not profile_id:
            return Response(
                {"success": False, "message": "User onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = UserProfile.objects.select_related('user').get(id=profile_id)
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User onboarding not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.is_verified:
            return Response(
                {"success": False, "message": "User onboarding is already approved"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                profile.is_verified = True
                profile.rejection_reason = ''
                if request.user.base_role == 'operatoradmin':
                    profile.verified_by = request.user.operatoradmin_profile
                profile.save()

                user = profile.user
                user.is_active = True
                user.save(update_fields=['is_active'])
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to approve user onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "User onboarding approved. Account is now active.",
                "data": AdminUserOnboardingSerializer(profile).data,
            },
            status=status.HTTP_200_OK
        )


class AdminUserOnboardingRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(tags=['Operator Admin'], request=RejectOnboardingSerializer, responses={200: AdminUserOnboardingSerializer})
    def post(self, request):
        serializer = RejectOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get('id')
        if not profile_id:
            return Response(
                {"success": False, "message": "User onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = UserProfile.objects.select_related('user').get(id=profile_id)
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User onboarding not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.is_verified:
            return Response(
                {"success": False, "message": "Approved user onboarding cannot be rejected"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                profile.rejection_reason = serializer.validated_data['reason']
                profile.is_verified = False
                profile.verified_by = None
                profile.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to reject user onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "User onboarding rejected. The user can resubmit via onboarding.",
                "data": AdminUserOnboardingSerializer(profile).data,
            },
            status=status.HTTP_200_OK
        )
