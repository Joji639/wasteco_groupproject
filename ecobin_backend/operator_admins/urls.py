from django.urls import path
from .views import (
    OperatorOnboardingListView, OperatorOnboardingApproveView,
    OperatorOnboardingRejectView, AdminUserOnboardingListView,
    AdminUserOnboardingApproveView, AdminUserOnboardingRejectView,
    OperatorAdminPickupListView, OperatorAdminPickupDetailView,
    OperatorAdminPickupAcceptView, OperatorAdminPickupRejectView,
    OperatorAdminPickupAssignView,
    OperatorAdminOperatorRatingsView, OperatorAdminOperatorReviewsView,
    OperatorAdminOnboardingView,
    ScheduledPickupCreateView, ScheduledPickupUpdateView,
    ScheduledPickupDeleteView, ScheduledPickupListView,
    AreaCreateView, AreaListView, AreaDeleteView,
    AreaAssignOperatorView, AreaRemoveOperatorView, AreaAssignmentListView,
    WasteCollectionReportView, WasteCollectionReportByOperatorView, WasteCollectionListView,
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

    # Operator admin self onboarding
    path('onboarding/', OperatorAdminOnboardingView.as_view(), name='oa-self-onboarding'),

    # Scheduled pickups
    path('scheduled-pickups/', ScheduledPickupListView.as_view(), name='oa-scheduled-pickup-list'),
    path('scheduled-pickups/create/', ScheduledPickupCreateView.as_view(), name='oa-scheduled-pickup-create'),
    path('scheduled-pickups/<uuid:pickup_id>/update/', ScheduledPickupUpdateView.as_view(), name='oa-scheduled-pickup-update'),
    path('scheduled-pickups/<uuid:pickup_id>/delete/', ScheduledPickupDeleteView.as_view(), name='oa-scheduled-pickup-delete'),

    # Area management
    path('areas/', AreaListView.as_view(), name='oa-area-list'),
    path('areas/create/', AreaCreateView.as_view(), name='oa-area-create'),
    path('areas/<uuid:area_id>/delete/', AreaDeleteView.as_view(), name='oa-area-delete'),
    path('areas/<uuid:area_id>/assignments/', AreaAssignmentListView.as_view(), name='oa-area-assignment-list'),
    path('areas/<uuid:area_id>/assign-operator/', AreaAssignOperatorView.as_view(), name='oa-area-assign-operator'),
    path('areas/<uuid:area_id>/assignments/<uuid:assignment_id>/remove/', AreaRemoveOperatorView.as_view(), name='oa-area-remove-operator'),

    # Waste collection reports
    path('waste-collections/', WasteCollectionListView.as_view(), name='oa-waste-collection-list'),
    path('waste-collections/report/', WasteCollectionReportView.as_view(), name='oa-waste-collection-report'),
    path('waste-collections/report/<uuid:operator_id>/', WasteCollectionReportByOperatorView.as_view(), name='oa-waste-collection-report-by-operator'),
]
