import secrets
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
from ..permissions import IsSuperAdminRole
from ..tasks import send_email_otp_task
from .constants import (
    OTP_CACHE_PREFIX, OTP_TTL_SECONDS,
    PARTIAL_TOKEN_PREFIX, PARTIAL_TOKEN_TTL_SECONDS,
    RATE_LIMIT_PREFIX, RATE_LIMIT_ATTEMPTS, RATE_LIMIT_WINDOW,
)

logger = logging.getLogger(__name__)


def _check_rate_limit(key, max_attempts=RATE_LIMIT_ATTEMPTS, window=RATE_LIMIT_WINDOW):
    cache_key = f"{RATE_LIMIT_PREFIX}{key}"
    attempts = cache.get(cache_key, 0)
    if attempts >= max_attempts:
        return False
    cache.set(cache_key, attempts + 1, timeout=window)
    return True


def _generate_partial_token(user_id):
    token = secrets.token_urlsafe(32)
    cache.set(f"{PARTIAL_TOKEN_PREFIX}{token}", str(user_id), timeout=PARTIAL_TOKEN_TTL_SECONDS)
    return token


class UserRegistrationView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        tags=['Public'],
        summary="User Registration (Public - No Token Required)",
        description="Public endpoint to register a new Resident/User account. Requires NO authentication token.",
        request=UserRegistrationSerializer,
        responses={201: None}
    )
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = serializer.save()
        except Exception:
            return Response(
                {"success": False, "message": "Registration failed"},
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

    @extend_schema(
        tags=['Public'],
        summary="User Login (Public - No Token Required)",
        description="Public endpoint to log in a Resident/User account using email or phone.",
        request=UserLoginSerializer,
        responses={200: None}
    )
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['identifier']
        password = serializer.validated_data['password']

        if not _check_rate_limit(f"user_login:{identifier}"):
            return Response(
                {"success": False, "message": "Too many login attempts. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            if "@" in identifier:
                user = CustomUser.objects.get(email=identifier, base_role='user')
            else:
                user = CustomUser.objects.get(phone=identifier, base_role='user')
        except CustomUser.DoesNotExist:
            return Response({"success": False, "message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        except Exception:
            return Response({"success": False, "message": "Login failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not user.check_password(password):
            return Response({"success": False, "message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({"success": False, "message": "Account is disabled"}, status=status.HTTP_403_FORBIDDEN)

        if user.is_2fa_enabled:
            partial_token = _generate_partial_token(user.id)
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "partial_token": partial_token}
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

        if not _check_rate_limit(f"otp:{email}"):
            return Response(
                {"success": False, "message": "Too many requests. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response(
                {"success": True, "message": "If this account exists, an OTP has been sent"},
                status=status.HTTP_200_OK
            )

        code = str(secrets.randbelow(900000) + 100000)

        try:
            cache.set(f"{OTP_CACHE_PREFIX}{email}", code, timeout=OTP_TTL_SECONDS)
        except Exception:
            return Response(
                {"success": False, "message": "Failed to generate OTP"},
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
        except Exception:
            return Response(
                {"success": False, "message": "Password reset failed"},
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
        except ValueError:
            return Response(
                {"success": False, "message": "Invalid Google token"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception:
            return Response(
                {"success": False, "message": "Google authentication failed"},
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
                created = True
            except Exception:
                return Response(
                    {"success": False, "message": "Account creation failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except Exception:
            return Response(
                {"success": False, "message": "Login failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "Account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        profile, _ = UserProfile.objects.get_or_create(user=user)

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

    @extend_schema(
        tags=['Public'],
        summary="Staff Login (Operator / OperatorAdmin - No Token Required)",
        description="Public endpoint for staff (Operators & OperatorAdmins) to log in using email/phone and password.",
        request=StaffLoginSerializer,
        responses={200: None}
    )
    def post(self, request):
        serializer = StaffLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get('identifier')
        operator_id = serializer.validated_data.get('operator_id')
        password = serializer.validated_data['password']

        rate_key = f"staff_login:{identifier or operator_id}"
        if not _check_rate_limit(rate_key):
            return Response(
                {"success": False, "message": "Too many login attempts. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            if operator_id:
                profile = (
                    OperatorAdminProfile.objects.select_related('user').get(operator_id=operator_id)
                    if operator_id.startswith('OA-')
                    else OperatorProfile.objects.select_related('user').get(operator_id=operator_id)
                )
                user = profile.user
            elif "@" in identifier:
                user = CustomUser.objects.get(
                    email=identifier,
                    base_role__in=['operator', 'operatoradmin']
                )
            else:
                user = CustomUser.objects.get(
                    phone=identifier,
                    base_role__in=['operator', 'operatoradmin']
                )
        except (CustomUser.DoesNotExist, OperatorProfile.DoesNotExist, OperatorAdminProfile.DoesNotExist):
            return Response(
                {"success": False, "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception:
            return Response(
                {"success": False, "message": "Login failed"},
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
            partial_token = _generate_partial_token(user.id)
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "partial_token": partial_token}
                },
                status=status.HTTP_200_OK
            )

        try:
            tokens = get_tokens_for_user(user)
            profile = user.operatoradmin_profile if user.base_role == 'operatoradmin' else user.operator_profile
        except Exception:
            return Response(
                {"success": False, "message": "Login failed"},
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

    @extend_schema(
        tags=['Public'],
        summary="Staff Registration (Operator / OperatorAdmin - Public)",
        description="Public registration endpoint for prospective Operators and OperatorAdmins to sign up. No authentication required.",
        request=StaffRegistrationSerializer,
        responses={201: None}
    )
    def post(self, request):
        serializer = StaffRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = serializer.save()
        except Exception:
            return Response(
                {"success": False, "message": "Registration failed"},
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
