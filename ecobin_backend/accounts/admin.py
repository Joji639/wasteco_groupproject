from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from .models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('email', 'username', 'base_role', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('base_role', 'is_active', 'is_staff')
    search_fields = ('email', 'username')
    ordering = ('-date_joined',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('username', 'phone', 'base_role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('2FA', {'fields': ('totp_secret', 'is_2fa_enabled')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'base_role', 'is_active', 'is_staff'),
        }),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'address', 'ward_no', 'is_verified')
    list_filter = ('is_verified',)
    search_fields = ('user__email',)


@admin.register(OperatorProfile)
class OperatorProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'operator_id', 'ward_no', 'is_verified')
    list_filter = ('is_verified',)
    search_fields = ('operator_id', 'user__email')


@admin.register(OperatorAdminProfile)
class OperatorAdminProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'operator_id', 'panchayath', 'is_verified')
    list_filter = ('is_verified',)
    search_fields = ('operator_id', 'user__email')


@admin.register(OperatorOnboarding)
class OperatorOnboardingAdmin(admin.ModelAdmin):
    list_display = ('user', 'approved', 'approved_by', 'created_at')
    list_filter = ('approved',)
    search_fields = ('user__email',)
