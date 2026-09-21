import logging

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer

from accounts.permissions import IsUserRole

from .services import call_groq, normalize_result, prepare_image

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_SIZE = 5 * 1024 * 1024


def _build_message(category, percentage, item):
    if category == "plastic":
        return f"This looks like plastic waste ({percentage}% sure)."
    if category == "e-waste":
        return f"This looks like e-waste ({percentage}% sure)."
    return "This is neither plastic waste nor e-waste."


class WasteScanView(APIView):
    permission_classes = [IsUserRole]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "waste_scan"

    @extend_schema(
        tags=["Waste Scanner"],
        request=inline_serializer(
            name="WasteScanRequest",
            fields={
                "image": serializers.ImageField(help_text="Upload waste image file (JPEG or PNG, max 5 MB)")
            }
        ),
        responses={
            200: inline_serializer(
                name="WasteScanResponse",
                fields={
                    "success": serializers.BooleanField(),
                    "message": serializers.CharField(),
                    "data": inline_serializer(
                        name="WasteScanResult",
                        fields={
                            "category": serializers.CharField(help_text="plastic | e-waste | neither"),
                            "percentage": serializers.IntegerField(help_text="Confidence percentage 0-100"),
                            "item": serializers.CharField(help_text="Detected item description"),
                            "message": serializers.CharField(),
                        }
                    )
                }
            ),
            400: inline_serializer(
                name="WasteScanError400",
                fields={"success": serializers.BooleanField(), "message": serializers.CharField()}
            ),
            502: inline_serializer(
                name="WasteScanError502",
                fields={"success": serializers.BooleanField(), "message": serializers.CharField()}
            ),
            503: inline_serializer(
                name="WasteScanError503",
                fields={"success": serializers.BooleanField(), "message": serializers.CharField()}
            ),
        }
    )
    def post(self, request):
        image = request.FILES.get("image")
        if not image:
            return Response(
                {"success": False, "message": "No image provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if image.content_type not in ALLOWED_TYPES:
            return Response(
                {"success": False, "message": "Unsupported file type. Use JPEG or PNG."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if image.size > MAX_SIZE:
            return Response(
                {"success": False, "message": "File too large. Maximum size is 5 MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        threshold = getattr(settings, "CONFIDENCE_THRESHOLD", 60)

        try:
            data_url = prepare_image(image)
            raw = call_groq(data_url)
            result = normalize_result(raw)
        except Exception as exc:
            error_str = str(exc).lower()
            if "429" in error_str or "rate" in error_str or "too many" in error_str:
                logger.warning("Groq rate limit: %s", exc)
                return Response(
                    {
                        "success": False,
                        "message": "Scanner is busy, please try again in a minute.",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if isinstance(exc, (ValueError, KeyError, TypeError)):
                logger.warning("Failed to parse Groq response: %s", exc)
                return Response(
                    {
                        "success": False,
                        "message": "Could not process the scanner result.",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            if "json" in error_str or "decode" in error_str:
                logger.warning("Invalid JSON from Groq: %s", exc)
                return Response(
                    {
                        "success": False,
                        "message": "Could not process the scanner result.",
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            logger.exception("Waste scan failed")
            return Response(
                {"success": False, "message": "Scanner service unavailable."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if result["percentage"] < threshold:
            result["category"] = "neither"

        message = _build_message(result["category"], result["percentage"], result["item"])

        if result["category"] == "neither" and result["percentage"] < threshold:
            message += " Try a clearer photo."

        return Response(
            {
                "success": True,
                "message": "Scan complete.",
                "data": {
                    "category": result["category"],
                    "percentage": result["percentage"],
                    "item": result["item"],
                    "message": message,
                },
            },
            status=status.HTTP_200_OK,
        )
