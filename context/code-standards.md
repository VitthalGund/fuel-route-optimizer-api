# Code Standards

## Project Structure

```
fuel_route/                            # Django project root
├── fuel_route/                        # Core config package
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py                    # Common: INSTALLED_APPS, DATABASES, CACHES, REST_FRAMEWORK
│   │   ├── development.py            # DEBUG=True, verbose logging
│   │   └── production.py             # DEBUG=False, ALLOWED_HOSTS, security
│   ├── urls.py                        # Root URL conf
│   └── wsgi.py
│
├── api/                               # Main Django app
│   ├── __init__.py
│   ├── models.py                      # FuelStation model (PointField)
│   ├── serializers.py                 # RouteRequestSerializer, RouteResponseSerializer
│   ├── views.py                       # RouteView, HealthView
│   ├── urls.py                        # /api/route/, /api/health/
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ors_client.py             # ORS geocode() + get_route() functions
│   │   ├── corridor.py               # get_candidate_stations() — PostGIS or Shapely
│   │   └── optimizer.py              # optimal_stops() — DP algorithm
│   ├── management/
│   │   └── commands/
│   │       └── load_fuel_stations.py  # One-time data pipeline
│   └── tests/
│       ├── __init__.py
│       ├── test_optimizer.py          # Unit tests for DP algorithm
│       ├── test_corridor.py           # Unit tests for corridor query
│       ├── test_ors_client.py         # Tests with mocked ORS responses
│       └── test_views.py             # Integration tests for API endpoint
│
├── data/
│   └── fuel-prices-for-be-assessment.csv  # Source data file
│
├── .env                               # Environment variables (not committed)
├── .env.example                       # Template with placeholder values
├── .gitignore
├── requirements.txt
├── manage.py
├── context/                           # Project knowledge base
│   └── ...
└── Agent.md                           # Agent entry point
```

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Django app | lowercase, singular | `api` |
| Models | PascalCase, singular | `FuelStation` |
| Serializers | PascalCase + `Serializer` | `RouteRequestSerializer` |
| Views | PascalCase + `View` | `RouteView` |
| Services | snake_case module + descriptive function | `corridor.get_candidate_stations()` |
| Management commands | snake_case | `load_fuel_stations` |
| URL paths | lowercase, trailing slash | `/api/route/` |
| Environment variables | SCREAMING_SNAKE_CASE | `ORS_API_KEY` |
| Constants | SCREAMING_SNAKE_CASE | `CORRIDOR_METRES = 24_140` |
| Test files | `test_` prefix | `test_optimizer.py` |
| Test methods | `test_` prefix, descriptive | `test_optimal_stops_two_stops_required` |

## Python / Django Conventions

### General
- Python 3.11+ (match Django 5.1 compatibility)
- Use type hints for all function signatures in service modules
- Use f-strings for string formatting
- Maximum line length: 99 characters (Black default)
- Imports: `isort` standard (stdlib → third-party → local)

### Django-Specific
- All settings via `django-environ` from `.env` — no hardcoded secrets
- Use `settings/base.py` for shared config; override in `development.py` / `production.py`
- Set `DJANGO_SETTINGS_MODULE` via `.env` or environment variable
- Database: use `dj-database-url` style connection string (`DATABASE_URL`)
- All model fields must have explicit `max_length`, `decimal_places`, etc.
- Use `bulk_create` with `batch_size` for large inserts (management command)

### DRF-Specific
- Use `APIView` (not generic views) for the single route endpoint
- Input validation via `Serializer` — never validate manually in views
- Return `Response()` with explicit status codes
- Use DRF throttling for rate limiting

### Services Layer
- Business logic lives in `api/services/`, NOT in views
- Each service module has one clear responsibility
- Services receive plain data (dicts, tuples) and return plain data
- Services do NOT import Django REST Framework classes
- Services CAN import Django ORM / GeoDjango

### Error Handling
- Raise `rest_framework.exceptions` in views for HTTP errors
- Services return `None` or raise `ValueError` for business logic failures
- ORS client: wrap `httpx` exceptions into descriptive `ServiceUnavailableError`
- Always include a human-readable `error` key in error responses

## Dependencies (requirements.txt)

```
Django==5.1.4
djangorestframework==3.15.2
django-environ==0.11.2
psycopg2-binary==2.9.9
httpx==0.27.0
django-redis==5.4.0
redis==5.0.3
pandas==2.2.2
Shapely==2.0.4
pytest==8.2.0
pytest-django==4.8.0
gunicorn==22.0.0
```

### Dependency Notes
- **No GDAL** — using Shapely for spatial operations to avoid Windows install issues
- **Shapely** added as explicit dependency for corridor queries and route projection
- **pandas** used only in management command (not at request time)
- `psycopg2-binary` for dev; use `psycopg2` (compiled) for production
- **GeoDjango** (`django.contrib.gis`) is built into Django — no separate install
  - If using GeoDjango PointField: need GDAL/GEOS libraries installed (Docker or conda)
  - If using plain FloatField fallback: no GDAL needed

### Conditional GeoDjango Usage

The project supports two modes:

**Mode A — Full GeoDjango (PostGIS backend):**
- `DATABASES.ENGINE = 'django.contrib.gis.db.backends.postgis'`
- `FuelStation.location = PointField(geography=True, srid=4326)`
- Requires GDAL/GEOS system libraries
- Uses ST_DWithin for corridor queries

**Mode B — Plain Django + Shapely (fallback):**
- `DATABASES.ENGINE = 'django.db.backends.postgresql'`
- `FuelStation.latitude = FloatField()` + `FuelStation.longitude = FloatField()`
- No system library dependencies
- Uses Shapely for all spatial operations
- Bounding box SQL filter replaces spatial index

**Decision:** Start with Mode B (simpler, no GDAL pain). Upgrade to
Mode A only if performance demands it (unlikely for this dataset size).

## Environment Variables (.env)

```env
# Django
SECRET_KEY=change-me-in-production
DEBUG=True
DJANGO_SETTINGS_MODULE=fuel_route.settings.development

# Database (Supabase PostgreSQL — direct connection, port 5432)
DATABASE_URL=postgis://postgres.xxxx:YOUR_PASSWORD@aws-0-region.pooler.supabase.com:5432/postgres

# Redis (local dev)
REDIS_URL=redis://localhost:6379/0

# OpenRouteService
ORS_API_KEY=your-ors-api-key-here

# Corridor settings (optional overrides)
CORRIDOR_MILES=15
TANK_RANGE_MILES=500
VEHICLE_MPG=10
```

## Git Conventions

- `.gitignore` must include: `.env`, `__pycache__/`, `*.pyc`, `db.sqlite3`, `.venv/`
- Commit the CSV file (`data/fuel-prices-for-be-assessment.csv`) — it's part of the assessment
- Commit `.env.example` with placeholder values
- Do NOT commit geocoded station cache files
