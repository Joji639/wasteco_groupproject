from django.urls import path
from .views import (
    UserComplaintCreateView, UserComplaintListView, UserComplaintDetailView,
    OperatorAdminComplaintListView, OperatorAdminComplaintDetailView,
    OperatorAdminAssignComplaintView,
    OperatorComplaintListView, OperatorComplaintDetailView,
    OperatorComplaintStatusView,
)

urlpatterns = [
    # User complaint endpoints
    path('user/complaints/', UserComplaintCreateView.as_view(), name='user-complaint-create'),
    path('user/complaints/list/', UserComplaintListView.as_view(), name='user-complaint-list'),
    path('user/complaints/<int:complaint_id>/', UserComplaintDetailView.as_view(), name='user-complaint-detail'),

    # Operator Admin complaint endpoints
    path('operator-admin/complaints/', OperatorAdminComplaintListView.as_view(), name='oa-complaint-list'),
    path('operator-admin/complaints/<int:complaint_id>/', OperatorAdminComplaintDetailView.as_view(), name='oa-complaint-detail'),
    path('operator-admin/complaints/<int:complaint_id>/assign/', OperatorAdminAssignComplaintView.as_view(), name='oa-complaint-assign'),

    # Operator complaint endpoints
    path('operator/complaints/', OperatorComplaintListView.as_view(), name='operator-complaint-list'),
    path('operator/complaints/<int:complaint_id>/', OperatorComplaintDetailView.as_view(), name='operator-complaint-detail'),
    path('operator/complaints/<int:complaint_id>/status/', OperatorComplaintStatusView.as_view(), name='operator-complaint-status'),
]
