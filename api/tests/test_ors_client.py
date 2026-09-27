"""
Unit tests for ORS client and coordinates parser.
"""
import pytest
from api.services.ors_client import parse_coordinate_string


def test_parse_coordinate_string():
    """Verify coordinate parser extracts (lon, lat) correctly."""
    # Standard lat, lon in US
    res1 = parse_coordinate_string("41.8781, -87.6298")
    assert res1 == (-87.6298, 41.8781)

    # Reversed lon, lat in US
    res2 = parse_coordinate_string("-87.6298, 41.8781")
    assert res2 == (-87.6298, 41.8781)

    # City string should return None
    res3 = parse_coordinate_string("Chicago, IL")
    assert res3 is None
