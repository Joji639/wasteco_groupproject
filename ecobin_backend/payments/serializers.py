from rest_framework import serializers
from .models import WasteCollection, Payment


class WasteCollectionSerializer(serializers.ModelSerializer):
    pickup_request_id = serializers.UUIDField(source='pickup_request.id', read_only=True)
    operator_email = serializers.EmailField(source='operator.email', read_only=True)

    class Meta:
        model = WasteCollection
        fields = [
            'id', 'pickup_request_id', 'operator_email',
            'plastic_kg', 'e_waste_kg',
            'plastic_rate', 'e_waste_rate',
            'plastic_amount', 'e_waste_amount', 'total_amount',
            'payment_method', 'status', 'created_at',
        ]
        read_only_fields = [
            'id', 'plastic_rate', 'e_waste_rate',
            'plastic_amount', 'e_waste_amount', 'total_amount',
            'status', 'created_at',
        ]


class CreateCollectionSerializer(serializers.Serializer):
    pickup_request_id = serializers.UUIDField()
    plastic_kg = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    e_waste_kg = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    payment_method = serializers.ChoiceField(choices=['CASH', 'ONLINE'])


class PaymentSerializer(serializers.ModelSerializer):
    collection_id = serializers.UUIDField(source='collection.id', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'collection_id', 'amount', 'currency',
            'payment_method', 'payment_status',
            'razorpay_order_id', 'razorpay_payment_id',
            'receipt', 'notes', 'created_at',
        ]
        read_only_fields = [
            'id', 'razorpay_order_id', 'razorpay_payment_id',
            'razorpay_signature', 'receipt', 'created_at',
        ]


class RazorpayCheckoutResponseSerializer(serializers.Serializer):
    order_id = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField()
    key_id = serializers.CharField()
    receipt = serializers.CharField()
    collection_id = serializers.UUIDField()
    pickup_request_id = serializers.UUIDField()


class PaymentStatusResponseSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    collection_id = serializers.UUIDField()
    pickup_request_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField()
    payment_method = serializers.CharField()
    payment_status = serializers.CharField()
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    checkout_url = serializers.URLField(required=False)
    created_at = serializers.DateTimeField()
