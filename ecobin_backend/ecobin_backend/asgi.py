"""
ASGI config for ecobin_backend project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecobin_backend.settings')

django_asgi_app = get_asgi_application()

from pickups.ws_routing import websocket_urlpatterns as pickup_ws
from chat.routing import websocket_urlpatterns as chat_ws
from services.routing import websocket_urlpatterns as service_ws

from pickups.jwt_auth import JWTAuthMiddleware

all_ws = pickup_ws + service_ws + chat_ws

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': JWTAuthMiddleware(URLRouter(all_ws)),
})
