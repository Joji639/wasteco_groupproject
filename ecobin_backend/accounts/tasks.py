import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_otp_task(self, email, otp_code):
    subject = 'EcoBin - Your Password Reset OTP'
    message = (
        f'Hello,\n\n'
        f'Your OTP for password reset is: {otp_code}\n\n'
        f'This code is valid for 5 minutes.\n'
        f'If you did not request a password reset, please ignore this email.\n\n'
        f'Regards,\nEcoBin Team'
    )
    try:
        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            [email],
            fail_silently=False,
        )
        logger.info(f"OTP email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {e}")
        raise self.retry(exc=e)
