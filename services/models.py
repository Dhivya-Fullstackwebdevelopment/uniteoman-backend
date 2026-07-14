from django.db import models

class Service(models.Model):

    name=models.CharField(max_length=100)

    icon=models.ImageField(upload_to="services")

    starting_price=models.DecimalField(max_digits=10,
                                       decimal_places=2)

    governorate=models.ForeignKey(
        "locations.Governorate",
        on_delete=models.CASCADE
    )

    is_active=models.BooleanField(default=True)