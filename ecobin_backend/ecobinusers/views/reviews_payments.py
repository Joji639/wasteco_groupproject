from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Review, Payment, WasteCollection
from ..serializers import (
    ReviewSerializer, PaymentSerializer, WasteCollectionSerializer,
)


class ReviewCreateView(APIView):
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
