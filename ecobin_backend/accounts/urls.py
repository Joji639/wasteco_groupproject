from django.urls import path
from .views import (
    UserRegistrationView, UserLoginView,
    ForgotPasswordRequestView, ResetPasswordView, GoogleAuthView,
    StaffRegistrationView, StaffLoginView,
    Setup2FAView, Verify2FAView, Disable2FAView, LoginWith2FAView,
)

urlpatterns = [
    path('registeruser/', UserRegistrationView.as_view(), name='register-user'),
    path('register/', StaffRegistrationView.as_view(), name='register-staff'),
    path('login/', StaffLoginView.as_view(), name='login-staff'),
    path('loginuser/', UserLoginView.as_view(), name='login-user'),
    path('2fasetup/', Setup2FAView.as_view(), name='2fa-setup'),
    path('2faverify/', Verify2FAView.as_view(), name='2fa-verify'),
    path('2fadisable/', Disable2FAView.as_view(), name='2fa-disable'),
    path('2falogin/', LoginWith2FAView.as_view(), name='2fa-login'),
    path('forgotpassword/', ForgotPasswordRequestView.as_view(), name='forgot-password'),
    path('resetpassword/', ResetPasswordView.as_view(), name='reset-password'),
    path('googleauth/', GoogleAuthView.as_view(), name='google-auth'),
]
