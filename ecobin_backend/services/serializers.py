from rest_framework import serializers
from .models import ServiceRequest


class ServiceRequestCreateSerializer(serializers.Serializer):
    user_latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    user_longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    user_address = serializers.CharField(required=False, allow_blank=True, default='')
    service_type = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')


class ServiceRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True, default=None)
    operator_email = serializers.CharField(source='operator.email', read_only=True, default=None)
    operator_name = serializers.CharField(source='operator.username', read_only=True, default=None)
    technician_email = serializers.CharField(source='technician.email', read_only=True, default=None)
    technician_name = serializers.CharField(source='technician.username', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ServiceRequest
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'user_latitude', 'user_longitude', 'user_address',
            'operator', 'operator_email', 'operator_name',
            'operator_latitude', 'operator_longitude',
            'technician', 'technician_email', 'technician_name',
            'technician_latitude', 'technician_longitude',
            'status', 'status_display',
            'service_type', 'description', 'rejection_reason',
            'created_at', 'updated_at', 'accepted_at', 'arrived_at', 'completed_at',
        ]
        read_only_fields = [
            'id', 'user', 'operator', 'technician',
            'operator_latitude', 'operator_longitude',
            'technician_latitude', 'technician_longitude',
            'accepted_at', 'arrived_at', 'completed_at',
            'created_at', 'updated_at',
        ]


class ServiceRequestAcceptSerializer(serializers.Serializer):
    operator_latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    operator_longitude = serializers.DecimalField(max_digits=9, decimal_places=6)


class ServiceRequestRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')


class ServiceRequestAssignTechnicianSerializer(serializers.Serializer):
    technician_id = serializers.UUIDField()

    def validate_technician_id(self, value):
        from accounts.models import CustomUser
        try:
            tech = CustomUser.objects.get(id=value)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("Technician not found.")
        if tech.base_role != 'operator':
            raise serializers.ValidationError("User is not an operator/technician.")
        return value


class ServiceRequestTechnicianLocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
