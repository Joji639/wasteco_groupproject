from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/pickup-tracking/(?P<pickup_id>[0-9a-f-]+)/$',
        consumers.PickupTrackingConsumer.as_asgi(),
    ),
]
