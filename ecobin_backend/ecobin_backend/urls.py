from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('api/users/', include('users.urls')),
    path('api/operators/', include('operators.urls')),
    path('api/operator-admins/', include('operator_admins.urls')),
    path('api/superadmins/', include('superadmins.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/', include('complaints.urls')),
    path('api/', include('chat.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
