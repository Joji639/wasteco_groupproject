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
            logger.error("Failed to load onboarding requests: %s", e)
            return Response(
                {"success": False, "message": "Failed to load onboarding requests"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to approve onboarding"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to reject onboarding"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to load user onboarding requests"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to approve user onboarding"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to reject user onboarding"},
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

from pickups.models import PickupRequest, ScheduledPickup, Area, AreaAssignment
from pickups.serializers import (
    OperatorAdminPickupListSerializer, OperatorAdminPickupDetailSerializer,
    RejectPickupSerializer, AssignOperatorSerializer,
    ScheduledPickupCreateSerializer, ScheduledPickupUpdateSerializer,
    ScheduledPickupSerializer,
    AreaCreateSerializer, AreaSerializer,
    AreaAssignmentCreateSerializer, AreaAssignmentSerializer,
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
    serializer_class = OperatorAdminPickupDetailSerializer

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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to submit onboarding"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Failed to update onboarding"},
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


# ---------------------------------------------------------------------------
# Scheduled Pickup Views
# ---------------------------------------------------------------------------

class ScheduledPickupCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        request=ScheduledPickupCreateSerializer,
        responses={201: ScheduledPickupSerializer},
    )
    def post(self, request):
        serializer = ScheduledPickupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pickup = ScheduledPickup.objects.create(
            scheduled_date=serializer.validated_data['scheduled_date'],
            created_by=request.user,
        )

        return Response(
            {
                "success": True,
                "message": "Scheduled pickup created.",
                "data": ScheduledPickupSerializer(pickup).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ScheduledPickupUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        request=ScheduledPickupUpdateSerializer,
        responses={200: ScheduledPickupSerializer},
    )
    def patch(self, request, pickup_id):
        try:
            pickup = ScheduledPickup.objects.get(id=pickup_id)
        except ScheduledPickup.DoesNotExist:
            return Response(
                {"success": False, "message": "Scheduled pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ScheduledPickupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pickup.scheduled_date = serializer.validated_data['scheduled_date']
        pickup.save()

        return Response(
            {
                "success": True,
                "message": "Scheduled pickup date updated.",
                "data": ScheduledPickupSerializer(pickup).data,
            },
            status=status.HTTP_200_OK,
        )


class ScheduledPickupDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: None},
    )
    def delete(self, request, pickup_id):
        try:
            pickup = ScheduledPickup.objects.get(id=pickup_id)
        except ScheduledPickup.DoesNotExist:
            return Response(
                {"success": False, "message": "Scheduled pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        pickup.delete()
        return Response(
            {"success": True, "message": "Scheduled pickup deleted."},
            status=status.HTTP_200_OK,
        )


class ScheduledPickupListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: ScheduledPickupSerializer(many=True)},
    )
    def get(self, request):
        from django.utils import timezone
        pickups = ScheduledPickup.objects.filter(
            scheduled_date__gte=timezone.now().date()
        ).select_related('created_by').order_by('scheduled_date')

        serializer = ScheduledPickupSerializer(pickups, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Area Management Views
# ---------------------------------------------------------------------------

class AreaCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        request=AreaCreateSerializer,
        responses={201: AreaSerializer},
    )
    def post(self, request):
        serializer = AreaCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        area = Area.objects.create(
            name=serializer.validated_data['name'],
            panchayath=serializer.validated_data.get('panchayath', ''),
            description=serializer.validated_data.get('description', ''),
            created_by=request.user,
        )

        return Response(
            {
                "success": True,
                "message": "Area created.",
                "data": AreaSerializer(area).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AreaListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: AreaSerializer(many=True)},
    )
    def get(self, request):
        areas = Area.objects.filter(
            created_by=request.user
        ).prefetch_related('assignments').order_by('-created_at')

        serializer = AreaSerializer(areas, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class AreaDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: None},
    )
    def delete(self, request, area_id):
        try:
            area = Area.objects.get(id=area_id, created_by=request.user)
        except Area.DoesNotExist:
            return Response(
                {"success": False, "message": "Area not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        area.delete()
        return Response(
            {"success": True, "message": "Area deleted."},
            status=status.HTTP_200_OK,
        )


class AreaAssignOperatorView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        request=AreaAssignmentCreateSerializer,
        responses={201: AreaAssignmentSerializer},
    )
    def post(self, request, area_id):
        try:
            area = Area.objects.get(id=area_id, created_by=request.user)
        except Area.DoesNotExist:
            return Response(
                {"success": False, "message": "Area not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AreaAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        operator_id = serializer.validated_data['operator_id']

        if AreaAssignment.objects.filter(area=area, operator_id=operator_id).exists():
            return Response(
                {"success": False, "message": "Operator is already assigned to this area."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = AreaAssignment.objects.create(
            area=area,
            operator_id=operator_id,
            assigned_by=request.user,
        )

        return Response(
            {
                "success": True,
                "message": "Operator assigned to area.",
                "data": AreaAssignmentSerializer(assignment).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AreaRemoveOperatorView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: None},
    )
    def delete(self, request, area_id, assignment_id):
        try:
            assignment = AreaAssignment.objects.get(
                id=assignment_id,
                area_id=area_id,
                area__created_by=request.user,
            )
        except AreaAssignment.DoesNotExist:
            return Response(
                {"success": False, "message": "Assignment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        assignment.delete()
        return Response(
            {"success": True, "message": "Operator removed from area."},
            status=status.HTTP_200_OK,
        )


class AreaAssignmentListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: AreaAssignmentSerializer(many=True)},
    )
    def get(self, request, area_id):
        try:
            area = Area.objects.get(id=area_id, created_by=request.user)
        except Area.DoesNotExist:
            return Response(
                {"success": False, "message": "Area not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        assignments = AreaAssignment.objects.filter(
            area=area
        ).select_related('operator', 'assigned_by').order_by('-assigned_at')

        serializer = AreaAssignmentSerializer(assignments, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Waste Collection Report Views
# ---------------------------------------------------------------------------

from pickups.models import CollectionRecord
from pickups.serializers import CollectionRecordSerializer, WasteCollectionReportSerializer


class WasteCollectionReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        operation_id="oa_waste_collections_all_reports",
        responses={200: WasteCollectionReportSerializer},
    )
    def get(self, request):
        collections = CollectionRecord.objects.filter(
            area__created_by=request.user,
        ).select_related('operator', 'area', 'pickup_request')

        operator_stats = {}
        for c in collections:
            op_id = c.operator_id_display
            if op_id not in operator_stats:
                profile = getattr(c.operator, 'operator_profile', None)
                operator_stats[op_id] = {
                    'operator_id': op_id,
                    'operator_name': c.operator.username,
                    'operator_email': c.operator.email,
                    'total_collections': 0,
                    'total_failed': 0,
                    'total_quantity_kg': 0,
                    'waste_breakdown': {},
                    'collections': [],
                }

            stats = operator_stats[op_id]
            if c.status == 'COLLECTED':
                stats['total_collections'] += 1
                if c.quantity_kg:
                    stats['total_quantity_kg'] += float(c.quantity_kg)
            else:
                stats['total_failed'] += 1

            waste = stats['waste_breakdown']
            waste[c.waste_type] = waste.get(c.waste_type, 0) + 1

            stats['collections'].append(CollectionRecordSerializer(c).data)

        reports = []
        for op_id, stats in operator_stats.items():
            stats['total_quantity_kg'] = round(stats['total_quantity_kg'], 2)
            reports.append(WasteCollectionReportSerializer(stats).data)

        return Response(
            {"success": True, "count": len(reports), "data": reports},
            status=status.HTTP_200_OK,
        )


class WasteCollectionReportByOperatorView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        operation_id="oa_waste_collections_operator_report",
        responses={200: WasteCollectionReportSerializer},
    )
    def get(self, request, operator_id):
        try:
            operator = CustomUser.objects.get(id=operator_id, base_role='operator')
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Operator not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        collections = CollectionRecord.objects.filter(
            operator=operator,
            area__created_by=request.user,
        ).select_related('operator', 'area', 'pickup_request')

        total_collections = collections.filter(status='COLLECTED').count()
        total_failed = collections.filter(status='FAILED').count()
        total_quantity = sum(
            float(c.quantity_kg) for c in collections if c.quantity_kg and c.status == 'COLLECTED'
        )

        waste_breakdown = {}
        for c in collections:
            waste_breakdown[c.waste_type] = waste_breakdown.get(c.waste_type, 0) + 1

        profile = getattr(operator, 'operator_profile', None)
        op_id_display = profile.operator_id if profile else f"OP-{str(operator.id)[:8]}"

        report = {
            'operator_id': op_id_display,
            'operator_name': operator.username,
            'operator_email': operator.email,
            'total_collections': total_collections,
            'total_failed': total_failed,
            'total_quantity_kg': round(total_quantity, 2),
            'waste_breakdown': waste_breakdown,
            'collections': CollectionRecordSerializer(collections, many=True).data,
        }

        return Response(
            {"success": True, "data": WasteCollectionReportSerializer(report).data},
            status=status.HTTP_200_OK,
        )


class WasteCollectionListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: CollectionRecordSerializer(many=True)},
    )
    def get(self, request):
        collections = CollectionRecord.objects.filter(
            area__created_by=request.user,
        ).select_related('operator', 'area', 'pickup_request').order_by('-collected_at')

        serializer = CollectionRecordSerializer(collections, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )
