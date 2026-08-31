import json
import boto3
import logging

logger = logging.getLogger(__name__)

lambda_client = boto3.client('lambda', region_name='ap-south-1')


def send_email_otp_task(email, otp_code):
    try:
        payload = json.dumps({'email': email, 'otp_code': otp_code})
        response = lambda_client.invoke(
            FunctionName='ecobin-send-otp',
            InvocationType='Event',
            Payload=payload,
        )
        logger.info(f"Lambda invoked for {email}, status: {response['StatusCode']}")
        return True
    except Exception as e:
        logger.error(f"Failed to invoke Lambda for {email}: {e}")
        return False