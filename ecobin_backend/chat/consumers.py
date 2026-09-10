import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

MESSAGE_MAX_LENGTH = 5000


class CommunityChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user', AnonymousUser())
        self.community_id = self.scope['url_route']['kwargs']['community_id']
        self.room_group_name = f'community_{self.community_id}'

        if self.user.is_anonymous:
            await self.close()
            return

        is_member = await self._check_membership()
        if not is_member:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
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
        if msg_type != 'message':
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Only "message" type is supported.',
            }))
            return

        content = data.get('content', '')
        if not content or not content.strip():
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Message content cannot be empty.',
            }))
            return

        content = content.strip()
        if len(content) > MESSAGE_MAX_LENGTH:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Message exceeds maximum length of {MESSAGE_MAX_LENGTH} characters.',
            }))
            return

        is_member = await self._check_membership()
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'You are not a member of this community.',
            }))
            return

        message = await self._save_message(content)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': {
                    'id': message['id'],
                    'community_id': self.community_id,
                    'sender': {
                        'id': str(self.user.id),
                        'email': self.user.email,
                        'base_role': self.user.base_role,
                    },
                    'content': message['content'],
                    'created_at': message['created_at'],
                },
            },
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message': event['message'],
        }))

    @database_sync_to_async
    def _check_membership(self):
        from .models import CommunityMember
        return CommunityMember.objects.filter(
            community_id=self.community_id,
            user=self.user,
            is_active=True,
        ).exists()

    @database_sync_to_async
    def _save_message(self, content):
        from .models import Message
        from django.utils import timezone
        message = Message.objects.create(
            community_id=self.community_id,
            sender=self.user,
            content=content,
        )
        return {
            'id': message.id,
            'content': message.content,
            'created_at': message.created_at.isoformat(),
        }
