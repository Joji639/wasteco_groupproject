from django.urls import path
from . import views

urlpatterns = [
    # Communities
    path('operator-admin/communities/', views.CommunityCreateView.as_view(), name='community-create'),
    path('communities/', views.CommunityListView.as_view(), name='community-list'),
    path('communities/<int:community_id>/', views.CommunityDetailView.as_view(), name='community-detail'),
    path('operator-admin/communities/<int:community_id>/', views.CommunityUpdateView.as_view(), name='community-update'),
    path('operator-admin/communities/<int:community_id>/deactivate/', views.CommunityDeactivateView.as_view(), name='community-deactivate'),

    # Members
    path('communities/<int:community_id>/members/', views.MemberListView.as_view(), name='member-list'),
    path('communities/<int:community_id>/members/add/', views.MemberAddView.as_view(), name='member-add'),
    path('operator-admin/communities/<int:community_id>/members/<int:member_id>/', views.MemberRemoveView.as_view(), name='member-remove'),
    path('operator-admin/communities/<int:community_id>/members/<int:member_id>/permissions/', views.MemberPermissionView.as_view(), name='member-permissions'),

    # Messages
    path('communities/<int:community_id>/messages/', views.MessageHistoryView.as_view(), name='message-history'),
]
