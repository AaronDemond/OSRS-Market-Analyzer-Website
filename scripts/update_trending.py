#!/usr/bin/env python
r"""
=============================================================================
TRENDING ITEMS UPDATE SCRIPT
=============================================================================
What: Standalone script that fetches price data, stores it in database,
      and calculates top movers
Why: Offloads expensive API calls from web requests to a background process
How: Run this script periodically (e.g., every 4 hours via cron/Task Scheduler)
     - Fetches daily price data for all items from Wiki API
     - Stores raw data in ItemPriceSnapshot model for future use
     - Calculates trending items and writes to JSON file

Usage:
    python scripts/update_trending.py

Output:
    - Database: ItemPriceSnapshot records for each item (6 snapshots per day)
    - File: Website/static/data/trending_items.json

Schedule (Windows):
    Run run_trending_loop.bat (loops with 4-hour sleep)

Schedule (Linux cron):
    0 */4 * * * cd /path/to/OSRSWebsite && python scripts/update_trending.py
=============================================================================
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# =============================================================================
# DJANGO SETUP - Required to use Django ORM from standalone script
# =============================================================================
# What: Configures Django settings so we can import models
# Why: This script runs outside of Django's normal request/response cycle
# How: Set DJANGO_SETTINGS_MODULE and call django.setup() before importing models

# SCRIPT_DIR: Directory where this script lives
SCRIPT_DIR = Path(__file__).resolve().parent

# PROJECT_ROOT: Root of the OSRSWebsite project
PROJECT_ROOT = SCRIPT_DIR.parent

# Add project root to Python path so we can import Website module
sys.path.insert(0, str(PROJECT_ROOT))

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')

import django
django.setup()

# Now we can import Django models
from Website.models import ItemPriceSnapshot

# =============================================================================
# CONFIGURATION
# =============================================================================

# VOLUME_THRESHOLD: Minimum HOURLY trading volume in GP to be considered
# 75,000,000 GP/hour filters out low-activity items with erratic price swings
# When using daily data, we calculate: (daily_volume / 24) * avg_price
VOLUME_THRESHOLD = 75_000_000

# MAX_WORKERS: Number of parallel API requests (rate limiting)
# Keep low to respect the Wiki API's rate limits
MAX_WORKERS = 5

# API_HEADERS: Required User-Agent header for RuneScape Wiki API
API_HEADERS = {'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}

# TOP_N: Number of gainers/losers to return
TOP_N = 10

# OUTPUT_FILE: Where to write the trending data JSON
OUTPUT_FILE = PROJECT_ROOT / 'Website' / 'static' / 'data' / 'trending_items.json'

# ITEM_MAPPING_FILE: Item ID to name mapping
ITEM_MAPPING_FILE = PROJECT_ROOT / 'Website' / 'static' / 'item-mapping.json'


def log(message):
    """
    Simple logging with timestamp.
    
    What: Prints a timestamped message to stdout
    Why: Track progress during long-running script execution
    How: Prepends ISO timestamp to message
    
    Args:
        message: String to log
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")


def load_item_mapping():
    """
    Load item mapping from local JSON file.
    
    What: Reads item ID to name/icon mapping from static file
    Why: Need item names and icons for the trending display
    How: Loads JSON file, returns dict keyed by lowercase item name
    
    Returns:
        dict: Mapping of item_name_lower -> {'id': int, 'name': str, 'icon': str, ...}
        None: If file not found or parse error
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


def fetch_single_item(item_tuple):
    """
    Fetch timeseries for a single item and return raw + calculated data.
    
    What: Makes API request for one item's daily data
    Why: Called in parallel by ThreadPoolExecutor
    How: Fetches 24h timeseries, returns both raw data (for storage) and calculated data (for trending)
    
    Args:
        item_tuple: (item_id, item_name, item_icon) tuple
    
    Returns:
        dict or None: {
            'raw': Raw data for database storage (current day snapshot),
            'trending': Calculated data for trending (or None if filtered out)
        }
        Returns None if API call fails
    """
    item_id, item_name, item_icon = item_tuple
    
    try:
        # Use 24h timestep to get daily price data
        response = requests.get(
            f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=24h&id={item_id}',
            headers=API_HEADERS,
            timeout=10
        )
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        if 'data' not in data or len(data['data']) < 1:
            return None
        
        # Data is sorted oldest first, so most recent is at the end
        timeseries = data['data']
        current_day = timeseries[-1]
        
        # Extract current snapshot's raw data for storage
        # Use current datetime as the snapshot timestamp (when we fetched this data)
        snapshot_timestamp = datetime.now()
        
        current_high = current_day.get('avgHighPrice')
        current_low = current_day.get('avgLowPrice')
        high_volume = current_day.get('highPriceVolume', 0) or 0
        low_volume = current_day.get('lowPriceVolume', 0) or 0
        
        # raw_data: Data to be stored in ItemPriceSnapshot model
        raw_data = {
            'item_id': item_id,
            'item_name': item_name,
            'timestamp': snapshot_timestamp,
            'avg_high_price': current_high,
            'avg_low_price': current_low,
            'high_price_volume': high_volume,
            'low_price_volume': low_volume,
        }
        
        # Now calculate trending data (requires 2 days minimum)
        trending_data = None
        
        if len(timeseries) >= 2:
            previous_day = timeseries[-2]
            
            prev_high = previous_day.get('avgHighPrice')
            prev_low = previous_day.get('avgLowPrice')
            
            # Only calculate trending if all price data is present
            if all([current_high, current_low, prev_high, prev_low]):
                current_price = (current_high + current_low) // 2
                previous_price = (prev_high + prev_low) // 2
                
                if previous_price > 0:
                    # Calculate HOURLY trading volume in GP from daily data
                    daily_volume = high_volume + low_volume
                    hourly_volume = daily_volume / 24
                    hourly_volume_gp = hourly_volume * current_price
                    
                    # Only include in trending if meets volume threshold
                    if hourly_volume_gp >= VOLUME_THRESHOLD:
                        change_percent = ((current_price - previous_price) / previous_price) * 100
                        
                        trending_data = {
                            'id': item_id,
                            'name': item_name,
                            'icon': item_icon,
                            'change': round(change_percent, 2),
                            'price': current_price,
                            'volume': int(hourly_volume_gp)
                        }
        
        return {
            'raw': raw_data,
            'trending': trending_data
        }
        
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        # Silently skip items that fail - don't spam logs
        return None


def fetch_all_items(item_ids_to_fetch):
    """
    Fetch 24h timeseries data for all items with rate limiting.
    
    What: Fetches daily price history for all items, 5 parallel requests at a time
    Why: Need historical data for storage and trending calculations
    How: Uses ThreadPoolExecutor with max_workers=5 to limit concurrent requests
    
    Args:
        item_ids_to_fetch: List of (item_id, item_name, item_icon) tuples
    
    Returns:
        tuple: (raw_data_list, trending_list)
            - raw_data_list: All items with price data (for database storage)
            - trending_list: Only high-volume items (for trending calculation)
    """
    raw_results = []
    trending_results = []
    total = len(item_ids_to_fetch)
    completed = 0
    
    log(f"Fetching data for {total} items with {MAX_WORKERS} parallel workers...")
    
    # Use ThreadPoolExecutor with limited workers to rate limit API calls
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        futures = {executor.submit(fetch_single_item, item): item for item in item_ids_to_fetch}
        
        # Process results as they complete
        for future in as_completed(futures):
            completed += 1
            
            # Progress update every 100 items
            if completed % 100 == 0:
                log(f"Progress: {completed}/{total} items processed...")
            
            result = future.result()
            if result is not None:
                # Always store raw data (if present)
                if result.get('raw'):
                    raw_results.append(result['raw'])
                
                # Only store trending data for high-volume items
                if result.get('trending'):
                    trending_results.append(result['trending'])
    
    log(f"Completed: {len(raw_results)} items with data, {len(trending_results)} passed volume filter")
    return raw_results, trending_results


def save_to_database(raw_data_list):
    """
    Save raw price data to ItemPriceSnapshot model.
    
    What: Bulk upserts price snapshots to the database
    Why: Persistent storage for historical analysis and future features
    How: Uses update_or_create to avoid duplicates (one per item per day)
    
    Args:
        raw_data_list: List of dicts with item price data
    
    Returns:
        tuple: (created_count, updated_count)
    """
    created = 0
    updated = 0
    
    log(f"Saving {len(raw_data_list)} price snapshots to database...")
    
    for item_data in raw_data_list:
        try:
            # Use create() instead of update_or_create since each run creates new snapshots
            # The unique_together constraint on (item_id, timestamp) prevents exact duplicates
            obj = ItemPriceSnapshot.objects.create(
                item_id=item_data['item_id'],
                item_name=item_data['item_name'],
                timestamp=item_data['timestamp'],
                avg_high_price=item_data['avg_high_price'],
                avg_low_price=item_data['avg_low_price'],
                high_price_volume=item_data['high_price_volume'],
                low_price_volume=item_data['low_price_volume'],
            )
            created += 1
        except Exception as e:
            # Log but don't fail the whole batch (likely duplicate timestamp)
            pass
    
    log(f"Database: {created} records created")
    return created, 0


def calculate_trending(price_changes):
    """
    Calculate top gainers and losers from price change data.
    
    What: Sorts items by price change to find biggest movers
    Why: Users want to see market trends at a glance
    How: Separate positive and negative changes, sort, take top N
    
    Args:
        price_changes: List of item dicts with 'change' key
    
    Returns:
        dict: {'gainers': [...], 'losers': [...], 'last_updated': str}
    """
    # Gainers: highest positive change first
    gainers = sorted(
        [p for p in price_changes if p['change'] > 0],
        key=lambda x: x['change'],
        reverse=True
    )[:TOP_N]
    
    # Losers: most negative change first (biggest drops)
    losers = sorted(
        [p for p in price_changes if p['change'] < 0],
        key=lambda x: x['change']
    )[:TOP_N]
    
    return {
        'gainers': gainers,
        'losers': losers,
        'last_updated': datetime.now().isoformat()
    }


def save_trending(data):
    """
    Save trending data to JSON file.
    
    What: Writes trending items data to static JSON file
    Why: Django app reads this file instead of computing trending itself
    How: Atomic write (write to temp, then rename) to prevent partial reads
    
    Args:
        data: Dict with 'gainers', 'losers', 'last_updated' keys
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temp file first (atomic write pattern)
        temp_file = OUTPUT_FILE.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        # Rename temp to final (atomic on most filesystems)
        temp_file.replace(OUTPUT_FILE)
        
        log(f"Saved trending data to {OUTPUT_FILE}")
        return True
        
    except Exception as e:
        log(f"ERROR: Failed to save trending data: {e}")
        return False


def main():
    """
    Main entry point for the trending update script.
    
    What: Orchestrates the full trending items update process
    Why: Single function to call when running as script or scheduled task
    How: Load mapping -> Fetch all items -> Calculate trending -> Save to file
    """
    start_time = time.time()
    log("=" * 60)
    log("Starting trending items update...")
    log("=" * 60)
    
    # Step 1: Load item mapping
    log("Loading item mapping...")
    item_mapping = load_item_mapping()
    if not item_mapping:
        log("FATAL: Cannot proceed without item mapping")
        sys.exit(1)
    
    log(f"Found {len(item_mapping)} items in mapping")
    
    # Step 2: Build list of items to fetch
    # item_ids_to_fetch: List of (item_id, item_name, item_icon) tuples
    # item_mapping is a list of dicts with 'id', 'name', 'icon' keys
    item_ids_to_fetch = []
    for item_data in item_mapping:
        item_ids_to_fetch.append((
            item_data['id'],
            item_data['name'],
            item_data.get('icon', '')
        ))
    
    # Step 3: Fetch price data for all items
    # Returns two lists: raw data (all items) and trending data (high-volume only)
    raw_data, trending_data = fetch_all_items(item_ids_to_fetch)
    
    # Step 4: Save raw data to database for future use
    if raw_data:
        save_to_database(raw_data)
    else:
        log("WARNING: No raw data to save to database")
    
    # Step 5: Calculate trending from high-volume items
    if not trending_data:
        log("WARNING: No items passed volume filter - saving empty trending result")
    
    log("Calculating top movers...")
    trending = calculate_trending(trending_data)
    
    log(f"Top gainers: {[g['name'] for g in trending['gainers']]}")
    log(f"Top losers: {[l['name'] for l in trending['losers']]}")
    
    # Step 6: Save trending to JSON file
    if save_trending(trending):
        elapsed = time.time() - start_time
        log(f"Update completed successfully in {elapsed:.1f} seconds")
    else:
        log("Update failed - see errors above")
        sys.exit(1)


if __name__ == '__main__':
    main()
