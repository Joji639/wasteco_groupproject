from rest_framework import serializers
from .models import (
    WastePickupRequest, PickupSchedule, Review,
    Payment, WasteCollection, Complaint,
)


class WastePickupRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = WastePickupRequest
        fields = [
            'id', 'user', 'user_email', 'complaint_type', 'image',
            'description', 'location', 'status', 'assigned_operator',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'status', 'assigned_operator', 'created_at', 'updated_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class PickupScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PickupSchedule
        fields = ['id', 'user', 'scheduled_date', 'is_active', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']


class ReviewSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'user', 'user_email', 'waste_request', 'rating', 'review_text', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class PaymentSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'user', 'user_email', 'waste_request', 'amount',
            'status', 'payment_method', 'transaction_id', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class WasteCollectionSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = WasteCollection
        fields = [
            'id', 'user', 'user_email', 'waste_request', 'waste_type',
            'date', 'time', 'status', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class ComplaintSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Complaint
        fields = [
            'id', 'user', 'user_email', 'waste_request', 'subject',
            'description', 'status', 'response', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'response', 'created_at', 'updated_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
