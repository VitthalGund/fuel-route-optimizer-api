"""
Management command to load, clean, geocode, and populate fuel stations from CSV.
"""
import os
import json
import time
import asyncio
from pathlib import Path
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction

from api.models import FuelStation

# Set of Canadian province codes to filter out
CANADIAN_PROVINCES = {
    'AB', 'BC', 'MB', 'NB', 'NS', 'ON', 'QC', 'SK', 'YT'
}

# Valid US States and territories
US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL',
    'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME',
    'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH',
    'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
}


class Command(BaseCommand):
    help = "Loads fuel stations from CSV, deduplicates, geocodes, and populates database."

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            type=str,
            default='data/fuel-prices-for-be-assessment.csv',
            help='Path to fuel prices CSV file'
        )
        parser.add_argument(
            '--cache-file',
            type=str,
            default='data/geocoded_stations_cache.json',
            help='Path to geocoding cache JSON'
        )
        parser.add_argument(
            '--concurrency',
            type=int,
            default=6,
            help='Concurrency limit for Photon/Nominatim geocoding'
        )
        parser.add_argument(
            '--max-records',
            type=int,
            default=0,
            help='Limit number of records to process (0 = all)'
        )

    def handle(self, *args, **options):
        csv_path = Path(options['csv'])
        cache_path = Path(options['cache_file'])
        concurrency = options['concurrency']
        max_records = options['max_records']

        if not csv_path.exists():
            # Try alternate path
            csv_path = Path(settings.BASE_DIR) / options['csv']
            if not csv_path.exists():
                csv_path = Path(settings.BASE_DIR) / 'fuel-prices-for-be-assessment.csv'

        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f"CSV file not found at {csv_path}"))
            return

        self.stdout.write(self.style.NOTICE(f"Loading CSV: {csv_path}"))
        df = pd.read_csv(csv_path)
        total_raw_rows = len(df)
        self.stdout.write(f"Total raw rows in CSV: {total_raw_rows}")

        # 1. Filter out Canadian provinces
        df_us = df[~df['State'].str.strip().str.upper().isin(CANADIAN_PROVINCES)].copy()
        df_us = df_us[df_us['State'].str.strip().str.upper().isin(US_STATES)]
        self.stdout.write(f"US-only rows after removing Canadian records: {len(df_us)}")

        # 2. Deduplicate by OPIS Truckstop ID: keep lowest Retail Price
        df_dedup = df_us.sort_values(by='Retail Price', ascending=True).drop_duplicates(
            subset=['OPIS Truckstop ID'],
            keep='first'
        ).copy()

        total_stations = len(df_dedup)
        self.stdout.write(self.style.SUCCESS(f"Unique US stations to process: {total_stations}"))

        if max_records > 0:
            df_dedup = df_dedup.head(max_records)
            self.stdout.write(f"Processing limited to first {max_records} stations.")

        # 3. Load or initialize geocoding cache
        cache_data: Dict[str, Any] = {}
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                self.stdout.write(f"Loaded {len(cache_data)} cached geocoded stations from {cache_path}")
            except Exception as e:
                self.stderr.write(f"Could not load cache file: {e}")

        # 4. Run async geocoding
        stations_to_geocode = []
        for _, row in df_dedup.iterrows():
            opis_id = str(row['OPIS Truckstop ID'])
            if opis_id not in cache_data:
                stations_to_geocode.append({
                    'opis_id': int(row['OPIS Truckstop ID']),
                    'name': str(row['Truckstop Name']).strip(),
                    'address': str(row['Address']).strip(),
                    'city': str(row['City']).strip(),
                    'state': str(row['State']).strip().upper(),
                    'retail_price': float(row['Retail Price']),
                })

        self.stdout.write(f"Stations needing geocoding: {len(stations_to_geocode)}")

        if stations_to_geocode:
            self.stdout.write(self.style.NOTICE("Starting geocoding pipeline..."))
            new_geocoded = asyncio.run(self._geocode_stations_async(stations_to_geocode, concurrency))
            cache_data.update(new_geocoded)
            
            # Save updated cache
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Geocoding cache saved to {cache_path}"))

        # 5. Populate Database
        self.stdout.write("Populating database...")
        records_to_create = []
        skipped_count = 0

        for _, row in df_dedup.iterrows():
            opis_id_str = str(row['OPIS Truckstop ID'])
            geo = cache_data.get(opis_id_str)
            if not geo or 'lat' not in geo or 'lon' not in geo:
                skipped_count += 1
                continue

            records_to_create.append(
                FuelStation(
                    opis_id=int(row['OPIS Truckstop ID']),
                    name=str(row['Truckstop Name']).strip()[:200],
                    address=str(row['Address']).strip()[:300],
                    city=str(row['City']).strip()[:100],
                    state=str(row['State']).strip().upper()[:2],
                    retail_price=Decimal(str(round(float(row['Retail Price']), 4))),
                    latitude=float(geo['lat']),
                    longitude=float(geo['lon']),
                )
            )

        with transaction.atomic():
            # Delete existing records to reload cleanly or bulk create
            FuelStation.objects.all().delete()
            created_stations = FuelStation.objects.bulk_create(records_to_create, batch_size=500)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully populated {len(created_stations)} FuelStation records into database! "
            f"(Skipped/unresolved: {skipped_count})"
        ))

    async def _geocode_stations_async(self, stations: List[Dict[str, Any]], concurrency: int) -> Dict[str, Dict[str, float]]:
        semaphore = asyncio.Semaphore(concurrency)
        results = {}
        headers = {"User-Agent": "FuelRoutePipeline/1.0 (Django Geocoder)"}
        
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            tasks = [
                self._geocode_single_station(client, station, semaphore)
                for station in stations
            ]
            completed = await asyncio.gather(*tasks)
            for item in completed:
                if item:
                    opis_id, coords = item
                    results[str(opis_id)] = coords
        return results

    async def _geocode_single_station(
        self,
        client: httpx.AsyncClient,
        station: Dict[str, Any],
        semaphore: asyncio.Semaphore
    ) -> Optional[Tuple[int, Dict[str, float]]]:
        opis_id = station['opis_id']
        city = station['city']
        state = station['state']
        address = station['address']

        async with semaphore:
            # 1. Try Photon Geocoder (Fast OSM search)
            try:
                query = f"{city}, {state}, USA"
                url = "https://photon.komoot.io/api/"
                resp = await client.get(url, params={"q": query, "limit": 1})
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    if features:
                        coords = features[0]["geometry"]["coordinates"] # [lon, lat]
                        return opis_id, {"lon": coords[0], "lat": coords[1]}
            except Exception:
                pass

            # 2. Fallback to Nominatim
            try:
                await asyncio.sleep(0.5) # respectful delay
                nom_url = "https://nominatim.openstreetmap.org/search"
                nom_resp = await client.get(nom_url, params={
                    "q": f"{city}, {state}, USA",
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "us"
                })
                if nom_resp.status_code == 200:
                    nom_data = nom_resp.json()
                    if nom_data:
                        lat = float(nom_data[0]["lat"])
                        lon = float(nom_data[0]["lon"])
                        return opis_id, {"lon": lon, "lat": lat}
            except Exception:
                pass

        return None
