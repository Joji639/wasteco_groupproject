import json
import logging
import math

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import ServiceRequest
from django.utils import timezone
from .models import ServiceRequest

logger = logging.getLogger(__name__)

ARRIVAL_RADIUS_KM = 0.05  # 50 meters


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ServiceTrackingConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: /ws/tracking/{requestId}/?token=xxx

    Technician sends GPS → backend validates + broadcasts to user.
    Payload: {latitude, longitude, route_coords, total_distance_m,
              total_duration_s, remaining_distance_m, remaining_duration_s, arrived}
    """

    async def connect(self):
        self.service_id = self.scope['url_route']['kwargs']['request_id']
        self.room_group = f'service_tracking_{self.service_id}'
        self.user = self.scope.get('user', AnonymousUser())

        if self.user.is_anonymous:
            await self.close()
            return

        has_access = await self._check_access()
        if not has_access:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group'):
            await self.channel_layer.group_discard(
                self.room_group,
                self.channel_name,
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON.',
            }))
            return

        msg_type = data.get('type', '')

        if msg_type == 'location_update':
            await self._handle_location_update(data)
        elif msg_type == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Unknown message type: {msg_type}',
            }))

    async def _handle_location_update(self, data):
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if latitude is None or longitude is None:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'latitude and longitude are required.',
            }))
            return

        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'latitude and longitude must be numbers.',
            }))
            return

        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid coordinates.',
            }))
            return

        is_technician = await self._is_technician()
        if not is_technician:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Only the assigned technician can send location updates.',
            }))
            return

        service = await self._update_technician_location(lat, lng)

        if service is None:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Service request not found or not in active status.',
            }))
            return

        user_lat = float(service.user_latitude)
        user_lng = float(service.user_longitude)
        distance_km = haversine_km(lat, lng, user_lat, user_lng)
        arrived = distance_km <= ARRIVAL_RADIUS_KM
        remaining_m = distance_km * 1000

        route_coords = data.get('route_coords', [])
        total_distance_m = data.get('total_distance_m', 0)
        total_duration_s = data.get('total_duration_s', 0)

        if arrived and service.status == 'ACCEPTED':
            await self._mark_arrived()

        await self.channel_layer.group_send(
            self.room_group,
            {
                'type': 'tracking_update',
                'payload': {
                    'type': 'location_update',
                    'technician_id': str(self.user.id),
                    'latitude': lat,
                    'longitude': lng,
                    'route_coords': route_coords,
                    'total_distance_m': total_distance_m,
                    'total_duration_s': total_duration_s,
                    'remaining_distance_m': round(remaining_m, 1),
                    'remaining_duration_s': 0,
                    'arrived': arrived,
                },
            },
        )

    async def tracking_update(self, event):
        await self.send(text_data=json.dumps(event['payload']))

    @database_sync_to_async
    def _check_access(self):
        
        try:
            service = ServiceRequest.objects.get(id=self.service_id)
        except ServiceRequest.DoesNotExist:
            return False

        return (
            self.user == service.user
            or self.user == service.technician
            or self.user == service.operator
            or self.user.groups.filter(name__in=['OperatorAdmin', 'SuperAdmin']).exists()
        )

    @database_sync_to_async
    def _is_technician(self):
        try:
            service = ServiceRequest.objects.get(id=self.service_id)
            return (
                self.user == service.technician
                and service.status in ('ACCEPTED', 'ARRIVED', 'IN_PROGRESS')
            )
        except ServiceRequest.DoesNotExist:
            return False

    @database_sync_to_async
    def _update_technician_location(self, lat, lng):
        try:
            service = ServiceRequest.objects.get(
                id=self.service_id,
                technician=self.user,
                status__in=('ACCEPTED', 'ARRIVED', 'IN_PROGRESS'),
            )
            service.technician_latitude = lat
            service.technician_longitude = lng
            service.save(update_fields=['technician_latitude', 'technician_longitude', 'updated_at'])
            return service
        except ServiceRequest.DoesNotExist:
            return None

    @database_sync_to_async
    def _mark_arrived(self):
        
        
        try:
            service = ServiceRequest.objects.get(id=self.service_id)
            service.status = 'ARRIVED'
            service.arrived_at = timezone.now()
            service.save(update_fields=['status', 'arrived_at', 'updated_at'])
        except ServiceRequest.DoesNotExist:
            pass
