from django.db import models
from django.core.exceptions import ValidationError


class Community(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='created_communities',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def clean(self):
        if not self.name or not self.name.strip():
            raise ValidationError('Community name cannot be empty.')
        if len(self.name) > 200:
            raise ValidationError('Community name is too long.')


class CommunityMember(models.Model):
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='members',
    )
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='community_memberships',
    )
    added_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='added_community_members',
    )
    is_group_admin = models.BooleanField(default=False)
    can_add_members = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['joined_at']
        constraints = [
            models.UniqueConstraint(
                fields=['community', 'user'],
                condition=models.Q(is_active=True),
                name='unique_active_membership_per_community',
            )
        ]

    def __str__(self):
        return f'{self.user.email} in {self.community.name}'


class Message(models.Model):
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='sent_messages',
    )
    content = models.TextField()
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Message by {self.sender.email} in {self.community.name}'

    def clean(self):
        if not self.content or not self.content.strip():
            raise ValidationError('Message content cannot be empty.')
        if len(self.content) > 5000:
            raise ValidationError('Message content exceeds maximum length of 5000 characters.')
