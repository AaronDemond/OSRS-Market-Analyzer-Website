#!/usr/bin/env python
"""
Backfill AllTimeData.volume from item-count volume to GP volume.

What: Updates existing AllTimeData rows in place using `volume * item_price`.
Why: Flip Finder all/custom ranges read volume from AllTimeData, and the page
     expects that value to represent traded GP rather than item count.
How: Walk the table in primary-key batches and update each batch inside its own
     transaction using a database-side expression.

Important:
    This is a one-time conversion script. It assumes the current
    AllTimeData.volume column stores raw item-count volume. Running it again
    after the column already contains GP values will multiply those GP values a
    second time.
"""

import argparse
import math
import os
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import F, Q, Value  # noqa: E402
from django.db.models.functions import Coalesce  # noqa: E402

from Website.models import AllTimeData  # noqa: E402


DEFAULT_BATCH_SIZE = 50_000


def log(message):
    """Print a timestamped progress message."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def format_count(value):
    """Render an integer count with separators for terminal progress output."""
    return f'{int(value):,}'


def format_duration(seconds):
    """Render a short human-readable duration for progress messages."""
    if seconds is None or math.isinf(seconds):
        return 'unknown'
    if seconds < 60:
        return f'{seconds:.1f}s'
    minutes, remaining_seconds = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f'{minutes}m {remaining_seconds:02d}s'
    hours, remaining_minutes = divmod(minutes, 60)
    return f'{hours}h {remaining_minutes:02d}m'


def build_progress_message(processed_rows, total_rows, batch_number, total_batches, started_at):
    """Build a readable batch-completion progress line for the terminal."""
    progress_ratio = processed_rows / total_rows if total_rows else 1.0
    percent_complete = progress_ratio * 100
    elapsed = max(0.001, time.monotonic() - started_at)
    rows_per_second = processed_rows / elapsed
    remaining_rows = max(0, total_rows - processed_rows)
    eta_seconds = remaining_rows / rows_per_second if rows_per_second > 0 else None
    return (
        f'Progress {percent_complete:6.2f}% '
        f'| batch {batch_number}/{total_batches} '
        f'| rows {format_count(processed_rows)}/{format_count(total_rows)} '
        f'| speed {format_count(round(rows_per_second))} rows/s '
        f'| elapsed {format_duration(elapsed)} '
        f'| ETA {format_duration(eta_seconds)}'
    )


def parse_args():
    """Parse command-line options for the backfill."""
    parser = argparse.ArgumentParser(
        description='Convert AllTimeData.volume from item counts to GP volume in place.',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f'Rows per update batch. Default: {DEFAULT_BATCH_SIZE}.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report how many rows would be converted without writing changes.',
    )
    return parser.parse_args()


def iter_batch_ranges(batch_size):
    """Yield inclusive primary-key ranges for sequential batch updates."""
    last_pk = 0
    while True:
        batch_pks = list(
            AllTimeData.objects
            .filter(pk__gt=last_pk)
            .order_by('pk')
            .values_list('pk', flat=True)[:batch_size]
        )
        if not batch_pks:
            return
        first_pk = batch_pks[0]
        last_pk = batch_pks[-1]
        yield first_pk, last_pk, len(batch_pks)


def backfill_all_time_volume(batch_size, dry_run):
    """Convert item-count volume to GP volume across the existing table."""
    if batch_size <= 0:
        raise ValueError('batch-size must be greater than zero')

    total_rows = AllTimeData.objects.order_by().count()
    if total_rows == 0:
        log('No AllTimeData rows found. Nothing to update.')
        return

    log('AllTimeData GP volume backfill starting')
    log(f'Total rows: {total_rows}')
    log(f'Batch size: {batch_size}')
    log(f'Dry run: {dry_run}')

    total_batches = max(1, math.ceil(total_rows / batch_size))
    processed_rows = 0
    converted_rows = 0
    zeroed_rows = 0
    started_at = time.monotonic()

    for batch_number, (first_pk, last_pk, batch_count) in enumerate(iter_batch_ranges(batch_size), start=1):
        batch_rows = AllTimeData.objects.filter(pk__gte=first_pk, pk__lte=last_pk)
        batch_zero_rows = batch_rows.filter(Q(volume__isnull=True) | Q(volume=0)).count()
        batch_convert_rows = batch_count - batch_zero_rows

        if not dry_run:
            with transaction.atomic():
                batch_rows.update(
                    volume=Coalesce(F('volume'), Value(0)) * F('item_price'),
                )

        processed_rows += batch_count
        converted_rows += batch_convert_rows
        zeroed_rows += batch_zero_rows
        progress_message = build_progress_message(
            processed_rows=processed_rows,
            total_rows=total_rows,
            batch_number=batch_number,
            total_batches=total_batches,
            started_at=started_at,
        )
        log(
            f'{progress_message} '
            f'| pk {first_pk}-{last_pk} '
            f'| batch rows {format_count(batch_count)} '
            f'| converted {format_count(batch_convert_rows)} '
            f'| zero-volume {format_count(batch_zero_rows)}'
        )

    elapsed = time.monotonic() - started_at
    mode = 'Dry run complete' if dry_run else 'Backfill complete'
    log(mode)
    log(f'Elapsed: {elapsed:.1f}s')
    log(f'Rows processed: {processed_rows}')
    log(f'Rows converted with volume * item_price: {converted_rows}')
    log(f'Rows normalized to zero volume: {zeroed_rows}')


def main():
    """CLI entry point."""
    args = parse_args()
    backfill_all_time_volume(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == '__main__':
    main()