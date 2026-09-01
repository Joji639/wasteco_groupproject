from .public_auth import (
    UserRegistrationView,
    UserLoginView,
    ForgotPasswordRequestView,
    ResetPasswordView,
    GoogleAuthView,
    StaffLoginView,
    StaffRegistrationView,
)

from .user_profile import (
    OnboardingView,
    LogoutView,
    AccountInfoView,
    PersonalInfoView,
    ChangePasswordView,
)

from .two_factor import (
    Setup2FAView,
    Verify2FAView,
    Disable2FAView,
    LoginWith2FAView,
)

from .staff import (
    OperatorOnboardingView,
    OperatorAccountInfoView,
    OperatorPersonalInfoView,
    OperatorChangePasswordView,
    OperatorLogoutView,
)

from .operator_admin import (
    OperatorOnboardingListView,
    OperatorOnboardingApproveView,
    OperatorOnboardingRejectView,
    AdminUserOnboardingListView,
    AdminUserOnboardingApproveView,
    AdminUserOnboardingRejectView,
)

from .super_admin import (
    AdminLoginView,
    AdminUserListView,
    AdminOperatorListView,
    AdminOperatorAdminListView,
    AdminOnboardingListView,
)

__all__ = [
    'UserRegistrationView',
    'UserLoginView',
    'ForgotPasswordRequestView',
    'ResetPasswordView',
    'GoogleAuthView',
    'StaffLoginView',
    'StaffRegistrationView',
    'OnboardingView',
    'LogoutView',
    'AccountInfoView',
    'PersonalInfoView',
    'ChangePasswordView',
    'Setup2FAView',
    'Verify2FAView',
    'Disable2FAView',
    'LoginWith2FAView',
    'OperatorOnboardingView',
    'OperatorAccountInfoView',
    'OperatorPersonalInfoView',
    'OperatorChangePasswordView',
    'OperatorLogoutView',
    'OperatorOnboardingListView',
    'OperatorOnboardingApproveView',
    'OperatorOnboardingRejectView',
    'AdminUserOnboardingListView',
    'AdminUserOnboardingApproveView',
    'AdminUserOnboardingRejectView',
    'AdminLoginView',
    'AdminUserListView',
    'AdminOperatorListView',
    'AdminOperatorAdminListView',
    'AdminOnboardingListView',
]
