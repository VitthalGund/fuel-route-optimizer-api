# API Contract

## Endpoints

### 1. `POST /api/route/` — Calculate Optimal Fuel Route

**Content-Type:** `application/json`

#### Request Body

```json
{
    "origin": "Chicago, IL",
    "destination": "Dallas, TX"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `origin` | string | yes | US city/address or "lat,lon" format |
| `destination` | string | yes | US city/address or "lat,lon" format |

**Coordinate shortcut:** If origin/destination match the pattern
`^\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*$`, parse as lat/lon directly
and skip geocoding calls (down to 1 external call total).

#### Success Response — `200 OK`

```json
{
    "summary": {
        "route_distance_miles": 920.4,
        "estimated_duration_hrs": 13.8,
        "total_fuel_gallons": 92.04,
        "total_fuel_cost_usd": 302.17,
        "fuel_stops_count": 2
    },
    "fuel_stops": [
        {
            "opis_id": 1234,
            "name": "Pilot Travel Center #52",
            "city": "Springfield",
            "state": "MO",
            "price_per_gal": 3.099,
            "miles_from_start": 381.2,
            "gallons_purchased": 38.12,
            "stop_cost_usd": 118.14,
            "coordinates": [-93.2917, 37.2153]
        }
    ],
    "map": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-87.6298, 41.8781], "...more coords..."]
                },
                "properties": {
                    "type": "route",
                    "distance_miles": 920.4,
                    "duration_hrs": 13.8
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-93.2917, 37.2153]
                },
                "properties": {
                    "type": "fuel_stop",
                    "sequence": 1,
                    "name": "Pilot Travel Center #52",
                    "price_per_gal": 3.099,
                    "gallons_purchased": 38.12,
                    "stop_cost_usd": 118.14
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-87.6298, 41.8781]
                },
                "properties": { "type": "origin", "label": "Chicago, IL" }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [-96.7970, 32.7767]
                },
                "properties": { "type": "destination", "label": "Dallas, TX" }
            }
        ]
    }
}
```

**Response field details:**

| Field | Computation |
|-------|-------------|
| `total_fuel_gallons` | `route_distance_miles / MPG` |
| `total_fuel_cost_usd` | Sum of all `stop_cost_usd` values |
| `gallons_purchased` | Distance to *next* stop (or destination) ÷ MPG |
| `stop_cost_usd` | `gallons_purchased × price_per_gal` |
| `coordinates` | `[longitude, latitude]` (GeoJSON order) |

#### Error Responses

| Status | Trigger | Response Body |
|--------|---------|---------------|
| `400` | Missing or invalid origin/destination | `{"error": "Invalid origin. Provide a US city/address or lat,lon."}` |
| `400` | Geocoding returned no result | `{"error": "Could not geocode 'XYZ'. Try a more specific US address."}` |
| `422` | Route has a gap > 500 mi with no stations | `{"error": "No fuel stations found between mile 234 and mile 789. Route cannot be completed with a 500-mile range."}` |
| `429` | Rate limit exceeded | `{"error": "Rate limit exceeded. Try again later."}` |
| `503` | ORS API unavailable | `{"error": "Routing service temporarily unavailable.", "retry_after": 30}` |

---

### 2. `GET /api/health/` — Health Check

```json
{
    "status": "ok",
    "stations_count": 6626,
    "db_connection": true,
    "redis_connection": true,
    "ors_api_key_set": true
}
```

| Status | Meaning |
|--------|---------|
| `200` | All services healthy |
| `503` | One or more dependencies down |

---

## Caching Rules

| Aspect | Policy |
|--------|--------|
| **Cache key** | `SHA256(origin_normalised + "\|" + dest_normalised)` |
| **Normalisation** | `text.strip().lower()` |
| **TTL** | 1 hour (3600 seconds) |
| **Backend** | Redis via `django-redis` |
| **Invalidation** | TTL-based only; no manual invalidation needed (static data) |
| **Cache scope** | Full JSON response body |

**Note:** Reverse routes (A→B vs B→A) are different cache keys. This is correct
because the route, stops, and costs differ by direction.

---

## Rate Limiting

```python
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '30/minute',
    },
}
```

This protects the ORS API quota (40 req/min, 2,000 req/day).

---

## Coordinate Convention

All coordinates in the API follow **GeoJSON standard**: `[longitude, latitude]`.

This is the opposite of many mapping APIs that use `(lat, lon)`.
Be consistent throughout the codebase. ORS returns GeoJSON order natively.
