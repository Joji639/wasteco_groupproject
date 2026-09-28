from django.db import models


import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from phonenumber_field.modelfields import PhoneNumberField
from cloudinary.models import CloudinaryField
from .managers import UserManager


class CustomUser(AbstractBaseUser, PermissionsMixin):

    ROLE_CHOICES = (
        ('user', 'User'),
        ('operator', 'Operator'),
        ('operatoradmin', 'Operator Admin'),
        ('superadmin', 'Super Admin'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    username = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True)
    phone = PhoneNumberField(unique=True, null=True, blank=True)

    base_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    totp_secret = models.CharField(max_length=64, blank=True, null=True)
    is_2fa_enabled = models.BooleanField(default=False)


    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return f"{self.email} ({self.base_role})"

    @property
    def staff_operator_id(self):
        attr = 'operatoradmin_profile' if self.base_role == 'operatoradmin' else 'operator_profile'
        profile = getattr(self, attr, None)
        return profile.operator_id if profile else None


def generate_operator_id():
    """Placeholder default — actual prefixed ID is set in save() based on role."""
    return str(uuid.uuid4()).split('-')[0].upper()


class UserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='user_profile')

    address = models.CharField(max_length=255, blank=True, null=True)
    current_location = models.CharField(max_length=255, blank=True, null=True)
    house_number = models.CharField(max_length=50, blank=True, null=True)
    pin = models.CharField(max_length=10, blank=True, null=True)
    ward_no = models.CharField(max_length=20, blank=True, null=True)

    pan_card_image = CloudinaryField('pan_card', blank=True, null=True)
    house_tax_receipt = CloudinaryField('house_tax_receipt', blank=True, null=True)
    rent_agreement = CloudinaryField('rent_agreement', blank=True, null=True)

    is_verified = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True, default='')
    verified_by = models.ForeignKey(
        'OperatorAdminProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_users'
    )

    def __str__(self):
        return f"UserProfile: {self.user.email}"


class OperatorAdminProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='operatoradmin_profile')

    operator_id = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    panchayath = models.CharField(max_length=100)

    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_operatoradmins',
        limit_choices_to={'base_role': 'superadmin'}
    )

    def save(self, *args, **kwargs):
        if not self.operator_id:
            self.operator_id = f"OA-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OperatorAdmin: {self.operator_id} (Panchayath {self.panchayath})"


class OperatorProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='operator_profile')

    operator_id = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    ward_no = models.CharField(max_length=20)

    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        OperatorAdminProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_operators'
    )
    assigned_admin = models.ForeignKey(
        OperatorAdminProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_operators'
    )

    def save(self, *args, **kwargs):
        if not self.operator_id:
            self.operator_id = f"OP-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Operator: {self.operator_id} (Ward {self.ward_no})"


class OperatorOnboarding(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='operator_onboarding'
    )

    photo = CloudinaryField('photo', blank=True, null=True)
    pan_number = models.CharField(max_length=10, blank=True)
    pan_image = CloudinaryField('pan_image', blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, blank=True)
    aadhaar_image = CloudinaryField('aadhaar_image', blank=True, null=True)

    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_staff_onboardings'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Onboarding: {self.user.email} (approved={self.approved})"


class OperatorAdminOnboarding(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='operatoradmin_onboarding'
    )

    photo = CloudinaryField('photo', blank=True, null=True)
    pan_number = models.CharField(max_length=10, blank=True)
    pan_image = CloudinaryField('pan_image', blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, blank=True)
    aadhaar_image = CloudinaryField('aadhaar_image', blank=True, null=True)

    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_oa_onboardings'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OA Onboarding: {self.user.email} (approved={self.approved})"