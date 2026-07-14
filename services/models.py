from django.db import models

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

    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2)

    duration = models.CharField(max_length=50)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.type_name