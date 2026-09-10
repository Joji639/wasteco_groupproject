from django.urls import path
from .views import (
    AdminLoginView, AdminUserListView, AdminOperatorListView,
    AdminOperatorAdminListView, AdminOnboardingListView,
    SuperAdminOperatorRatingsView,
)

urlpatterns = [
    path('login/', AdminLoginView.as_view(), name='admin-login'),
    path('users/', AdminUserListView.as_view(), name='admin-users'),
    path('operators/', AdminOperatorListView.as_view(), name='admin-operators'),
    path('operator-admins/', AdminOperatorAdminListView.as_view(), name='admin-operatoradmins'),
    path('onboardings/', AdminOnboardingListView.as_view(), name='admin-onboardings'),
    path('operators/ratings/', SuperAdminOperatorRatingsView.as_view(), name='admin-operator-ratings'),
]
