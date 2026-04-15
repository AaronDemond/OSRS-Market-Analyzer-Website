#!/usr/bin/env python
r"""
=============================================================================
TRENDING ITEMS UPDATE SCRIPT
=============================================================================
What:
    - Fetches the OSRS Wiki 24-hour snapshot endpoint once for all items.
    - Stores raw snapshot rows in ItemPriceSnapshot.
    - Calculates top movers and writes Website/static/data/trending_items.json.
Why:
    - Keeps trending generation fast like the other snapshot ingestors.
    - Avoids one external request per item.
How:
    - Load the item mapping from item-mapping.json.
    - Fetch the /24h snapshot in a single API call.
    - Bulk-insert ItemPriceSnapshot rows for the current snapshot timestamp.
    - Compare current prices against previously stored snapshots to rank movers.

Usage:
    python scripts/update_trending.py
=============================================================================
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

import requests

# =============================================================================
# DJANGO SETUP - Required to use Django ORM from standalone script
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402
from Website.models import ItemPriceSnapshot  # noqa: E402

# =============================================================================
# CONFIGURATION
# =============================================================================

API_BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'
API_HEADERS = {'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
REQUEST_TIMEOUT_SECONDS = 10
VOLUME_THRESHOLD = 75_000_000
TOP_N = 10
BULK_INSERT_BATCH_SIZE = 500
COMPARISON_WINDOW_HOURS = 48
PREFERRED_COMPARISON_MIN_HOURS = 20
PREFERRED_COMPARISON_MAX_HOURS = 30
OUTPUT_FILE = PROJECT_ROOT / 'Website' / 'static' / 'data' / 'trending_items.json'
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'


def log(message):
    """Print a timestamped log line."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}")


def load_item_mapping():
    """Load the local item mapping JSON."""
    try:
        with open(ITEM_MAPPING_FILE, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        log(f"ERROR: Item mapping file not found: {ITEM_MAPPING_FILE}")
        return None
    except json.JSONDecodeError as exc:
        log(f"ERROR: Failed to parse item mapping JSON: {exc}")
        return None


def build_item_lookup(items):
    """Build an item_id -> metadata lookup from item-mapping.json."""
    lookup = {}
    for item in items:
        item_id = item.get('id')
        if item_id is None:
            continue

        lookup[item_id] = {
            'name': item.get('name') or '',
            'icon': item.get('icon') or '',
        }

    return lookup


def normalize_snapshot_timestamp(raw_timestamp):
    """
    Normalize the API snapshot timestamp into an aware UTC datetime.

    The Wiki snapshot endpoints provide Unix timestamps. This helper also
    tolerates millisecond timestamps and ISO strings to keep the script robust.
    """
    if raw_timestamp is None:
        return datetime.now(dt_timezone.utc)

    if isinstance(raw_timestamp, str):
        raw_timestamp = raw_timestamp.strip()
        try:
            raw_timestamp = int(raw_timestamp)
        except ValueError:
            return datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))

    if isinstance(raw_timestamp, (int, float)):
        if raw_timestamp > 10_000_000_000:
            raw_timestamp = raw_timestamp / 1000
        return datetime.fromtimestamp(raw_timestamp, tz=dt_timezone.utc)

    raise ValueError(f"Unsupported snapshot timestamp: {raw_timestamp!r}")


def fetch_24h_snapshot():
    """Fetch the latest 24-hour snapshot for all items in one API call."""
    try:
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

    payload = response.json()
    if not isinstance(payload, dict):
        log("ERROR: 24h API payload is not a JSON object.")
        return None

    if 'data' not in payload or 'timestamp' not in payload:
        log("ERROR: 24h API payload missing required keys (data/timestamp).")
        return None

    return payload


def snapshot_already_ingested(snapshot_timestamp):
    """Return True when the snapshot timestamp is already present in the DB."""
    return ItemPriceSnapshot.objects.filter(timestamp=snapshot_timestamp).exists()


def chunk_list(items, batch_size):
    """Yield successive chunks from a list."""
    for start_index in range(0, len(items), batch_size):
        yield items[start_index:start_index + batch_size]


def build_snapshot_rows(snapshot_data, lookup, snapshot_timestamp):
    """
    Convert snapshot payload data into ItemPriceSnapshot rows and a current map.

    The returned current-data map is used for trending calculations without
    re-reading the freshly fetched payload.
    """
    rows = []
    current_data = {}

    for item_id_raw, item_payload in snapshot_data.items():
        try:
            item_id = int(item_id_raw)
        except (TypeError, ValueError):
            log(f"WARNING: Invalid item_id '{item_id_raw}', skipping.")
            continue

        if not isinstance(item_payload, dict) or not item_payload:
            continue

        metadata = lookup.get(item_id, {})
        item_name = metadata.get('name', '')
        item_icon = metadata.get('icon', '')

        avg_high_price = item_payload.get('avgHighPrice')
        avg_low_price = item_payload.get('avgLowPrice')
        high_price_volume = item_payload.get('highPriceVolume') or 0
        low_price_volume = item_payload.get('lowPriceVolume') or 0

        rows.append(ItemPriceSnapshot(
            item_id=item_id,
            item_name=item_name,
            timestamp=snapshot_timestamp,
            avg_high_price=avg_high_price,
            avg_low_price=avg_low_price,
            high_price_volume=high_price_volume,
            low_price_volume=low_price_volume,
        ))

        current_data[item_id] = {
            'id': item_id,
            'name': item_name,
            'icon': item_icon,
            'avg_high_price': avg_high_price,
            'avg_low_price': avg_low_price,
            'high_price_volume': high_price_volume,
            'low_price_volume': low_price_volume,
        }

    return rows, current_data


def save_to_database(rows):
    """Bulk-insert raw snapshot rows using the same pattern as the fast ingestors."""
    attempted_count = 0
    with transaction.atomic():
        for batch in chunk_list(rows, BULK_INSERT_BATCH_SIZE):
            ItemPriceSnapshot.objects.bulk_create(
                batch,
                batch_size=BULK_INSERT_BATCH_SIZE,
                ignore_conflicts=True,
            )
            attempted_count += len(batch)

    log(f"Attempted insert of {attempted_count} ItemPriceSnapshot rows.")
    return attempted_count


def load_comparison_snapshots(item_ids, snapshot_timestamp):
    """
    Load one comparison snapshot per item from recent local history.

    Prefer snapshots roughly 24 hours older than the current one so the trend
    still behaves like a daily-movement view. If that window is missing for an
    item, fall back to the latest older snapshot within the recent history
    window.
    """
    if not item_ids:
        return {}

    window_start = snapshot_timestamp - timedelta(hours=COMPARISON_WINDOW_HOURS)
    preferred_start = snapshot_timestamp - timedelta(hours=PREFERRED_COMPARISON_MAX_HOURS)
    preferred_end = snapshot_timestamp - timedelta(hours=PREFERRED_COMPARISON_MIN_HOURS)

    recent_rows = ItemPriceSnapshot.objects.filter(
        item_id__in=item_ids,
        timestamp__lt=snapshot_timestamp,
        timestamp__gte=window_start,
    ).order_by('item_id', '-timestamp').values(
        'item_id',
        'timestamp',
        'avg_high_price',
        'avg_low_price',
    )

    latest_prior = {}
    preferred_prior = {}

    for row in recent_rows:
        item_id = row['item_id']
        row_timestamp = row['timestamp']

        if item_id not in latest_prior:
            latest_prior[item_id] = row

        if preferred_start <= row_timestamp <= preferred_end and item_id not in preferred_prior:
            preferred_prior[item_id] = row

    comparison_rows = {}
    for item_id in item_ids:
        chosen_row = preferred_prior.get(item_id) or latest_prior.get(item_id)
        if chosen_row is not None:
            comparison_rows[item_id] = chosen_row

    log(f"Loaded comparison snapshots for {len(comparison_rows)}/{len(item_ids)} items.")
    return comparison_rows


def build_trending_candidates(current_data, comparison_rows):
    """Build trending candidates from current snapshot data and local history."""
    candidates = []

    for item_id, item in current_data.items():
        previous = comparison_rows.get(item_id)
        if previous is None:
            continue

        current_high = item['avg_high_price']
        current_low = item['avg_low_price']
        previous_high = previous['avg_high_price']
        previous_low = previous['avg_low_price']

        if any(value is None for value in (current_high, current_low, previous_high, previous_low)):
            continue

        current_price = (current_high + current_low) // 2
        previous_price = (previous_high + previous_low) // 2
        if previous_price <= 0:
            continue

        daily_volume = item['high_price_volume'] + item['low_price_volume']
        hourly_volume_gp = (daily_volume / 24) * current_price
        if hourly_volume_gp < VOLUME_THRESHOLD:
            continue

        change_percent = ((current_price - previous_price) / previous_price) * 100
        candidates.append({
            'id': item_id,
            'name': item['name'],
            'icon': item['icon'],
            'change': round(change_percent, 2),
            'price': current_price,
            'volume': int(hourly_volume_gp),
        })

    log(f"Prepared {len(candidates)} trending candidates after history and volume filtering.")
    return candidates


def calculate_trending(price_changes):
    """Sort candidates into top gainers and losers."""
    gainers = sorted(
        [item for item in price_changes if item['change'] > 0],
        key=lambda item: item['change'],
        reverse=True,
    )[:TOP_N]

    losers = sorted(
        [item for item in price_changes if item['change'] < 0],
        key=lambda item: item['change'],
    )[:TOP_N]

    return {
        'gainers': gainers,
        'losers': losers,
        'last_updated': datetime.now(dt_timezone.utc).isoformat(),
    }


def save_trending(data):
    """Write trending data atomically to the static JSON file."""
    try:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = OUTPUT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
        temp_file.replace(OUTPUT_FILE)
        log(f"Saved trending data to {OUTPUT_FILE}")
        return True
    except Exception as exc:
        log(f"ERROR: Failed to save trending data: {exc}")
        return False


def main():
    """Orchestrate the full trending update flow."""
    start_time = time.time()
    log("=" * 60)
    log("Starting trending items update...")
    log("=" * 60)

    item_mapping = load_item_mapping()
    if not item_mapping:
        log("FATAL: Cannot proceed without item mapping")
        sys.exit(1)

    item_lookup = build_item_lookup(item_mapping)
    log(f"Found {len(item_lookup)} items in mapping")

    snapshot = fetch_24h_snapshot()
    if snapshot is None:
        log("FATAL: Could not fetch 24h snapshot")
        sys.exit(1)

    try:
        snapshot_timestamp = normalize_snapshot_timestamp(snapshot.get('timestamp'))
    except (TypeError, ValueError) as exc:
        log(f"FATAL: Invalid 24h snapshot timestamp: {exc}")
        sys.exit(1)

    rows, current_data = build_snapshot_rows(
        snapshot_data=snapshot.get('data') or {},
        lookup=item_lookup,
        snapshot_timestamp=snapshot_timestamp,
    )

    if not rows:
        log("FATAL: Snapshot contained no insertable item data")
        sys.exit(1)

    if snapshot_already_ingested(snapshot_timestamp):
        log(f"INFO: Snapshot timestamp {snapshot_timestamp.isoformat()} already exists; skipping DB insert.")
    else:
        save_to_database(rows)

    comparison_rows = load_comparison_snapshots(
        item_ids=list(current_data.keys()),
        snapshot_timestamp=snapshot_timestamp,
    )
    trending_candidates = build_trending_candidates(current_data, comparison_rows)

    if not trending_candidates:
        log("WARNING: No items passed the history/volume filters - saving empty trending result")

    trending = calculate_trending(trending_candidates)
    log(f"Top gainers: {[item['name'] for item in trending['gainers']]}")
    log(f"Top losers: {[item['name'] for item in trending['losers']]}")

    if not save_trending(trending):
        log("Update failed - see errors above")
        sys.exit(1)

    elapsed = time.time() - start_time
    log(f"Update completed successfully in {elapsed:.1f} seconds")


if __name__ == '__main__':
    main()
