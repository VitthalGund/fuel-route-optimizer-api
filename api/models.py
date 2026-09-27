from django.db import models


class FuelStation(models.Model):
    """
    Model representing a geocoded fuel truck stop with retail pricing.
    """
    opis_id = models.IntegerField(
        unique=True,
        db_index=True,
        help_text="Unique OPIS Truckstop ID"
    )
    name = models.CharField(
        max_length=200,
        help_text="Truckstop brand or name"
    )
    address = models.CharField(
        max_length=300,
        help_text="Street address / highway exit"
    )
    city = models.CharField(
        max_length=100,
        help_text="City"
    )
    state = models.CharField(
        max_length=2,
        db_index=True,
        help_text="2-letter US state code"
    )
    retail_price = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        help_text="Retail fuel price per gallon (USD)"
    )
    latitude = models.FloatField(
        db_index=True,
        help_text="WGS84 Latitude"
    )
    longitude = models.FloatField(
        db_index=True,
        help_text="WGS84 Longitude"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_fuelstation'
        verbose_name = 'Fuel Station'
        verbose_name_plural = 'Fuel Stations'
        indexes = [
            models.Index(fields=['state', 'retail_price']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) - ${self.retail_price}/gal"
