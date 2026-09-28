import uuid

from django.conf import settings
from django.db import models
from cloudinary.models import CloudinaryField


def generate_collection_qr_code():
    import secrets
    return f"ECOBIN-{secrets.token_hex(8).upper()}"


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


class ScheduledPickup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scheduled_date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scheduled_pickups_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"Scheduled Pickup — {self.scheduled_date}"


class Area(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="e.g., Ward 5, Market Road, Lake Area")
    panchayath = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='areas_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.panchayath})" if self.panchayath else self.name


class AreaAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    area = models.ForeignKey(
        Area,
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='area_assignments',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='area_assignments_made',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['area', 'operator'],
                name='unique_operator_per_area',
            )
        ]
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.operator.email} → {self.area.name}"


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


class CollectionRecord(models.Model):
    WASTE_TYPE_CHOICES = (
        ('PLASTIC', 'Plastic'),
        ('E_WASTE', 'E-Waste'),
        ('ORGANIC', 'Organic'),
        ('PAPER', 'Paper'),
        ('GLASS', 'Glass'),
        ('METAL', 'Metal'),
        ('MIXED', 'Mixed'),
    )

    STATUS_CHOICES = (
        ('COLLECTED', 'Collected'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Operator who collected
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='collection_records',
    )
    operator_id_display = models.CharField(
        max_length=20,
        help_text="Operator ID displayed on collection report",
    )

    # Link to pickup request (for on-demand) or area (for scheduled)
    pickup_request = models.ForeignKey(
        PickupRequest,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='waste_collections',
    )
    area = models.ForeignKey(
        Area,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='waste_collections',
    )

    # Resident details
    resident_name = models.CharField(max_length=200)
    resident_email = models.EmailField(blank=True, default='')
    resident_phone = models.CharField(max_length=20, blank=True, default='')
    house_address = models.TextField()

    # Waste details
    waste_type = models.CharField(max_length=20, choices=WASTE_TYPE_CHOICES)
    quantity_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Weight in kilograms",
    )

    # QR code for tracking
    qr_code = models.CharField(
        max_length=50,
        unique=True,
        default=generate_collection_qr_code,
    )

    # Collection status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COLLECTED')
    failure_reason = models.TextField(blank=True, default='')

    collected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-collected_at']

    def __str__(self):
        return f"{self.operator_id_display} — {self.resident_name} ({self.waste_type})"


class PickupTracking(models.Model):
    STATUS_CHOICES = (
        ('NOT_STARTED', 'Not Started'),
        ('EN_ROUTE', 'En Route'),
        ('ARRIVED', 'Arrived'),
        ('COLLECTING', 'Collecting'),
        ('COMPLETED', 'Completed'),
        ('PAID', 'Paid'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    pickup_request = models.OneToOneField(
        PickupRequest,
        on_delete=models.CASCADE,
        related_name='tracking',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pickup_tracking',
    )

    # Starting location (operator inputs before starting)
    start_place = models.CharField(max_length=500, blank=True, default='')
    start_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    start_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Current position (updated via WebSocket in real-time)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Route data (stored as JSON - waypoints from OSRM)
    route_data = models.JSONField(default=dict, blank=True)
    total_distance_meters = models.FloatField(default=0)
    total_duration_seconds = models.FloatField(default=0)

    # Status and progress
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NOT_STARTED')
    progress = models.FloatField(default=0.0, help_text="0.0 to 1.0 along route")

    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Tracking — {self.pickup_request_id} ({self.status})"
