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
        ('flip_confidence', 'Flip Confidence'),  # Confidence score for flipping items (0-100)
        ('dump', 'Dump'),  # Detects sharp sell-off below fair value on liquid items
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
    # FLIP CONFIDENCE ALERT SPECIFIC FIELDS
    # =============================================================================
    # What: Fields that configure the flip confidence scoring algorithm
    # Why: The flip confidence alert uses time-series data from the OSRS Wiki API to compute
    #      a 0-100 "flip confidence" score based on trend, buy/sell pressure, spread health,
    #      volume sufficiency, and price stability. Users need to configure the data source
    #      (timestep/lookback), the trigger condition (threshold/direction/delta), and
    #      optionally tune the scoring weights.
    # How: These fields are stored on the Alert model and read by check_alerts.py when
    #      evaluating flip_confidence alerts.
    
    # =============================================================================
    # TIMESTEP CHOICES: The time bucket size for the OSRS Wiki timeseries endpoint
    # What: Defines available timestep options for fetching price history data
    # Why: Different timesteps provide different granularity of market data;
    #      5m gives very recent fine-grained data, 24h gives longer historical view
    # How: Maps to the OSRS Wiki API 'timestep' parameter (in seconds)
    # =============================================================================
    CONFIDENCE_TIMESTEP_CHOICES = [
        ('5m', '5 Minutes'),
        ('1h', '1 Hour'),
        ('6h', '6 Hours'),
        ('24h', '24 Hours'),
    ]
    
    # confidence_timestep: The time bucket size for fetching OSRS Wiki timeseries data
    # What: Controls the granularity of price data used in the confidence calculation
    # Why: Smaller timesteps (5m) capture recent micro-trends; larger ones (24h) capture macro-trends
    # How: Passed to the OSRS Wiki timeseries API as the 'timestep' parameter
    # Note: Default '1h' provides a good balance between granularity and data coverage
    confidence_timestep = models.CharField(
        max_length=5,
        choices=CONFIDENCE_TIMESTEP_CHOICES,
        blank=True,
        null=True,
        default=None
    )
    
    # confidence_lookback: Number of data buckets to include in the confidence calculation
    # What: How many time buckets (of size confidence_timestep) to fetch and analyze
    # Why: More buckets = more historical context but may dilute recent signals;
    #      fewer buckets = more responsive but potentially noisy. Must be >= 3 because
    #      the compute_flip_confidence function returns 0.0 with fewer than 3 data points.
    # How: Used to set the time range when querying the OSRS Wiki timeseries API
    # Note: Examples: 5m + 24 points = last 2 hours; 1h + 48 points = last 2 days
    confidence_lookback = models.IntegerField(blank=True, null=True, default=None)
    
    # confidence_threshold: The confidence score (0-100) that triggers the alert
    # What: The minimum flip confidence score required for the alert to fire
    # Why: Users want to be notified when an item's flip confidence exceeds their chosen level
    # How: After computing the score via compute_flip_confidence(), compare against this value
    # Note: Typical values might be 60-80; higher = more selective
    confidence_threshold = models.FloatField(blank=True, null=True, default=None)
    
    # =============================================================================
    # TRIGGER RULE CHOICES: How the confidence score is evaluated to fire the alert
    # What: Defines the comparison method for checking confidence against threshold
    # Why: Users may want different trigger behaviors:
    #      - 'crosses_above': Alert when score rises above threshold (standard)
    #      - 'delta_increase': Alert when score increases by >= threshold over last N checks
    # How: Used in check_alerts.py to select the appropriate comparison logic
    # =============================================================================
    CONFIDENCE_TRIGGER_CHOICES = [
        ('crosses_above', 'Score Crosses Above Threshold'),
        ('delta_increase', 'Score Increases By Threshold'),
    ]
    
    # confidence_trigger_rule: How the confidence score comparison is performed
    # What: Determines whether to alert on absolute score level or rate of change
    # Why: 'crosses_above' is intuitive for most users; 'delta_increase' catches momentum
    # How: 'crosses_above' fires when score >= threshold; 'delta_increase' fires when
    #      current_score - previous_score >= threshold
    confidence_trigger_rule = models.CharField(
        max_length=15,
        choices=CONFIDENCE_TRIGGER_CHOICES,
        blank=True,
        null=True,
        default=None
    )
    
    # confidence_min_spread_pct: Minimum spread percentage required before alert can fire
    # What: A floor on the spread (high-low)/low percentage to filter out low-margin items
    # Why: Even if confidence score is high, a tiny spread means no profit opportunity;
    #      this prevents false positives on items with good trend/volume but negligible margin
    # How: Checked before evaluating confidence; if current spread < this value, skip the item
    confidence_min_spread_pct = models.FloatField(blank=True, null=True, default=None)
    
    # confidence_min_volume: Minimum total GP volume across the lookback window
    # What: The minimum gold-piece value of all trades (buys + sells) across all
    #        timeseries buckets within the lookback window
    # Why: Raw trade counts are misleading — 500 trades of a 10gp item is negligible
    #      market activity, while 500 trades of a 10M item is enormous.  GP volume
    #      normalises across price tiers so the filter is meaningful for any item.
    # How: After fetching timeseries data, compute:
    #        GP volume = SUM(highPriceVolume * avgHighPrice) + SUM(lowPriceVolume * avgLowPrice)
    #      If the result is below this threshold, the item is skipped.
    # Note: BigIntegerField is required because GP volumes can easily exceed 2.1B
    #       (the max of a 32-bit int) for actively traded expensive items.
    confidence_min_volume = models.BigIntegerField(blank=True, null=True, default=None)
    
    # confidence_cooldown: Minutes to wait before re-alerting on the same item
    # What: Cooldown period (in minutes) after an alert fires before it can fire again
    # Why: Prevents notification spam when an item stays above the threshold for a while
    # How: After triggering, store triggered_at timestamp; skip re-evaluation until
    #      current_time - triggered_at >= cooldown minutes
    confidence_cooldown = models.IntegerField(blank=True, null=True, default=None)
    
    # confidence_sustained_count: Number of consecutive evaluations the condition must hold
    # What: Require the confidence score to be >= threshold for N consecutive checks
    # Why: Filters out transient spikes in confidence that may not represent real opportunities
    # How: Track a counter of consecutive passing evaluations; only trigger when counter >= this
    confidence_sustained_count = models.IntegerField(blank=True, null=True, default=None)
    
    # confidence_eval_interval: How often (in minutes) to re-evaluate this alert
    # What: The interval between confidence score recalculations
    # Why: Users may want less frequent checks to reduce noise; must be >= timestep
    # How: In check_alerts.py, track last evaluation time; skip if interval hasn't elapsed
    confidence_eval_interval = models.IntegerField(blank=True, null=True, default=None)
    
    # =============================================================================
    # ADVANCED WEIGHT FIELDS (for power users)
    # What: Allow users to override the default scoring weights used in compute_flip_confidence
    # Why: Different trading strategies may value different signals differently;
    #      e.g., a volume-focused trader may want to increase volume weight
    # How: If set, these weights replace the defaults (0.35, 0.25, 0.20, 0.10, 0.10)
    #      in the confidence calculation. Must sum to 1.0.
    # Note: These are shown under an "Advanced" toggle in the UI
    # =============================================================================
    
    # confidence_weight_trend: Weight for the trend sub-score (default: 0.35)
    confidence_weight_trend = models.FloatField(blank=True, null=True, default=None)
    
    # confidence_weight_pressure: Weight for the buy/sell pressure sub-score (default: 0.25)
    confidence_weight_pressure = models.FloatField(blank=True, null=True, default=None)
    
    # confidence_weight_spread: Weight for the spread health sub-score (default: 0.20)
    confidence_weight_spread = models.FloatField(blank=True, null=True, default=None)
    
    # confidence_weight_volume: Weight for the volume sufficiency sub-score (default: 0.10)
    confidence_weight_volume = models.FloatField(blank=True, null=True, default=None)

    # confidence_weight_stability: Weight for the stability sub-score (default: 0.10)
    # Note: This is implicitly 1.0 - sum(other weights) but stored for explicitness
    confidence_weight_stability = models.FloatField(blank=True, null=True, default=None)
    
    # confidence_last_scores: JSON dict storing per-item state for the confidence alert
    # What: Tracks the last computed confidence score, consecutive pass count, and last eval time
    # Why: Needed for delta_increase trigger rule (compare to previous score),
    #      sustained_count (track consecutive passes), and eval_interval (skip if too soon)
    # How: JSON like {"4151": {"score": 73.4, "consecutive": 3, "last_eval": 1706012400}, ...}
    confidence_last_scores = models.TextField(blank=True, null=True, default=None)
    
    # =============================================================================
    # DUMP ALERT SPECIFIC FIELDS
    # =============================================================================
    # What: Fields that configure the dump detection algorithm.
    # Why: The dump alert detects sharp sell-offs on liquid items by combining EWMA fair value,
    #      idiosyncratic shock (vs market drift), sell pressure, relative volume, and discount
    #      below fair value. Users can tune all thresholds via these fields.
    # How: These fields are stored on the Alert model and read by check_alerts.py when
    #      evaluating dump alerts. Basic fields are shown in the main form; advanced fields
    #      are hidden under an "Advanced" toggle in the UI.
    
    # -------------------------------------------------------------------------
    # BASIC DUMP FIELDS (shown in main form)
    # -------------------------------------------------------------------------
    
    # dump_discount_min: Minimum percentage discount below EWMA fair value to trigger
    # What: The floor on how far below fair value the avgLowPrice must be
    # Why: Filters out small, insignificant dips that aren't actionable
    # How: discount = (fair - avgLowPrice) / fair * 100; trigger if discount >= this value
    # Note: Default 3.0 means the item must be trading at least 3% below fair value
    dump_discount_min = models.FloatField(blank=True, null=True, default=None)
    
    # dump_shock_sigma: Shock sigma threshold for idiosyncratic return (negative = downward)
    # What: How many standard deviations the item's return must deviate from market drift
    # Why: Isolates item-specific crashes from general market movement
    # How: shock_sigma = (item_return - market_drift) / sqrt(ewma_variance);
    #      trigger if shock_sigma <= this value (e.g., -4 means 4 sigma down-shock)
    # Note: More negative = more extreme dump required = fewer false positives
    dump_shock_sigma = models.FloatField(blank=True, null=True, default=None)
    
    # dump_liquidity_floor: Minimum expected hourly GP volume for an item to be eligible
    # What: Items must have at least this much GP trading volume per hour to be considered
    # Why: Prevents alerts on illiquid items where prices are noisy and entry/exit is difficult
    # How: Checked against HourlyItemVolume via get_volume_from_timeseries()
    # Note: BigIntegerField because GP volumes can exceed 2.1B (32-bit int max)
    dump_liquidity_floor = models.BigIntegerField(blank=True, null=True, default=None)
    
    # dump_cooldown: Minutes to wait before re-alerting on the same item after a trigger
    # What: Cooldown period preventing notification spam on the same dump event
    # Why: A single dump event can persist across multiple 5m buckets; without cooldown,
    #      the same dump would fire every 30 seconds
    # How: After triggering, store cooldown_until timestamp per item in dump_state;
    #      skip re-evaluation until current_time >= cooldown_until
    dump_cooldown = models.IntegerField(blank=True, null=True, default=None)
    
    # -------------------------------------------------------------------------
    # ADVANCED DUMP FIELDS (hidden under "Advanced" toggle in UI)
    # -------------------------------------------------------------------------
    
    # dump_sell_ratio_min: Minimum sell-side ratio to qualify as a dump
    # What: The fraction of total volume that must be on the sell (low-price) side
    # Why: True dumps are sell-heavy; without this, organic two-sided price drops would trigger
    # How: sell_ratio = lowPriceVolume / (highPriceVolume + lowPriceVolume);
    #      trigger only if sell_ratio >= this value
    # Note: 0.70 means at least 70% of trades must be sells
    dump_sell_ratio_min = models.FloatField(blank=True, null=True, default=None)
    
    # dump_rel_vol_min: Minimum relative volume (current bucket vs EWMA expected)
    # What: How much higher the current bucket's volume must be compared to normal
    # Why: Dumps involve abnormally high activity; normal-volume price drops are organic
    # How: rel_vol = bucket_volume / ewma_expected_volume; trigger if rel_vol >= this value
    # Note: 2.5 means volume must be at least 2.5x the rolling average
    dump_rel_vol_min = models.FloatField(blank=True, null=True, default=None)
    
    # dump_fair_halflife: EWMA half-life in minutes for the fair value (mid price) calculation
    # What: Controls how quickly the fair value adapts to price changes
    # Why: Shorter half-life = more responsive to recent prices; longer = more stable anchor
    # How: alpha = 1 - exp(ln(0.5) / (halflife_minutes / 5))  (5 = bucket size in minutes)
    # Note: Default 120 minutes (2 hours) = 24 buckets half-life
    dump_fair_halflife = models.IntegerField(blank=True, null=True, default=None)
    
    # dump_vol_halflife: EWMA half-life in minutes for expected volume calculation
    # What: Controls how quickly the expected volume adapts to volume changes
    # Why: Longer half-life gives a more stable "normal volume" baseline for relative volume
    # How: Same alpha formula as fair_halflife, applied to bucket_volume EWMA
    # Note: Default 360 minutes (6 hours) = 72 buckets half-life
    dump_vol_halflife = models.IntegerField(blank=True, null=True, default=None)
    
    # dump_var_halflife: EWMA half-life in minutes for idiosyncratic return variance
    # What: Controls how quickly the variance estimate adapts to return volatility changes
    # Why: Used to normalize the shock sigma; shorter = more responsive to recent vol regime
    # How: Same alpha formula, applied to r_idio^2 EWMA
    # Note: Default 120 minutes (2 hours) = 24 buckets half-life
    dump_var_halflife = models.IntegerField(blank=True, null=True, default=None)
    
    # dump_confirmation_buckets: Number of consecutive 5m buckets the dump signal must persist
    # What: Requires the dump conditions to be met for M consecutive check cycles
    # Why: Prevents triggering on a single noisy bucket; confirms the dump is sustained
    # How: Track consecutive passes per item in dump_state; only trigger when count >= this
    # Note: Default 2 means conditions must hold for ~10 minutes (2 consecutive 5m buckets)
    dump_confirmation_buckets = models.IntegerField(blank=True, null=True, default=None)
    
    # dump_consistency_required: Whether to require both-side volume consistency
    # What: When True, requires at least 6 of the last 12 five-minute buckets to have
    #       both highPriceVolume > 0 AND lowPriceVolume > 0 for an item
    # Why: Prevents triggering on items where only one side is trading (manipulated/illiquid)
    # How: Query last 12 FiveMinTimeSeries rows; count rows with both sides > 0; skip if < 6
    # Note: Default True; advanced users can disable if they want to catch edge cases
    dump_consistency_required = models.BooleanField(default=True, blank=True, null=True)
    
    # -------------------------------------------------------------------------
    # DUMP STATE PERSISTENCE (Option B — persisted EWMA across cycles)
    # -------------------------------------------------------------------------
    
    # dump_state: JSON dict storing per-item EWMA state and tracking data
    # What: Persists running EWMA values and trigger state across check cycles
    # Why: Option B chosen for performance — computing EWMA from DB history each cycle
    #      would require thousands of DB reads for "all items" mode at scale
    # How: JSON dict keyed by item_id string:
    #      {
    #        "4151": {
    #          "fair": 1500000.0,        // EWMA of mid price
    #          "var_idio": 0.0004,       // EWMA of idiosyncratic return variance
    #          "expected_vol": 250.0,    // EWMA of bucket volume (trade count)
    #          "last_mid": 1495000.0,    // Previous cycle's mid price
    #          "consecutive": 2,         // Consecutive dump-condition passes
    #          "cooldown_until": 1706012400  // Unix timestamp when cooldown expires
    #        },
    #        ...
    #      }
    # Note: Initialized on first evaluation cycle; survives server restarts via DB persistence
    dump_state = models.TextField(blank=True, null=True, default=None)
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
        # FLIP CONFIDENCE ALERTS: "[target] confidence ≥[threshold] ([timestep])"
        # =========================================================================
        # What: Display format for flip_confidence alerts showing the key configuration
        # Why: Users need to quickly understand what the alert monitors at a glance
        # How: Shows target items, confidence threshold, and timestep setting
        if self.type == 'flip_confidence':
            target = get_target()
            threshold = self.confidence_threshold if self.confidence_threshold is not None else "N/A"
            timestep = self.confidence_timestep or '1h'
            trigger = self.confidence_trigger_rule or 'crosses_above'
            if trigger == 'delta_increase':
                return f"{target} confidence Δ≥{threshold} ({timestep})"
            return f"{target} confidence ≥{threshold} ({timestep})"
        
        # =========================================================================
        # DUMP ALERTS: "[target] dump ≥[discount]% discount (σ≤[sigma])"
        # =========================================================================
        # What: Display format for dump alerts showing the key trigger thresholds
        # Why: Users need to see the discount % and shock sigma at a glance
        # How: Shows target items, minimum discount percentage, and shock sigma threshold
        if self.type == 'dump':
            target = get_target()
            # discount: The minimum discount % below fair value required to trigger
            discount = self.dump_discount_min if self.dump_discount_min is not None else 3.0
            # sigma: The shock sigma threshold (negative = downward shock)
            sigma = self.dump_shock_sigma if self.dump_shock_sigma is not None else -4.0
            return f"{target} dump ≥{discount}% discount (σ≤{sigma})"
        
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


class HourlyItemVolume(models.Model):
    """
    Stores hourly trading volume snapshots for OSRS items, measured in GP (gold pieces).

    What: A single hourly volume snapshot for one item at a specific point in time.
    Why: Sustained move alerts need volume data to filter out low-activity items. Previously,
         volume was fetched via individual API calls to the RuneScape Wiki timeseries endpoint
         during each alert check cycle. For "all items" alerts, this meant hundreds of HTTP
         requests per cycle. This model pre-fetches and caches volume data in the database,
         replacing those API calls with fast DB queries.
    How: Populated by scripts/update_volumes.py every 1 hour 5 minutes. Each fetch cycle
         creates a NEW row per item (historical data accumulates over time). The alert checker
         queries the most recent row for each item to get its current hourly volume.

    Volume Calculation:
        volume_gp = (highPriceVolume + lowPriceVolume) × ((avgHighPrice + avgLowPrice) / 2)
        This represents the total GP value of items traded in the most recent hour.
        Example: 5,000 units traded × 500,000 GP average price = 2,500,000,000 GP volume.

    Data Source:
        - RuneScape Wiki API: /timeseries?timestep=1h&id={item_id}
        - Uses the most recent 1h interval from the timeseries response

    Usage:
        - check_alerts.py queries: HourlyItemVolume.objects.filter(item_id=X).first()
          (ordered by -timestamp via Meta.ordering, so .first() = most recent)
        - Historical data can be used for volume trend analysis in the future
    """

    # item_id: The OSRS item ID from the Wiki API (e.g., 4151 for Abyssal whip)
    # Indexed for fast lookups when the alert checker queries by item
    item_id = models.IntegerField(db_index=True)

    # item_name: Human-readable item name, denormalized from item mapping
    # Why denormalized: Avoids needing a join/lookup when displaying volume data
    item_name = models.CharField(max_length=255)

    # volume: Hourly trading volume measured in GP (gold pieces), NOT units traded
    # Formula: (highPriceVolume + lowPriceVolume) × avg_price
    # BigIntegerField because GP volume can easily exceed 2.1 billion for popular items
    # (e.g., 5000 Twisted Bows traded × 1.2B GP each = 6 trillion GP)
    volume = models.BigIntegerField()

    # timestamp: When this volume data was gathered by the update_volumes.py script
    # NOT the timestamp from the API response — this is when our script ran
    # Indexed for fast ordering and time-range queries on historical data
    timestamp = models.CharField(max_length=255)

    class Meta:
        # Default ordering: most recent first, so .first() always returns the latest snapshot
        ordering = ['-timestamp']

    def __str__(self):
        """
        What: Human-readable string representation of this volume snapshot
        Why: Useful in Django admin and debugging
        How: Shows item name, formatted GP volume, and timestamp
        """
        from datetime import datetime, timezone

        return f"{self.item_name} - {self.volume}"


class FiveMinTimeSeries(models.Model):
    """
    Stores hourly trading volume snapshots for OSRS items, measured in GP (gold pieces).

    What: A single hourly volume snapshot for one item at a specific point in time.
    Why: Sustained move alerts need volume data to filter out low-activity items. Previously,
         volume was fetched via individual API calls to the RuneScape Wiki timeseries endpoint
         during each alert check cycle. For "all items" alerts, this meant hundreds of HTTP
         requests per cycle. This model pre-fetches and caches volume data in the database,
         replacing those API calls with fast DB queries.
    How: Populated by scripts/update_volumes.py every 1 hour 5 minutes. Each fetch cycle
         creates a NEW row per item (historical data accumulates over time). The alert checker
         queries the most recent row for each item to get its current hourly volume.

    Volume Calculation:
        volume_gp = (highPriceVolume + lowPriceVolume) × ((avgHighPrice + avgLowPrice) / 2)
        This represents the total GP value of items traded in the most recent hour.
        Example: 5,000 units traded × 500,000 GP average price = 2,500,000,000 GP volume.

    Data Source:
        - RuneScape Wiki API: /timeseries?timestep=1h&id={item_id}
        - Uses the most recent 1h interval from the timeseries response

    Usage:
        - check_alerts.py queries: HourlyItemVolume.objects.filter(item_id=X).first()
          (ordered by -timestamp via Meta.ordering, so .first() = most recent)
        - Historical data can be used for volume trend analysis in the future
    """

    # item_id: The OSRS item ID from the Wiki API (e.g., 4151 for Abyssal whip)
    # Indexed for fast lookups when the alert checker queries by item
    item_id = models.IntegerField(db_index=True)

    # item_name: Human-readable item name, denormalized from item mapping
    # Why denormalized: Avoids needing a join/lookup when displaying volume data
    item_name = models.CharField(max_length=255)
    
    avg_high_price = models.IntegerField(null=True, blank=True)
    avg_low_price = models.IntegerField(null=True, blank=True)
    high_price_volume = models.IntegerField(default=0)
    low_price_volume = models.IntegerField(default=0)

    timestamp = models.CharField(max_length=255)

    class Meta:
        # Default ordering: most recent first, so .first() always returns the latest snapshot
        ordering = ['-timestamp']



class OneHourTimeSeries(models.Model):
    item_id = models.IntegerField(db_index=True)
    item_name = models.CharField(max_length=255)
    avg_high_price = models.IntegerField(null=True, blank=True)
    avg_low_price = models.IntegerField(null=True, blank=True)
    high_price_volume = models.IntegerField(default=0)
    low_price_volume = models.IntegerField(default=0)
    timestamp = models.CharField(max_length=255)

    class Meta:
        # Default ordering: most recent first, so .first() always returns the latest snapshot
        ordering = ['-timestamp']

class SixHourTimeSeries(models.Model):
    item_id = models.IntegerField(db_index=True)
    item_name = models.CharField(max_length=255)
    avg_high_price = models.IntegerField(null=True, blank=True)
    avg_low_price = models.IntegerField(null=True, blank=True)
    high_price_volume = models.IntegerField(default=0)
    low_price_volume = models.IntegerField(default=0)
    timestamp = models.CharField(max_length=255)

    class Meta:
        # Default ordering: most recent first, so .first() always returns the latest snapshot
        ordering = ['-timestamp']

class TwentyFourHourTimeSeries(models.Model):
    item_id = models.IntegerField(db_index=True)
    item_name = models.CharField(max_length=255)
    avg_high_price = models.IntegerField(null=True, blank=True)
    avg_low_price = models.IntegerField(null=True, blank=True)
    high_price_volume = models.IntegerField(default=0)
    low_price_volume = models.IntegerField(default=0)
    timestamp = models.CharField(max_length=255)

    class Meta:
        # Default ordering: most recent first, so .first() always returns the latest snapshot
        ordering = ['-timestamp']




