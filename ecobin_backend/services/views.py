import math

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import _in_group, IsStaffRole
from .models import ServiceRequest
from .serializers import (
    ServiceRequestCreateSerializer, ServiceRequestSerializer,
    ServiceRequestAcceptSerializer, ServiceRequestRejectSerializer,
    ServiceRequestAssignTechnicianSerializer,
    ServiceRequestTechnicianLocationSerializer,
)

ARRIVAL_RADIUS_KM = 0.05  # 50 meters


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ServiceRequestCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Services'],
        request=ServiceRequestCreateSerializer,
        responses={201: ServiceRequestSerializer},
    )
    def post(self, request):
        if request.user.base_role != 'user':
            return Response(
                {"success": False, "message": "Only users can create service requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ServiceRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ServiceRequest.objects.create(
            user=request.user,
            user_latitude=serializer.validated_data['user_latitude'],
            user_longitude=serializer.validated_data['user_longitude'],
            user_address=serializer.validated_data.get('user_address', ''),
            service_type=serializer.validated_data.get('service_type', ''),
            description=serializer.validated_data.get('description', ''),
            status='PENDING',
        )

        return Response(
            {
                "success": True,
                "message": "Service request created.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_201_CREATED,
        )


class ServiceRequestListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Services'],
        responses={200: ServiceRequestSerializer(many=True)},
    )
    def get(self, request):
        user = request.user

        if _in_group(user, 'Operator'):
            services = ServiceRequest.objects.filter(
                technician=user,
            ).select_related('user', 'operator', 'technician')
        elif _in_group(user, 'OperatorAdmin'):
            services = ServiceRequest.objects.filter(
                operator=user,
            ).select_related('user', 'operator', 'technician')
        else:
            services = ServiceRequest.objects.filter(
                user=user,
            ).select_related('user', 'operator', 'technician')

        serializer = ServiceRequestSerializer(services, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class ServiceRequestDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Services'],
        responses={200: ServiceRequestSerializer},
    )
    def get(self, request, service_id):
        try:
            service = ServiceRequest.objects.select_related(
                'user', 'operator', 'technician',
            ).get(id=service_id)
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user
        is_owner = user == service.user
        is_operator = user == service.operator
        is_technician = user == service.technician
        is_admin = _in_group(user, 'OperatorAdmin', 'SuperAdmin')

        if not (is_owner or is_operator or is_technician or is_admin):
            return Response(
                {"success": False, "message": "You do not have permission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {"success": True, "data": ServiceRequestSerializer(service).data},
            status=status.HTTP_200_OK,
        )


class ServiceRequestAcceptView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Services'],
        request=ServiceRequestAcceptSerializer,
        responses={200: ServiceRequestSerializer},
    )
    def patch(self, request, service_id):
        try:
            service = ServiceRequest.objects.get(id=service_id, status='PENDING')
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pending service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ServiceRequestAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            service.operator = request.user
            service.operator_latitude = serializer.validated_data['operator_latitude']
            service.operator_longitude = serializer.validated_data['operator_longitude']
            service.status = 'ACCEPTED'
            service.accepted_at = timezone.now()
            service.save(update_fields=[
                'operator', 'operator_latitude', 'operator_longitude',
                'status', 'accepted_at', 'updated_at',
            ])

        return Response(
            {
                "success": True,
                "message": "Service accepted.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_200_OK,
        )


class ServiceRequestRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Services'],
        request=ServiceRequestRejectSerializer,
        responses={200: ServiceRequestSerializer},
    )
    def patch(self, request, service_id):
        try:
            service = ServiceRequest.objects.get(id=service_id, status='PENDING')
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pending service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ServiceRequestRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            service.operator = request.user
            service.status = 'REJECTED'
            service.rejection_reason = serializer.validated_data.get('rejection_reason', '')
            service.save(update_fields=[
                'operator', 'status', 'rejection_reason', 'updated_at',
            ])

        return Response(
            {
                "success": True,
                "message": "Service rejected.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_200_OK,
        )


class ServiceRequestAssignTechnicianView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Services'],
        request=ServiceRequestAssignTechnicianSerializer,
        responses={200: ServiceRequestSerializer},
    )
    def patch(self, request, service_id):
        try:
            service = ServiceRequest.objects.get(id=service_id, status='ACCEPTED')
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Accepted service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if service.operator != request.user and not _in_group(request.user, 'OperatorAdmin'):
            return Response(
                {"success": False, "message": "Only the accepting operator or admin can assign a technician."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ServiceRequestAssignTechnicianSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from accounts.models import CustomUser
        technician = CustomUser.objects.get(id=serializer.validated_data['technician_id'])

        with transaction.atomic():
            service.technician = technician
            service.save(update_fields=['technician', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Technician assigned.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_200_OK,
        )


class ServiceRequestTechnicianLocationUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Services'],
        request=ServiceRequestTechnicianLocationSerializer,
        responses={200: None},
    )
    def patch(self, request, service_id):
        try:
            service = ServiceRequest.objects.get(
                id=service_id,
                technician=request.user,
                status__in=('ACCEPTED', 'ARRIVED', 'IN_PROGRESS'),
            )
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Active service request not found for this technician."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ServiceRequestTechnicianLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lat = serializer.validated_data['latitude']
        lng = serializer.validated_data['longitude']

        with transaction.atomic():
            service.technician_latitude = lat
            service.technician_longitude = lng

            distance_km = haversine_km(
                float(lat), float(lng),
                float(service.user_latitude), float(service.user_longitude),
            )

            if service.status == 'ACCEPTED' and distance_km <= ARRIVAL_RADIUS_KM:
                service.status = 'ARRIVED'
                service.arrived_at = timezone.now()

            service.save(update_fields=[
                'technician_latitude', 'technician_longitude',
                'status', 'arrived_at', 'updated_at',
            ])

        return Response(
            {
                "success": True,
                "message": "Location updated.",
                "distance_to_user_km": round(distance_km, 3),
                "arrived": distance_km <= ARRIVAL_RADIUS_KM,
            },
            status=status.HTTP_200_OK,
        )


class ServiceRequestStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ServiceRequestSerializer

    @extend_schema(
        tags=['Services'],
        responses={200: ServiceRequestSerializer},
    )
    def patch(self, request, service_id, new_status):
        VALID_TRANSITIONS = {
            'ARRIVED': ('IN_PROGRESS',),
            'IN_PROGRESS': ('COMPLETED',),
            'COMPLETED': ('PAID',),
        }

        allowed = VALID_TRANSITIONS.get(new_status, ())
        if not allowed:
            return Response(
                {"success": False, "message": f"Cannot transition to '{new_status}' via this endpoint."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = ServiceRequest.objects.get(id=service_id)
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if service.status not in allowed:
            return Response(
                {"success": False, "message": f"Cannot transition from '{service.status}' to '{new_status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        is_technician = user == service.technician
        is_operator = user == service.operator
        is_admin = _in_group(user, 'OperatorAdmin', 'SuperAdmin')

        if not (is_technician or is_operator or is_admin):
            return Response(
                {"success": False, "message": "You do not have permission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            service.status = new_status
            if new_status == 'COMPLETED':
                service.completed_at = timezone.now()
            service.save(update_fields=['status', 'completed_at', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": f"Status updated to {new_status}.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_200_OK,
        )


class ServiceRequestCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ServiceRequestSerializer

    @extend_schema(
        tags=['Services'],
        responses={200: ServiceRequestSerializer},
    )
    def patch(self, request, service_id):
        try:
            service = ServiceRequest.objects.get(id=service_id)
        except ServiceRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Service request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if service.status in ('COMPLETED', 'PAID', 'CANCELLED'):
            return Response(
                {"success": False, "message": f"Cannot cancel a '{service.status}' service."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if user != service.user and not _in_group(user, 'OperatorAdmin', 'SuperAdmin'):
            return Response(
                {"success": False, "message": "You do not have permission."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            service.status = 'CANCELLED'
            service.save(update_fields=['status', 'updated_at'])

        return Response(
            {
                "success": True,
                "message": "Service cancelled.",
                "data": ServiceRequestSerializer(service).data,
            },
            status=status.HTTP_200_OK,
        )
