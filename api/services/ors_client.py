"""
OpenRouteService (ORS) client for geocoding and routing directions.
"""
import re
import logging
from typing import Tuple, List, Dict, Any, Optional
import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class RoutingServiceError(Exception):
    """Custom exception raised when routing service fails."""
    def __init__(self, message: str, status_code: int = 503, retry_after: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


class GeocodingError(Exception):
    """Custom exception raised when geocoding fails."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_coordinate_string(text: str) -> Optional[Tuple[float, float]]:
    """
    Checks if a string is a direct 'lat, lon' or 'lon, lat' coordinate pair.
    Returns (longitude, latitude) in standard GeoJSON/ORS order if matched, otherwise None.
    """
    coord_pattern = r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$'
    match = re.match(coord_pattern, text.strip())
    if match:
        val1 = float(match.group(1))
        val2 = float(match.group(2))

        # Check for US specific longitude (< 0) vs latitude (> 0)
        if val1 < 0 and val2 > 0 and -180 <= val1 <= 0 and 0 <= val2 <= 90:
            # val1 is lon, val2 is lat
            return (val1, val2)
        elif val2 < 0 and val1 > 0 and 0 <= val1 <= 90 and -180 <= val2 <= 0:
            # val1 is lat, val2 is lon
            return (val2, val1)
        elif -90 <= val1 <= 90 and -180 <= val2 <= 180:
            # Generic standard format: lat, lon -> return (lon, lat)
            return (val2, val1)
        elif -180 <= val1 <= 180 and -90 <= val2 <= 90:
            # Generic format: lon, lat -> return (lon, lat)
            return (val1, val2)
    return None


def geocode_location(location_text: str) -> Tuple[float, float]:
    """
    Resolves location text into (longitude, latitude).
    First checks for coordinate format, then calls ORS Geocode API.
    Fallback to Nominatim if ORS API key is missing.
    """
    coords = parse_coordinate_string(location_text)
    if coords is not None:
        return coords

    api_key = getattr(settings, 'ORS_API_KEY', '')
    
    # 1. Try OpenRouteService Geocoding if API key is present
    if api_key:
        url = "https://api.openrouteservice.org/geocode/search"
        params = {
            "api_key": api_key,
            "text": location_text,
            "boundary.country": "USA",
            "size": 1
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    features = data.get("features", [])
                    if features:
                        # GeoJSON coordinates are [lon, lat]
                        lon, lat = features[0]["geometry"]["coordinates"][:2]
                        return float(lon), float(lat)
                    else:
                        raise GeocodingError(
                            f"Could not find coordinates for location '{location_text}'. Please provide a valid US address or city."
                        )
                elif response.status_code in (401, 403):
                    logger.warning(f"ORS geocoding authorization error: {response.status_code}")
                elif response.status_code == 429:
                    raise RoutingServiceError("OpenRouteService geocoding rate limit exceeded. Please try again shortly.", status_code=429)
        except httpx.RequestError as exc:
            logger.warning(f"ORS geocoding network error: {exc}. Trying fallback.")

    # 2. Fallback to Nominatim OpenStreetMap (Free, requires User-Agent)
    nominatim_url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "FuelRouteOptimizerAPI/1.0 (Django Backend)"}
    params = {
        "q": location_text if "USA" in location_text.upper() else f"{location_text}, USA",
        "format": "json",
        "limit": 1,
        "countrycodes": "us"
    }
    try:
        with httpx.Client(timeout=10.0, headers=headers) as client:
            response = client.get(nominatim_url, params=params)
            if response.status_code == 200:
                results = response.json()
                if results:
                    lat = float(results[0]["lat"])
                    lon = float(results[0]["lon"])
                    return lon, lat
                else:
                    raise GeocodingError(
                        f"Could not resolve location '{location_text}'. Please verify city/state name."
                    )
            elif response.status_code == 429:
                raise RoutingServiceError("Geocoding rate limit exceeded. Please try again.", status_code=429)
    except httpx.RequestError as exc:
        raise RoutingServiceError(f"Geocoding service unavailable: {str(exc)}", status_code=503)

    raise GeocodingError(f"Could not geocode location '{location_text}'.")


def get_route_directions(origin_lon_lat: Tuple[float, float], dest_lon_lat: Tuple[float, float]) -> Dict[str, Any]:
    """
    Calls OpenRouteService directions API to fetch the route between origin and destination.
    Fallback to OSRM demo if ORS key is not configured.
    Returns:
        {
            "coordinates": [[lon, lat], ...],
            "distance_miles": float,
            "duration_hours": float,
            "geojson": dict
        }
    """
    orig_lon, orig_lat = origin_lon_lat
    dest_lon, dest_lat = dest_lon_lat
    api_key = getattr(settings, 'ORS_API_KEY', '')

    # 1. Primary: OpenRouteService
    if api_key:
        url = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        body = {
            "coordinates": [
                [orig_lon, orig_lat],
                [dest_lon, dest_lat]
            ],
            "radiuses": [-1, -1]
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(url, json=body, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    features = data.get("features", [])
                    if not features:
                        raise RoutingServiceError("Routing service returned empty route geometry.", status_code=503)
                    
                    feature = features[0]
                    geometry = feature.get("geometry", {})
                    summary = feature.get("properties", {}).get("summary", {})
                    
                    dist_meters = float(summary.get("distance", 0.0))
                    duration_seconds = float(summary.get("duration", 0.0))
                    coords = geometry.get("coordinates", [])

                    return {
                        "coordinates": coords,
                        "distance_miles": round(dist_meters * 0.000621371, 2),
                        "duration_hours": round(duration_seconds / 3600.0, 2),
                        "geojson": feature
                    }
                elif response.status_code == 429:
                    raise RoutingServiceError("ORS rate limit exceeded. Please retry later.", status_code=429)
                else:
                    logger.warning(f"ORS routing returned status {response.status_code}: {response.text}. Attempting fallback.")
        except httpx.RequestError as exc:
            logger.warning(f"ORS routing request failed: {exc}. Trying fallback routing.")

    # 2. Free Fallback: OSRM Public Routing API (driving)
    osrm_url = f"https://router.project-osrm.org/route/v1/driving/{orig_lon},{orig_lat};{dest_lon},{dest_lat}?overview=full&geometries=geojson"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(osrm_url)
            if response.status_code == 200:
                data = response.json()
                routes = data.get("routes", [])
                if not routes:
                    raise RoutingServiceError("No driving route found between start and finish locations.", status_code=400)
                
                route = routes[0]
                dist_meters = float(route.get("distance", 0.0))
                duration_seconds = float(route.get("duration", 0.0))
                coords = route.get("geometry", {}).get("coordinates", [])

                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords
                    },
                    "properties": {
                        "distance_meters": dist_meters,
                        "duration_seconds": duration_seconds
                    }
                }

                return {
                    "coordinates": coords,
                    "distance_miles": round(dist_meters * 0.000621371, 2),
                    "duration_hours": round(duration_seconds / 3600.0, 2),
                    "geojson": feature
                }
            elif response.status_code == 429:
                raise RoutingServiceError("Routing rate limit reached. Please wait a moment.", status_code=429)
            else:
                raise RoutingServiceError("Routing service returned an error.", status_code=503)
    except httpx.RequestError as exc:
        raise RoutingServiceError(f"Routing service is temporarily unreachable: {str(exc)}", status_code=503)
