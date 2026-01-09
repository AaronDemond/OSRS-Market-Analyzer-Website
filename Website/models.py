from django.db import models
import requests


def get_item_price(item_id, reference):
    """
    Fetch the high or low price for an item based on reference.
    reference: 'high' or 'low'
    """
    try:
        response = requests.get(
            'https://prices.runescape.wiki/api/v1/osrs/latest',
            headers={'User-Agent': 'GE Tracker'}
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

    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    price = models.IntegerField()
    date = models.DateTimeField()
    quantity = models.IntegerField()
    type = models.CharField(max_length=4, choices=TYPE_CHOICES)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"


class AlertGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
            ('spike', 'Spike')
    ]
    
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
    
    def __str__(self):
        if self.type == 'spread':
            if self.is_all_items:
                min_price = f"{self.minimum_price:,}" if self.minimum_price else "None"
                max_price = f"{self.maximum_price:,}" if self.maximum_price else "None"
                return f"All items spread >= {self.percentage}%, minimum price: {min_price}, maximum price: {max_price}"
            return f"{self.item_name} spread >= {self.percentage}%"
        if self.type == 'spike':
            frame = f"{self.price}m" if self.price else "N/A"
            ref = self.reference or 'low'
            return f"{self.item_name} spike {self.percentage}% over {frame} ({ref})"
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
            return f"{self.item_name} moved {self.percentage}% within {self.price}m ({self.reference})"
        return f"Item price is now {price_formatted}"
