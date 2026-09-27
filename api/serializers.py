import re
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    """
    Serializer for route optimization request.
    Accepts US city/address string or 'lat,lon' coordinates.
    """
    origin = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
        help_text="Start location (e.g., 'Chicago, IL' or '41.8781,-87.6298')"
    )
    destination = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=255,
        help_text="Finish location (e.g., 'Dallas, TX' or '32.7767,-96.7970')"
    )

    def validate_origin(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Origin cannot be empty.")
        return cleaned

    def validate_destination(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Destination cannot be empty.")
        return cleaned

    def validate(self, data):
        if data['origin'].lower() == data['destination'].lower():
            raise serializers.ValidationError("Origin and destination cannot be identical.")
        return data


class FuelStopSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gal = serializers.FloatField()
    miles_from_start = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    stop_cost_usd = serializers.FloatField()
    coordinates = serializers.ListField(
        child=serializers.FloatField(),
        min_length=2,
        max_length=2,
        help_text="[longitude, latitude]"
    )


class SummarySerializer(serializers.Serializer):
    route_distance_miles = serializers.FloatField()
    estimated_duration_hrs = serializers.FloatField()
    total_fuel_gallons = serializers.FloatField()
    total_fuel_cost_usd = serializers.FloatField()
    fuel_stops_count = serializers.IntegerField()


class RouteResponseSerializer(serializers.Serializer):
    summary = SummarySerializer()
    fuel_stops = FuelStopSerializer(many=True)
    map = serializers.DictField(help_text="GeoJSON FeatureCollection")
