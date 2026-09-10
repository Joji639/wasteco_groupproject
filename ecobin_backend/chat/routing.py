from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/communities/(?P<community_id>\d+)/$',
        consumers.CommunityChatConsumer.as_asgi(),
    ),
]
