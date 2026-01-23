from django.db import models
from django.contrib.auth.models import User
import requests


def get_item_price(item_id, reference):
    """
    Fetch the high or low price for an item based on reference.
    reference: 'high' or 'low'
    """
    try:
        response = requests.get(
            'https://prices.runescape.wiki/api/v1/osrs/latest',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                price_data = data['data'].get(str(item_id))
                if price_data:
                    if reference == 'high':
                        return price_data.get('high')
                    elif reference == 'low':
                        return price_data.get('low')
    except requests.RequestException:
        pass
    return None



class Flip(models.Model):
    TYPE_CHOICES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    price = models.IntegerField()
    date = models.DateTimeField()
    quantity = models.IntegerField()
    type = models.CharField(max_length=4, choices=TYPE_CHOICES)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"


class FlipProfit(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255, blank=True, null=True, default=None)
    average_cost = models.FloatField(default=0)
    unrealized_net = models.FloatField(default=0)
    realized_net = models.FloatField(default=0)
    quantity_held = models.IntegerField(default=0)

    class Meta:
        unique_together = ['user', 'item_id']

    def __str__(self):
        return f"FlipProfit item_id={self.item_id} qty={self.quantity_held}"


class AlertGroup(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'name']

    def __str__(self):
        return self.name


class Alert(models.Model):
    """
    Alert Model
    ===========
    What: Represents a user-defined price alert for OSRS Grand Exchange items.
    Why: Allows users to be notified when items meet specific price conditions.
    How: Stores alert configuration including type, item(s) to track, thresholds, and trigger state.
    
    Alert Types:
        # NOTE: The legacy "Above Threshold" / "Below Threshold" alert types were removed from the product.
        # What: This list documents the currently supported alert types.
        # Why: Keeping this up-to-date prevents UI/backend drift and avoids users creating alert types
        #      that no longer have evaluation logic.
        # How: We explicitly list only the remaining alert types.
        - spread: Triggers when buy/sell spread exceeds a percentage
        - spike: Triggers when price changes rapidly within a time frame
        - sustained: Triggers when price moves consistently in one direction
        - threshold: Triggers when price crosses a threshold (by percentage or value) from a reference price
    """
    
    # DIRECTION_CHOICES: Options for which direction of price movement to track
    # What: Defines whether to alert on upward, downward, or both directions of price movement
    # Why: Users may only care about price increases (buying) or decreases (selling)
    # How: Used by spike, sustained, and threshold alerts to filter which movements trigger
    DIRECTION_CHOICES = [
        ('up', 'Up'),
        ('down', 'Down'),
        ('both', 'Both'),
    ]
    
    # ABOVE_BELOW_CHOICES: Legacy field choices (unused, kept for backwards compatibility)
    ABOVE_BELOW_CHOICES = [
        ('above', 'Above'),
        ('below', 'Below'),
    ]
    
    # REFERENCE_CHOICES: Options for which price to use as reference for calculations
    # What: Defines whether to use high (instant sell), low (instant buy), or average price
    # Why: Different trading strategies require different price references
    # How: Used by spike/threshold alerts to determine which current price to compare against
    REFERENCE_CHOICES = [
        ('high', 'High Price'),
        ('low', 'Low Price'),
        ('average', 'Average Price'),  # Average of high and low prices
    ]

    # ALERT_CHOICES: All available alert types in the system
    # What: Defines the different types of alerts users can create
    # Why: Each type has different triggering logic and configuration options
    ALERT_CHOICES = [
        # NOTE: "Above Threshold" and "Below Threshold" were intentionally removed.
        # What: The remaining supported alert types.
        # Why: Django uses this to validate forms/admin and to keep the UI constrained to valid types.
        # How: Only include alert types that still have UI + evaluation logic.
        ('spread', 'Spread'),
        ('spike', 'Spike'),
        ('sustained', 'Sustained Move'),
        ('threshold', 'Threshold'),  # Percentage or value-based threshold from reference price
    ]
    
    # THRESHOLD_TYPE_CHOICES: Options for how threshold alerts calculate their trigger condition
    # What: Defines whether threshold is measured as a percentage change or absolute value change
    # Why: Users may want to track "10% increase" or "1000gp increase" depending on the item
    # How: Used by threshold alerts to determine calculation method
    THRESHOLD_TYPE_CHOICES = [
        ('percentage', 'Percentage'),  # Threshold as % change from reference price
        ('value', 'Value'),  # Threshold as absolute gp change from reference price
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    alert_name = models.CharField(max_length=255, default='Default')
    # type: The alert type selector (validated by ALERT_CHOICES)
    # What: Stores which alert evaluation strategy to use (spread/spike/sustained/threshold).
    # Why: We removed legacy above/below alert types; default must be a supported type to avoid invalid forms.
    # How: Default is set to 'threshold' because it is the closest modern replacement for value/percentage triggers.
    type = models.CharField(max_length=10, null=True, choices=ALERT_CHOICES, default='threshold')
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, blank=True, null=True)
    # unused field
    above_below = models.CharField(max_length=10, choices=ABOVE_BELOW_CHOICES, blank=True, null=True)
    item_name = models.CharField(max_length=255, blank=True, null=True, default=None)
    item_id = models.IntegerField(blank=True, null=True, default=None)
    price = models.IntegerField(blank=True, null=True, default=None)
    percentage = models.FloatField(blank=True, null=True, default=None)
    is_all_items = models.BooleanField(default=False, blank=True, null=True)
    # reference: The price type to use as the baseline for spike/threshold comparisons
    # What: Stores which price reference the alert should use ('high', 'low', or 'average')
    # Why: Users may want to compare against different price points depending on their trading strategy
    # How: When evaluating the alert, this field determines which current price to fetch for comparison
    # Note: max_length=7 to accommodate 'average' (the longest choice value)
    reference = models.CharField(max_length=7, choices=REFERENCE_CHOICES, blank=True, null=True, default=None)
    is_triggered = models.BooleanField(default=False, blank=True, null=True)
    is_active = models.BooleanField(default=True, blank=True, null=True)
    is_dismissed = models.BooleanField(default=False, blank=True, null=True)
    
    # show_notification: Controls whether this alert shows a notification banner when triggered
    # What: Boolean flag to enable/disable notification display for this alert
    # Why: Users may want to track alerts without seeing notifications (e.g., just check detail page)
    # How: When False, is_dismissed is always set to True so notification never appears
    show_notification = models.BooleanField(default=True, blank=True, null=True)
    
    triggered_data = models.TextField(blank=True, null=True, default=None)  # JSON string for spread all items data
    created_at = models.DateTimeField(auto_now_add=True)
    minimum_price = models.IntegerField(blank=True, null=True, default=None)
    maximum_price = models.IntegerField(blank=True, null=True, default=None)
    email_notification = models.BooleanField(default=False)
    groups = models.ManyToManyField(AlertGroup, blank=True, related_name='alerts')
    triggered_at = models.DateTimeField(blank=True, null=True, default=None)
    time_frame = models.IntegerField(blank=True, null=True, default=None)  # Time window in minutes (for sustained alerts)
    
    # Sustained Move alert fields
    min_consecutive_moves = models.IntegerField(blank=True, null=True, default=None)  # Minimum number of consecutive price moves
    min_move_percentage = models.FloatField(blank=True, null=True, default=None)  # Minimum % change to count as a move
    volatility_buffer_size = models.IntegerField(blank=True, null=True, default=None)  # N - rolling buffer size for volatility
    volatility_multiplier = models.FloatField(blank=True, null=True, default=None)  # K - strength multiplier
    min_volume = models.IntegerField(blank=True, null=True, default=None)  # Minimum volume requirement
    sustained_item_ids = models.TextField(blank=True, null=True, default=None)  # JSON array of item IDs for multi-item sustained alerts
    
    # Generic item_ids field for multi-item alerts (e.g., spread alerts with specific items, threshold alerts)
    # What: Stores a JSON array of item IDs that this alert should check against
    # Why: Allows alerts like "spread" and "threshold" to target multiple specific items instead of just one or all
    # How: JSON string like "[123, 456, 789]" parsed when checking the alert
    item_ids = models.TextField(blank=True, null=True, default=None)
    
    # Threshold alert specific field
    # threshold_type: Determines how the threshold is calculated for threshold alerts
    # What: Stores whether the threshold is measured as 'percentage' or 'value' (absolute gp)
    # Why: Users may want different measurement types depending on the item price and their trading strategy
    # How: When 'percentage', threshold is calculated as % change from reference; when 'value', as gp change
    threshold_type = models.CharField(max_length=10, choices=[('percentage', 'Percentage'), ('value', 'Value')], blank=True, null=True, default=None)
    
    # target_price: The target price for value-based threshold alerts (single item only)
    # What: Stores the target price that the current price is compared against
    # Why: For value-based thresholds, users specify an exact price they want to be alerted at
    # How: When threshold_type='value', alert triggers when current price crosses this value
    #      Set to null when threshold_type is changed to 'percentage'
    # Note: Only valid for single-item alerts; multi-item/all-items must use percentage-based thresholds
    target_price = models.IntegerField(blank=True, null=True, default=None)
    
    # reference_prices: JSON dictionary storing baseline prices for percentage-based threshold alerts
    # What: Stores per-item reference prices captured at alert creation or item addition time
    # Why: Percentage-based thresholds need a baseline to calculate the % change from
    #      Each item has its own baseline since items have different prices
    # How: JSON dict like {"6737": 1500000, "11802": 25000000} mapping item_id -> baseline price
    #      For all-items mode, stores baselines for all items that met min/max filters at creation
    #      For specific items, stores baselines only for selected items
    # Note: Prices are stored using the reference type (high/low/average) specified by the user
    reference_prices = models.TextField(blank=True, null=True, default=None)
    
    # Pressure filter fields for sustained alerts
    PRESSURE_STRENGTH_CHOICES = [
        ('strong', 'Strong'),
        ('moderate', 'Moderate'),
        ('weak', 'Weak'),
    ]
    min_pressure_strength = models.CharField(max_length=10, choices=PRESSURE_STRENGTH_CHOICES, blank=True, null=True, default=None)
    min_pressure_spread_pct = models.FloatField(blank=True, null=True, default=None)  # Minimum spread % for pressure check
    
    # =============================================================================
    # SPIKE ALERT BASELINE TRACKING FIELDS
    # =============================================================================
    # baseline_prices: JSON dictionary storing per-item baseline prices for spike alerts
    # What: Stores the baseline price for each monitored item at the point in time [timeframe] ago
    # Why: Spike alerts use a rolling window comparison - comparing current price to price from X minutes ago
    #      This field stores the initial baseline captured at alert creation, which will be updated
    #      by the check_alerts command as the rolling window moves forward
    # How: JSON dict like {"6737": {"price": 1500000, "timestamp": 1706012400}, ...}
    #      - price: The baseline price value
    #      - timestamp: Unix timestamp when this baseline was recorded
    # Note: For single-item spike alerts, this stores data for just that one item
    #       For multi-item spike alerts, stores data for all monitored items
    #       For all-items spike alerts, baselines are managed entirely in check_alerts.py price_history
    baseline_prices = models.TextField(blank=True, null=True, default=None)
    
    # baseline_method: Determines how the baseline price is calculated for spike comparisons
    # What: Specifies the method used to determine the baseline price within the rolling window
    # Why: Provides extensibility for different comparison strategies users may prefer:
    #      - 'single_point': Compare to price at exactly [timeframe] ago (default, implemented)
    #      - 'average': Compare to average price around that time point (future enhancement)
    #      - 'min_max': Compare to min or max price in the window (future enhancement)
    # How: Used by check_alerts.py to determine which baseline calculation to apply
    # Note: Currently only 'single_point' is implemented; other methods are placeholders for future
    BASELINE_METHOD_CHOICES = [
        ('single_point', 'Single Point'),   # Price at exactly [timeframe] ago
        ('average', 'Window Average'),       # Future: Average of prices around baseline point
        ('min_max', 'Min/Max'),              # Future: Min or max price in window
    ]
    baseline_method = models.CharField(
        max_length=15, 
        choices=BASELINE_METHOD_CHOICES, 
        blank=True, 
        null=True, 
        default='single_point'
    )
    
    def _format_time_frame(self, minutes_value=None):
        try:
            minutes = int(minutes_value) if minutes_value is not None else (int(self.price) if self.price is not None else None)
        except (TypeError, ValueError):
            minutes = None
        if minutes is None or minutes < 0:
            return "N/A"
        days, rem = divmod(minutes, 1440)
        hours, mins = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if mins or not parts:
            parts.append(f"{mins} minute{'s' if mins != 1 else ''}")
        return ' '.join(parts)

    @property
    def time_frame_display(self):
        return self._format_time_frame()
    
    def __str__(self):
        if self.type == 'spread':
            # What: Returns a human-readable string representation for spread alerts
            # Why: Needed for admin display and debugging
            # How: Checks is_all_items, then item_ids for multi-item, then falls back to single item
            if self.is_all_items:
                return f"All items with a spread >= {self.percentage}%"
            elif self.item_ids:
                # Multi-item spread alert - show count of items being monitored
                import json
                try:
                    ids = json.loads(self.item_ids)
                    count = len(ids) if isinstance(ids, list) else 1
                    if count == 1:
                        target = self.item_name or "1 item"
                    else:
                        target = f"{count} items"
                except:
                    target = self.item_name or "Unknown"
                return f"{target} spread >= {self.percentage}%"
            return f"{self.item_name} spread >= {self.percentage}%"
        if self.type == 'spike':
            # What: Returns a human-readable string representation for spike alerts
            # Why: Needed for admin display, alert list, and debugging
            # How: Checks is_all_items, then item_ids for multi-item, then falls back to single item
            frame = self._format_time_frame()
            perc = f"{self.percentage}%" if self.percentage is not None else "N/A"
            if self.is_all_items:
                return f"All items spike {perc} within {frame}"
            elif self.item_ids:
                # Multi-item spike alert - show count of items being monitored
                import json
                try:
                    ids = json.loads(self.item_ids)
                    count = len(ids) if isinstance(ids, list) else 1
                    if count == 1:
                        target = self.item_name or "1 item"
                    else:
                        target = f"{count} items"
                except:
                    target = self.item_name or "Unknown"
                return f"{target} spike {perc} within {frame}"
            target = self.item_name or "Unknown item"
            return f"{target} spike {perc} within {frame}"
        if self.type == 'sustained':
            frame = self._format_time_frame(self.time_frame)
            moves = self.min_consecutive_moves or 0
            direction = (self.direction or 'both').capitalize()
            if self.is_all_items:
                return f"All items sustained {direction} ({moves} moves in {frame})"
            elif self.sustained_item_ids:
                import json
                try:
                    ids = json.loads(self.sustained_item_ids)
                    count = len(ids) if isinstance(ids, list) else 1
                    if count == 1:
                        target = self.item_name or "1 item"
                    else:
                        target = f"{count} items"
                except:
                    target = self.item_name or "Unknown"
                return f"{target} sustained {direction} ({moves} moves in {frame})"
            else:
                target = self.item_name or "Unknown item"
                return f"{target} sustained {direction} ({moves} moves in {frame})"
        # Threshold alert: displays target, direction, threshold value/percentage, and reference price
        # What: Returns a human-readable string representation for threshold alerts
        # Why: Users need to quickly understand what the alert is tracking
        # How: Formats based on threshold_type (percentage vs value) and tracks items (all vs specific)
        if self.type == 'threshold':
            direction = (self.direction or 'up').capitalize()
            threshold_type = self.threshold_type or 'percentage'
            reference = (self.reference or 'high').capitalize()
            
            # =============================================================================
            # DETERMINE THRESHOLD VALUE BASED ON TYPE
            # =============================================================================
            # What: Gets the correct threshold value depending on whether this is a percentage or value alert
            # Why: Percentage alerts store their value in self.percentage, but value-based alerts store
            #      their target price in self.target_price - using the wrong field causes display bugs
            # How: Check threshold_type and use the appropriate field:
            #      - 'percentage': Use self.percentage (e.g., 5 for "5% change")
            #      - 'value': Use self.target_price (e.g., 1500000 for "above 1,500,000 gp")
            if threshold_type == 'percentage':
                threshold_val = self.percentage if self.percentage is not None else 0
                threshold_str = f"{threshold_val}%"
            else:
                # Value-based threshold uses target_price, not percentage
                threshold_val = self.target_price if self.target_price is not None else 0
                threshold_str = f"{int(threshold_val):,} gp"
            
            # Determine target (all items, multiple specific, or single item)
            if self.is_all_items:
                target = "All items"
            elif self.item_ids:
                import json
                try:
                    ids = json.loads(self.item_ids)
                    count = len(ids) if isinstance(ids, list) else 1
                    if count == 1:
                        target = self.item_name or "1 item"
                    else:
                        target = f"{count} items"
                except:
                    target = self.item_name or "Unknown"
            else:
                target = self.item_name or "Unknown item"
            
            if direction == "Up":
                return f"{target}  above {threshold_str} ({reference})"
            else:
                return f"{target}  below {threshold_str} ({reference})"
        if self.is_all_items:
            return f"All items {self.type} {self.price:,} ({self.reference})"
        return f"{self.item_name} {self.type} {self.price:,} ({self.reference})"

    def triggered_text(self):
        # What: Returns a human-readable description of what triggered the alert
        # Why: Displayed to users when viewing triggered alerts
        # How: Parses triggered_data JSON and formats based on alert type
        if self.type == "spread":
            if self.is_all_items:
                return f"Price spread above {self.percentage}% Triggered. Click for details"
            elif self.item_ids and self.triggered_data:
                # Multi-item spread alert - show how many items have triggered
                import json
                try:
                    triggered_items = json.loads(self.triggered_data)
                    total_items = json.loads(self.item_ids)
                    triggered_count = len(triggered_items) if isinstance(triggered_items, list) else 0
                    total_count = len(total_items) if isinstance(total_items, list) else 0
                    return f"Spread >= {self.percentage}% on {triggered_count}/{total_count} items. Click for details"
                except Exception:
                    pass
            return f"{self.item_name} spread has reached {self.percentage}% or higher"
        # item_price: Current price fetched for display for alert types that need a spot-price in messaging
        # What: Fetches a current price using the alert's reference type (high/low/average)
        # Why: Some alert types (like spike) may include a reference price in messaging; we keep the helper
        #      call here because it is shared and inexpensive, but we removed the legacy above/below branches.
        # How: get_item_price() handles the reference type selection.
        item_price = get_item_price(self.item_id, self.reference)
        price_formatted = f"{item_price:,}" if item_price else str(item_price)
        if self.type == "spike":
            # What: Returns a human-readable description of what triggered the spike alert
            # Why: Users need to understand which items spiked and by how much
            # How: Parses triggered_data JSON and formats based on scope (all/multi/single)
            frame = self._format_time_frame()
            perc = f"{self.percentage:.1f}" if self.percentage is not None else "N/A"
            
            # Determine target description based on alert scope
            if self.is_all_items:
                target = "All items"
            elif self.item_ids:
                # Multi-item spike alert
                import json
                try:
                    ids = json.loads(self.item_ids)
                    count = len(ids) if isinstance(ids, list) else 1
                    target = f"{count} items" if count > 1 else self.item_name
                except:
                    target = self.item_name
            else:
                target = self.item_name
            
            base = f"{target} spike {perc}% within {frame}"
            
            # For multi-item or all-items spike alerts, show triggered count
            if (self.is_all_items or self.item_ids) and self.triggered_data:
                import json
                try:
                    data = json.loads(self.triggered_data)
                    if isinstance(data, list):
                        triggered_count = len(data)
                        if self.item_ids:
                            # Multi-item: show triggered/total
                            total_items = json.loads(self.item_ids)
                            total_count = len(total_items) if isinstance(total_items, list) else 0
                            return f"Spike >= {perc}% on {triggered_count}/{total_count} items. Click for details"
                        else:
                            # All items: just show count
                            return f"{base} ({triggered_count} item(s) matched)"
                except Exception:
                    pass
            return base
        if self.type == "sustained":
            if self.triggered_data:
                import json
                try:
                    data = json.loads(self.triggered_data)
                    item_name = data.get('item_name', self.item_name or 'Unknown')
                    streak_dir = data.get('streak_direction', 'up')
                    total_move = data.get('total_move_percent', 0)
                    streak_count = data.get('streak_count', 0)
                    direction_word = "up" if streak_dir == "up" else "down"
                    return f"{item_name} moved {direction_word} {total_move:.2f}% over {streak_count} consecutive moves"
                except Exception:
                    pass
            # Fallback if no triggered_data
            frame = self._format_time_frame(self.time_frame)
            moves = self.min_consecutive_moves or 0
            direction = (self.direction or 'both').capitalize()
            return f"{self.item_name} sustained {direction} move triggered ({moves} moves in {frame})"
        # Threshold alert triggered text
        # What: Returns a description of what triggered the threshold alert
        # Why: Users need to understand which items triggered and by how much
        # How: Parses triggered_data JSON and formats based on items and threshold type
        if self.type == "threshold":
            direction = self.direction or 'up'
            threshold_type = self.threshold_type or 'percentage'
            reference = self.reference or 'high'
            
            # =============================================================================
            # DETERMINE THRESHOLD VALUE BASED ON TYPE
            # =============================================================================
            # What: Gets the correct threshold value depending on whether this is a percentage or value alert
            # Why: Percentage alerts store their value in self.percentage, but value-based alerts store
            #      their target price in self.target_price - using the wrong field causes display bugs
            # How: Check threshold_type and use the appropriate field:
            #      - 'percentage': Use self.percentage (e.g., 5 for "5% change")
            #      - 'value': Use self.target_price (e.g., 1500000 for "above 1,500,000 gp")
            if threshold_type == 'percentage':
                threshold_val = self.percentage if self.percentage is not None else 0
                threshold_str = f"{threshold_val}%"
            else:
                # Value-based threshold uses target_price, not percentage
                threshold_val = self.target_price if self.target_price is not None else 0
                threshold_str = f"{int(threshold_val):,} gp"
            
            direction_word = "up" if direction == "up" else "down"
            
            # Check for multi-item triggered data
            if (self.is_all_items or self.item_ids) and self.triggered_data:
                import json
                try:
                    triggered_items = json.loads(self.triggered_data)
                    if self.is_all_items:
                        count = len(triggered_items) if isinstance(triggered_items, list) else 0
                        return f"Threshold {direction_word} {threshold_str} triggered on {count} item(s). Click for details"
                    else:
                        total_items = json.loads(self.item_ids) if self.item_ids else []
                        triggered_count = len(triggered_items) if isinstance(triggered_items, list) else 0
                        total_count = len(total_items) if isinstance(total_items, list) else 0
                        return f"Threshold {direction_word} {threshold_str} triggered on {triggered_count}/{total_count} items. Click for details"
                except Exception:
                    pass
            
            # Single item threshold
            item_price = get_item_price(self.item_id, self.reference)
            price_formatted = f"{item_price:,}" if item_price else str(item_price)
            return f"{self.item_name} moved {direction_word} by {threshold_str} to {price_formatted}"
        return f"Item price is now {price_formatted}"

    def cleanup_triggered_data_for_removed_items(self, removed_item_ids):
        """
        Removes triggered_data entries for items that have been removed from the alert.
        
        What: Filters the triggered_data JSON array to remove entries matching removed item IDs.
        Why: When a user removes items from a multi-item alert, the corresponding triggered data
             should also be removed to keep the data consistent and accurate.
        How: Parses triggered_data as JSON array, filters out entries where item_id is in the
             removed_item_ids set, then saves the filtered data back (or clears if empty).
        
        Args:
            removed_item_ids: A set or list of item IDs that were removed from the alert.
                              These IDs will be matched against 'item_id' field in each triggered_data entry.
        
        Returns:
            bool: True if any changes were made to triggered_data, False otherwise.
        
        Side Effects:
            - Updates self.triggered_data with filtered JSON (or None if all entries removed)
            - Sets self.is_triggered = False if all triggered entries are removed
            - Calls self.save() to persist the changes immediately
        """
        import json
        
        # Convert all removed IDs to strings for consistent comparison
        # Why: triggered_data stores item_id as strings (from check_alerts.py: 'item_id': item_id_str)
        #      but removed_item_ids may contain integers from the set subtraction
        # How: Convert everything to strings so "123" == str(123)
        removed_ids_as_str = set(str(x) for x in removed_item_ids)
        
        if not removed_ids_as_str or not self.triggered_data:
            return False
        
        try:
            # triggered_data_list: The parsed JSON array of triggered item data
            # Each entry should have an 'item_id' field identifying which item it belongs to
            triggered_data_list = json.loads(self.triggered_data)
            
            if not isinstance(triggered_data_list, list):
                # triggered_data is not a list (might be single item dict), don't modify
                return False
            
            # original_count: Number of triggered items before filtering
            original_count = len(triggered_data_list)
            
            # filtered_data: List of triggered items after removing entries for deleted items
            # We filter out any entry where item_id (converted to string) matches a removed ID
            # This handles both cases: item_id stored as int or string in triggered_data
            filtered_data = [
                item for item in triggered_data_list
                if str(item.get('item_id')) not in removed_ids_as_str
            ]
            
            # Check if any items were actually removed
            if len(filtered_data) == original_count:
                return False  # No changes made
            
            if filtered_data:
                # Some items remain - update with filtered list
                self.triggered_data = json.dumps(filtered_data)
            else:
                # All triggered items were removed - clear triggered state
                self.triggered_data = None
                self.is_triggered = False
            
            # Save immediately to persist the changes
            # Why: Ensures triggered_data cleanup is saved before any other operations
            self.save()
            
            return True  # Changes were made
            
        except (json.JSONDecodeError, TypeError, ValueError):
            # Invalid JSON or unexpected data format - don't modify
            return False
    
    def cleanup_reference_prices_for_removed_items(self, removed_item_ids):
        """
        Removes reference_prices entries for items that have been removed from the alert.
        
        What: Filters the reference_prices JSON dict to remove entries matching removed item IDs.
        Why: When a user removes items from a multi-item threshold alert, the corresponding
             reference prices should also be removed to keep the data consistent.
        How: Parses reference_prices as JSON dict, filters out entries where key (item_id) is in the
             removed_item_ids set, then saves the filtered data back (or clears if empty).
        
        Args:
            removed_item_ids: A set or list of item IDs that were removed from the alert.
                              These IDs will be matched against keys in the reference_prices dict.
        
        Returns:
            bool: True if any changes were made to reference_prices, False otherwise.
        
        Side Effects:
            - Updates self.reference_prices with filtered JSON (or None if all entries removed)
            - Calls self.save() to persist the changes immediately
        """
        import json
        
        # Convert all removed IDs to strings for consistent comparison
        # Why: reference_prices stores item_id as string keys (JSON standard for dict keys)
        #      but removed_item_ids may contain integers
        # How: Convert everything to strings so "123" == str(123)
        removed_ids_as_str = set(str(x) for x in removed_item_ids)
        
        if not removed_ids_as_str or not self.reference_prices:
            return False
        
        try:
            # reference_prices_dict: The parsed JSON dictionary of item_id -> baseline price
            reference_prices_dict = json.loads(self.reference_prices)
            
            if not isinstance(reference_prices_dict, dict):
                # reference_prices is not a dict, don't modify
                return False
            
            # original_count: Number of items in reference_prices before filtering
            original_count = len(reference_prices_dict)
            
            # filtered_prices: Dict of reference prices after removing entries for deleted items
            # We filter out any key (item_id as string) that matches a removed ID
            filtered_prices = {
                item_id: price for item_id, price in reference_prices_dict.items()
                if str(item_id) not in removed_ids_as_str
            }
            
            # Check if any items were actually removed
            if len(filtered_prices) == original_count:
                return False  # No changes made
            
            if filtered_prices:
                # Some items remain - update with filtered dict
                self.reference_prices = json.dumps(filtered_prices)
            else:
                # All items were removed - clear reference_prices
                self.reference_prices = None
            
            # Save immediately to persist the changes
            # Why: Ensures reference_prices cleanup is saved before any other operations
            self.save()
            
            return True  # Changes were made
            
        except (json.JSONDecodeError, TypeError, ValueError):
            # Invalid JSON or unexpected data format - don't modify
            return False


class FavoriteGroup(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']
        unique_together = ['user', 'name']

    def __str__(self):
        return self.name


class FavoriteItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    groups = models.ManyToManyField(FavoriteGroup, blank=True, related_name='items')
    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    added_at = models.DateTimeField(auto_now_add=True)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order', '-added_at']
        unique_together = ['user', 'item_id']

    def __str__(self):
        return self.item_name


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    def is_valid(self):
        from django.utils import timezone
        from datetime import timedelta
        # Token expires after 1 hour
        return not self.used and (timezone.now() - self.created_at) < timedelta(hours=1)

    def __str__(self):
        return f"Reset token for {self.user.email}"
