from django.db import models

class Service(models.Model):

    name = models.CharField(max_length=100)

    icon = models.ImageField(upload_to="services")

    description = models.TextField(blank=True)

    starting_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    governorate = models.ForeignKey(
        "locations.Governorate",
        on_delete=models.CASCADE
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    name = models.CharField(max_length=100)

    icon = models.ImageField(upload_to="services")

    description = models.TextField(blank=True)

    starting_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    governorate = models.ForeignKey(
        "locations.Governorate",
        on_delete=models.CASCADE
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name