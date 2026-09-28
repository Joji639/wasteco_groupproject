from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema
from django.db.models import Avg, Count, Q

from accounts.models import OperatorOnboarding
from accounts.serializers import (
    OperatorOnboardingSerializer, OperatorPersonalInfoSerializer,
    AccountInfoSerializer, ChangePasswordSerializer, LogoutSerializer,
)
from accounts.permissions import IsStaffRole, IsApprovedStaff, _in_group


class OperatorOnboardingView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=['Operators'], responses={200: OperatorOnboardingSerializer})
    def get(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": True, "data": None, "message": "No onboarding submitted yet"},
                status=status.HTTP_200_OK
            )

        serializer = OperatorOnboardingSerializer(onboarding)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={201: OperatorOnboardingSerializer})
    def post(self, request):
        if OperatorOnboarding.objects.filter(user=request.user).exists():
            return Response(
                {"success": False, "message": "Onboarding already submitted. Use PATCH to resubmit after rejection."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OperatorOnboardingSerializer(data=request.data, context={"request": request})
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
                "message": "Onboarding submitted. Awaiting approval.",
                "data": OperatorOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_201_CREATED
        )

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={200: OperatorOnboardingSerializer})
    def patch(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorOnboardingSerializer(
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
                "message": "Onboarding updated. Awaiting approval.",
                "data": OperatorOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class OperatorAccountInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsApprovedStaff]

    @extend_schema(tags=['Operators'], responses={200: AccountInfoSerializer})
    def get(self, request):
        try:
            serializer = AccountInfoSerializer(request.user)
            return Response(
                {"success": True, "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load account info", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(tags=['Operators'], request=AccountInfoSerializer, responses={200: None})
    def patch(self, request):
        try:
            serializer = AccountInfoSerializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": "Account info updated.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class OperatorPersonalInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsApprovedStaff]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=['Operators'], responses={200: OperatorPersonalInfoSerializer})
    def get(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorPersonalInfoSerializer(onboarding)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={200: OperatorPersonalInfoSerializer})
    def patch(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorOnboardingSerializer(
            onboarding, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Personal info updated. Awaiting re-approval.",
                "data": OperatorPersonalInfoSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class OperatorChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(tags=['Operators'], request=ChangePasswordSerializer, responses={200: None})
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {"success": False, "message": "Old password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user.set_password(serializer.validated_data['new_password'])
            user.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Password change failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Password changed successfully. Please log in again."},
            status=status.HTTP_200_OK
        )


class OperatorLogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(tags=['Operators'], request=LogoutSerializer, responses={200: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data['refresh'])
            token.blacklist()
        except TokenError:
            return Response(
                {"success": False, "message": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Logout failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Logged out successfully"},
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# Operator Review Views
# ---------------------------------------------------------------------------

from pickups.models import OperatorReview
from pickups.serializers import OperatorReviewListSerializer, OperatorRatingSummarySerializer, AreaAssignmentSerializer


class OperatorReviewsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: OperatorReviewListSerializer(many=True)}
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reviews = OperatorReview.objects.filter(
            operator=request.user,
        ).select_related('pickup_request')

        serializer = OperatorReviewListSerializer(reviews, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class OperatorRatingSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: OperatorRatingSummarySerializer}
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reviews = OperatorReview.objects.filter(operator=request.user)
        total = reviews.count()

        if total == 0:
            data = {
                'average_rating': None,
                'total_reviews': 0,
                'rating_distribution': {'5': 0, '4': 0, '3': 0, '2': 0, '1': 0},
            }
        else:
            avg = reviews.aggregate(avg=Avg('rating'))['avg']
            distribution = {}
            for star in range(5, 0, -1):
                distribution[str(star)] = reviews.filter(rating=star).count()
            data = {
                'average_rating': round(float(avg), 1),
                'total_reviews': total,
                'rating_distribution': distribution,
            }

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Operator Area Assignment View
# ---------------------------------------------------------------------------

from pickups.models import AreaAssignment


class OperatorAssignedAreasView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: AreaAssignmentSerializer(many=True)},
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        assignments = AreaAssignment.objects.filter(
            operator=request.user
        ).select_related('area', 'assigned_by').order_by('-assigned_at')

        serializer = AreaAssignmentSerializer(assignments, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Waste Collection Views
# ---------------------------------------------------------------------------

from pickups.models import CollectionRecord, PickupRequest, Area
from pickups.serializers import (
    WasteCollectionCreateSerializer, WasteCollectionFailureSerializer,
    CollectionRecordSerializer,
)


class WasteCollectionCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        request=WasteCollectionCreateSerializer,
        responses={201: CollectionRecordSerializer},
    )
    def post(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = WasteCollectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from accounts.models import OperatorProfile
        try:
            profile = request.user.operator_profile
            operator_id_display = profile.operator_id
        except OperatorProfile.DoesNotExist:
            operator_id_display = f"OP-{str(request.user.id)[:8]}"

        collection = CollectionRecord.objects.create(
            operator=request.user,
            operator_id_display=operator_id_display,
            resident_name=serializer.validated_data['resident_name'],
            resident_email=serializer.validated_data.get('resident_email', ''),
            resident_phone=serializer.validated_data.get('resident_phone', ''),
            house_address=serializer.validated_data['house_address'],
            waste_type=serializer.validated_data['waste_type'],
            quantity_kg=serializer.validated_data.get('quantity_kg'),
            status='COLLECTED',
        )

        return Response(
            {
                "success": True,
                "message": "Waste collected successfully.",
                "data": CollectionRecordSerializer(collection).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WasteCollectionFailureView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        request=WasteCollectionFailureSerializer,
        responses={201: CollectionRecordSerializer},
    )
    def post(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = WasteCollectionFailureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from accounts.models import OperatorProfile
        try:
            profile = request.user.operator_profile
            operator_id_display = profile.operator_id
        except OperatorProfile.DoesNotExist:
            operator_id_display = f"OP-{str(request.user.id)[:8]}"

        collection = CollectionRecord.objects.create(
            operator=request.user,
            operator_id_display=operator_id_display,
            resident_name=serializer.validated_data['resident_name'],
            resident_email=serializer.validated_data.get('resident_email', ''),
            resident_phone=serializer.validated_data.get('resident_phone', ''),
            house_address=serializer.validated_data['house_address'],
            waste_type='MIXED',
            status='FAILED',
            failure_reason=serializer.validated_data['failure_reason'],
        )

        return Response(
            {
                "success": True,
                "message": "Failure recorded.",
                "data": CollectionRecordSerializer(collection).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WasteCollectionHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: CollectionRecordSerializer(many=True)},
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        collections = CollectionRecord.objects.filter(
            operator=request.user
        ).select_related('pickup_request', 'area').order_by('-collected_at')

        serializer = CollectionRecordSerializer(collections, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Pickup Tracking Views
# ---------------------------------------------------------------------------

from pickups.models import PickupTracking, PickupRequest
from pickups.serializers import (
    PickupTrackingStartSerializer, PickupTrackingSerializer,
    PickupTrackingLocationSerializer,
)
from pickups.routing import calculate_route
from pickups.simulation import start_simulation, stop_simulation, get_operator_position


class PickupTrackingStartView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        request=PickupTrackingStartSerializer,
        responses={201: PickupTrackingSerializer},
    )
    def post(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PickupTrackingStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pickup_id = serializer.validated_data['pickup_request_id']

        try:
            pickup = PickupRequest.objects.get(id=pickup_id)
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if pickup.assigned_operator != request.user:
            return Response(
                {"success": False, "message": "This pickup is not assigned to you."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if PickupTracking.objects.filter(pickup_request=pickup, status__in=('EN_ROUTE', 'ARRIVED')).exists():
            return Response(
                {"success": False, "message": "Tracking already active for this pickup."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_lat = float(serializer.validated_data['start_latitude'])
        start_lng = float(serializer.validated_data['start_longitude'])
        end_lat = float(pickup.latitude)
        end_lng = float(pickup.longitude)

        waypoints, duration = calculate_route(start_lat, start_lng, end_lat, end_lng)

        if not waypoints:
            return Response(
                {"success": False, "message": "Could not calculate route. Please try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone

        tracking = PickupTracking.objects.create(
            pickup_request=pickup,
            operator=request.user,
            start_place=serializer.validated_data['start_location'],
            start_latitude=start_lat,
            start_longitude=start_lng,
            current_latitude=start_lat,
            current_longitude=start_lng,
            route_data={"waypoints": waypoints},
            total_distance_meters=len(waypoints) * 10,
            total_duration_seconds=duration,
            status='EN_ROUTE',
            progress=0.0,
            started_at=timezone.now(),
        )

        pickup.status = 'ON_THE_WAY'
        pickup.save(update_fields=['status', 'updated_at'])

        start_simulation(str(tracking.id))

        return Response(
            {
                "success": True,
                "message": "Tracking started. Route calculated.",
                "data": PickupTrackingSerializer(tracking).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PickupTrackingLocationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Operators'],
        responses={200: PickupTrackingSerializer},
    )
    def get(self, request, tracking_id):
        try:
            tracking = PickupTracking.objects.select_related(
                'pickup_request', 'pickup_request__user', 'operator',
            ).get(id=tracking_id)
        except PickupTracking.DoesNotExist:
            return Response(
                {"success": False, "message": "Tracking not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        is_operator = user == tracking.operator
        is_user = user == tracking.pickup_request.user
        is_admin = _in_group(user, 'OperatorAdmin') or _in_group(user, 'SuperAdmin')

        if not (is_operator or is_user or is_admin):
            return Response(
                {"success": False, "message": "You do not have permission to view this tracking."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cached_pos = get_operator_position(str(tracking.id))
        if cached_pos:
            tracking.current_latitude = cached_pos['lat']
            tracking.current_longitude = cached_pos['lng']
            tracking.progress = cached_pos.get('progress', tracking.progress)

        return Response(
            {"success": True, "data": PickupTrackingSerializer(tracking).data},
            status=status.HTTP_200_OK,
        )


class PickupTrackingStopView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]
    serializer_class = PickupTrackingSerializer

    @extend_schema(
        tags=['Operators'],
        responses={200: PickupTrackingSerializer},
    )
    def post(self, request, tracking_id):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            tracking = PickupTracking.objects.get(
                id=tracking_id,
                operator=request.user,
                status='EN_ROUTE',
            )
        except PickupTracking.DoesNotExist:
            return Response(
                {"success": False, "message": "Active tracking not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        stop_simulation(str(tracking.id))

        from django.utils import timezone
        tracking.status = 'COMPLETED'
        tracking.save(update_fields=['status', 'updated_at'])

        pickup = tracking.pickup_request
        pickup.status = 'COLLECTED'
        pickup.save(update_fields=['status', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Tracking stopped. Pickup marked as collected.",
                "data": PickupTrackingSerializer(tracking).data,
            },
            status=status.HTTP_200_OK,
        )


class PickupTrackingActiveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Operators'],
        responses={200: PickupTrackingSerializer(many=True)},
    )
    def get(self, request):
        user = request.user

        if _in_group(user, 'Operator'):
            trackings = PickupTracking.objects.filter(
                operator=user,
                status__in=('EN_ROUTE', 'ARRIVED'),
            ).select_related('pickup_request', 'pickup_request__user', 'operator')
        elif _in_group(user, 'OperatorAdmin') or _in_group(user, 'SuperAdmin'):
            trackings = PickupTracking.objects.filter(
                status__in=('EN_ROUTE', 'ARRIVED'),
            ).select_related('pickup_request', 'pickup_request__user', 'operator')
        else:
            trackings = PickupTracking.objects.filter(
                pickup_request__user=user,
                status__in=('EN_ROUTE', 'ARRIVED'),
            ).select_related('pickup_request', 'pickup_request__user', 'operator')

        serializer = PickupTrackingSerializer(trackings, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )
