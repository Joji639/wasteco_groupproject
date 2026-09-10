from django.urls import path
from .views import (
    OnboardingView, LogoutView, AccountInfoView,
    PersonalInfoView, ChangePasswordView,
    PickupRequestCreateView,
    UserReviewCreateView, UserReviewDetailView,
)

urlpatterns = [
    path('onboarding/', OnboardingView.as_view(), name='user-onboarding'),
    path('logout/', LogoutView.as_view(), name='user-logout'),
    path('account-info/', AccountInfoView.as_view(), name='user-account-info'),
    path('personal-info/', PersonalInfoView.as_view(), name='user-personal-info'),
    path('change-password/', ChangePasswordView.as_view(), name='user-change-password'),
    path('pickups/', PickupRequestCreateView.as_view(), name='user-pickup-create'),
    path('pickups/<uuid:pickup_id>/review/', UserReviewCreateView.as_view(), name='user-pickup-review-create'),
    path('pickups/<uuid:pickup_id>/review/detail/', UserReviewDetailView.as_view(), name='user-pickup-review-detail'),
]
