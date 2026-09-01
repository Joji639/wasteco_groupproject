from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema

from ..models import UserProfile
from ..serializers import (
    OnboardingSerializer, LogoutSerializer, AccountInfoSerializer,
    PersonalInfoSerializer, ChangePasswordSerializer,
)
from ..permissions import IsVerifiedForActions


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
