from django.urls import path
from . import views

urlpatterns = [
    path('create/', views.ServiceRequestCreateView.as_view(), name='service-create'),
    path('', views.ServiceRequestListView.as_view(), name='service-list'),
    path('<uuid:service_id>/', views.ServiceRequestDetailView.as_view(), name='service-detail'),
    path('<uuid:service_id>/accept/', views.ServiceRequestAcceptView.as_view(), name='service-accept'),
    path('<uuid:service_id>/reject/', views.ServiceRequestRejectView.as_view(), name='service-reject'),
    path('<uuid:service_id>/assign-technician/', views.ServiceRequestAssignTechnicianView.as_view(), name='service-assign-technician'),
    path('<uuid:service_id>/technician-location/', views.ServiceRequestTechnicianLocationUpdateView.as_view(), name='service-technician-location'),
    path('<uuid:service_id>/status/<str:new_status>/', views.ServiceRequestStatusUpdateView.as_view(), name='service-status-update'),
    path('<uuid:service_id>/cancel/', views.ServiceRequestCancelView.as_view(), name='service-cancel'),
]
