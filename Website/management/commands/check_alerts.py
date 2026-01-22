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
            2. Compare item IDs and all data values (spread, high, low)
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
        # What: Compare spread, high, and low values for items present in both
        # Why: Even if same items are triggering, price/spread changes are meaningful
        # How: Compare rounded values to avoid float precision false positives
        for item_id, new_item in new_items_map.items():
            old_item = old_items_map.get(item_id)
            if old_item:
                # Compare spread values
                old_spread = round(old_item.get('spread', 0), 2)
                new_spread = round(new_item.get('spread', 0), 2)
                if old_spread != new_spread:
                    return True
                
                # Compare high values
                old_high = old_item.get('high')
                new_high = new_item.get('high')
                if old_high != new_high:
                    return True
                
                # Compare low values
                old_low = old_item.get('low')
                new_low = new_item.get('low')
                if old_low != new_low:
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
            # All items have triggered - deactivate the alert
            # What: Set is_active to False to stop checking this alert
            # Why: User requested to be notified when ALL items meet the condition
            alert.is_active = False
            self.stdout.write(
                self.style.WARNING(
                    f'TRIGGERED (multi-item spread - ALL {len(total_item_ids)} items): Deactivating alert'
                )
            )
        else:
            # Some items triggered but not all (or none) - keep alert active
            # What: Keep is_active True to continue monitoring remaining items
            # Why: Alert should not deactivate until ALL items have triggered
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
        How: Dispatches to type-specific handlers (spread, spike, sustained, above/below)
        
        Returns:
            - True/False for simple alerts
            - List of matching items for all_items spread/spike
            - List of triggered items for multi-item spread (via item_ids)
        """
        
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
        
        # Handle spike alerts (rolling window percent change)
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
            cutoff = now - (time_frame_minutes * 60)

            if alert.is_all_items:
                item_mapping = self.get_item_mapping()
                matches = []
                for item_id, price_data in all_prices.items():
                    if not price_data:
                        continue
                    current_price = price_data.get('high') if alert.reference == 'high' else price_data.get('low')
                    if current_price is None:
                        continue

                    key = f"{item_id}:{alert.reference or 'low'}"
                    history = self.price_history[key]
                    history.append((now, current_price))
                    self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]
                    window = self.price_history[key]
                    if not window:
                        continue

                    baseline_price = window[0][1]
                    if baseline_price in (None, 0):
                        continue

                    if alert.minimum_price is not None and baseline_price < alert.minimum_price:
                        continue
                    if alert.maximum_price is not None and baseline_price > alert.maximum_price:
                        continue

                    percent_change = ((current_price - baseline_price) / baseline_price) * 100
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
                    matches.sort(key=lambda x: x['percent_change'], reverse=True)
                    alert.triggered_data = json.dumps(matches)
                    return matches
                return False

            if not alert.item_id:
                return False

            price_data = all_prices.get(str(alert.item_id))
            if not price_data:
                return False

            current_price = price_data.get('high') if alert.reference == 'high' else price_data.get('low')
            print("Current observed price:", current_price)
            if current_price is None:
                return False

            key = f"{alert.item_id}:{alert.reference or 'low'}"

            history = self.price_history[key]
            history.append((now, current_price))
            self.price_history[key] = [(ts, val) for ts, val in history if ts >= cutoff]

            window = self.price_history[key]
            if not window:
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
                    'percent_change': percent_change,
                    'time_frame_minutes': time_frame_minutes,
                    'reference': alert.reference,
                    'direction': direction
                })
                return True
            return False
        
        # Handle above/below alerts
        if not alert.item_id or not alert.price or not alert.reference:
            return False
        
        price_data = all_prices.get(str(alert.item_id))
        if not price_data:
            return False
        
        # Get the appropriate price based on reference
        if alert.reference == 'high':
            current_price = price_data.get('high')
        else:
            current_price = price_data.get('low')
        
        if current_price is None:
            return False
        
        # Check if condition is met
        if alert.type == 'above' and current_price > alert.price:
            return True
        elif alert.type == 'below' and current_price < alert.price:
            return True
        
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
                   or (a.type == 'sustained')  # Sustained always re-checks
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
                        
                        if result:
                            # Handle all_items spread alerts specially
                            if alert.type == 'spread' and alert.is_all_items and isinstance(result, list):
                                alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Keep is_active = True for all_items spread alerts
                                # Only show notification if show_notification is enabled
                                # What: Controls whether notification banner appears
                                # Why: Users may disable notifications but still want to track alerts
                                alert.is_dismissed = not alert.show_notification
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spread): {len(result)} items found')
                                )
                                # Send email notification if enabled
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                            
                            elif alert.type == 'spike' and alert.is_all_items and isinstance(result, list):
                                alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # keep monitoring
                                alert.triggered_at = timezone.now()
                                # Keep active for re-trigger
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spike): {len(result)} items found')
                                )
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                            elif alert.type == 'sustained':
                                # Sustained alerts stay active for re-triggering
                                alert.is_triggered = True
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.is_active = True  # Keep monitoring
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
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                            else:
                                alert.is_triggered = True
                                # Deactivate alert if it's not for all items
                                if alert.is_all_items is not True:
                                    alert.is_active = False
                                # Only show notification if show_notification is enabled
                                alert.is_dismissed = not alert.show_notification
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED: {alert}')
                                )
                                # Send email notification if enabled
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
            else:
                self.stdout.write('No alerts to check.')
            
            # Wait 30 seconds before next check
            time.sleep(15)
