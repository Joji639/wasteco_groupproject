from django.urls import path
from .views import (
    OperatorOnboardingView, OperatorAccountInfoView,
    OperatorPersonalInfoView, OperatorChangePasswordView,
    OperatorLogoutView, OperatorReviewsView, OperatorRatingSummaryView,
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
]
