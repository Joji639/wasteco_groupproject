from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema

from accounts.models import UserProfile
from accounts.serializers import (
    OnboardingSerializer, LogoutSerializer, AccountInfoSerializer,
    PersonalInfoSerializer, ChangePasswordSerializer,
)
from pickups.serializers import PickupRequestSerializer
from accounts.permissions import IsVerifiedForActions, _in_group


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
    permission_classes = [permissions.IsAuthenticated]
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


# ---------------------------------------------------------------------------
# User Pickup Request (moved from pickups app)
# ---------------------------------------------------------------------------

from django.conf import settings
from rest_framework.parsers import MultiPartParser as MP, FormParser as FP, JSONParser
from pickups.models import PickupRequest


class IsVerifiedUser(permissions.BasePermission):
    """Only verified users in the 'User' group."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from accounts.permissions import _in_group
        if not _in_group(request.user, 'User'):
            return False
        try:
            profile = request.user.user_profile
            return profile.is_verified
        except UserProfile.DoesNotExist:
            return False


class PickupRequestCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsVerifiedUser]
    parser_classes = [MP, FP, JSONParser]

    @extend_schema(
        tags=['Pickups'],
        request=PickupRequestSerializer,
        responses={201: PickupRequestSerializer}
    )
    def post(self, request):
        serializer = PickupRequestSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        pickup = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Pickup request created successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED
        )


# ---------------------------------------------------------------------------
# User Review Views
# ---------------------------------------------------------------------------

from django.db import transaction
from pickups.models import OperatorReview
from pickups.serializers import OperatorReviewCreateSerializer, OperatorReviewResponseSerializer


class IsUserRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and _in_group(request.user, 'User')
        )


class UserReviewCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsUserRole]

    @extend_schema(
        tags=['User - Reviews'],
        request=OperatorReviewCreateSerializer,
        responses={201: OperatorReviewResponseSerializer}
    )
    def post(self, request, pickup_id):
        serializer = OperatorReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rating = serializer.validated_data['rating']
        comment = serializer.validated_data.get('comment', '')

        try:
            pickup = PickupRequest.objects.get(id=pickup_id)
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if pickup.user != request.user:
            return Response(
                {"success": False, "message": "You do not have permission to review this pickup."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if pickup.status != 'COMPLETED':
            return Response(
                {"success": False, "message": "You can review the operator only after the pickup is completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not pickup.assigned_operator:
            return Response(
                {"success": False, "message": "No operator was assigned to this pickup."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if OperatorReview.objects.filter(pickup_request=pickup, user=request.user).exists():
            return Response(
                {"success": False, "message": "You have already submitted a review for this pickup."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                review = OperatorReview.objects.create(
                    pickup_request=pickup,
                    user=request.user,
                    operator=pickup.assigned_operator,
                    rating=rating,
                    comment=comment if comment else None,
                )
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to submit review.", "errors": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": "Review submitted successfully.",
                "data": OperatorReviewResponseSerializer(review).data,
            },
            status=status.HTTP_201_CREATED,
        )


class UserReviewDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsUserRole]

    @extend_schema(
        tags=['User - Reviews'],
        responses={200: OperatorReviewResponseSerializer}
    )
    def get(self, request, pickup_id):
        try:
            pickup = PickupRequest.objects.get(id=pickup_id)
        except PickupRequest.DoesNotExist:
            return Response(
                {"success": False, "message": "Pickup not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if pickup.user != request.user:
            return Response(
                {"success": False, "message": "You do not have permission to view this pickup's review."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            review = OperatorReview.objects.get(pickup_request=pickup, user=request.user)
        except OperatorReview.DoesNotExist:
            return Response(
                {"success": False, "message": "No review found for this pickup."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "success": True,
                "data": OperatorReviewResponseSerializer(review).data,
            },
            status=status.HTTP_200_OK,
        )
