from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from .serializers import ( UserRegistrationSerializer,OnboardingSerializer,
UserLoginSerializer, get_tokens_for_user,LogoutSerializer,
AccountInfoSerializer, PersonalInfoSerializer ,ChangePasswordSerializer,Verify2FASerializer, 
Disable2FASerializer,LoginWith2FASerializer,ForgotPasswordRequestSerializer, ResetPasswordSerializer,
StaffLoginSerializer,OperatorOnboardingSerializer,
OperatorOnboardingAdminSerializer,OperatorPersonalInfoSerializer,RejectOnboardingSerializer,AdminUserOnboardingSerializer,
StaffRegistrationSerializer,set_staff_verified,AdminUserListSerializer,AdminStaffListSerializer,
AdminLoginSerializer,staff_onboarding_status

                     
)
from .models import UserProfile,CustomUser,OperatorProfile,OperatorOnboarding,OperatorAdminProfile
from django.db.models import Q
from django.db import transaction
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from .permissions import IsVerifiedForActions, IsOperatorAdminOrSuperAdmin, IsStaffRole, IsSuperAdminRole, IsApprovedStaff
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
import pyotp
import qrcode
import io
import base64
import random
from django.core.cache import cache
from .tasks import send_email_otp_task
from django.conf import settings
from django.utils import timezone
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from .serializers import GoogleAuthSerializer
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
signer = TimestampSigner()
OTP_CACHE_PREFIX = "forgot_password_otp_"
OTP_TTL_SECONDS = 300  # 5 minutes


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



class OnboardingView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=['User'], request=OnboardingSerializer, responses={200: None})
    def post(self, request):
        if request.user.base_role != 'user':
            return Response(
                {"success": False, "message": "Only users can access onboarding"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            profile = request.user.user_profile
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User profile not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.is_verified:
            return Response(
                {"success": False, "message": "Onboarding already completed and verified"},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OnboardingSerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to save onboarding details", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {"success": True, "message": "Onboarding submitted. Awaiting operator admin verification."},
            status=status.HTTP_200_OK
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

        # --- 2FA branch ---
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


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], request=LogoutSerializer, responses={200: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data['refresh'])
            token.blacklist()
        except TokenError:
            return Response(
                {"success": False, "message": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Logout failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Logged out successfully"},
            status=status.HTTP_200_OK
        )



class AccountInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], responses={200: AccountInfoSerializer})
    def get(self, request):

        serializer = AccountInfoSerializer(request.user)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['User'], request=AccountInfoSerializer, responses={200: None})
    def patch(self, request):
        serializer = AccountInfoSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Account info updated.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK
        )


class PersonalInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsVerifiedForActions]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=['User'], responses={200: PersonalInfoSerializer})
    def get(self, request):
        try:
            profile = request.user.user_profile
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User profile not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = PersonalInfoSerializer(profile)
        return Response(
            {"success": True, "data": serializer.data, "is_verified": profile.is_verified},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['User'], request=PersonalInfoSerializer, responses={200: None})
    def patch(self, request):
        try:
            profile = request.user.user_profile
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User profile not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = PersonalInfoSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Personal information updated. Awaiting operator admin re-verification.",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['User'], request=ChangePasswordSerializer, responses={200: None})
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {"success": False, "message": "Old password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user.set_password(serializer.validated_data['new_password'])
            user.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Password change failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Password changed successfully. Please log in again."},
            status=status.HTTP_200_OK
        )



class Setup2FAView(APIView):
    """Step 1: Generate a TOTP secret and return a QR code to scan."""
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
    """Step 2: Confirm the user scanned correctly by submitting a valid code, activating 2FA."""
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
    """Step 2 of login: identifier + TOTP code, issues real JWT tokens."""
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
    """Login for operator and operator admin via email/phone OR operator_id (OP-/OA-) + password."""
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


class OperatorOnboardingView(APIView):
    """Submit, view, or update the staff member's own onboarding request (operator or operator admin)."""
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=['Staff'], responses={200: OperatorOnboardingSerializer})
    def get(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": True, "data": None, "message": "No onboarding submitted yet"},
                status=status.HTTP_200_OK
            )

        serializer = OperatorOnboardingSerializer(onboarding)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['Staff'], request=OperatorOnboardingSerializer, responses={201: OperatorOnboardingSerializer})
    def post(self, request):
        if OperatorOnboarding.objects.filter(user=request.user).exists():
            return Response(
                {"success": False, "message": "Onboarding already submitted. Use PATCH to resubmit after rejection."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = OperatorOnboardingSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to submit onboarding", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding submitted. Awaiting approval.",
                "data": OperatorOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_201_CREATED
        )

    @extend_schema(tags=['Staff'], request=OperatorOnboardingSerializer, responses={200: OperatorOnboardingSerializer})
    def patch(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorOnboardingSerializer(
            onboarding, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to update onboarding", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding updated. Awaiting approval.",
                "data": OperatorOnboardingSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class StaffRegistrationView(APIView):
    """Register an operator (role='operator') or operator admin (role='operatoradmin')."""
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


class OperatorAccountInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsApprovedStaff]

    @extend_schema(tags=['Staff'], responses={200: AccountInfoSerializer})
    def get(self, request):
        try:
            serializer = AccountInfoSerializer(request.user)
            return Response(
                {"success": True, "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load account info", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(tags=['Staff'], request=AccountInfoSerializer, responses={200: None})
    def patch(self, request):
        try:
            serializer = AccountInfoSerializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    "success": True,
                    "message": "Account info updated.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class OperatorPersonalInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsApprovedStaff]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=['Staff'], responses={200: OperatorPersonalInfoSerializer})
    def get(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorPersonalInfoSerializer(onboarding)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    @extend_schema(tags=['Staff'], request=OperatorOnboardingSerializer, responses={200: OperatorPersonalInfoSerializer})
    def patch(self, request):
        try:
            onboarding = request.user.operator_onboarding
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "No onboarding submitted yet"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = OperatorOnboardingSerializer(
            onboarding, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            onboarding = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Update failed", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Personal info updated. Awaiting re-approval.",
                "data": OperatorPersonalInfoSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class OperatorChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(tags=['Staff'], request=ChangePasswordSerializer, responses={200: None})
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if not user.check_password(serializer.validated_data['old_password']):
            return Response(
                {"success": False, "message": "Old password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user.set_password(serializer.validated_data['new_password'])
            user.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Password change failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Password changed successfully. Please log in again."},
            status=status.HTTP_200_OK
        )


class OperatorLogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(tags=['Staff'], request=LogoutSerializer, responses={200: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data['refresh'])
            token.blacklist()
        except TokenError:
            return Response(
                {"success": False, "message": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Logout failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"success": True, "message": "Logged out successfully"},
            status=status.HTTP_200_OK
        )


def _can_approve(request, onboarding):
    target_role = onboarding.user.base_role
    if target_role == 'operatoradmin':
        return request.user.base_role == 'superadmin'
    return request.user.base_role == 'operatoradmin'


class OperatorOnboardingListView(APIView):
    """Operator admin: list operator onboarding requests. Super admin: see all."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved"], description="Filter by status"),
            OpenApiParameter("role", str, description="Filter by role"),
        ],
        responses={200: OperatorOnboardingAdminSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = OperatorOnboarding.objects.select_related(
                'user', 'approved_by'
            ).all()

            if request.user.base_role == 'operatoradmin':
                queryset = queryset.filter(user__base_role='operator')

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(approved=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(approved=True)

            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(user__base_role=role_filter)

            serializer = OperatorOnboardingAdminSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load onboarding requests", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OperatorOnboardingApproveView(APIView):
    """Operator admin approves operators; super admin approves operator admins."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        request=OpenApiTypes.OBJECT,
        responses={200: OperatorOnboardingAdminSerializer}
    )
    def post(self, request):
        onboarding_id = request.data.get('id')
        if not onboarding_id:
            return Response(
                {"success": False, "message": "Onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            onboarding = OperatorOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not _can_approve(request, onboarding):
            return Response(
                {"success": False, "message": "You are not authorized to approve this request"},
                status=status.HTTP_403_FORBIDDEN
            )

        if onboarding.approved:
            return Response(
                {"success": False, "message": "Onboarding is already approved"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                onboarding.approved = True
                onboarding.approved_by = request.user
                onboarding.approved_at = timezone.now()
                onboarding.rejection_reason = ''
                onboarding.save()

                user = onboarding.user
                user.is_active = True
                user.save(update_fields=['is_active'])
                set_staff_verified(user, True)
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to approve onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding approved. Account is now active.",
                "data": OperatorOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class OperatorOnboardingRejectView(APIView):
    """Operator admin rejects operators; super admin rejects operator admins."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(tags=['Operator Admin'], request=RejectOnboardingSerializer, responses={200: OperatorOnboardingAdminSerializer})
    def post(self, request):
        serializer = RejectOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        onboarding_id = request.data.get('id')
        if not onboarding_id:
            return Response(
                {"success": False, "message": "Onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            onboarding = OperatorOnboarding.objects.select_related('user').get(id=onboarding_id)
        except OperatorOnboarding.DoesNotExist:
            return Response(
                {"success": False, "message": "Onboarding request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if not _can_approve(request, onboarding):
            return Response(
                {"success": False, "message": "You are not authorized to reject this request"},
                status=status.HTTP_403_FORBIDDEN
            )

        if onboarding.approved:
            return Response(
                {"success": False, "message": "Approved onboarding cannot be rejected"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                onboarding.rejection_reason = serializer.validated_data['reason']
                onboarding.save(update_fields=['rejection_reason', 'updated_at'])

                user = onboarding.user
                set_staff_verified(user, False)
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to reject onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Onboarding rejected. The staff member can resubmit via PATCH.",
                "data": OperatorOnboardingAdminSerializer(onboarding).data,
            },
            status=status.HTTP_200_OK
        )


class AdminUserOnboardingListView(APIView):
    """Operator admin / super admin: list user (customer) onboarding requests."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved", "not_submitted"], description="Filter by status"),
        ],
        responses={200: AdminUserOnboardingSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = UserProfile.objects.select_related('user', 'verified_by').filter(
                user__base_role='user'
            )

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(is_verified=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(is_verified=True)
            elif filter_param == 'not_submitted':
                queryset = queryset.filter(address__isnull=True, current_location__isnull=True)

            serializer = AdminUserOnboardingSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load user onboarding requests", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminUserOnboardingApproveView(APIView):
    """Operator admin / super admin approves a user's onboarding."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(
        tags=['Operator Admin'],
        request=OpenApiTypes.OBJECT,
        responses={200: AdminUserOnboardingSerializer}
    )
    def post(self, request):
        profile_id = request.data.get('id')
        if not profile_id:
            return Response(
                {"success": False, "message": "User onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = UserProfile.objects.select_related('user').get(id=profile_id)
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User onboarding not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.is_verified:
            return Response(
                {"success": False, "message": "User onboarding is already approved"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                profile.is_verified = True
                profile.rejection_reason = ''
                if request.user.base_role == 'operatoradmin':
                    profile.verified_by = request.user.operatoradmin_profile
                profile.save()

                user = profile.user
                user.is_active = True
                user.save(update_fields=['is_active'])
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to approve user onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "User onboarding approved. Account is now active.",
                "data": AdminUserOnboardingSerializer(profile).data,
            },
            status=status.HTTP_200_OK
        )


class AdminUserOnboardingRejectView(APIView):
    """Operator admin / super admin rejects a user's onboarding."""
    permission_classes = [permissions.IsAuthenticated, IsOperatorAdminOrSuperAdmin]

    @extend_schema(tags=['Operator Admin'], request=RejectOnboardingSerializer, responses={200: AdminUserOnboardingSerializer})
    def post(self, request):
        serializer = RejectOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile_id = request.data.get('id')
        if not profile_id:
            return Response(
                {"success": False, "message": "User onboarding id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            profile = UserProfile.objects.select_related('user').get(id=profile_id)
        except UserProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "User onboarding not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if profile.is_verified:
            return Response(
                {"success": False, "message": "Approved user onboarding cannot be rejected"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                profile.rejection_reason = serializer.validated_data['reason']
                profile.is_verified = False
                profile.verified_by = None
                profile.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to reject user onboarding", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "User onboarding rejected. The user can resubmit via onboarding.",
                "data": AdminUserOnboardingSerializer(profile).data,
            },
            status=status.HTTP_200_OK
        )


class AdminLoginView(APIView):
    """Login for the super admin via email + password (with 2FA branch)."""
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Super Admin'], request=AdminLoginSerializer, responses={200: None})
    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        try:
            user = CustomUser.objects.get(email=email, base_role='superadmin')
        except CustomUser.DoesNotExist:
            return Response(
                {"success": False, "message": "Invalid admin credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        if not user.check_password(password):
            return Response(
                {"success": False, "message": "Invalid admin credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_active:
            return Response(
                {"success": False, "message": "Admin account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.is_2fa_enabled:
            return Response(
                {
                    "success": True,
                    "message": "2FA required",
                    "data": {"requires_2fa": True, "identifier": email}
                },
                status=status.HTTP_200_OK
            )

        try:
            tokens = get_tokens_for_user(user)
        except Exception as e:
            return Response(
                {"success": False, "message": "Login failed", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Admin login successful",
                "data": {"tokens": tokens, "role": user.base_role},
            },
            status=status.HTTP_200_OK
        )


class AdminUserListView(APIView):
    """Super admin: list all regular users."""
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admin'], responses={200: AdminUserListSerializer(many=True)})
    def get(self, request):
        try:
            queryset = CustomUser.objects.filter(base_role='user').select_related('user_profile')
            serializer = AdminUserListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load users", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOperatorListView(APIView):
    """Super admin: list all operators."""
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admin'], responses={200: AdminStaffListSerializer(many=True)})
    def get(self, request):
        try:
            queryset = CustomUser.objects.filter(base_role='operator').select_related('operator_profile')
            serializer = AdminStaffListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load operators", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOperatorAdminListView(APIView):
    """Super admin: list all operator admins."""
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(tags=['Super Admin'], responses={200: AdminStaffListSerializer(many=True)})
    def get(self, request):
        try:
            queryset = CustomUser.objects.filter(base_role='operatoradmin').select_related('operatoradmin_profile')
            serializer = AdminStaffListSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load operator admins", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminOnboardingListView(APIView):
    """Super admin: list all onboarding requests (operators + operator admins)."""
    permission_classes = [permissions.IsAuthenticated, IsSuperAdminRole]

    @extend_schema(
        tags=['Super Admin'],
        parameters=[
            OpenApiParameter("status", str, enum=["pending", "approved"], description="Filter by status"),
            OpenApiParameter("role", str, description="Filter by role"),
        ],
        responses={200: OperatorOnboardingAdminSerializer(many=True)}
    )
    def get(self, request):
        try:
            queryset = OperatorOnboarding.objects.select_related('user', 'approved_by').all()

            filter_param = request.query_params.get('status')
            if filter_param == 'pending':
                queryset = queryset.filter(approved=False)
            elif filter_param == 'approved':
                queryset = queryset.filter(approved=True)

            role_filter = request.query_params.get('role')
            if role_filter:
                queryset = queryset.filter(user__base_role=role_filter)

            serializer = OperatorOnboardingAdminSerializer(queryset, many=True)
            return Response(
                {"success": True, "count": len(serializer.data), "data": serializer.data},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to load onboarding requests", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
