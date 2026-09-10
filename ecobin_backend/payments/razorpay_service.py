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
    }
    if receipt:
        payload['receipt'] = receipt
    if notes:
        payload['notes'] = notes

    order = client.order.create(payload)
    return order


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
