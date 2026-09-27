"""
API views for Fuel Route Optimizer.
"""
import hashlib
import json
import logging
from typing import Dict, Any

from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from django.conf import settings
from django.db import connection

from api.models import FuelStation
from api.serializers import RouteRequestSerializer, RouteResponseSerializer


class PreviewView(APIView):
    """Renders the interactive Map & Route Preview UI."""
    def get(self, request, *args, **kwargs):
        return render(request, 'preview.html')
from api.services.ors_client import (
    geocode_location,
    get_route_directions,
    GeocodingError,
    RoutingServiceError
)
from api.services.corridor import get_candidate_stations
from api.services.optimizer import optimize_fuel_stops

logger = logging.getLogger(__name__)


def generate_cache_key(origin: str, destination: str) -> str:
    """Creates a deterministic SHA-256 cache key for origin-destination pair."""
    normalized = f"{origin.strip().lower()}|{destination.strip().lower()}"
    return f"route_opt:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


class RouteView(APIView):
    """
    POST /api/route/
    Calculates the driving route and the optimal, cost-effective fuel stops.
    """

    def post(self, request, *args, **kwargs):
        # 1. Validate Input
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Validation failed", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        origin_text = serializer.validated_data['origin']
        dest_text = serializer.validated_data['destination']

        # 2. Check Cache
        cache_key = generate_cache_key(origin_text, dest_text)
        try:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                return Response(cached_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")

        # 3. Geocode start and finish locations (skipped if coords supplied)
        try:
            origin_coords = geocode_location(origin_text)
        except GeocodingError as ge:
            return Response({"error": str(ge)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingServiceError as re:
            return Response({"error": re.message}, status=re.status_code)

        try:
            dest_coords = geocode_location(dest_text)
        except GeocodingError as ge:
            return Response({"error": str(ge)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingServiceError as re:
            return Response({"error": re.message}, status=re.status_code)

        # 4. Fetch Route Polyline & Distance
        try:
            route_data = get_route_directions(origin_coords, dest_coords)
        except RoutingServiceError as re:
            resp_data = {"error": re.message}
            if re.retry_after:
                return Response(resp_data, status=re.status_code, headers={"Retry-After": str(re.retry_after)})
            return Response(resp_data, status=re.status_code)
        except Exception as exc:
            logger.error(f"Unexpected routing failure: {exc}", exc_info=True)
            return Response(
                {"error": "An unexpected error occurred while fetching route directions."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        route_coords = route_data['coordinates']
        distance_miles = route_data['distance_miles']
        duration_hours = route_data['duration_hours']

        # 5. Corridor Query: Find candidate fuel stations within 15 miles of the route
        corridor_miles = getattr(settings, 'CORRIDOR_MILES', 15.0)
        candidates = get_candidate_stations(
            route_coordinates=route_coords,
            route_distance_miles=distance_miles,
            corridor_miles=corridor_miles
        )

        # 6. DP Optimization: Choose cheapest stops with <= 500 mile intervals
        tank_range = getattr(settings, 'TANK_RANGE_MILES', 500.0)
        mpg = getattr(settings, 'VEHICLE_MPG', 10.0)
        
        chosen_stops, total_fuel_cost, opt_error = optimize_fuel_stops(
            candidate_stations=candidates,
            route_distance_miles=distance_miles,
            tank_range_miles=tank_range,
            vehicle_mpg=mpg
        )

        if opt_error is not None:
            return Response({"error": opt_error}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # 7. Assemble GeoJSON Map FeatureCollection
        features = [
            # Route LineString
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": route_coords
                },
                "properties": {
                    "type": "route",
                    "distance_miles": distance_miles,
                    "duration_hrs": duration_hours
                }
            },
            # Origin Point
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [origin_coords[0], origin_coords[1]]
                },
                "properties": {
                    "type": "origin",
                    "label": origin_text
                }
            },
            # Destination Point
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [dest_coords[0], dest_coords[1]]
                },
                "properties": {
                    "type": "destination",
                    "label": dest_text
                }
            }
        ]

        # Fuel Stop Points
        for stop in (chosen_stops or []):
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": stop['coordinates']
                },
                "properties": {
                    "type": "fuel_stop",
                    "sequence": stop['sequence'],
                    "name": stop['name'],
                    "city": stop['city'],
                    "state": stop['state'],
                    "price_per_gal": stop['price_per_gal'],
                    "gallons_purchased": stop['gallons_purchased'],
                    "stop_cost_usd": stop['stop_cost_usd']
                }
            })

        geojson_map = {
            "type": "FeatureCollection",
            "features": features
        }

        # Calculate Total Gallons consumed
        total_fuel_gallons = round(distance_miles / mpg, 2)

        response_payload = {
            "summary": {
                "route_distance_miles": distance_miles,
                "estimated_duration_hrs": duration_hours,
                "total_fuel_gallons": total_fuel_gallons,
                "total_fuel_cost_usd": total_fuel_cost,
                "fuel_stops_count": len(chosen_stops or [])
            },
            "fuel_stops": chosen_stops or [],
            "map": geojson_map
        }

        # 8. Cache response (TTL 1 hour)
        try:
            cache.set(cache_key, response_payload, timeout=3600)
        except Exception as e:
            logger.warning(f"Failed to cache response: {e}")

        return Response(response_payload, status=status.HTTP_200_OK)


class HealthView(APIView):
    """
    GET /api/health/
    Verifies service health, database status, and configuration.
    """

    def get(self, request, *args, **kwargs):
        db_ok = False
        station_count = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
            station_count = FuelStation.objects.count()
        except Exception as e:
            logger.error(f"Health DB check failed: {e}")

        redis_ok = False
        try:
            cache.set('health_check_ping', 'pong', timeout=10)
            redis_ok = (cache.get('health_check_ping') == 'pong')
        except Exception:
            redis_ok = False

        ors_key_set = bool(getattr(settings, 'ORS_API_KEY', ''))

        payload = {
            "status": "ok" if db_ok else "degraded",
            "stations_count": station_count,
            "db_connection": db_ok,
            "redis_connection": redis_ok,
            "ors_api_key_set": ors_key_set
        }

        status_code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=status_code)
