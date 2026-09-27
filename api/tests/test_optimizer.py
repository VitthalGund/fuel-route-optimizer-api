"""
Unit tests for the DP fuel-stop optimizer.
"""
import pytest
from api.services.optimizer import optimize_fuel_stops


def test_optimizer_short_trip_zero_stops():
    """Trips <= 500 miles require 0 fuel stops."""
    candidates = [
        {'opis_id': 1, 'route_miles': 200.0, 'retail_price': 3.10, 'name': 'Station A', 'city': 'City A', 'state': 'IL', 'address': '123 St', 'latitude': 40.0, 'longitude': -88.0}
    ]
    stops, cost, error = optimize_fuel_stops(
        candidate_stations=candidates,
        route_distance_miles=450.0,
        tank_range_miles=500.0,
        vehicle_mpg=10.0
    )
    assert error is None
    assert stops == []
    assert cost == 0.0


def test_optimizer_single_stop_required():
    """A 800-mile trip requires at least 1 stop. It should pick the cheapest station in reach."""
    candidates = [
        # Station 1: Mile 300, Price 3.50
        {'opis_id': 1, 'route_miles': 300.0, 'retail_price': 3.50, 'name': 'Expensive Stop', 'city': 'City 1', 'state': 'MO', 'address': 'Addr 1', 'latitude': 38.0, 'longitude': -92.0},
        # Station 2: Mile 400, Price 2.90 (cheaper & reaches destination from 400 to 800 = 400 mi <= 500)
        {'opis_id': 2, 'route_miles': 400.0, 'retail_price': 2.90, 'name': 'Cheap Stop', 'city': 'City 2', 'state': 'MO', 'address': 'Addr 2', 'latitude': 37.5, 'longitude': -93.0},
    ]
    stops, cost, error = optimize_fuel_stops(
        candidate_stations=candidates,
        route_distance_miles=800.0,
        tank_range_miles=500.0,
        vehicle_mpg=10.0
    )
    assert error is None
    assert len(stops) == 1
    assert stops[0]['opis_id'] == 2
    # 800 miles total / 10 MPG = 80 gallons total @ $2.90/gal = $232.00
    assert stops[0]['gallons_purchased'] == 80.0
    assert cost == 232.00


def test_optimizer_multiple_stops_required():
    """A 1200-mile trip requires at least 2 stops."""
    candidates = [
        # Leg 1 options
        {'opis_id': 10, 'route_miles': 350.0, 'retail_price': 3.00, 'name': 'Stop 1', 'city': 'City A', 'state': 'IL', 'address': '1', 'latitude': 39.0, 'longitude': -89.0},
        {'opis_id': 11, 'route_miles': 450.0, 'retail_price': 3.80, 'name': 'Stop 1 Expensive', 'city': 'City B', 'state': 'MO', 'address': '2', 'latitude': 38.0, 'longitude': -91.0},
        # Leg 2 options
        {'opis_id': 20, 'route_miles': 750.0, 'retail_price': 2.80, 'name': 'Stop 2 Cheap', 'city': 'City C', 'state': 'OK', 'address': '3', 'latitude': 36.0, 'longitude': -95.0},
        # Leg 3 options
        {'opis_id': 30, 'route_miles': 1100.0, 'retail_price': 3.10, 'name': 'Stop 3', 'city': 'City D', 'state': 'TX', 'address': '4', 'latitude': 33.0, 'longitude': -97.0},
    ]
    stops, cost, error = optimize_fuel_stops(
        candidate_stations=candidates,
        route_distance_miles=1200.0,
        tank_range_miles=500.0,
        vehicle_mpg=10.0
    )
    assert error is None
    assert len(stops) >= 2
    # All gaps between stops must be <= 500
    last_pos = 0.0
    for s in stops:
        assert (s['route_miles'] - last_pos) <= 500.0
        last_pos = s['route_miles']
    assert (1200.0 - last_pos) <= 500.0


def test_optimizer_impossible_gap_returns_error():
    """When a gap exceeds 500 miles, error is returned."""
    candidates = [
        {'opis_id': 1, 'route_miles': 200.0, 'retail_price': 3.00, 'name': 'Stop 1', 'city': 'City 1', 'state': 'NV', 'address': '1', 'latitude': 39.0, 'longitude': -115.0},
        # Gap of 600 miles between Stop 1 (200) and Stop 2 (800)
        {'opis_id': 2, 'route_miles': 800.0, 'retail_price': 3.00, 'name': 'Stop 2', 'city': 'City 2', 'state': 'UT', 'address': '2', 'latitude': 40.0, 'longitude': -111.0},
    ]
    stops, cost, error = optimize_fuel_stops(
        candidate_stations=candidates,
        route_distance_miles=1000.0,
        tank_range_miles=500.0,
        vehicle_mpg=10.0
    )
    assert stops is None
    assert cost is None
    assert error is not None
    assert "cannot be completed" in error.lower() or "gap" in error.lower()
