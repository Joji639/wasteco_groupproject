from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsVerifiedForActions
from ..models import WastePickupRequest
from ..serializers import WastePickupRequestSerializer


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
