import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class WasteCollection(models.Model):
    PLASTIC_RATE = Decimal('5.00')
    E_WASTE_RATE = Decimal('20.00')

    PAYMENT_METHOD_CHOICES = (
        ('CASH', 'Cash'),
        ('ONLINE', 'Online (Razorpay)'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('AMOUNT_DUE', 'Amount Due'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pickup_request = models.OneToOneField(
        'pickups.PickupRequest',
        on_delete=models.CASCADE,
        related_name='waste_collection',
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='waste_collections',
    )

    plastic_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    e_waste_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))

    plastic_rate = models.DecimalField(max_digits=8, decimal_places=2, default=PLASTIC_RATE)
    e_waste_rate = models.DecimalField(max_digits=8, decimal_places=2, default=E_WASTE_RATE)

    plastic_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    e_waste_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default='CASH')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Collection {self.id} - {self.pickup_request_id} ({self.status})"

    def calculate_amounts(self):
        self.plastic_amount = self.plastic_kg * self.plastic_rate
        self.e_waste_amount = self.e_waste_kg * self.e_waste_rate
        self.total_amount = self.plastic_amount + self.e_waste_amount
        return self.total_amount

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self.calculate_amounts()
        else:
            self.calculate_amounts()
        super().save(*args, **kwargs)


class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = (
        ('CASH', 'Cash'),
        ('ONLINE', 'Online (Razorpay)'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('CREATED', 'Order Created'),
        ('CAPTURED', 'Captured (Paid)'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.OneToOneField(
        WasteCollection,
        on_delete=models.CASCADE,
        related_name='payment',
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')

    razorpay_order_id = models.CharField(max_length=100, blank=True, default='')
    razorpay_payment_id = models.CharField(max_length=100, blank=True, default='')
    razorpay_signature = models.CharField(max_length=256, blank=True, default='')

    receipt = models.CharField(max_length=100, blank=True, default='')

    notes = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.id} - {self.amount} {self.currency} ({self.payment_status})"
