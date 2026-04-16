#!/usr/bin/env python
r"""
=============================================================================
HIGH-SPEED HOURLY VOLUME BACKFILL SCRIPT
=============================================================================
What: Fetches the full 1-hour Wiki timeseries for every OSRS item and stores
      every hourly data point in HourlyItemVolume.

Why: The recurring update_volumes.py script only stores the latest hour. This
     script is the one-time historical backfill so the database has a full
     hourly volume history for older analysis and alert filtering.

How:
    1. Load the local item mapping.
    2. Fetch item history in batches of 500 ids, mirroring the fast get-all
       scripts.
    3. Convert each API entry into a HourlyItemVolume object.
    4. Store the API timestamp as a Unix timestamp string in the database.
    5. Bulk insert in committed chunks with duplicates skipped.

Volume Calculation:
    volume_gp = (highPriceVolume + lowPriceVolume) * ((avgHighPrice + avgLowPrice) // 2)

Timestamp Storage:
    HourlyItemVolume.timestamp is a CharField, so this script stores the Wiki
    API's Unix timestamp as a digit string. That keeps it consistent with the
    newer timeseries scripts and the alert checker's mixed-format parser.

Usage:
    python scripts\backfill_volumes.py
=============================================================================
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import aiohttp

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Website.settings")

import django

django.setup()

from django.db import transaction

from Website.models import HourlyItemVolume


BASE_URL = "https://prices.runescape.wiki/api/v1/osrs/timeseries"
API_HEADERS = {"User-Agent": "GE-Tools (not yet live) - demondsoftware@gmail.com"}
ITEM_MAPPING_FILE = PROJECT_ROOT / "Website" / "static" / "item-mapping.json"

MAX_WORKERS = 50
FETCH_BATCH_SIZE = 500
BULK_INSERT_BATCH_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 30


def log(message: str) -> None:
    """
    Print a timestamped log line.
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def load_item_mapping() -> List[Dict[str, Any]] | None:
    """
    Load the local OSRS item mapping file.
    """
    try:
        with open(ITEM_MAPPING_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        log(f"ERROR: Item mapping file not found: {ITEM_MAPPING_FILE}")
        return None
    except json.JSONDecodeError as exc:
        log(f"ERROR: Failed to parse item mapping JSON: {exc}")
        return None


def build_id_to_name(items: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    """
    Build a fast item-id to item-name lookup.
    """
    lookup: Dict[int, str] = {}
    for item in items:
        item_id = item.get("id")
        if item_id is None:
            continue
        lookup[int(item_id)] = item.get("name") or ""
    return lookup


def chunked(seq: Sequence[Tuple[int, str]], size: int) -> Iterable[Sequence[Tuple[int, str]]]:
    """
    Yield fixed-size slices of the input sequence.
    """
    for index in range(0, len(seq), size):
        yield seq[index:index + size]


async def fetch_one(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    item_id: int,
) -> Dict[str, Any]:
    """
    Fetch one item's 1-hour timeseries payload.
    """
    params = {"timestep": "1h", "id": item_id}
    async with semaphore:
        async with session.get(BASE_URL, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
            return {"id": item_id, "data": payload.get("data", [])}


async def fetch_batch_payloads(
    item_ids: Sequence[int],
    concurrency: int = MAX_WORKERS,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Fetch one 500-item batch using the fast async pattern from the get-all scripts.
    """
    semaphore = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    connector = aiohttp.TCPConnector(limit=concurrency)

    async with aiohttp.ClientSession(
        headers=API_HEADERS,
        timeout=timeout,
        connector=connector,
    ) as session:
        tasks = [fetch_one(session, semaphore, item_id) for item_id in item_ids]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[Dict[str, Any]] = []
    fetched_ok = 0
    fetched_fail = 0

    for result in raw_results:
        if isinstance(result, Exception):
            fetched_fail += 1
            continue
        results.append(result)
        fetched_ok += 1

    return results, fetched_ok, fetched_fail


def build_volume_objects(
    results: Sequence[Dict[str, Any]],
    lookup: Dict[int, str],
) -> List[HourlyItemVolume]:
    """
    Convert raw API results into HourlyItemVolume objects.
    """
    objects: List[HourlyItemVolume] = []

    for result in results:
        item_id = int(result["id"])
        item_name = lookup.get(item_id, "")

        for entry in result.get("data", []):
            avg_high_price = entry.get("avgHighPrice")
            avg_low_price = entry.get("avgLowPrice")

            if avg_high_price is None or avg_low_price is None:
                continue

            high_volume = entry.get("highPriceVolume", 0) or 0
            low_volume = entry.get("lowPriceVolume", 0) or 0
            total_units = high_volume + low_volume
            average_price = (avg_high_price + avg_low_price) // 2
            volume_gp = total_units * average_price

            api_timestamp = entry.get("timestamp")
            if api_timestamp is None:
                continue

            try:
                unix_timestamp = str(int(api_timestamp))
            except (TypeError, ValueError):
                continue

            objects.append(
                HourlyItemVolume(
                    item_id=item_id,
                    item_name=item_name,
                    volume=volume_gp,
                    timestamp=unix_timestamp,
                )
            )

    return objects


def bulk_create_committed_chunks(
    model,
    objects: Sequence[HourlyItemVolume],
    label: str,
) -> tuple[int, int, int]:
    """
    Bulk insert objects in committed chunks so progress is visible and reruns are safe.
    """
    attempted = 0
    inserted = 0
    duplicates_skipped = 0
    total = len(objects)

    for start in range(0, total, BULK_INSERT_BATCH_SIZE):
        batch = list(objects[start:start + BULK_INSERT_BATCH_SIZE])
        batch_unique_pairs = {(obj.item_id, obj.timestamp) for obj in batch}
        item_ids = {obj.item_id for obj in batch}
        timestamps = {obj.timestamp for obj in batch}
        existing_pairs = set(
            model.objects.filter(
                item_id__in=item_ids,
                timestamp__in=timestamps,
            ).values_list("item_id", "timestamp")
        )
        inserted_in_batch = len(batch_unique_pairs - existing_pairs)
        with transaction.atomic():
            model.objects.bulk_create(
                batch,
                batch_size=BULK_INSERT_BATCH_SIZE,
                ignore_conflicts=True,
            )
        attempted += len(batch)
        inserted += inserted_in_batch
        duplicates_skipped += len(batch) - inserted_in_batch
        log(
            f"committed {label} chunk {attempted}/{total}; "
            f"inserted {inserted}; duplicates skipped {duplicates_skipped}"
        )

    return attempted, inserted, duplicates_skipped


def main() -> None:
    """
    Run the full backfill from fetch through insert.
    """
    started_at = time.time()
    log("=" * 70)
    log("HIGH-SPEED HOURLY VOLUME BACKFILL")
    log(f"Fetch workers: {MAX_WORKERS}")
    log(f"Fetch batch size: {FETCH_BATCH_SIZE}")
    log(f"Insert batch size: {BULK_INSERT_BATCH_SIZE}")
    log("=" * 70)

    item_mapping = load_item_mapping()
    if not item_mapping:
        log("FATAL: Cannot proceed without item mapping")
        sys.exit(1)

    lookup = build_id_to_name(item_mapping)
    items_to_fetch = [(int(item["id"]), item.get("name") or "") for item in item_mapping if item.get("id") is not None]
    total_items = len(items_to_fetch)

    log(f"Loaded {total_items} items")

    fetched_ok = 0
    fetched_fail = 0
    prepared_rows = 0
    inserted_rows = 0

    for batch_index, batch in enumerate(chunked(items_to_fetch, FETCH_BATCH_SIZE), start=1):
        batch_ids = [item_id for item_id, _item_name in batch]
        results, batch_ok, batch_fail = asyncio.run(fetch_batch_payloads(batch_ids))

        fetched_ok += batch_ok
        fetched_fail += batch_fail
        done = fetched_ok + fetched_fail
        log(
            f"[batch {batch_index}] fetched {done}/{total_items} "
            f"(ok={fetched_ok}, fail={fetched_fail})"
        )

        batch_objects = build_volume_objects(results, lookup)
        prepared_rows += len(batch_objects)

        if not batch_objects:
            log(f"[batch {batch_index}] no insertable rows in this batch")
            continue

        log(f"[batch {batch_index}] prepared {len(batch_objects)} rows, inserting...")
        attempted_in_batch, inserted_in_batch, skipped_in_batch = bulk_create_committed_chunks(
            HourlyItemVolume,
            batch_objects,
            "HourlyItemVolume",
        )
        inserted_rows += inserted_in_batch

    elapsed = time.time() - started_at
    log("=" * 70)
    log("BACKFILL COMPLETE")
    log(f"Total time: {elapsed:.1f} seconds ({elapsed / 60:.1f} minutes)")
    log(f"Items processed: {total_items}")
    log(f"Fetch successes: {fetched_ok}")
    log(f"Fetch failures: {fetched_fail}")
    log(f"Rows prepared: {prepared_rows}")
    log(f"Rows inserted: {inserted_rows}")
    log("=" * 70)


if __name__ == "__main__":
    main()
