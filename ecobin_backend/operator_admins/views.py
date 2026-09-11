import logging

from django.db import transaction
from django.utils import timezone
from django.db.models import Avg, Count, Q
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserProfile, OperatorOnboarding, CustomUser, OperatorProfile, OperatorAdminOnboarding
from accounts.serializers import (
    OperatorOnboardingAdminSerializer, OperatorPersonalInfoSerializer,
    RejectOnboardingSerializer, AdminUserOnboardingSerializer,
    OperatorAdminOnboardingSerializer, OperatorAdminOnboardingAdminSerializer,
    set_staff_verified,
)
from accounts.permissions import IsOperatorAdminOrSuperAdmin, _in_group


def can_approve(request, onboarding):
    target_role = onboarding.user.base_role
    if target_role == 'operatoradmin':
        return request.user.base_role == 'superadmin'
    return request.user.base_role == 'operatoradmin'


class OperatorOnboardingListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admins'],
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
        tags=['Operator Admins'],
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

    @extend_schema(tags=['Operator Admins'], request=RejectOnboardingSerializer, responses={200: OperatorOnboardingAdminSerializer})
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
        tags=['Operator Admins'],
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
        tags=['Operator Admins'],
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

    @extend_schema(tags=['Operator Admins'], request=RejectOnboardingSerializer, responses={200: AdminUserOnboardingSerializer})
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


# ---------------------------------------------------------------------------
# Operator Admin Pickup Views (moved from pickups app)
# ---------------------------------------------------------------------------

from pickups.models import PickupRequest
from pickups.serializers import (
    OperatorAdminPickupListSerializer, OperatorAdminPickupDetailSerializer,
    RejectPickupSerializer, AssignOperatorSerializer,
)


class IsOperatorAdminOnly(permissions.BasePermission):
    message = "Operator admin privileges required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'OperatorAdmin')
        )


class OperatorAdminPickupListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: OperatorAdminPickupListSerializer(many=True)}
    )
    def get(self, request):
        pickups = PickupRequest.objects.filter(
            pickup_type='ON_DEMAND',
        ).select_related('user', 'assigned_operator').order_by('-created_at')

        serializer = OperatorAdminPickupListSerializer(pickups, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class OperatorAdminPickupDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: OperatorAdminPickupDetailSerializer}
    )
    def get(self, request, pickup_id):
        try:
            pickup = PickupRequest.objects.select_related(
                'user', 'accepted_by', 'rejected_by',
                'assigned_operator', 'assigned_by',
            ).get(id=pickup_id, pickup_type='ON_DEMAND')
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup request not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorAdminPickupDetailSerializer(pickup)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )


class OperatorAdminPickupAcceptView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(tags=['Operator Admins'], responses={200: None})
    def patch(self, request, pickup_id):
        with transaction.atomic():
            try:
                pickup = PickupRequest.objects.select_for_update().get(
                    id=pickup_id, pickup_type='ON_DEMAND'
                )
            except PickupRequest.DoesNotExist:
                return Response(
                    {"success": False, "message": "Pickup request not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if pickup.status != 'PENDING':
                return Response(
                    {
                        "success": False,
                        "message": f"Cannot accept a pickup request with status '{pickup.status}'. Only PENDING requests can be accepted.",
                    },
                    status=status.HTTP_409_CONFLICT
                )

            pickup.status = 'ACCEPTED'
            pickup.accepted_by = request.user
            pickup.accepted_at = timezone.now()
            pickup.save(update_fields=['status', 'accepted_by', 'accepted_at', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Pickup request accepted successfully.",
                "data": {"pickup_id": str(pickup.id), "status": pickup.status}
            },
            status=status.HTTP_200_OK
        )


class OperatorAdminPickupRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(tags=['Operator Admins'], request=RejectPickupSerializer, responses={200: None})
    def patch(self, request, pickup_id):
        serializer = RejectPickupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            try:
                pickup = PickupRequest.objects.select_for_update().get(
                    id=pickup_id, pickup_type='ON_DEMAND'
                )
            except PickupRequest.DoesNotExist:
                return Response(
                    {"success": False, "message": "Pickup request not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if pickup.status != 'PENDING':
                return Response(
                    {
                        "success": False,
                        "message": f"Cannot reject a pickup request with status '{pickup.status}'. Only PENDING requests can be rejected.",
                    },
                    status=status.HTTP_409_CONFLICT
                )

            pickup.status = 'REJECTED'
            pickup.rejected_by = request.user
            pickup.rejected_at = timezone.now()
            pickup.rejection_reason = serializer.validated_data['reason']
            pickup.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Pickup request rejected successfully.",
                "data": {
                    "pickup_id": str(pickup.id),
                    "status": pickup.status,
                    "rejection_reason": pickup.rejection_reason,
                }
            },
            status=status.HTTP_200_OK
        )


class OperatorAdminPickupAssignView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(tags=['Operator Admins'], request=AssignOperatorSerializer, responses={200: None})
    def patch(self, request, pickup_id):
        serializer = AssignOperatorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        operator_id = serializer.validated_data['operator_id']

        with transaction.atomic():
            try:
                pickup = PickupRequest.objects.select_for_update().get(
                    id=pickup_id, pickup_type='ON_DEMAND'
                )
            except PickupRequest.DoesNotExist:
                return Response(
                    {"success": False, "message": "Pickup request not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if pickup.status != 'ACCEPTED':
                return Response(
                    {
                        "success": False,
                        "message": f"Cannot assign an operator to a pickup request with status '{pickup.status}'. Only ACCEPTED requests can have operators assigned.",
                    },
                    status=status.HTTP_409_CONFLICT
                )

            try:
                operator_user = CustomUser.objects.get(id=operator_id)
            except CustomUser.DoesNotExist:
                return Response(
                    {"success": False, "message": "Operator not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            if operator_user.base_role != 'operator':
                return Response(
                    {"success": False, "message": "The selected user is not an operator."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not operator_user.is_active:
                return Response(
                    {"success": False, "message": "The selected operator is not active."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                operator_profile = operator_user.operator_profile
                if not operator_profile.is_verified:
                    return Response(
                        {"success": False, "message": "The selected operator is not verified."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except OperatorProfile.DoesNotExist:
                return Response(
                    {"success": False, "message": "Operator profile not found."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            pickup.status = 'ASSIGNED'
            pickup.assigned_operator = operator_user
            pickup.assigned_by = request.user
            pickup.assigned_at = timezone.now()
            pickup.save(update_fields=['status', 'assigned_operator', 'assigned_by', 'assigned_at', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Operator assigned successfully.",
                "data": {
                    "pickup_id": str(pickup.id),
                    "status": pickup.status,
                    "assigned_operator": {
                        "id": str(operator_user.id),
                        "email": operator_user.email,
                        "operator_id": operator_profile.operator_id,
                    }
                }
            },
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Operator Admin Rating Views
# ---------------------------------------------------------------------------

from pickups.models import OperatorReview
from pickups.serializers import (
    OperatorAdminRatingSerializer,
    OperatorAdminOperatorReviewsSerializer,
    OperatorReviewListSerializer,
)


class OperatorAdminOperatorRatingsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: OperatorAdminRatingSerializer(many=True)}
    )
    def get(self, request):
        admin_profile = request.user.operatoradmin_profile

        operators = OperatorProfile.objects.filter(
            assigned_admin=admin_profile,
            is_verified=True,
        ).select_related('user')

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


class OperatorAdminOperatorReviewsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: OperatorAdminOperatorReviewsSerializer}
    )
    def get(self, request, operator_id):
        admin_profile = request.user.operatoradmin_profile

        try:
            operator_user = CustomUser.objects.get(id=operator_id, base_role='operator')
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Operator not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not OperatorProfile.objects.filter(
            user=operator_user,
            assigned_admin=admin_profile,
        ).exists():
            return Response(
                {"success": False, "message": "You do not have access to this operator."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reviews = OperatorReview.objects.filter(
            operator=operator_user,
        ).select_related('pickup_request')

        total = reviews.count()
        if total > 0:
            avg = reviews.aggregate(avg=Avg('rating'))['avg']
            avg_rating = round(float(avg), 1)
        else:
            avg_rating = None

        distribution = {}
        for star in range(5, 0, -1):
            distribution[str(star)] = reviews.filter(rating=star).count()

        return Response(
            {
                "success": True,
                "data": {
                    "operator_id": operator_user.id,
                    "operator_name": operator_user.username or operator_user.email,
                    "average_rating": avg_rating,
                    "total_reviews": total,
                    "rating_distribution": distribution,
                    "reviews": OperatorReviewListSerializer(reviews, many=True).data,
                },
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Operator Admin Onboarding (self-service, approved by superadmin)
# ---------------------------------------------------------------------------

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser


class OperatorAdminOnboardingView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: OperatorAdminOnboardingSerializer}
    )
    def get(self, request):
        if request.user.base_role != 'operatoradmin':
            return Response(
                {"success": False, "message": "Only operator admins can access this"},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            onboarding = request.user.operatoradmin_onboarding
        except OperatorAdminOnboarding.DoesNotExist:
            return Response(
                {"success": True, "data": None, "message": "No onboarding submitted yet"},
                status=status.HTTP_200_OK
            )
        serializer = OperatorAdminOnboardingSerializer(onboarding)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(
        tags=['Operator Admins'],
        request=OperatorAdminOnboardingSerializer,
        responses={201: OperatorAdminOnboardingSerializer},
        consumes=[OpenApiTypes.BINARY, OpenApiTypes.MULTIPART]
    )
    def post(self, request):
        if request.user.base_role != 'operatoradmin':
            return Response(
                {"success": False, "message": "Only operator admins can access this"},
                status=status.HTTP_403_FORBIDDEN
            )
        if OperatorAdminOnboarding.objects.filter(user=request.user).exists():
            return Response(
                {"success": False, "message": "Onboarding already submitted. Use PATCH to update."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = OperatorAdminOnboardingSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to submit onboarding", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {
                "success": True,
                "message": "Onboarding submitted. Awaiting superadmin approval.",
                "data": OperatorAdminOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        tags=['Operator Admins'],
        request=OperatorAdminOnboardingSerializer,
        responses={200: OperatorAdminOnboardingSerializer},
        consumes=[OpenApiTypes.BINARY, OpenApiTypes.MULTIPART]
    )
    def patch(self, request):
        if request.user.base_role != 'operatoradmin':
            return Response(
                {"success": False, "message": "Only operator admins can access this"},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            onboarding = request.user.operatoradmin_onboarding
        except OperatorAdminOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet. Use POST first."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = OperatorAdminOnboardingSerializer(
            onboarding, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to update onboarding", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {
                "success": True,
                "message": "Onboarding updated. Awaiting superadmin approval.",
                "data": OperatorAdminOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )
