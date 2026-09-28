from django.urls import path
from .views import (
    AdminLoginView, AdminUserListView, AdminOperatorListView,
    AdminOperatorAdminListView, AdminOnboardingListView,
    AdminOAOnboardingListView, AdminOAOnboardingApproveView,
    AdminOAOnboardingRejectView,
)

urlpatterns = [
    path('login/', AdminLoginView.as_view(), name='admin-login'),
    path('users/', AdminUserListView.as_view(), name='admin-users'),
    path('operators/', AdminOperatorListView.as_view(), name='admin-operators'),
    path('operator-admins/', AdminOperatorAdminListView.as_view(), name='admin-operatoradmins'),
    path('onboardings/', AdminOnboardingListView.as_view(), name='admin-onboardings'),
    path('oa-onboardings/', AdminOAOnboardingListView.as_view(), name='admin-oa-onboardings'),
    path('oa-onboardings/approve/', AdminOAOnboardingApproveView.as_view(), name='admin-oa-onboarding-approve'),
    path('oa-onboardings/reject/', AdminOAOnboardingRejectView.as_view(), name='admin-oa-onboarding-reject'),
]
