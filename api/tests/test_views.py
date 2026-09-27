"""
Integration tests for RouteView and HealthView.
"""
from decimal import Decimal
from unittest.mock import patch
import pytest
from rest_framework.test import APIClient
from api.models import FuelStation


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_health_view(api_client):
    """Test health check endpoint."""
    response = api_client.get('/api/health/')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert data['db_connection'] is True
    assert 'stations_count' in data


@pytest.mark.django_db
def test_route_view_validation_error(api_client):
    """Test validation errors for missing or identical start and finish."""
    # Missing origin
    resp1 = api_client.post('/api/route/', {'destination': 'Dallas, TX'}, format='json')
    assert resp1.status_code == 400

    # Identical origin and destination
    resp2 = api_client.post('/api/route/', {'origin': 'Chicago, IL', 'destination': 'Chicago, IL'}, format='json')
    assert resp2.status_code == 400


@pytest.mark.django_db
@patch('api.views.geocode_location')
@patch('api.views.get_route_directions')
def test_route_view_success(mock_get_route, mock_geocode, api_client):
    """Test end-to-end route optimization flow with mocked routing response."""
    # Mock geocode responses
    mock_geocode.side_effect = [
        (-87.6298, 41.8781),  # Chicago (lon, lat)
        (-96.7970, 32.7767),  # Dallas (lon, lat)
    ]

    # Mock route directions (920 miles)
    # LineString with points along Chicago -> St. Louis -> Springfield -> Tulsa -> Dallas
    mock_get_route.return_value = {
        'coordinates': [
            [-87.6298, 41.8781],  # Chicago (0 mi)
            [-90.1994, 38.6270],  # St. Louis (~300 mi)
            [-93.2917, 37.2153],  # Springfield MO (~500 mi)
            [-95.9928, 36.1540],  # Tulsa OK (~680 mi)
            [-96.7970, 32.7767]   # Dallas (~920 mi)
        ],
        'distance_miles': 920.0,
        'duration_hours': 14.0,
        'geojson': {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': []}}
    }

    # Create fuel stations in DB to cover the 920-mile trip
    # Stop 1: St. Louis MO (~300 miles)
    FuelStation.objects.create(
        opis_id=501,
        name="Pilot Travel Center St Louis",
        address="I-55 Exit 10",
        city="St. Louis",
        state="MO",
        retail_price=Decimal("3.0500"),
        latitude=38.6270,
        longitude=-90.1994
    )
    # Stop 2: Tulsa OK (~680 miles)
    FuelStation.objects.create(
        opis_id=502,
        name="Love's Travel Stop Tulsa",
        address="I-44 Exit 200",
        city="Tulsa",
        state="OK",
        retail_price=Decimal("2.9500"),
        latitude=36.1540,
        longitude=-95.9928
    )

    response = api_client.post(
        '/api/route/',
        {'origin': 'Chicago, IL', 'destination': 'Dallas, TX'},
        format='json'
    )

    assert response.status_code == 200
    data = response.json()
    assert 'summary' in data
    assert 'fuel_stops' in data
    assert 'map' in data
    assert data['summary']['route_distance_miles'] == 920.0
    assert data['summary']['total_fuel_gallons'] == 92.0
    assert data['map']['type'] == 'FeatureCollection'
