#!/usr/bin/env python
r"""
=============================================================================
BULK HISTORICAL VOLUME BACKFILL SCRIPT
=============================================================================
What: One-time script that fetches the FULL hourly timeseries history for every
      OSRS item and saves ALL hourly records to the HourlyItemVolume table.

Why: The regular update_volumes.py script only saves the most recent hour's data
     per cycle. This script backfills the entire available history from the API,
     giving a large dataset of historical hourly volume (in GP) for analysis,
     charting, and future features.

How: 1. Loads the item mapping (all known OSRS items)
     2. For each item, fetches timeseries data with timestep=1h from the Wiki API
     3. For EVERY hourly entry in the response (not just the latest), calculates
        GP volume: (highPriceVolume + lowPriceVolume) × ((avgHighPrice + avgLowPrice) / 2)
     4. Bulk-inserts all HourlyItemVolume records
     5. Uses 15 parallel workers for faster fetching

Volume Calculation:
    Same formula as update_volumes.py:
    volume_gp = (highPriceVolume + lowPriceVolume) × ((avgHighPrice + avgLowPrice) / 2)
    Entries where either price is null are skipped (can't calculate GP volume).

API Response:
    The /timeseries?timestep=1h endpoint returns up to ~300 hourly data points
    per item (roughly 12-13 days of history). Each entry contains:
      - timestamp: Unix epoch for the start of that hour
      - avgHighPrice, avgLowPrice: Prices during that hour
      - highPriceVolume, lowPriceVolume: Units traded during that hour

Parallelism:
    Uses ThreadPoolExecutor with 15 workers for aggressive parallel fetching.
    This is a one-time backfill, so higher parallelism is acceptable vs. the
    recurring update_volumes.py which uses 6 workers.

Usage:
    python scripts\backfill_volumes.py

    This is a ONE-TIME script. Run it once to populate the history, then rely on
    update_volumes.py for ongoing hourly updates. Running it again will create
    duplicate records (the model has no unique constraint on item_id + timestamp).

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
# 15 workers for aggressive parallel fetching — acceptable for a one-time backfill.
# Higher than update_volumes.py's 6 workers since this only runs once.
MAX_WORKERS = 5

# API_HEADERS: Required User-Agent header for RuneScape Wiki API.
# The Wiki API requires a descriptive User-Agent to identify the application.
API_HEADERS = {'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}

# API_BASE_URL: Base URL for the RuneScape Wiki pricing API.
API_BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'

# ITEM_MAPPING_FILE: Path to the local JSON file containing item ID/name mappings.
# This file is the same one used by update_volumes.py and the main Django app.
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'

# BULK_INSERT_BATCH_SIZE: Number of records to insert per bulk_create call.
# 500 is safe for SQLite's variable limit (default max 999 variables per query).
BULK_INSERT_BATCH_SIZE = 500


def log(message):
    """
    Simple logging with timestamp.

    What: Prints a timestamped message to stdout
    Why: Track progress and errors during the backfill process
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
    Why: We need every item ID and name to fetch their full volume history.
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


def fetch_single_item_history(item_tuple):
    """
    Fetch the FULL hourly timeseries history for a single item and convert all
    entries to GP volume records.

    What: Makes one API request for a single item's timeseries data, then processes
          EVERY hourly entry (not just the latest) into HourlyItemVolume-ready dicts.
    Why: This is the core of the backfill — we want the entire available history
         (up to ~300 hourly data points / ~12 days) for each item.
    How:
        1. GET /timeseries?timestep=1h&id={item_id}
        2. Iterate over ALL entries in the response 'data' array
        3. For each entry with valid prices, calculate:
           volume_gp = (highPriceVolume + lowPriceVolume) × ((avgHighPrice + avgLowPrice) / 2)
        4. Convert the API's Unix timestamp to a Python datetime for the timestamp field
        5. Return a list of dicts, one per valid hourly entry

    Args:
        item_tuple: (item_id, item_name) tuple identifying the item to fetch

    Returns:
        list: List of dicts [{'item_id': int, 'item_name': str, 'volume': int, 'timestamp': datetime}, ...]
              One dict per valid hourly entry. May be empty if item has no data.
        None: If the API call fails entirely
    """
    # item_id: The OSRS item ID to fetch history for
    # item_name: The human-readable item name for database storage
    item_id, item_name = item_tuple

    try:
        # Make the API request using 1h timestep to get hourly timeseries data.
        # The response 'data' array contains ALL available hourly entries (oldest first),
        # typically ~300 entries covering the last ~12-13 days.
        response = requests.get(
            f'{API_BASE_URL}/timeseries?timestep=1h&id={item_id}',
            headers=API_HEADERS,
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()
        if 'data' not in data or len(data['data']) < 1:
            return None

        # timeseries: Full list of hourly data entries sorted oldest-first.
        # Each entry has: timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume
        timeseries = data['data']

        # records: Accumulates valid volume records for this item.
        # Will contain one dict per hourly entry where both prices are available.
        records = []

        for entry in timeseries:
            # avg_high_price: Average instant-buy price during this hour (None if no buys)
            # avg_low_price: Average instant-sell price during this hour (None if no sells)
            avg_high_price = entry.get('avgHighPrice')
            avg_low_price = entry.get('avgLowPrice')

            # Skip entries where either price is missing — can't calculate GP volume
            # without knowing the item's price. Common for low-activity items in
            # off-peak hours where no buys or sells occurred.
            if avg_high_price is None or avg_low_price is None:
                continue

            # high_vol: Number of items instant-bought during this hour
            # low_vol: Number of items instant-sold during this hour
            high_vol = entry.get('highPriceVolume', 0) or 0
            low_vol = entry.get('lowPriceVolume', 0) or 0

            # total_units: Total number of items traded (bought + sold) this hour
            total_units = high_vol + low_vol

            # avg_price: Midpoint of high and low prices, used to convert units → GP
            avg_price = (avg_high_price + avg_low_price) // 2

            # volume_gp: Hourly trading volume in GP (gold pieces)
            # This is the value stored in the database.
            volume_gp = total_units * avg_price

            # entry_timestamp: The API's Unix timestamp converted to a Python datetime.
            # The API returns the start-of-hour Unix epoch (e.g., 1707184800 = 2024-02-06 00:00:00).
            # We use datetime.fromtimestamp() to convert it for Django's DateTimeField.
            api_timestamp = entry.get('timestamp', 0)
            entry_timestamp = datetime.fromtimestamp(api_timestamp)

            records.append({
                'item_id': item_id,
                'item_name': item_name,
                'volume': volume_gp,
                'timestamp': entry_timestamp,
            })

        return records

    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        # Silently skip items that fail — don't let one bad item crash the whole backfill.
        return None


def fetch_all_item_histories(items_to_fetch):
    """
    Fetch full hourly history for all items using 15 parallel HTTP requests.

    What: Orchestrates fetching the complete timeseries for every OSRS item.
    Why: There are ~3500+ items and no batch API endpoint, so we must make
         individual requests. Using 15 parallel workers keeps total fetch time
         manageable (~5-10 minutes) for this one-time backfill.
    How: Uses ThreadPoolExecutor with max_workers=15. Submits all items as futures,
         collects results as they complete, flattens into a single list of records.

    Args:
        items_to_fetch: List of (item_id, item_name) tuples for all items

    Returns:
        list: Flat list of all volume record dicts across all items.
              Each dict has: item_id, item_name, volume, timestamp
    """
    # all_records: Accumulates volume records from all items into one flat list
    all_records = []
    # total: Number of items to process (for progress logging)
    total = len(items_to_fetch)
    # completed: Counter for progress tracking
    completed = 0
    # items_with_data: Counter for items that returned at least one valid record
    items_with_data = 0

    log(f"Fetching full hourly history for {total} items with {MAX_WORKERS} parallel workers...")

    # Use ThreadPoolExecutor to limit concurrent API requests to MAX_WORKERS (15).
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all fetch tasks to the executor.
        # futures: Dict mapping Future objects to their input item tuples
        futures = {
            executor.submit(fetch_single_item_history, item): item
            for item in items_to_fetch
        }

        # Process results as each future completes (not in submission order).
        for future in as_completed(futures):
            completed += 1

            # result: List of volume record dicts for this item, or None on failure
            result = future.result()
            # item_tuple: The (item_id, item_name) tuple that produced this result
            item_tuple = futures[future]

            if result is not None and len(result) > 0:
                all_records.extend(result)
                items_with_data += 1
                # Log every successful fetch with item name and record count
                log(f"  [{completed}/{total}] {item_tuple[1]} (ID: {item_tuple[0]}) — {len(result)} records")
            else:
                # Log skipped/failed items so the operator knows what was missed
                log(f"  [{completed}/{total}] {item_tuple[1]} (ID: {item_tuple[0]}) — skipped (no data)")

    log(f"Fetch complete: {completed}/{total} items processed")
    log(f"  - {items_with_data} items had valid data")
    log(f"  - {len(all_records)} total hourly records collected")
    return all_records


def save_records(records):
    """
    Save all collected volume records to the HourlyItemVolume table.

    What: Bulk-creates HourlyItemVolume records in the database.
    Why: Inserting potentially hundreds of thousands of records one at a time
         would be extremely slow. bulk_create with batch_size handles this efficiently.
    How: Builds HourlyItemVolume model instances from the record dicts, then uses
         Django's bulk_create() with batch_size=500 for efficient batch insertion.

    Args:
        records: List of dicts with 'item_id', 'item_name', 'volume', 'timestamp' keys

    Returns:
        int: Number of records successfully created
    """
    if not records:
        log("WARNING: No records to save")
        return 0

    log(f"Building {len(records)} model instances...")

    # volume_objects: List of HourlyItemVolume model instances to bulk-insert.
    # Built in memory first, then inserted in batches.
    volume_objects = [
        HourlyItemVolume(
            item_id=record['item_id'],
            item_name=record['item_name'],
            volume=record['volume'],
            timestamp=record['timestamp'],
        )
        for record in records
    ]

    log(f"Inserting {len(volume_objects)} records into database (batch_size={BULK_INSERT_BATCH_SIZE})...")

    try:
        # bulk_create with batch_size splits the insert into manageable chunks.
        # This is critical for SQLite which has a variable limit per query.
        HourlyItemVolume.objects.bulk_create(volume_objects, batch_size=BULK_INSERT_BATCH_SIZE)
        log(f"SUCCESS: {len(volume_objects)} records inserted")
        return len(volume_objects)
    except Exception as e:
        log(f"ERROR: bulk_create failed: {e}")
        # Fallback: try inserting in smaller batches to identify problem records
        log("Attempting fallback: inserting in small batches of 100...")
        created = 0
        for i in range(0, len(volume_objects), 100):
            batch = volume_objects[i:i + 100]
            try:
                HourlyItemVolume.objects.bulk_create(batch, batch_size=100)
                created += len(batch)
            except Exception as batch_error:
                log(f"  Batch {i // 100 + 1} failed: {batch_error}")
        log(f"Fallback complete: {created}/{len(volume_objects)} records saved")
        return created


def main():
    """
    Main entry point for the one-time volume history backfill.

    What: Orchestrates the full backfill process: load items → fetch all history → save to DB.
    Why: Populates the HourlyItemVolume table with ~12 days of historical hourly volume data
         for every OSRS item, providing a large dataset for analysis and future features.
    How: Sequential steps with progress logging. Runs once and exits (no loop).
    """
    start_time = time.time()
    log("=" * 70)
    log("BULK HISTORICAL VOLUME BACKFILL")
    log(f"Parallel workers: {MAX_WORKERS}")
    log("This is a ONE-TIME script — it fetches the full available history")
    log("=" * 70)

    # Step 1: Load item mapping from local JSON file
    log("Step 1: Loading item mapping...")
    item_mapping = load_item_mapping()
    if not item_mapping:
        log("FATAL: Cannot proceed without item mapping")
        sys.exit(1)

    log(f"Found {len(item_mapping)} items in mapping")

    # Step 2: Build list of (item_id, item_name) tuples for fetching.
    # items_to_fetch: Each element is a tuple consumed by fetch_single_item_history()
    items_to_fetch = [
        (item_data['id'], item_data['name'])
        for item_data in item_mapping
    ]

    # Step 3: Fetch full hourly history for all items (15 concurrent requests)
    log("Step 2: Fetching full timeseries history for all items...")
    all_records = fetch_all_item_histories(items_to_fetch)

    if not all_records:
        log("FATAL: No records collected — nothing to save")
        sys.exit(1)

    # Step 4: Save all records to the database
    log("Step 3: Saving records to database...")
    created = save_records(all_records)

    # Step 5: Summary
    elapsed = time.time() - start_time
    log("=" * 70)
    log("BACKFILL COMPLETE")
    log(f"  Total time: {elapsed:.1f} seconds ({elapsed / 60:.1f} minutes)")
    log(f"  Items processed: {len(items_to_fetch)}")
    log(f"  Records saved: {created}")
    if created > 0:
        # avg_records_per_item: Average number of hourly records per item
        avg_records_per_item = created / len(items_to_fetch)
        log(f"  Avg records per item: {avg_records_per_item:.1f}")
    log("=" * 70)


if __name__ == '__main__':
    main()
