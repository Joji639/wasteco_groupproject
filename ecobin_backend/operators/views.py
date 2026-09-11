from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema
from django.db.models import Avg, Count, Q

from accounts.models import OperatorOnboarding
from accounts.serializers import (
    OperatorOnboardingSerializer, OperatorPersonalInfoSerializer,
    AccountInfoSerializer, ChangePasswordSerializer, LogoutSerializer,
)
from accounts.permissions import IsStaffRole, IsApprovedStaff


class OperatorOnboardingView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=['Operators'], responses={200: OperatorOnboardingSerializer})
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

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={201: OperatorOnboardingSerializer})
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

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={200: OperatorOnboardingSerializer})
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


class OperatorAccountInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsApprovedStaff]

    @extend_schema(tags=['Operators'], responses={200: AccountInfoSerializer})
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

    @extend_schema(tags=['Operators'], request=AccountInfoSerializer, responses={200: None})
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

    @extend_schema(tags=['Operators'], responses={200: OperatorPersonalInfoSerializer})
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

    @extend_schema(tags=['Operators'], request=OperatorOnboardingSerializer, responses={200: OperatorPersonalInfoSerializer})
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

    @extend_schema(tags=['Operators'], request=ChangePasswordSerializer, responses={200: None})
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

    @extend_schema(tags=['Operators'], request=LogoutSerializer, responses={200: None})
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


# ---------------------------------------------------------------------------
# Operator Review Views
# ---------------------------------------------------------------------------

from pickups.models import OperatorReview
from pickups.serializers import OperatorReviewListSerializer, OperatorRatingSummarySerializer


class OperatorReviewsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: OperatorReviewListSerializer(many=True)}
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reviews = OperatorReview.objects.filter(
            operator=request.user,
        ).select_related('pickup_request')

        serializer = OperatorReviewListSerializer(reviews, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK,
        )


class OperatorRatingSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStaffRole]

    @extend_schema(
        tags=['Operators'],
        responses={200: OperatorRatingSummarySerializer}
    )
    def get(self, request):
        if request.user.base_role != 'operator':
            return Response(
                {"success": False, "message": "Only operators can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reviews = OperatorReview.objects.filter(operator=request.user)
        total = reviews.count()

        if total == 0:
            data = {
                'average_rating': None,
                'total_reviews': 0,
                'rating_distribution': {'5': 0, '4': 0, '3': 0, '2': 0, '1': 0},
            }
        else:
            avg = reviews.aggregate(avg=Avg('rating'))['avg']
            distribution = {}
            for star in range(5, 0, -1):
                distribution[str(star)] = reviews.filter(rating=star).count()
            data = {
                'average_rating': round(float(avg), 1),
                'total_reviews': total,
                'rating_distribution': distribution,
            }

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )
