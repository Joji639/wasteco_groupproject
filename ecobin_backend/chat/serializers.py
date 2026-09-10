from rest_framework import serializers
from .models import Community, CommunityMember, Message


class CommunityCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Community
        fields = ['name', 'description']

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Community name cannot be empty.')
        if len(value) > 200:
            raise serializers.ValidationError('Community name is too long.')
        return value.strip()

    def validate_description(self, value):
        if value and len(value) > 1000:
            raise serializers.ValidationError('Description is too long.')
        return value.strip() if value else value


class CommunityDetailSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Community
        fields = [
            'id', 'name', 'description', 'created_by',
            'is_active', 'created_at', 'updated_at', 'member_count',
        ]

    def get_created_by(self, obj):
        return {
            'id': str(obj.created_by.id),
            'email': obj.created_by.email,
        }

    def get_member_count(self, obj):
        return obj.members.filter(is_active=True).count()


class CommunityListSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Community
        fields = [
            'id', 'name', 'description', 'created_by',
            'is_active', 'created_at', 'member_count',
        ]

    def get_created_by(self, obj):
        return {
            'id': str(obj.created_by.id),
            'email': obj.created_by.email,
        }

    def get_member_count(self, obj):
        return obj.members.filter(is_active=True).count()


class MemberDetailSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    added_by = serializers.SerializerMethodField()

    class Meta:
        model = CommunityMember
        fields = [
            'id', 'user', 'added_by', 'is_group_admin',
            'can_add_members', 'is_active', 'joined_at', 'updated_at',
        ]

    def get_user(self, obj):
        return {
            'id': str(obj.user.id),
            'email': obj.user.email,
            'base_role': obj.user.base_role,
        }

    def get_added_by(self, obj):
        if obj.added_by:
            return {
                'id': str(obj.added_by.id),
                'email': obj.added_by.email,
            }
        return None


class MemberAddSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField()

    def validate_operator_id(self, value):
        from accounts.models import CustomUser
        try:
            user = CustomUser.objects.get(id=value)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError('User not found.')
        if user.base_role != 'operator':
            raise serializers.ValidationError('Only operators can be added to communities.')
        if not user.is_active:
            raise serializers.ValidationError('Cannot add an inactive operator.')
        return value


class PermissionUpdateSerializer(serializers.Serializer):
    can_add_members = serializers.BooleanField()


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'community', 'sender', 'content', 'is_deleted', 'created_at']
        read_only_fields = ['id', 'community', 'sender', 'is_deleted', 'created_at']

    def get_sender(self, obj):
        return {
            'id': str(obj.sender.id),
            'email': obj.sender.email,
            'base_role': obj.sender.base_role,
        }

    def validate_content(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Message content cannot be empty.')
        if len(value) > 5000:
            raise serializers.ValidationError('Message content exceeds maximum length of 5000 characters.')
        return value.strip()
