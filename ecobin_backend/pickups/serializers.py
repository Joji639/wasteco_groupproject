from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from .models import PickupRequest, OperatorReview
from .geocoding import geocode_place


class PickupRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    class Meta:
        model = PickupRequest
        fields = [
            'id', 'user', 'user_email', 'pickup_type', 'place',
            'latitude', 'longitude', 'description', 'image', 'status',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'pickup_type', 'status', 'created_at', 'updated_at']

    def validate_place(self, value):
        if value is not None:
            value = value.strip()
            if not value:
                return None
        return value

    def validate_latitude(self, value):
        if value is not None and value != '':
            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError("Latitude must be a number.")
            if value < -90 or value > 90:
                raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if value is not None and value != '':
            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError("Longitude must be a number.")
            if value < -180 or value > 180:
                raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value

    def validate_description(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Description cannot be empty.")
        if len(value) > 1000:
            raise serializers.ValidationError("Description must be 1000 characters or less.")
        return value

    def validate(self, data):
        place = data.get('place')
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        # If place is provided but lat/lng are missing, geocode
        if place and (latitude is None or longitude is None):
            coords = geocode_place(place)
            if coords is None:
                raise serializers.ValidationError(
                    {"place": "Could not find coordinates for this place. Please provide latitude and longitude, or try a more specific address."}
                )
            data['latitude'] = coords[0]
            data['longitude'] = coords[1]
        elif place and latitude is not None and longitude is not None:
            # Both provided — geocode from place and override
            coords = geocode_place(place)
            if coords is not None:
                data['latitude'] = coords[0]
                data['longitude'] = coords[1]
        elif not place and (latitude is None or longitude is None):
            raise serializers.ValidationError(
                "Either 'place' (text address) or both 'latitude' and 'longitude' are required."
            )

        return data

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        validated_data['pickup_type'] = 'ON_DEMAND'
        validated_data['status'] = 'PENDING'
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# Operator Admin Serializers
# ---------------------------------------------------------------------------

class OperatorAdminPickupListSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    assigned_operator_email = serializers.CharField(
        source='assigned_operator.email', read_only=True, default=None
    )
    assigned_operator_name = serializers.CharField(
        source='assigned_operator.username', read_only=True, default=None
    )

    class Meta:
        model = PickupRequest
        fields = [
            'id', 'user', 'user_email', 'user_username', 'pickup_type',
            'place', 'latitude', 'longitude', 'description', 'image', 'status',
            'rejection_reason', 'assigned_operator', 'assigned_operator_email',
            'assigned_operator_name', 'created_at', 'updated_at',
        ]


class OperatorAdminPickupDetailSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    accepted_by_email = serializers.CharField(
        source='accepted_by.email', read_only=True, default=None
    )
    rejected_by_email = serializers.CharField(
        source='rejected_by.email', read_only=True, default=None
    )
    assigned_operator_email = serializers.CharField(
        source='assigned_operator.email', read_only=True, default=None
    )
    assigned_operator_name = serializers.CharField(
        source='assigned_operator.username', read_only=True, default=None
    )
    assigned_by_email = serializers.CharField(
        source='assigned_by.email', read_only=True, default=None
    )

    class Meta:
        model = PickupRequest
        fields = [
            'id', 'user', 'user_email', 'user_username', 'pickup_type',
            'place', 'latitude', 'longitude', 'description', 'image', 'status',
            'accepted_by', 'accepted_by_email', 'accepted_at',
            'rejected_by', 'rejected_by_email', 'rejected_at', 'rejection_reason',
            'assigned_operator', 'assigned_operator_email', 'assigned_operator_name',
            'assigned_by', 'assigned_by_email', 'assigned_at',
            'created_at', 'updated_at',
        ]


class RejectPickupSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=True)

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Rejection reason cannot be empty.")
        return value


class AssignOperatorSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField(required=True)


# ---------------------------------------------------------------------------
# Operator Review Serializers
# ---------------------------------------------------------------------------

class OperatorReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)


class OperatorReviewResponseSerializer(serializers.ModelSerializer):
    pickup_request_id = serializers.UUIDField(source='pickup_request.id', read_only=True)
    operator_id = serializers.UUIDField(source='operator.id', read_only=True)

    class Meta:
        model = OperatorReview
        fields = ['id', 'pickup_request_id', 'operator_id', 'rating', 'comment', 'created_at']
        read_only_fields = fields


class OperatorReviewListSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperatorReview
        fields = ['id', 'rating', 'comment', 'created_at']
        read_only_fields = fields


class OperatorRatingSummarySerializer(serializers.Serializer):
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=1, allow_null=True)
    total_reviews = serializers.IntegerField()
    rating_distribution = serializers.DictField(child=serializers.IntegerField())


class OperatorAdminRatingSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField()
    operator_name = serializers.CharField()
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=1, allow_null=True)
    total_reviews = serializers.IntegerField()


class OperatorAdminOperatorReviewsSerializer(serializers.Serializer):
    operator_id = serializers.UUIDField()
    operator_name = serializers.CharField()
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=1, allow_null=True)
    total_reviews = serializers.IntegerField()
    rating_distribution = serializers.DictField(child=serializers.IntegerField())
    reviews = OperatorReviewListSerializer(many=True)
