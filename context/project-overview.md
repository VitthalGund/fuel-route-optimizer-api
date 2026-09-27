# Project Overview

## Product Definition

**Fuel Route Optimizer API** — A Django REST API that calculates the
cheapest fueling strategy for a road trip across the United States.

Given a start and end location (both within the USA), the API returns:
- The driving route as a GeoJSON polyline
- Optimal fuel stops along the route (cost-optimized)
- Total fuel cost breakdown

## Core Requirements (from Assessment)

| # | Requirement | Constraint |
|---|-------------|------------|
| R1 | Accept start + finish location (both USA) | Free-text city/address OR lat/lon |
| R2 | Return a map of the route | GeoJSON FeatureCollection with LineString |
| R3 | Return optimal fuel stop locations | "Optimal" = cost-effective based on fuel prices |
| R4 | Vehicle max range: 500 miles | Multiple fuel-ups if route exceeds 500 mi |
| R5 | Return total money spent on fuel | Vehicle achieves 10 miles per gallon |
| R6 | Use attached CSV for fuel prices | `fuel-prices-for-be-assessment.csv` (8,151 rows) |
| R7 | Find a free API for map/routing | OpenRouteService selected |
| R8 | Framework: latest stable Django | Django 5.1.x |
| R9 | API must return results quickly | Cold response target: < 2 seconds |
| R10 | Minimize external API calls | Ideal: 1 call. Acceptable: 2–3 calls |

## Vehicle Assumptions

| Parameter | Value |
|-----------|-------|
| Fuel efficiency | 10 miles per gallon (MPG) |
| Tank capacity | 50 gallons (derived: 500 mi ÷ 10 MPG) |
| Maximum range per tank | 500 miles |
| Fueling model | Fill to full at every stop |
| Starting fuel | Full tank at origin |

## Scope

### In Scope
- Single REST endpoint: `POST /api/route/`
- Pre-loaded fuel station data from CSV (one-time pipeline)
- Spatial corridor search for candidate stations
- Dynamic programming optimizer for cheapest stops
- Redis caching of computed routes
- Health check endpoint
- GeoJSON response with route + stop markers

### Out of Scope
- User authentication / accounts
- Frontend / UI
- Real-time fuel price updates
- Multi-vehicle support
- Waypoint / multi-stop routes (beyond fuel stops)
- Alternate route suggestions
- Electric vehicle charging

## Success Criteria

1. Chicago, IL → Dallas, TX returns a valid route with 2 fuel stops in < 2 seconds
2. Repeated identical queries return in < 20 ms (cache hit)
3. No more than 3 external API calls per cold request
4. All fuel stop gaps ≤ 500 miles
5. Total cost matches hand-calculation: `(route_miles / MPG) × weighted_avg_price`
