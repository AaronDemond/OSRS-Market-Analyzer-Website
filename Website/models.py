from django.db import models
from django.contrib.auth.models import User


def get_item_price(item_id, reference):
    """
    Fetch the high or low price for an item based on reference.
    
    What: Returns the current price for a single item.
    Why: Used by triggered_text() to display current prices in notification messages.
    How: Uses the cached get_all_current_prices() from views to avoid redundant API calls.
    
    PERFORMANCE FIX: Previously made a FULL external API call for EACH triggered alert.
    This was causing ~500-1000ms delay PER notification when loading the alerts page.
    Now uses the cached price data which is shared across all price lookups.
    
    Args:
        item_id: The OSRS item ID to look up
        reference: 'high' or 'low' - which price to return
    
    Returns:
        int: The price value, or None if not found
    """
    # Import here to avoid circular imports (views imports models)
    from Website.views import get_all_current_prices
    
    # Use the cached price data - this has a 5-second cache so won't hit API repeatedly
    all_prices = get_all_current_prices()
    
    price_data = all_prices.get(str(item_id))
    if price_data:
        if reference == 'high':
            return price_data.get('high')
        elif reference == 'low':
            return price_data.get('low')
    return None


def get_all_current_prices():
    """
    Wrapper function to get all current prices from views.
    
    What: Returns the full price dictionary from the cached API response.
    Why: Used by triggered_text() to display spread percentages with buy/sell prices.
    How: Imports and calls the cached get_all_current_prices() from views.
    
    Returns:
        dict: Dictionary mapping item_id (str) to {'high': int, 'low': int, ...}
    """
    # Import here to avoid circular imports (views imports models)
    from Website.views import get_all_current_prices as _get_all_prices
    return _get_all_prices()



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
        ('collective_move', 'Collective Move'),  # Average percentage change across multiple items
    ]
    
    # THRESHOLD_TYPE_CHOICES: Options for how threshold alerts calculate their trigger condition
    # What: Defines whether threshold is measured as a percentage change or absolute value change
    # Why: Users may want to track "10% increase" or "1000gp increase" depending on the item
    # How: Used by threshold alerts to determine calculation method
    THRESHOLD_TYPE_CHOICES = [
        ('percentage', 'Percentage'),  # Threshold as % change from reference price
        ('value', 'Value'),  # Threshold as absolute gp change from reference price
    ]
    
    # CALCULATION_METHOD_CHOICES: Options for how collective_move alerts calculate the average
    # What: Defines whether average is simple (arithmetic mean) or weighted by item value
    # Why: Simple mean treats all items equally; weighted mean gives more influence to high-value items
    # How: Used by collective_move alerts to determine averaging method
    CALCULATION_METHOD_CHOICES = [
        ('simple', 'Non Weighted'),  # Simple arithmetic mean - each item counts equally
        ('weighted', 'Weighted by Value'),  # Weighted by baseline value - expensive items count more
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    alert_name = models.CharField(max_length=255, default='Default')
    # type: The alert type selector (validated by ALERT_CHOICES)
    # What: Stores which alert evaluation strategy to use (spread/spike/sustained/threshold).
    # Why: We removed legacy above/below alert types; default must be a supported type to avoid invalid forms.
    # How: Default is set to 'threshold' because it is the closest modern replacement for value/percentage triggers.
    type = models.CharField(max_length=25, null=True, choices=ALERT_CHOICES, default='threshold')
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
    
    # =============================================================================
    # COLLECTIVE MOVE ALERT SPECIFIC FIELDS
    # =============================================================================
    # calculation_method: Determines how the average is calculated for collective_move alerts
    # What: Stores whether average is 'simple' (arithmetic mean) or 'weighted' (by baseline value)
    # Why: Simple mean treats all items equally; weighted gives more influence to expensive items
    #      Example: A 10% move on a 1B item affects weighted average more than 10% move on 10K item
    # How: When 'simple', average = sum(changes) / count
    #      When 'weighted', average = sum(change * baseline) / sum(baselines)
    # Note: Default is 'simple' for intuitive behavior; users can opt for weighted if desired
    calculation_method = models.CharField(
        max_length=10, 
        choices=[('simple', 'Non Weighted'), ('weighted', 'Weighted by Value')], 
        blank=True, 
        null=True, 
        default='simple'
    )
    
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
        """
        Returns a concise, human-readable string representation of the alert.
        
        What: Generates display text for alert notifications, list items, and admin views.
        Why: Users need to quickly understand what the alert is monitoring at a glance.
        How: Format is "[target] [type] [threshold/value] ([timeframe/reference])"
        
        Examples:
            Single item:  "Abyssal whip spread ≥5%"
            Multi-item:   "3 items spread ≥5%"
            All items:    "All items spread ≥5%"
            Threshold:    "Abyssal whip above 2,500,000 gp (High)"
            Spike:        "Abyssal whip spike ≥10% (1hr)"
            Sustained:    "Abyssal whip sustained Up (5 moves)"
        """
        import json
        
        # Helper to get target description (item name, count, or "All items")
        def get_target(item_ids_field=None):
            if self.is_all_items:
                return "All items"
            
            ids_to_check = item_ids_field or self.item_ids
            if ids_to_check:
                try:
                    ids = json.loads(ids_to_check)
                    count = len(ids) if isinstance(ids, list) else 1
                    if count == 1:
                        return self.item_name or "1 item"
                    else:
                        return f"{count} items"
                except:
                    pass
            return self.item_name or "Unknown item"
        
        # =========================================================================
        # SPREAD ALERTS: "[target] spread ≥[percentage]%"
        # =========================================================================
        if self.type == 'spread':
            target = get_target()
            return f"{target} spread ≥{self.percentage}%"
        
        # =========================================================================
        # SPIKE ALERTS: "[target] spike ≥[percentage]% ([timeframe])"
        # =========================================================================
        if self.type == 'spike':
            target = get_target()
            frame = self._format_time_frame()
            perc = f"{self.percentage}%" if self.percentage is not None else "N/A"
            return f"{target} spike ≥{perc} ({frame})"
        
        # =========================================================================
        # SUSTAINED ALERTS: "[target] sustained [direction] ([moves] moves)"
        # =========================================================================
        if self.type == 'sustained':
            target = get_target(self.sustained_item_ids)
            moves = self.min_consecutive_moves or 0
            direction = (self.direction or 'both').capitalize()
            if direction == 'Both':
                return f"{target} sustained in both directions ({moves} moves)"
            else:
                return f"{target} sustained {direction} ({moves} moves)"
        
        # =========================================================================
        # THRESHOLD ALERTS: "[target] [above/below] [value] ([reference])"
        # =========================================================================
        if self.type == 'threshold':
            target = get_target()
            direction = "above" if (self.direction or 'up') == 'up' else "below"
            threshold_type = self.threshold_type or 'percentage'
            reference = (self.reference or 'high').capitalize()
            
            # Format threshold value based on type (percentage vs gp value)
            if threshold_type == 'percentage':
                threshold_val = self.percentage if self.percentage is not None else 0
                threshold_str = f"≥{threshold_val}%"
            else:
                threshold_val = self.target_price if self.target_price is not None else 0
                threshold_str = f"{int(threshold_val):,} gp"
            
            return f"{target} {direction} {threshold_str} ({reference})"
        
        # =========================================================================
        # COLLECTIVE MOVE ALERTS: "[target] collective [direction] ≥[percentage]% ([method])"
        # =========================================================================
        # What: Display format for collective_move alerts showing key configuration
        # Why: Users need to quickly understand what the alert monitors at a glance
        # How: Shows target items, direction, threshold percentage, and calculation method
        if self.type == 'collective_move':
            target = get_target()
            direction = (self.direction or 'both').capitalize()
            perc = f"{self.percentage}%" if self.percentage is not None else "N/A"
            # Display calculation method in human-readable form
            method = 'Weighted' if self.calculation_method == 'weighted' else 'Simple'
            
            if direction == 'Both':
                return f"{target} collective ≥{perc} in any direction ({method})"
            else:
                return f"{target} collective {direction} ≥{perc} ({method})"
        
        # =========================================================================
        # FALLBACK: Generic format for unknown types
        # =========================================================================
        target = get_target()
        return f"{target} {self.type} alert"

    def triggered_text(self):
        """
        Returns the notification text shown when an alert triggers.
        
        What: Returns the alert's display text for notification banners.
        Why: Users need to quickly identify which alert triggered.
        How: If user set a custom name (not "Default"), use that name.
             Otherwise, fall back to the auto-generated __str__() format.
        
        Examples:
            Custom name:  "My Herb Alert"
            Default:      "Abyssal whip spread ≥5%"
        """
        # Check if user has set a custom name (not empty and not "Default")
        # alert_name: User-defined custom name for the alert
        # Why: Users may want a memorable name like "Herb Flipping" instead of auto-generated text
        if self.alert_name and self.alert_name.strip() and self.alert_name.strip().lower() != 'default':
            return self.alert_name.strip()
        
        # Fall back to auto-generated description
        return str(self)

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


# =============================================================================
# ITEM COLLECTION MODEL
# =============================================================================
# What: Stores named collections of items that users can quickly apply to alerts
# Why: Users often want to monitor the same group of items across multiple alerts
#      (e.g., "High-value weapons", "Skilling supplies", "Boss drops"). This model
#      allows them to save a selection of items once and reuse it for future alerts
#      without having to search and select each item individually every time.
# How: Stores item IDs and names as JSON arrays, linked to a user account.
#      Collections are accessed via the "Item Collection" button on the alerts page,
#      which opens a modal allowing users to create, select, and apply collections.
# =============================================================================

class ItemCollection(models.Model):
    """
    ItemCollection Model
    ====================
    What: Represents a user-defined collection of OSRS items for quick alert setup.
    Why: Streamlines the process of creating multi-item alerts by allowing users to
         save and reuse item selections across different alerts.
    How: Stores item data as JSON arrays; user selects collection via modal UI.
    
    Fields:
        user: The owner of this collection (required - no anonymous collections)
        name: User-defined name for the collection (e.g., "GWD Drops", "Flip Items")
        item_ids: JSON array of item IDs (e.g., "[4151, 11802, 12924]")
        item_names: JSON array of item names for display without API lookup
        created_at: Timestamp when collection was created
        updated_at: Timestamp when collection was last modified
    
    Usage:
        1. User clicks "Item Collection" button above item selector
        2. Modal shows existing collections or option to create new one
        3. User can apply a collection to quickly populate the item selector
        4. Collections persist and can be reused across multiple alerts
    """
    
    # user: The owner of this collection
    # What: Foreign key linking collection to a specific user account
    # Why: Collections are personal to each user; different users have different needs
    # How: CASCADE delete ensures collections are removed when user account is deleted
    # Note: NOT nullable - this feature is only available to authenticated users
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # name: User-defined name for the collection
    # What: A descriptive name chosen by the user to identify this collection
    # Why: Users need to distinguish between multiple collections they've created
    # How: Displayed in the collection list modal; must be unique per user
    # Note: Max 100 chars provides enough room for descriptive names
    name = models.CharField(max_length=100)
    
    # item_ids: JSON array storing the item IDs in this collection
    # What: Stores item IDs as a JSON-formatted string array (e.g., "[4151, 11802]")
    # Why: Items are identified by their OSRS item ID for reliable matching
    # How: Parsed as JSON when applying collection; stored as text for flexibility
    # Note: Uses TextField to accommodate collections with many items
    item_ids = models.TextField()
    
    # item_names: JSON array storing item names for display
    # What: Stores item names as a JSON-formatted string array
    # Why: Allows displaying item names in the UI without needing to look them up
    #      from the item mapping every time the collection is shown
    # How: Captured at collection creation time; displayed in preview card
    # Note: Names are stored in the same order as item_ids for index matching
    item_names = models.TextField()
    
    # created_at: Timestamp when collection was created
    # What: Auto-set datetime when the collection record is first created
    # Why: Useful for sorting collections and potential future features
    # How: auto_now_add=True sets this once on initial save
    created_at = models.DateTimeField(auto_now_add=True)
    
    # updated_at: Timestamp when collection was last modified
    # What: Auto-updated datetime whenever the collection is saved
    # Why: Tracks when collection was last changed (for future edit feature)
    # How: auto_now=True updates this on every save
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # unique_together: Prevent duplicate collection names for the same user
        # What: Database constraint ensuring user+name combination is unique
        # Why: Users shouldn't have two collections with the same name (confusing)
        # How: Django enforces this at the database level
        unique_together = ['user', 'name']
        
        # ordering: Default sort order when querying collections
        # What: Sort alphabetically by name by default
        # Why: Makes it easy for users to find collections in the modal
        ordering = ['name']

    def __str__(self):
        """String representation showing collection name and item count."""
        import json
        try:
            item_count = len(json.loads(self.item_ids))
        except (json.JSONDecodeError, TypeError):
            item_count = 0
        return f"{self.name} ({item_count} items)"
    
    def get_item_count(self):
        """
        Returns the number of items in this collection.
        
        What: Parses item_ids JSON and returns the count
        Why: Used in UI to display "X items" badge on collection cards
        How: JSON parse the item_ids array and return its length
        
        Returns:
            int: Number of items in the collection, or 0 if parsing fails
        """
        import json
        try:
            return len(json.loads(self.item_ids))
        except (json.JSONDecodeError, TypeError):
            return 0


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


# =============================================================================
# ITEM PRICE DATA - Historical Price Storage
# =============================================================================
# What: Stores daily price snapshots for all OSRS items
# Why: Enables historical analysis, trending calculations, and future features
#      without needing to re-fetch data from external API
# How: Background script (update_trending.py) populates this table hourly
# Note: One row per item per day - stores raw API data for maximum flexibility

class ItemPriceSnapshot(models.Model):
    """
    Stores price data snapshots for OSRS items (every 4 hours).
    
    What: A price snapshot for one item at a specific time
    Why: Persistent storage of price history for analytics and future features
    How: Populated by scripts/update_trending.py background task every 4 hours
    
    Data Sources:
        - prices.runescape.wiki API with timestep=24h
        - Stores both high and low prices plus volumes
        - New snapshot created every 4 hours (6 per day)
    
    Usage Examples:
        - Calculate daily/weekly/monthly price trends
        - Generate price charts
        - Identify market patterns
        - Power trending items feature (gainers/losers)
    """
    
    # item_id: OSRS item ID from the Wiki API
    item_id = models.IntegerField(db_index=True)
    
    # item_name: Human-readable item name (denormalized for convenience)
    item_name = models.CharField(max_length=255)
    
    # timestamp: When this snapshot was taken (every 4 hours)
    timestamp = models.DateTimeField(db_index=True)
    
    # avg_high_price: Average instant-buy price (in GP)
    avg_high_price = models.IntegerField(null=True, blank=True)
    
    # avg_low_price: Average instant-sell price (in GP)
    avg_low_price = models.IntegerField(null=True, blank=True)
    
    # high_price_volume: Number of items instant-bought
    high_price_volume = models.BigIntegerField(default=0)
    
    # low_price_volume: Number of items instant-sold
    low_price_volume = models.BigIntegerField(default=0)
    
    # created_at: When this record was inserted (for debugging/auditing)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        # Ensure one snapshot per item per timestamp
        unique_together = ['item_id', 'timestamp']
        # Default ordering: most recent first
        ordering = ['-timestamp', 'item_name']
        # Index for common queries
        indexes = [
            models.Index(fields=['item_id', '-timestamp']),
            models.Index(fields=['-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.item_name} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def avg_price(self):
        """
        Calculate average price (midpoint of high and low).
        
        What: Returns the midpoint price for this snapshot
        Why: Commonly used metric for price comparisons
        How: (high + low) / 2, handling None values
        """
        if self.avg_high_price and self.avg_low_price:
            return (self.avg_high_price + self.avg_low_price) // 2
        return self.avg_high_price or self.avg_low_price
    
    @property
    def total_volume(self):
        """
        Calculate total items traded.
        
        What: Returns sum of buy and sell volumes
        Why: Useful for filtering by activity level
        How: high_volume + low_volume
        """
        return self.high_price_volume + self.low_price_volume
    
    @property
    def volume_gp(self):
        """
        Calculate total GP traded.
        
        What: Returns approximate GP value of all trades
        Why: Better measure of market activity than item count
        How: (high_vol * high_price) + (low_vol * low_price)
        """
        high_gp = (self.high_price_volume or 0) * (self.avg_high_price or 0)
        low_gp = (self.low_price_volume or 0) * (self.avg_low_price or 0)
        return high_gp + low_gp



