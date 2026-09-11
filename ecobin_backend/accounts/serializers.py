from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from .models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding, OperatorAdminOnboarding
from rest_framework_simplejwt.tokens import RefreshToken


def operator_account_dict(user):
    return {
        'username': user.username,
        'email': user.email,
        'phone': str(user.phone) if user.phone else None,
    }


def staff_profile(user):
    if user.base_role == 'operatoradmin':
        return getattr(user, 'operatoradmin_profile', None)
    return getattr(user, 'operator_profile', None)


class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)


def set_staff_verified(user, value):
    profile = staff_profile(user)
    if profile is not None:
        profile.is_verified = value
        profile.save(update_fields=['is_verified'])


class UserRegistrationSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'phone', 'password', 'confirm_password']

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def validate_phone(self, value):
        if CustomUser.objects.filter(phone=value).exists():
            raise serializers.ValidationError("Phone number already registered")
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match"})
        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')

        user = CustomUser.objects.create_user(
            password=password,
            base_role='user',
            **validated_data
        )
        # Empty profile — is_verified stays False until operator admin approves
        UserProfile.objects.create(user=user)
        return user


class OnboardingSerializer(serializers.ModelSerializer):
    pan_card_image = serializers.ImageField(required=True)
    house_tax_receipt = serializers.FileField(required=False)
    rent_agreement = serializers.FileField(required=False)

    class Meta:
        model = UserProfile
        fields = [
            'address', 'current_location', 'house_number', 'pin',
            'pan_card_image', 'house_tax_receipt', 'rent_agreement'
        ]

    def validate_pin(self, value):
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("PIN must be a 6-digit number")
        return value

    def validate(self, data):
        if not data.get('address') and not data.get('current_location'):
            raise serializers.ValidationError("Either address or current location is required")

        if not data.get('house_tax_receipt') and not data.get('rent_agreement'):
            raise serializers.ValidationError("Either house tax receipt or rent agreement is required")

        return data



class UserLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()   # email or phone
    password = serializers.CharField(write_only=True)


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    refresh['base_role'] = user.base_role
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class AccountInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'phone']

    def validate_email(self, value):
        queryset = CustomUser.objects.filter(email=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def validate_phone(self, value):
        queryset = CustomUser.objects.filter(phone=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Phone number already registered")
        return value


class PersonalInfoSerializer(serializers.ModelSerializer):
    pan_card_image = serializers.ImageField(required=False)
    house_tax_receipt = serializers.FileField(required=False)

    class Meta:
        model = UserProfile
        fields = ['address', 'ward_no', 'pan_card_image', 'house_tax_receipt']

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        # Editing personal info requires re-verification
        instance.is_verified = False
        instance.verified_by = None
        instance.save()
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    confirm_new_password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match"})

        if data['old_password'] == data['new_password']:
            raise serializers.ValidationError({"new_password": "New password must be different from the old password"})

        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=True)


class Verify2FASerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=6, min_length=6)


class Disable2FASerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, required=True)


class LoginWith2FASerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False)   # email or phone
    operator_id = serializers.CharField(required=False)  # OP-xxxxx / OA-xxxxx
    code = serializers.CharField(required=True, max_length=6, min_length=6)

    def validate(self, data):
        if not data.get('identifier') and not data.get('operator_id'):
            raise serializers.ValidationError(
                "Provide either 'identifier' (email/phone) or 'operator_id'"
            )
        return data


class ForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True, max_length=6, min_length=6)
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    confirm_new_password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "Passwords do not match"})
        return data

class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True)



class StaffLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False)  # email or phone
    operator_id = serializers.CharField(required=False)  # OP-xxxxx / OA-xxxxx
    password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if not data.get('identifier') and not data.get('operator_id'):
            raise serializers.ValidationError(
                "Provide either 'identifier' (email/phone) or 'operator_id'"
            )
        return data


class StaffRegistrationSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=['operator', 'operatoradmin'], write_only=True)
    ward_no = serializers.CharField(required=False, write_only=True)
    panchayath = serializers.CharField(required=False, write_only=True)
    phone = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'phone', 'role', 'ward_no', 'panchayath', 'password', 'confirm_password']

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def validate_phone(self, value):
        if CustomUser.objects.filter(phone=value).exists():
            raise serializers.ValidationError("Phone number already registered")
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match"})

        role = data.get('role')
        if role == 'operatoradmin' and not data.get('panchayath'):
            raise serializers.ValidationError({"panchayath": "Panchayath/Municipality is required for operator admin"})
        if role != 'operatoradmin' and not data.get('ward_no'):
            raise serializers.ValidationError({"ward_no": "Ward number is required for operators"})

        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')
        role = validated_data.pop('role')
        ward_no = validated_data.pop('ward_no', None)
        panchayath = validated_data.pop('panchayath', None)

        user = CustomUser.objects.create_user(
            password=password,
            base_role=role,
            **validated_data
        )

        if role == 'operatoradmin':
            OperatorAdminProfile.objects.create(user=user, panchayath=panchayath)
        else:
            OperatorProfile.objects.create(user=user, ward_no=ward_no)
        return user


class OperatorOnboardingSerializer(serializers.ModelSerializer):
    pan_number = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^[A-Z]{5}[0-9]{4}[A-Z]$',
            message='Enter a valid PAN number (e.g. ABCDE1234F).'
        )]
    )
    aadhaar_number = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^\d{12}$',
            message='Aadhaar must be exactly 12 digits.'
        )]
    )
    photo = serializers.ImageField(required=False, allow_null=True)
    pan_image = serializers.ImageField(required=False, allow_null=True)
    aadhaar_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = OperatorOnboarding
        fields = [
            'id', 'user', 'photo', 'pan_number', 'pan_image',
            'aadhaar_number', 'aadhaar_image', 'approved', 'approved_by',
            'approved_at', 'rejection_reason', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'approved', 'approved_by',
            'approved_at', 'rejection_reason', 'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        if instance.approved:
            instance.approved = False
            instance.approved_at = None
            instance.approved_by = None
            instance.rejection_reason = ''
            instance.save(update_fields=[
                'approved', 'approved_at', 'approved_by', 'rejection_reason', 'updated_at'
            ])
            set_staff_verified(instance.user, False)
        return instance


class OperatorOnboardingAdminSerializer(OperatorOnboardingSerializer):
    account = serializers.SerializerMethodField()
    role = serializers.CharField(source='user.base_role', read_only=True)

    class Meta(OperatorOnboardingSerializer.Meta):
        fields = OperatorOnboardingSerializer.Meta.fields + ['account', 'role']
        read_only_fields = OperatorOnboardingSerializer.Meta.read_only_fields + ['role']

    def get_account(self, obj):
        return operator_account_dict(obj.user)


class OperatorPersonalInfoSerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()

    class Meta:
        model = OperatorOnboarding
        fields = [
            'id', 'account', 'photo', 'pan_number', 'pan_image',
            'aadhaar_number', 'aadhaar_image', 'approved',
            'rejection_reason', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_account(self, obj):
        return operator_account_dict(obj.user)


class RejectOnboardingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, max_length=500)


class AdminUserListSerializer(serializers.ModelSerializer):
    is_verified = serializers.SerializerMethodField()
    onboarding_status = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'phone', 'is_active',
            'is_verified', 'onboarding_status', 'date_joined',
        ]
        read_only_fields = fields

    def get_is_verified(self, obj):
        profile = getattr(obj, 'user_profile', None)
        return bool(profile and profile.is_verified)

    def get_onboarding_status(self, obj):
        profile = getattr(obj, 'user_profile', None)
        if profile is None:
            return 'not_submitted'
        if not profile.address and not profile.current_location:
            return 'not_submitted'
        return 'verified' if profile.is_verified else 'pending_verification'


class AdminUserOnboardingSerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()
    role = serializers.CharField(source='user.base_role', read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    verified_by = serializers.SerializerMethodField()
    pan_card_image = serializers.SerializerMethodField()
    house_tax_receipt = serializers.SerializerMethodField()
    rent_agreement = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'account', 'role', 'address', 'current_location',
            'house_number', 'pin', 'ward_no', 'pan_card_image',
            'house_tax_receipt', 'rent_agreement', 'rejection_reason',
            'is_verified', 'verified_by',
        ]
        read_only_fields = fields

    def get_account(self, obj):
        user = obj.user
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": str(user.phone) if user.phone else None,
            "is_active": user.is_active,
        }

    def get_verified_by(self, obj):
        if obj.verified_by:
            return {
                "operator_id": obj.verified_by.operator_id,
                "panchayath": obj.verified_by.panchayath,
            }
        return None

    def get_pan_card_image(self, obj):
        if not obj.pan_card_image:
            return None
        return getattr(obj.pan_card_image, 'url', str(obj.pan_card_image))

    def get_house_tax_receipt(self, obj):
        if not obj.house_tax_receipt:
            return None
        return getattr(obj.house_tax_receipt, 'url', str(obj.house_tax_receipt))

    def get_rent_agreement(self, obj):
        if not obj.rent_agreement:
            return None
        return getattr(obj.rent_agreement, 'url', str(obj.rent_agreement))


def staff_onboarding_status(user):
    onboarding = getattr(user, 'operator_onboarding', None)
    if onboarding is None:
        return 'not_submitted'
    if onboarding.approved:
        return 'approved'
    if onboarding.rejection_reason:
        return 'rejected'
    return 'pending'


class AdminStaffListSerializer(serializers.ModelSerializer):
    operator_id = serializers.SerializerMethodField()
    ward_no = serializers.SerializerMethodField()
    panchayath = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()
    onboarding_status = serializers.SerializerMethodField()
    role = serializers.CharField(source='base_role', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'phone', 'role', 'operator_id', 'ward_no',
            'panchayath', 'is_active', 'is_verified', 'onboarding_status', 'date_joined',
        ]
        read_only_fields = fields

    def _profile(self, obj):
        if obj.base_role == 'operatoradmin':
            return getattr(obj, 'operatoradmin_profile', None)
        return getattr(obj, 'operator_profile', None)

    def get_operator_id(self, obj):
        profile = self._profile(obj)
        return profile.operator_id if profile else None

    def get_ward_no(self, obj):
        if obj.base_role == 'operatoradmin':
            return None
        profile = getattr(obj, 'operator_profile', None)
        return profile.ward_no if profile else None

    def get_panchayath(self, obj):
        if obj.base_role != 'operatoradmin':
            return None
        profile = getattr(obj, 'operatoradmin_profile', None)
        return profile.panchayath if profile else None

    def get_is_verified(self, obj):
        profile = self._profile(obj)
        return bool(profile and profile.is_verified)

    def get_onboarding_status(self, obj):
        return staff_onboarding_status(obj)


class OperatorAdminOnboardingSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(required=False, allow_null=True)
    pan_image = serializers.ImageField(required=False, allow_null=True)
    aadhaar_image = serializers.ImageField(required=False, allow_null=True)
    pan_number = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^[A-Z]{5}[0-9]{4}[A-Z]$',
            message='Enter a valid PAN number (e.g. ABCDE1234F).'
        )]
    )
    aadhaar_number = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^\d{12}$',
            message='Aadhaar must be exactly 12 digits.'
        )]
    )

    class Meta:
        model = OperatorAdminOnboarding
        fields = [
            'id', 'user', 'photo', 'pan_number', 'pan_image',
            'aadhaar_number', 'aadhaar_image', 'approved', 'approved_by',
            'approved_at', 'rejection_reason', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'approved', 'approved_by',
            'approved_at', 'rejection_reason', 'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        if instance.approved:
            instance.approved = False
            instance.approved_at = None
            instance.approved_by = None
            instance.rejection_reason = ''
            instance.save(update_fields=[
                'approved', 'approved_at', 'approved_by', 'rejection_reason', 'updated_at'
            ])
            profile = instance.user.operatoradmin_profile
            profile.is_verified = False
            profile.save(update_fields=['is_verified'])
        return instance


class OperatorAdminOnboardingAdminSerializer(OperatorAdminOnboardingSerializer):
    account = serializers.SerializerMethodField()
    role = serializers.CharField(source='user.base_role', read_only=True)

    class Meta(OperatorAdminOnboardingSerializer.Meta):
        fields = OperatorAdminOnboardingSerializer.Meta.fields + ['account', 'role']
        read_only_fields = OperatorAdminOnboardingSerializer.Meta.read_only_fields + ['role']

    def get_account(self, obj):
        return {
            'username': obj.user.username,
            'email': obj.user.email,
            'phone': str(obj.user.phone) if obj.user.phone else None,
        }

