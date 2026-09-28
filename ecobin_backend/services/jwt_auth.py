from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from urllib.parse import parse_qs
from accounts.models import CustomUser

class JWTAuthMiddleware(BaseMiddleware):
    """
    WebSocket middleware that authenticates users via JWT token.
    Token passed as query parameter: ?token=xxx
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        token_list = params.get('token', [])

        if token_list:
            token = token_list[0]
            scope['user'] = await self._authenticate_jwt(token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)

    @database_sync_to_async
    def _authenticate_jwt(self, token):
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            
            return CustomUser.objects.get(id=user_id)
        except (InvalidToken, TokenError, KeyError, Exception):
            return AnonymousUser()
