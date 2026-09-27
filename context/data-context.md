# Data Context

## CSV File: `fuel-prices-for-be-assessment.csv`

### Schema

| Column | Type | Example | Notes |
|--------|------|---------|-------|
| `OPIS Truckstop ID` | int | `7` | Primary key for dedup |
| `Truckstop Name` | string | `WOODSHED OF BIG CABIN` | May have name variants for same ID |
| `Address` | string | `I-44, EXIT 283 & US-69` | Highway-exit format; needs geocoding |
| `City` | string | `Big Cabin` | Used with State for geocoding context |
| `State` | string | `OK` | 2-letter code; includes Canadian provinces |
| `Rack ID` | int | `307` | Not used — pricing region identifier |
| `Retail Price` | float | `3.00733333` | USD per gallon; 4+ decimal precision |

### Data Statistics (Verified)

| Metric | Value |
|--------|-------|
| Total CSV rows | 8,151 |
| Unique OPIS Truckstop IDs | 6,738 |
| US-only states after filtering | ~48 states + DC |
| Canadian provinces in data | AB, BC, MB, NB, NS, ON, QC, SK, YT |
| Canadian rows to filter out | **620 rows → 112 unique stations** |
| US stations after dedup | **~6,626** |
| Price range | $2.687 – $6.399 per gallon |
| Null values | **None** (clean dataset) |

### Duplicate Analysis

Duplicates (same OPIS ID, multiple rows) fall into two categories:

1. **Multiple price entries** — same station, different fuel grades or pricing tiers
   - Example: OPIS 105 (TA Saginaw) has 6 rows: $3.269, $3.339, $3.429, etc.

2. **Name variants** — same station, same price, different name spelling
   - Example: OPIS 20 → "PILOT TRAVEL CENTER #1243" and "PILOT #1243"

**Dedup strategy:** Keep the row with the **lowest Retail Price** per OPIS ID.
This ensures the optimizer always sees the best available deal.

### US State Filter

```python
US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL',
    'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME',
    'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH',
    'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
}

CANADIAN_PROVINCES_TO_EXCLUDE = {
    'AB', 'BC', 'MB', 'NB', 'NS', 'ON', 'QC', 'SK', 'YT'
}
```

---

## Data Pipeline: `load_fuel_stations` Management Command

### Purpose
One-time command run on deploy. Loads, cleans, geocodes, and inserts
all fuel stations into the database. After completion, the CSV is
never touched again at runtime.

### Pipeline Steps

```
CSV file
  │
  ▼
Step 1: Load CSV with pandas
  │
  ▼
Step 2: Filter to US-only states
  │  Remove rows where State ∈ {AB, BC, MB, NB, NS, ON, QC, SK, YT}
  │
  ▼
Step 3: Deduplicate by OPIS Truckstop ID
  │  Sort by Retail Price ascending
  │  drop_duplicates('OPIS Truckstop ID', keep='first')
  │  Result: ~6,626 unique US stations
  │
  ▼
Step 4: Batch geocode via Nominatim (or Photon)
  │  Query: "{Address}, {City}, {State}, USA"
  │  Rate limit: 1 req/sec (Nominatim) or ~10/sec (Photon)
  │  Estimated time: ~2 hrs (Nominatim) or ~12 min (Photon)
  │  Store results: latitude, longitude per station
  │  Log failures for manual review
  │
  ▼
Step 5: Bulk insert into FuelStation table
  │  bulk_create(stations, batch_size=500)
  │  Skip stations that failed geocoding (log count)
  │
  ▼
Step 6: Verify
  │  Print total inserted count
  │  Confirm GiST spatial index exists
  │  Run sample ST_DWithin query to validate
  │
  ▼
Done. Database ready for queries.
```

### Geocoding Strategy

**Primary: Nominatim (OpenStreetMap)**
- Free, no API key required
- Rate limit: 1 request/second (strict)
- Query format: `"{Address}, {City}, {State}, USA"`
- Good accuracy for US addresses

**Alternative: Photon (OSM mirror)**
- Free, no API key, higher throughput
- Rate limit: ~10 requests/second on public instance
- Same OSM data as Nominatim
- Faster: ~12 min vs ~2 hrs for full dataset

**Fallback for failed geocodes:**
- Some addresses (highway exits) may fail geocoding
- Fallback query: `"{City}, {State}, USA"` (city-level precision)
- Stations that fail both attempts are logged and skipped
- Expected failure rate: < 5%

### Geocoding Result Caching

To avoid re-geocoding on repeat runs (e.g., during development):
- Save geocoded results to a JSON/CSV file alongside the pipeline
- On subsequent runs, load cached results first, only geocode new/failed entries
- This is critical during development iteration

---

## Corridor Query Logic

### How It Works

Given a route LineString from ORS, find all fuel stations within
15 miles (24,140 metres) of the route path.

**PostGIS approach:**
```sql
SELECT * FROM api_fuelstation
WHERE ST_DWithin(location, <route_linestring>, 24140)
-- 24,140 metres ≈ 15 miles
-- Uses GiST spatial index → O(log n)
```

**Shapely approach (primary — avoids GDAL):**
```python
from shapely.geometry import LineString, Point

route = LineString(route_coords)  # from ORS GeoJSON
buffer = route.buffer(0.217)       # ~15 miles in degrees

candidates = []
for station in FuelStation.objects.filter(
    latitude__range=(min_lat - 0.3, max_lat + 0.3),
    longitude__range=(min_lon - 0.3, max_lon + 0.3)
):
    pt = Point(station.longitude, station.latitude)
    if buffer.contains(pt):
        frac = route.project(pt, normalized=True)
        station.route_miles = frac * route_length_mi
        candidates.append(station)

candidates.sort(key=lambda s: s.route_miles)
```

**Buffer distance conversion:**
- 15 miles ≈ 24,140 metres ≈ 0.217° latitude
- Longitude degrees vary by latitude; 0.217° is approximate but sufficient
  for the corridor filter (a generous over-estimate is fine — the optimizer
  handles the rest)

---

## DP Fuel-Stop Optimizer Algorithm

### Problem Statement

Given:
- An ordered list of candidate fuel stations along the route
- Each station has: `route_miles` (distance from start) and `retail_price`
- Vehicle starts at origin with a full tank (50 gal, 500 mi range)
- At each stop, vehicle fills to full

Find the subset of stations that minimizes total fuel cost,
subject to: no two consecutive stops (including origin and destination)
are more than 500 miles apart.

### Algorithm: Shortest Path on DAG

This is a shortest-path problem on a directed acyclic graph:
- **Nodes:** [origin, station_0, station_1, ..., station_n, destination]
- **Edges:** Connect any pair reachable within 500 miles
- **Edge weight:** `(gap_miles / MPG) × price_at_departure_node`
- **Solution:** DP with path reconstruction

### Corrected Implementation

```python
def optimal_stops(candidates, route_miles, tank_range=500, mpg=10):
    """
    candidates: list of dicts with 'route_miles' and 'retail_price'
                sorted ascending by route_miles
    route_miles: total route distance in miles
    tank_range: max distance per tank (default 500)
    mpg: miles per gallon (default 10)

    Returns: (chosen_stops, total_cost)
    """
    # Build node list: [origin, ...stations..., destination]
    # Origin has price=0 (we don't buy fuel there — tank is full)
    # Destination has price=0 (we don't buy fuel there)
    nodes = [(0, 0)]  # (position, price)
    for s in candidates:
        nodes.append((s['route_miles'], float(s['retail_price'])))
    nodes.append((route_miles, 0))

    n = len(nodes)
    INF = float('inf')
    dp = [INF] * n      # dp[i] = min cost to reach node i
    prev = [-1] * n      # for path reconstruction

    dp[0] = 0

    for i in range(n - 1):
        if dp[i] == INF:
            continue
        pos_i, price_i = nodes[i]
        for j in range(i + 1, n):
            pos_j, _ = nodes[j]
            gap = pos_j - pos_i
            if gap > tank_range:
                break  # sorted — no further j reachable
            gallons = gap / mpg
            cost = dp[i] + gallons * price_i
            if cost < dp[j]:
                dp[j] = cost
                prev[j] = i

    # Reconstruct path
    if dp[n - 1] == INF:
        return None, None  # No valid path — gap > 500mi somewhere

    path = []
    cur = n - 1
    while prev[cur] != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()

    # Map back to station objects (exclude origin=0 and destination=n-1)
    chosen = [candidates[i - 1] for i in path if 0 < i < n - 1]
    total_cost = dp[n - 1]

    return chosen, total_cost
```

### Cost Model: Fill-to-Full

The DP computes cost as: *"fuel purchased at station i to drive to
the next stop"*. Since the vehicle fills to full at every stop:

- `gallons_purchased_at_stop = gap_to_next_stop / MPG`
- `cost_at_stop = gallons_purchased × price_per_gallon`
- `total_cost = sum(cost_at_each_stop)`

**Edge case — no valid path:**
If any gap between consecutive stations (including origin/destination)
exceeds 500 miles, the route is impossible. Return HTTP 422 with
a description of the unreachable gap.

### Complexity

- Theoretical: O(n²) where n = number of candidate stations
- Practical: O(n × ~30) because the inner loop breaks at 500mi
- For 300 candidates: < 1 millisecond in CPython
