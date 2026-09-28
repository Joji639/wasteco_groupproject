from django.urls import path
from .views import (
    OperatorAssignedPickupsView,
    OperatorRecordCollectionView,
    OperatorCollectionView,
    OperatorCollectionDetailView,
    OperatorInitiatePaymentView,
    PaymentStatusView,
    UserPickupPaymentsView,
    razorpay_webhook,
)

urlpatterns = [
    path('operator/assigned-pickups/', OperatorAssignedPickupsView.as_view(), name='operator-assigned-pickups'),
    path('operator/collections/', OperatorCollectionView.as_view(), name='operator-collection-list'),
    path('operator/collections/create/', OperatorRecordCollectionView.as_view(), name='operator-create-collection'),
    path('operator/collections/<uuid:collection_id>/', OperatorCollectionDetailView.as_view(), name='operator-collection-detail'),
    path('operator/collections/<uuid:collection_id>/payment/', OperatorInitiatePaymentView.as_view(), name='operator-initiate-payment'),
    path('user/pickups/<uuid:pickup_id>/payment/status/', PaymentStatusView.as_view(), name='payment-status'),
    path('user/payments/', UserPickupPaymentsView.as_view(), name='user-payments-list'),
    path('razorpay/webhook/', razorpay_webhook, name='razorpay-webhook'),
]
