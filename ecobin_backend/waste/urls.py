from django.urls import path

from .views import WasteScanView

urlpatterns = [
    path("scan/", WasteScanView.as_view(), name="waste-scan"),
]
