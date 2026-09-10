import uuid

from django.conf import settings
from django.db import models
from cloudinary.models import CloudinaryField


class PickupRequest(models.Model):
    PICKUP_TYPE_CHOICES = (
        ('ON_DEMAND', 'On Demand'),
        ('SCHEDULED', 'Scheduled'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('ASSIGNED', 'Assigned'),
        ('ON_THE_WAY', 'On The Way'),
        ('COLLECTED', 'Collected'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('REJECTED', 'Rejected'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pickup_requests',
    )
    pickup_type = models.CharField(
        max_length=20,
        choices=PICKUP_TYPE_CHOICES,
        default='ON_DEMAND',
    )
    place = models.CharField(max_length=500, blank=True, null=True, help_text="Text address — auto-converted to lat/lng via geocoding")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    description = models.TextField()
    image = CloudinaryField('waste_image', blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
    )

    # Operator Admin decision tracking
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='accepted_pickups',
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Rejection tracking
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rejected_pickups',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')

    # Operator assignment
    assigned_operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_pickups',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_pickups_by_me',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.pickup_type} - {self.user.email} ({self.status})"


class OperatorReview(models.Model):
    id = models.AutoField(primary_key=True)
    pickup_request = models.ForeignKey(
        PickupRequest,
        on_delete=models.CASCADE,
        related_name='operator_reviews',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='operator_reviews_given',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='operator_reviews_received',
    )
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True, null=True, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['pickup_request', 'user'],
                name='unique_user_review_per_pickup',
            )
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Review by {self.user.email} for {self.operator.email} — {self.rating}/5"
