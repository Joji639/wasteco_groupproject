import json
import logging
import math

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

ARRIVAL_RADIUS_KM = 0.05  # 50 meters


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class PickupTrackingConsumer(AsyncWebsocketConsumer):
    """
    WebSocket: /ws/pickup-tracking/{pickup_id}/?token=xxx

    Flow:
      Operator sends GPS   → backend broadcasts to user
      Operator arrives     → status: ARRIVED
      Operator collects    → REST API records waste → status: COLLECTING → COMPLETED
      User pays            → status: PAID

    Location payload: {latitude, longitude, remaining_distance_m, arrived}
    Status payload:   {status, message, collection_data?, payment_data?}
    """

    async def connect(self):
        self.pickup_id = self.scope['url_route']['kwargs']['pickup_id']
        self.room_group = f'pickup_tracking_{self.pickup_id}'
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

        current_status = await self._get_current_status()
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'tracking_id': self.pickup_id,
            'status': current_status,
        }))

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

        is_operator = await self._is_operator()
        if not is_operator:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Only the assigned operator can send location updates.',
            }))
            return

        tracking = await self._update_location(lat, lng)

        if tracking is None:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Tracking not found or not active.',
            }))
            return

        user_lat = float(tracking.pickup_request.latitude)
        user_lng = float(tracking.pickup_request.longitude)
        distance_km = haversine_km(lat, lng, user_lat, user_lng)
        arrived = distance_km <= ARRIVAL_RADIUS_KM
        remaining_m = distance_km * 1000

        if arrived and tracking.status == 'EN_ROUTE':
            await self._mark_arrived()

        await self.channel_layer.group_send(
            self.room_group,
            {
                'type': 'tracking_update',
                'payload': {
                    'type': 'location_update',
                    'operator_id': str(self.user.id),
                    'latitude': lat,
                    'longitude': lng,
                    'remaining_distance_m': round(remaining_m, 1),
                    'arrived': arrived,
                },
            },
        )

    async def tracking_update(self, event):
        await self.send(text_data=json.dumps(event['payload']))

    async def status_update(self, event):
        await self.send(text_data=json.dumps(event['payload']))

    @database_sync_to_async
    def _get_current_status(self):
        from pickups.models import PickupTracking
        try:
            tracking = PickupTracking.objects.get(id=self.pickup_id)
            return tracking.status
        except PickupTracking.DoesNotExist:
            return 'UNKNOWN'

    @database_sync_to_async
    def _check_access(self):
        from pickups.models import PickupTracking
        try:
            tracking = PickupTracking.objects.select_related(
                'pickup_request', 'pickup_request__user', 'operator',
            ).get(id=self.pickup_id)
        except PickupTracking.DoesNotExist:
            return False

        return (
            self.user == tracking.pickup_request.user
            or self.user == tracking.operator
            or self.user.groups.filter(name__in=['OperatorAdmin', 'SuperAdmin']).exists()
        )

    @database_sync_to_async
    def _is_operator(self):
        from pickups.models import PickupTracking
        try:
            tracking = PickupTracking.objects.get(id=self.pickup_id)
            return (
                self.user == tracking.operator
                and tracking.status in ('EN_ROUTE', 'ARRIVED')
            )
        except PickupTracking.DoesNotExist:
            return False

    @database_sync_to_async
    def _update_location(self, lat, lng):
        from pickups.models import PickupTracking
        try:
            tracking = PickupTracking.objects.get(
                id=self.pickup_id,
                operator=self.user,
                status__in=('EN_ROUTE', 'ARRIVED'),
            )
            tracking.current_latitude = lat
            tracking.current_longitude = lng
            tracking.save(update_fields=['current_latitude', 'current_longitude', 'updated_at'])
            return tracking
        except PickupTracking.DoesNotExist:
            return None

    @database_sync_to_async
    def _mark_arrived(self):
        from pickups.models import PickupTracking
        from django.utils import timezone
        try:
            tracking = PickupTracking.objects.get(id=self.pickup_id)
            tracking.status = 'ARRIVED'
            tracking.arrived_at = timezone.now()
            tracking.save(update_fields=['status', 'arrived_at', 'updated_at'])

            self.channel_layer.group_send(
                self.room_group,
                {
                    'type': 'status_update',
                    'payload': {
                        'type': 'status_change',
                        'status': 'ARRIVED',
                        'message': 'Operator has arrived at your location.',
                    },
                },
            )
        except PickupTracking.DoesNotExist:
            pass
