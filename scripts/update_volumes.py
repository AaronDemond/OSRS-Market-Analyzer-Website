#!/usr/bin/env python
r"""
=============================================================================
HOURLY ITEM VOLUME UPDATE SCRIPT
=============================================================================
What: Standalone script that fetches hourly trading volume (in GP) for every
      OSRS item from the RuneScape Wiki API and stores it in the database.

Why: Sustained move alerts need volume data to filter out low-activity items.
     Previously, volume was fetched via individual API calls inside check_alerts.py
     during each alert check cycle. For "all items" alerts, this meant hundreds
     of HTTP requests per cycle (every 5 seconds). This script pre-fetches volume
     data on a schedule and stores it in the HourlyItemVolume model, so the alert
     checker can do fast database lookups instead of live API calls.

How: 1. Loads the item mapping (all known OSRS items)
     2. For each item, fetches timeseries data with timestep=1h from the Wiki API
     3. Extracts the most recent hour's volume data:
        - total_units = highPriceVolume + lowPriceVolume
        - avg_price = (avgHighPrice + avgLowPrice) / 2
        - volume_gp = total_units * avg_price
     4. Bulk-inserts HourlyItemVolume records (one per item per cycle)
     5. Sleeps for 1 hour 5 minutes, then repeats

Volume Calculation:
    The volume stored is in GP (gold pieces), NOT raw units traded.
    This gives a more meaningful measure of market activity — 100 trades of a
    10M GP item (1B GP volume) is more significant than 100 trades of a 5 GP item
    (500 GP volume).

Schedule:
    Runs immediately on launch, then loops every 1h5m (3900 seconds).
    The 5-minute offset prevents alignment with other hourly processes.

Parallelism:
    Uses ThreadPoolExecutor with 6 workers (6 concurrent API requests at a time).
    This balances speed against API rate limits.

Usage:
    python scripts\update_volumes.py

=============================================================================
"""

import os
import sys
import json
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# =============================================================================
# DJANGO SETUP - Required to use Django ORM from standalone script
# =============================================================================
# What: Configures Django settings so we can import models
# Why: This script runs outside of Django's normal request/response cycle
# How: Set DJANGO_SETTINGS_MODULE and call django.setup() before importing models

# SCRIPT_DIR: Directory where this script lives (scripts/)
SCRIPT_DIR = Path(__file__).resolve().parent

# PROJECT_ROOT: Root of the OSRSWebsite project (one level up from scripts/)
PROJECT_ROOT = SCRIPT_DIR.parent

# Add project root to Python path so we can import the Website module
sys.path.insert(0, str(PROJECT_ROOT))

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django
django.setup()

# Now we can safely import Django models
from Website.models import HourlyItemVolume

# =============================================================================
# CONFIGURATION
# =============================================================================

# MAX_WORKERS: Number of parallel API requests to make at once.
# 6 workers means 6 HTTP requests in flight simultaneously.
# This balances speed (fetching ~3500 items) against respecting API rate limits.
MAX_WORKERS = 6

# SLEEP_INTERVAL: Time in seconds between fetch cycles.
# 3900 seconds = 1 hour and 5 minutes.
# The 5-minute offset avoids collision with other hourly processes/caches.
SLEEP_INTERVAL = 3900

# API_HEADERS: Required User-Agent header for RuneScape Wiki API.
# The Wiki API requires a descriptive User-Agent to identify the application.
API_HEADERS = {'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}

# API_BASE_URL: Base URL for the RuneScape Wiki pricing API.
API_BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'

# ITEM_MAPPING_FILE: Path to the local JSON file containing item ID/name mappings.
# This file is the same one used by update_trending.py and the main Django app.
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'


def log(message):
    """
    Simple logging with timestamp.

    What: Prints a timestamped message to stdout
    Why: Track progress and errors during long-running script execution
    How: Prepends ISO-formatted timestamp to the message string

    Args:
        message: String to log
    """
    # timestamp: Current time formatted as YYYY-MM-DD HH:MM:SS for readability
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")


def load_item_mapping():
    """
    Load item mapping from local JSON file.

    What: Reads the full list of OSRS items from the static item-mapping.json file.
    Why: We need to know every item ID and name to fetch volume data for all items.
    How: Reads the JSON file which contains a list of dicts, each with 'id' and 'name' keys.

    Returns:
        list: List of item dicts [{'id': int, 'name': str, ...}, ...], or None on failure
    """
    try:
        with open(ITEM_MAPPING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        log(f"ERROR: Item mapping file not found: {ITEM_MAPPING_FILE}")
        return None
    except json.JSONDecodeError as e:
        log(f"ERROR: Failed to parse item mapping JSON: {e}")
        return None


def fetch_single_item_volume(item_tuple):
    """
    Fetch hourly volume data for a single item from the RuneScape Wiki API.

    What: Makes one API request for a single item's timeseries data, extracts the
          most recent hour's volume, and converts it from units to GP.
    Why: Called in parallel by ThreadPoolExecutor — each item needs its own API call
         because the timeseries endpoint requires a single item ID.
    How:
        1. GET /timeseries?timestep=1h&id={item_id}
        2. Extract the most recent entry from the response data
        3. Calculate GP volume: (highPriceVolume + lowPriceVolume) × avg_price
           where avg_price = (avgHighPrice + avgLowPrice) / 2
        4. Return dict ready for HourlyItemVolume.objects.create()

    Args:
        item_tuple: (item_id, item_name) tuple identifying the item to fetch

    Returns:
        dict: {'item_id': int, 'item_name': str, 'volume': int} on success
        None: If the API call fails or price data is missing (can't calculate GP volume)
    """
    # item_id: The OSRS item ID to fetch volume for
    # item_name: The human-readable item name for database storage
    item_id, item_name = item_tuple

    try:
        # Make the API request using 1h timestep to get hourly volume data.
        # The response contains a 'data' array of hourly entries, each with:
        #   - timestamp: Unix timestamp for the start of the hour
        #   - avgHighPrice: Average instant-buy price during that hour
        #   - avgLowPrice: Average instant-sell price during that hour
        #   - highPriceVolume: Number of items instant-bought during that hour
        #   - lowPriceVolume: Number of items instant-sold during that hour
        response = requests.get(
            f'{API_BASE_URL}/timeseries?timestep=1h&id={item_id}',
            headers=API_HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return None

        data = response.json()
        if 'data' not in data or len(data['data']) < 1:
            return None

        # timeseries: List of hourly data entries sorted oldest-first.
        # We want the most recent entry (last element) for the latest hour's volume.
        timeseries = data['data']
        # latest_entry: The most recent hourly data point from the timeseries
        latest_entry = timeseries[-1]

        # Extract prices for the most recent hour.
        # avg_high_price: Average instant-buy price in GP (or None if no buys occurred)
        # avg_low_price: Average instant-sell price in GP (or None if no sells occurred)
        avg_high_price = latest_entry.get('avgHighPrice')
        avg_low_price = latest_entry.get('avgLowPrice')

        # Skip items where either price is missing — we can't calculate GP volume
        # without knowing the item's price. This can happen for items with zero
        # trading activity in the most recent hour.
        if avg_high_price is None or avg_low_price is None:
            return None

        # high_vol: Number of items instant-bought in the most recent hour
        # low_vol: Number of items instant-sold in the most recent hour
        high_vol = latest_entry.get('highPriceVolume', 0) or 0
        low_vol = latest_entry.get('lowPriceVolume', 0) or 0

        # total_units: Total number of items traded (bought + sold) in the hour
        total_units = high_vol + low_vol

        # avg_price: Midpoint of high and low prices, used to convert units → GP.
        # Integer division is fine here — we don't need sub-GP precision.
        avg_price = (avg_high_price + avg_low_price) // 2

        # volume_gp: The hourly trading volume measured in GP (gold pieces).
        # This is the core value stored in the database.
        # Example: 5000 items traded × 500,000 GP average = 2,500,000,000 GP
        volume_gp = total_units * avg_price

        return {
            'item_id': item_id,
            'item_name': item_name,
            'volume': volume_gp,
            'timestamp': latest_entry['timestamp']
        }

    except (requests.RequestException, KeyError, TypeError, ValueError):
        # Silently skip items that fail — don't let one bad item crash the whole batch.
        # Common failure modes: network timeout, malformed JSON, unexpected data shape.
        return None


def fetch_all_volumes(items_to_fetch):
    """
    Fetch hourly volume for all items using semi-parallel HTTP requests.

    What: Orchestrates fetching volume data for every OSRS item, 6 at a time.
    Why: There are ~3500+ items and no batch API endpoint for timeseries data,
         so we must make individual requests. Using 6 parallel workers keeps
         total fetch time reasonable (~10-15 minutes) without overwhelming the API.
    How: Uses ThreadPoolExecutor with max_workers=6. Submits all items as futures,
         collects results as they complete, and logs progress every 500 items.

    Args:
        items_to_fetch: List of (item_id, item_name) tuples for all items

    Returns:
        list: List of dicts [{'item_id': int, 'item_name': str, 'volume': int}, ...]
              Only includes items where volume was successfully calculated.
    """
    # results: Accumulates successful volume data dicts as futures complete
    results = []
    # total: Number of items to fetch (used for progress logging)
    total = len(items_to_fetch)
    # completed: Counter for progress tracking
    completed = 0

    log(f"Fetching hourly volume for {total} items with {MAX_WORKERS} parallel workers...")

    # Use ThreadPoolExecutor to limit concurrent API requests to MAX_WORKERS (6).
    # Each worker fetches one item's timeseries data at a time.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all fetch tasks. The executor queues them internally and runs
        # up to MAX_WORKERS concurrently.
        # futures: Dict mapping Future objects to their input item tuples (for debugging)
        futures = {
            executor.submit(fetch_single_item_volume, item): item
            for item in items_to_fetch
        }

        # Process results as each future completes (not necessarily in submission order).
        # as_completed() yields futures as soon as they finish, maximizing throughput.
        for future in as_completed(futures):
            completed += 1

            # Log progress every 500 items so the operator knows the script is alive
            if completed % 500 == 0:
                log(f"Progress: {completed}/{total} items processed...")

            # result: The return value from fetch_single_item_volume() — either a dict or None
            result = future.result()
            if result is not None:
                results.append(result)

    log(f"Completed: {completed}/{total} items processed, {len(results)} with valid volume data")
    return results


def save_volumes(volume_data_list):
    """
    Save volume data to HourlyItemVolume model as new historical rows.

    What: Bulk-creates HourlyItemVolume records in the database.
    Why: Each fetch cycle creates NEW rows (not upserts) to build historical volume data.
         This allows future features like volume trend analysis, volume charts, etc.
    How: Uses Django's bulk_create() for efficient batch insertion. All rows in a single
         cycle share the same timestamp (when the fetch cycle started).

    Args:
        volume_data_list: List of dicts with 'item_id', 'item_name', 'volume' keys

    Returns:
        int: Number of records successfully created
    """
    if not volume_data_list:
        log("WARNING: No volume data to save")
        return 0

    # fetch_timestamp: The time when this fetch cycle ran.
    # All rows created in this cycle share the same timestamp for consistency.
    # This makes it easy to identify which records came from the same fetch cycle.
    fetch_timestamp = datetime.now()

    # volume_objects: List of HourlyItemVolume model instances to bulk-insert.
    # We build them all in memory first, then insert in one DB operation.
    volume_objects = [
        HourlyItemVolume(
            item_id=item_data['item_id'],
            item_name=item_data['item_name'],
            volume=item_data['volume'],
            timestamp=item_data['timestamp']
        )
        for item_data in volume_data_list
    ]

    log(f"Saving {len(volume_objects)} volume records to database...")

    try:
        # batch_size=500: Insert in batches of 500 to avoid overwhelming SQLite's
        # variable limit (default max is 999 variables per query).
        # For PostgreSQL this could be higher, but 500 is safe for all backends.
        HourlyItemVolume.objects.bulk_create(volume_objects, batch_size=500)
        log(f"Database: {len(volume_objects)} records created (timestamp: {fetch_timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
        return len(volume_objects)
    except Exception as e:
        log(f"ERROR: Failed to bulk-create volume records: {e}")
        # Fallback: try creating records one at a time to save what we can
        # This is slower but ensures partial data is saved even if some records fail
        created = 0
        for obj in volume_objects:
            try:
                obj.save()
                created += 1
            except Exception:
                pass
        log(f"Fallback: saved {created}/{len(volume_objects)} records individually")
        return created


def run_update_cycle():
    """
    Execute a single volume update cycle.

    What: Loads item mapping, fetches volume for all items, saves to database.
    Why: Encapsulates one full fetch-and-store cycle so it can be called in a loop.
    How: Sequential steps: load mapping → build item list → fetch volumes → save to DB.

    Returns:
        bool: True if the cycle completed successfully, False on fatal error
    """
    # start_time: Track how long the full cycle takes for performance monitoring
    start_time = time.time()
    log("=" * 60)
    log("Starting hourly volume update...")
    log("=" * 60)

    # Step 1: Load item mapping from local JSON file
    log("Loading item mapping...")
    item_mapping = load_item_mapping()
    if not item_mapping:
        log("FATAL: Cannot proceed without item mapping")
        return False

    log(f"Found {len(item_mapping)} items in mapping")

    # Step 2: Build list of (item_id, item_name) tuples for fetching.
    # items_to_fetch: Each element is a tuple consumed by fetch_single_item_volume()
    items_to_fetch = [
        (item_data['id'], item_data['name'])
        for item_data in item_mapping
    ]

    # Step 3: Fetch hourly volume for all items (6 concurrent requests)
    volume_data = fetch_all_volumes(items_to_fetch)

    # Step 4: Save to database
    if volume_data:
        created = save_volumes(volume_data)
        # elapsed: Total time taken for this cycle in seconds
        elapsed = time.time() - start_time
        log(f"Update completed successfully in {elapsed:.1f} seconds ({created} records)")
    else:
        log("WARNING: No volume data fetched — nothing saved to database")

    return True


def main():
    """
    Main entry point — runs the volume update in a continuous loop.

    What: Executes a volume update immediately on launch, then sleeps for 1h5m
          and repeats indefinitely.
    Why: Volume data needs to be refreshed periodically. Running immediately on launch
         ensures the database has data as soon as the script starts. The 1h5m interval
         aligns with hourly API data while avoiding exact-hour collisions.
    How: Infinite loop with try/except around each cycle to prevent crashes from
         killing the long-running process. Only KeyboardInterrupt (Ctrl+C) stops it.
    """
    log("=" * 60)
    log("HOURLY VOLUME UPDATER STARTED")
    log(f"Fetch interval: {SLEEP_INTERVAL} seconds ({SLEEP_INTERVAL / 3600:.1f} hours)")
    log(f"Parallel workers: {MAX_WORKERS}")
    log("=" * 60)

    while True:
        try:
            # Run one full fetch-and-store cycle
            run_update_cycle()
        except KeyboardInterrupt:
            # Allow clean exit via Ctrl+C
            log("Received keyboard interrupt — shutting down")
            break
        except Exception as e:
            # Catch ALL other exceptions to prevent the loop from dying.
            # Log the error and continue to the next cycle.
            # This handles transient issues like network outages, DB locks, etc.
            log(f"ERROR: Update cycle failed with unexpected error: {e}")

        # Sleep until the next cycle
        log(f"Sleeping for {SLEEP_INTERVAL} seconds ({SLEEP_INTERVAL / 3600:.1f} hours)...")
        try:
            time.sleep(SLEEP_INTERVAL)
        except KeyboardInterrupt:
            log("Received keyboard interrupt during sleep — shutting down")
            break


if __name__ == '__main__':
    main()
