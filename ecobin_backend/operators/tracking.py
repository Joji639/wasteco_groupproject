import json
import logging
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from accounts.permissions import _in_group
from pickups.models import PickupRequest

logger = logging.getLogger(__name__)

# Redis key pattern: operator_location:{pickup_id}
# Value: JSON {"lat": ..., "lng": ..., "operator_id": ..., "timestamp": ...}
LOCATION_TTL = 30  # seconds — auto-expires stale locations


def _location_key(pickup_id):
    return f"operator_location:{pickup_id}"


def _save_operator_location(pickup_id, lat, lng, operator_id):
    key = _location_key(pickup_id)
    data = json.dumps({
        "lat": str(lat),
        "lng": str(lng),
        "operator_id": str(operator_id),
        "timestamp": datetime.utcnow().isoformat(),
    })
    cache.set(key, data, timeout=LOCATION_TTL)


def _get_operator_location(pickup_id):
    key = _location_key(pickup_id)
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


class IsOperatorRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.base_role == 'operator'
        )


class OperatorUpdateLocationView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'pickup_id': {'type': 'string', 'format': 'uuid'},
                    'latitude': {'type': 'number'},
                    'longitude': {'type': 'number'},
                },
                'required': ['pickup_id', 'latitude', 'longitude'],
            }
        },
        responses={200: None}
    )
    def post(self, request):
        pickup_id = request.data.get('pickup_id')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')

        if not pickup_id or latitude is None or longitude is None:
            return Response(
                {"success": False, "message": "pickup_id, latitude, and longitude are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError):
            return Response(
                {"success": False, "message": "latitude and longitude must be numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return Response(
                {"success": False, "message": "Invalid coordinates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        if pickup.status not in ('ASSIGNED', 'ON_THE_WAY', 'COLLECTED'):
            return Response(
                {"success": False, "message": f"Cannot update location for pickup with status '{pickup.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _save_operator_location(pickup_id, lat, lng, request.user.id)

        return Response(
            {"success": True, "message": "Location updated."},
            status=status.HTTP_200_OK,
        )


class OperatorGetLocationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Operators'],
        responses={200: None}
    )
    def get(self, request, pickup_id):
        try:
            pickup = PickupRequest.objects.get(id=pickup_id)
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only the pickup owner or the assigned operator can see location
        if pickup.user != request.user and pickup.assigned_operator != request.user:
            return Response(
                {"success": False, "message": "You do not have permission to view this location."},
                status=status.HTTP_403_FORBIDDEN,
            )

        location = _get_operator_location(pickup_id)

        if location is None:
            return Response(
                {
                    "success": True,
                    "data": None,
                    "message": "Operator location not available (may be offline).",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"success": True, "data": location},
            status=status.HTTP_200_OK,
        )
