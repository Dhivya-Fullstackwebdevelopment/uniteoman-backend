import random
import string
from django.db import models
from django.utils import timezone

from services.models import Service, ServiceType
from locations.models import Governorate
from django.conf import settings



def generate_booking_code():
    return "UO-" + "".join(random.choices(string.digits, k=4))


class Professional(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='professional_profile'
    )
    name = models.CharField(max_length=150)
    specialty = models.CharField(max_length=150, blank=True)
    avatar = models.ImageField(upload_to="professionals", blank=True, null=True)

    governorate = models.ForeignKey(Governorate, on_delete=models.CASCADE, related_name="professionals")
    area = models.CharField(max_length=100, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    password = models.CharField(max_length=128, blank=True, null=True)  # Django hashed password

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_km = models.DecimalField(max_digits=5, decimal_places=1, default=0)

    rating = models.DecimalField(max_digits=2, decimal_places=1, default=5.0)
    jobs_done = models.PositiveIntegerField(default=0)
    completion_rate = models.PositiveIntegerField(default=100)
    cancellations = models.PositiveIntegerField(default=0)
    avg_arrival_minutes = models.PositiveIntegerField(default=15)

    next_available_date = models.DateField(null=True, blank=True)
    next_available_time = models.TimeField(null=True, blank=True)

    phone = models.CharField(max_length=20, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)
        self.save()

    def __str__(self):
        return self.name

    @property
    def is_available_today(self):
        return self.next_available_date == timezone.localdate()

    def ai_match_score(self, service_type=None):
        """Simple heuristic score used for 'AI Top Picks' / 'Best Match' badges."""
        score = 100
        score -= float(self.cancellations) * 5
        score -= max(0, self.avg_arrival_minutes - 10) * 0.5
        score -= max(0, (5 - float(self.rating))) * 10
        if not self.is_available_today:
            score -= 15
        return max(0, min(100, round(score)))


class ProfessionalServiceType(models.Model):
    """A specific service_type a professional offers, with their own price."""
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name="offerings")
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE, related_name="offered_by")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("professional", "service_type")

    def __str__(self):
        return f"{self.professional.name} - {self.service_type.type_name}"


class Review(models.Model):
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE, related_name="reviews")
    reviewer_name = models.CharField(max_length=150)
    rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reviewer_name} -> {self.professional.name} ({self.rating}★)"


# class Booking(models.Model):
#     STATUS_PENDING = "pending"
#     STATUS_CONFIRMED = "confirmed"
#     STATUS_ONGOING = "ongoing"
#     STATUS_CANCELLED = "cancelled"
#     STATUS_COMPLETED = "completed"
#     STATUS_CHOICES = [
#         (STATUS_PENDING, "Pending"),
#         (STATUS_CONFIRMED, "Confirmed"),
#         (STATUS_ONGOING, "Ongoing"),
#         (STATUS_CANCELLED, "Cancelled"),
#         (STATUS_COMPLETED, "Completed"),
#     ]
class Booking(models.Model):
    STATUS_SCHEDULED = "SCHEDULED"
    STATUS_PENDING = "PENDING"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_EN_ROUTE = "EN_ROUTE"
    STATUS_ARRIVED = "ARRIVED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"
    
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_EN_ROUTE, "En Route"),
        (STATUS_ARRIVED, "Arrived"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PAYMENT_CHOICES = [
        ("bank_of_muscat_card", "Bank of Muscat Card"),
        ("apple_pay", "Apple Pay"),
        ("google_pay", "Google Pay"),
        ("thawani", "Thawani"),
        ("cash_on_completion", "Cash on Completion"),
    ]

    booking_code = models.CharField(max_length=20, unique=True, default=generate_booking_code)

    # Who booked
    user_name = models.CharField(max_length=150)
    user_email = models.EmailField()
    user_mobile = models.CharField(max_length=20)

    # What / who
    professional = models.ForeignKey(
        Professional,
        on_delete=models.CASCADE,
        related_name="bookings",
        null=True,
        blank=True,
    )
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE, related_name="bookings")

    # Date & time
    booking_date = models.DateField()
    booking_time = models.TimeField()

    # Address
    area = models.CharField(max_length=100)
    villa_apartment_no = models.CharField(max_length=100)
    street_name = models.CharField(max_length=150)
    building_floor = models.CharField(max_length=100, blank=True)
    nearest_landmark = models.CharField(max_length=150, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Payment
    payment_method = models.CharField(max_length=30, choices=PAYMENT_CHOICES, default="cash_on_completion")
    card_last4 = models.CharField(max_length=4, blank=True)
    save_card = models.BooleanField(default=False)

    # Pricing snapshot
    service_fee = models.DecimalField(max_digits=10, decimal_places=3)
    platform_fee_percent = models.DecimalField(max_digits=4, decimal_places=2, default=10.00)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=3)
    vat_percent = models.DecimalField(max_digits=4, decimal_places=2, default=9.00)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=3)
    total_amount = models.DecimalField(max_digits=10, decimal_places=3)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        pro_name = self.professional.name if self.professional else "Unassigned"
        return f"{self.booking_code} - {self.user_name} -> {pro_name}"

    def calculate_pricing(self):
        from decimal import Decimal
        
        service_fee = self.service_fee
        
        platform_fee_percent_decimal = Decimal(str(self.platform_fee_percent)) / Decimal('100')
        vat_percent_decimal = Decimal(str(self.vat_percent)) / Decimal('100')
        
        platform_fee = (service_fee * platform_fee_percent_decimal).quantize(Decimal('0.001'))
        subtotal = service_fee + platform_fee
        vat_amount = (subtotal * vat_percent_decimal).quantize(Decimal('0.001'))
        total = service_fee + platform_fee + vat_amount
        
        self.platform_fee = platform_fee
        self.vat_amount = vat_amount
        self.total_amount = total
        return total