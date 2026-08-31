from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import Group


ROLE_TO_GROUP = {
    'user': 'User',
    'operator': 'Operator',
    'operatoradmin': 'OperatorAdmin',
    'superadmin': 'SuperAdmin',
}


class UserManager(BaseUserManager):

    def create_user(self, email, password=None, phone=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        base_role = extra_fields.get('base_role', getattr(user, 'base_role', 'user'))
        group_name = ROLE_TO_GROUP.get(base_role)
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('base_role', 'superadmin')
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, **extra_fields)