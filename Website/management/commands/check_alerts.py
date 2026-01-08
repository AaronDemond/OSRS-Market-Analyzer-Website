import time
import requests
from django.core.management.base import BaseCommand
from Website.models import Alert


class Command(BaseCommand):
    help = 'Continuously checks alerts every 30 seconds and triggers them if conditions are met'

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

    def check_alert(self, alert, all_prices):
        """Check if an alert should be triggered"""
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
            # Get all active, non-triggered alerts
            active_alerts = Alert.objects.filter(is_active=True, is_triggered=False)
            
            if active_alerts.exists():
                self.stdout.write(f'Checking {active_alerts.count()} active alerts...')
                
                # Fetch all prices once
                all_prices = self.get_all_prices()
                
                if all_prices:
                    for alert in active_alerts:
                        if self.check_alert(alert, all_prices):
                            alert.is_triggered = True
                            alert.save()
                            self.stdout.write(
                                self.style.WARNING(f'TRIGGERED: {alert}')
                            )
            else:
                self.stdout.write('No active alerts to check.')
            
            # Wait 30 seconds before next check
            time.sleep(30)
