from django.db import migrations

PERMISSIONS = {
    'can_view_communities': 'Can list/view communities',
    'can_create_community': 'Can create a community',
    'can_manage_community': 'Can update/deactivate a community',
    'can_manage_members': 'Can add/remove members and change permissions',
}

GROUP_PERMISSIONS = {
    'Operator': ['can_view_communities'],
    'OperatorAdmin': list(PERMISSIONS),
    'SuperAdmin': list(PERMISSIONS),
}


def assign_perms_to_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    db = schema_editor.connection.alias

    ct, _ = ContentType.objects.using(db).get_or_create(
        app_label='chat', model='community',
    )
    perms = {}
    for codename, name in PERMISSIONS.items():
        perm, _ = Permission.objects.using(db).get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )
        perms[codename] = perm

    for group_name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.using(db).get_or_create(name=group_name)
        group.permissions.add(*(perms[c] for c in codenames))


def remove_perms_from_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    db = schema_editor.connection.alias

    codenames = list(PERMISSIONS)
    groups = Group.objects.using(db).filter(name__in=list(GROUP_PERMISSIONS))
    for group in groups:
        group.permissions.remove(
            *Permission.objects.using(db).filter(codename__in=codenames)
        )


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_alter_community_options'),
        ('contenttypes', '0001_initial'),
        ('auth', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(assign_perms_to_groups, remove_perms_from_groups),
    ]
