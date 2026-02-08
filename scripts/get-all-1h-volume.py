#!/usr/bin/env python
r"""
================================================================================
ONE-TIME BACKFILL: HourlyItemVolume (1h resolution)
================================================================================
What:
    Fetches the full 1-hour timeseries history for every OSRS item from the
    RuneScape Wiki API and bulk-inserts it into the HourlyItemVolume table.

Why:
    The continuous fetch script (fetch_hourly_volume.py) only inserts the LATEST
    snapshot each hour. When the database is cleared or first set up, there is no
    historical volume data. This script backfills the full history (~300 data
    points per item at 1h resolution) so that volume-dependent alerts
    (spike, spread, sustained, threshold) can filter by volume immediately.

How:
    1. Load the item mapping (all OSRS items with IDs and names).
    2. Build an item_id -> item_name lookup dictionary.
    3. Use async HTTP (aiohttp) to fetch /timeseries?timestep=1h&id={item_id}
       for every item, with concurrency limited by a semaphore.
    4. For each item's response, convert every data point into an
       HourlyItemVolume model instance with computed GP volume.
    5. Bulk-insert all rows in a single atomic transaction.
    6. Exit after the insert completes (this is NOT a continuous loop script).

Volume Calculation:
    volume_gp = (avgHighPrice * highPriceVolume) + (avgLowPrice * lowPriceVolume)
    This is the correct weighted formula: each trade side is multiplied by its
    actual price, not averaged. Null prices default to 0 so partial data is
    captured (e.g. items that only traded on one side in an hour).

Usage:
    python scripts\get-all-1h-volume.py

Notes:
    - Run this ONCE after clearing the database. Then start fetch_hourly_volume.py
      for ongoing incremental updates.
    - Uses ignore_conflicts=True so it can be safely re-run without crashing on
      duplicate (item_id, timestamp) pairs.
    - The HourlyItemVolume model has unique_together = ['item_id', 'timestamp'],
      so duplicates are silently skipped rather than causing IntegrityError.
================================================================================
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp

# =============================================================================
# DJANGO SETUP — Required to use Django ORM from a standalone script
# =============================================================================

# SCRIPT_DIR: Absolute path to the directory containing this script (scripts/).
# Why: Used to derive PROJECT_ROOT and locate static files.
# How: Path(__file__).resolve().parent gives the directory of the current file.
SCRIPT_DIR = Path(__file__).resolve().parent

# PROJECT_ROOT: Absolute path to the repository root (one level up from scripts/).
# Why: Needed for Django settings and for locating item-mapping.json.
# How: Parent of the scripts/ directory.
PROJECT_ROOT = SCRIPT_DIR.parent

# What: Add the project root to sys.path so Django app modules are importable.
# Why: This script runs outside manage.py, so Python needs explicit module paths.
# How: Insert at position 0 for highest import priority.
sys.path.insert(0, str(PROJECT_ROOT))

# What: Point Django at the settings module so the ORM can initialize.
# Why: Without DJANGO_SETTINGS_MODULE, django.setup() cannot load settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django  # noqa: E402
django.setup()

# Now we can safely import Django models and utilities
from django.db import transaction  # noqa: E402
from Website.models import HourlyItemVolume  # noqa: E402

# =============================================================================
# CONFIGURATION
# =============================================================================

# BASE_URL: The OSRS Wiki timeseries API endpoint.
# What: URL used to fetch per-item timeseries data at various timesteps.
# Why: Each item requires its own request to /timeseries with an item ID parameter.
# How: Combined with query params ?timestep=1h&id={item_id} for each request.
BASE_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries"

# HEADERS: Required User-Agent header for the RuneScape Wiki API.
# What: Identifies this application to the API.
# Why: The Wiki API requires a descriptive User-Agent string for access.
# How: Passed to every aiohttp request via the session constructor.
HEADERS = {"User-Agent": "GE-Tools (not yet live) - demondsoftware@gmail.com"}

# ITEM_MAPPING_FILE: Path to item-mapping.json (maps item IDs to names).
# What: Absolute path to the local JSON file containing all OSRS item metadata.
# Why: We need item names for denormalized storage in HourlyItemVolume.
# How: Located at Website/static/item-mapping.json relative to PROJECT_ROOT.
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'

# MAX_CONCURRENCY: Maximum number of simultaneous HTTP requests.
# What: Controls how many API requests are in flight at once.
# Why: Limits load on the Wiki API to avoid rate limiting or bans.
#      50 is aggressive but acceptable for a one-time backfill script.
# How: Used as the value for asyncio.Semaphore in the fetch loop.
MAX_CONCURRENCY = 50

# CHUNK_SIZE: Number of items per batch for progress reporting.
# What: Items are fetched in logical batches of this size for progress logging.
# Why: Fetching ~3500 items takes a while; batched logging shows progress.
# How: The item ID list is split into chunks, and each chunk's tasks are gathered.
CHUNK_SIZE = 500

# BULK_INSERT_BATCH_SIZE: Number of rows per Django bulk_create call.
# What: Controls how many model instances are inserted in a single SQL statement.
# Why: SQLite has a limit of ~999 variables per query. With 4 fields per row,
#      500 rows = 2000 variables, which Django handles by splitting internally.
#      500 is a safe, performant batch size for all database backends.
BULK_INSERT_BATCH_SIZE = 500


# =============================================================================
# ITEM MAPPING
# =============================================================================

def load_item_mapping():
    """
    Load the item mapping from item-mapping.json.

    What: Reads the JSON list of item objects (each with 'id' and 'name' keys).
    Why: We need item names for denormalized storage in HourlyItemVolume rows.
    How: Opens the JSON file and parses it into a Python list of dicts.

    Returns:
        list: List of item dicts [{'id': int, 'name': str, ...}, ...], or None on failure.
    """
    try:
        with open(ITEM_MAPPING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Item mapping file not found: {ITEM_MAPPING_FILE}")
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse item mapping JSON: {e}")
        return None


def build_id_to_name(items):
    """
    Build an item_id -> item_name lookup dictionary from the item mapping list.

    What: Converts a list of item dicts into a dict keyed by numeric item ID.
    Why: Provides O(1) name lookups when building database rows for ~3500 items.
    How: Iterates the mapping list and stores each {id: name} pair.

    Args:
        items: List of item dicts from item-mapping.json.

    Returns:
        dict: {item_id (int): item_name (str)} lookup dictionary.
    """
    # lookup: Dictionary mapping integer item IDs to their human-readable names.
    lookup = {}
    for item in items:
        # item_id: Numeric OSRS item ID (e.g., 4151 for Abyssal whip).
        item_id = item.get("id")
        if item_id is None:
            continue
        # item_name: Human-readable name, defaults to empty string if missing.
        item_name = item.get("name") or ""
        lookup[item_id] = item_name
    return lookup


# =============================================================================
# ASYNC API FETCHING
# =============================================================================

def chunked(seq, size):
    """
    Yield successive chunks from a list.

    What: Splits a list into fixed-size batches.
    Why: Used for progress reporting — we log after each chunk completes.
    How: Iterates with a step size and yields slices.

    Args:
        seq: The list to split into chunks.
        size: Maximum size of each chunk.

    Yields:
        list: A slice of at most `size` items.
    """
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


async def fetch_one(session, sem, item_id, timestep):
    """
    Fetch timeseries data for a single item from the OSRS Wiki API.

    What: Makes one async HTTP GET request for a single item's timeseries.
    Why: The timeseries endpoint requires one request per item — no batch endpoint.
    How: Acquires the semaphore to limit concurrency, then sends the request.

    Args:
        session: The shared aiohttp.ClientSession for connection pooling.
        sem: asyncio.Semaphore controlling max concurrent requests.
        item_id: The OSRS item ID to fetch data for.
        timestep: The timeseries resolution (e.g., "1h").

    Returns:
        dict: {"id": item_id, "data": [...]} where data is the API's timeseries array.
    """
    # params: Query parameters for the timeseries API endpoint.
    params = {"timestep": timestep, "id": item_id}
    async with sem:
        async with session.get(BASE_URL, params=params) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return {"id": item_id, "data": payload.get("data", [])}


async def fetch_all_items(item_ids, timestep="1h"):
    """
    Fetch timeseries data for all items using async HTTP with concurrency control.

    What: Orchestrates fetching timeseries data for every item in the mapping.
    Why: ~3500 items need individual API calls; async + semaphore keeps it fast
         (~30-60 seconds) while respecting API rate limits.
    How: Creates an aiohttp session, splits items into chunks for progress logging,
         and gathers tasks per chunk. Failed requests are counted but don't crash.

    Args:
        item_ids: List of integer item IDs to fetch.
        timestep: Timeseries resolution — "1h" for hourly data.

    Returns:
        list: List of dicts [{"id": int, "data": [...]}, ...] for successful fetches.
    """
    # sem: Semaphore that limits concurrent HTTP requests to MAX_CONCURRENCY.
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    # timeout: Per-request timeout to prevent hanging on unresponsive servers.
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        # results: Accumulates successful API responses.
        results = []
        # total: Total number of items to fetch (for progress logging).
        total = len(item_ids)
        # fetched_ok: Count of items that returned valid data.
        fetched_ok = 0
        # fetched_fail: Count of items that failed (network error, HTTP error, etc.).
        fetched_fail = 0

        for batch_index, batch in enumerate(chunked(item_ids, CHUNK_SIZE), start=1):
            # tasks: List of coroutines for this chunk's API requests.
            tasks = [fetch_one(session, sem, item_id, timestep) for item_id in batch]
            # batch_results: Results from asyncio.gather; may contain Exception objects
            #                for failed requests (return_exceptions=True prevents crash).
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in batch_results:
                if isinstance(r, Exception):
                    fetched_fail += 1
                    continue
                results.append(r)
                fetched_ok += 1

            # done: Total items processed so far (success + failure).
            done = fetched_ok + fetched_fail
            print(
                f"[batch {batch_index}] fetched {done}/{total} "
                f"(ok={fetched_ok}, fail={fetched_fail})"
            )

        return results


# =============================================================================
# DATA TRANSFORMATION
# =============================================================================

def build_volume_objects(api_results, lookup):
    """
    Convert raw API results into HourlyItemVolume model instances.

    What: Transforms the list of per-item API responses into Django model objects
          ready for bulk_create.
    Why: Separates data transformation from insertion logic for testability and clarity.
    How: For each item's timeseries, iterates every data point and computes GP volume.

    Volume Formula:
        volume_gp = (avgHighPrice * highPriceVolume) + (avgLowPrice * lowPriceVolume)
        - Null prices default to 0 so partial data is captured (items with trades
          on only one side still contribute their actual traded GP).
        - This matches fetch_hourly_volume.py's formula for consistency.

    Args:
        api_results: List of dicts [{"id": int, "data": [...]}, ...] from fetch_all_items.
        lookup: Dict mapping item_id -> item_name for denormalized storage.

    Returns:
        list: List of HourlyItemVolume model instances.
    """
    # all_objects: Accumulates HourlyItemVolume instances across all items.
    all_objects = []

    for result in api_results:
        # item_id: The OSRS item ID from the API response.
        item_id = result["id"]
        # item_name: Human-readable name from the lookup, or empty string if unmapped.
        item_name = lookup.get(item_id, "")

        for data_point in result.get("data", []):
            # ts: The API-provided Unix epoch timestamp for this data point.
            # Stored as-is (integer) in the CharField field — consistent with
            # fetch_hourly_volume.py which stores str(snapshot_timestamp).
            ts = data_point["timestamp"]

            # avg_high: Average instant-buy price during this hour, or 0 if no buys occurred.
            # Why default to 0: If avgHighPrice is None, there were no buy trades. The
            # contribution to volume_gp is 0 * highPriceVolume = 0, which is correct.
            avg_high = data_point.get("avgHighPrice") or 0

            # avg_low: Average instant-sell price during this hour, or 0 if no sells occurred.
            # Why default to 0: Same reasoning as avg_high — no sells = 0 GP contribution.
            avg_low = data_point.get("avgLowPrice") or 0

            # high_vol: Number of items instant-bought during this hour, or 0 if None.
            high_vol = data_point.get("highPriceVolume") or 0

            # low_vol: Number of items instant-sold during this hour, or 0 if None.
            low_vol = data_point.get("lowPriceVolume") or 0

            # volume_gp: Total GP traded during this hour for this item.
            # Formula: (buy price * buy volume) + (sell price * sell volume)
            # This correctly weights each trade side by its actual price.
            volume_gp = (avg_high * high_vol) + (avg_low * low_vol)

            all_objects.append(HourlyItemVolume(
                item_id=item_id,
                item_name=item_name,
                volume=volume_gp,
                timestamp=ts,
            ))

    return all_objects


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """
    Main entry point — backfills HourlyItemVolume with full 1h timeseries history.

    What: Loads item mapping, fetches all 1h timeseries data, builds model objects,
          and bulk-inserts them into the database in a single transaction.
    Why: Provides a complete volume history so volume-dependent alerts work immediately
         after a database clear/rebuild.
    How:
        1. Load item mapping and build name lookup.
        2. Async-fetch all items' 1h timeseries (concurrency-limited).
        3. Convert API data into HourlyItemVolume objects with GP volume.
        4. Bulk-insert with ignore_conflicts=True for idempotent re-runs.
        5. Print summary and exit.
    """
    print("=" * 70)
    print("BACKFILL: HourlyItemVolume (1h timeseries)")
    print("=" * 70)

    # --- Step 1: Load item mapping ---
    # mapping: Full list of item dicts from item-mapping.json.
    mapping = load_item_mapping()
    if not mapping:
        print("FATAL: Could not load item mapping. Aborting.")
        return

    # lookup: Dictionary mapping item_id (int) -> item_name (str).
    lookup = build_id_to_name(mapping)
    print(f"Loaded {len(lookup)} items from item-mapping.json")

    # ids: List of all integer item IDs to fetch timeseries data for.
    ids = [item["id"] for item in mapping]

    # --- Step 2: Fetch all 1h timeseries data ---
    print(f"\nFetching 1h timeseries for {len(ids)} items "
          f"(concurrency={MAX_CONCURRENCY})...")
    # api_results: List of {"id": int, "data": [...]} dicts from the async fetcher.
    api_results = asyncio.run(
        fetch_all_items(ids, timestep="1h")
    )
    print(f"Received data for {len(api_results)} items")

    # --- Step 3: Build model objects ---
    print("\nBuilding HourlyItemVolume objects...")
    # all_objects: List of HourlyItemVolume instances ready for bulk_create.
    all_objects = build_volume_objects(api_results, lookup)
    print(f"Prepared {len(all_objects)} rows for insertion")

    if not all_objects:
        print("WARNING: No data to insert. Check API responses.")
        return

    # --- Step 4: Bulk insert ---
    # Why ignore_conflicts=True: The model has unique_together = ['item_id', 'timestamp'].
    # If this script is re-run (e.g. after a partial failure), existing rows are silently
    # skipped instead of raising IntegrityError. This makes the script idempotent.
    print(f"\nInserting into database (batch_size={BULK_INSERT_BATCH_SIZE}, "
          f"ignore_conflicts=True)...")
    with transaction.atomic():
        HourlyItemVolume.objects.bulk_create(
            all_objects,
            batch_size=BULK_INSERT_BATCH_SIZE,
            ignore_conflicts=True,
        )

    # --- Step 5: Summary ---
    # final_count: Actual number of rows in the table after insertion.
    # Why query the DB: ignore_conflicts=True means some rows may have been skipped,
    # so len(all_objects) doesn't reflect actual inserts.
    final_count = HourlyItemVolume.objects.count()
    print(f"\nDone! HourlyItemVolume now contains {final_count} rows.")
    print("=" * 70)


if __name__ == "__main__":
    main()
