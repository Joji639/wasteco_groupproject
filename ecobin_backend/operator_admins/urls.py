from django.urls import path
from .views import (
    OperatorOnboardingListView, OperatorOnboardingApproveView,
    OperatorOnboardingRejectView, AdminUserOnboardingListView,
    AdminUserOnboardingApproveView, AdminUserOnboardingRejectView,
    OperatorAdminPickupListView, OperatorAdminPickupDetailView,
    OperatorAdminPickupAcceptView, OperatorAdminPickupRejectView,
    OperatorAdminPickupAssignView,
    OperatorAdminOperatorRatingsView, OperatorAdminOperatorReviewsView,
)

urlpatterns = [
    # Operator onboarding management
    path('onboardings/', OperatorOnboardingListView.as_view(), name='oa-onboarding-list'),
    path('onboardings/approve/', OperatorOnboardingApproveView.as_view(), name='oa-onboarding-approve'),
    path('onboardings/reject/', OperatorOnboardingRejectView.as_view(), name='oa-onboarding-reject'),

    # User onboarding management
    path('user-onboardings/', AdminUserOnboardingListView.as_view(), name='oa-user-onboarding-list'),
    path('user-onboardings/approve/', AdminUserOnboardingApproveView.as_view(), name='oa-user-onboarding-approve'),
    path('user-onboardings/reject/', AdminUserOnboardingRejectView.as_view(), name='oa-user-onboarding-reject'),

    # Pickup management
    path('pickups/', OperatorAdminPickupListView.as_view(), name='oa-pickup-list'),
    path('pickups/<uuid:pickup_id>/', OperatorAdminPickupDetailView.as_view(), name='oa-pickup-detail'),
    path('pickups/<uuid:pickup_id>/accept/', OperatorAdminPickupAcceptView.as_view(), name='oa-pickup-accept'),
    path('pickups/<uuid:pickup_id>/reject/', OperatorAdminPickupRejectView.as_view(), name='oa-pickup-reject'),
    path('pickups/<uuid:pickup_id>/assign-operator/', OperatorAdminPickupAssignView.as_view(), name='oa-pickup-assign'),

    # Operator ratings
    path('operators/ratings/', OperatorAdminOperatorRatingsView.as_view(), name='oa-operator-ratings'),
    path('operators/<uuid:operator_id>/reviews/', OperatorAdminOperatorReviewsView.as_view(), name='oa-operator-reviews'),
]
