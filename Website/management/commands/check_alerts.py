import os
import sys
import time
import json
import math
from collections import defaultdict
from pathlib import Path
from datetime import timedelta, timezone as dt_tz

import requests
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

# Allow running the command directly (outside manage.py) by ensuring the project is on sys.path and Django is configured
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')
    import django
    django.setup()

# What: Import Django models used by the alert checker
# Why: Alert is the core model for all alert types; HourlyItemVolume provides volume data
#       for spike alert filtering; FiveMinTimeSeries provides cached timeseries data for
#       flip confidence alerts (replacing per-item HTTP API calls with fast DB queries).
# How: These models are imported from the Website app's models.py module.
from Website.models import Alert, HourlyItemVolume, FiveMinTimeSeries

# =============================================================================
# FLIP CONFIDENCE SCORING FUNCTIONS
# =============================================================================
# What: Pure functions that compute a "flip confidence" score (0-100) for an OSRS item
#        using time-series data from the OSRS Wiki API.
# Why: These functions are used by check_flip_confidence_alert() to evaluate whether
#       an item is a good flipping candidate based on trend, pressure, spread, volume,
#       and stability signals.
# How: Originally defined in scripts/confidence_score.py; imported here so check_alerts.py
#       can call them directly without subprocess or cross-module imports.
# =============================================================================

def _clamp(x, lo, hi):
    """
    Clamp a value to a range [lo, hi].

    What: Returns x capped to the range [lo, hi].
    Why: Used to normalize sub-scores to predictable 0-1 ranges.
    How: If x < lo returns lo; if x > hi returns hi; otherwise returns x.
    """
    return max(lo, min(x, hi))


def _weighted_regression_slope(prices, volumes):
    """
    Compute the slope of a volume-weighted least-squares regression line through a price series.

    What: Returns the slope of the best-fit line through price points weighted by volume.
    Why: Volume-weighted slope gives more importance to price movements during high-activity
         periods, producing a more meaningful trend signal.
    How: Uses weighted least squares with x = [0, 1, ..., n-1] as the time index
         and volumes as weights. Calculates slope = weighted_cov(x, y) / weighted_var(x).

    Args:
        prices: List of price values (one per time bucket).
        volumes: List of volume values (same length as prices).

    Returns:
        float: The slope in "price units per bucket index". Returns 0.0 if fewer than
               2 points, total weight is 0, or denominator is 0.
    """
    n = len(prices)
    if n < 2:
        return 0.0

    # x: Time index positions [0, 1, 2, ..., n-1]
    x = list(range(n))
    # total_weight: Sum of all volume weights; if zero, regression is undefined
    total_weight = sum(volumes)

    if total_weight == 0:
        return 0.0

    # x_mean: Volume-weighted mean of the time indices
    x_mean = sum(x[i] * volumes[i] for i in range(n)) / total_weight
    # y_mean: Volume-weighted mean of the price values
    y_mean = sum(prices[i] * volumes[i] for i in range(n)) / total_weight

    # numerator: Weighted covariance of x and y (prices)
    numerator = sum(
        volumes[i] * (x[i] - x_mean) * (prices[i] - y_mean)
        for i in range(n)
    )

    # denominator: Weighted variance of x (time indices)
    denominator = sum(
        volumes[i] * (x[i] - x_mean) ** 2
        for i in range(n)
    )

    return numerator / denominator if denominator else 0.0


def _standard_deviation(values):
    """
    Compute the population standard deviation of a list of numeric values.

    What: Returns the population std dev (divides by n, not n-1).
    Why: Used to measure price volatility/noise in the stability sub-score.
    How: Calculates mean, then average squared deviation, then square root.

    Args:
        values: List of numeric values.

    Returns:
        float: Population standard deviation, or 0.0 if the list is empty.
    """
    if not values:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


def compute_flip_confidence(api_data, weights=None):
    """
    Compute a flip confidence score (0-100) for an item using OSRS Wiki timeseries data.

    What: Takes a list of time-bucket dicts from the OSRS Wiki timeseries endpoint and
          returns a single numeric score (0.0 to 100.0) representing how promising the
          item looks for flipping.
    Why: Combines five market-quality signals into one number so users can quickly
         assess flip opportunities without manual analysis.
    How: Cleans the input data, extracts price/volume series, computes five sub-scores
         (trend, pressure, spread, volume, stability), then takes a weighted average.

    Args:
        api_data: List of dicts, each containing:
            - avgHighPrice: Average high (instant buy) price for the time bucket
            - avgLowPrice: Average low (instant sell) price for the time bucket
            - highPriceVolume: Number of items traded at high price
            - lowPriceVolume: Number of items traded at low price
        weights: Optional dict with keys 'trend', 'pressure', 'spread', 'volume', 'stability'
                 mapping to float weights that must sum to 1.0. If None, uses defaults
                 (0.35, 0.25, 0.20, 0.10, 0.10).

    Returns:
        float: Confidence score from 0.0 to 100.0 (rounded to 1 decimal place).
               Returns 0.0 if fewer than 3 valid data points are available.
    """
    # --- Step A: Clean the input (filter out rows with null prices) ---
    # cleaned: List of validated data dicts with non-null prices and defaulted volumes
    cleaned = []
    for p in api_data:
        # ah: Average high price for this time bucket (None means no trades occurred)
        ah = p.get("avgHighPrice")
        # al: Average low price for this time bucket (None means no trades occurred)
        al = p.get("avgLowPrice")
        # hv: High price volume (number of items instant-bought); defaults to 0 if missing
        hv = p.get("highPriceVolume")
        # lv: Low price volume (number of items instant-sold); defaults to 0 if missing
        lv = p.get("lowPriceVolume")

        # Skip rows where either price is None (no trades in that bucket)
        if ah is None or al is None:
            continue

        cleaned.append({
            "avgHighPrice": ah,
            "avgLowPrice": al,
            "highPriceVolume": hv or 0,
            "lowPriceVolume": lv or 0,
        })

    # Require at least 3 data points for meaningful statistical analysis
    if len(cleaned) < 3:
        return 0.0

    # --- Step B: Extract series and compute basic aggregates ---
    # avg_high_prices: List of average high prices across all cleaned buckets
    avg_high_prices = [p["avgHighPrice"] for p in cleaned]
    # avg_low_prices: List of average low prices across all cleaned buckets
    avg_low_prices = [p["avgLowPrice"] for p in cleaned]
    # high_volumes: List of high-price trade volumes across all cleaned buckets
    high_volumes = [p["highPriceVolume"] for p in cleaned]
    # low_volumes: List of low-price trade volumes across all cleaned buckets
    low_volumes = [p["lowPriceVolume"] for p in cleaned]

    # n: Number of cleaned data points
    n = len(cleaned)

    # avg_price: Overall average price (mean of all high and low prices combined)
    avg_price = (sum(avg_high_prices) + sum(avg_low_prices)) / (2 * n)
    # avg_high: Mean of high prices only
    avg_high = sum(avg_high_prices) / n
    # avg_low: Mean of low prices only
    avg_low = sum(avg_low_prices) / n

    # total_high_volume: Sum of all high-price trade volumes
    total_high_volume = sum(high_volumes)
    # total_low_volume: Sum of all low-price trade volumes
    total_low_volume = sum(low_volumes)
    # total_volume: Combined total of all trade volumes
    total_volume = total_high_volume + total_low_volume

    # --- Sub-score 1: Trend (volume-weighted regression slope) ---
    # high_slope: Slope of high-price trend weighted by high volumes
    high_slope = _weighted_regression_slope(avg_high_prices, high_volumes)
    # low_slope: Slope of low-price trend weighted by low volumes
    low_slope = _weighted_regression_slope(avg_low_prices, low_volumes)

    # weighted_slope: Combined slope emphasizing high-price trend (60/40 split)
    weighted_slope = 0.6 * high_slope + 0.4 * low_slope

    # trend_strength: Normalized relative slope, clamped to [-2%, +2%] per bucket
    trend_strength = _clamp(weighted_slope / avg_price, -0.02, 0.02)
    # trend_score: Mapped to 0-1 where -2% => 0, 0% => 0.5, +2% => 1.0
    trend_score = (trend_strength + 0.02) / 0.04

    # --- Sub-score 2: Buy vs sell pressure ---
    # buy_pressure: Ratio of high-volume trades to total trades (0.5 = balanced)
    buy_pressure = (total_high_volume / total_volume) if total_volume > 0 else 0.5
    # pressure_score: Rescaled to 0-1 where 0.25 => 0, 0.5 => 0.5, 0.75 => 1.0
    pressure_score = _clamp((buy_pressure - 0.5) * 2 + 0.5, 0.0, 1.0)

    # --- Sub-score 3: Spread health ---
    # spread_pct: Percentage spread between average high and low prices
    spread_pct = (avg_high - avg_low) / avg_low if avg_low > 0 else 0.0
    # spread_score: Normalized to 0-1 where 0% => 0, 1.5% => 0.5, 3%+ => 1.0
    spread_score = _clamp(spread_pct / 0.03, 0.0, 1.0)

    # --- Sub-score 4: Volume sufficiency ---
    # volume_threshold: Dynamic "enough volume" threshold based on item price tier
    # Minimum 200 trades; scales linearly with price (2000 per 1M GP)
    volume_threshold = max(200, int(2000 * (avg_price / 1_000_000)))
    # volume_score: Ratio of total volume to threshold, capped at 1.0
    volume_score = _clamp(total_volume / volume_threshold, 0.0, 1.0)

    # --- Sub-score 5: Stability (noise penalty) ---
    # mid_prices: Mid-point prices for each bucket (average of high and low)
    mid_prices = [(avg_high_prices[i] + avg_low_prices[i]) / 2 for i in range(n)]
    # price_std: Population standard deviation of mid-prices
    price_std = _standard_deviation(mid_prices)
    # stability_score: 1.0 minus relative volatility, where 1% std = 0 stability
    stability_score = 1.0 - _clamp((price_std / avg_price) / 0.01, 0.0, 1.0)

    # --- Final weighted score ---
    # Use custom weights if provided, otherwise use defaults
    if weights:
        w_trend = weights.get('trend', 0.35)
        w_pressure = weights.get('pressure', 0.25)
        w_spread = weights.get('spread', 0.20)
        w_volume = weights.get('volume', 0.10)
        w_stability = weights.get('stability', 0.10)
    else:
        w_trend = 0.35
        w_pressure = 0.25
        w_spread = 0.20
        w_volume = 0.10
        w_stability = 0.10

    # score: Weighted average of all five sub-scores (0.0 to 1.0 range)
    score = (
        w_trend * trend_score +
        w_pressure * pressure_score +
        w_spread * spread_score +
        w_volume * volume_score +
        w_stability * stability_score
    )

    return round(score * 100, 1)


class Command(BaseCommand):
    help = 'Continuously checks alerts every 30 seconds and triggers them if conditions are met'

    # Email/SMS recipient for alert notifications (loaded from environment variable)
    ALERT_RECIPIENT = os.environ.get('ALERT_RECIPIENT', '')
    # VOLUME_RECENCY_MINUTES: Maximum age (in minutes) that a HourlyItemVolume snapshot
    #                          can be before it is considered stale for min_volume checks.
    # What: Defines the freshness window for hourly volume data used by spike/threshold/spread/sustained alerts.
    # Why: The RuneScape Wiki hourly timeseries endpoint can lag by ~2 hours; we allow a 10-minute
    #      buffer so alerts still work with delayed data while preventing stale snapshots (e.g., 6h old)
    #      from passing min_volume filters.
    # How: get_volume_from_timeseries compares the latest snapshot timestamp against
    #      timezone.now() minus this window and returns None when the snapshot is too old.
    VOLUME_RECENCY_MINUTES = 130

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_mapping = None
        self.price_history = defaultdict(list)  # key: itemId:reference, value: list[(ts, price)]
        
        # Sustained move tracking state - keyed by alert_id
        # Each entry contains: {
        #   'last_price': float,           # Last observed average price
        #   'streak_count': int,           # Current consecutive move count
        #   'streak_direction': str,       # 'up' or 'down'
        #   'streak_start_time': float,    # Timestamp when streak started
        #   'streak_total_move': float,    # Total absolute price change during streak
        #   'volatility_buffer': list,     # Rolling buffer of absolute moves
        # }
        self.sustained_state = {}
        
        # =============================================================================
        # DUMP ALERT MARKET DRIFT STATE
        # =============================================================================
        # What: Instance-level state for computing market-wide drift each check cycle.
        # Why: Dump alerts need to subtract market-wide movement from individual item returns
        #      to isolate idiosyncratic (item-specific) shocks. This state persists across
        #      cycles within the same process lifetime.
        # How: 'last_mids' stores the previous cycle's mid prices per item so we can compute
        #      log returns; 'market_drift' stores the latest computed median return.
        self.dump_market_state = {
            'last_mids': {},      # item_id_str -> last mid price (float)
            'market_drift': 0.0,  # median log return of liquid items this cycle
        }

    def get_item_mapping(self):
        """Fetch and cache item ID to name mapping"""
        if self.item_mapping is None:
            try:
                response = requests.get(
                    'https://prices.runescape.wiki/api/v1/osrs/mapping',
                    headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
                )
                if response.status_code == 200:
                    data = response.json()
                    self.item_mapping = {str(item['id']): item['name'] for item in data}
            except requests.RequestException:
                self.item_mapping = {}
        return self.item_mapping

    def get_all_prices(self):
        """Fetch all current prices in one API call"""
        try:
            response = requests.get(
                'https://prices.runescape.wiki/api/v1/osrs/latest',
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
            )
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    return data['data']
        except requests.RequestException as e:
            self.stdout.write(self.style.ERROR(f'Error fetching prices: {e}'))
        return {}

    def calculate_spread(self, high, low):
        """Calculate spread percentage: ((high - low) / low) * 100"""
        if low is None or low == 0 or high is None:
            return None
        return ((high - low) / low) * 100

    def _check_spread_for_item_ids(self, alert, all_prices):
        """
        Check spread conditions for a multi-item spread alert (using item_ids field).
        
        What: Checks if specific items (stored in item_ids JSON) meet the spread threshold
              AND optional minimum hourly volume requirement.
        Why: Allows users to monitor multiple specific items for spread alerts, with an
             optional volume filter to ensure only actively-traded items trigger alerts.
        How: 
            1. Parse item_ids JSON array to get list of items to check
            2. For each item, calculate spread and compare against threshold
            3. If min_volume is set, check the item's latest HourlyItemVolume from the DB
            4. Build triggered_data with items that meet ALL criteria
            5. Return list of triggered items (empty list if none triggered)
        
        Args:
            alert: Alert model instance with item_ids set
            all_prices: Dictionary of all current prices keyed by item_id
            
        Returns:
            List of triggered item data dicts (may be empty if none triggered)
            Each dict contains: item_id, item_name, high, low, spread
            Returns None only on parse error (invalid item_ids JSON)
        """
        try:
            # item_ids_list: List of integer item IDs to check against
            item_ids_list = json.loads(alert.item_ids)
            if not isinstance(item_ids_list, list) or not item_ids_list:
                return None
        except (json.JSONDecodeError, TypeError):
            return None
        
        # item_mapping: Dictionary mapping item_id -> item_name for display purposes
        item_mapping = self.get_item_mapping()
        
        # triggered_items: List of items that currently meet the spread threshold
        # These will be stored in triggered_data for display
        triggered_items = []
        
        for item_id in item_ids_list:
            # Convert to string for dict lookup (API returns string keys)
            item_id_str = str(item_id)
            price_data = all_prices.get(item_id_str)
            
            if not price_data:
                continue
            
            high = price_data.get('high')
            low = price_data.get('low')
            
            # spread: The percentage difference between high and low prices
            spread = self.calculate_spread(high, low)
            
            if spread is not None and spread >= alert.percentage:
                # =========================================================================
                # VOLUME FILTER FOR MULTI-ITEM SPREAD ALERTS
                # What: Skip items whose hourly volume (GP) is below the user's min_volume
                # Why: Users may only want to see spread opportunities on actively-traded
                #      items. Low-volume items can have inflated spreads but are hard to
                #      actually flip because there aren't enough buyers/sellers.
                # How: Query the HourlyItemVolume table for the latest volume snapshot.
                #      If the volume is below the threshold, skip this item entirely.
                # =========================================================================
                if alert.min_volume:
                    # volume: The most recent hourly trading volume in GP for this item,
                    #         or None if no volume data exists in the database yet
                    volume = self.get_volume_from_timeseries(item_id_str, 0)
                    if volume is None or volume < alert.min_volume:
                        continue

                # item_name: Human-readable name for display, defaults to "Item {id}" if not found
                item_name = item_mapping.get(item_id_str, f'Item {item_id}')
                triggered_items.append({
                    'item_id': item_id_str,
                    'item_name': item_name,
                    'high': high,
                    'low': low,
                    'spread': round(spread, 2)
                })
        
        # Sort by spread descending so highest spreads appear first
        if triggered_items:
            triggered_items.sort(key=lambda x: x['spread'], reverse=True)
        
        # Always return the list (even if empty) so handle() can update triggered_data
        # This ensures that when items drop below threshold, the UI reflects that change
        return triggered_items

    def _has_triggered_data_changed(self, old_data_json, new_triggered_items):
        """
        Check if triggered data has meaningfully changed from the previous state.
        
        What: Compares old triggered_data with new triggered items to detect changes
        Why: We should only send notifications when there's actual new information
        How: 
            1. Parse old data JSON
            2. Compare item IDs and all data values
            3. Return True if any item is new, dropped out, or has different values
        
        Args:
            old_data_json: JSON string of previous triggered_data (or None)
            new_triggered_items: List of newly triggered item dicts (may be empty)
            
        Returns:
            Boolean indicating if there are meaningful changes worth notifying about
        """
        # Handle case where new_triggered_items is empty
        if not new_triggered_items:
            # If old data exists and had items, that's a change (all items dropped out)
            if old_data_json:
                try:
                    old_items = json.loads(old_data_json)
                    if isinstance(old_items, list) and len(old_items) > 0:
                        return True  # Had items before, now have none
                except (json.JSONDecodeError, TypeError):
                    pass
            return False  # No old data and no new data = no change
        
        if not old_data_json:
            # No previous data but we have new items - this is a new trigger
            return True
        
        try:
            # old_items: List of previously triggered item data
            old_items = json.loads(old_data_json)
            if not isinstance(old_items, list):
                return True
        except (json.JSONDecodeError, TypeError):
            return True
        
        # old_items_map: Dictionary mapping item_id -> item data for quick lookup
        # Used to compare individual item data values
        old_items_map = {str(item.get('item_id')): item for item in old_items}
        
        # new_items_map: Dictionary of new triggered items for comparison
        new_items_map = {str(item.get('item_id')): item for item in new_triggered_items}
        
        # Check for new items that weren't in old data
        # What: Detect items that are now triggering but weren't before
        # Why: New items triggering is a meaningful change worth notifying about
        for item_id in new_items_map:
            if item_id not in old_items_map:
                # New item triggered that wasn't triggered before
                return True
        
        # Check for items that dropped out (no longer meet threshold)
        # What: Detect items that were triggering but no longer are
        # Why: Items dropping out is a meaningful change worth notifying about
        for item_id in old_items_map:
            if item_id not in new_items_map:
                # An item that was triggered is no longer triggered
                return True
        
        # Check for data value changes on items that exist in both old and new
        # What: Compare all numeric values for items present in both
        # Why: Even if same items are triggering, price/spread changes are meaningful
        # How: Compare rounded values to avoid float precision false positives
        #
        # Fields to compare by alert type:
        # - Spread alerts: spread, high, low
        # - Threshold alerts: current_price, change_percent
        # - Spike alerts: percent_change, current
        # - Sustained alerts: total_move_percent, current_price, streak_count
        #
        # Generic comparison: compare all numeric fields present in items
        for item_id, new_item in new_items_map.items():
            old_item = old_items_map.get(item_id)
            if old_item:
                # Compare all common fields between old and new item
                # fields_to_compare: List of field names that exist in both items
                all_fields = set(old_item.keys()) | set(new_item.keys())
                
                for field in all_fields:
                    old_val = old_item.get(field)
                    new_val = new_item.get(field)
                    
                    # Skip non-comparable fields (item_id, item_name, direction)
                    if field in ('item_id', 'item_name', 'direction', 'threshold', 'reference', 'reference_price'):
                        continue
                    
                    # Compare numeric values with rounding for floats
                    if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                        # Round to 2 decimal places to avoid float precision issues
                        if round(float(old_val), 2) != round(float(new_val), 2):
                            return True
                    elif old_val != new_val:
                        # Non-numeric values: direct comparison
                        return True
        
        # No meaningful changes detected
        return False

    def _handle_multi_item_spread_trigger(self, alert, triggered_items):
        """
        Handle trigger logic for multi-item spread alerts (using item_ids field).
        
        What: Processes triggered items for spread alerts monitoring multiple specific items
        Why: Multi-item spread alerts should only fully deactivate when ALL monitored items trigger
        How:
            1. Get the total list of items being monitored (from item_ids)
            2. Check if triggered data has meaningfully changed (items added/removed/spread changed)
            3. Compare against currently triggered items
            4. If all items have triggered, deactivate the alert
            5. Otherwise, keep the alert active and update triggered_data
            6. Only send notification if data has changed
        
        Args:
            alert: Alert model instance with item_ids set
            triggered_items: List of item data dicts that currently meet the spread threshold
                            (may be empty if no items meet threshold)
        
        Deactivation Logic:
            - Alert stays active until EVERY item in item_ids has triggered at least once
            - triggered_data shows current items meeting the threshold (updated each check)
            - Only when triggered_items contains ALL item_ids does the alert deactivate
            
        Notification Logic:
            - Only send notification if triggered data has meaningfully changed
            - Changes include: new items triggering, items dropping out, spread values changing
            - Prevents spam when data stays the same between checks
            
        Data Update Logic:
            - ALWAYS update triggered_data with latest values on every check
            - This ensures the UI always shows current high/low/spread values
        """
        try:
            # total_item_ids: List of all item IDs the alert is meant to monitor
            total_item_ids = json.loads(alert.item_ids)
            if not isinstance(total_item_ids, list):
                total_item_ids = []
        except (json.JSONDecodeError, TypeError):
            total_item_ids = []
        
        # old_triggered_data: Previous triggered_data for comparison
        # Used to determine if we should send a notification
        old_triggered_data = alert.triggered_data
        
        # data_changed: Boolean indicating if triggered data has meaningfully changed
        # If False, we skip notification to avoid spam
        data_changed = self._has_triggered_data_changed(old_triggered_data, triggered_items)
        
        # triggered_item_ids: Set of item IDs that triggered in this check cycle
        # Using set for O(1) lookup when comparing against total_item_ids
        triggered_item_ids = set(str(item['item_id']) for item in triggered_items)
        
        # total_item_ids_set: Set of all item IDs for comparison
        total_item_ids_set = set(str(item_id) for item_id in total_item_ids)
        
        # Check if ALL items have triggered
        # all_triggered: Boolean indicating if every monitored item has reached the threshold
        all_triggered = len(triggered_items) > 0 and total_item_ids_set.issubset(triggered_item_ids)
        
        # ALWAYS update triggered_data with current snapshot (even if empty)
        # What: Store current triggered items (or empty array) in triggered_data
        # Why: The UI should always reflect the current state of which items meet threshold
        # How: Serialize triggered_items list to JSON (may be empty array "[]")
        alert.triggered_data = json.dumps(triggered_items)
        
        # Only update is_triggered and triggered_at if we have actual triggered items
        if triggered_items:
            alert.is_triggered = True
            alert.triggered_at = timezone.now()
        
        # Only reset is_dismissed if data has actually changed AND show_notification is enabled
        # What: Controls whether notification banner appears when alert triggers
        # Why: Users may disable notifications but still want to track alerts
        # How: Only set is_dismissed=False if show_notification is True
        if data_changed and alert.show_notification:
            alert.is_dismissed = False
        
        if all_triggered:
            # All items have triggered
            # What: Log that all items met the threshold
            # Why: User may want to know when all items have triggered
            # Note: Alert stays active - only user can deactivate manually
            alert.is_active = True
            self.stdout.write(
                self.style.WARNING(
                    f'TRIGGERED (multi-item spread - ALL {len(total_item_ids)} items): Alert stays active'
                )
            )
        else:
            # Some items triggered but not all (or none) - keep alert active
            # What: Keep is_active True to continue monitoring remaining items
            # Why: Alert should stay active until manually deactivated by user
            alert.is_active = True
            if data_changed and triggered_items:
                self.stdout.write(
                    self.style.WARNING(
                        f'TRIGGERED (multi-item spread): {len(triggered_items)}/{len(total_item_ids)} items triggered'
                    )
                )
            elif data_changed and not triggered_items:
                self.stdout.write(
                    self.style.WARNING(
                        f'Multi-item spread alert {alert.id}: All items dropped below threshold (0/{len(total_item_ids)})'
                    )
                )
            else:
                self.stdout.write(
                    f'Multi-item spread alert {alert.id}: No changes ({len(triggered_items)}/{len(total_item_ids)} items)'
                )
        
        alert.save()
        
        # Only send email notification if data has changed AND notifications are enabled
        # AND there are actually triggered items to report
        # This prevents email spam when the same items keep triggering with same values
        if alert.email_notification and data_changed and triggered_items:
            self.send_alert_notification(alert, alert.triggered_text())
            # Disable email notification after first trigger to prevent spam
            # What: Set email_notification to False after sending
            # Why: User only wants to be notified once, but alert stays active for monitoring
            # How: Alert can still re-trigger and update triggered_data, just won't send emails
            alert.email_notification = False
            alert.save()

    def _handle_multi_item_spike_trigger(self, alert, triggered_items, all_within_threshold, all_warmed_up):
        """
        Handle trigger logic for multi-item spike alerts (using item_ids field).
        
        What: Processes triggered items for spike alerts monitoring multiple specific items
        Why: Multi-item spike alerts should:
             - Trigger when ANY item exceeds threshold
             - Re-trigger when triggered_data CHANGES (different items or percentages)
             - NOT re-trigger if triggered_data is identical
             - Deactivate when ALL items are SIMULTANEOUSLY within threshold
        How:
            1. Compare new triggered_data to previous triggered_data
            2. If different → trigger/re-trigger and notify
            3. If same → don't notify (avoid spam)
            4. If all items within threshold → deactivate
        
        Args:
            alert: Alert model instance with item_ids set
            triggered_items: List of item data dicts that currently exceed the spike threshold
                           (may be empty if no items exceed threshold)
            all_within_threshold: Boolean - True if ALL items are within threshold (none exceed)
            all_warmed_up: Boolean - True if all items have sufficient historical data
        
        Returns:
            - List of triggered_items if data changed (for notification handling)
            - False if no change or deactivated
            
        Deactivation Logic:
            - Alert deactivates when ALL items are SIMULTANEOUSLY within threshold
            - If item A triggered then fell back, but item B is still triggered → stay active
            - Must be a single check where every monitored item is within bounds
            
        Re-trigger Logic:
            - Compare current triggered_data to previous
            - If ANY difference (items added, removed, or percentages changed) → re-trigger
            - Prevents notification spam when same items trigger with same values
        """
        try:
            # total_item_ids: List of all item IDs the alert is meant to monitor
            total_item_ids = json.loads(alert.item_ids)
            if not isinstance(total_item_ids, list):
                total_item_ids = []
        except (json.JSONDecodeError, TypeError):
            total_item_ids = []
        
        # old_triggered_data: Previous triggered_data for comparison
        # Used to determine if we should re-trigger and send notification
        old_triggered_data = alert.triggered_data
        
        # data_changed: Boolean indicating if triggered data has meaningfully changed
        # If False, we skip notification to avoid spam
        data_changed = self._has_triggered_data_changed(old_triggered_data, triggered_items)
        
        # Always update triggered_data with current snapshot
        # What: Store current triggered items in triggered_data (even if empty)
        # Why: The UI should always reflect the current state of which items exceed threshold
        # How: Serialize triggered_items list to JSON (may be empty array "[]")
        new_triggered_data = json.dumps(triggered_items) if triggered_items else json.dumps([])
        alert.triggered_data = new_triggered_data
        
        # =============================================================================
        # TRIGGER/RE-TRIGGER CHECK: Has triggered_data changed?
        # =============================================================================
        # Note: Multi-item spike alerts do NOT auto-deactivate. They stay active until
        # manually turned off by the user. This allows continuous monitoring for spikes.
        if triggered_items:
            # We have items exceeding threshold
            if data_changed:
                # Data changed - this is a new trigger or re-trigger
                alert.is_triggered = True
                alert.triggered_at = timezone.now()
                
                # Only show notification if enabled
                if alert.show_notification:
                    alert.is_dismissed = False
                
                alert.is_active = True  # Keep monitoring for changes
                alert.save()
                
                self.stdout.write(
                    self.style.WARNING(
                        f'TRIGGERED (multi-item spike): {len(triggered_items)}/{len(total_item_ids)} items exceed threshold'
                    )
                )
                
                # Send email notification if enabled, then disable to prevent spam
                # What: Send notification once, then disable email_notification
                # Why: User only wants one notification per trigger, but alert stays active
                if alert.email_notification:
                    self.send_alert_notification(alert, alert.triggered_text())
                    alert.email_notification = False
                    alert.save()
                
                return triggered_items
            else:
                # Data unchanged - don't re-notify
                alert.is_active = True  # Keep monitoring
                alert.save()
                self.stdout.write(
                    f'Multi-item spike alert {alert.id}: No data change ({len(triggered_items)}/{len(total_item_ids)} items still exceeding)'
                )
                return False
        else:
            # No items exceeding threshold, but not all warmed up or not all within threshold
            # Keep the alert active and monitoring
            alert.is_active = True
            if data_changed and old_triggered_data:
                # Items that were triggered have now dropped below threshold
                self.stdout.write(
                    f'Multi-item spike alert {alert.id}: Items returned within threshold, waiting for all items'
                )
            alert.save()
            return False

    # =============================================================================
    # THRESHOLD ALERT METHODS
    # =============================================================================
    
    def check_threshold_alert(self, alert, all_prices):
        """
        Check if a threshold alert should trigger.
        
        What: Checks if item price(s) have crossed the threshold from their reference price
        Why: Users want to be notified when prices change by a certain amount/percentage
        How: 
            - For value-based: Check if current price crosses target_price
            - For percentage-based: Check if current price differs from reference_prices by threshold %
        
        Args:
            alert: Alert model instance with threshold configuration
            all_prices: Dictionary of all current prices keyed by item_id
        
        Returns:
            - True/False for single-item alerts
            - List of triggered items for multi-item/all-items alerts
        """
        # Get threshold configuration
        # threshold_type: 'percentage' or 'value'
        threshold_type = alert.threshold_type or 'percentage'
        # direction: 'up' or 'down'
        direction = (alert.direction or 'up').lower()
        # =============================================================================
        # REFERENCE TYPE FOR THRESHOLD ALERTS
        # =============================================================================
        # What: Determine which price type (high/low/average) to use for comparisons
        # Why: Users can choose to monitor high (instant buy), low (instant sell), or average
        # How: Get from alert.reference field, default to 'average' for new alerts
        # Note: Changed default from 'high' to 'average' for consistency across all alert types
        # =============================================================================
        reference_type = alert.reference or 'average'
        # threshold_value: The percentage threshold (stored in alert.percentage)
        threshold_value = alert.percentage if alert.percentage is not None else 0
        
        # Determine which items to check
        # items_to_check: List of (item_id_str, reference_price) tuples
        items_to_check = []
        
        if threshold_type == 'value':
            # =============================================================================
            # VALUE-BASED THRESHOLD: SINGLE ITEM ONLY
            # =============================================================================
            # What: Check if current price crosses the target_price (absolute gp value)
            # Why: User wants to be alerted when price reaches a specific gp value
            # How: Compare current price to target_price based on direction (up/down)
            # Note: Value-based thresholds are single-item only (no multi-item support)
            # =============================================================================
            if not alert.item_id or alert.target_price is None:
                return False
            
            # item_id_str: String version of item ID for dictionary lookups
            item_id_str = str(alert.item_id)
            # price_data: Dict containing 'high' and 'low' prices for this item from API
            price_data = all_prices.get(item_id_str)
            if not price_data:
                return False
            
            # Get current price based on reference type
            # current_price: The current market price based on reference_type setting (high/low/average)
            current_price = self._get_price_by_reference(price_data, reference_type)
            if current_price is None:
                return False

            # =============================================================================
            # VOLUME FILTER FOR VALUE-BASED THRESHOLD ALERTS
            # =============================================================================
            # What: Skip triggering if the item's hourly trading volume (GP) is below min_volume
            # Why: Users may want threshold alerts to only fire for actively traded items,
            #      avoiding noisy alerts on illiquid items with unreliable prices
            # How: Query the HourlyItemVolume table for the latest volume snapshot and
            #      return False early if the volume is missing or below the threshold
            # =============================================================================
            if alert.min_volume:
                # volume: The most recent hourly trading volume (in GP) for this item
                # What: Volume value used to enforce the minimum activity requirement
                # Why: Ensures alerts only trigger for items meeting the user's liquidity filter
                # How: Retrieved from get_volume_from_timeseries, which reads HourlyItemVolume
                volume = self.get_volume_from_timeseries(item_id_str, 0)
                if volume is None or volume < alert.min_volume:
                    return False
            
            # target: The target price the user wants to be alerted at
            target = alert.target_price
            
            # Check if threshold is crossed
            # For 'up': trigger when current_price >= target (price has risen to/above target)
            # For 'down': trigger when current_price <= target (price has fallen to/below target)
            if direction == 'up':
                triggered = current_price >= target
            else:  # direction == 'down'
                triggered = current_price <= target
            
            if triggered:
                # =============================================================================
                # BUILD TRIGGERED_DATA FOR VALUE-BASED THRESHOLD ALERT
                # =============================================================================
                # What: Create a JSON-serializable dict with all trigger details
                # Why: The alert_detail view and triggered_text() method need this data to
                #      display what triggered the alert (target price, current price, direction,
                #      and baseline price at alert creation time)
                # How: Build dict with relevant fields for value-based threshold display.
                #      Includes reference_price (baseline) from alert.reference_prices if available,
                #      so users can see what the price was when the alert was first created.
                # =============================================================================
                item_mapping = self.get_item_mapping()
                # item_name: Human-readable name of the item for display
                item_name = item_mapping.get(item_id_str, alert.item_name or f'Item {item_id_str}')
                
                # reference_price: The baseline price at alert creation time, retrieved from
                # the alert's reference_prices JSON field. This is stored at creation for context —
                # it lets users see where the price started relative to the target.
                # For example: "Price was 12M at creation, target was 15M, now it's at 15.2M"
                reference_price = None
                if alert.reference_prices:
                    try:
                        ref_prices = json.loads(alert.reference_prices)
                        reference_price = ref_prices.get(item_id_str)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                # triggered_item: Dict containing all information about the triggered alert
                triggered_item = {
                    'item_id': item_id_str,
                    'item_name': item_name,
                    'target_price': target,
                    'current_price': current_price,
                    'reference_price': reference_price,
                    'direction': direction,
                    'threshold_type': 'value'
                }
                
                # Store as triggered_data JSON
                # Why: This enables proper display in alert_detail view and triggered_text()
                alert.triggered_data = json.dumps(triggered_item)
                
                return True
            
            return False
        
        # Percentage-based threshold
        # What: Check if current price differs from baseline by threshold %
        # Why: User wants to be alerted when price changes by a certain percentage
        
        # Load reference prices
        reference_prices = {}
        if alert.reference_prices:
            try:
                reference_prices = json.loads(alert.reference_prices)
            except (json.JSONDecodeError, TypeError):
                pass
        
        if not reference_prices:
            # No reference prices stored - can't calculate percentage change
            return False
        
        if alert.is_all_items:
            # All items mode: Check all items in market (respecting min/max filters)
            # triggered_items: List of items that meet the threshold
            triggered_items = []
            item_mapping = self.get_item_mapping()
            
            for item_id, price_data in all_prices.items():
                item_id_str = str(item_id)
                
                # Apply min/max price filters if configured
                high = price_data.get('high')
                low = price_data.get('low')
                
                if alert.minimum_price is not None:
                    if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                        continue
                if alert.maximum_price is not None:
                    if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                        continue
                
                # Get reference price for this item
                ref_price = reference_prices.get(item_id_str)
                if ref_price is None:
                    # No baseline for this item - skip it
                    continue
                
                # Get current price
                current_price = self._get_price_by_reference(price_data, reference_type)
                if current_price is None:
                    continue
                
                # Calculate percentage change
                change_percent = self._calculate_percent_change(ref_price, current_price)
                
                # Check if threshold is crossed
                threshold_crossed = self._check_threshold_crossed(
                    change_percent, threshold_value, direction
                )
                
                if threshold_crossed:
                    # =========================================================================
                    # VOLUME FILTER FOR ALL-ITEMS THRESHOLD ALERTS
                    # =========================================================================
                    # What: Skip items whose hourly volume (GP) is below the user's min_volume
                    # Why: Ensures threshold alerts only surface items with sufficient liquidity
                    # How: Query the HourlyItemVolume table for the latest snapshot and
                    #      skip adding the item if volume is missing or below threshold
                    # =========================================================================
                    if alert.min_volume:
                        # volume: The most recent hourly trading volume (in GP) for this item
                        # What: Activity metric used to enforce the minimum volume filter
                        # Why: Avoids triggering alerts on low-liquidity items
                        # How: Retrieved via get_volume_from_timeseries (DB-backed lookup)
                        volume = self.get_volume_from_timeseries(item_id_str, 0)
                        if volume is None or volume < alert.min_volume:
                            continue
                    item_name = item_mapping.get(item_id_str, f'Item {item_id_str}')
                    triggered_items.append({
                        'item_id': item_id_str,
                        'item_name': item_name,
                        'reference_price': ref_price,
                        'current_price': current_price,
                        'change_percent': round(change_percent, 2),
                        'threshold': threshold_value,
                        'direction': direction
                    })
            
            if triggered_items:
                # Sort by absolute change percentage (highest first)
                triggered_items.sort(key=lambda x: abs(x['change_percent']), reverse=True)
            
            return triggered_items
        
        elif alert.item_ids:
            # Multi-item mode: Check specific list of items
            triggered_items = []
            item_mapping = self.get_item_mapping()
            
            try:
                item_ids_list = json.loads(alert.item_ids)
            except (json.JSONDecodeError, TypeError):
                return []
            
            for item_id in item_ids_list:
                item_id_str = str(item_id)
                
                # Get price data
                price_data = all_prices.get(item_id_str)
                if not price_data:
                    continue
                
                # Get reference price for this item
                ref_price = reference_prices.get(item_id_str)
                if ref_price is None:
                    continue
                
                # Get current price
                current_price = self._get_price_by_reference(price_data, reference_type)
                if current_price is None:
                    continue
                
                # Calculate percentage change
                change_percent = self._calculate_percent_change(ref_price, current_price)
                
                # Check if threshold is crossed
                threshold_crossed = self._check_threshold_crossed(
                    change_percent, threshold_value, direction
                )
                
                if threshold_crossed:
                    # =========================================================================
                    # VOLUME FILTER FOR MULTI-ITEM THRESHOLD ALERTS
                    # =========================================================================
                    # What: Skip items whose hourly volume (GP) is below the user's min_volume
                    # Why: Prevents threshold alerts from triggering on low-activity items
                    # How: Query HourlyItemVolume for the latest snapshot and skip if
                    #      volume is missing or below the configured minimum
                    # =========================================================================
                    if alert.min_volume:
                        # volume: Most recent hourly trading volume (GP) for this item
                        # What: Used to validate liquidity before triggering
                        # Why: Enforces the user's minimum activity requirement
                        # How: Retrieved through get_volume_from_timeseries (DB-backed)
                        volume = self.get_volume_from_timeseries(item_id_str, 0)
                        if volume is None or volume < alert.min_volume:
                            continue
                    item_name = item_mapping.get(item_id_str, f'Item {item_id_str}')
                    triggered_items.append({
                        'item_id': item_id_str,
                        'item_name': item_name,
                        'reference_price': ref_price,
                        'current_price': current_price,
                        'change_percent': round(change_percent, 2),
                        'threshold': threshold_value,
                        'direction': direction
                    })
            
            if triggered_items:
                triggered_items.sort(key=lambda x: abs(x['change_percent']), reverse=True)
            
            return triggered_items
        
        else:
            # Single item mode (percentage-based)
            # =============================================================================
            # SINGLE-ITEM PERCENTAGE-BASED THRESHOLD ALERT
            # =============================================================================
            # What: Checks if a single item's price has changed by the threshold percentage
            # Why: Users want to be notified when a specific item's price changes significantly
            # How: 
            #   1. Get the stored reference price (baseline at alert creation)
            #   2. Get current price based on reference type (high/low/average)
            #   3. Calculate percentage change from reference to current
            #   4. If threshold is crossed, build triggered_data and return True
            # Note: We must build and store triggered_data here (not just return True)
            #       so the alert detail page and triggered_text() can display proper info
            # =============================================================================
            if not alert.item_id:
                return False
            
            # item_id_str: String version of item ID for dictionary lookups
            item_id_str = str(alert.item_id)
            
            # Get price data
            # price_data: Dict containing 'high' and 'low' prices for this item from API
            price_data = all_prices.get(item_id_str)
            if not price_data:
                return False
            
            # Get reference price
            # ref_price: The baseline price stored when the alert was created/reset
            # This is what we compare against to calculate percentage change
            ref_price = reference_prices.get(item_id_str)
            if ref_price is None:
                return False
            
            # Get current price
            # current_price: The current market price based on reference_type setting
            current_price = self._get_price_by_reference(price_data, reference_type)
            if current_price is None:
                return False
            
            # Calculate percentage change
            # change_percent: How much the price has changed as a percentage
            # Positive = price increased, Negative = price decreased
            change_percent = self._calculate_percent_change(ref_price, current_price)
            
            # Check if threshold is crossed
            # threshold_crossed: Boolean indicating if change meets/exceeds threshold in specified direction
            threshold_crossed = self._check_threshold_crossed(change_percent, threshold_value, direction)
            
            if threshold_crossed:
                # =========================================================================
                # VOLUME FILTER FOR SINGLE-ITEM THRESHOLD ALERTS
                # =========================================================================
                # What: Skip triggering if the item's hourly volume (GP) is below min_volume
                # Why: Ensures single-item threshold alerts respect the liquidity filter
                # How: Query the HourlyItemVolume table for the latest snapshot and
                #      return False if volume is missing or below the minimum
                # =========================================================================
                if alert.min_volume:
                    # volume: The most recent hourly trading volume (GP) for this item
                    # What: Activity metric used to enforce min_volume
                    # Why: Prevents triggering alerts for low-liquidity items
                    # How: Retrieved via get_volume_from_timeseries (DB-backed lookup)
                    volume = self.get_volume_from_timeseries(item_id_str, 0)
                    if volume is None or volume < alert.min_volume:
                        return False
                # =============================================================================
                # BUILD TRIGGERED_DATA FOR SINGLE-ITEM THRESHOLD ALERT
                # =============================================================================
                # What: Create a JSON-serializable dict with all trigger details
                # Why: The alert_detail view and triggered_text() method need this data to
                #      display what triggered the alert (reference price, current price, change %)
                # How: Build dict with same structure as multi-item triggered items for consistency
                # Note: This was previously missing - single-item alerts only returned True/False
                #       without storing any triggered_data, causing display issues
                # =============================================================================
                item_mapping = self.get_item_mapping()
                # item_name: Human-readable name of the item for display
                item_name = item_mapping.get(item_id_str, alert.item_name or f'Item {item_id_str}')
                
                # triggered_item: Dict containing all information about the triggered alert
                # This matches the structure used by multi-item threshold alerts for consistency
                triggered_item = {
                    'item_id': item_id_str,
                    'item_name': item_name,
                    'reference_price': ref_price,
                    'current_price': current_price,
                    'change_percent': round(change_percent, 2),
                    'threshold': threshold_value,
                    'direction': direction
                }
                
                # Store as triggered_data JSON
                # Why: This enables proper display in alert_detail view and triggered_text()
                # Note: We store as a single dict (not a list) for single-item alerts
                #       The view handles both formats (dict for single, list for multi)
                alert.triggered_data = json.dumps(triggered_item)
                
                return True
            
            return False
    
    # =============================================================================
    # COLLECTIVE MOVE ALERT CHECKING
    # =============================================================================
    def check_collective_move_alert(self, alert, all_prices):
        """
        Check if a collective move alert should trigger.
        
        What: Checks if the average percentage change across multiple items meets the threshold
        Why: Users want to be notified when a group of items moves together (e.g., all herbs up 5%)
        How:
            1. Determine the time window (minutes) and reference price type
            2. Update rolling price history per item+reference+time_frame
            3. Compare current price to the price from [time_frame] minutes ago
            4. Compute average change (simple or weighted by baseline value)
            5. Check if average crosses threshold in specified direction
            6. Store top 50 individual item changes in triggered_data for display
        
        Calculation Methods:
            - Simple: arithmetic mean = sum(changes) / count
            - Weighted: weighted mean = sum(change * baseline) / sum(baselines)
              This gives more influence to expensive items
        
        Args:
            alert: Alert model instance with collective_move configuration
            all_prices: Dictionary of all current prices keyed by item_id
        
        Returns:
            - True if alert should trigger (also sets alert.triggered_data)
            - False otherwise
        """
        # =============================================================================
        # GET ALERT CONFIGURATION
        # =============================================================================
        # calculation_method: 'simple' for arithmetic mean, 'weighted' for value-weighted mean
        calculation_method = alert.calculation_method or 'simple'
        # direction: 'up' for increases, 'down' for decreases, 'both' for either
        direction = (alert.direction or 'both').lower()
        # reference_type: Which price to monitor - 'high' (instant sell), 'low' (instant buy), 'average'
        reference_type = alert.reference or 'average'
        # threshold_value: The percentage threshold to trigger (stored in alert.percentage)
        threshold_value = alert.percentage if alert.percentage is not None else 0
        # time_frame_minutes: Rolling window duration (minutes) for baseline comparisons
        # What: Time frame setting for collective move alerts
        # Why: We must compare against the price from X minutes ago
        # How: Read from alert.time_frame and validate
        time_frame_minutes = alert.time_frame
        
        # =============================================================================
        # LOAD REFERENCE PRICES (ITEM SET)
        # =============================================================================
        # reference_prices: Dict mapping item_id -> baseline price stored at alert creation
        # What: Used primarily to preserve the item set for collective move alerts
        # Why: Keeps the alert scoped to the items captured at creation time
        # How: Parse JSON if present; may be empty for older alerts
        reference_prices = {}
        if alert.reference_prices:
            try:
                reference_prices = json.loads(alert.reference_prices)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # =============================================================================
        # VALIDATE TIME FRAME
        # =============================================================================
        # What: Ensure time frame is valid before we attempt rolling window comparisons
        # Why: A missing/invalid time frame makes baseline comparisons impossible
        # How: Validate and return False if missing or <= 0
        try:
            time_frame_minutes = int(time_frame_minutes) if time_frame_minutes is not None else None
        except (TypeError, ValueError):
            time_frame_minutes = None
        
        if not time_frame_minutes or time_frame_minutes <= 0:
            return False
        
        # =============================================================================
        # DETERMINE ITEMS TO CHECK
        # =============================================================================
        # items_to_check: List of item IDs to process
        items_to_check = []
        
        if alert.is_all_items:
            # All items mode: Use reference_prices if available; fallback to all_prices keys
            # What: Use the stored item set if possible, otherwise check all available items
            # Why: Collective move alerts may have been created before baselines were captured
            # How: Prefer reference_prices keys, but fall back to all_prices for resilience
            items_to_check = list(reference_prices.keys()) if reference_prices else list(all_prices.keys())
        elif alert.item_ids:
            # Multi-item mode: Use specific list of items
            try:
                item_ids_list = json.loads(alert.item_ids)
                items_to_check = [str(item_id) for item_id in item_ids_list]
            except (json.JSONDecodeError, TypeError):
                return False
        else:
            # Single item in item_id field - not typical for collective but handle it
            if alert.item_id:
                items_to_check = [str(alert.item_id)]
        
        if not items_to_check:
            return False
        
        # =============================================================================
        # CALCULATE INDIVIDUAL ITEM CHANGES
        # =============================================================================
        # item_changes: List of dicts with change data for each item
        # Each entry: {item_id, item_name, reference_price, current_price, change_percent, baseline_value}
        item_changes = []
        item_mapping = self.get_item_mapping()
        
        # now: Current UNIX timestamp for rolling window operations
        # What: Used to timestamp price history entries
        # Why: Needed for pruning and baseline lookup
        # How: time.time() gives current epoch seconds
        now = time.time()
        
        # warmup_threshold: Minimum age of oldest data point to consider window "warm"
        # What: Oldest data point must be at least [time_frame_minutes] old
        # Why: Avoid triggering until we have a full window for baseline comparisons
        # How: Compare oldest timestamp to this threshold
        warmup_threshold = now - (time_frame_minutes * 60)
        
        # cutoff: Timestamp marking the start of the rolling window for pruning
        # What: Any price data older than this is removed from history
        # Why: Keep memory bounded and prevent stale baselines
        # How: Keep an extra 60-second buffer to avoid pruning before warmup completes
        cutoff = now - (time_frame_minutes * 60) - 60
        
        # sum_weighted_changes: Sum of (change_percent * baseline) for weighted calculation
        sum_weighted_changes = 0.0
        # sum_baselines: Sum of baseline values for weighted calculation divisor
        sum_baselines = 0.0
        # sum_changes: Sum of change percentages for simple calculation
        sum_changes = 0.0
        # valid_count: Number of items with valid price data
        valid_count = 0
        
        for item_id_str in items_to_check:
            # Get price data for this item
            price_data = all_prices.get(item_id_str)
            if not price_data:
                continue
            
            # Apply min/max price filters if configured (for all-items mode)
            if alert.is_all_items:
                high = price_data.get('high')
                low = price_data.get('low')
                
                if alert.minimum_price is not None:
                    if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                        continue
                if alert.maximum_price is not None:
                    if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                        continue
            
            # Get current price based on reference type
            current_price = self._get_price_by_reference(price_data, reference_type)
            if current_price is None:
                continue
            
            # =============================================================================
            # ROLLING WINDOW BASELINE (PRICE HISTORY)
            # =============================================================================
            # key: Unique identifier for item+reference+time_frame
            # What: Ensures different time frames do not prune each other's histories
            # Why: Avoids mixing windows across alerts with different time frames
            # How: Include time_frame_minutes in the key
            key = f"{item_id_str}:{reference_type}:{time_frame_minutes}"
            history = self.price_history[key]
            history.append((now, current_price))
            # Prune old entries outside the window + buffer
            self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]
            window = self.price_history[key]
            
            if not window:
                continue
            
            # Warmup check: Ensure we have data old enough to compare
            oldest_timestamp = window[0][0]
            if oldest_timestamp > warmup_threshold:
                # Still warming up - not enough historical data yet
                continue
            
            # baseline_price: Price at exactly [time_frame] ago (oldest in window)
            # What: Baseline used for percentage comparison
            # Why: Collective move requires comparison to historical price
            # How: Use the oldest entry in the window as the baseline
            baseline_price = window[0][1]
            if baseline_price in (None, 0):
                continue
            
            # Calculate percentage change for this item
            change_percent = self._calculate_percent_change(baseline_price, current_price)
            
            # Get item name for display
            item_name = item_mapping.get(item_id_str, f'Item {item_id_str}')
            
            # Store individual item change data
            item_changes.append({
                'item_id': item_id_str,
                'item_name': item_name,
                'reference_price': baseline_price,
                'current_price': current_price,
                'change_percent': round(change_percent, 2),
                'baseline_value': baseline_price  # Used for weighted calculation display
            })
            
            # Accumulate for average calculation
            sum_changes += change_percent
            sum_weighted_changes += change_percent * baseline_price
            sum_baselines += baseline_price
            valid_count += 1
        
        if valid_count == 0:
            # No valid items to check
            return False
        
        # =============================================================================
        # CALCULATE AVERAGE PERCENTAGE CHANGE
        # =============================================================================
        # average_change: The computed average based on calculation method
        if calculation_method == 'weighted':
            # Weighted average: sum(change * baseline) / sum(baselines)
            # This gives more influence to expensive items
            # Example: If a 1B item moves 10% and a 10K item moves 10%, 
            #          the 1B item contributes much more to the average
            if sum_baselines == 0:
                return False
            average_change = sum_weighted_changes / sum_baselines
        else:
            # Simple average: sum(changes) / count
            # Each item contributes equally regardless of value
            average_change = sum_changes / valid_count
        
        # =============================================================================
        # CHECK IF THRESHOLD IS CROSSED
        # =============================================================================
        # threshold_crossed: Boolean indicating if average meets/exceeds threshold in specified direction
        threshold_crossed = self._check_threshold_crossed(average_change, threshold_value, direction)
        
        if threshold_crossed:
            # =============================================================================
            # BUILD TRIGGERED_DATA
            # =============================================================================
            # What: Create JSON with average change and top individual items
            # Why: The alert_detail view needs this to display what triggered the alert
            # How: Sort items by absolute change, limit to top 50, include summary stats
            
            # Sort items by absolute change percentage (highest first)
            item_changes.sort(key=lambda x: abs(x['change_percent']), reverse=True)
            
            # Limit to top 50 items to prevent huge triggered_data
            # MAX_TRIGGERED_ITEMS: Maximum items to include in triggered_data
            MAX_TRIGGERED_ITEMS = 50
            top_items = item_changes[:MAX_TRIGGERED_ITEMS]
            
            # Determine effective direction of the move
            # effective_direction: 'up' if average is positive, 'down' if negative
            effective_direction = 'up' if average_change >= 0 else 'down'
            
            # Build triggered_data dict
            # triggered_data: JSON object with all information about the triggered alert
            triggered_data = {
                'average_change': round(average_change, 2),
                'calculation_method': calculation_method,
                'direction': direction,
                'effective_direction': effective_direction,
                'threshold': threshold_value,
                'total_items_checked': valid_count,
                'items_in_response': len(top_items),
                'reference_type': reference_type,
                'time_frame_minutes': time_frame_minutes,
                'items': top_items
            }
            
            # Store in alert
            alert.triggered_data = json.dumps(triggered_data)
            
            return True
        
        return False
    
    def _get_price_by_reference(self, price_data, reference_type):
        """
        Get the appropriate price from price_data based on reference type.
        
        What: Extracts high, low, or average price from price_data dict
        Why: Users can choose which price point to monitor for their alerts
        How: Switch on reference_type and calculate/return appropriate value
        
        Args:
            price_data: Dict containing 'high' and 'low' price keys
            reference_type: 'high', 'low', or 'average'
        
        Returns:
            int: The price value, or None if not available
        """
        high = price_data.get('high')
        low = price_data.get('low')
        
        if reference_type == 'high':
            return high
        elif reference_type == 'low':
            return low
        elif reference_type == 'average':
            if high is not None and low is not None:
                return (high + low) // 2
            return high or low
        else:
            return high  # Default to high
    
    def _calculate_percent_change(self, reference_price, current_price):
        """
        Calculate percentage change from reference price to current price.
        
        What: Computes ((current - reference) / reference) * 100
        Why: Threshold alerts need to know how much the price has changed as a percentage
        How: Standard percentage change formula, handles edge cases
        
        Args:
            reference_price: The baseline price (captured at alert creation)
            current_price: The current market price
        
        Returns:
            float: Percentage change (positive for increase, negative for decrease)
        """
        if reference_price == 0 or reference_price is None:
            return 0
        return ((current_price - reference_price) / reference_price) * 100
    
    def _check_threshold_crossed(self, change_percent, threshold, direction):
        """
        Check if a price change crosses the threshold in the specified direction.
        
        What: Determines if change_percent exceeds threshold based on direction
        Why: Different users want alerts for increases vs decreases vs either
        How: 
            - 'up': Change must be >= +threshold (price increased)
            - 'down': Change must be <= -threshold (price decreased)
            - 'both': Absolute change must be >= threshold
        
        Args:
            change_percent: The calculated percentage change
            threshold: The threshold percentage to compare against
            direction: 'up', 'down', or 'both'
        
        Returns:
            bool: True if threshold is crossed in the specified direction
        """
        if direction == 'up':
            return change_percent >= threshold
        elif direction == 'down':
            return change_percent <= -threshold
        else:  # 'both'
            return abs(change_percent) >= threshold
    
    def _handle_multi_item_threshold_trigger(self, alert, triggered_items):
        """
        Handle trigger logic for multi-item/all-items threshold alerts.
        
        What: Processes triggered items for threshold alerts monitoring multiple items
        Why: Multi-item threshold alerts should only fully deactivate when ALL monitored items trigger
        How:
            1. Get the total list of items being monitored
            2. Check if triggered data has meaningfully changed
            3. Compare against currently triggered items
            4. If all items have triggered, deactivate the alert
            5. Otherwise, keep the alert active and update triggered_data
            6. Only send notification if data has changed
        
        Args:
            alert: Alert model instance with threshold configuration
            triggered_items: List of item data dicts that currently meet the threshold
                            (may be empty if no items meet threshold)
        
        Deactivation Logic:
            - Alert stays active until EVERY item has triggered at least once
            - triggered_data shows current items meeting the threshold (updated each check)
            - Only when triggered_items contains ALL monitored items does the alert deactivate
        """
        # Determine total items being monitored
        # total_item_ids: List of all item IDs the alert is meant to monitor
        if alert.is_all_items:
            # For all-items mode, use the reference_prices keys as the monitored items
            # (since reference_prices contains all items that were in range at creation)
            try:
                reference_prices = json.loads(alert.reference_prices) if alert.reference_prices else {}
                total_item_ids = list(reference_prices.keys())
            except (json.JSONDecodeError, TypeError):
                total_item_ids = []
        else:
            try:
                total_item_ids = json.loads(alert.item_ids)
                if not isinstance(total_item_ids, list):
                    total_item_ids = []
                # Convert to strings for comparison
                total_item_ids = [str(x) for x in total_item_ids]
            except (json.JSONDecodeError, TypeError):
                total_item_ids = []
        
        # old_triggered_data: Previous triggered_data for comparison
        old_triggered_data = alert.triggered_data
        
        # Check if data has changed
        data_changed = self._has_triggered_data_changed(old_triggered_data, triggered_items)
        
        # triggered_item_ids: Set of item IDs that triggered in this check cycle
        triggered_item_ids = set(str(item['item_id']) for item in triggered_items)
        
        # total_item_ids_set: Set of all item IDs for comparison
        total_item_ids_set = set(str(item_id) for item_id in total_item_ids)
        
        # Check if ALL items have triggered
        # all_triggered: Boolean indicating if every monitored item has reached the threshold
        all_triggered = len(triggered_items) > 0 and total_item_ids_set.issubset(triggered_item_ids)
        
        # ALWAYS update triggered_data with current snapshot
        alert.triggered_data = json.dumps(triggered_items)
        
        # Only update is_triggered and triggered_at if we have actual triggered items
        if triggered_items:
            alert.is_triggered = True
            alert.triggered_at = timezone.now()
        
        # Only reset is_dismissed if data has changed AND show_notification is enabled
        if data_changed and alert.show_notification:
            alert.is_dismissed = False
        
        if all_triggered:
            # All items have triggered
            # What: Log that all items met the threshold
            # Why: User may want to know when all items have triggered
            # Note: Alert stays active - only user can deactivate manually
            alert.is_active = True
            self.stdout.write(
                self.style.WARNING(
                    f'TRIGGERED (threshold - ALL {len(total_item_ids)} items): Alert stays active'
                )
            )
        else:
            # Some items triggered but not all (or none) - keep alert active
            # What: Keep is_active True to continue monitoring
            # Why: Alert stays active until manually deactivated by user
            alert.is_active = True
            if data_changed and triggered_items:
                self.stdout.write(
                    self.style.WARNING(
                        f'TRIGGERED (threshold): {len(triggered_items)}/{len(total_item_ids)} items triggered'
                    )
                )
            elif data_changed and not triggered_items:
                self.stdout.write(
                    self.style.WARNING(
                        f'Threshold alert {alert.id}: All items dropped below threshold (0/{len(total_item_ids)})'
                    )
                )
            else:
                self.stdout.write(
                    f'Threshold alert {alert.id}: No changes ({len(triggered_items)}/{len(total_item_ids)} items)'
                )
        
        alert.save()
        
        # Only send email notification if data has changed AND notifications are enabled
        # AND there are actually triggered items to report
        if alert.email_notification and data_changed and triggered_items:
            self.send_alert_notification(alert, alert.triggered_text())
            # Disable email notification after first trigger to prevent spam
            # What: Set email_notification to False after sending
            # Why: User only wants to be notified once, but alert stays active for monitoring
            alert.email_notification = False
            alert.save()

    def get_volume_from_timeseries(self, item_id, time_window_minutes):
        """
        Get the most recent hourly volume (in GP) for an item from the database.

        What: Queries the HourlyItemVolume table for the latest volume snapshot of a given item.
        Why: Previously, this method made a live HTTP request to the RuneScape Wiki timeseries
             API for every item being checked. For "all items" sustained alerts, this meant
             hundreds of individual API calls per check cycle. Now, volume data is pre-fetched
             by scripts/update_volumes.py every 1h5m and stored in the database, making this
             a fast DB query instead of a slow HTTP request.
        How: Queries HourlyItemVolume filtered by item_id. The model's Meta.ordering is
             ['-timestamp'], so .first() returns the most recent snapshot. Returns the
             volume field (in GP) or None if no data exists for this item.

        Note: The time_window_minutes parameter is kept in the method signature for backwards
              compatibility with existing callers, but is no longer used. We always return
              the most recent hourly volume when (and only when) the snapshot timestamp is
              within VOLUME_RECENCY_MINUTES of now; stale snapshots return None so min_volume
              filters fail safely on outdated volume data.

        Args:
            item_id: The OSRS item ID to look up volume for
            time_window_minutes: (Unused) Previously used to filter by time window.
                                 Kept for API compatibility with existing callers.

        Returns:
            int: Hourly volume in GP from the most recent HourlyItemVolume record
            None: If no volume data exists for this item (script hasn't run yet,
                  or item was skipped due to missing price data)
        """
        try:
            # latest_volume: The most recent HourlyItemVolume record for this item.
            # Model ordering is ['-timestamp'] so .first() gives the newest entry.
            latest_volume = HourlyItemVolume.objects.filter(item_id=int(item_id)).first()
            if latest_volume:
                # latest_volume_timestamp: Raw timestamp stored on the latest volume snapshot.
                # What: Captures the timestamp value recorded by update_volumes.py (typically
                #       a Unix epoch seconds string, but tests may store ISO-8601 strings).
                # Why: We must validate freshness before trusting min_volume checks.
                # How: Parsed below into a timezone-aware datetime for comparison.
                latest_volume_timestamp = latest_volume.timestamp
                # parsed_volume_timestamp: Parsed, timezone-aware datetime for the snapshot.
                # What: Represents when the latest volume snapshot was recorded.
                # Why: Enables a direct comparison against the allowed recency window.
                # How: Attempt Unix-epoch parsing first; fall back to ISO parsing.
                parsed_volume_timestamp = None
                # What: Parse timestamps stored as Unix epoch seconds (string or numeric).
                # Why: The RuneScape Wiki timeseries API returns Unix timestamps, and
                #      update_volumes.py stores them as-is, so this is the primary format.
                # How: Convert to float and build a UTC-aware datetime.
                try:
                    parsed_volume_timestamp = timezone.datetime.fromtimestamp(
                        float(latest_volume_timestamp),
                        tz=dt_tz.utc,
                    )
                except (TypeError, ValueError, OverflowError):
                    # What: Fall back to ISO-8601 parsing for test fixtures or legacy data.
                    # Why: Some tests insert human-readable timestamps (e.g., "2026-02-06T12:00:00Z").
                    # How: Use Django's parse_datetime and normalize to UTC if needed.
                    parsed_volume_timestamp = parse_datetime(str(latest_volume_timestamp))
                    if parsed_volume_timestamp and timezone.is_naive(parsed_volume_timestamp):
                        parsed_volume_timestamp = timezone.make_aware(
                            parsed_volume_timestamp,
                            dt_tz.utc,
                        )
                # volume_recency_cutoff: Oldest timestamp allowed for volume to be considered current.
                # What: Defines the freshness threshold for hourly volume data.
                # Why: Prevents stale snapshots (e.g., several hours old) from passing min_volume gates.
                # How: Compare parsed_volume_timestamp against "now - VOLUME_RECENCY_MINUTES".
                volume_recency_cutoff = timezone.now() - timedelta(minutes=self.VOLUME_RECENCY_MINUTES)
                # What: Treat missing/invalid timestamps or stale snapshots as "no volume data".
                # Why: Alerts should only pass the min_volume filter if the volume is recent.
                # How: Return None when parsing fails or the timestamp is older than the cutoff.
                if parsed_volume_timestamp is None or parsed_volume_timestamp < volume_recency_cutoff:
                    return None
                return latest_volume.volume
            return None
        except Exception as e:
            # Catch any unexpected DB errors (connection issues, etc.) gracefully.
            # Return None so the alert check can continue without volume data.
            return None


    def check_sustained_alert(self, alert, all_prices):
        """
        Check if a sustained move alert should be triggered.
        
        Supports:
        - Single item (item_id set)
        - Multiple specific items (sustained_item_ids JSON array)
        - All items (is_all_items=True, with optional min/max price filter)
        
        Returns True if triggered, or a list of matching items for all-items alerts.
        """
        # Get required parameters
        time_window_minutes = alert.time_frame  # Use dedicated time_frame field
        min_moves = alert.min_consecutive_moves
        min_move_pct = alert.min_move_percentage
        vol_buffer_size = alert.volatility_buffer_size
        vol_multiplier = alert.volatility_multiplier
        min_volume = alert.min_volume
        direction = (alert.direction or 'both').lower()
        min_pressure_strength = alert.min_pressure_strength
        min_pressure_spread_pct = alert.min_pressure_spread_pct
        
        if not all([time_window_minutes, min_moves, min_move_pct, vol_buffer_size, vol_multiplier]):
            return False
        
        # Determine which items to check
        items_to_check = []
        
        if alert.is_all_items:
            # All items - filter by min/max price if set
            for item_id, price_data in all_prices.items():
                high = price_data.get('high')
                low = price_data.get('low')
                if high is None or low is None:
                    continue
                avg_price = (high + low) / 2
                
                # Apply price filters
                if alert.minimum_price is not None and avg_price < alert.minimum_price:
                    continue
                if alert.maximum_price is not None and avg_price > alert.maximum_price:
                    continue
                
                items_to_check.append(int(item_id))
        elif alert.sustained_item_ids:
            # Multiple specific items
            try:
                items_to_check = json.loads(alert.sustained_item_ids)
            except:
                items_to_check = []
        elif alert.item_id:
            # Single item
            items_to_check = [alert.item_id]
        
        if not items_to_check:
            return False
        
        now = time.time()
        triggered_items = []
        
        for item_id in items_to_check:
            result = self._check_sustained_for_item(
                alert, item_id, all_prices, now,
                time_window_minutes, min_moves, min_move_pct,
                vol_buffer_size, vol_multiplier, min_volume, direction,
                min_pressure_strength, min_pressure_spread_pct
            )
            if result:
                triggered_items.append(result)
        
        if not triggered_items:
            return False
        
        # For single item alerts, return True
        if not alert.is_all_items and len(items_to_check) == 1:
            alert.triggered_data = json.dumps(triggered_items[0])
            return True
        
        # For multi-item or all-items, return the list
        alert.triggered_data = json.dumps(triggered_items)
        return triggered_items if alert.is_all_items else True
    
    def _check_sustained_for_item(self, alert, item_id, all_prices, now,
                                   time_window_minutes, min_moves, min_move_pct,
                                   vol_buffer_size, vol_multiplier, min_volume, direction,
                                   min_pressure_strength=None, min_pressure_spread_pct=None):
        """
        Check sustained move conditions for a single item.
        Returns trigger data dict if triggered, None otherwise.
        
        What: Evaluates whether a single item meets the sustained move conditions
        Why: Sustained alerts can track multiple items; this checks one at a time
        How: Compares current price against historical state, tracking consecutive moves
        """
        price_data = all_prices.get(str(item_id))
        if not price_data:
            return None
        
        high = price_data.get('high')
        low = price_data.get('low')
        if high is None or low is None:
            return None
        
        # =============================================================================
        # DETERMINE CURRENT PRICE BASED ON REFERENCE TYPE
        # =============================================================================
        # What: Get the current price using the alert's reference type setting
        # Why: Users can choose to monitor high (instant buy), low (instant sell), or average price
        # How: Check alert.reference and use the appropriate price from the API data
        # Note: Default to average for backwards compatibility with existing alerts
        # =============================================================================
        reference_type = alert.reference or 'average'
        if reference_type == 'high':
            current_price = high
        elif reference_type == 'low':
            current_price = low
        else:
            # 'average' or any other value defaults to average
            current_price = (high + low) / 2
        
        # State key includes both alert ID and item ID for multi-item support
        state_key = f"{alert.id}:{item_id}"
        
        if state_key not in self.sustained_state:
            self.sustained_state[state_key] = {
                'last_price': current_price,
                'streak_count': 0,
                'streak_direction': None,
                'streak_start_time': now,
                'streak_start_price': current_price,
                'volatility_buffer': []
            }
            return None  # Need at least one previous price to compare

        
        state = self.sustained_state[state_key]
        last_price = state['last_price']
        
        if last_price == 0:
            state['last_price'] = current_price
            return None
        
        price_change_pct = ((current_price - last_price) / last_price) * 100
        abs_change = abs(price_change_pct)
        
        # Always update volatility buffer
        state['volatility_buffer'].append(abs_change)
        if len(state['volatility_buffer']) > vol_buffer_size:
            state['volatility_buffer'] = state['volatility_buffer'][-vol_buffer_size:]
        
        state['last_price'] = current_price
        
        # Determine move direction
        if price_change_pct > 0:
            move_dir = 'up'
        elif price_change_pct < 0:
            move_dir = 'down'
        else:
            move_dir = None
        
        # Check if this move counts
        if abs_change >= min_move_pct and move_dir:
            if state['streak_direction'] == move_dir:
                state['streak_count'] += 1
            elif state['streak_direction'] is None:
                state['streak_count'] = 1
                state['streak_direction'] = move_dir
                state['streak_start_time'] = now
                state['streak_start_price'] = last_price
            else:
                state['streak_count'] = 1
                state['streak_direction'] = move_dir
                state['streak_start_time'] = now
                state['streak_start_price'] = last_price
        
        
        # Check time window
        streak_duration = now - state['streak_start_time']
        if streak_duration > (time_window_minutes * 60):
            state['streak_count'] = 0
            state['streak_direction'] = None
            return None
        
        if state['streak_count'] < min_moves:
            return None
        
        if direction != 'both' and state['streak_direction'] != direction:
            return None
        
        # Check volume
        # =============================================================================
        # DEBUG: Volume check diagnostics
        # What: Log volume lookup details to diagnose sustained alert volume issues
        # Why: After migrating from API-based volume (units) to DB-based volume (GP),
        #      alerts may fail silently if min_volume thresholds are mismatched or
        #      if no HourlyItemVolume records exist for the item
        # =============================================================================
        volume = 0
        if min_volume:
            volume = self.get_volume_from_timeseries(item_id, time_window_minutes)
            if volume is None:
                return None
            if volume < min_volume:
                return None
        else:
            volume = self.get_volume_from_timeseries(item_id, time_window_minutes) or 0
        
        # Volatility check
        if len(state['volatility_buffer']) < 5:
            return None
        
        avg_volatility = sum(state['volatility_buffer']) / len(state['volatility_buffer'])
        required_move = vol_multiplier * avg_volatility
        
        streak_start_price = state['streak_start_price']
        if streak_start_price == 0:
            return None
        total_move_pct = abs((current_price - streak_start_price) / streak_start_price * 100)
        
        
        if total_move_pct < required_move:
            return None
        
        # Market pressure filter check
        pressure_direction = None
        pressure_strength = None
        if min_pressure_strength:
            high_time = price_data.get('highTime')
            low_time = price_data.get('lowTime')
            
            # Determine pressure direction: BUY if highTime > lowTime, SELL if lowTime > highTime
            if high_time and low_time:
                if high_time > low_time:
                    pressure_direction = 'buy'  # Recent buy = upward pressure
                elif low_time > high_time:
                    pressure_direction = 'sell'  # Recent sell = downward pressure
                
                # Calculate time delta and spread percentage
                time_delta = abs(high_time - low_time)
                spread_pct = ((high - low) / low * 100) if low > 0 else 0
                
                # Determine pressure strength based on time_delta
                if time_delta < 60:
                    pressure_strength = 'strong'
                elif time_delta < 300:
                    pressure_strength = 'moderate'
                else:
                    pressure_strength = 'weak'
                
                # Check if spread meets threshold (if configured)
                spread_ok = True
                if min_pressure_spread_pct and spread_pct < min_pressure_spread_pct:
                    spread_ok = False
                
                # Check if pressure strength meets minimum requirement
                strength_order = {'weak': 1, 'moderate': 2, 'strong': 3}
                required_strength = strength_order.get(min_pressure_strength, 0)
                actual_strength = strength_order.get(pressure_strength, 0)
                strength_ok = actual_strength >= required_strength
                
                # Pressure direction must match streak direction
                # BUY pressure = expecting UP movement, SELL pressure = expecting DOWN movement
                direction_match = (
                    (pressure_direction == 'buy' and state['streak_direction'] == 'up') or
                    (pressure_direction == 'sell' and state['streak_direction'] == 'down')
                )
                
                # All pressure conditions must be met
                if not (spread_ok and strength_ok and direction_match):
                    return None
        
        # TRIGGERED!
        item_mapping = self.get_item_mapping()
        item_name = item_mapping.get(str(item_id), f'Item {item_id}')
        
        trigger_data = {
            'item_id': item_id,
            'item_name': item_name,
            'streak_direction': state['streak_direction'],
            'streak_count': state['streak_count'],
            'total_move_percent': round(total_move_pct, 4),
            'start_price': streak_start_price,
            'current_price': current_price,
            'volume': volume,
            'avg_volatility': round(avg_volatility, 4),
            'required_move': round(required_move, 4),
            'time_window_minutes': time_window_minutes,
            'pressure_direction': pressure_direction,
            'pressure_strength': pressure_strength
        }
        
        
        # Reset streak after trigger
        state['streak_count'] = 0
        state['streak_direction'] = None
        
        return trigger_data

    # =============================================================================
    # FLIP CONFIDENCE ALERT METHODS
    # =============================================================================

    # TIMESTEP_SECONDS: Maps user-facing timestep labels to the API 'timestep' parameter
    # What: Lookup table converting timestep choices to the value the OSRS Wiki API expects
    # Why: The OSRS Wiki API timeseries endpoint accepts specific timestep values (5m, 1h, 6h)
    # How: Used by fetch_timeseries_data to construct the API URL
    TIMESTEP_API_VALUES = {
        '5m': '5m',
        '1h': '1h',
        '6h': '6h',
        '24h': '6h',  # Wiki API doesn't have 24h; use 6h with more lookback
    }

    # TIMESTEP_TO_SECONDS: Maps timestep labels to their duration in seconds
    # What: Converts timestep labels to seconds for calculating time ranges
    # Why: Needed to compute the 'start' timestamp when querying the timeseries API
    # How: lookback_seconds = timestep_seconds * lookback_count
    TIMESTEP_TO_SECONDS = {
        '5m': 300,
        '1h': 3600,
        '6h': 21600,
        '24h': 86400,
    }

    # TIMESTEP_TO_MODEL: Maps timestep labels to the Django model that stores cached
    # timeseries data for that resolution.
    # What: Lookup table from timestep string -> Django ORM model class
    # Why: The flip confidence alert originally made individual HTTP requests to the
    #       OSRS Wiki API for every item being checked. For "all items" alerts, this meant
    #       ~4,400 HTTP requests per check cycle (~37 minutes). By caching timeseries data
    #       in the database (populated by scripts/get-all-volume.py), we replace those HTTP
    #       calls with fast DB queries. This dict maps each timestep to the correct model.
    # How: Each timestep key ('5m', '1h', '6h', '24h') maps to a model class that has the
    #       same schema: item_id, item_name, avg_high_price, avg_low_price, high_price_volume,
    #       low_price_volume, timestamp. Models that don't exist yet are set to None, which
    #       triggers a fallback to the HTTP API in fetch_timeseries_from_db().
    # Note: Currently only FiveMinTimeSeries exists (despite its name, it stores 1h data).
    #        When OneHourTimeSeries, SixHourTimeSeries, TwentyFourHourTimeSeries are created,
    #        update this mapping to point to the correct model classes.
    TIMESTEP_TO_MODEL = {
        '5m': FiveMinTimeSeries,   # Currently stores 1h data (used as the default model)
        '1h': FiveMinTimeSeries,   # Same model — 1h data is what's actually cached here
        '6h': None,                # Not yet created — will fall back to HTTP API
        '24h': None,               # Not yet created — will fall back to HTTP API
    }

    def fetch_timeseries_from_db(self, item_id, timestep, lookback_count):
        """
        Fetch timeseries data from the local database instead of the OSRS Wiki HTTP API.

        What: Retrieves price history (avgHighPrice, avgLowPrice, highPriceVolume,
              lowPriceVolume) for a given item from the cached timeseries tables in the
              database, formatted identically to the OSRS Wiki API response so that
              compute_flip_confidence() can consume it without modification.

        Why: The original fetch_timeseries_data() made individual HTTP requests to the
             OSRS Wiki API for every item. For "all items" flip confidence alerts (~4,400
             items), this took ~37 minutes per check cycle, causing the entire alert loop
             to hang. By reading from pre-cached database tables (populated by
             scripts/get-all-volume.py), we reduce this to fast SQL queries that complete
             in milliseconds per item.

        How:
            1. Looks up the correct Django model for the given timestep via TIMESTEP_TO_MODEL
            2. If no model exists for that timestep, falls back to the HTTP API method
            3. Queries the model for all rows matching the item_id, ordered by timestamp
               descending (newest first), limited to lookback_count rows
            4. Deduplicates by timestamp — if the same item has multiple rows with the same
               timestamp (e.g., from duplicate script runs), only the first (most recent by
               insertion order) is kept
            5. Converts Django model field names (snake_case) to the camelCase format that
               compute_flip_confidence() expects (e.g., avg_high_price -> avgHighPrice)
            6. Reverses the list to chronological order (oldest first) to match the API format
            7. For '24h' timestep, samples every 4th point from 6h data (same as the API method)

        Args:
            item_id: The OSRS item ID to fetch data for (int or string).
            timestep: The time bucket size ('5m', '1h', '6h', '24h').
            lookback_count: Number of unique time buckets to return.

        Returns:
            list: List of dicts with keys avgHighPrice, avgLowPrice, highPriceVolume,
                  lowPriceVolume, timestamp. Ordered chronologically (oldest first).
                  Empty list if no data is found or the model doesn't exist and API
                  fallback also fails.
        """
        # model_class: The Django ORM model that stores timeseries data for this timestep.
        # None means no model exists yet for this resolution, so we fall back to HTTP API.
        model_class = self.TIMESTEP_TO_MODEL.get(timestep)

        if model_class is None:
            # No DB model for this timestep — fall back to HTTP API
            # This ensures the system still works for timesteps where we haven't yet
            # created a database table (e.g., 6h, 24h).
            print(f"[FLIP CONFIDENCE DB] No DB model for timestep '{timestep}', "
                  f"falling back to HTTP API for item {item_id}")
            return self.fetch_timeseries_data(item_id, timestep, lookback_count)

        try:
            # effective_lookback: How many rows to fetch from the DB.
            # For '24h' timestep, we need 4x more rows because we'll sample every 4th
            # point to simulate daily data from 6h-resolution data (matching the API method).
            effective_lookback = lookback_count * 4 if timestep == '24h' else lookback_count

            # db_rows: QuerySet of timeseries rows for this item, ordered newest-first
            # (via Meta.ordering = ['-timestamp']), limited to the effective lookback count.
            # We fetch more rows than needed to account for deduplication removing some.
            # The extra 20% buffer (int(... * 1.2) + 5) ensures we have enough unique
            # timestamps even if there are scattered duplicates.
            fetch_limit = int(effective_lookback * 1.2) + 5
            db_rows = model_class.objects.filter(
                item_id=int(item_id)
            )[:fetch_limit]

            # seen_timestamps: Set used to track which timestamps we've already included,
            # ensuring each time bucket appears only once in the result.
            # Why: The user confirmed that duplicate timestamps can occur (e.g., from
            #       overlapping script runs), and we should only use one entry per timestamp.
            seen_timestamps = set()

            # result: List of data dicts in the format compute_flip_confidence() expects,
            # built by converting Django model fields (snake_case) to API-style camelCase.
            # Accumulated in reverse-chronological order (newest first) then reversed.
            result = []

            for row in db_rows:
                # ts: The timestamp string for this row, used as the deduplication key
                ts = row.timestamp

                # Skip duplicate timestamps — only use the first occurrence (newest by
                # insertion order) for each unique timestamp
                if ts in seen_timestamps:
                    continue
                seen_timestamps.add(ts)

                # Convert Django model field names to the camelCase format that
                # compute_flip_confidence() expects. This mapping matches the OSRS Wiki
                # API response format exactly:
                #   avg_high_price  -> avgHighPrice  (average instant-buy price)
                #   avg_low_price   -> avgLowPrice   (average instant-sell price)
                #   high_price_volume -> highPriceVolume (instant-buy trade count)
                #   low_price_volume  -> lowPriceVolume  (instant-sell trade count)
                result.append({
                    'avgHighPrice': row.avg_high_price,
                    'avgLowPrice': row.avg_low_price,
                    'highPriceVolume': row.high_price_volume,
                    'lowPriceVolume': row.low_price_volume,
                    'timestamp': ts,
                })

                # Stop once we have enough unique data points
                if len(result) >= effective_lookback:
                    break

            # Reverse to chronological order (oldest first) — this matches the format
            # returned by the OSRS Wiki API and expected by compute_flip_confidence().
            result.reverse()

            # For '24h' timestep, sample every 4th point from the data to simulate
            # daily resolution from hourly data. This matches the behavior of the
            # original HTTP API method (which used 6h API data sampled every 4th point).
            if timestep == '24h':
                result = result[::4]

            # Trim to exactly lookback_count points (the sampling or dedup buffer
            # may have produced slightly more or fewer than needed)
            result = result[-lookback_count:]

            return result

        except Exception as e:
            # On any DB error, fall back to the HTTP API as a safety net
            print(f"[FLIP CONFIDENCE DB] Error querying DB for item {item_id}: {e}, "
                  f"falling back to HTTP API")
            return self.fetch_timeseries_data(item_id, timestep, lookback_count)

    def fetch_timeseries_data(self, item_id, timestep, lookback_count):
        """
        Fetch timeseries data from the OSRS Wiki API for a single item.

        What: Retrieves price history (avgHighPrice, avgLowPrice, highPriceVolume,
              lowPriceVolume) for a given item over a specified time window.
        Why: The flip confidence score requires historical time-series data to compute
             trend, pressure, spread, volume, and stability sub-scores.
        How: Constructs a GET request to the OSRS Wiki timeseries endpoint with the
             appropriate timestep parameter, then returns the data array.

        Args:
            item_id: The OSRS item ID to fetch data for.
            timestep: The time bucket size (e.g., '5m', '1h', '6h', '24h').
            lookback_count: Number of time buckets to include.

        Returns:
            list: List of dicts with keys avgHighPrice, avgLowPrice, highPriceVolume,
                  lowPriceVolume, timestamp. Empty list on error or no data.
        """
        try:
            # api_timestep: The actual timestep value to pass to the API
            # Note: '24h' maps to '6h' since the Wiki API doesn't support 24h timestep
            api_timestep = self.TIMESTEP_API_VALUES.get(timestep, '1h')

            # Build the API URL with item ID and timestep
            url = f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={api_timestep}&id={item_id}'

            response = requests.get(
                url,
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'},
                timeout=10
            )

            if response.status_code != 200:
                return []

            data = response.json()
            if 'data' not in data or not data['data']:
                return []

            # timeseries: Raw list of data points from the API, sorted oldest-first
            timeseries = data['data']

            # For '24h' timestep, we need to aggregate 6h buckets into 24h buckets
            # by taking every 4th point. This approximates daily data from 6-hourly data.
            if timestep == '24h':
                timeseries = timeseries[::4]

            # Return only the last lookback_count data points
            # Why: We only need the most recent N buckets for the confidence calculation
            return timeseries[-lookback_count:]

        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            self.stdout.write(self.style.ERROR(
                f'Error fetching timeseries for item {item_id}: {e}'
            ))
            return []

    def check_flip_confidence_alert(self, alert, all_prices):
        """
        Check if a flip confidence alert should trigger.

        What: Evaluates item(s) by computing their flip confidence scores and comparing
              against the user's configured threshold and trigger rule.
        Why: Users want to be notified when items become good flipping candidates based
             on a multi-factor confidence score that considers trend, pressure, spread,
             volume sufficiency, and price stability.
        How:
            1. Validate alert configuration (timestep, lookback, threshold)
            2. Determine which items to check (single, multi, or all)
            3. For each item:
               a. Check cooldown period
               b. Check evaluation interval
               c. Fetch timeseries data from OSRS Wiki API
               d. Apply pre-filters (min spread, min volume)
               e. Compute flip confidence score via compute_flip_confidence()
               f. Apply trigger rule (crosses_above or delta_increase)
               g. Track sustained condition if configured
            4. Return triggered items list or True/False

        Args:
            alert: Alert model instance with flip_confidence configuration
            all_prices: Dictionary of all current prices keyed by item_id

        Returns:
            - List of triggered item dicts for multi-item/all-items alerts
            - True/False for single-item alerts
        """
        # =============================================================================
        # VALIDATE ALERT CONFIGURATION
        # =============================================================================
        # timestep: The time bucket granularity for the timeseries API call
        timestep = alert.confidence_timestep or '1h'
        # lookback: Number of time buckets to analyze (must be >= 3)
        lookback = alert.confidence_lookback or 24
        if lookback < 3:
            lookback = 3
        # threshold: The confidence score threshold for triggering
        threshold = alert.confidence_threshold
        if threshold is None:
            return False
        # trigger_rule: How to compare the score against the threshold
        trigger_rule = alert.confidence_trigger_rule or 'crosses_above'
        # cooldown_minutes: How long to wait before re-alerting on the same item
        cooldown_minutes = alert.confidence_cooldown or 0
        # sustained_count: Number of consecutive passing evaluations required
        sustained_count = alert.confidence_sustained_count or 1
        # eval_interval: Minutes between evaluations
        eval_interval = alert.confidence_eval_interval or 0
        # min_spread_pct: Minimum spread percentage to consider an item
        min_spread_pct = alert.confidence_min_spread_pct
        # min_vol: Minimum total GP volume across the lookback window
        # What: The gold-piece threshold below which items are filtered out
        # Why: GP-based volume is more meaningful than raw trade counts since it
        #      normalises across price tiers (cheap vs expensive items)
        # How: Compared against sum of (qty * price) for all buys and sells
        min_vol = alert.confidence_min_volume

        # Build custom weights dict if any are set, otherwise None for defaults
        weights = None
        if any([
            alert.confidence_weight_trend is not None,
            alert.confidence_weight_pressure is not None,
            alert.confidence_weight_spread is not None,
            alert.confidence_weight_volume is not None,
            alert.confidence_weight_stability is not None,
        ]):
            weights = {
                'trend': alert.confidence_weight_trend if alert.confidence_weight_trend is not None else 0.35,
                'pressure': alert.confidence_weight_pressure if alert.confidence_weight_pressure is not None else 0.25,
                'spread': alert.confidence_weight_spread if alert.confidence_weight_spread is not None else 0.20,
                'volume': alert.confidence_weight_volume if alert.confidence_weight_volume is not None else 0.10,
                'stability': alert.confidence_weight_stability if alert.confidence_weight_stability is not None else 0.10,
            }

        # =============================================================================
        # LOAD PERSISTENT STATE (last scores, consecutive counts, eval times)
        # =============================================================================
        # last_scores: Per-item state dict tracking score history for trigger rules
        last_scores = {}
        if alert.confidence_last_scores:
            try:
                last_scores = json.loads(alert.confidence_last_scores)
            except (json.JSONDecodeError, TypeError):
                last_scores = {}

        # =============================================================================
        # DETERMINE ITEMS TO CHECK
        # =============================================================================
        items_to_check = []
        item_mapping = self.get_item_mapping()

        if alert.is_all_items:
            # All items mode: check every item in the market (with price filters)
            # pre_filter_count: Tracks how many items were filtered out during pre-filtering,
            # used for debug output to show the effectiveness of pre-filters.
            pre_filter_count = 0
            for item_id_str, price_data in all_prices.items():
                high = price_data.get('high')
                low = price_data.get('low')
                if high is None or low is None:
                    continue
                # Apply min/max price filters if configured
                if alert.minimum_price is not None and (high < alert.minimum_price or low < alert.minimum_price):
                    pre_filter_count += 1
                    continue
                if alert.maximum_price is not None and (high > alert.maximum_price or low > alert.maximum_price):
                    pre_filter_count += 1
                    continue

                # =============================================================================
                # EARLY SPREAD PRE-FILTER (for is_all_items mode only)
                # =============================================================================
                # What: Skips items whose current spread is below the minimum threshold
                #        BEFORE making any DB queries or computing confidence scores.
                # Why: For "all items" alerts, there can be ~4,400 items. Many will have
                #       tiny spreads that would fail the per-item spread check later anyway.
                #       By filtering here using already-available all_prices data, we avoid
                #       unnecessary DB queries and confidence score computations.
                # How: Calculates current_spread = ((high - low) / low) * 100 and compares
                #       against min_spread_pct. Items below the threshold are skipped.
                if min_spread_pct is not None and min_spread_pct > 0 and low > 0:
                    current_spread = ((high - low) / low) * 100
                    if current_spread < min_spread_pct:
                        pre_filter_count += 1
                        continue

                items_to_check.append(item_id_str)

            # Debug output showing the pre-filter effectiveness for all-items mode
            print(f"[FLIP CONFIDENCE] is_all_items pre-filter: "
                  f"{len(items_to_check)} items passed, {pre_filter_count} filtered out "
                  f"(from {len(all_prices)} total)")
        elif alert.item_ids:
            # Multi-item mode: check specific list of items
            try:
                items_to_check = [str(x) for x in json.loads(alert.item_ids)]
            except (json.JSONDecodeError, TypeError):
                items_to_check = []
        elif alert.item_id:
            # Single-item mode
            items_to_check = [str(alert.item_id)]

        if not items_to_check:
            return False

        # now_ts: Current Unix timestamp for cooldown and eval interval checks
        now_ts = time.time()
        # triggered_items: List of items that meet all trigger conditions
        triggered_items = []
        # state_changed: Whether we need to save updated last_scores
        state_changed = False

        # loop_start_time: Timestamp when the per-item loop begins, used for debug
        # output showing total processing time for all items.
        loop_start_time = time.time()
        # items_processed: Counter for how many items were actually evaluated (not skipped
        # by cooldown/interval checks), used for debug output.
        items_processed = 0
        # items_skipped: Counter for items skipped due to cooldown or eval interval
        items_skipped = 0

        print(f"[FLIP CONFIDENCE] Starting per-item evaluation for {len(items_to_check)} items "
              f"(alert #{alert.id}, timestep={timestep}, lookback={lookback}, threshold={threshold})")

        for item_id_str in items_to_check:
            # =============================================================================
            # PER-ITEM STATE: Load previous score, consecutive count, and last eval time
            # =============================================================================
            item_state = last_scores.get(item_id_str, {})
            # prev_score: The last computed confidence score for this item
            prev_score = item_state.get('score')
            # consecutive: How many consecutive evaluations this item has passed
            consecutive = item_state.get('consecutive', 0)
            # last_eval: Unix timestamp of the last evaluation for this item
            last_eval = item_state.get('last_eval', 0)

            # =============================================================================
            # CHECK EVALUATION INTERVAL: Skip if checked too recently
            # =============================================================================
            if eval_interval > 0 and last_eval > 0:
                elapsed_minutes = (now_ts - last_eval) / 60
                if elapsed_minutes < eval_interval:
                    items_skipped += 1
                    continue  # Too soon, skip this item

            # =============================================================================
            # CHECK COOLDOWN: Skip if recently triggered
            # =============================================================================
            # last_triggered_ts: Unix timestamp when this item last triggered the alert
            last_triggered_ts = item_state.get('last_triggered', 0)
            if cooldown_minutes > 0 and last_triggered_ts > 0:
                elapsed_since_trigger = (now_ts - last_triggered_ts) / 60
                if elapsed_since_trigger < cooldown_minutes:
                    items_skipped += 1
                    continue  # Still in cooldown, skip

            # =============================================================================
            # PRE-FILTER: Check current spread percentage against minimum
            # =============================================================================
            if min_spread_pct is not None and min_spread_pct > 0:
                price_data = all_prices.get(item_id_str)
                if price_data:
                    high = price_data.get('high')
                    low = price_data.get('low')
                    if high and low and low > 0:
                        current_spread = ((high - low) / low) * 100
                        if current_spread < min_spread_pct:
                            # Update state to reflect this check even if skipped
                            item_state['last_eval'] = now_ts
                            item_state['consecutive'] = 0
                            last_scores[item_id_str] = item_state
                            state_changed = True
                            continue

            # =============================================================================
            # FETCH TIMESERIES DATA FROM LOCAL DATABASE (with HTTP API fallback)
            # =============================================================================
            # What: Retrieves price history from the local DB instead of the OSRS Wiki API.
            # Why: The original HTTP API approach made individual requests per item (~4,400
            #       for "all items" alerts), taking ~37 minutes. DB queries are near-instant.
            # How: fetch_timeseries_from_db() queries the appropriate timeseries model,
            #       deduplicates by timestamp, converts field names to API format, and
            #       falls back to the HTTP API if no DB model exists for the timestep.
            timeseries_data = self.fetch_timeseries_from_db(item_id_str, timestep, lookback)
            if not timeseries_data or len(timeseries_data) < 3:
                # Not enough data points; reset consecutive counter
                item_state['last_eval'] = now_ts
                item_state['consecutive'] = 0
                last_scores[item_id_str] = item_state
                state_changed = True
                continue

            # =============================================================================
            # PRE-FILTER: Check minimum GP volume across the lookback window
            # =============================================================================
            # What: Computes the total gold-piece value of all trades in the lookback
            #       window and skips items that fall below the user's threshold
            # Why: GP volume is a better activity proxy than raw trade count because it
            #      normalises across price tiers — 500 trades of a 10gp item (5,000 GP)
            #      is negligible, while 500 trades of a 10M item (5B GP) is massive.
            # How: For each timeseries bucket, multiply trade count by average price:
            #        gp_vol = SUM(highPriceVolume * avgHighPrice + lowPriceVolume * avgLowPrice)
            #      If the total is below min_vol, the item is skipped entirely.
            if min_vol is not None and min_vol > 0:
                # total_gp_vol: The sum of (quantity * price) for every buy and sell
                #               across all timeseries buckets in the lookback window
                total_gp_vol = sum(
                    (p.get('highPriceVolume') or 0) * (p.get('avgHighPrice') or 0)
                    + (p.get('lowPriceVolume') or 0) * (p.get('avgLowPrice') or 0)
                    for p in timeseries_data
                )
                if total_gp_vol < min_vol:
                    item_state['last_eval'] = now_ts
                    item_state['consecutive'] = 0
                    last_scores[item_id_str] = item_state
                    state_changed = True
                    continue

            # =============================================================================
            # COMPUTE FLIP CONFIDENCE SCORE
            # =============================================================================
            score = compute_flip_confidence(timeseries_data, weights=weights)
            items_processed += 1

            # =============================================================================
            # APPLY TRIGGER RULE
            # =============================================================================
            # passed: Whether this item's score meets the trigger condition
            passed = False

            if trigger_rule == 'delta_increase':
                # Delta increase rule: score increased by >= threshold since last check
                if prev_score is not None:
                    delta = score - prev_score
                    if delta >= threshold:
                        passed = True
            else:
                # Default: crosses_above rule: score >= threshold
                if score >= threshold:
                    passed = True

            # Update the stored score for next comparison
            item_state['score'] = score
            item_state['last_eval'] = now_ts

            if passed:
                # Increment consecutive counter
                item_state['consecutive'] = consecutive + 1

                # Check sustained condition: must pass N consecutive times
                if item_state['consecutive'] >= sustained_count:
                    # TRIGGERED! Reset consecutive counter and set last_triggered
                    item_state['last_triggered'] = now_ts

                    # item_name: Human-readable name for display
                    item_name = item_mapping.get(item_id_str, f'Item {item_id_str}')

                    triggered_items.append({
                        'item_id': item_id_str,
                        'item_name': item_name,
                        'confidence_score': score,
                        'previous_score': prev_score,
                        'trigger_rule': trigger_rule,
                        'threshold': threshold,
                        'consecutive_passes': item_state['consecutive'],
                    })
            else:
                # Reset consecutive counter on failure
                item_state['consecutive'] = 0

            last_scores[item_id_str] = item_state
            state_changed = True

        # =============================================================================
        # DEBUG: Per-item loop timing summary
        # =============================================================================
        # loop_elapsed: Total seconds spent in the per-item evaluation loop
        loop_elapsed = time.time() - loop_start_time
        print(f"[FLIP CONFIDENCE] Evaluation complete for alert #{alert.id}: "
              f"{items_processed} items scored, {items_skipped} skipped (cooldown/interval), "
              f"{len(triggered_items)} triggered, took {loop_elapsed:.2f}s")

        # =============================================================================
        # SAVE UPDATED STATE
        # =============================================================================
        if state_changed:
            alert.confidence_last_scores = json.dumps(last_scores)
            alert.save(update_fields=['confidence_last_scores'])

        # =============================================================================
        # RETURN RESULTS
        # =============================================================================
        if alert.item_id and not alert.is_all_items and not alert.item_ids:
            # Single-item mode: return True/False
            if triggered_items:
                # Store triggered data for display
                alert.triggered_data = json.dumps(triggered_items[0])
                alert.save(update_fields=['triggered_data'])
                return True
            return False
        else:
            # Multi-item or all-items mode: return list
            if triggered_items:
                triggered_items.sort(key=lambda x: x['confidence_score'], reverse=True)
            return triggered_items

    def send_alert_notification(self, alert, triggered_text):
        """
        Send email/SMS notification when an alert is triggered.
        
        What: Sends an email to notify user of triggered alert (works with email-to-SMS gateways)
        Why: Users need to be notified even when not viewing the website
        How: Uses Django's send_mail with the alert's triggered_text as content
        """
        # Skip if not configured
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            self.stdout.write(self.style.WARNING('Email not configured - skipping notification'))
            return
        if not self.ALERT_RECIPIENT:
            self.stdout.write(self.style.WARNING('ALERT_RECIPIENT not set - skipping notification'))
            return
            
        try:
            send_mail(
                subject='Alert Triggered',
                message=triggered_text,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.ALERT_RECIPIENT],
                fail_silently=False
            )
            self.stdout.write(self.style.SUCCESS(f'Notification sent for alert: {alert}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to send notification: {e}'))

    # =============================================================================
    # DUMP ALERT: EWMA HELPER FUNCTIONS
    # =============================================================================

    def _compute_ewma_alpha(self, halflife_minutes):
        """
        Convert an EWMA half-life (in minutes) to the smoothing factor alpha.

        What: Returns the alpha value such that the EWMA halves its weight
              every 'halflife_minutes' minutes, with 5-minute buckets.
        Why: EWMA alpha controls how fast the moving average adapts;
             derived from half-life for intuitive user configuration.
        How: alpha = 1 - exp(ln(0.5) / (halflife_minutes / 5))
             where 5 is the bucket size in minutes.

        Args:
            halflife_minutes: Half-life in minutes (e.g., 120 = 2 hours).

        Returns:
            float: Alpha in (0, 1]. Returns 1.0 if halflife <= 0.
        """
        if halflife_minutes is None or halflife_minutes <= 0:
            return 1.0
        # halflife_buckets: Number of 5-minute buckets that make up the half-life
        halflife_buckets = halflife_minutes / 5.0
        return 1.0 - math.exp(math.log(0.5) / halflife_buckets)

    def _update_ewma(self, current_ewma, new_value, alpha):
        """
        Update a single EWMA value with a new observation.

        What: Returns the updated EWMA after incorporating new_value.
        Why: Core building block for all EWMA calculations (fair, variance, volume).
        How: If current_ewma is None (first observation), returns new_value;
             otherwise returns (1 - alpha) * current_ewma + alpha * new_value.

        Args:
            current_ewma: Previous EWMA value, or None if uninitialized.
            new_value: The new observation to incorporate.
            alpha: Smoothing factor in (0, 1].

        Returns:
            float: Updated EWMA value.
        """
        if current_ewma is None:
            return float(new_value)
        return (1.0 - alpha) * current_ewma + alpha * float(new_value)

    def compute_market_drift(self, all_prices):
        """
        Compute the median log return across all liquid items this check cycle.

        What: Calculates the market-wide price drift so individual item returns
              can be adjusted for general market movement.
        Why: Dump detection must distinguish item-specific sell-offs from broad
             market sell-offs. Subtracting market drift isolates idiosyncratic shocks.
        How:
            1. For each item in all_prices, compute mid = (high + low) / 2
            2. If we have a previous mid (from last cycle), compute log return
            3. Collect all valid log returns
            4. Market drift = median of all returns (robust to outliers)
            5. Update last_mids for next cycle

        Args:
            all_prices: Dict of item_id_str -> {'high': int, 'low': int, ...}

        Side Effects:
            Updates self.dump_market_state['last_mids'] and
            self.dump_market_state['market_drift'].
        """
        # last_mids: Previous cycle's mid prices, keyed by item_id string
        last_mids = self.dump_market_state['last_mids']
        # returns: List of log returns for all items with valid previous and current mids
        returns = []
        # new_mids: This cycle's mid prices, will replace last_mids at end
        new_mids = {}

        for item_id_str, price_data in all_prices.items():
            high = price_data.get('high')
            low = price_data.get('low')
            if high is None or low is None or high <= 0 or low <= 0:
                continue
            # mid: Current mid price for this item
            mid = (high + low) / 2.0
            new_mids[item_id_str] = mid

            # prev_mid: Previous cycle's mid price for this item
            prev_mid = last_mids.get(item_id_str)
            if prev_mid is not None and prev_mid > 0:
                # r: Log return from previous cycle to current
                r = math.log(mid / prev_mid)
                returns.append(r)

        # Update state for next cycle
        self.dump_market_state['last_mids'] = new_mids

        # Compute median return as robust drift estimate
        if returns:
            returns.sort()
            n = len(returns)
            if n % 2 == 1:
                self.dump_market_state['market_drift'] = returns[n // 2]
            else:
                self.dump_market_state['market_drift'] = (
                    returns[n // 2 - 1] + returns[n // 2]
                ) / 2.0
        else:
            # No valid returns yet (first cycle) — drift is 0
            self.dump_market_state['market_drift'] = 0.0

    def _get_latest_5m_bucket(self, item_id):
        """
        Get the most recent FiveMinTimeSeries row for an item.

        What: Returns the latest 5-minute time series data point for an item.
        Why: Provides sell ratio and bucket volume data for dump evaluation.
        How: Queries FiveMinTimeSeries ordered by -timestamp and returns first result.

        Args:
            item_id: Integer or string item ID.

        Returns:
            FiveMinTimeSeries instance, or None if no data exists.
        """
        return FiveMinTimeSeries.objects.filter(
            item_id=int(item_id)
        ).first()

    def _compute_sell_ratio(self, bucket):
        """
        Compute the sell-side ratio from a FiveMinTimeSeries bucket.

        What: Returns the fraction of total volume on the sell (low-price) side.
        Why: Dumps are characterized by sell-heavy volume; this metric quantifies it.
        How: sell_ratio = low_price_volume / (high_price_volume + low_price_volume)

        Args:
            bucket: FiveMinTimeSeries instance with high_price_volume and low_price_volume.

        Returns:
            float: Sell ratio in [0, 1], or 0.0 if total volume is 0.
        """
        # total: Combined high and low price volume for this 5-minute bucket
        total = (bucket.high_price_volume or 0) + (bucket.low_price_volume or 0)
        if total <= 0:
            return 0.0
        return (bucket.low_price_volume or 0) / total

    def _check_dump_consistency(self, item_id):
        """
        Check if an item has consistent two-sided trading in recent history.

        What: Returns True if at least 6 of the last 12 five-minute buckets have
              both high-side and low-side volume > 0.
        Why: Items with one-sided volume are likely manipulated or illiquid,
             making dump detection unreliable.
        How: Queries last 12 FiveMinTimeSeries rows and counts valid buckets.

        Args:
            item_id: Integer or string item ID.

        Returns:
            bool: True if consistency check passes (>= 6 of 12 buckets valid).
        """
        # recent_buckets: Last 12 five-minute time series rows for this item
        recent_buckets = FiveMinTimeSeries.objects.filter(
            item_id=int(item_id)
        )[:12]
        # both_side_count: Number of buckets where both sides have trades
        both_side_count = sum(
            1 for b in recent_buckets
            if (b.high_price_volume or 0) > 0 and (b.low_price_volume or 0) > 0
        )
        return both_side_count >= 6

    def _evaluate_single_item_dump(self, item_id_str, all_prices, item_state,
                                    alpha_fair, alpha_vol, alpha_var,
                                    market_drift, alert):
        """
        Evaluate dump conditions for a single item, updating EWMA state in place.

        What: Checks all dump conditions for one item and returns triggered data
              if all conditions are met, or None otherwise.
        Why: Core per-item evaluation logic, separated from multi-item iteration
             for clarity and testability.
        How:
            1. Get current mid price from all_prices
            2. Update EWMA state (fair value, expected volume, variance)
            3. Check each dump condition (shock, sell ratio, rel vol, discount)
            4. Handle confirmation buckets and cooldown
            5. Return triggered data dict or None

        Args:
            item_id_str: String item ID.
            all_prices: Dict of all current prices.
            item_state: Mutable dict with this item's EWMA state (modified in place).
            alpha_fair: EWMA alpha for fair value.
            alpha_vol: EWMA alpha for expected volume.
            alpha_var: EWMA alpha for variance.
            market_drift: Current market drift value.
            alert: Alert model instance with dump configuration.

        Returns:
            dict: Triggered item data if all conditions met, None otherwise.
        """
        # --- Get current price data ---
        price_data = all_prices.get(item_id_str)
        if not price_data:
            return None
        high = price_data.get('high')
        low = price_data.get('low')
        if high is None or low is None or high <= 0 or low <= 0:
            return None

        # mid: Current mid price for EWMA and return calculations
        mid = (high + low) / 2.0
        # last_mid: Previous cycle's mid price for this item
        last_mid = item_state.get('last_mid')

        # --- Update fair value EWMA ---
        item_state['fair'] = self._update_ewma(item_state.get('fair'), mid, alpha_fair)

        # --- Get latest 5m bucket for sell ratio and volume ---
        bucket = self._get_latest_5m_bucket(item_id_str)
        if not bucket:
            item_state['last_mid'] = mid
            return None

        # bucket_vol: Total trade count in the latest 5-minute bucket
        bucket_vol = (bucket.high_price_volume or 0) + (bucket.low_price_volume or 0)
        # Update expected volume EWMA
        item_state['expected_vol'] = self._update_ewma(
            item_state.get('expected_vol'), bucket_vol, alpha_vol
        )

        # --- Compute idiosyncratic shock ---
        # shock_sigma: How many sigmas the item's return deviates from market drift
        # Requires a previous mid price to compute return
        shock_sigma = 0.0
        if last_mid is not None and last_mid > 0:
            # r: Item's log return from previous to current cycle
            r = math.log(mid / last_mid)
            # r_idio: Idiosyncratic return after removing market drift
            r_idio = r - market_drift
            # Update variance EWMA with squared idiosyncratic return
            item_state['var_idio'] = self._update_ewma(
                item_state.get('var_idio'), r_idio * r_idio, alpha_var
            )
            # sigma: Standard deviation of idiosyncratic returns
            var_val = item_state.get('var_idio', 0)
            # epsilon: Small value to prevent division by zero in sigma computation
            epsilon = 1e-12
            sigma = math.sqrt(max(var_val, epsilon))
            shock_sigma = r_idio / sigma
        else:
            # First observation — initialize variance but can't compute shock yet
            item_state['var_idio'] = item_state.get('var_idio')
            item_state['last_mid'] = mid
            return None

        # Update last_mid for next cycle
        item_state['last_mid'] = mid

        # --- Extract alert thresholds (with defaults) ---
        # discount_min: Minimum % discount below fair value to trigger
        discount_min = alert.dump_discount_min if alert.dump_discount_min is not None else 3.0
        # shock_threshold: Shock sigma threshold (negative = downward)
        shock_threshold = alert.dump_shock_sigma if alert.dump_shock_sigma is not None else -4.0
        # sell_ratio_min: Minimum fraction of volume on sell side
        sell_ratio_min = alert.dump_sell_ratio_min if alert.dump_sell_ratio_min is not None else 0.70
        # rel_vol_min: Minimum relative volume vs expected
        rel_vol_min = alert.dump_rel_vol_min if alert.dump_rel_vol_min is not None else 2.5
        # confirmation_needed: Consecutive buckets required before triggering
        confirmation_needed = alert.dump_confirmation_buckets if alert.dump_confirmation_buckets is not None else 2
        # cooldown_minutes: Minutes to wait before re-alerting on same item
        cooldown_minutes = alert.dump_cooldown if alert.dump_cooldown is not None else 30
        # consistency_required: Whether to require both-side volume consistency
        consistency_required = alert.dump_consistency_required if alert.dump_consistency_required is not None else True

        # --- Check cooldown ---
        now_ts = int(time.time())
        # cooldown_until: Unix timestamp when this item's cooldown expires
        cooldown_until = item_state.get('cooldown_until', 0)
        if now_ts < cooldown_until:
            return None

        # --- Check each dump condition ---
        # Condition 1: Shock sigma (must be a large negative outlier)
        if shock_sigma > shock_threshold:
            item_state['consecutive'] = 0
            return None

        # Condition 2: Sell ratio
        # sell_ratio: Fraction of volume on the sell (low-price) side
        sell_ratio = self._compute_sell_ratio(bucket)
        if sell_ratio < sell_ratio_min:
            item_state['consecutive'] = 0
            return None

        # Condition 3: Relative volume
        expected_vol = item_state.get('expected_vol', 0)
        # rel_vol: Current bucket volume relative to EWMA expected volume
        rel_vol = (bucket_vol / expected_vol) if expected_vol > 0 else 0.0
        if rel_vol < rel_vol_min:
            item_state['consecutive'] = 0
            return None

        # Condition 4: Discount below fair value
        fair = item_state.get('fair', mid)
        # avg_low: The low-side average price from the 5m bucket (what buyers are paying)
        avg_low = bucket.avg_low_price
        if avg_low is None or avg_low <= 0 or fair <= 0:
            item_state['consecutive'] = 0
            return None
        # discount_pct: How far below fair value the low price is, as a percentage
        discount_pct = ((fair - avg_low) / fair) * 100.0
        if discount_pct < discount_min:
            item_state['consecutive'] = 0
            return None

        # Condition 5: Consistency check (if enabled)
        if consistency_required and not self._check_dump_consistency(item_id_str):
            item_state['consecutive'] = 0
            return None

        # --- All conditions passed — handle confirmation ---
        # consecutive: Number of consecutive cycles where all conditions were met
        consecutive = item_state.get('consecutive', 0) + 1
        item_state['consecutive'] = consecutive

        if consecutive < confirmation_needed:
            return None

        # --- TRIGGERED: Build result data ---
        # Reset consecutive counter and set cooldown
        item_state['consecutive'] = 0
        item_state['cooldown_until'] = now_ts + (cooldown_minutes * 60)

        # item_mapping: Dict of item_id_str -> item_name for display
        item_mapping = self.get_item_mapping()
        # item_name: Human-readable name for this item
        item_name = item_mapping.get(item_id_str, f'Item {item_id_str}')

        return {
            'item_id': item_id_str,
            'item_name': item_name,
            'fair_value': round(fair, 0),
            'current_low': avg_low,
            'discount_pct': round(discount_pct, 2),
            'sell_ratio': round(sell_ratio, 4),
            'rel_vol': round(rel_vol, 2),
            'shock_sigma': round(shock_sigma, 2),
        }

    def check_dump_alert(self, alert, all_prices):
        """
        Check if a dump alert should trigger for any monitored items.

        What: Evaluates dump conditions across all items the alert is monitoring.
        Why: Users want to detect sharp sell-offs on liquid items in real time.
        How:
            1. Load persisted EWMA state from alert.dump_state
            2. Compute EWMA alphas from half-life settings
            3. Determine which items to check (specific or all with price filters)
            4. For "all items" mode, pre-filter to items with price drops
            5. Check liquidity gate before expensive 5m queries
            6. Evaluate each candidate via _evaluate_single_item_dump()
            7. Persist updated state back to alert.dump_state
            8. Return list of triggered items or True/False for single item

        Args:
            alert: Alert model instance with dump configuration.
            all_prices: Dict of item_id_str -> {'high': int, 'low': int, ...}

        Returns:
            - List of triggered item dicts for multi-item/all-items alerts
            - True/False for single-item alerts
        """
        # --- Load persisted EWMA state ---
        # dump_state: Per-item EWMA state dict loaded from the database
        dump_state = {}
        if alert.dump_state:
            try:
                dump_state = json.loads(alert.dump_state)
            except (json.JSONDecodeError, TypeError):
                dump_state = {}

        # --- Compute EWMA alphas from half-life settings ---
        # alpha_fair: Smoothing factor for fair value EWMA
        alpha_fair = self._compute_ewma_alpha(
            alert.dump_fair_halflife if alert.dump_fair_halflife is not None else 120
        )
        # alpha_vol: Smoothing factor for expected volume EWMA
        alpha_vol = self._compute_ewma_alpha(
            alert.dump_vol_halflife if alert.dump_vol_halflife is not None else 360
        )
        # alpha_var: Smoothing factor for variance EWMA
        alpha_var = self._compute_ewma_alpha(
            alert.dump_var_halflife if alert.dump_var_halflife is not None else 120
        )

        # market_drift: Current cycle's market drift (computed once before alert loop)
        market_drift = self.dump_market_state.get('market_drift', 0.0)
        # liquidity_floor: Minimum hourly GP volume for an item to be eligible
        liquidity_floor = alert.dump_liquidity_floor if alert.dump_liquidity_floor is not None else 5000000

        # --- Determine which items to check ---
        items_to_check = self._get_dump_items_to_check(alert, all_prices, dump_state)

        # --- Evaluate each item ---
        # triggered_items: List of items that passed all dump conditions
        triggered_items = []

        for item_id_str in items_to_check:
            # --- Liquidity gate (check before expensive 5m queries) ---
            volume = self.get_volume_from_timeseries(item_id_str, 0)
            if volume is None or volume < liquidity_floor:
                continue

            # Get or create per-item state dict
            if item_id_str not in dump_state:
                dump_state[item_id_str] = {}
            # item_state: Mutable reference to this item's EWMA state
            item_state = dump_state[item_id_str]

            result = self._evaluate_single_item_dump(
                item_id_str, all_prices, item_state,
                alpha_fair, alpha_vol, alpha_var,
                market_drift, alert
            )
            if result:
                triggered_items.append(result)

        # --- Persist updated state ---
        alert.dump_state = json.dumps(dump_state)
        alert.save(update_fields=['dump_state'])

        # --- Return results ---
        if alert.is_all_items or alert.item_ids:
            # Multi-item/all-items: return list (may be empty)
            return triggered_items if triggered_items else False
        else:
            # Single item: return True/False
            return True if triggered_items else False

    def _get_dump_items_to_check(self, alert, all_prices, dump_state):
        """
        Determine which items a dump alert should evaluate this cycle.

        What: Returns a list of item_id strings to check for dump conditions.
        Why: Different alert scopes (single, multi, all) need different item lists;
             "all items" mode benefits from pre-filtering for performance.
        How:
            - Single item: returns [str(alert.item_id)]
            - Multi-item: returns parsed item_ids JSON
            - All items: returns all items from all_prices that pass price filters
              and show a price drop vs last cycle (pre-filter optimization)

        Args:
            alert: Alert model instance.
            all_prices: Dict of all current prices.
            dump_state: Current persisted EWMA state (for pre-filter comparison).

        Returns:
            list: Item ID strings to evaluate.
        """
        if alert.is_all_items:
            return self._get_all_items_dump_candidates(alert, all_prices, dump_state)
        elif alert.item_ids:
            try:
                ids = json.loads(alert.item_ids)
                return [str(x) for x in ids] if isinstance(ids, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        elif alert.item_id:
            return [str(alert.item_id)]
        return []

    def _get_all_items_dump_candidates(self, alert, all_prices, dump_state):
        """
        Pre-filter all items for dump alert "all items" mode.

        What: Returns item IDs that pass price range filters and show a potential price drop.
        Why: Checking all ~4400 items is expensive; pre-filtering by price drop
             eliminates items that can't possibly be dumping (going up or stable).
        How:
            1. Apply min/max price filters from alert config
            2. Skip items where current mid >= last_mid (not dropping)
            3. Return only items where mid has declined since last cycle

        Args:
            alert: Alert model instance with optional min/max price.
            all_prices: Dict of all current prices.
            dump_state: Current EWMA state with last_mid values.

        Returns:
            list: Item ID strings that are candidates for dump evaluation.
        """
        # candidates: Items that pass price filters and show a price decline
        candidates = []
        for item_id_str, price_data in all_prices.items():
            high = price_data.get('high')
            low = price_data.get('low')
            if high is None or low is None or high <= 0 or low <= 0:
                continue

            # Apply min/max price filters
            if alert.minimum_price is not None:
                if high < alert.minimum_price or low < alert.minimum_price:
                    continue
            if alert.maximum_price is not None:
                if high > alert.maximum_price or low > alert.maximum_price:
                    continue

            # Pre-filter: only check items with declining mid price
            mid = (high + low) / 2.0
            item_s = dump_state.get(item_id_str, {})
            last_mid = item_s.get('last_mid')
            # Allow items with no previous mid (first observation needs to initialize state)
            if last_mid is not None and mid >= last_mid:
                continue

            candidates.append(item_id_str)
        return candidates

    def check_alert(self, alert, all_prices):
        """
        Check if an alert should be triggered.
        
        What: Evaluates alert conditions against current price data
        Why: Core function that determines when users should be notified
        How: Dispatches to type-specific handlers (spread, spike, sustained, threshold, collective_move)
        
        Returns:
            - True/False for simple alerts
            - List of matching items for all_items spread/spike/threshold
            - List of triggered items for multi-item spread/threshold (via item_ids)
        """
        
        # =============================================================================
        # HANDLE COLLECTIVE MOVE ALERTS
        # =============================================================================
        # What: Checks if average percentage change across multiple items meets threshold
        # Why: Users want to track collective movement of item groups (e.g., all herbs)
        # How: Calculates simple or weighted average of item changes, compares to threshold
        if alert.type == 'collective_move':
            return self.check_collective_move_alert(alert, all_prices)
        
        # =============================================================================
        # HANDLE FLIP CONFIDENCE ALERTS
        # =============================================================================
        # What: Computes a flip confidence score (0-100) for item(s) using OSRS Wiki
        #       timeseries data and triggers when score meets the user's threshold/rule.
        # Why: Users want automated notification when items become good flip candidates
        # How: Fetches timeseries data, runs compute_flip_confidence(), applies trigger rule
        if alert.type == 'flip_confidence':
            return self.check_flip_confidence_alert(alert, all_prices)
        
        # =============================================================================
        # HANDLE DUMP ALERTS
        # =============================================================================
        # What: Detects sharp sell-offs on liquid items below EWMA fair value
        # Why: Users want to catch dump events distinct from general market sell-offs
        # How: Uses EWMA fair value, idiosyncratic shock, sell pressure, and discount
        if alert.type == 'dump':
            return self.check_dump_alert(alert, all_prices)
        
        # Handle threshold alerts
        # What: Checks if price has crossed a threshold (percentage or value) from reference price
        # Why: Users want to know when prices change by a certain amount/percentage
        # How: Compares current price to stored reference price using threshold_type calculation
        if alert.type == 'threshold':
            return self.check_threshold_alert(alert, all_prices)
        
        # Handle sustained move alerts
        if alert.type == 'sustained':
            return self.check_sustained_alert(alert, all_prices)
        
        # Handle spread alerts
        if alert.type == 'spread':
            if alert.percentage is None:
                return False
            
            if alert.is_all_items:
                # All items spread check - scan entire market
                # item_mapping: dictionary mapping item_id -> item_name for display
                item_mapping = self.get_item_mapping()
                # matching_items: list of items that meet the spread threshold
                matching_items = []
                
                for item_id, price_data in all_prices.items():
                    high = price_data.get('high')
                    low = price_data.get('low')
                    
                    # Filter by min/max price if set (check both high AND low are within bounds)
                    if alert.minimum_price is not None:
                        if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                            continue
                    if alert.maximum_price is not None:
                        if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                            continue
                    
                    spread = self.calculate_spread(high, low)
                    if spread is not None and spread >= alert.percentage:
                        # =========================================================================
                        # VOLUME FILTER FOR ALL-ITEMS SPREAD ALERTS
                        # What: Skip items whose hourly volume (GP) is below the user's min_volume
                        # Why: When scanning the entire GE, many items have inflated spreads
                        #      but extremely low trading volume, making them impractical to flip.
                        #      Volume filtering ensures only actively-traded items appear.
                        # How: Query the HourlyItemVolume table for the latest volume snapshot.
                        #      If the volume is below the threshold, skip this item entirely.
                        # =========================================================================
                        # volume: The most recent hourly trading volume in GP for this item,
                        #         or None if no volume data exists in the database yet
                        volume = self.get_volume_from_timeseries(item_id, 0)
                        if volume is None or volume < alert.min_volume:
                            continue

                        item_name = item_mapping.get(item_id, f'Item {item_id}')
                        matching_items.append({
                            'item_id': item_id,
                            'item_name': item_name,
                            'high': high,
                            'low': low,
                            'spread': round(spread, 2)
                        })
                
                if matching_items:
                    # Sort by spread descending
                    matching_items.sort(key=lambda x: x['spread'], reverse=True)
                    return matching_items
                
                return False
            
            elif alert.item_ids:
                # Multi-item spread alert - check specific list of items
                # What: Check spread for each item in item_ids JSON array
                # Why: Allows users to monitor specific items instead of all or just one
                # How: Parse item_ids, check each item's spread, build triggered_data
                return self._check_spread_for_item_ids(alert, all_prices)
            
            else:
                # Check specific single item for spread threshold
                # What: Checks a single item's spread against the alert threshold and
                #       optional min volume requirement.
                # Why: Single-item spread alerts are the simplest mode — one item, one check.
                # How: Get price data, calculate spread, check threshold, then optionally
                #      verify hourly volume meets minimum before triggering.
                if not alert.item_id:
                    return False
                price_data = all_prices.get(str(alert.item_id))
                if not price_data:
                    return False
                high = price_data.get('high')
                low = price_data.get('low')
                spread = self.calculate_spread(high, low)
                if spread is not None and spread >= alert.percentage:
                    # =========================================================================
                    # VOLUME FILTER FOR SINGLE-ITEM SPREAD ALERTS
                    # What: Skip triggering if the item's hourly volume (GP) is below min_volume
                    # Why: Even for a single item, users may want to ensure it's actively traded
                    #      before being notified about spread opportunities.
                    # How: Query the HourlyItemVolume table for the latest volume snapshot.
                    #      If the volume is below the threshold, don't trigger the alert.
                    # =========================================================================
                    if alert.min_volume:
                        # volume: The most recent hourly trading volume in GP for this item,
                        #         or None if no volume data exists in the database yet
                        volume = self.get_volume_from_timeseries(str(alert.item_id), 0)
                        if volume is None or volume < alert.min_volume:
                            return False
                    return True
                return False
        
        # =============================================================================
        # SPIKE ALERTS (Rolling window percent change with multi-item support)
        # =============================================================================
        # What: Detects when price changes exceed a threshold within a time window
        # Why: Allows users to be notified of sudden price movements (up or down)
        # How: Uses a rolling window to compare current price vs price from [timeframe] ago
        #      Supports all-items, single-item, and multi-item monitoring modes
        #      
        # Key behaviors:
        # - Warmup period: Won't trigger until we have data from [timeframe] ago
        # - Rolling baseline: Always compares to price at exactly [timeframe] ago
        # - Re-trigger: For multi-item, re-triggers when triggered_data changes
        # - Deactivation: Multi-item alerts deactivate when ALL items are within threshold
        if alert.type == 'spike':
            # =============================================================================
            # SPIKE ALERT VALIDATION
            # =============================================================================
            # What: Validate that required spike alert fields are set
            # Why: Cannot calculate spike without percentage threshold and time frame
            # How: Check percentage and price (time_frame); reference defaults to 'average' if not set
            # Note: Changed validation to not require reference - defaults to 'average'
            # =============================================================================
            if alert.percentage is None or not alert.price:
                return False
            
            # =============================================================================
            # SPIKE ALERT VALIDATION: MIN HOURLY VOLUME REQUIRED
            # =============================================================================
            # What: Ensure spike alerts always have a min_volume configured
            # Why: The requirement mandates spike alerts must filter by hourly GP volume
            # How: If min_volume is missing (None), treat the alert as invalid and skip
            if alert.min_volume is None:
                return False
            
            # min_volume_threshold: Validated minimum hourly volume for spike alerts
            # What: Stores the required min_volume value after validation
            # Why: Makes it explicit that spike alert logic assumes a non-None volume threshold
            # How: Assign from alert.min_volume after the required-field check above
            min_volume_threshold = alert.min_volume
            
            # Get reference type, defaulting to 'average' for spike alerts
            # reference_type: Which price to monitor (high/low/average)
            spike_reference = alert.reference or 'average'

            try:
                time_frame_minutes = int(alert.price)
                print("Time frame (minutes):", time_frame_minutes)
            except (TypeError, ValueError):
                return False
            if time_frame_minutes <= 0:
                return False

            now = time.time()
            direction = (alert.direction or 'both').lower()
            
            # warmup_threshold: Minimum age of oldest data point to consider window "warm"
            # What: Timestamp that data must be older than for warmup to be complete
            # Why: We don't want to trigger on partial data - wait until we have full window
            # How: Data must be at least [timeframe] seconds old
            warmup_threshold = now - (time_frame_minutes * 60)
            
            # cutoff: Timestamp marking the start of our rolling window for pruning
            # What: Any price data older than this is pruned from history
            # Why: We only need data within the timeframe to find the baseline
            # IMPORTANT: Add 60-second buffer beyond warmup_threshold to ensure data survives
            #            long enough for the warmup check to pass. Without this buffer, data
            #            gets pruned right as it becomes old enough (race condition).
            # How: Keep data for an extra 60 seconds beyond the required window
            cutoff = now - (time_frame_minutes * 60) - 60  # Extra 60-second buffer

            # =============================================================================
            # ALL-ITEMS SPIKE ALERT
            # =============================================================================
            if alert.is_all_items:
                item_mapping = self.get_item_mapping()
                matches = []
                for item_id, price_data in all_prices.items():
                    if not price_data:
                        continue
                    
                    # Get current price based on reference type (high, low, or average)
                    # current_price: The latest price for this item
                    if spike_reference == 'high':
                        current_price = price_data.get('high')
                    elif spike_reference == 'low':
                        current_price = price_data.get('low')
                    elif spike_reference == 'average':
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    else:
                        # Default to average for unknown reference types
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    
                    if current_price is None:
                        continue

                    # Update price history for this item
                    # key: Unique identifier for item+reference combination
                    key = f"{item_id}:{spike_reference}"
                    history = self.price_history[key]
                    history.append((now, current_price))
                    # Prune old entries outside the window
                    self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]
                    window = self.price_history[key]
                    if not window:
                        continue

                    # Warmup check: Ensure we have data old enough to compare
                    # What: Check if the oldest price in our window is from [timeframe] ago
                    # Why: Don't want to trigger on partial data (e.g., 3 min data for 10 min window)
                    oldest_timestamp = window[0][0]
                    if oldest_timestamp > warmup_threshold:
                        # Still warming up for this item - not enough historical data
                        continue

                    # baseline_price: Price at exactly [timeframe] ago (oldest in window)
                    baseline_price = window[0][1]
                    if baseline_price in (None, 0):
                        continue

                    # Apply min/max price filters
                    if alert.minimum_price is not None and baseline_price < alert.minimum_price:
                        continue
                    if alert.maximum_price is not None and baseline_price > alert.maximum_price:
                        continue

                    # Calculate percent change from baseline
                    percent_change = ((current_price - baseline_price) / baseline_price) * 100
                    
                    # Determine if this item exceeds threshold based on direction
                    should_trigger = False
                    if direction == 'up':
                        should_trigger = percent_change >= alert.percentage
                    elif direction == 'down':
                        should_trigger = percent_change <= -alert.percentage
                    else:
                        should_trigger = abs(percent_change) >= alert.percentage

                    if should_trigger:
                        # =========================================================================
                        # VOLUME FILTER FOR ALL-ITEMS SPIKE ALERTS
                        # What: Skip items whose hourly volume (GP) is below the user's min_volume
                        # Why: Spike alerts must only trigger on actively-traded items to avoid
                        #      noisy alerts from low-volume items with volatile prices
                        # How: Query the HourlyItemVolume table for the latest volume snapshot.
                        #      If the volume is below the threshold, skip this item entirely.
                        # =========================================================================
                        # volume: The most recent hourly trading volume in GP for this item,
                        #         or None if no volume data exists in the database yet
                        volume = self.get_volume_from_timeseries(item_id, 0)
                        # item_name_debug: Human-readable name for debug output, falls back to
                        #                  "Item {id}" if the item isn't in our mapping
                        item_name_debug = item_mapping.get(item_id, f'Item {item_id}')
                        if volume is None or volume < min_volume_threshold:
                            # What: Log that this item was filtered out by the volume check
                            # Why: Provides visibility into which spiking items are being
                            #      excluded due to insufficient trading volume
                            # How: Print the item details and the reason for filtering
                            continue
                        
                        matches.append({
                            'item_id': item_id,
                            'item_name': item_mapping.get(item_id, f'Item {item_id}'),
                            'baseline': baseline_price,
                            'current': current_price,
                            'percent_change': round(percent_change, 2),
                            'reference': spike_reference,
                            'direction': direction
                        })

                if matches:
                    matches.sort(key=lambda x: abs(x['percent_change']), reverse=True)
                    alert.triggered_data = json.dumps(matches)
                    return matches
                return False

            # =============================================================================
            # MULTI-ITEM SPIKE ALERT (item_ids field is set)
            # =============================================================================
            # What: Monitor specific items for spike threshold
            # Why: Users may want to watch a curated list instead of all items or just one
            # How: Check each item in item_ids, track which exceed threshold
            #      Re-trigger when triggered_data changes
            #      Deactivate when ALL items are simultaneously within threshold
            if alert.item_ids:
                item_ids = json.loads(alert.item_ids)
                item_mapping = self.get_item_mapping()
                
                matches = []  # Items currently exceeding threshold
                all_warmed_up = True  # Track if all items have warmed up
                all_within_threshold = True  # Track if all items are within threshold
                
                for item_id in item_ids:
                    item_id_str = str(item_id)
                    price_data = all_prices.get(item_id_str)
                    
                    if not price_data:
                        # No price data for this item - can't evaluate
                        all_warmed_up = False
                        all_within_threshold = False
                        continue
                    
                    # Get current price based on reference type
                    if spike_reference == 'high':
                        current_price = price_data.get('high')
                    elif spike_reference == 'low':
                        current_price = price_data.get('low')
                    elif spike_reference == 'average':
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    else:
                        # Default to average for unknown reference types
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    
                    if current_price is None:
                        all_warmed_up = False
                        all_within_threshold = False
                        continue
                    
                    # Update price history for this item
                    key = f"{item_id_str}:{spike_reference}"
                    history = self.price_history[key]
                    history.append((now, current_price))
                    self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]
                    window = self.price_history[key]
                    
                    if not window:
                        all_warmed_up = False
                        all_within_threshold = False
                        continue


                    # Warmup check for this item
                    # What: Check if we have accumulated enough historical data for valid comparison
                    # Why: We need data from at least [time_frame_minutes] ago to calculate meaningful % change
                    # How: Compare oldest timestamp in window against warmup_threshold
                    #      If oldest data is newer than threshold, we don't have a full window yet
                    oldest_timestamp = window[0][0]
                    
                    if oldest_timestamp > warmup_threshold:
                        # Still warming up for this item - not enough historical data accumulated
                        # What: Skip this item until we have price data from [time_frame_minutes] ago
                        # Why: Can't calculate meaningful % change without baseline from the past
                        # How: Continue to next item, marking all_warmed_up as False
                        all_warmed_up = False
                        all_within_threshold = False
                        continue
                    
                    # Get baseline price (oldest in window)
                    baseline_price = window[0][1]
                    if baseline_price in (None, 0):
                        all_within_threshold = False
                        continue
                    
                    # Calculate percent change
                    # What: Compute the percentage difference between current and baseline prices
                    # Why: This is the core metric for determining if a spike has occurred
                    # How: ((current - baseline) / baseline) * 100 gives percent change
                    percent_change = ((current_price - baseline_price) / baseline_price) * 100
                    
                    # Check if this item exceeds threshold
                    # What: Determine if the percent change meets the alert's spike threshold
                    # Why: Different alerts may watch for upward, downward, or both directions
                    # How: Compare percent_change against alert.percentage based on direction
                    exceeds_threshold = False
                    if direction == 'up':
                        exceeds_threshold = percent_change >= alert.percentage
                    elif direction == 'down':
                        exceeds_threshold = percent_change <= -alert.percentage
                    else:
                        exceeds_threshold = abs(percent_change) >= alert.percentage
                    
                    if exceeds_threshold:
                        # =========================================================================
                        # MULTI-ITEM SPIKE: MARK AS NOT WITHIN THRESHOLD (BEFORE VOLUME CHECK)
                        # What: Set all_within_threshold to False as soon as we know the item
                        #       has exceeded the spike percentage threshold
                        # Why: The volume filter should only control whether the item appears
                        #      in the triggered matches list, NOT whether the alert considers
                        #      "all items within threshold" for deactivation logic. An item
                        #      that spiked but has low volume still spiked — the alert should
                        #      remain active because a real price movement occurred.
                        # How: Move this flag BEFORE the volume check so that volume-filtered
                        #      items still prevent premature deactivation of the alert.
                        # BUG FIX: Previously, all_within_threshold was set AFTER the volume
                        #          check, meaning items that spiked but had low volume were
                        #          treated as "within threshold," which could incorrectly
                        #          signal that all items are within bounds and affect alert
                        #          deactivation logic.
                        # =========================================================================
                        all_within_threshold = False
                        
                        # =========================================================================
                        # VOLUME FILTER FOR MULTI-ITEM SPIKE ALERTS
                        # What: Skip items whose hourly volume (GP) is below the user's min_volume
                        # Why: Spike alerts must only trigger on actively-traded items to avoid
                        #      noisy alerts from low-volume items with volatile prices
                        # How: Query the HourlyItemVolume table for the latest volume snapshot.
                        #      If the volume is below the threshold, skip this item entirely
                        #      from the matches list (but keep all_within_threshold = False).
                        # =========================================================================
                        # volume: The most recent hourly trading volume in GP for this item,
                        #         or None if no volume data exists in the database yet
                        volume = self.get_volume_from_timeseries(item_id_str, 0)
                        # item_name_debug: Human-readable name for debug output, falls back to
                        #                  "Item {id}" if the item isn't in our mapping
                        item_name_debug = item_mapping.get(item_id_str, f'Item {item_id_str}')
                        if volume is None or volume < min_volume_threshold:
                            # What: Log that this item was filtered out by the volume check
                            # Why: Provides visibility into which spiking items are being
                            #      excluded due to insufficient trading volume
                            # How: Print the item details and the reason for filtering
                            #      Note: all_within_threshold is already False (set above)
                            #      so this item still prevents premature deactivation
                            continue
                        
                        matches.append({
                            'item_id': item_id_str,
                            'item_name': item_mapping.get(item_id_str, f'Item {item_id_str}'),
                            'baseline': baseline_price,
                            'current': current_price,
                            'percent_change': round(percent_change, 2),
                            'reference': spike_reference,
                            'direction': direction
                        })
                
                # Handle multi-item spike triggering (no auto-deactivation)
                return self._handle_multi_item_spike_trigger(alert, matches, all_within_threshold, all_warmed_up)

            # =============================================================================
            # SINGLE-ITEM SPIKE ALERT
            # =============================================================================
            if not alert.item_id:
                return False

            price_data = all_prices.get(str(alert.item_id))
            if not price_data:
                return False

            # Get current price based on reference type
            if spike_reference == 'high':
                current_price = price_data.get('high')
            elif spike_reference == 'low':
                current_price = price_data.get('low')
            elif spike_reference == 'average':
                high = price_data.get('high')
                low = price_data.get('low')
                current_price = (high + low) // 2 if high and low else (high or low)
            else:
                # Default to average for unknown reference types
                high = price_data.get('high')
                low = price_data.get('low')
                current_price = (high + low) // 2 if high and low else (high or low)
            
            if current_price is None:
                return False

            key = f"{alert.item_id}:{spike_reference}"

            history = self.price_history[key]
            history.append((now, current_price))
            self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]

            window = self.price_history[key]
            if not window:
                return False

            # Warmup check for single item
            # What: Check if we have data old enough to compare
            # Why: Don't trigger on partial data during initial warmup period
            oldest_timestamp = window[0][0]
            if oldest_timestamp > warmup_threshold:
                print(f"Spike alert warming up - need {time_frame_minutes} min of data")
                return False

            baseline_price = window[0][1]
            print("Baseline price from history:", baseline_price)
            if baseline_price in (None, 0):
                return False

            percent_change = ((current_price - baseline_price) / baseline_price) * 100
            should_trigger = False
            if direction == 'up':
                should_trigger = percent_change >= alert.percentage
            elif direction == 'down':
                should_trigger = percent_change <= -alert.percentage
            else:
                should_trigger = abs(percent_change) >= alert.percentage

            if should_trigger:
                # =========================================================================
                # VOLUME FILTER FOR SINGLE-ITEM SPIKE ALERTS
                # What: Skip triggering if the item's hourly volume (GP) is below min_volume
                # Why: Spike alerts must only trigger on actively-traded items to avoid
                #      noisy alerts from low-volume items with volatile prices
                # How: Query the HourlyItemVolume table for the latest volume snapshot.
                #      If the volume is below the threshold, don't trigger the alert.
                # =========================================================================
                # volume: The most recent hourly trading volume in GP for this item,
                #         or None if no volume data exists in the database yet
                volume = self.get_volume_from_timeseries(str(alert.item_id), 0)
                if volume is None or volume < min_volume_threshold:
                    # What: Log that this item was filtered out by the volume check
                    # Why: Provides visibility into why a spiking item did not trigger
                    # How: Print the item details and the reason for filtering
                    return False
                
                alert.triggered_data = json.dumps({
                    'baseline': baseline_price,
                    'current': current_price,
                    'percent_change': round(percent_change, 2),
                    'time_frame_minutes': time_frame_minutes,
                    'reference': spike_reference,
                    'direction': direction
                })
                return True
            return False
        
        # NOTE: Legacy 'above'/'below' alert types were removed.
        # What: Previously, we evaluated simple "price > X" / "price < X" conditions here.
        # Why: Keeping this logic would allow creation/evaluation of removed alert types and make the
        #      codebase harder to maintain.
        # How: With above/below removed, if we reach this point it means the alert type was not handled
        #      by any of the supported branches above, so we safely do not trigger.
        return False

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting alert checker...'))
        
        while True:
            # Get all active alerts (include triggered all_items spread alerts for re-check)
            try:
                active_alerts = Alert.objects.filter(is_active=True)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error fetching alerts: {e}'))
                time.sleep(30)
                return self.handle(self, *args, **options)
            # alerts_to_check: Filter to non-triggered OR alerts that can re-trigger
            # What: Determines which alerts need to be checked this cycle
            # Why: Some alerts (all_items spread, spike, sustained, multi-item spread, collective_move) can re-trigger
            # How: Include non-triggered alerts PLUS special alert types that stay active
            alerts_to_check = [
                a for a in active_alerts
                if (not a.is_triggered) 
                   or (a.type == 'spread' and a.is_all_items)  # All items spread can re-trigger
                   or (a.type == 'spread' and a.item_ids)  # Multi-item spread can re-trigger
                   or (a.type == 'spike' and a.is_all_items)  # All items spike can re-trigger
                   or (a.type == 'spike' and a.item_ids)  # Multi-item spike can re-trigger
                   or (a.type == 'sustained')  # Sustained always re-checks
                   or (a.type == 'threshold' and (a.is_all_items or a.item_ids))  # Multi-item/all-items threshold can re-trigger
                   or (a.type == 'collective_move')  # Collective move alerts always re-check (monitors groups)
                   or (a.type == 'flip_confidence')  # Flip confidence alerts always re-check (continuous monitoring)
                   or (a.type == 'dump')  # Dump alerts always re-check (continuous monitoring)
            ]
            
            if alerts_to_check:
                self.stdout.write(f'Checking {len(alerts_to_check)} alerts...')
                
                # Fetch all prices once
                all_prices = self.get_all_prices()
                
                if all_prices:
                    # =============================================================================
                    # COMPUTE MARKET DRIFT (once per check cycle, before evaluating alerts)
                    # =============================================================================
                    # What: Calculates the median log return across all items this cycle
                    # Why: Dump alerts need market drift to isolate idiosyncratic shocks
                    # How: Compares current mid prices to last cycle's mids, takes median return
                    # Note: Runs every cycle regardless of whether dump alerts exist;
                    #       the cost is negligible (just iterating all_prices dict in memory)
                    self.compute_market_drift(all_prices)
                    
                    for alert in alerts_to_check:
                        result = self.check_alert(alert, all_prices)
                        
                        # =============================================================================
                        # HANDLE COLLECTIVE MOVE ALERTS
                        # =============================================================================
                        # What: Process collective_move alerts which return True/False
                        # Why: Collective move alerts monitor group averages and can re-trigger
                        # How: When triggered, mark as triggered and save; always stays active
                        if alert.type == 'collective_move':
                            if result:
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring - never auto-deactivate
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (collective move): {alert}')
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            continue  # Skip to next alert
                        
                        # =============================================================================
                        # HANDLE FLIP CONFIDENCE ALERTS
                        # =============================================================================
                        # What: Process flip_confidence alerts which return True/list/False
                        # Why: Flip confidence alerts continuously monitor items and can re-trigger
                        # How: For single-item, result is True/False; for multi/all-items, result is a list.
                        #      Similar to collective_move handling: always stay active.
                        if alert.type == 'flip_confidence':
                            if result and result is not False:
                                # Handle both single-item (True) and multi-item (list) results
                                if isinstance(result, list) and result:
                                    alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring - never auto-deactivate
                                alert.triggered_at = timezone.now()
                                alert.save()
                                triggered_count = len(result) if isinstance(result, list) else 1
                                # alert_str: String representation of the alert, with Unicode
                                # characters replaced by ASCII equivalents to avoid cp1252
                                # encoding errors on Windows consoles (e.g., ≥ -> >=)
                                alert_str = str(alert).replace('\u2265', '>=').replace('\u0394', 'D')
                                self.stdout.write(
                                    self.style.WARNING(
                                        f'TRIGGERED (flip confidence): {triggered_count} item(s) for {alert_str}'
                                    )
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            continue  # Skip to next alert
                        
                        # =============================================================================
                        # HANDLE DUMP ALERTS
                        # =============================================================================
                        # What: Process dump alerts which return True/list/False
                        # Why: Dump alerts continuously monitor items and can re-trigger
                        # How: For single-item, result is True/False; for multi/all-items, result is a list.
                        #      Always stay active for continuous monitoring.
                        if alert.type == 'dump':
                            if result and result is not False:
                                # Handle both single-item (True) and multi-item (list) results
                                if isinstance(result, list) and result:
                                    alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring - never auto-deactivate
                                alert.triggered_at = timezone.now()
                                alert.save()
                                # triggered_count: Number of items that triggered this cycle
                                triggered_count = len(result) if isinstance(result, list) else 1
                                # alert_str: Safe ASCII representation for Windows console output
                                alert_str = str(alert).replace('\u2265', '>=').replace('\u2264', '<=').replace('\u03c3', 'o')
                                self.stdout.write(
                                    self.style.WARNING(
                                        f'TRIGGERED (dump): {triggered_count} item(s) for {alert_str}'
                                    )
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            continue  # Skip to next alert
                        
                        # Handle multi-item spread alerts FIRST, even when result is empty list
                        # What: Always process multi-item spread alerts to update triggered_data
                        # Why: When items drop below threshold, we need to update the display
                        # How: Check if this is a multi-item spread alert and result is a list (even empty)
                        if alert.type == 'spread' and alert.item_ids and isinstance(result, list):
                            self._handle_multi_item_spread_trigger(alert, result)
                            continue  # Skip to next alert, already handled
                        
                        # Handle multi-item spike alerts
                        # What: Process spike alerts that monitor multiple specific items (via item_ids)
                        # Why: Multi-item spike alerts are fully handled in _handle_multi_item_spike_trigger
                        #      and should NOT fall through to the generic else block which deactivates
                        # How: Check if this is a multi-item spike alert and skip further processing
                        if alert.type == 'spike' and alert.item_ids:
                            # Already handled by _handle_multi_item_spike_trigger in check_alert()
                            # The handler saves the alert, so we just continue to next alert
                            continue
                        
                        # Handle multi-item/all-items threshold alerts
                        # What: Process threshold alerts that monitor multiple items
                        # Why: These alerts can re-trigger and need special handling for triggered_data
                        # How: Update triggered_data with current triggered items, manage active state
                        if alert.type == 'threshold' and (alert.is_all_items or alert.item_ids) and isinstance(result, list):
                            self._handle_multi_item_threshold_trigger(alert, result)
                            continue  # Skip to next alert, already handled
                        
                        if result:
                            # Handle all_items spread alerts specially
                            if alert.type == 'spread' and alert.is_all_items and isinstance(result, list):
                                alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Keep is_active = True - alerts never auto-deactivate
                                alert.is_active = True
                                # Only show notification if show_notification is enabled
                                # What: Controls whether notification banner appears
                                # Why: Users may disable notifications but still want to track alerts
                                alert.is_dismissed = not alert.show_notification
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spread): {len(result)} items found')
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            
                            elif alert.type == 'spike' and alert.is_all_items and isinstance(result, list):
                                alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring - never auto-deactivate
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spike): {len(result)} items found')
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            elif alert.type == 'sustained':
                                # Sustained alerts stay active for re-triggering
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring - never auto-deactivate
                                alert.triggered_at = timezone.now()
                                alert.save()
                                
                                # Log appropriately based on result type
                                if isinstance(result, list):
                                    self.stdout.write(
                                        self.style.WARNING(f'TRIGGERED (sustained move - all items): {len(result)} items matched')
                                    )
                                else:
                                    self.stdout.write(
                                        self.style.WARNING(f'TRIGGERED (sustained move): {alert.item_name or "multiple items"}')
                                    )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
                            else:
                                # Generic alert handler (single-item alerts, etc.)
                                alert.is_triggered = True
                                # Keep alert active - never auto-deactivate
                                # What: All alerts stay active until manually deactivated by user
                                # Why: User may want to continue monitoring even after trigger
                                alert.is_active = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED: {alert}')
                                )
                                # Send email notification if enabled, then disable to prevent spam
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                                    alert.email_notification = False
                                    alert.save()
            else:
                self.stdout.write('No alerts to check.')
            
            # Wait 30 seconds before next check
            time.sleep(5)
