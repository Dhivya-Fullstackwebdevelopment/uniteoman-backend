from django.db import models
from django.conf import settings

class Service(models.Model):
    name = models.CharField(max_length=100)
    icon = models.ImageField(upload_to="services")
    description = models.TextField(blank=True)
    starting_price = models.DecimalField(max_digits=10, decimal_places=2)

    governorate = models.ForeignKey(
        "locations.Governorate",
        on_delete=models.CASCADE
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ServiceType(models.Model):

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE
    )

    type_name = models.CharField(max_length=150)

    # NEW
    icon = models.ImageField(
        upload_to="service_types",
        blank=True,
        null=True
    )

    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2)

    duration = models.CharField(max_length=50)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.type_name

class Professional(models.Model):
    name = models.CharField(max_length=255)
    specialty = models.CharField(max_length=255) # e.g., AC Specialist
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=5.0)
    jobs_count = models.IntegerField(default=0)
    avatar = models.ImageField(upload_to='professionals/', blank=True, null=True)

    def __str__(self):
        return self.name

class Booking(models.Model):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('EN_ROUTE', 'En Route'),
        ('ARRIVED', 'Arrived'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    booking_number = models.CharField(max_length=50, unique=True) # e.g., UO-4601
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_type = models.ForeignKey(ServiceType, on_delete=models.CASCADE)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE)
    scheduled_at = models.DateTimeField()
    duration_minutes = models.IntegerField(default=45)
    location_name = models.CharField(max_length=255) # e.g., Qurum
    address = models.TextField() # e.g., Villa 12, Al Noor St, Qurum
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    
    # Financial Elements
    service_fee = models.DecimalField(max_digits=10, decimal_places=3)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=3)
    vat = models.DecimalField(max_digits=10, decimal_places=3)
    total_paid = models.DecimalField(max_digits=10, decimal_places=3)
    payment_method = models.CharField(max_length=100, default="Bank of Muscat ****4521")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.booking_number} ({self.status})"

class Review(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='review')
    rating = models.IntegerField()
    review_text = models.TextField(blank=True, null=True)
    tags = models.JSONField(default=list) # e.g., ["Punctual", "Thorough"]
    created_at = models.DateTimeField(auto_now_add=True)