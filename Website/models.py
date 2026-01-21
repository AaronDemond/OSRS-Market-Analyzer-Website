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
    DIRECTION_CHOICES = [
        ('up', 'Up'),
        ('down', 'Down'),
        ('both', 'Both'),
    ]
    
    ABOVE_BELOW_CHOICES = [
        ('above', 'Above'),
        ('below', 'Below'),
    ]
    
    REFERENCE_CHOICES = [
        ('high', 'High Price'),
        ('low', 'Low Price'),
    ]

    ALERT_CHOICES = [
            ('above', 'Above Threshold'),
            ('below', 'Below Threshold'),
            ('spread', 'Spread'),
            ('spike', 'Spike'),
            ('sustained', 'Sustained Move')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    type = models.CharField(max_length=10, null=True, choices=ALERT_CHOICES, default='above')
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, blank=True, null=True)
    # unused field
    above_below = models.CharField(max_length=10, choices=ABOVE_BELOW_CHOICES, blank=True, null=True)
    item_name = models.CharField(max_length=255, blank=True, null=True, default=None)
    item_id = models.IntegerField(blank=True, null=True, default=None)
    price = models.IntegerField(blank=True, null=True, default=None)
    percentage = models.FloatField(blank=True, null=True, default=None)
    is_all_items = models.BooleanField(default=False, blank=True, null=True)
    reference = models.CharField(max_length=4, choices=REFERENCE_CHOICES, blank=True, null=True, default=None)
    is_triggered = models.BooleanField(default=False, blank=True, null=True)
    is_active = models.BooleanField(default=True, blank=True, null=True)
    is_dismissed = models.BooleanField(default=False, blank=True, null=True)
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
    
    # Pressure filter fields for sustained alerts
    PRESSURE_STRENGTH_CHOICES = [
        ('strong', 'Strong'),
        ('moderate', 'Moderate'),
        ('weak', 'Weak'),
    ]
    min_pressure_strength = models.CharField(max_length=10, choices=PRESSURE_STRENGTH_CHOICES, blank=True, null=True, default=None)
    min_pressure_spread_pct = models.FloatField(blank=True, null=True, default=None)  # Minimum spread % for pressure check
    
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
            if self.is_all_items:
                return f"All items spread >= {self.percentage}%"
            return f"{self.item_name} spread >= {self.percentage}%"
        if self.type == 'spike':
            frame = self._format_time_frame()
            perc = f"{self.percentage}%" if self.percentage is not None else "N/A"
            if self.is_all_items:
                return f"All items spike {perc} within {frame}"
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
        if self.is_all_items:
            return f"All items {self.type} {self.price:,} ({self.reference})"
        return f"{self.item_name} {self.type} {self.price:,} ({self.reference})"

    def triggered_text(self):
        if self.type == "spread":
            if self.is_all_items:
                return f"Price spread above {self.percentage}% Triggered. Click for details"
            return f"{self.item_name} spread has reached {self.percentage}% or higher"
        item_price = get_item_price(self.item_id, self.reference)
        price_formatted = f"{item_price:,}" if item_price else str(item_price)
        if self.type == "above":
            return f"{self.item_name} has risen above {self.price:,} to {price_formatted}"
        if self.type == "below":
            return f"{self.item_name} has fallen below {self.price:,} to {price_formatted}"
        if self.type == "spike":
            frame = self._format_time_frame()
            perc = f"{self.percentage:.1f}" if self.percentage is not None else "N/A"
            target = "All items" if self.is_all_items else self.item_name
            base = f"{target} spike {perc} within {frame}"
            if self.is_all_items and self.triggered_data:
                import json
                try:
                    data = json.loads(self.triggered_data)
                    count = len(data) if isinstance(data, list) else 0
                    return f"{base} ({count} item(s) matched)"
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
        return f"Item price is now {price_formatted}"


class FavoriteItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    added_at = models.DateTimeField(auto_now_add=True)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order', '-added_at']
        unique_together = ['user', 'item_id']

    def __str__(self):
        return self.item_name
