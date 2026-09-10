from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('users/', include('users.urls')),
    path('operators/', include('operators.urls')),
    path('operator-admins/', include('operator_admins.urls')),
    path('superadmins/', include('superadmins.urls')),
    path('payments/', include('payments.urls')),
    path('', include('complaints.urls')),
    path('', include('chat.urls')),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
