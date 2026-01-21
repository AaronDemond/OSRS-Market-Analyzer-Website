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

print("LOADED")

# Allow running the command directly (outside manage.py) by ensuring the project is on sys.path and Django is configured
BASE_DIR = Path(__file__).resolve().parents[3]  # Goes up from commands -> management -> Website -> OSRSWebsite
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
        print("Sending alert for: ")
        print(alert)
        print("==================")
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
        """Check if an alert should be triggered. Returns True/False or list of matching items for all_items spread."""
        
        # Handle sustained move alerts
        if alert.type == 'sustained':
            return self.check_sustained_alert(alert, all_prices)
        
        # Handle spread alerts
        if alert.type == 'spread':
            if alert.percentage is None:
                return False
            
            if alert.is_all_items:
                item_mapping = self.get_item_mapping()
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
            else:
                # Check specific item for spread threshold
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
            # Filter to non-triggered OR is_all_items spread/spike (which can re-trigger) OR sustained (which can re-trigger)
            alerts_to_check = [
                a for a in active_alerts
                if (not a.is_triggered) or (a.type == 'spread' and a.is_all_items) or (a.type == 'spike' and a.is_all_items) or (a.type == 'sustained')
            ]
            
            if alerts_to_check:
                self.stdout.write(f'Checking {len(alerts_to_check)} alerts...')
                
                # Fetch all prices once
                all_prices = self.get_all_prices()
                
                if all_prices:
                    for alert in alerts_to_check:
                        result = self.check_alert(alert, all_prices)
                        
                        if result:
                            # Handle all_items spread alerts specially
                            if alert.type == 'spread' and alert.is_all_items and isinstance(result, list):
                                # Check if data changed before sending notification
                                old_triggered_data = alert.triggered_data
                                new_triggered_data = json.dumps(result)
                                was_triggered = alert.is_triggered
                                data_changed = old_triggered_data != new_triggered_data
                                
                                alert.triggered_data = new_triggered_data
                                alert.is_triggered = True
                                # Keep is_active = True for all_items spread alerts
                                alert.is_dismissed = False  # Reset dismissed so notification shows again
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spread): {len(result)} items found')
                                )
                                # Send email notification only if data changed or first trigger
                                if alert.email_notification and (not was_triggered or data_changed):
                                    self.send_alert_notification(alert, alert.triggered_text())
                                elif alert.email_notification:
                                    self.stdout.write(self.style.NOTICE('Skipping notification - data unchanged'))
                            elif alert.type == 'spike' and alert.is_all_items and isinstance(result, list):
                                # Check if data changed before sending notification
                                old_triggered_data = alert.triggered_data
                                new_triggered_data = json.dumps(result)
                                was_triggered = alert.is_triggered
                                data_changed = old_triggered_data != new_triggered_data
                                
                                alert.triggered_data = new_triggered_data
                                alert.is_triggered = True
                                alert.is_dismissed = False
                                alert.is_active = True  # keep monitoring
                                alert.triggered_at = timezone.now()
                                # Keep active for re-trigger
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spike): {len(result)} items found')
                                )
                                # Send email notification only if data changed or first trigger
                                if alert.email_notification and (not was_triggered or data_changed):
                                    self.send_alert_notification(alert, alert.triggered_text())
                                elif alert.email_notification:
                                    self.stdout.write(self.style.NOTICE('Skipping notification - data unchanged'))
                            elif alert.type == 'sustained':
                                # Check if data changed before sending notification
                                old_triggered_data = alert.triggered_data
                                new_triggered_data = json.dumps(result) if isinstance(result, list) else alert.triggered_data
                                was_triggered = alert.is_triggered
                                data_changed = old_triggered_data != new_triggered_data
                                
                                # Sustained alerts stay active for re-triggering
                                alert.is_triggered = True
                                alert.is_dismissed = False
                                alert.is_active = True  # Keep monitoring
                                alert.triggered_at = timezone.now()
                                if isinstance(result, list):
                                    alert.triggered_data = new_triggered_data
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
                                # Send email notification only if data changed or first trigger
                                if alert.email_notification and (not was_triggered or data_changed):
                                    self.send_alert_notification(alert, alert.triggered_text())
                                elif alert.email_notification:
                                    self.stdout.write(self.style.NOTICE('Skipping notification - data unchanged'))
                            else:
                                alert.is_triggered = True
                                # Deactivate alert if it's not for all items
                                if alert.is_all_items is not True:
                                    alert.is_active = False
                                alert.triggered_at = timezone.now()
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED: {alert}')
                                )
                                # Send email notification if enabled (single-item alerts only trigger once)
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
            else:
                self.stdout.write('No alerts to check.')
            
            # Wait 30 seconds before next check
            time.sleep(5)
