"""
Corridor spatial service using Shapely for route buffer filtering and mileage projection.
"""
import math
from typing import List, Dict, Any
from shapely.geometry import LineString, Point
from django.conf import settings
from api.models import FuelStation


def get_candidate_stations(
    route_coordinates: List[List[float]],
    route_distance_miles: float,
    corridor_miles: float = 15.0
) -> List[Dict[str, Any]]:
    """
    Finds all fuel stations within `corridor_miles` buffer along the route line,
    projects their location onto the route to calculate mileage-from-start,
    and returns them sorted in ascending order of route_miles.

    Args:
        route_coordinates: List of [longitude, latitude] pairs from GeoJSON route.
        route_distance_miles: Total road distance of the trip in miles.
        corridor_miles: Search buffer radius around route (default 15 miles).

    Returns:
        List of dicts representing candidate stations with 'route_miles' attribute.
    """
    if not route_coordinates or len(route_coordinates) < 2:
        return []

    # 1. Build Shapely LineString (coordinates in [lon, lat])
    route_line = LineString(route_coordinates)
    min_lon, min_lat, max_lon, max_lat = route_line.bounds

    # 2. Compute bounding box buffer in degrees
    # 1 degree latitude ~= 69 miles. 1 degree longitude ~= 69 * cos(mid_lat) miles.
    mid_lat = (min_lat + max_lat) / 2.0
    lat_deg_margin = (corridor_miles + 5.0) / 69.0
    cos_lat = max(math.cos(math.radians(mid_lat)), 0.2)
    lon_deg_margin = (corridor_miles + 5.0) / (69.0 * cos_lat)

    # 3. Database fetch filtered by bounding box (indexed B-Tree scan)
    stations_qs = FuelStation.objects.filter(
        latitude__range=(min_lat - lat_deg_margin, max_lat + lat_deg_margin),
        longitude__range=(min_lon - lon_deg_margin, max_lon + lon_deg_margin)
    ).values(
        'id', 'opis_id', 'name', 'address', 'city', 'state',
        'retail_price', 'latitude', 'longitude'
    )

    candidates: List[Dict[str, Any]] = []

    # 4. In-memory spatial filtering & projection
    # Buffer in degrees: roughly corridor_miles / 69.0
    buffer_deg = corridor_miles / 69.0

    for s in stations_qs:
        pt = Point(s['longitude'], s['latitude'])
        
        # Calculate perpendicular distance from point to route line in degrees
        deg_dist = route_line.distance(pt)
        # Convert degree distance to approximate miles
        approx_miles_dist = deg_dist * 69.0
        
        if approx_miles_dist <= corridor_miles:
            # Normalized projection along the route (0.0 at start, 1.0 at destination)
            norm_pos = route_line.project(pt, normalized=True)
            station_mile = round(norm_pos * route_distance_miles, 2)
            
            candidate_item = {
                'id': s['id'],
                'opis_id': s['opis_id'],
                'name': s['name'],
                'address': s['address'],
                'city': s['city'],
                'state': s['state'],
                'retail_price': float(s['retail_price']),
                'latitude': s['latitude'],
                'longitude': s['longitude'],
                'route_miles': station_mile,
                'distance_from_corridor_miles': round(approx_miles_dist, 2)
            }
            candidates.append(candidate_item)

    # 5. Sort candidate stations monotonically along the route from start to finish
    candidates.sort(key=lambda item: item['route_miles'])

    return candidates
