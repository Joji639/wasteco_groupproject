import hashlib
import hmac
import json
import logging
import razorpay
from django.conf import settings

logger = logging.getLogger(__name__)


def get_razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


def create_razorpay_order(amount_paise, currency='INR', receipt=None, notes=None):
    client = get_razorpay_client()
    payload = {
        'amount': int(amount_paise),
        'currency': currency,
        'payment_capture': 1,
    }
    if receipt:
        payload['receipt'] = receipt
    if notes:
        payload['notes'] = notes

    order = client.order.create(payload)
    return order


def fetch_order(order_id):
    client = get_razorpay_client()
    return client.order.fetch(order_id)


def fetch_order_payments(order_id):
    client = get_razorpay_client()
    return client.payment.fetch_all({'order_id': order_id})


def capture_payment(payment_id, amount_paise):
    client = get_razorpay_client()
    return client.payment.capture(payment_id, int(amount_paise))


def verify_razorpay_signature(body, signature, secret=None):
    if secret is None:
        secret = settings.RAZORPAY_KEY_SECRET
    try:
        generated_signature = hmac.new(
            secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(generated_signature, signature)
    except Exception as e:
        logger.error("Signature verification failed: %s", e)
        return False
