import json
import smtplib
from email.mime.text import MIMEText
import os


def lambda_handler(event, context):
    email = event.get('email')
    otp_code = event.get('otp_code')

    if not email or not otp_code:
        return {
            'statusCode': 400,
            'body': json.dumps({'success': False, 'message': 'Missing email or otp_code'})
        }

    smtp_host = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('EMAIL_PORT', '587'))
    smtp_user = os.environ.get('EMAIL_HOST_USER', '')
    smtp_pass = os.environ.get('EMAIL_HOST_PASSWORD', '')
    use_tls = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'

    subject = 'EcoBin - Your Password Reset OTP'
    body = (
        f'Hello,\n\n'
        f'Your OTP for password reset is: {otp_code}\n\n'
        f'This code is valid for 5 minutes.\n'
        f'If you did not request a password reset, please ignore this email.\n\n'
        f'Regards,\nEcoBin Team'
    )

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = email

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [email], msg.as_string())

        return {
            'statusCode': 200,
            'body': json.dumps({'success': True, 'message': 'OTP email sent successfully'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'success': False, 'message': f'Failed to send email: {str(e)}'})
        }
