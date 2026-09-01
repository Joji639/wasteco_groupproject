from django.urls import path
from .views import (
    WastePickupRequestCreateView, WastePickupRequestListView,
    PickupDateView, ReviewCreateView, ReviewListView,
    PaymentHistoryView, WasteCollectionHistoryView,
    ComplaintListView, ComplaintCreateView,
)

urlpatterns = [
    path('requests/', WastePickupRequestCreateView.as_view(), name='waste-request-create'),
    path('requests/list/', WastePickupRequestListView.as_view(), name='waste-request-list'),
    path('pickup-date/', PickupDateView.as_view(), name='pickup-date'),
    path('reviews/', ReviewCreateView.as_view(), name='review-create'),
    path('reviews/list/', ReviewListView.as_view(), name='review-list'),
    path('payments/', PaymentHistoryView.as_view(), name='payment-history'),
    path('collections/', WasteCollectionHistoryView.as_view(), name='collection-history'),
    path('complaints/', ComplaintListView.as_view(), name='complaint-list'),
    path('complaints/create/', ComplaintCreateView.as_view(), name='complaint-create'),
]
