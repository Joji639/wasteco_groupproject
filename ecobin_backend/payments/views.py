import uuid
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter

from accounts.models import CustomUser
from accounts.permissions import IsStaffRole, _in_group
from pickups.models import PickupRequest
from .models import WasteCollection, Payment
from .serializers import (
    WasteCollectionSerializer, CreateCollectionSerializer,
    PaymentSerializer, RazorpayCheckoutResponseSerializer,
    PaymentStatusResponseSerializer,
)
from .razorpay_service import create_razorpay_order, verify_razorpay_signature

logger = logging.getLogger(__name__)


class IsOperatorRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.base_role == 'operator'
        )


class OperatorAssignedPickupsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        parameters=[
            OpenApiParameter("status", str, enum=['ASSIGNED', 'ON_THE_WAY', 'COLLECTED', 'COMPLETED'], description="Filter by pickup status"),
        ],
        responses={200: None}
    )
    def get(self, request):
        queryset = PickupRequest.objects.filter(
            assigned_operator=request.user,
        ).select_related('user')

        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        else:
            queryset = queryset.filter(status__in=['ASSIGNED', 'ON_THE_WAY'])

        data = []
        for pickup in queryset:
            data.append({
                'pickup_id': str(pickup.id),
                'pickup_type': pickup.pickup_type,
                'user_email': pickup.user.email,
                'latitude': str(pickup.latitude),
                'longitude': str(pickup.longitude),
                'description': pickup.description,
                'status': pickup.status,
                'assigned_at': pickup.assigned_at.isoformat() if pickup.assigned_at else None,
            })

        return Response(
            {"success": True, "count": len(data), "data": data},
            status=status.HTTP_200_OK,
        )


class OperatorStartTaskView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(tags=['Operators'], responses={200: None})
    def patch(self, request, pickup_id):
        try:
            pickup = PickupRequest.objects.select_for_update().get(
                id=pickup_id,
                assigned_operator=request.user,
            )
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found or not assigned to you."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if pickup.status != 'ASSIGNED':
            return Response(
                {"success": False, "message": f"Cannot start task for pickup with status '{pickup.status}'. Only ASSIGNED pickups can be started."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            pickup.status = 'ON_THE_WAY'
            pickup.save(update_fields=['status', 'updated_at'])

        return Response(
            {"success": True, "message": "Task started. Status updated to ON_THE_WAY."},
            status=status.HTTP_200_OK,
        )


class OperatorRecordCollectionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        request=CreateCollectionSerializer,
        responses={201: WasteCollectionSerializer}
    )
    def post(self, request):
        serializer = CreateCollectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pickup_id = serializer.validated_data['pickup_request_id']
        plastic_kg = serializer.validated_data['plastic_kg']
        e_waste_kg = serializer.validated_data['e_waste_kg']
        payment_method = serializer.validated_data['payment_method']

        if plastic_kg == 0 and e_waste_kg == 0:
            return Response(
                {"success": False, "message": "At least one waste type (plastic or e-waste) must have a quantity greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pickup = PickupRequest.objects.get(
                id=pickup_id,
                assigned_operator=request.user,
            )
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found or not assigned to you."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if pickup.status not in ('ASSIGNED', 'ON_THE_WAY'):
            return Response(
                {"success": False, "message": f"Cannot record collection for pickup with status '{pickup.status}'."},
                status=status.HTTP_409_CONFLICT,
            )

        if WasteCollection.objects.filter(pickup_request=pickup).exists():
            return Response(
                {"success": False, "message": "Collection already recorded for this pickup."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            collection = WasteCollection.objects.create(
                pickup_request=pickup,
                operator=request.user,
                plastic_kg=plastic_kg,
                e_waste_kg=e_waste_kg,
                payment_method=payment_method,
                status='PENDING',
            )

            pickup.status = 'COLLECTED'
            pickup.save(update_fields=['status', 'updated_at'])

        result = WasteCollectionSerializer(collection).data
        return Response(
            {
                "success": True,
                "message": "Waste collection recorded successfully.",
                "data": result,
            },
            status=status.HTTP_201_CREATED,
        )


class OperatorCollectionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: WasteCollectionSerializer(many=True)}
    )
    def get(self, request):
        collections = WasteCollection.objects.filter(
            operator=request.user,
        ).select_related('pickup_request')

        data = WasteCollectionSerializer(collections, many=True).data
        return Response(
            {"success": True, "count": len(data), "data": data},
            status=status.HTTP_200_OK,
        )


class OperatorCollectionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: WasteCollectionSerializer}
    )
    def get(self, request, collection_id):
        try:
            collection = WasteCollection.objects.select_related('pickup_request').get(
                id=collection_id,
                operator=request.user,
            )
        except WasteCollection.DoesNotExist:
            return Response(
                {"success": False, "message": "Collection not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = WasteCollectionSerializer(collection).data
        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )


class OperatorInitiatePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]

    @extend_schema(
        tags=['Operators'],
        responses={201: RazorpayCheckoutResponseSerializer}
    )
    def post(self, request, collection_id):
        try:
            collection = WasteCollection.objects.select_related('pickup_request').get(
                id=collection_id,
                operator=request.user,
            )
        except WasteCollection.DoesNotExist:
            return Response(
                {"success": False, "message": "Collection not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if collection.payment_method != 'ONLINE':
            return Response(
                {"success": False, "message": "This collection is not marked for online payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if collection.status == 'PAID':
            return Response(
                {"success": False, "message": "This collection is already paid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_paise = int(collection.total_amount * 100)
        receipt = f"ecobin_{collection.id.hex[:12]}"

        try:
            order = create_razorpay_order(
                amount_paise=amount_paise,
                receipt=receipt,
                notes={
                    'collection_id': str(collection.id),
                    'pickup_id': str(collection.pickup_request_id),
                },
            )
        except Exception as e:
            logger.error("Razorpay order creation failed: %s", e)
            return Response(
                {"success": False, "message": "Failed to create payment order. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            payment, created = Payment.objects.update_or_create(
                collection=collection,
                defaults={
                    'amount': collection.total_amount,
                    'currency': 'INR',
                    'payment_method': 'ONLINE',
                    'payment_status': 'CREATED',
                    'razorpay_order_id': order['id'],
                    'receipt': receipt,
                },
            )
            collection.status = 'AMOUNT_DUE'
            collection.save(update_fields=['status', 'updated_at'])

        checkout_url = f"https://checkout.razorpay.com/v1/checkout.js#order_id={order['id']}"

        return Response(
            {
                "success": True,
                "message": "Payment order created. Display the QR or open the checkout URL.",
                "data": {
                    "order_id": order['id'],
                    "amount": str(collection.total_amount),
                    "currency": "INR",
                    "key_id": settings.RAZORPAY_KEY_ID,
                    "receipt": receipt,
                    "collection_id": str(collection.id),
                    "pickup_request_id": str(collection.pickup_request_id),
                    "checkout_url": checkout_url,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Payments'],
        responses={200: PaymentStatusResponseSerializer}
    )
    def get(self, request, pickup_id):
        try:
            pickup = PickupRequest.objects.get(id=pickup_id, user=request.user)
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            collection = WasteCollection.objects.get(pickup_request=pickup)
        except WasteCollection.DoesNotExist:
            return Response(
                {"success": False, "message": "No waste collection recorded for this pickup."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            payment = Payment.objects.get(collection=collection)
        except Payment.DoesNotExist:
            return Response(
                {"success": False, "message": "No payment initiated for this collection."},
                status=status.HTTP_404_NOT_FOUND,
            )

        checkout_url = None
        if payment.payment_status in ('PENDING', 'CREATED'):
            checkout_url = f"https://checkout.razorpay.com/v1/checkout.js#order_id={payment.razorpay_order_id}"

        data = {
            'payment_id': payment.id,
            'collection_id': collection.id,
            'pickup_request_id': pickup.id,
            'amount': payment.amount,
            'currency': payment.currency,
            'payment_method': payment.payment_method,
            'payment_status': payment.payment_status,
            'razorpay_order_id': payment.razorpay_order_id,
            'razorpay_payment_id': payment.razorpay_payment_id,
            'checkout_url': checkout_url,
            'created_at': payment.created_at,
        }

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    webhook_secret = settings.RAZORPAY_KEY_SECRET

    signature = request.headers.get('X-Razorpay-Signature', '')
    body = request.body

    if not verify_razorpay_signature(body, signature, webhook_secret):
        logger.warning("Invalid Razorpay webhook signature")
        return JsonResponse({"status": "error", "message": "Invalid signature"}, status=400)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    event = payload.get('event', '')
    entity = payload.get('payload', {}).get('payment', {}).get('entity', {})

    if event == 'payment.captured':
        razorpay_order_id = entity.get('order_id', '')
        razorpay_payment_id = entity.get('id', '')
        razorpay_signature = entity.get('signature', '')

        try:
            payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
        except Payment.DoesNotExist:
            logger.warning("Payment not found for order_id: %s", razorpay_order_id)
            return JsonResponse({"status": "ok"}, status=200)

        with transaction.atomic():
            payment.payment_status = 'CAPTURED'
            payment.razorpay_payment_id = razorpay_payment_id
            payment.razorpay_signature = razorpay_signature
            payment.save(update_fields=['payment_status', 'razorpay_payment_id', 'razorpay_signature', 'updated_at'])

            collection = payment.collection
            collection.status = 'PAID'
            collection.save(update_fields=['status', 'updated_at'])

        logger.info("Payment captured: %s", razorpay_payment_id)

    elif event == 'payment.failed':
        razorpay_order_id = entity.get('order_id', '')
        try:
            payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
            payment.payment_status = 'FAILED'
            payment.save(update_fields=['payment_status', 'updated_at'])
        except Payment.DoesNotExist:
            pass

        logger.warning("Payment failed for order_id: %s", razorpay_order_id)

    return JsonResponse({"status": "ok"}, status=200)
