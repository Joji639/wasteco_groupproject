import uuid
import json
import logging
import io
import base64

import qrcode
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
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
    PaymentStatusResponseSerializer, OrderStatusResponseSerializer,
)
from .razorpay_service import (
    create_razorpay_order, verify_razorpay_signature,
    fetch_order, fetch_order_payments, capture_payment,
)
from pickups.models import PickupTracking
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

        pickup_request_id = serializer.validated_data.get('pickup_request_id')
        scheduled_pickup_id = serializer.validated_data.get('scheduled_pickup_id')
        plastic_kg = serializer.validated_data['plastic_kg']
        e_waste_kg = serializer.validated_data['e_waste_kg']
        payment_method = serializer.validated_data['payment_method']
        resident_name = serializer.validated_data.get('resident_name', '')
        resident_email = serializer.validated_data.get('resident_email', '')
        resident_phone = serializer.validated_data.get('resident_phone', '')

        if plastic_kg == 0 and e_waste_kg == 0:
            return Response(
                {"success": False, "message": "At least one waste type (plastic or e-waste) must have a quantity greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # On-demand pickup flow (requires tracking)
        if pickup_request_id:
            try:
                pickup = PickupRequest.objects.get(
                    id=pickup_request_id,
                    assigned_operator=request.user,
                )
            except PickupRequest.DoesNotExist:
                return Response(
                    {"success": False, "message": "Pickup not found or not assigned to you."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            
            try:
                tracking = PickupTracking.objects.get(
                    pickup_request=pickup,
                    operator=request.user,
                    status='ARRIVED',
                )
            except PickupTracking.DoesNotExist:
                return Response(
                    {"success": False, "message": "You must arrive at the location first. Start tracking and arrive before recording collection."},
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
                    resident_name=resident_name or pickup.user.get_full_name() or pickup.user.email,
                    resident_email=resident_email or pickup.user.email,
                    resident_phone=resident_phone,
                    plastic_kg=plastic_kg,
                    e_waste_kg=e_waste_kg,
                    payment_method=payment_method,
                    status='PENDING',
                )

                tracking.status = 'COMPLETED'
                tracking.completed_at = timezone.now()
                tracking.save(update_fields=['status', 'completed_at', 'updated_at'])

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

        # Scheduled pickup flow (no tracking needed)
        if scheduled_pickup_id:
            from pickups.models import ScheduledPickup
            try:
                scheduled = ScheduledPickup.objects.get(id=scheduled_pickup_id)
            except ScheduledPickup.DoesNotExist:
                return Response(
                    {"success": False, "message": "Scheduled pickup not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if WasteCollection.objects.filter(scheduled_pickup=scheduled).exists():
                return Response(
                    {"success": False, "message": "Collection already recorded for this scheduled pickup."},
                    status=status.HTTP_409_CONFLICT,
                )

            with transaction.atomic():
                collection = WasteCollection.objects.create(
                    scheduled_pickup=scheduled,
                    operator=request.user,
                    resident_name=resident_name,
                    resident_email=resident_email,
                    resident_phone=resident_phone,
                    plastic_kg=plastic_kg,
                    e_waste_kg=e_waste_kg,
                    payment_method=payment_method,
                    status='PENDING',
                )

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


def _make_qr_data_url(data):
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


class OperatorInitiatePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsOperatorRole]
    serializer_class = RazorpayCheckoutResponseSerializer

    @extend_schema(
        tags=['Operators'],
        responses={201: RazorpayCheckoutResponseSerializer}
    )
    def post(self, request, collection_id):
        try:
            collection = WasteCollection.objects.select_related('pickup_request', 'scheduled_pickup').get(
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

        notes = {'collection_id': str(collection.id)}
        if collection.pickup_request_id:
            notes['pickup_id'] = str(collection.pickup_request_id)
        elif collection.scheduled_pickup_id:
            notes['scheduled_pickup_id'] = str(collection.scheduled_pickup_id)

        try:
            order = create_razorpay_order(
                amount_paise=amount_paise,
                currency='INR',
                receipt=receipt,
                notes=notes,
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

        import base64
        qr_data = {
            'order_id': order['id'],
            'amount': str(collection.total_amount),
            'currency': 'INR',
            'key_id': settings.RAZORPAY_KEY_ID,
        }
        qr_payload = json.dumps(qr_data)
        qr_b64 = base64.b64encode(qr_payload.encode()).decode()

        if collection.pickup_request_id:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            try:
                channel_layer = get_channel_layer()
                room_group = f'pickup_tracking_{collection.pickup_request_id}'
                async_to_sync(channel_layer.group_send)(
                    room_group,
                    {
                        'type': 'status_update',
                        'payload': {
                            'type': 'status_change',
                            'status': 'PAYMENT_PENDING',
                            'message': 'Waste collected. Payment is pending.',
                            'collection_data': {
                                'collection_id': str(collection.id),
                                'plastic_kg': str(collection.plastic_kg),
                                'e_waste_kg': str(collection.e_waste_kg),
                                'total_amount': str(collection.total_amount),
                            },
                            'payment_data': {
                                'order_id': order['id'],
                                'amount': str(collection.total_amount),
                                'currency': 'INR',
                                'key_id': settings.RAZORPAY_KEY_ID,
                                'checkout_url': f"https://checkout.razorpay.com/v1/checkout.js#order_id={order['id']}",
                            },
                        },
                    },
                )
            except Exception:
                pass

        response_data = {
            "order_id": order['id'],
            "amount": str(collection.total_amount),
            "currency": "INR",
            "key_id": settings.RAZORPAY_KEY_ID,
            "receipt": receipt,
            "collection_id": str(collection.id),
            "checkout_url": f"https://checkout.razorpay.com/v1/checkout.js#order_id={order['id']}",
            "qr_payload": qr_b64,
        }
        checkout_page_path = reverse('payment-checkout-page', args=[order['id']])
        checkout_page_url = request.build_absolute_uri(checkout_page_path)
        response_data["checkout_page_url"] = checkout_page_url
        try:
            response_data["qr_image"] = _make_qr_data_url(checkout_page_url)
        except Exception as e:
            logger.warning("QR generation failed: %s", e)
            response_data["qr_image"] = None
        if collection.pickup_request_id:
            response_data["pickup_request_id"] = str(collection.pickup_request_id)
        elif collection.scheduled_pickup_id:
            response_data["scheduled_pickup_id"] = str(collection.scheduled_pickup_id)

        return Response(
            {
                "success": True,
                "message": "Payment order created. Display the QR or open the checkout URL.",
                "data": response_data,
            },
            status=status.HTTP_201_CREATED,
        )


def _finalize_paid_payment(payment, razorpay_payment_id=''):
    with transaction.atomic():
        payment.payment_status = 'CAPTURED'
        if razorpay_payment_id:
            payment.razorpay_payment_id = razorpay_payment_id
        payment.save(update_fields=['payment_status', 'razorpay_payment_id', 'updated_at'])

        collection = payment.collection
        collection.status = 'PAID'
        collection.save(update_fields=['status', 'updated_at'])

        pickup = collection.pickup_request
        if pickup:
            pickup.status = 'COMPLETED'
            pickup.save(update_fields=['status', 'updated_at'])
            PickupTracking.objects.filter(
                pickup_request=pickup,
                status__in=('COMPLETED', 'COLLECTING'),
            ).update(status='PAID')


def sync_payment_with_razorpay(payment):
    """
    Webhook-free payment confirmation: ask Razorpay whether this order has
    been paid (or capture an authorized test payment) and update local
    records accordingly. Returns True if records were updated to PAID.
    """
    if payment.payment_status == 'CAPTURED' or not payment.razorpay_order_id:
        return False

    try:
        order = fetch_order(payment.razorpay_order_id)
        amount = int(order.get('amount') or 0)
        amount_paid = int(order.get('amount_paid') or 0)
        order_paid = order.get('status') == 'paid' or (amount > 0 and amount_paid >= amount)

        items = []
        try:
            items = (fetch_order_payments(payment.razorpay_order_id) or {}).get('items', [])
        except Exception as exc:
            logger.warning("Could not list payments for order %s: %s", payment.razorpay_order_id, exc)

        for p in items:
            if p.get('status') == 'captured':
                _finalize_paid_payment(payment, p.get('id', ''))
                return True

        if order_paid:
            payment_ref = items[0].get('id', '') if items else ''
            _finalize_paid_payment(payment, payment_ref)
            return True

        for p in items:
            if p.get('status') == 'authorized':
                try:
                    capture_payment(p['id'], amount or int(payment.amount * 100))
                except Exception as exc:
                    logger.warning("Capture failed for payment %s: %s", p.get('id'), exc)
                    continue
                _finalize_paid_payment(payment, p.get('id', ''))
                return True
    except Exception as exc:
        logger.warning("Razorpay sync failed for order %s: %s", payment.razorpay_order_id, exc)

    return False


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
                {
                    "success": True,
                    "data": {
                        "collection_id": str(collection.id),
                        "pickup_request_id": str(pickup.id),
                        "plastic_kg": str(collection.plastic_kg),
                        "e_waste_kg": str(collection.e_waste_kg),
                        "total_amount": str(collection.total_amount),
                        "payment_status": "NOT_INITIATED",
                        "pickup_status": pickup.status,
                    },
                },
                status=status.HTTP_200_OK,
            )

        checkout_url = None
        if payment.payment_status in ('PENDING', 'CREATED'):
            checkout_url = f"https://checkout.razorpay.com/v1/checkout.js#order_id={payment.razorpay_order_id}"
            sync_payment_with_razorpay(payment)
            payment.refresh_from_db()
            collection.refresh_from_db()
            if collection.pickup_request_id:
                pickup.refresh_from_db()
            if payment.payment_status == 'CAPTURED':
                checkout_url = None

        data = {
            'payment_id': str(payment.id),
            'collection_id': str(collection.id),
            'pickup_request_id': str(pickup.id),
            'plastic_kg': str(collection.plastic_kg),
            'e_waste_kg': str(collection.e_waste_kg),
            'total_amount': str(collection.total_amount),
            'amount': str(payment.amount),
            'currency': payment.currency,
            'payment_method': payment.payment_method,
            'payment_status': payment.payment_status,
            'razorpay_order_id': payment.razorpay_order_id,
            'razorpay_payment_id': payment.razorpay_payment_id,
            'checkout_url': checkout_url,
            'pickup_status': pickup.status,
            'created_at': payment.created_at,
        }

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )


class UserPickupPaymentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Payments'],
        responses={200: None}
    )
    def get(self, request):
        collections = WasteCollection.objects.filter(
            pickup_request__user=request.user,
        ).select_related('pickup_request', 'payment').order_by('-created_at')

        data = []
        for c in collections:
            payment_data = None
            if hasattr(c, 'payment'):
                payment_data = {
                    'payment_id': str(c.payment.id),
                    'amount': str(c.payment.amount),
                    'payment_status': c.payment.payment_status,
                    'razorpay_order_id': c.payment.razorpay_order_id,
                }

            data.append({
                'collection_id': str(c.id),
                'pickup_request_id': str(c.pickup_request_id),
                'plastic_kg': str(c.plastic_kg),
                'e_waste_kg': str(c.e_waste_kg),
                'total_amount': str(c.total_amount),
                'collection_status': c.status,
                'payment': payment_data,
                'created_at': c.created_at.isoformat(),
            })

        return Response(
            {"success": True, "count": len(data), "data": data},
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

            pickup = collection.pickup_request
            pickup.status = 'COMPLETED'
            pickup.save(update_fields=['status', 'updated_at'])

            from pickups.models import PickupTracking
            PickupTracking.objects.filter(
                pickup_request=pickup,
                status__in=('COMPLETED', 'COLLECTING'),
            ).update(status='PAID')

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


class RazorpayOrderStatusView(APIView):
    """
    Public (order-id-gated) status check used by the hosted checkout page.
    Syncs local records from Razorpay so payment completion works without
    a webhook.
    """
    authentication_classes = []
    permission_classes = []
    serializer_class = OrderStatusResponseSerializer

    @extend_schema(tags=['User - Payments'])
    def get(self, request, razorpay_order_id):
        payment = Payment.objects.select_related(
            'collection', 'collection__pickup_request',
        ).filter(razorpay_order_id=razorpay_order_id).first()
        if payment is None:
            return Response(
                {"success": False, "message": "Payment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        sync_payment_with_razorpay(payment)
        payment.refresh_from_db()
        collection = payment.collection

        return Response(
            {
                "success": True,
                "data": {
                    "paid": payment.payment_status == 'CAPTURED',
                    "payment_status": payment.payment_status,
                    "collection_status": collection.status,
                    "pickup_status": collection.pickup_request.status if collection.pickup_request_id else None,
                    "amount": str(payment.amount),
                },
            },
            status=status.HTTP_200_OK,
        )


_CHECKOUT_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EcoBin Secure Payment</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f4f6f8; margin:0; display:flex; justify-content:center; align-items:center; min-height:100vh; }
  .card { background:#fff; border-radius:14px; box-shadow:0 4px 18px rgba(0,0,0,.12); padding:32px 28px; width:100%; max-width:400px; text-align:center; }
  .brand { color:#16a34a; font-weight:700; font-size:20px; margin-bottom:4px; }
  h1 { font-size:18px; margin:8px 0 2px; }
  .amount { font-size:32px; font-weight:700; margin:12px 0; }
  #status { min-height:22px; font-size:14px; color:#555; margin:10px 0; }
  #status.ok { color:#16a34a; font-weight:600; }
  #status.err { color:#dc2626; }
  button { width:100%; padding:13px; border:0; border-radius:9px; background:#16a34a; color:#fff; font-size:16px; font-weight:600; cursor:pointer; margin-top:8px; }
  button:disabled { background:#9ca3af; }
  .test { font-size:12px; color:#9ca3af; margin-top:14px; }
</style>
</head>
<body>
<div class="card">
  <div class="brand">EcoBin</div>
  <h1>Waste Collection Payment</h1>
  <div class="amount">&#8377;__AMOUNT__</div>
  <div id="status">Preparing checkout...</div>
  <button id="pay" disabled>Pay Now</button>
  <div class="test">Test mode &mdash; no real money is charged.</div>
</div>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
  var KEY = "__KEY__";
  var ORDER = "__ORDER_ID__";
  var AMOUNT = __AMOUNT_PAISE__;
  var statusEl = document.getElementById('status');
  var payBtn = document.getElementById('pay');
  var polling = null;
  var opened = false;

  function setStatus(text, cls) { statusEl.textContent = text; statusEl.className = cls || ''; }

  function showPaid() {
    if (polling) clearInterval(polling);
    setStatus('Payment successful! You can close this page.', 'ok');
    payBtn.disabled = true;
    payBtn.textContent = 'Paid';
  }

  function poll() {
    if (statusEl.className === 'err') return;
    fetch('/payments/order/' + ORDER + '/status/')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.success && j.data && j.data.paid) { showPaid(); }
        else if (j.success && j.data) { setStatus('Waiting for payment... (status: ' + j.data.payment_status + ')'); }
      })
      .catch(function () {});
  }

  function openCheckout() {
    if (opened) return;
    opened = true;
    try {
      var rzp = new Razorpay({
        key: KEY,
        amount: AMOUNT,
        currency: 'INR',
        order_id: ORDER,
        name: 'EcoBin',
        description: 'Waste collection payment',
        theme: { color: '#16a34a' },
        handler: function () { setStatus('Payment submitted, confirming...'); poll(); },
        modal: { ondismiss: function () { opened = false; setStatus('Checkout closed. Tap Pay Now to retry.'); payBtn.disabled = false; } }
      });
      rzp.on('payment.failed', function () { opened = false; setStatus('Payment failed. Please try again.', 'err'); payBtn.disabled = false; });
      rzp.open();
      setStatus('Complete the payment in the checkout window (test mode).');
    } catch (e) {
      opened = false;
      setStatus('Could not open checkout automatically. Tap Pay Now.', 'err');
      payBtn.disabled = false;
    }
  }

  payBtn.addEventListener('click', openCheckout);
  polling = setInterval(poll, 2000);
  poll();
  setTimeout(openCheckout, 300);
</script>
</body>
</html>
"""


def checkout_page(request, razorpay_order_id):
    payment = Payment.objects.select_related('collection').filter(
        razorpay_order_id=razorpay_order_id,
    ).first()
    if payment is None:
        return HttpResponse("<h3>Invalid or expired payment link.</h3>", status=404, content_type='text/html')

    sync_payment_with_razorpay(payment)
    payment.refresh_from_db()
    if payment.payment_status == 'CAPTURED':
        return HttpResponse(
            "<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>EcoBin Payment</title></head>"
            "<body style=\"font-family:sans-serif;text-align:center;padding:60px 20px;\">"
            "<h2 style='color:#16a34a;'>&#10003; Payment successful</h2>"
            f"<p>Amount: &#8377;{payment.amount}</p>"
            "<p>You can close this page.</p></body></html>",
            content_type='text/html',
        )

    html = (
        _CHECKOUT_PAGE_HTML
        .replace('__AMOUNT__', str(payment.amount))
        .replace('__KEY__', settings.RAZORPAY_KEY_ID)
        .replace('__ORDER_ID__', razorpay_order_id)
        .replace('__AMOUNT_PAISE__', str(int(payment.amount * 100)))
    )
    return HttpResponse(html, content_type='text/html')
