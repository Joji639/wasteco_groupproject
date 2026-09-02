from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import permissions, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Complaint
from ..serializers import ComplaintSerializer


class ComplaintListView(APIView):
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
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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
