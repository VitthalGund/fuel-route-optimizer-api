# 🗺️ Fuel Route Optimizer API

A high-performance Django REST API that calculates the most cost-effective fuel stops for a road trip within the USA. By providing a start and finish location, the API generates a full driving route and intelligently selects where to fuel up based on a vehicle's range, fuel efficiency, and real-time gas prices.

---

## 📸 Demo

<img width="1349" height="597" alt="image" src="https://github.com/user-attachments/assets/43c4a5e3-090e-4256-a414-aec9c213130c" />
<img width="935" height="560" alt="image" src="https://github.com/user-attachments/assets/762b9d17-b0c9-415d-9ab6-784d576a4969" />
<img width="927" height="264" alt="image" src="https://github.com/user-attachments/assets/e329d960-8201-44ea-a820-05d2f66a52c9" />


![Map Preview](https://via.placeholder.com/800x450.png?text=Frontend+Map+Preview+Screenshot+Goes+Here)

*The included `preview.html` offers a lightweight, interactive Leaflet.js map to visualize the API's route and selected stops.*

---

## ✨ Features

- **Intelligent Route Optimization:** Uses a custom Dynamic Programming (DP) algorithm to minimize total fuel cost rather than just picking the cheapest nearby stations (Greedy approach).
- **Spatial Corridor Filtering:** Utilizes `Shapely` to create a 15-mile buffer along the route polyline, filtering out fuel stations that require significant detours.
- **High-Performance Caching:** SHA-256 hashed origin-destination queries are cached in **Redis** for instant subsequent retrievals.
- **Resilient Geocoding & Routing:** Integrates with **OpenRouteService (ORS)** with smart fallback parsing for raw coordinates and text-based locations.
- **Cross-Platform Compatibility:** Replaces heavy GDAL/GeoDjango dependencies with lightweight Shapely and pure PostgreSQL indexing for seamless setup on Windows environments.

---

## 🛠️ Technical Architecture

### Tech Stack
- **Backend Framework:** Django 5.1 & Django REST Framework (DRF)
- **Database:** PostgreSQL (via Supabase) or local SQLite fallback
- **Caching:** Redis
- **Spatial Math:** Shapely (Python)
- **External Services:** OpenRouteService API (Routing & Geocoding)
- **Frontend (Preview):** HTML5, Vanilla JS, Leaflet.js, CartoDB Voyager tiles

### Core Algorithm
The fuel stop optimizer operates in two main phases:
1. **Corridor Extraction:** The routing engine fetches the driving polyline. We construct a spatial buffer (polygon) representing a 15-mile corridor. Stations within this buffer are mapped to their closest distance along the route.
2. **Cost Minimization (DP):** A Dynamic Programming matrix evaluates every valid sequence of stops (constrained by the 500-mile max range and 10 MPG efficiency). It calculates the exact gallons needed to reach the next stop, evaluating fuel prices to guarantee the absolute minimum financial cost for the entire trip.

---

## 📖 API Documentation

### 1. Calculate Route & Optimal Stops
**Endpoint:** `POST /api/route/`

Calculates the optimal driving route and the cheapest sequence of fuel stops.

**Request Body (JSON):**
```json
{
  "origin": "Dallas, TX",
  "destination": "Atlanta, GA"
}
```

**Successful Response (`200 OK`):**
```json
{
  "summary": {
    "route_distance_miles": 781.5,
    "estimated_duration_hrs": 11.4,
    "total_fuel_gallons": 78.15,
    "total_fuel_cost_usd": 245.30,
    "fuel_stops_count": 2
  },
  "fuel_stops": [
    {
      "sequence": 1,
      "name": "Buc-ee's",
      "city": "Terrell",
      "state": "TX",
      "price_per_gal": 2.95,
      "miles_from_start": 35.2,
      "gallons_purchased": 50.0,
      "stop_cost_usd": 147.50,
      "coordinates": [-96.275, 32.735]
    }
  ],
  "map": {
    "type": "FeatureCollection",
    "features": [
      // ... GeoJSON representation of the Route LineString and Point features
    ]
  }
}
```

### 2. System Health Check
**Endpoint:** `GET /api/health/`

Returns the live status of the API, Database, and Redis cache. Used by monitoring tools and the frontend UI.

**Successful Response (`200 OK`):**
```json
{
  "status": "ok",
  "stations_count": 500,
  "db_connection": true,
  "redis_connection": true,
  "ors_api_key_set": true
}
```

---

## 🚀 Local Development Setup

### Prerequisites
- Python 3.10+
- Redis Server (Optional but recommended)
- PostgreSQL (Optional, defaults to SQLite)
- OpenRouteService API Key (Free)

### 1. Clone & Install Dependencies
```bash
git clone <repository_url>
cd "Backend Django Engineer"
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file in the root directory (where `manage.py` is):
```env
# Core
SECRET_KEY=your_secure_django_key
DEBUG=True

# Database (Supabase Session Pooler or Local)
# Leave blank to use local SQLite automatically
DATABASE_URL=postgres://[user]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres

# Redis Cache (Optional)
REDIS_URL=redis://127.0.0.1:6379/1

# 3rd Party APIs
ORS_API_KEY=your_openrouteservice_api_key
```

### 3. Database Setup & Data Ingestion
Run migrations to generate the database schema:
```bash
python manage.py migrate
```

Load the initial fuel stations from the provided CSV file. This command asynchronously parses, cleans, and geocodes thousands of addresses:
```bash
python manage.py load_fuel_stations
```

### 4. Run the Server
Start the Django development server:
```bash
python manage.py runserver
```

You can now test the API via Postman or open the visual preview by navigating to `http://127.0.0.1:8000/api/preview/` (or simply opening `preview.html` in your browser).

---

## 🧪 Testing
The project includes a robust suite of unit and integration tests covering the DP algorithm math, spatial geometry filtering, and API handlers.

To run the test suite:
```bash
pytest
```
*Note: Ensure your `.env` contains valid configurations or use mock flags if running in a constrained CI/CD pipeline.*
