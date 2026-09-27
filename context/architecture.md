# Architecture

## System Overview

```
┌──────────────┐     ┌───────────────────────────────────────────────┐
│   Client     │────▶│  Django 5.1 + DRF                            │
│  (any HTTP)  │◀────│                                               │
└──────────────┘     │  POST /api/route/                             │
                     │    ├─ Cache check (Redis)                     │
                     │    ├─ Geocode origin + dest (ORS, 2 calls)    │
                     │    ├─ Get route polyline (ORS, 1 call)        │
                     │    ├─ Corridor query (PostGIS or Shapely)     │
                     │    ├─ DP optimizer (pure Python)              │
                     │    └─ Build GeoJSON + cache + return          │
                     └──────────────┬──────────────┬────────────────┘
                                    │              │
                          ┌─────────▼──┐    ┌──────▼──────┐
                          │ PostgreSQL  │    │   Redis 7   │
                          │ + PostGIS   │    │  (cache)    │
                          │ (Supabase)  │    └─────────────┘
                          └────────────┘
                                    ▲
                                    │ one-time load
                          ┌─────────┴──────────┐
                          │ fuel-prices CSV     │
                          │ + Nominatim geocode │
                          └────────────────────┘
```

## Tech Stack

| Layer | Choice | Version | Why |
|-------|--------|---------|-----|
| Framework | Django + DRF | 5.1.x / 3.15.x | Required by assessment |
| Database | PostgreSQL + PostGIS | 16 / 3.4 | Spatial queries (ST_DWithin, GiST index) |
| Hosting DB | Supabase (free tier) | — | Free PostGIS out of the box |
| Spatial ORM | GeoDjango (`django.contrib.gis`) | built-in | Native PostGIS function exposure |
| Cache | Redis via `django-redis` | 7.x | Response caching, sub-5ms hits |
| HTTP client | `httpx` | 0.27.x | Async-capable for batch geocoding |
| Routing API | OpenRouteService (ORS) | v2 | Free: 2,000 req/day, geocoding + routing |
| Geocoding (bulk) | Nominatim or Photon | OSM | Free, one-time pipeline use only |
| Config | `django-environ` | 0.11.x | 12-factor `.env` config |

## Database Schema

### FuelStation Model

```python
from django.contrib.gis.db import models

class FuelStation(models.Model):
    opis_id       = models.IntegerField(unique=True, db_index=True)
    name          = models.CharField(max_length=200)
    address       = models.CharField(max_length=300)
    city          = models.CharField(max_length=100)
    state         = models.CharField(max_length=2, db_index=True)
    retail_price  = models.DecimalField(max_digits=6, decimal_places=4)
    location      = models.PointField(geography=True, srid=4326)

    class Meta:
        indexes = [
            models.Index(fields=['state', 'retail_price']),
        ]
```

**Key decisions:**
- `geography=True` → distance calculations in metres (accurate across US)
- `srid=4326` → WGS84 (matches ORS and OSM coordinate systems)
- GiST spatial index auto-created by GeoDjango on `PointField`
- `unique=True` on `opis_id` enforces deduplication at DB level

### Geography vs Geometry Caveat

`ST_LineLocatePoint` requires **geometry**, not geography. Two approaches:

**Option A — PostGIS cast (if ST_LineLocatePoint available on Supabase):**
```sql
ST_LineLocatePoint(route_geom::geometry, station_location::geometry)
```

**Option B — Shapely fallback (recommended primary approach):**
```python
from shapely.geometry import LineString, Point
route = LineString(route_coords)
frac = route.project(Point(lon, lat), normalized=True)
```

**Decision: Use Shapely as primary, PostGIS as optional optimization.**
This avoids GDAL dependency issues and geography/geometry casting complexity.

## External API: OpenRouteService (ORS)

| Endpoint | Purpose | Calls per Request |
|----------|---------|-------------------|
| `GET /geocode/search?text=...` | Resolve text address → lat/lon | 2 (one per location) |
| `GET /v2/directions/driving-hgv` | Get route polyline + distance | 1 |

**Call budget per request:**

| User Input | Geocode Calls | Route Calls | Total |
|------------|---------------|-------------|-------|
| Text addresses | 2 | 1 | **3** |
| Lat/lon coordinates | 0 | 1 | **1** |
| Cache hit | 0 | 0 | **0** |

**ORS free tier limits:**
- 2,000 requests/day
- 40 requests/minute
- API key required (stored in `.env`)

## Request Flow

```
Client POST /api/route/ {"origin": "Chicago, IL", "destination": "Dallas, TX"}
  │
  ▼
① Validate + normalise input (serializer)
  │
  ▼
② Cache lookup: SHA256(lower(origin) + "|" + lower(destination))
  │
  ├─ HIT → return cached response (< 5ms)
  │
  ▼ MISS
③ Geocode origin → (lat, lon)          [ORS call 1]
④ Geocode destination → (lat, lon)     [ORS call 2]
  │
  ▼
⑤ Get route: origin→dest polyline     [ORS call 3]
   Returns: GeoJSON LineString, total_distance_m, duration_s
  │
  ▼
⑥ Corridor query: find stations within 15 miles of route
   - PostGIS: ST_DWithin(location, route, 24140m) with GiST index
   - Returns 50–300 candidates for cross-country routes
  │
  ▼
⑦ Project stations onto route (Shapely)
   - Calculate each station's distance-from-start in miles
   - Sort ascending by route_miles
  │
  ▼
⑧ DP optimizer: select cheapest subset of stops
   - Constraint: no gap > 500 miles
   - O(n × ~30) effective complexity, < 1ms runtime
  │
  ▼
⑨ Build response: GeoJSON FeatureCollection + cost summary
  │
  ▼
⑩ Cache response in Redis (TTL = 1 hour)
  │
  ▼
Return 200 OK with response JSON
```

## PostGIS / Supabase Configuration

**Connection:** Use Supabase **direct connection** (port 5432), NOT the
pooler (port 6543). GeoDjango needs session-mode connections.

```
DATABASE_URL=postgis://postgres.xxxx:password@aws-0-region.pooler.supabase.com:5432/postgres
```

**PostGIS extensions** are enabled by default on Supabase free tier.

## Fallback: Shapely + Pure Python (if PostGIS issues arise)

If PostGIS/GeoDjango integration doesn't work (GDAL issues, Supabase
limitations), the fallback is:

1. Use plain `django.db.backends.postgresql` (not postgis backend)
2. Store station lat/lon as `FloatField` (not `PointField`)
3. Filter stations by bounding box SQL query (simple WHERE on lat/lon)
4. Use `shapely.geometry.LineString.buffer()` for corridor
5. Use `shapely.ops.nearest_points()` for projection
6. All spatial operations in Python memory after initial DB fetch

**Performance:** Nearly identical for this use case. The DB fetch with
bounding box filter is O(log n) with a B-tree index on lat/lon.

## Invariants

1. **No external API calls on cache hit** — cached responses served from Redis only
2. **At most 3 external API calls on cold request** — 2 geocode + 1 route
3. **No fuel stop gap exceeds 500 miles** — enforced by DP constraint
4. **All stations are US-only** — Canadian provinces filtered at load time
5. **Station data is static** — loaded once from CSV, never updated at runtime
6. **Fuel price per station is the minimum** across all CSV rows for that OPIS ID
