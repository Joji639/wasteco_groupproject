from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from .models import PickupRequest, OperatorReview, ScheduledPickup, Area, AreaAssignment, CollectionRecord, PickupTracking
from .geocoding import geocode_place


class PickupRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    image = serializers.ImageField(required=False, allow_null=True)

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
    operator_id = serializers.CharField(max_length=20, required=True)

    def validate_operator_id(self, value):
        from accounts.models import OperatorProfile
        value = value.strip().upper()
        try:
            profile = OperatorProfile.objects.select_related('user').get(operator_id=value)
        except OperatorProfile.DoesNotExist:
            raise serializers.ValidationError("Operator not found.")
        if not profile.user.is_active:
            raise serializers.ValidationError("The selected operator is not active.")
        if not profile.is_verified:
            raise serializers.ValidationError("The selected operator is not verified.")
        return profile.user


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


# ---------------------------------------------------------------------------
# Scheduled Pickup Serializers
# ---------------------------------------------------------------------------

class ScheduledPickupCreateSerializer(serializers.Serializer):
    scheduled_date = serializers.DateField()

    def validate_scheduled_date(self, value):
        from django.utils import timezone
        if value < timezone.now().date():
            raise serializers.ValidationError("Scheduled date cannot be in the past.")
        return value


class ScheduledPickupUpdateSerializer(serializers.Serializer):
    scheduled_date = serializers.DateField(required=True)

    def validate_scheduled_date(self, value):
        from django.utils import timezone
        if value < timezone.now().date():
            raise serializers.ValidationError("Scheduled date cannot be in the past.")
        return value


class ScheduledPickupSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)

    class Meta:
        model = ScheduledPickup
        fields = ['id', 'scheduled_date', 'created_by', 'created_by_email', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


# ---------------------------------------------------------------------------
# Area Assignment Serializers
# ---------------------------------------------------------------------------

class AreaCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    panchayath = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Area name cannot be empty.")
        return value


class AreaSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(source='created_by.email', read_only=True, default=None)
    assigned_operators_count = serializers.SerializerMethodField()

    class Meta:
        model = Area
        fields = ['id', 'name', 'panchayath', 'description', 'created_by', 'created_by_email', 'assigned_operators_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_assigned_operators_count(self, obj):
        return obj.assignments.count()


class AreaAssignmentCreateSerializer(serializers.Serializer):
    operator_id = serializers.CharField(max_length=20)

    def validate_operator_id(self, value):
        from accounts.models import OperatorProfile
        value = value.strip().upper()
        try:
            profile = OperatorProfile.objects.select_related('user').get(operator_id=value)
        except OperatorProfile.DoesNotExist:
            raise serializers.ValidationError("Operator not found.")
        if not profile.user.is_active:
            raise serializers.ValidationError("The selected operator is not active.")
        if not profile.is_verified:
            raise serializers.ValidationError("The selected operator is not verified.")
        return profile.user


class AreaAssignmentSerializer(serializers.ModelSerializer):
    operator_email = serializers.CharField(source='operator.email', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True, default=None)
    area_name = serializers.CharField(source='area.name', read_only=True)
    assigned_by_email = serializers.CharField(source='assigned_by.email', read_only=True, default=None)

    class Meta:
        model = AreaAssignment
        fields = ['id', 'area', 'area_name', 'operator', 'operator_email', 'operator_name', 'assigned_by', 'assigned_by_email', 'assigned_at']
        read_only_fields = ['id', 'assigned_by', 'assigned_at']


# ---------------------------------------------------------------------------
# Waste Collection Serializers
# ---------------------------------------------------------------------------

class WasteCollectionCreateSerializer(serializers.Serializer):
    resident_name = serializers.CharField(max_length=200)
    resident_email = serializers.EmailField(required=False, allow_blank=True, default='')
    resident_phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    house_address = serializers.CharField()
    waste_type = serializers.ChoiceField(choices=CollectionRecord.WASTE_TYPE_CHOICES)
    quantity_kg = serializers.DecimalField(max_digits=8, decimal_places=2, required=False, allow_null=True)

    def validate_resident_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Resident name cannot be empty.")
        return value

    def validate_house_address(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("House address cannot be empty.")
        return value


class WasteCollectionFailureSerializer(serializers.Serializer):
    resident_name = serializers.CharField(max_length=200)
    resident_email = serializers.EmailField(required=False, allow_blank=True, default='')
    resident_phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    house_address = serializers.CharField()
    failure_reason = serializers.CharField(max_length=500)

    def validate_failure_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Failure reason cannot be empty.")
        return value

    def validate_house_address(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("House address cannot be empty.")
        return value


class CollectionRecordSerializer(serializers.ModelSerializer):
    operator_email = serializers.CharField(source='operator.email', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True, default=None)
    area_name = serializers.CharField(source='area.name', read_only=True, default=None)
    waste_type_display = serializers.CharField(source='get_waste_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = CollectionRecord
        fields = [
            'id', 'operator', 'operator_email', 'operator_name', 'operator_id_display',
            'pickup_request', 'area', 'area_name',
            'resident_name', 'resident_email', 'resident_phone', 'house_address',
            'waste_type', 'waste_type_display', 'quantity_kg',
            'qr_code', 'status', 'status_display', 'failure_reason',
            'collected_at', 'updated_at',
        ]
        read_only_fields = ['id', 'operator', 'operator_id_display', 'qr_code', 'collected_at', 'updated_at']


class WasteCollectionReportSerializer(serializers.Serializer):
    operator_id = serializers.CharField()
    operator_name = serializers.CharField()
    operator_email = serializers.CharField()
    total_collections = serializers.IntegerField()
    total_failed = serializers.IntegerField()
    total_quantity_kg = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    waste_breakdown = serializers.DictField()
    collections = CollectionRecordSerializer(many=True)


# ---------------------------------------------------------------------------
# Pickup Tracking Serializers
# ---------------------------------------------------------------------------

class PickupTrackingStartSerializer(serializers.Serializer):
    pickup_request_id = serializers.UUIDField()
    start_location = serializers.CharField(max_length=500)

    def validate_pickup_request_id(self, value):
        try:
            pickup = PickupRequest.objects.get(id=value)
        except PickupRequest.DoesNotExist:
            raise serializers.ValidationError("Pickup request not found.")
        if pickup.status not in ('ASSIGNED', 'ON_THE_WAY'):
            raise serializers.ValidationError("Pickup must be assigned before starting tracking.")
        return value

    def validate(self, data):
        coords = geocode_place(data.get('start_location', ''))
        if coords is None:
            raise serializers.ValidationError({"start_location": "Could not find coordinates for this place."})
        data['start_latitude'] = coords[0]
        data['start_longitude'] = coords[1]
        return data


class PickupTrackingSerializer(serializers.ModelSerializer):
    operator_email = serializers.CharField(source='operator.email', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True, default=None)
    pickup_place = serializers.CharField(source='pickup_request.place', read_only=True, default=None)
    pickup_lat = serializers.DecimalField(source='pickup_request.latitude', max_digits=9, decimal_places=6, read_only=True)
    pickup_lng = serializers.DecimalField(source='pickup_request.longitude', max_digits=9, decimal_places=6, read_only=True)
    user_email = serializers.CharField(source='pickup_request.user.email', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PickupTracking
        fields = [
            'id', 'pickup_request', 'operator', 'operator_email', 'operator_name',
            'pickup_place', 'pickup_lat', 'pickup_lng', 'user_email',
            'start_place', 'start_latitude', 'start_longitude',
            'current_latitude', 'current_longitude',
            'total_distance_meters', 'total_duration_seconds',
            'status', 'status_display', 'progress',
            'started_at', 'arrived_at', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'operator', 'current_latitude', 'current_longitude',
            'total_distance_meters', 'total_duration_seconds',
            'progress', 'started_at', 'arrived_at', 'created_at', 'updated_at',
        ]


class PickupTrackingLocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
