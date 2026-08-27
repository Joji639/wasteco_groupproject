from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from accounts.models import CustomUser, UserProfile, OperatorProfile, OperatorAdminProfile, OperatorOnboarding


GROUPS_PERMISSIONS = {
    'User': {
        'models': ['userprofile'],
        'permissions': ['view', 'add', 'change'],
    },
    'Operator': {
        'models': ['operatorprofile', 'operatoronboarding'],
        'permissions': ['view'],
    },
    'OperatorAdmin': {
        'models': ['operatoradminprofile', 'operatoronboarding'],
        'permissions': ['view', 'change'],
    },
    'SuperAdmin': {
        'models': [
            'customuser', 'userprofile', 'operatorprofile',
            'operatoradminprofile', 'operatoronboarding',
        ],
        'permissions': ['view', 'add', 'change', 'delete'],
    },
}


class Command(BaseCommand):
    help = 'Creates default groups and assigns permissions'

    def handle(self, *args, **options):
        for group_name, config in GROUPS_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created group: {group_name}'))
            else:
                self.stdout.write(f'Group already exists: {group_name}')

            for model_name in config['models']:
                try:
                    content_type = ContentType.objects.get(
                        app_label='accounts',
                        model=model_name.lower()
                    )
                except ContentType.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        f'ContentType not found for {model_name}. '
                        f'Make sure the model is migrated.'
                    ))
                    continue

                for perm_action in config['permissions']:
                    codename = f'{perm_action}_{model_name}'
                    try:
                        permission = Permission.objects.get(
                            codename=codename,
                            content_type=content_type,
                        )
                        group.permissions.add(permission)
                    except Permission.DoesNotExist:
                        self.stdout.write(self.style.WARNING(
                            f'Permission {codename} not found. '
                            f'Skipping.'
                        ))

        self.stdout.write(self.style.SUCCESS('Groups and permissions created successfully.'))
