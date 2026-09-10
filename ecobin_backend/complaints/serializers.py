from rest_framework import serializers
from .models import Complaint, ComplaintStatusHistory


class ComplaintCreateSerializer(serializers.Serializer):
    place = serializers.CharField(max_length=500)
    description = serializers.CharField(max_length=1000)
    image = serializers.ImageField(required=False, allow_null=True)

    def validate_place(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Place cannot be empty.")
        return value

    def validate_description(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Description cannot be empty.")
        return value

    def validate_image(self, value):
        if value is None:
            return value
        allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        if hasattr(value, 'content_type') and value.content_type not in allowed_types:
            raise serializers.ValidationError("Image must be JPEG, PNG, or WEBP.")
        max_size = 5 * 1024 * 1024  # 5MB
        if hasattr(value, 'size') and value.size > max_size:
            raise serializers.ValidationError("Image size must be less than 5MB.")
        return value


class ComplaintResponseSerializer(serializers.ModelSerializer):
    assigned_operator_email = serializers.CharField(
        source='assigned_operator.email', read_only=True, default=None
    )
    assigned_operator_name = serializers.CharField(
        source='assigned_operator.username', read_only=True, default=None
    )

    class Meta:
        model = Complaint
        fields = [
            'id', 'place', 'latitude', 'longitude', 'description', 'image',
            'status', 'assigned_operator', 'assigned_operator_email',
            'assigned_operator_name', 'created_at', 'updated_at',
            'assigned_at', 'resolved_at',
        ]
        read_only_fields = fields


class ComplaintListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = [
            'id', 'place', 'latitude', 'longitude', 'status',
            'assigned_operator', 'created_at', 'resolved_at',
        ]
        read_only_fields = fields


class ComplaintDetailSerializer(serializers.ModelSerializer):
    assigned_operator_email = serializers.CharField(
        source='assigned_operator.email', read_only=True, default=None
    )
    assigned_operator_name = serializers.CharField(
        source='assigned_operator.username', read_only=True, default=None
    )
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Complaint
        fields = [
            'id', 'user', 'user_email', 'place', 'latitude', 'longitude',
            'description', 'image', 'status',
            'assigned_operator', 'assigned_operator_email', 'assigned_operator_name',
            'created_at', 'updated_at', 'assigned_at', 'resolved_at',
        ]
        read_only_fields = fields


class AssignOperatorSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField()


class ComplaintStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['IN_PROGRESS', 'RESOLVED', 'REJECTED'])


class ComplaintStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.CharField(
        source='changed_by.email', read_only=True, default=None
    )

    class Meta:
        model = ComplaintStatusHistory
        fields = ['id', 'status', 'changed_by', 'changed_by_email', 'created_at']
        read_only_fields = fields
