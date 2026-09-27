"""
Unit tests for the Shapely corridor spatial filter.
"""
import pytest
from decimal import Decimal
from api.models import FuelStation
from api.services.corridor import get_candidate_stations


@pytest.mark.django_db
def test_corridor_filtering_and_projection():
    """Test that corridor service filters out distant stations and projects valid ones along the route."""
    # Create test stations
    # Route is a straight line from (lon -90.0, lat 40.0) to (lon -90.0, lat 45.0) -> approx 345 miles
    route_coords = [
        [-90.0, 40.0],
        [-90.0, 42.5],
        [-90.0, 45.0]
    ]
    route_distance_miles = 345.0

    # Station 1: directly on route around 1/4 way (lat 41.25)
    s1 = FuelStation.objects.create(
        opis_id=101,
        name="On Route Station",
        address="100 Highway Rd",
        city="Midway",
        state="IL",
        retail_price=Decimal("3.1500"),
        latitude=41.25,
        longitude=-90.0
    )

    # Station 2: 5 miles off route (lon -89.9)
    s2 = FuelStation.objects.create(
        opis_id=102,
        name="Close Off Route Station",
        address="200 Highway Rd",
        city="Nearby",
        state="IL",
        retail_price=Decimal("2.9900"),
        latitude=43.0,
        longitude=-89.9
    )

    # Station 3: 150 miles off route (lon -86.0) -> Should be filtered out!
    s3 = FuelStation.objects.create(
        opis_id=103,
        name="Far Away Station",
        address="300 Far Rd",
        city="Farville",
        state="IN",
        retail_price=Decimal("2.5000"),
        latitude=42.0,
        longitude=-86.0
    )

    candidates = get_candidate_stations(
        route_coordinates=route_coords,
        route_distance_miles=route_distance_miles,
        corridor_miles=15.0
    )

    candidate_ids = [c['opis_id'] for c in candidates]
    assert 101 in candidate_ids
    assert 102 in candidate_ids
    assert 103 not in candidate_ids  # Out of corridor buffer

    # Check ordering along route
    assert candidates[0]['opis_id'] == 101
    assert candidates[1]['opis_id'] == 102
    assert candidates[0]['route_miles'] < candidates[1]['route_miles']
