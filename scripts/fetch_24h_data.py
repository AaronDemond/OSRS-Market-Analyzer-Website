#!/usr/bin/env python
r"""
================================================================================
24-HOUR PRICE SNAPSHOT INGEST SCRIPT
================================================================================
What:
    - Polls the OSRS Wiki 24-hour price snapshot endpoint and inserts a single
      TwentyFourHourTimeSeries row per item for each snapshot timestamp.
Why:
    - The alert system needs fast, local access to short-interval price data.
    - Storing each snapshot avoids repeated API calls and supports historical analysis.
How:
    - Load the item ID -> name mapping from item-mapping.json.
    - Fetch the /24h snapshot (single API call).
    - If the snapshot timestamp already exists in the database for ANY item, skip
      the entire snapshot insert to avoid duplication.
    - Build TwentyFourHourTimeSeries objects, leaving missing fields blank (None or 0 when
      the model does not permit NULL), and bulk-insert in a transaction.
    - Loop forever: fetch immediately, then sleep for 24 hours between cycles.
================================================================================
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

import requests

# =============================================================================
# DJANGO SETUP - Required to use Django ORM from a standalone script
# =============================================================================

# SCRIPT_DIR: Directory where this script lives (scripts/)
# What: Absolute path for this file's directory.
# Why: Used to build stable paths to the project root and item mapping file.
# How: Path(__file__).resolve().parent gives an absolute folder path.
SCRIPT_DIR = Path(__file__).resolve().parent

# PROJECT_ROOT: Root of the OSRSWebsite project (one level up from scripts/)
# What: Absolute path to the repository root.
# Why: Needed to import Website.* modules and load static assets.
# How: The project root is the parent of the scripts directory.
PROJECT_ROOT = SCRIPT_DIR.parent

# What: Add the project root to sys.path so Django app modules are importable.
# Why: This script runs outside manage.py, so Python needs explicit module paths.
# How: Insert project root at the start of sys.path for highest import priority.
sys.path.insert(0, str(PROJECT_ROOT))

# What: Point Django at the settings module so ORM can initialize.
# Why: Without DJANGO_SETTINGS_MODULE, django.setup() cannot load settings.
# How: Set the environment variable before calling django.setup().
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django  # noqa: E402  (import after settings are configured)

# What: Initialize Django so ORM models can be imported and used.
# Why: Required for any standalone script that interacts with Django models.
# How: django.setup() loads settings, app configs, and model registrations.
django.setup()

# Now we can safely import Django models
from django.db import transaction  # noqa: E402
from Website.models import TwentyFourHourTimeSeries  # noqa: E402

# =============================================================================
# CONFIGURATION
# =============================================================================

# API_BASE_URL: Base URL for RuneScape Wiki pricing API
# What: Root URL used for the 24h snapshot endpoint.
# Why: Centralized for maintainability and reuse.
# How: Combine with "/24h" to build the request URL.
API_BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'

# API_HEADERS: Required User-Agent header for RuneScape Wiki API
# What: Identifies the application to the API.
# Why: The Wiki API requires a descriptive User-Agent for access.
# How: Passed directly to requests.get(..., headers=API_HEADERS).
API_HEADERS = {'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}

# REQUEST_TIMEOUT_SECONDS: HTTP timeout for the 24h snapshot request
# What: Maximum time to wait for the API response.
# Why: Prevents the script from hanging on slow or stalled requests.
# How: Passed as timeout=REQUEST_TIMEOUT_SECONDS to requests.get.
REQUEST_TIMEOUT_SECONDS = 10

# ITEM_MAPPING_FILE: Path to item-mapping.json (ID -> name mapping)
# What: Absolute path to the local JSON mapping file.
# Why: Used to convert item IDs into human-readable names.
# How: Build path from PROJECT_ROOT / Website / static / item-mapping.json.
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'

# BULK_INSERT_BATCH_SIZE: Number of rows per bulk_create batch
# What: Chunk size for Django bulk insert.
# Why: Keeps SQLite variable limits safe and improves performance.
# How: Passed as batch_size to TwentyFourHourTimeSeries.objects.bulk_create.
BULK_INSERT_BATCH_SIZE = 500

# SLEEP_INTERVAL_SECONDS: Delay between snapshot polls
# What: Sleep duration between fetch cycles.
# Why: The endpoint updates every 24 hours, so we poll on that cadence.
# How: time.sleep(SLEEP_INTERVAL_SECONDS) at the end of each loop.
SLEEP_INTERVAL_SECONDS = 24 * 60 * 60


def log(message):
    """
    Timestamped logger for console output.

    What: Prints a timestamped log line.
    Why: Helps monitor progress and issues in a long-running loop.
    How: Prepends current local time to the provided message.

    Args:
        message: The log message to print.
    """
    # now: Current local datetime for log prefix.
    now = datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M:%S}] {message}")


def load_item_mapping():
    """
    Load item mapping from item-mapping.json.

    What: Reads the JSON list of item objects (each with 'id' and 'name').
    Why: We need item names for denormalized storage in TwentyFourHourTimeSeries.
    How: Open the JSON file and parse it into Python structures.

    Returns:
        list: List of item dicts, or None on failure.
    """
    try:
        with open(ITEM_MAPPING_FILE, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        log(f"ERROR: Item mapping file not found: {ITEM_MAPPING_FILE}")
        return None
    except json.JSONDecodeError as exc:
        log(f"ERROR: Failed to parse item mapping JSON: {exc}")
        return None


def build_id_to_name(items):
    """
    Build an item_id -> item_name lookup from the item mapping list.

    What: Converts a list of item dicts into a dict keyed by ID.
    Why: Provides O(1) lookups when building database rows.
    How: Iterates the mapping list and stores each id/name pair.

    Args:
        items: List of item dicts loaded from item-mapping.json.

    Returns:
        dict: {item_id: item_name} lookup.
    """
    # lookup: Dictionary keyed by numeric item ID with item name values.
    lookup = {}
    for item in items:
        # item_id: Numeric OSRS item ID from the mapping.
        item_id = item.get("id")
        if item_id is None:
            continue

        # item_name: Human-readable item name from the mapping.
        item_name = item.get("name") or ""
        lookup[item_id] = item_name

    return lookup


def name_from_id(item_id, lookup):
    """
    Retrieve an item name from an ID lookup.

    What: Return the item name for a given ID.
    Why: Keeps name resolution logic centralized and consistent.
    How: Use dict.get on the lookup for a safe optional return.
    """
    return lookup.get(item_id)


def fetch_24h_snapshot():
    """
    Fetch the latest 24-hour price snapshot from the OSRS Wiki API.

    What: GET /24h and parse the JSON response.
    Why: The 24h endpoint returns all item price data and a snapshot timestamp.
    How: Use requests.get with headers + timeout, then validate payload shape.

    Returns:
        dict: Parsed JSON payload with 'data' and 'timestamp', or None on failure.
    """
    try:
        # response: Raw HTTP response from the 24h snapshot endpoint.
        response = requests.get(
            f"{API_BASE_URL}/24h",
            headers=API_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        log(f"ERROR: 24h API request failed: {exc}")
        return None

    if response.status_code != 200:
        log(f"ERROR: 24h API returned status {response.status_code}")
        return None

    # payload: Parsed JSON object returned by the API.
    payload = response.json()

    if not isinstance(payload, dict):
        log("ERROR: 24h API payload is not a JSON object.")
        return None

    if "data" not in payload or "timestamp" not in payload:
        log("ERROR: 24h API payload missing required keys (data/timestamp).")
        return None

    return payload


def snapshot_already_ingested(snapshot_timestamp):
    """
    Determine whether a snapshot timestamp already exists in the database.

    What: Checks for any TwentyFourHourTimeSeries row with the same timestamp.
    Why: Requirement says to skip entire snapshot if timestamp already exists.
    How: Use Django ORM .exists() for an efficient DB lookup.

    Args:
        snapshot_timestamp: Timestamp string to check for duplicates.

    Returns:
        bool: True if any row exists with this timestamp, else False.
    """
    return TwentyFourHourTimeSeries.objects.filter(timestamp=snapshot_timestamp).exists()


def chunk_list(items, batch_size):
    """
    Yield successive chunks from a list.

    What: Splits a list into fixed-size batches.
    Why: Needed for bulk_create batches of 500 to match project conventions.
    How: Iterate indices and slice the list for each batch.

    Args:
        items: List of objects to chunk.
        batch_size: Maximum size of each chunk.

    Yields:
        list: A list slice of at most batch_size items.
    """
    # start_index: Current list offset for slicing.
    for start_index in range(0, len(items), batch_size):
        yield items[start_index:start_index + batch_size]


def build_timeseries_objects(snapshot_data, lookup, snapshot_timestamp):
    """
    Build TwentyFourHourTimeSeries objects from snapshot data.

    What: Converts API "data" dict into model instances.
    Why: Enables bulk_create for high-performance inserts.
    How:
        - Iterate each item ID in the snapshot.
        - Skip items with no payload at all.
        - Store missing fields as None (for nullable fields) or 0 (for non-nullable).

    Args:
        snapshot_data: Dict of item_id -> price/volume payload.
        lookup: Dict mapping item IDs to names.
        snapshot_timestamp: Snapshot timestamp for all rows.

    Returns:
        list: List of TwentyFourHourTimeSeries objects ready for bulk_create.
    """
    # objects_to_insert: Accumulates model instances for bulk insert.
    objects_to_insert = []

    for item_id_raw, item_payload in snapshot_data.items():
        # item_id_raw: Raw ID from API dict key (often a string).
        # Why: Must be coerced to int for consistent lookup + storage.
        try:
            item_id = int(item_id_raw)
        except (TypeError, ValueError):
            log(f"WARNING: Invalid item_id '{item_id_raw}', skipping.")
            continue

        # item_payload: Per-item data dict with price/volume fields.
        # Why: Missing or empty payload means the API has no data for this item.
        if not isinstance(item_payload, dict) or not item_payload:
            log(f"INFO: No data for item_id={item_id}; skipping row.")
            continue

        # avg_high_price: Average instant-buy price (nullable in the model).
        # Why: Leave as None if the field is missing from the API payload.
        avg_high_price = item_payload.get("avgHighPrice")

        # avg_low_price: Average instant-sell price (nullable in the model).
        # Why: Leave as None if the field is missing from the API payload.
        avg_low_price = item_payload.get("avgLowPrice")

        # high_price_volume: Volume of high-price trades (non-nullable in model).
        # Why: If missing, use 0 as the safest "blank" representation without a migration.
        high_price_volume = item_payload.get("highPriceVolume")
        if high_price_volume is None:
            high_price_volume = 0

        # low_price_volume: Volume of low-price trades (non-nullable in model).
        # Why: If missing, use 0 as the safest "blank" representation without a migration.
        low_price_volume = item_payload.get("lowPriceVolume")
        if low_price_volume is None:
            low_price_volume = 0

        # item_name: Human-readable name for the item (may be blank if unmapped).
        item_name = name_from_id(item_id, lookup) or ""

        objects_to_insert.append(TwentyFourHourTimeSeries(
            item_id=item_id,
            item_name=item_name,
            avg_low_price=avg_low_price,
            avg_high_price=avg_high_price,
            high_price_volume=high_price_volume,
            low_price_volume=low_price_volume,
            timestamp=snapshot_timestamp,
        ))

    return objects_to_insert


def fetch_and_store_snapshot(lookup):
    """
    Fetch a single 24h snapshot and insert it into the database (if new).

    What: Orchestrates API fetch, duplicate check, object building, and insert.
    Why: Keeps main loop concise and testable.
    How:
        - Fetch snapshot JSON.
        - Normalize timestamp to string.
        - Skip insert if timestamp already exists.
        - Build and bulk-create model instances.

    Args:
        lookup: Item ID -> name dictionary.

    Returns:
        int: Number of rows inserted for this snapshot.
    """
    # snapshot: Raw JSON payload for the current 24h snapshot.
    snapshot = fetch_24h_snapshot()
    if snapshot is None:
        return 0

    # snapshot_timestamp: Canonical snapshot timestamp as a string.
    # Why: TwentyFourHourTimeSeries.timestamp is a CharField, and we need stable comparison.
    snapshot_timestamp = str(snapshot.get("timestamp"))

    if snapshot_already_ingested(snapshot_timestamp):
        log(f"INFO: Snapshot timestamp {snapshot_timestamp} already exists; skipping.")
        return 0

    # snapshot_data: Dict of item_id -> price/volume payloads.
    snapshot_data = snapshot.get("data") or {}

    # objects_to_insert: Prepared model instances for bulk insert.
    objects_to_insert = build_timeseries_objects(
        snapshot_data=snapshot_data,
        lookup=lookup,
        snapshot_timestamp=snapshot_timestamp,
    )

    if not objects_to_insert:
        log("INFO: Snapshot contained no insertable item data.")
        return 0

    # inserted_count: Running total of inserted rows for accurate logging.
    inserted_count = 0
    with transaction.atomic():
        for batch in chunk_list(objects_to_insert, BULK_INSERT_BATCH_SIZE):
            # batch: Current slice of objects to insert in this bulk_create call.
            TwentyFourHourTimeSeries.objects.bulk_create(batch, batch_size=BULK_INSERT_BATCH_SIZE)
            inserted_count += len(batch)

    log(f"Inserted {inserted_count} TwentyFourHourTimeSeries rows.")
    return inserted_count


def main():
    """
    Main execution loop for the 24-hour snapshot ingestor.

    What: Load mapping, build lookup, then run a fetch/sleep loop forever.
    Why: Keeps the script running continuously on a 24-hour cadence.
    How: Fetch immediately, then time.sleep(SLEEP_INTERVAL_SECONDS) between cycles.
    """
    # mapping: Raw list of item dicts from item-mapping.json.
    mapping = load_item_mapping()
    if not mapping:
        log("ERROR: Item mapping could not be loaded; exiting.")
        return

    # lookup: Dictionary mapping item_id -> item_name for fast lookups.
    lookup = build_id_to_name(mapping)

    while True:
        fetch_and_store_snapshot(lookup)
        log("Sleeping for 24 hours...")
        time.sleep(SLEEP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
