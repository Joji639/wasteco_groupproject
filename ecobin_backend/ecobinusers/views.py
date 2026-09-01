from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.utils import timezone
from datetime import timedelta
from .models import (
    WastePickupRequest, PickupSchedule, Review,
    Payment, WasteCollection, Complaint,
)
from .serializers import (
    WastePickupRequestSerializer, PickupScheduleSerializer, ReviewSerializer,
    PaymentSerializer, WasteCollectionSerializer, ComplaintSerializer,
)
from accounts.permissions import IsVerifiedForActions


class WastePickupRequestCreateView(APIView):
    """User creates a waste pickup request."""
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
    """User views their own waste pickup requests."""
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
    """Returns the next pickup date for the user."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Pickup Date'],
        responses={200: PickupScheduleSerializer}
    )
    def get(self, request):
        today = timezone.now().date()

        # Check for a future/active pickup
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

        # Check for a past schedule — waste given before date, switch to next
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

        # No schedule at all — set default
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


class ReviewCreateView(APIView):
    """User submits a review after operator finishes pickup."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Reviews'],
        request=ReviewSerializer,
        responses={201: ReviewSerializer}
    )
    def post(self, request):
        if request.user.base_role != 'user':
            return Response(
                {"success": False, "message": "Only users can submit reviews"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ReviewSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            review = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to submit review", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Review submitted successfully.",
                "data": ReviewSerializer(review).data,
            },
            status=status.HTTP_201_CREATED
        )


class ReviewListView(APIView):
    """User views their own reviews."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Reviews'],
        responses={200: ReviewSerializer(many=True)}
    )
    def get(self, request):
        queryset = Review.objects.filter(user=request.user).order_by('-created_at')
        serializer = ReviewSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class PaymentHistoryView(APIView):
    """Returns user's payment records."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Payments'],
        responses={200: PaymentSerializer(many=True)}
    )
    def get(self, request):
        queryset = Payment.objects.filter(user=request.user).order_by('-created_at')
        serializer = PaymentSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class WasteCollectionHistoryView(APIView):
    """Returns user's waste collection history."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Collections'],
        responses={200: WasteCollectionSerializer(many=True)}
    )
    def get(self, request):
        queryset = WasteCollection.objects.filter(user=request.user).order_by('-date', '-time')
        serializer = WasteCollectionSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class ComplaintListView(APIView):
    """Returns user's complaints with optional filter."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Complaints'],
        parameters=[
            OpenApiParameter("filter", str, enum=["all", "open", "resolved", "pending"], description="Filter by status"),
        ],
        responses={200: ComplaintSerializer(many=True)}
    )
    def get(self, request):
        queryset = Complaint.objects.filter(user=request.user).order_by('-created_at')

        filter_param = request.query_params.get('filter', 'all')
        if filter_param == 'open':
            queryset = queryset.filter(status='open')
        elif filter_param == 'resolved':
            queryset = queryset.filter(status='resolved')
        elif filter_param == 'pending':
            queryset = queryset.filter(status='pending')

        serializer = ComplaintSerializer(queryset, many=True)
        return Response(
            {"success": True, "count": len(serializer.data), "data": serializer.data},
            status=status.HTTP_200_OK
        )


class ComplaintCreateView(APIView):
    """User creates a complaint."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['User - Complaints'],
        request=ComplaintSerializer,
        responses={201: ComplaintSerializer}
    )
    def post(self, request):
        serializer = ComplaintSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        try:
            complaint = serializer.save()
        except Exception as e:
            return Response(
                {"success": False, "message": "Failed to create complaint", "errors": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Complaint submitted successfully.",
                "data": ComplaintSerializer(complaint).data,
            },
            status=status.HTTP_201_CREATED
        )
