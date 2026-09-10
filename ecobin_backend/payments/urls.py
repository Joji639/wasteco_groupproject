from django.urls import path
from .views import (
    OperatorAssignedPickupsView,
    OperatorStartTaskView,
    OperatorRecordCollectionView,
    OperatorCollectionView,
    OperatorCollectionDetailView,
    OperatorInitiatePaymentView,
    PaymentStatusView,
    razorpay_webhook,
)

urlpatterns = [
    # Operator task management
    path('operator/assigned-pickups/', OperatorAssignedPickupsView.as_view(), name='operator-assigned-pickups'),
    path('operator/pickups/<uuid:pickup_id>/start/', OperatorStartTaskView.as_view(), name='operator-start-task'),

    # Waste collection recording
    path('operator/collections/', OperatorCollectionView.as_view(), name='operator-collection-list'),
    path('operator/collections/create/', OperatorRecordCollectionView.as_view(), name='operator-create-collection'),
    path('operator/collections/<uuid:collection_id>/', OperatorCollectionDetailView.as_view(), name='operator-collection-detail'),

    # Payment initiation (operator)
    path('operator/collections/<uuid:collection_id>/payment/', OperatorInitiatePaymentView.as_view(), name='operator-initiate-payment'),

    # Payment status (user)
    path('user/pickups/<uuid:pickup_id>/payment/status/', PaymentStatusView.as_view(), name='payment-status'),

    # Razorpay webhook (unauthenticated)
    path('razorpay/webhook/', razorpay_webhook, name='razorpay-webhook'),
]
