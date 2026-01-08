import os
import time
import json
import requests
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from Website.models import Alert


class Command(BaseCommand):
    help = 'Continuously checks alerts every 30 seconds and triggers them if conditions are met'

    # Email/SMS recipient for alert notifications (loaded from environment variable)
    ALERT_RECIPIENT = os.environ.get('ALERT_RECIPIENT', '')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_mapping = None

    def get_item_mapping(self):
        """Fetch and cache item ID to name mapping"""
        if self.item_mapping is None:
            try:
                response = requests.get(
                    'https://prices.runescape.wiki/api/v1/osrs/mapping',
                    headers={'User-Agent': 'GE Tracker'}
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
                headers={'User-Agent': 'GE Tracker'}
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
        """Check if an alert should be triggered. Returns True/False or list of matching items for all_items spread."""
        
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
            # Filter to non-triggered OR is_all_items spread (which can re-trigger)
            alerts_to_check = [a for a in active_alerts if not a.is_triggered or (a.type == 'spread' and a.is_all_items)]
            
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
                                alert.triggered_data = json.dumps(result)
                                alert.is_triggered = True
                                # Keep is_active = True for all_items spread alerts
                                alert.is_dismissed = False  # Reset dismissed so notification shows again
                                alert.save()
                                self.stdout.write(
                                    self.style.WARNING(f'TRIGGERED (all items spread): {len(result)} items found')
                                )
                                # Send email notification if enabled
                                if alert.email_notification:
                                    self.send_alert_notification(alert, alert.triggered_text())
                            else:
                                alert.is_triggered = True
                                # Deactivate alert if it's not for all items
                                if alert.is_all_items is not True:
                                    alert.is_active = False
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
            time.sleep(10)
