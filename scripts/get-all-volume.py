import asyncio
from typing import Iterable, Dict, Any, List
import aiohttp
import json

from pathlib import Path
import os
import sys
import json
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path



BASE_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries"
HEADERS = {"User-Agent": "GE-Tools (not yet live) - demondsoftware@gmail.com"}
SCRIPT_DIR = Path(__file__).resolve().parent

# PROJECT_ROOT: Root of the OSRSWebsite project (one level up from scripts/)
PROJECT_ROOT = SCRIPT_DIR.parent


ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'

# Add project root to Python path so we can import the Website module
sys.path.insert(0, str(PROJECT_ROOT))

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django
django.setup()

# Now we can safely import Django models
from Website.models import HourlyItemVolume, FiveMinTimeSeries

# =============================================================================
# CONFIGURATION
# =============================================================================

# MAX_WORKERS: Number of parallel API requests to make at once.
# 15 workers for aggressive parallel fetching — acceptable for a one-time backfill.
# Higher than update_volumes.py's 6 workers since this only runs once.

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
BULK_INSERT_BATCH_SIZE = 100


MAX_WORKERS = 50
CHUNK_SIZE = 500  # number of ids per batch (tune this)

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


def chunked(seq: List[int], size: int) -> Iterable[List[int]]:
    for i in range(0, len(seq), size):
        yield seq[i:i+size]

async def fetch_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    item_id: int,
    timestep: str,
) -> Dict[str, Any]:
    params = {"timestep": timestep, "id": item_id}
    async with sem:
        async with session.get(BASE_URL, params=params) as resp:
            resp.raise_for_status()
            payload = await resp.json()
            return {"id": item_id, "data": payload.get("data", [])}

async def fetch_many(item_ids: List[int], timestep: str = "1h", concurrency: int = MAX_WORKERS):
    sem = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        results: List[Dict[str, Any]] = []

        total = len(item_ids)
        fetched_ok = 0
        fetched_fail = 0

        for batch_index, batch in enumerate(chunked(item_ids, CHUNK_SIZE), start=1):
            tasks = [fetch_one(session, sem, item_id, timestep) for item_id in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in batch_results:
                if isinstance(r, Exception):
                    fetched_fail += 1
                    continue
                results.append(r)
                fetched_ok += 1

            done = fetched_ok + fetched_fail
            print(
                f"[batch {batch_index}] fetched {done}/{total} "
                f"(ok={fetched_ok}, fail={fetched_fail})"
            )

        return results

def get_all_volume(ids: List[int], timestep: str = "1h") -> List[Dict[str, Any]]:
    return asyncio.run(fetch_many(ids, timestep=timestep, concurrency=MAX_WORKERS))

def get_all_volume_5m(ids: List[int], timestep: str = "5m") -> List[Dict[str, Any]]:
    return asyncio.run(fetch_many(ids, timestep=timestep, concurrency=MAX_WORKERS))


def getNameAndIds():
    mapping = load_item_mapping()
    nameAndIds = [(x['id'], x['name']) for x in mapping]
    return nameAndIds

def getData():
    mapping = load_item_mapping()
    ids = [x['id'] for x in mapping]
    result = get_all_volume(ids)
    for r in result:
        make_volume_objects([r])

def getAllTimeSeries():
    mapping = load_item_mapping()
    ids = [x['id'] for x in mapping]
    result = get_all_volume(ids)
    for r in result:
        make_timeseries_objects([r])
    #with open("output.txt", "w", encoding="utf-8") as f:
        #print(result, file=f)


# Pass in an item mapping list (from load_item_mapping) to build the lookup.
def build_id_to_name(items):
    lookup = {}
    for item in items:
        item_id = item.get("id")
        if item_id is None:
            continue

        name = item.get("name")
        if name is None:
            # optional fallback if "name" is missing
            name = ""
        lookup[item_id] = name

    return lookup

# Given an item ID and the lookup dict, return the name or None if not found.
def name_from_id(item_id, lookup):
    return lookup.get(item_id)  # returns None if not found

from datetime import datetime, timezone
def makeObjects(results):
    id = results[0]['id']
    data = results[0]['data']
    volumeObjects = []
    for x in data:
        timestamp = datetime.fromtimestamp(x['timestamp'], tz=timezone.utc)
        avgHighPrice = x['avgHighPrice'] if x['avgHighPrice'] is not None else 0
        avgLowPrice = x['avgLowPrice'] if x['avgLowPrice'] is not None else 0
        highPriceVolume = x['highPriceVolume'] if x['highPriceVolume'] is not None else 0
        lowPriceVolume = x['lowPriceVolume'] if x['lowPriceVolume'] is not None else 0

        avgPrice = (avgHighPrice + avgLowPrice) / 2
        volumeGP = (avgHighPrice * highPriceVolume) + (avgLowPrice * lowPriceVolume)
        itemName = name_from_id(id, lookup)
        volumeObject = HourlyItemVolume(
                item_id=id,
                item_name=itemName,
                volume=volumeGP,
                timestamp=timestamp)
        volumeObjects.append(volumeObject)
    HourlyItemVolume.objects.bulk_create(volumeObjects, batch_size=500)



from django.db import transaction
from datetime import datetime, timezone

BULK_INSERT_BATCH_SIZE = 500


def make_5m_timeseries_objects(result_item, lookup):
    item_id = result_item["id"]
    item_name = name_from_id(item_id, lookup) or ""
    objs = []

    for x in result_item.get("data", []):
        ts = x["timestamp"]
        avg_high = x["avgHighPrice"]
        avg_low = x["avgLowPrice"]
        high_vol = x["highPriceVolume"] or 0
        low_vol = x["lowPriceVolume"] or 0


        objs.append(FiveMinTimeSeries(
            item_id=item_id,
            item_name=item_name,
            avg_low_price=avg_low,
            avg_high_price=avg_high,
            high_price_volume=high_vol,
            low_price_volume=low_vol,
            timestamp=ts
        ))
    return objs

def make_volume_objects(result_item, lookup):
    item_id = result_item["id"]
    item_name = name_from_id(item_id, lookup) or ""
    objs = []

    for x in result_item.get("data", []):
        ts = x["timestamp"]

        avg_high = x["avgHighPrice"] or 0
        avg_low = x["avgLowPrice"] or 0
        high_vol = x["highPriceVolume"] or 0
        low_vol = x["lowPriceVolume"] or 0

        volume_gp = (avg_high * high_vol) + (avg_low * low_vol)

        objs.append(HourlyItemVolume(
            item_id=item_id,
            item_name=item_name,
            volume=volume_gp,
            timestamp=ts
        ))
    return objs

def getData2():
    mapping = load_item_mapping()
    ids = [x["id"] for x in mapping]

    result = get_all_volume(ids)

    all_objects = []
    for r in result:
        all_objects.extend(make_volume_objects(r, lookup))

    print(f"prepared {len(all_objects)} rows, inserting...")

    with transaction.atomic():
        HourlyItemVolume.objects.bulk_create(
            all_objects,
            batch_size=BULK_INSERT_BATCH_SIZE,
            # ignore_conflicts=True,  # optional if you want to skip duplicates
        )

    print("done")

def getDataTimeSeries():
    mapping = load_item_mapping()
    ids = [x["id"] for x in mapping]

    result = get_all_volume(ids)

    all_objects = []
    for r in result:
        all_objects.extend(make_5m_timeseries_objects(r, lookup))

    print(f"prepared {len(all_objects)} rows, inserting...")

    with transaction.atomic():
        FiveMinTimeSeries.objects.bulk_create(
            all_objects,
            batch_size=BULK_INSERT_BATCH_SIZE,
            # ignore_conflicts=True,  # optional if you want to skip duplicates
        )

    print("done")







def fetch_latest_volume_snapshot():
    """
    Fetch the most recent hourly volume datapoint for every item and insert it into the database.

    What: For each item in the item mapping, fetches the 1h timeseries from the OSRS Wiki API,
          extracts ONLY the newest (most recent) datapoint, calculates GP volume, and inserts
          a single HourlyItemVolume row per item into the database.

    Why: Provides a quick way to get a fresh volume snapshot for all items without storing
         the full history. Useful for on-demand refreshes — e.g., before running spread alert
         checks that filter by volume, or after the DB has gone stale.

    How:
        1. Loads all item IDs from the item mapping file.
        2. Uses the existing async fetch_many() to request timeseries data for every item
           with 25 concurrent workers.
        3. For each item's response, takes ONLY the LAST entry in the 'data' array
           (the API returns data sorted chronologically, so the last entry is the newest).
        4. Calculates GP volume as: (avgHighPrice * highPriceVolume) + (avgLowPrice * lowPriceVolume).
        5. Creates an HourlyItemVolume object and collects them all into a list.
        6. Prints the item name and timestamp to the terminal for every new database entry.
        7. Bulk-inserts all objects in a single atomic transaction for performance.

    Returns:
        int: The number of HourlyItemVolume records inserted into the database.
    """
    # mapping: Full list of item dicts from item-mapping.json, each with 'id' and 'name' keys.
    mapping = load_item_mapping()
    if not mapping:
        print("ERROR: Could not load item mapping. Aborting.")
        return 0

    # ids: List of all item IDs to fetch timeseries data for.
    ids = [x['id'] for x in mapping]
    print(f"Fetching latest volume for {len(ids)} items...")

    # raw_results: List of dicts [{'id': int, 'data': [...]}, ...] from the async API fetcher.
    # Each entry contains the full timeseries response for one item.
    raw_results = get_all_volume(ids)
    print(f"Received responses for {len(raw_results)} items. Extracting latest datapoints...")

    # new_records: List of HourlyItemVolume model instances to bulk-insert.
    # Only the single most recent datapoint per item is included.
    new_records = []

    for result in raw_results:
        # item_id: The OSRS item ID from the API response.
        item_id = result['id']

        # data_points: The chronologically-sorted list of hourly snapshots from the API.
        # The last element is the most recent hour's data.
        data_points = result.get('data', [])
        if not data_points:
            continue

        # latest: The newest datapoint dict — last element in the chronological array.
        # Contains keys: timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume.
        latest = data_points[-1]

        # timestamp: UTC datetime of the most recent hourly snapshot.
        timestamp = latest['timestamp']

        # avg_high / avg_low: Average prices for the hour, defaulting to 0 if None
        # (None means no trades occurred at that price point during the hour).
        avg_high = latest['avgHighPrice'] or 0
        avg_low = latest['avgLowPrice'] or 0

        # high_vol / low_vol: Number of units traded at high/low price, defaulting to 0 if None.
        high_vol = latest['highPriceVolume'] or 0
        low_vol = latest['lowPriceVolume'] or 0

        # volume_gp: Total GP traded in the most recent hour.
        # Calculated as (units sold at high price * high price) + (units sold at low price * low price).
        volume_gp = (avg_high * high_vol) + (avg_low * low_vol)

        # item_name: Human-readable item name from the lookup dict, or empty string if not found.
        item_name = name_from_id(item_id, lookup) or ""

        # Print each new entry to the terminal so the user can monitor progress.
        print(f"  + {item_name} (id={item_id}) | timestamp={timestamp} | volume={volume_gp:,} GP")

        new_records.append(HourlyItemVolume(
            item_id=item_id,
            item_name=item_name,
            volume=volume_gp,
            timestamp=timestamp
        ))

    # Bulk-insert all records in a single atomic transaction for performance.
    # batch_size=500 stays within SQLite's variable limit (default max 999 per query).
    if new_records:
        with transaction.atomic():
            HourlyItemVolume.objects.bulk_create(new_records, batch_size=BULK_INSERT_BATCH_SIZE)
        print(f"\nInserted {len(new_records)} records into HourlyItemVolume.")
    else:
        print("\nNo records to insert.")

    return len(new_records)

def fetch_latest_five_min_snapshot():
    """
    Fetch the most recent hourly volume datapoint for every item and insert it into the database.

    What: For each item in the item mapping, fetches the 1h timeseries from the OSRS Wiki API,
          extracts ONLY the newest (most recent) datapoint, calculates GP volume, and inserts
          a single HourlyItemVolume row per item into the database.

    Why: Provides a quick way to get a fresh volume snapshot for all items without storing
         the full history. Useful for on-demand refreshes — e.g., before running spread alert
         checks that filter by volume, or after the DB has gone stale.

    How:
        1. Loads all item IDs from the item mapping file.
        2. Uses the existing async fetch_many() to request timeseries data for every item
           with 25 concurrent workers.
        3. For each item's response, takes ONLY the LAST entry in the 'data' array
           (the API returns data sorted chronologically, so the last entry is the newest).
        4. Calculates GP volume as: (avgHighPrice * highPriceVolume) + (avgLowPrice * lowPriceVolume).
        5. Creates an HourlyItemVolume object and collects them all into a list.
        6. Prints the item name and timestamp to the terminal for every new database entry.
        7. Bulk-inserts all objects in a single atomic transaction for performance.

    Returns:
        int: The number of HourlyItemVolume records inserted into the database.
    """
    # mapping: Full list of item dicts from item-mapping.json, each with 'id' and 'name' keys.
    mapping = load_item_mapping()
    if not mapping:
        print("ERROR: Could not load item mapping. Aborting.")
        return 0

    # ids: List of all item IDs to fetch timeseries data for.
    ids = [x['id'] for x in mapping]
    print(f"Fetching latest volume for {len(ids)} items...")

    # raw_results: List of dicts [{'id': int, 'data': [...]}, ...] from the async API fetcher.
    # Each entry contains the full timeseries response for one item.
    raw_results = get_all_volume(ids)
    print(f"Received responses for {len(raw_results)} items. Extracting latest datapoints...")

    # new_records: List of HourlyItemVolume model instances to bulk-insert.
    # Only the single most recent datapoint per item is included.
    new_records = []

    for result in raw_results:
        # item_id: The OSRS item ID from the API response.
        item_id = result['id']

        # data_points: The chronologically-sorted list of hourly snapshots from the API.
        # The last element is the most recent hour's data.
        data_points = result.get('data', [])
        if not data_points:
            continue

        # latest: The newest datapoint dict — last element in the chronological array.
        # Contains keys: timestamp, avgHighPrice, avgLowPrice, highPriceVolume, lowPriceVolume.
        latest = data_points[-1]

        # timestamp: UTC datetime of the most recent hourly snapshot.
        timestamp = latest['timestamp']

        # avg_high / avg_low: Preserve None from the API — the model fields are nullable.
        avg_high = latest['avgHighPrice']
        avg_low = latest['avgLowPrice']

        # high_vol / low_vol: Number of units traded at high/low price, defaulting to 0 if None.
        high_vol = latest['highPriceVolume'] or 0
        low_vol = latest['lowPriceVolume'] or 0

        # item_name: Human-readable item name from the lookup dict, or empty string if not found.
        item_name = name_from_id(item_id, lookup) or ""

        new_records.append(FiveMinTimeSeries(
            item_id=item_id,
            item_name=item_name,
            avg_low_price=avg_low,
            avg_high_price=avg_high,
            high_price_volume=high_vol,
            low_price_volume=low_vol
        ))

    # Bulk-insert all records in a single atomic transaction for performance.
    # batch_size=500 stays within SQLite's variable limit (default max 999 per query).
    if new_records:
        with transaction.atomic():
            FiveMinTimeSeries.objects.bulk_create(new_records, batch_size=BULK_INSERT_BATCH_SIZE)
        print(f"\nInserted {len(new_records)} records into FiveMinTimeSeries.")
    else:
        print("\nNo records to insert.")

    return len(new_records)








lookup = build_id_to_name(load_item_mapping())  
# use this to get all.
#getDataTimeSeries()
import time
hours = 1
minutes = 5
#time.sleep(1000)
while True:
    print("Sleeping for 5 minutes...")
    time.sleep((hours * 60 * 60) + (60 * 5))
    print("Fetching again...")
    fetch_latest_volume_snapshot()
    #fetch_latest_five_min_snapshot()


