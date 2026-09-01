from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CustomUser, OperatorOnboarding
from ..serializers import (
    AdminLoginSerializer, get_tokens_for_user,
    AdminUserListSerializer, AdminStaffListSerializer,
    OperatorOnboardingAdminSerializer,
)
from ..permissions import IsSuperAdminRole


class AdminLoginView(APIView):
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
