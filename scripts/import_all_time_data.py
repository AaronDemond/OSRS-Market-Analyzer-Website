#!/usr/bin/env python
r"""
=============================================================================
ALL-TIME MARKET DATA IMPORT SCRIPT
=============================================================================
What: Imports historical OSRS market prices from all_osrs_market_data.json into
      the AllTimeData table used by Flip Finder's all-time range.

Why: The Flip Finder all-time view needs local historical rows instead of an
     empty schema-only table.

How: Reads the local JSON export, normalizes timestamps into epoch seconds,
     builds AllTimeData objects with volume left as NULL, and bulk-inserts rows
     in duplicate-safe PostgreSQL-friendly chunks.

Usage:
    python scripts\import_all_time_data.py
    python scripts\import_all_time_data.py --dry-run --limit-items 5
=============================================================================
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


# =============================================================================
# DJANGO SETUP - Required to use Django ORM from standalone scripts
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django  # noqa: E402

django.setup()

from django.db import connection, transaction  # noqa: E402
from Website.models import AllTimeData  # noqa: E402


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_IMPORT_FILE = PROJECT_ROOT / 'Website' / 'static' / 'all_osrs_market_data.json'
BULK_INSERT_BATCH_SIZE = 500
DEFAULT_PROGRESS_INTERVAL = 100
MILLISECONDS_THRESHOLD = 10_000_000_000
JSON_READ_CHUNK_SIZE = 1024 * 1024


@dataclass
class ImportStats:
    """Collect counters for one import run."""
    items_seen: int = 0
    points_seen: int = 0
    rows_built: int = 0
    attempted: int = 0
    inserted: int = 0
    duplicates: int = 0
    batches: int = 0
    skipped: Counter = field(default_factory=Counter)

    @property
    def skipped_total(self):
        return sum(self.skipped.values())


def log(message):
    """Print a timestamped progress message."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def parse_args():
    """Parse command-line options for the importer."""
    parser = argparse.ArgumentParser(
        description='Import all_osrs_market_data.json into Website.models.AllTimeData.',
    )
    parser.add_argument(
        '--file',
        default=str(DEFAULT_IMPORT_FILE),
        help='Path to all_osrs_market_data.json. Defaults to Website/static/all_osrs_market_data.json.',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=BULK_INSERT_BATCH_SIZE,
        help=f'Rows per bulk insert batch. Default: {BULK_INSERT_BATCH_SIZE}.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Parse and report progress without writing rows to the database.',
    )
    parser.add_argument(
        '--limit-items',
        type=int,
        default=None,
        help='Only process the first N parent items. Useful for smoke tests.',
    )
    parser.add_argument(
        '--progress-interval',
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help=f'Log parent item progress every N items. Default: {DEFAULT_PROGRESS_INTERVAL}.',
    )
    return parser.parse_args()


def normalize_timestamp(value):
    """Convert ISO text, numeric text, seconds, or milliseconds to epoch seconds."""
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return normalize_numeric_timestamp(value)

    text = str(value).strip()
    if not text:
        return None

    try:
        return normalize_numeric_timestamp(Decimal(text))
    except InvalidOperation:
        pass

    iso_text = text.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def normalize_numeric_timestamp(value):
    """Normalize a numeric timestamp, treating very large values as milliseconds."""
    try:
        timestamp = int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if abs(timestamp) >= MILLISECONDS_THRESHOLD:
        timestamp = timestamp // 1000
    return timestamp


def normalize_integer(value):
    """Return an integer value, or None for blank/non-numeric data."""
    if value is None or isinstance(value, bool):
        return None

    text = str(value).strip().replace(',', '')
    if not text:
        return None

    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def normalize_name(value):
    """Return a displayable item name, or None for missing/blank names."""
    if value is None:
        return None
    item_name = str(value).strip()
    return item_name or None


def read_export_source(file_path):
    """Read the optional source field from the export header without loading the full file."""
    decoder = json.JSONDecoder()
    with file_path.open('r', encoding='utf-8') as data_file:
        header = data_file.read(64 * 1024)

    key_index = header.find('"source"')
    if key_index == -1:
        return 'unknown'

    colon_index = header.find(':', key_index)
    if colon_index == -1:
        return 'unknown'

    try:
        source, _ = decoder.raw_decode(header[colon_index + 1:].lstrip())
    except json.JSONDecodeError:
        return 'unknown'
    return source if isinstance(source, str) else 'unknown'


def iter_market_items(file_path):
    """Stream parent item objects from the top-level `items` array."""
    decoder = json.JSONDecoder()
    with file_path.open('r', encoding='utf-8') as data_file:
        buffer = read_until_items_array(data_file)

        while True:
            buffer = buffer.lstrip()
            while not buffer:
                chunk = data_file.read(JSON_READ_CHUNK_SIZE)
                if not chunk:
                    raise ValueError('Unexpected end of file while reading items array.')
                buffer += chunk
                buffer = buffer.lstrip()

            if buffer.startswith(']'):
                return

            if buffer.startswith(','):
                buffer = buffer[1:]
                continue

            while True:
                try:
                    item, end_index = decoder.raw_decode(buffer)
                except json.JSONDecodeError as error:
                    chunk = data_file.read(JSON_READ_CHUNK_SIZE)
                    if not chunk:
                        raise ValueError(f'Could not decode item object near: {buffer[:80]!r}') from error
                    buffer += chunk
                    continue

                yield item
                buffer = buffer[end_index:]
                break


def read_until_items_array(data_file):
    """Return the buffer immediately after the top-level `items` array opening bracket."""
    buffer = ''
    while True:
        chunk = data_file.read(JSON_READ_CHUNK_SIZE)
        if not chunk:
            raise ValueError('Expected top-level key "items" containing an array.')

        buffer += chunk
        key_index = buffer.find('"items"')
        if key_index == -1:
            if len(buffer) > JSON_READ_CHUNK_SIZE * 2:
                buffer = buffer[-JSON_READ_CHUNK_SIZE:]
            continue

        bracket_index = buffer.find('[', key_index)
        if bracket_index != -1:
            return buffer[bracket_index + 1:]


def build_all_time_row(parent_item, data_point, stats):
    """Build one AllTimeData object from a parent item and one data point."""
    item_id = normalize_integer(data_point.get('item_id') or parent_item.get('item_id'))
    if item_id is None:
        stats.skipped['bad_item_id'] += 1
        return None

    item_name = normalize_name(data_point.get('name') or parent_item.get('name'))
    if item_name is None:
        stats.skipped['blank_name'] += 1
        return None

    item_price = normalize_integer(data_point.get('price'))
    if item_price is None or item_price <= 0:
        stats.skipped['bad_price'] += 1
        return None

    timestamp = normalize_timestamp(data_point.get('timestamp'))
    if timestamp is None:
        stats.skipped['bad_timestamp'] += 1
        return None

    return AllTimeData(
        item_id=item_id,
        item_name=item_name,
        item_price=item_price,
        volume=None,
        timestamp=timestamp,
    )


def existing_item_timestamp_pairs(objects):
    """Return already-present unique keys for the current batch."""
    if not objects:
        return set()

    item_ids = {obj.item_id for obj in objects}
    timestamps = {obj.timestamp for obj in objects}
    return set(
        AllTimeData.objects.filter(
            item_id__in=item_ids,
            timestamp__in=timestamps,
        ).values_list('item_id', 'timestamp')
    )


def flush_batch(batch, stats, batch_size, dry_run):
    """Write one batch and update progress counters."""
    if not batch:
        return

    stats.batches += 1
    batch_unique_pairs = {(obj.item_id, obj.timestamp) for obj in batch}

    if dry_run:
        inserted_in_batch = len(batch_unique_pairs)
        duplicate_in_batch = len(batch) - inserted_in_batch
        stats.attempted += len(batch)
        stats.inserted += inserted_in_batch
        stats.duplicates += duplicate_in_batch
        log(
            f"DRY RUN batch {stats.batches}: would attempt {stats.attempted} rows, "
            f"unique rows {stats.inserted}, in-file duplicates {stats.duplicates}"
        )
        batch.clear()
        return

    existing_pairs = existing_item_timestamp_pairs(batch)
    inserted_in_batch = len(batch_unique_pairs - existing_pairs)

    with transaction.atomic():
        AllTimeData.objects.bulk_create(
            batch,
            batch_size=batch_size,
            ignore_conflicts=True,
        )

    stats.attempted += len(batch)
    stats.inserted += inserted_in_batch
    stats.duplicates += len(batch) - inserted_in_batch
    log(
        f"Batch {stats.batches}: attempted {stats.attempted}, "
        f"inserted {stats.inserted}, duplicates skipped {stats.duplicates}"
    )
    batch.clear()


def ensure_database_schema_ready():
    """Fail early with a clear message if the user has not applied migration 0059."""
    table_name = AllTimeData._meta.db_table
    with connection.cursor() as cursor:
        table_names = connection.introspection.table_names(cursor)
        if table_name not in table_names:
            raise RuntimeError(f'Database table {table_name!r} does not exist. Run migrations first.')

        columns = {
            getattr(column, 'name', column[0])
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    if 'volume' not in columns:
        raise RuntimeError(
            'AllTimeData.volume column is missing. Apply migration '
            'Website/migrations/0059_alltimedata_volume.py before running a real import.'
        )


def import_all_time_data(file_path, batch_size, dry_run, limit_items=None, progress_interval=DEFAULT_PROGRESS_INTERVAL):
    """Run the import and return populated ImportStats."""
    if batch_size <= 0:
        raise ValueError('batch size must be greater than zero')
    if limit_items is not None and limit_items <= 0:
        raise ValueError('limit-items must be greater than zero when provided')

    start_time = time.monotonic()
    stats = ImportStats()
    batch = []
    selected_description = f'first {limit_items}' if limit_items else 'all available'

    log(f"Source: {read_export_source(file_path)}")
    log(f"Processing {selected_description} parent items")

    for parent_item in iter_market_items(file_path):
        if limit_items is not None and stats.items_seen >= limit_items:
            break

        stats.items_seen += 1
        if not isinstance(parent_item, dict):
            stats.skipped['bad_parent_item'] += 1
            continue

        data_points = parent_item.get('data_points')

        if not isinstance(data_points, list) or not data_points:
            stats.skipped['empty_data_points'] += 1
        else:
            for data_point in data_points:
                if not isinstance(data_point, dict):
                    stats.skipped['bad_data_point'] += 1
                    continue

                stats.points_seen += 1
                row = build_all_time_row(parent_item, data_point, stats)
                if row is None:
                    continue

                stats.rows_built += 1
                batch.append(row)
                if len(batch) >= batch_size:
                    flush_batch(batch, stats, batch_size, dry_run)

        if progress_interval > 0 and stats.items_seen % progress_interval == 0:
            log(
                f"Items processed {stats.items_seen}; "
                f"points seen {stats.points_seen}; rows built {stats.rows_built}; skipped {stats.skipped_total}"
            )

    flush_batch(batch, stats, batch_size, dry_run)
    elapsed = time.monotonic() - start_time
    log_summary(stats, elapsed, dry_run)
    return stats


def log_summary(stats, elapsed, dry_run):
    """Print final import totals."""
    mode = 'DRY RUN complete' if dry_run else 'Import complete'
    log(mode)
    log(f"Elapsed: {elapsed:.1f}s")
    log(f"Items seen: {stats.items_seen}")
    log(f"Data points seen: {stats.points_seen}")
    log(f"Rows built: {stats.rows_built}")
    log(f"Rows attempted: {stats.attempted}")
    log(f"Rows inserted{' (would insert)' if dry_run else ''}: {stats.inserted}")
    log(f"Duplicates skipped{' (in file)' if dry_run else ''}: {stats.duplicates}")
    log(f"Rows skipped: {stats.skipped_total}")
    for reason, count in sorted(stats.skipped.items()):
        log(f"  - {reason}: {count}")


def main():
    """CLI entry point."""
    args = parse_args()
    file_path = Path(args.file).expanduser().resolve()

    if not file_path.exists():
        raise FileNotFoundError(f'Import file does not exist: {file_path}')

    log('All-time market data import starting')
    log(f"File: {file_path}")
    log(f"File size: {file_path.stat().st_size / (1024 * 1024):.1f} MB")
    log(f"Database vendor: {connection.vendor}")
    log(f"Batch size: {args.batch_size}")
    log(f"Dry run: {args.dry_run}")

    if args.dry_run:
        log('Schema write check skipped for dry run.')
    else:
        ensure_database_schema_ready()

    import_all_time_data(
        file_path=file_path,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        limit_items=args.limit_items,
        progress_interval=args.progress_interval,
    )


if __name__ == '__main__':
    main()
