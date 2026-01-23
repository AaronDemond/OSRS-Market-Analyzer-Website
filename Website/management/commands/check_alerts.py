import os
import sys
import time
import json
from collections import defaultdict
from pathlib import Path

import requests
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

# Allow running the command directly (outside manage.py) by ensuring the project is on sys.path and Django is configured
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')
    import django
    django.setup()

from Website.models import Alert


class Command(BaseCommand):
    help = 'Continuously checks alerts every 30 seconds and triggers them if conditions are met'

    # Email/SMS recipient for alert notifications (loaded from environment variable)
    ALERT_RECIPIENT = os.environ.get('ALERT_RECIPIENT', '')

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
        Why: Allows users to monitor multiple specific items for spread alerts
        How: 
            1. Parse item_ids JSON array to get list of items to check
            2. For each item, calculate spread and compare against threshold
            3. Build triggered_data with items that meet the threshold
            4. Return list of triggered items (empty list if none triggered)
        
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
        # reference_type: 'high', 'low', or 'average' - which price to monitor
        reference_type = alert.reference or 'high'
        # threshold_value: The percentage threshold (stored in alert.percentage)
        threshold_value = alert.percentage if alert.percentage is not None else 0
        
        # Determine which items to check
        # items_to_check: List of (item_id_str, reference_price) tuples
        items_to_check = []
        
        if threshold_type == 'value':
            # Value-based threshold: Single item only
            # What: Check if current price crosses the target_price
            # Why: User wants to be alerted when price reaches a specific value
            if not alert.item_id or alert.target_price is None:
                return False
            
            item_id_str = str(alert.item_id)
            price_data = all_prices.get(item_id_str)
            if not price_data:
                return False
            
            # Get current price based on reference type
            current_price = self._get_price_by_reference(price_data, reference_type)
            if current_price is None:
                return False
            
            target = alert.target_price
            
            # Check if threshold is crossed
            # For 'up': trigger when current_price >= target
            # For 'down': trigger when current_price <= target
            if direction == 'up':
                triggered = current_price >= target
            else:  # direction == 'down'
                triggered = current_price <= target
            
            return triggered
        
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
            if not alert.item_id:
                return False
            
            item_id_str = str(alert.item_id)
            
            # Get price data
            price_data = all_prices.get(item_id_str)
            if not price_data:
                return False
            
            # Get reference price
            ref_price = reference_prices.get(item_id_str)
            if ref_price is None:
                return False
            
            # Get current price
            current_price = self._get_price_by_reference(price_data, reference_type)
            if current_price is None:
                return False
            
            # Calculate percentage change
            change_percent = self._calculate_percent_change(ref_price, current_price)
            
            # Check if threshold is crossed
            return self._check_threshold_crossed(change_percent, threshold_value, direction)
    
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
        Fetch volume from timeseries API for a given item within a time window.
        Uses 5-minute intervals (the most granular available).
        Returns total volume or None if unavailable.
        """
        try:
            response = requests.get(
                f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=5m&id={item_id}',
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
            )
            if response.status_code != 200:
                return None
            
            data = response.json()
            if 'data' not in data:
                return None
            
            now = time.time()
            cutoff = now - (time_window_minutes * 60)
            total_volume = 0
            
            for entry in data['data']:
                timestamp = entry.get('timestamp', 0)
                if timestamp >= cutoff:
                    high_vol = entry.get('highPriceVolume', 0) or 0
                    low_vol = entry.get('lowPriceVolume', 0) or 0
                    total_volume += high_vol + low_vol
            
            return total_volume
        except requests.RequestException:
            return None

    def print_sustained_debug(self, alert, state, trigger_data):
        """Print formatted debug info for a triggered sustained move alert."""
        print("\n" + "=" * 70)
        print("SUSTAINED MOVE ALERT TRIGGERED")
        print("=" * 70)
        print(f"\n{'ALERT CONFIGURATION':^70}")
        print("-" * 70)
        print(f"  Alert ID:              {alert.id}")
        print(f"  Item:                  {alert.item_name} (ID: {alert.item_id})")
        print(f"  Direction:             {alert.direction or 'both'}")
        print(f"  Time Window:           {alert.time_frame} minutes")
        print(f"  Min Consecutive Moves: {alert.min_consecutive_moves}")
        print(f"  Min Move Percentage:   {alert.min_move_percentage}%")
        print(f"  Volatility Buffer (N): {alert.volatility_buffer_size}")
        print(f"  Volatility Mult (K):   {alert.volatility_multiplier}")
        print(f"  Min Volume:            {alert.min_volume or 'None'}")
        
        print(f"\n{'TRIGGER DATA':^70}")
        print("-" * 70)
        print(f"  Streak Direction:      {trigger_data['streak_direction']}")
        print(f"  Streak Count:          {trigger_data['streak_count']} moves")
        print(f"  Total Move:            {trigger_data['total_move_percent']:.4f}%")
        print(f"  Start Price:           {trigger_data['start_price']:,.2f}")
        print(f"  Current Price:         {trigger_data['current_price']:,.2f}")
        print(f"  Volume:                {trigger_data['volume']:,}")
        print(f"  Avg Volatility:        {trigger_data['avg_volatility']:.4f}%")
        print(f"  Required Move (K×avg): {trigger_data['required_move']:.4f}%")
        print(f"  Volatility Check:      PASSED")
        
        buffer = state.get('volatility_buffer', [])
        buffer_header = f"VOLATILITY BUFFER (last {len(buffer)} moves)"
        print(f"\n{buffer_header:^70}")
        print("-" * 70)
        if buffer:
            for i, move in enumerate(buffer[-10:], 1):  # Show last 10 moves
                print(f"    Move {i}: {move:.4f}%")
            if len(buffer) > 10:
                print(f"    ... ({len(buffer) - 10} more moves)")
        
        print("=" * 70 + "\n")

    def check_sustained_alert(self, alert, all_prices):
        print(alert)
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
        """
        price_data = all_prices.get(str(item_id))
        if not price_data:
            return None
        
        high = price_data.get('high')
        low = price_data.get('low')
        if high is None or low is None:
            return None
        
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
        volume = 0
        if min_volume:
            volume = self.get_volume_from_timeseries(item_id, time_window_minutes)
            if volume is None or volume < min_volume:
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
        
        # Print debug info
        self.print_sustained_debug(alert, state, trigger_data)
        
        # Reset streak after trigger
        state['streak_count'] = 0
        state['streak_direction'] = None
        
        return trigger_data

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

    def check_alert(self, alert, all_prices):
        """
        Check if an alert should be triggered.
        
        What: Evaluates alert conditions against current price data
        Why: Core function that determines when users should be notified
        How: Dispatches to type-specific handlers (spread, spike, sustained, threshold)
        
        Returns:
            - True/False for simple alerts
            - List of matching items for all_items spread/spike/threshold
            - List of triggered items for multi-item spread/threshold (via item_ids)
        """
        
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
                if not alert.item_id:
                    return False
                price_data = all_prices.get(str(alert.item_id))
                if not price_data:
                    return False
                high = price_data.get('high')
                low = price_data.get('low')
                spread = self.calculate_spread(high, low)
                if spread is not None and spread >= alert.percentage:
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
            if alert.percentage is None or not alert.reference or not alert.price:
                return False

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
                    if alert.reference == 'high':
                        current_price = price_data.get('high')
                    elif alert.reference == 'low':
                        current_price = price_data.get('low')
                    elif alert.reference == 'average':
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    else:
                        current_price = price_data.get('high')
                    
                    if current_price is None:
                        continue

                    # Update price history for this item
                    # key: Unique identifier for item+reference combination
                    key = f"{item_id}:{alert.reference or 'low'}"
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
                        matches.append({
                            'item_id': item_id,
                            'item_name': item_mapping.get(item_id, f'Item {item_id}'),
                            'baseline': baseline_price,
                            'current': current_price,
                            'percent_change': round(percent_change, 2),
                            'reference': alert.reference,
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
                    if alert.reference == 'high':
                        current_price = price_data.get('high')
                    elif alert.reference == 'low':
                        current_price = price_data.get('low')
                    elif alert.reference == 'average':
                        high = price_data.get('high')
                        low = price_data.get('low')
                        current_price = (high + low) // 2 if high and low else (high or low)
                    else:
                        current_price = price_data.get('high')
                    
                    if current_price is None:
                        all_warmed_up = False
                        all_within_threshold = False
                        continue
                    
                    # Update price history for this item
                    key = f"{item_id_str}:{alert.reference or 'low'}"
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
                        all_within_threshold = False
                        matches.append({
                            'item_id': item_id_str,
                            'item_name': item_mapping.get(item_id_str, f'Item {item_id_str}'),
                            'baseline': baseline_price,
                            'current': current_price,
                            'percent_change': round(percent_change, 2),
                            'reference': alert.reference,
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
            if alert.reference == 'high':
                current_price = price_data.get('high')
            elif alert.reference == 'low':
                current_price = price_data.get('low')
            elif alert.reference == 'average':
                high = price_data.get('high')
                low = price_data.get('low')
                current_price = (high + low) // 2 if high and low else (high or low)
            else:
                current_price = price_data.get('high')
            
            if current_price is None:
                return False

            key = f"{alert.item_id}:{alert.reference or 'low'}"

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
                alert.triggered_data = json.dumps({
                    'baseline': baseline_price,
                    'current': current_price,
                    'percent_change': round(percent_change, 2),
                    'time_frame_minutes': time_frame_minutes,
                    'reference': alert.reference,
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
            active_alerts = Alert.objects.filter(is_active=True)
            # alerts_to_check: Filter to non-triggered OR alerts that can re-trigger
            # What: Determines which alerts need to be checked this cycle
            # Why: Some alerts (all_items spread, spike, sustained, multi-item spread) can re-trigger
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
            ]
            
            if alerts_to_check:
                self.stdout.write(f'Checking {len(alerts_to_check)} alerts...')
                
                # Fetch all prices once
                all_prices = self.get_all_prices()
                
                if all_prices:
                    for alert in alerts_to_check:
                        result = self.check_alert(alert, all_prices)
                        
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
            time.sleep(15)
