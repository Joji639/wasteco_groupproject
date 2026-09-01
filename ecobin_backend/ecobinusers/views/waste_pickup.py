from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsVerifiedForActions
from ..models import WastePickupRequest, PickupSchedule
from ..serializers import WastePickupRequestSerializer, PickupScheduleSerializer


class WastePickupRequestCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsVerifiedForActions]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=['User - Waste Pickup'],
        request=WastePickupRequestSerializer,
        responses={201: WastePickupRequestSerializer}
    )
    def post(self, request):
        if request.user.base_role != 'user':
            return Response(
                {"success": False, "message": "Only users can create waste requests"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = WastePickupRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            waste_request = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to create request", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Waste pickup request created. Awaiting operator admin assignment.",
                "data": WastePickupRequestSerializer(waste_request).data,
            },
            status=status.HTTP_201_CREATED
        )


class WastePickupRequestListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Waste Pickup'],
        responses={200: WastePickupRequestSerializer(many=True)}
    )
    def get(self, request):
        queryset = WastePickupRequest.objects.filter(user=request.user).order_by('-created_at')
        serializer = WastePickupRequestSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class PickupDateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Pickup Date'],
        responses={200: PickupScheduleSerializer}
    )
    def get(self, request):
        today = timezone.now().date()

        future_schedule = PickupSchedule.objects.filter(
            user=request.user,
            scheduled_date__gte=today,
            is_active=True
        ).first()

        if future_schedule:
            days_until = (future_schedule.scheduled_date - today).days
            return Response(
                {
                    "success": True,
                    "data": {
                        "next_pickup_date": str(future_schedule.scheduled_date),
                        "days_until_pickup": days_until,
                    }
                },
                status=status.HTTP_200_OK
            )

        past_schedule = PickupSchedule.objects.filter(
            user=request.user,
            scheduled_date__lt=today,
            is_active=True
        ).order_by('-scheduled_date').first()

        if past_schedule:
            next_date = past_schedule.scheduled_date + timedelta(days=32)
            next_date = next_date.replace(day=min(5, 28))
            return Response(
                {
                    "success": True,
                    "data": {
                        "next_pickup_date": str(next_date),
                        "message": "Waste given before assigned date. Switched to next scheduled date."
                    }
                },
                status=status.HTTP_200_OK
            )

        next_date = today.replace(day=5) + timedelta(days=32)
        next_date = next_date.replace(day=5)
        return Response(
            {
                "success": True,
                "data": {
                    "next_pickup_date": str(next_date),
                    "message": "No scheduled pickup. Default next date set."
                }
            },
            status=status.HTTP_200_OK
        )
