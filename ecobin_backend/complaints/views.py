import logging

from django.db import models, transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter

from accounts.models import CustomUser, OperatorProfile
from accounts.permissions import _in_group
from pickups.geocoding import geocode_place
from .models import Complaint, ComplaintStatusHistory
from .serializers import (
    ComplaintCreateSerializer, ComplaintResponseSerializer,
    ComplaintListSerializer, ComplaintDetailSerializer,
    AssignOperatorSerializer, ComplaintStatusUpdateSerializer,
    ComplaintStatusHistorySerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class IsUserRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'User')
        )


class IsOperatorRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.base_role == 'operator'
        )


class IsOperatorAdminOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'OperatorAdmin')
        )


# ---------------------------------------------------------------------------
# USER APIs
# ---------------------------------------------------------------------------

class UserComplaintCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsUserRole]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=['User - Complaints'],
        request=ComplaintCreateSerializer,
        responses={201: ComplaintResponseSerializer}
    )
    def post(self, request):
        serializer = ComplaintCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        place = serializer.validated_data['place']
        description = serializer.validated_data['description']
        image = serializer.validated_data.get('image')

        coords = geocode_place(place)
        if coords is None:
            return Response(
                {"success": False, "message": "Could not find coordinates for this place. Please try a more specific address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                complaint = Complaint.objects.create(
                    user=request.user,
                    place=place,
                    latitude=coords[0],
                    longitude=coords[1],
                    description=description,
                    image=image,
                    status='PENDING',
                )
                ComplaintStatusHistory.objects.create(
                    complaint=complaint,
                    status='PENDING',
                    changed_by=request.user,
                )
        except Exception as e:
            logger.error("Failed to create complaint: %s", e)
            return Response(
                {"success": False, "message": "Failed to create complaint.", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": "Complaint submitted successfully.",
                "data": ComplaintResponseSerializer(complaint).data,
            },
            status=status.HTTP_201_CREATED,
        )


class UserComplaintListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsUserRole]

    @extend_schema(
        tags=['User - Complaints'],
        parameters=[
            OpenApiParameter("status", str, enum=['PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED', 'REJECTED']),
        ],
        responses={200: ComplaintListSerializer(many=True)}
    )
    def get(self, request):
        queryset = Complaint.objects.filter(user=request.user)

        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        serializer = ComplaintListSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class UserComplaintDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsUserRole]

    @extend_schema(
        tags=['User - Complaints'],
        responses={200: ComplaintDetailSerializer}
    )
    def get(self, request, complaint_id):
        try:
            complaint = Complaint.objects.select_related(
                'assigned_operator',
            ).get(id=complaint_id, user=request.user)
        except Complaint.DoesNotExist:
            return Response(
                {"success": False, "message": "Complaint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"success": True, "data": ComplaintDetailSerializer(complaint).data},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# OPERATOR ADMIN APIs
# ---------------------------------------------------------------------------

class OperatorAdminComplaintListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        parameters=[
            OpenApiParameter("status", str, enum=['PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED', 'REJECTED']),
            OpenApiParameter("operator_id", str, description="Filter by assigned operator UUID"),
        ],
        responses={200: ComplaintDetailSerializer(many=True)}
    )
    def get(self, request):
        admin_profile = request.user.operatoradmin_profile

        managed_operator_ids = OperatorProfile.objects.filter(
            assigned_admin=admin_profile,
        ).values_list('user_id', flat=True)

        queryset = Complaint.objects.filter(
            models.Q(assigned_operator__in=managed_operator_ids)
            | models.Q(assigned_operator__isnull=True, status='PENDING')
        ).select_related('user', 'assigned_operator').distinct()

        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        operator_filter = request.query_params.get('operator_id')
        if operator_filter:
            queryset = queryset.filter(assigned_operator_id=operator_filter)

        serializer = ComplaintDetailSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class OperatorAdminComplaintDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        responses={200: ComplaintDetailSerializer}
    )
    def get(self, request, complaint_id):
        admin_profile = request.user.operatoradmin_profile

        managed_operator_ids = OperatorProfile.objects.filter(
            assigned_admin=admin_profile,
        ).values_list('user_id', flat=True)

        try:
            complaint = Complaint.objects.select_related(
                'user', 'assigned_operator',
            ).get(id=complaint_id)
        except Complaint.DoesNotExist:
            return Response(
                {"success": False, "message": "Complaint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if complaint.assigned_operator and complaint.assigned_operator_id not in managed_operator_ids:
            return Response(
                {"success": False, "message": "You do not have access to this complaint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if complaint.assigned_operator is None and complaint.status == 'PENDING':
            pass  # Admins can see unassigned pending complaints

        history = ComplaintStatusHistory.objects.filter(
            complaint=complaint
        ).select_related('changed_by')

        data = ComplaintDetailSerializer(complaint).data
        data['history'] = ComplaintStatusHistorySerializer(history, many=True).data

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )


class OperatorAdminAssignComplaintView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOnly]

    @extend_schema(
        tags=['Operator Admins'],
        request=AssignOperatorSerializer,
        responses={200: None}
    )
    def post(self, request, complaint_id):
        serializer = AssignOperatorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        operator_id = serializer.validated_data['operator_id']
        admin_profile = request.user.operatoradmin_profile

        try:
            complaint = Complaint.objects.select_for_update().get(id=complaint_id)
        except Complaint.DoesNotExist:
            return Response(
                {"success": False, "message": "Complaint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if complaint.status != 'PENDING':
            return Response(
                {"success": False, "message": f"Cannot assign complaint with status '{complaint.status}'. Only PENDING complaints can be assigned."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            operator_user = CustomUser.objects.get(id=operator_id, base_role='operator')
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Operator not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not operator_user.is_active:
            return Response(
                {"success": False, "message": "The selected operator is not active."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not OperatorProfile.objects.filter(
            user=operator_user,
            assigned_admin=admin_profile,
            is_verified=True,
        ).exists():
            return Response(
                {"success": False, "message": "Operator is not within your authorized scope or not verified."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            complaint.assigned_operator = operator_user
            complaint.status = 'ASSIGNED'
            complaint.assigned_at = timezone.now()
            complaint.save(update_fields=['assigned_operator', 'status', 'assigned_at', 'updated_at'])

            ComplaintStatusHistory.objects.create(
                complaint=complaint,
                status='ASSIGNED',
                changed_by=request.user,
            )

        return Response(
            {
                "success": True,
                "message": "Complaint assigned successfully.",
                "data": ComplaintDetailSerializer(complaint).data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# OPERATOR APIs
# ---------------------------------------------------------------------------

class OperatorComplaintListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        parameters=[
            OpenApiParameter("status", str, enum=['ASSIGNED', 'IN_PROGRESS', 'RESOLVED']),
        ],
        responses={200: ComplaintListSerializer(many=True)}
    )
    def get(self, request):
        queryset = Complaint.objects.filter(
            assigned_operator=request.user,
        ).select_related('user')

        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        serializer = ComplaintListSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class OperatorComplaintDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: ComplaintDetailSerializer}
    )
    def get(self, request, complaint_id):
        try:
            complaint = Complaint.objects.select_related(
                'user', 'assigned_operator',
            ).get(id=complaint_id, assigned_operator=request.user)
        except Complaint.DoesNotExist:
            return Response(
                {"success": False, "message": "Complaint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"success": True, "data": ComplaintDetailSerializer(complaint).data},
            status=status.HTTP_200_OK,
        )


class OperatorComplaintStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        request=ComplaintStatusUpdateSerializer,
        responses={200: ComplaintDetailSerializer}
    )
    def patch(self, request, complaint_id):
        serializer = ComplaintStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']

        try:
            complaint = Complaint.objects.select_for_update().get(
                id=complaint_id,
                assigned_operator=request.user,
            )
        except Complaint.DoesNotExist:
            return Response(
                {"success": False, "message": "Complaint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not complaint.can_transition_to(new_status):
            return Response(
                {
                    "success": False,
                    "message": f"Cannot transition from '{complaint.status}' to '{new_status}'.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            complaint.status = new_status
            if new_status == 'RESOLVED':
                complaint.resolved_at = timezone.now()
            complaint.save(update_fields=['status', 'resolved_at', 'updated_at'])

            ComplaintStatusHistory.objects.create(
                complaint=complaint,
                status=new_status,
                changed_by=request.user,
            )

        return Response(
            {
                "success": True,
                "message": f"Complaint status updated to '{new_status}'.",
                "data": ComplaintDetailSerializer(complaint).data,
            },
            status=status.HTTP_200_OK,
        )
