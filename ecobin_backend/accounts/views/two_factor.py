import pyotp
import qrcode
import io
import base64

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CustomUser, OperatorProfile, OperatorAdminProfile
from ..serializers import (
    Verify2FASerializer, Disable2FASerializer, LoginWith2FASerializer,
    get_tokens_for_user,
)


class Setup2FAView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], responses={200: None})
    def post(self, request):
        user = request.user

        if user.is_2fa_enabled:
            return Response(
                {"success": False, "message": "2FA is already enabled"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            secret = pyotp.random_base32()
            user.totp_secret = secret
            user.save()

            totp = pyotp.TOTP(secret)
            provisioning_uri = totp.provisioning_uri(
                name=user.email,
                issuer_name="EcoBin"
            )

            qr = qrcode.make(provisioning_uri)
            buffer = io.BytesIO()
            qr.save(buffer, format='PNG')
            qr_base64 = base64.b64encode(buffer.getvalue()).decode()

        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to set up 2FA", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Scan this QR code with Microsoft Authenticator, then verify with a code",
                "data": {
                    "qr_code_base64": qr_base64,
                    "manual_entry_key": secret,
                }
            },
            status=status.HTTP_200_OK
        )


class Verify2FAView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], request=Verify2FASerializer, responses={200: None})
    def post(self, request):
        serializer = Verify2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data['code']

        user = request.user

        if not user.totp_secret:
            return Response(
                {"success": False, "message": "2FA setup not started"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            totp = pyotp.TOTP(user.totp_secret)
            is_valid = totp.verify(code, valid_window=1)
        except Exception as e:
            return Response(
                {"success": False, "message": "Verification failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not is_valid:
            return Response(
                {"success": False, "message": "Invalid or expired code"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_2fa_enabled = True
        user.save()

        return Response(
            {"success": True, "message": "2FA enabled successfully"},
            status=status.HTTP_200_OK
        )


class Disable2FAView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], request=Disable2FASerializer, responses={200: None})
    def post(self, request):
        serializer = Disable2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if not user.check_password(serializer.validated_data['password']):
            return Response(
                {"success": False, "message": "Incorrect password"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_2fa_enabled = False
        user.totp_secret = None
        user.save()

        return Response(
            {"success": True, "message": "2FA disabled"},
            status=status.HTTP_200_OK
        )


class LoginWith2FAView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=LoginWith2FASerializer, responses={200: None})
    def post(self, request):
        serializer = LoginWith2FASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get('identifier')
        operator_id = serializer.validated_data.get('operator_id')
        code = serializer.validated_data['code']

        try:
            if operator_id:
                profile = (
                    OperatorAdminProfile.objects.select_related('user').get(operator_id=operator_id)
                    if operator_id.startswith('OA-')
                    else OperatorProfile.objects.select_related('user').get(operator_id=operator_id)
                )
                user = profile.user
            else:
                user = CustomUser.objects.get(Q(email=identifier) | Q(phone=identifier))
        except (CustomUser.DoesNotExist, OperatorProfile.DoesNotExist, OperatorAdminProfile.DoesNotExist):
            return Response(
                {"success": False, "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception:
            return Response(
                {"success": False, "message": "An error occurred"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not user.is_2fa_enabled or not user.totp_secret:
            return Response(
                {"success": False, "message": "2FA is not enabled for this account"},
                status=status.HTTP_400_BAD_REQUEST
            )

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            return Response(
                {"success": False, "message": "Invalid or expired code"},
                status=status.HTTP_400_BAD_REQUEST
            )

        tokens = get_tokens_for_user(user)
        return Response(
            {"success": True, "message": "Login successful", "data": {"tokens": tokens, "role": user.base_role}},
            status=status.HTTP_200_OK
        )
