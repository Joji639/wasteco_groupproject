from django.urls import path
from .views import (
    OperatorOnboardingView, OperatorAccountInfoView,
    OperatorPersonalInfoView, OperatorChangePasswordView,
    OperatorLogoutView, OperatorReviewsView, OperatorRatingSummaryView,
    OperatorAssignedAreasView,
    WasteCollectionCreateView, WasteCollectionFailureView, WasteCollectionHistoryView,
    PickupTrackingStartView, PickupTrackingLocationView,
    PickupTrackingStopView, PickupTrackingActiveView,
)
from .tracking import OperatorUpdateLocationView, OperatorGetLocationView

urlpatterns = [
    path('onboarding/', OperatorOnboardingView.as_view(), name='operator-onboarding'),
    path('account-info/', OperatorAccountInfoView.as_view(), name='operator-account-info'),
    path('personal-info/', OperatorPersonalInfoView.as_view(), name='operator-personal-info'),
    path('change-password/', OperatorChangePasswordView.as_view(), name='operator-change-password'),
    path('logout/', OperatorLogoutView.as_view(), name='operator-logout'),
    path('reviews/', OperatorReviewsView.as_view(), name='operator-reviews'),
    path('reviews/summary/', OperatorRatingSummaryView.as_view(), name='operator-rating-summary'),
    path('location/update/', OperatorUpdateLocationView.as_view(), name='operator-location-update'),
    path('location/<uuid:pickup_id>/', OperatorGetLocationView.as_view(), name='operator-location-get'),
    path('assigned-areas/', OperatorAssignedAreasView.as_view(), name='operator-assigned-areas'),
    path('waste-collection/collect/', WasteCollectionCreateView.as_view(), name='operator-waste-collect'),
    path('waste-collection/fail/', WasteCollectionFailureView.as_view(), name='operator-waste-fail'),
    path('waste-collection/history/', WasteCollectionHistoryView.as_view(), name='operator-waste-history'),
    path('tracking/start/', PickupTrackingStartView.as_view(), name='operator-tracking-start'),
    path('tracking/<uuid:tracking_id>/', PickupTrackingLocationView.as_view(), name='operator-tracking-location'),
    path('tracking/<uuid:tracking_id>/stop/', PickupTrackingStopView.as_view(), name='operator-tracking-stop'),
    path('tracking/active/', PickupTrackingActiveView.as_view(), name='operator-tracking-active'),
]
