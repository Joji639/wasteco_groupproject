import random
import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile
from ..serializers import (
    UserRegistrationSerializer, UserLoginSerializer, get_tokens_for_user,
    ForgotPasswordRequestSerializer, ResetPasswordSerializer,
    GoogleAuthSerializer, StaffLoginSerializer, StaffRegistrationSerializer,
    staff_onboarding_status,
)
from ..tasks import send_email_otp_task
from .constants import OTP_CACHE_PREFIX, OTP_TTL_SECONDS

logger = logging.getLogger(__name__)


class UserRegistrationView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=UserRegistrationSerializer, responses={201: None})
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Registration failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "User registered successfully. Awaiting operator admin verification.",
                "data": {
                    "email": user.email,
                    "phone": str(user.phone),
                    "is_verified": user.user_profile.is_verified,
                }
            },
            status=status.HTTP_201_CREATED
        )


class UserLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=UserLoginSerializer, responses={200: None})
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['identifier']
        password = serializer.validated_data['password']

        try:
            user = CustomUser.objects.get(
                Q(email=identifier) | Q(phone=identifier),
                base_role='user'
            )
        except CustomUser.DoesNotExist:
            return Response({"success": False, "message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({"success": False, "message": "Login failed", "errors": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not user.check_password(password):
            return Response({"success": False, "message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({"success": False, "message": "Account is disabled"}, status=status.HTTP_403_FORBIDDEN)

        if user.is_2fa_enabled:
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "email": user.email}
                },
                status=status.HTTP_200_OK
            )

        try:
            profile = user.user_profile
        except UserProfile.DoesNotExist:
            return Response({"success": False, "message": "User profile not found"}, status=status.HTTP_404_NOT_FOUND)

        tokens = get_tokens_for_user(user)

        if not profile.address and not profile.current_location:
            onboarding_status = "not_submitted"
        elif not profile.is_verified:
            onboarding_status = "pending_verification"
        else:
            onboarding_status = "verified"

        return Response(
            {
                "success": True,
                "message": "Login successful",
                "data": {
                    "tokens": tokens,
                    "role": user.base_role,
                    "is_verified": profile.is_verified,
                    "onboarding_status": onboarding_status,
                }
            },
            status=status.HTTP_200_OK
        )


class ForgotPasswordRequestView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=ForgotPasswordRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response(
                {"success": True, "message": "If this account exists, an OTP has been sent"},
                status=status.HTTP_200_OK
            )

        code = str(random.randint(100000, 999999))

        try:
            cache.set(f"{OTP_CACHE_PREFIX}{email}", code, timeout=OTP_TTL_SECONDS)
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to generate OTP", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        send_email_otp_task.delay(email, code)

        return Response(
            {"success": True, "message": "If this account exists, an OTP has been sent"},
            status=status.HTTP_200_OK
        )


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=ResetPasswordSerializer, responses={200: None})
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Invalid OTP or email"},
                status=status.HTTP_400_BAD_REQUEST
            )

        cache_key = f"{OTP_CACHE_PREFIX}{email}"
        stored_code = cache.get(cache_key)

        if not stored_code or stored_code != code:
            return Response(
                {"success": False, "message": "Invalid or expired OTP"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user.set_password(new_password)
            user.save()
            cache.delete(cache_key)
        except Exception as e:
            return Response(
                {"success": False, "message": "Password reset failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Password reset successfully. Please log in with your new password."},
            status=status.HTTP_200_OK
        )


class GoogleAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=GoogleAuthSerializer, responses={200: None})
    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['id_token']

        try:
            idinfo = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError as e:
            return Response(
                {"success": False, "message": "Invalid Google token", "errors": str(e)},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Google authentication failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        email = idinfo.get('email')
        username = idinfo.get('name', email.split('@')[0] if email else None)

        if not email:
            return Response(
                {"success": False, "message": "Email not found in Google account"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = CustomUser.objects.get(email=email, base_role='user')
            created = False
        except CustomUser.DoesNotExist:
            try:
                user = CustomUser.objects.create_user(
                    email=email,
                    username=username,
                    password=None,
                    base_role='user'
                )
                user.set_unusable_password()
                user.save()
                UserProfile.objects.create(user=user)
                created = True
            except Exception as e:
                return Response(
                    {"success": False, "message": "Account creation failed", "errors": str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "Account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            profile = user.user_profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=user)

        tokens = get_tokens_for_user(user)

        if not profile.address and not profile.current_location:
            onboarding_status = "not_submitted"
        elif not profile.is_verified:
            onboarding_status = "pending_verification"
        else:
            onboarding_status = "verified"

        return Response(
            {
                "success": True,
                "message": "Account created" if created else "Login successful",
                "data": {
                    "tokens": tokens,
                    "role": user.base_role,
                    "is_verified": profile.is_verified,
                    "onboarding_status": onboarding_status,
                }
            },
            status=status.HTTP_200_OK
        )


class StaffLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=StaffLoginSerializer, responses={200: None})
    def post(self, request):
        serializer = StaffLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get('identifier')
        operator_id = serializer.validated_data.get('operator_id')
        password = serializer.validated_data['password']

        try:
            if operator_id:
                profile = (
                    OperatorAdminProfile.objects.select_related('user').get(operator_id=operator_id)
                    if operator_id.startswith('OA-')
                    else OperatorProfile.objects.select_related('user').get(operator_id=operator_id)
                )
                user = profile.user
            else:
                user = CustomUser.objects.get(
                    Q(email=identifier) | Q(phone=identifier),
                    base_role__in=['operator', 'operatoradmin']
                )
        except (CustomUser.DoesNotExist, OperatorProfile.DoesNotExist, OperatorAdminProfile.DoesNotExist):
            return Response(
                {"success": False, "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if user.base_role not in ('operator', 'operatoradmin'):
            return Response(
                {"success": False, "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.check_password(password):
            return Response(
                {"success": False, "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "Account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.is_2fa_enabled:
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "operator_id": user.staff_operator_id}
                },
                status=status.HTTP_200_OK
            )

        try:
            tokens = get_tokens_for_user(user)
            profile = user.operatoradmin_profile if user.base_role == 'operatoradmin' else user.operator_profile
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        data = {
            "tokens": tokens,
            "role": user.base_role,
            "operator_id": profile.operator_id,
            "is_verified": profile.is_verified,
            "onboarding_status": staff_onboarding_status(user),
        }
        if user.base_role == 'operatoradmin':
            data["panchayath"] = profile.panchayath
        else:
            data["ward_no"] = profile.ward_no

        return Response(
            {"success": True, "message": "Login successful", "data": data},
            status=status.HTTP_200_OK
        )


class StaffRegistrationView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Public'], request=StaffRegistrationSerializer, responses={201: None})
    def post(self, request):
        serializer = StaffRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Registration failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        profile = user.operatoradmin_profile if user.base_role == 'operatoradmin' else user.operator_profile

        return Response(
            {
                "success": True,
                "message": "Registered successfully. Pending admin approval.",
                "data": {
                    "email": user.email,
                    "role": user.base_role,
                    "operator_id": profile.operator_id,
                    "is_active": user.is_active,
                }
            },
            status=status.HTTP_201_CREATED
        )
