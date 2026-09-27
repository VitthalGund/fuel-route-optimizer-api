# AI Workflow Rules

## Development Philosophy

1. **Get it working, then optimise.** Start with the simplest correct
   implementation (Mode B: plain Django + Shapely). Only add complexity
   (PostGIS, Celery, async) when a measured bottleneck demands it.

2. **One external dependency, fully understood.** ORS handles both
   geocoding and routing. Don't introduce a second API unless ORS
   is provably insufficient.

3. **Static data, fast queries.** The fuel station dataset is loaded
   once and never changes at runtime. Every optimisation flows from
   this fact: spatial indexes, in-memory filtering, aggressive caching.

## Implementation Order

Build in this exact sequence. Each step should produce a testable,
runnable state before proceeding to the next.

| Phase | Task | Deliverable | Test |
|-------|------|-------------|------|
| **1** | Bootstrap Django project | `manage.py runserver` works | Server starts |
| **2** | Settings + `.env` + Supabase DB connection | DB connected | `manage.py migrate` succeeds |
| **3** | `FuelStation` model + migration | Table created | `manage.py shell` → `FuelStation.objects.count()` |
| **4** | `load_fuel_stations` management command | ~6,626 stations in DB | Count matches; spot-check 5 stations |
| **5** | `ors_client.py` | Geocode + route functions | Manual test: Chicago → Dallas |
| **6** | `corridor.py` | Candidate station list | Returns 50–300 for Chicago → Dallas |
| **7** | `optimizer.py` | Cheapest stop set | Unit tests: 0 stops, 1 stop, 2 stops, impossible route |
| **8** | `RouteView` + serializers | `POST /api/route/` returns JSON | curl test returns valid GeoJSON |
| **9** | Redis caching | Cache hit < 20ms | Second identical request is instant |
| **10** | Health endpoint | `GET /api/health/` | Returns station count + service status |
| **11** | Error handling | 400/422/503 responses | Test each error case |
| **12** | Rate limiting | 429 on excess | Send 31 requests in 1 minute |

## Scoping Rules

### Do
- Build the single `POST /api/route/` endpoint completely before anything else
- Test each service module in isolation before wiring into the view
- Cache aggressively — the data is static
- Log ORS API call count per request (for quota monitoring)
- Handle all three error cases (bad input, impossible route, ORS down)

### Don't
- Don't build a frontend — this is API-only
- Don't add authentication — not required
- Don't implement real-time price updates — prices are from the CSV
- Don't add WebSocket/streaming — simple request/response is fine
- Don't optimise for concurrent requests until single-request latency is proven
- Don't add Celery unless background cache-warming is explicitly needed
- Don't deploy to production — local development + Supabase DB is sufficient

## Testing Approach

### Unit Tests (required)
- `test_optimizer.py`:
  - Route with 0 fuel stops needed (< 500 mi)
  - Route with exactly 1 stop needed
  - Route with 2+ stops needed
  - Impossible route (gap > 500 mi) → returns None
  - Tie-breaking: two stations at same distance, different prices
  - Edge: station at exactly 500 miles from start

- `test_corridor.py`:
  - Returns stations sorted by route_miles ascending
  - Filters out stations beyond corridor width
  - Empty result when no stations near route

- `test_ors_client.py`:
  - Mock successful geocode response
  - Mock successful route response
  - Mock ORS timeout → raises appropriate error
  - Mock ORS 429 → raises rate limit error

### Integration Tests (required)
- `test_views.py`:
  - Happy path: valid origin + destination → 200 with all required fields
  - Invalid input → 400
  - Cache hit returns same response
  - GeoJSON structure is valid

### Test Fixtures
- Use `pytest-django` with `@pytest.fixture`
- Create a small set of test stations (10–20) with known coordinates
- Mock ORS responses with pre-recorded JSON fixtures
- Never call live ORS API in automated tests

## Delivery Checklist

Before considering the project complete:

- [ ] `POST /api/route/` returns correct GeoJSON for at least 3 test routes
- [ ] Chicago, IL → Dallas, TX works end-to-end
- [ ] New York, NY → Los Angeles, CA works (cross-country, 4+ stops)
- [ ] Short route (< 500 mi, 0 stops needed) works
- [ ] Repeated request returns cached response in < 20ms
- [ ] `GET /api/health/` returns station count and service status
- [ ] Invalid input returns 400 with helpful message
- [ ] No more than 3 ORS API calls per cold request
- [ ] All fuel stop gaps ≤ 500 miles
- [ ] Total cost calculation matches: `(distance / 10) × avg_price`
- [ ] Canadian stations are excluded from database
- [ ] `.env.example` committed with placeholder values
- [ ] All tests pass

## Context File Maintenance

- Update `progress-tracker.md` after completing each phase
- If a service module's API changes, update `architecture.md`
- If the response schema changes, update `api-contract.md`
- If a new dependency is added, update `code-standards.md`
- If an invariant is violated or changed, update `architecture.md`
