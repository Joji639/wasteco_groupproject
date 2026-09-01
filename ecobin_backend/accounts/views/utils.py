def can_approve(request, onboarding):
    target_role = onboarding.user.base_role
    if target_role == 'operatoradmin':
        return request.user.base_role == 'superadmin'
    return request.user.base_role == 'operatoradmin'
