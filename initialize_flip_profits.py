"""
Standalone script to initialize FlipProfit objects from existing Flip records.
Run from the project root: python initialize_flip_profits.py
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import requests
from Website.models import Flip, FlipProfit

USER_AGENT = 'GE-Tools (not yet live) - demondsoftware@gmail.com'

def get_all_current_prices():
    """Fetch all current prices from the API"""
    try:
        response = requests.get(
            'https://prices.runescape.wiki/api/v1/osrs/latest',
            headers={'User-Agent': USER_AGENT}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                return data['data']
    except requests.RequestException as e:
        print(f"Error fetching prices: {e}")
    return {}

def initialize_flip_profits():
    # Clear existing FlipProfit records
    deleted_count = FlipProfit.objects.count()
    FlipProfit.objects.all().delete()
    print(f"Deleted {deleted_count} existing FlipProfit records")
    
    # Get all current prices
    print("Fetching current prices from API...")
    all_prices = get_all_current_prices()
    print(f"Got prices for {len(all_prices)} items")
    
    # Get all unique item_ids from Flips
    item_ids = Flip.objects.values_list('item_id', flat=True).distinct()
    print(f"Found {len(item_ids)} unique items in Flips")
    
    for item_id in item_ids:
        if item_id == 0:
            print(f"Skipping item_id 0 (unknown item)")
            continue
        
        # Get all flips for this item, ordered by date
        flips = Flip.objects.filter(item_id=item_id).order_by('date')
        
        if not flips.exists():
            continue
        
        item_name = flips.first().item_name
        
        # Initialize tracking variables
        average_cost = 0
        quantity_held = 0
        realized_net = 0
        
        print(f"\nProcessing {item_name} (ID: {item_id})...")
        
        for flip in flips:
            if flip.type == 'buy':
                # Recalculate average_cost and quantity_held
                if quantity_held == 0:
                    average_cost = flip.price
                    quantity_held = flip.quantity
                else:
                    average_cost = ((quantity_held * average_cost) + (flip.quantity * flip.price)) / (quantity_held + flip.quantity)
                    quantity_held = quantity_held + flip.quantity
                print(f"  BUY: {flip.quantity} @ {flip.price} -> avg_cost: {average_cost:.2f}, qty_held: {quantity_held}")
            
            elif flip.type == 'sell':
                # Calculate realized gain/loss
                realized_gain = flip.quantity * (flip.price - average_cost)
                realized_net = realized_net + realized_gain
                quantity_held = quantity_held - flip.quantity
                print(f"  SELL: {flip.quantity} @ {flip.price} -> realized_gain: {realized_gain:.2f}, total_realized: {realized_net:.2f}, qty_held: {quantity_held}")
        
        # Calculate unrealized_net
        current_high = None
        if str(item_id) in all_prices:
            current_high = all_prices[str(item_id)].get('high')
        
        if current_high and quantity_held > 0:
            unrealized_net = quantity_held * ((current_high * 0.98) - average_cost)
        else:
            unrealized_net = 0
        
        # Create FlipProfit record
        FlipProfit.objects.create(
            item_id=item_id,
            average_cost=average_cost,
            unrealized_net=unrealized_net,
            realized_net=realized_net,
            quantity_held=quantity_held
        )
        
        print(f"  RESULT: avg_cost={average_cost:.2f}, qty_held={quantity_held}, realized={realized_net:.2f}, unrealized={unrealized_net:.2f}")
    
    print(f"\n{'='*50}")
    print(f"Created {FlipProfit.objects.count()} FlipProfit records")
    
    # Summary
    total_realized = sum(fp.realized_net for fp in FlipProfit.objects.all())
    total_unrealized = sum(fp.unrealized_net for fp in FlipProfit.objects.all())
    print(f"Total Realized P/L: {total_realized:,.2f} gp")
    print(f"Total Unrealized P/L: {total_unrealized:,.2f} gp")

if __name__ == '__main__':
    initialize_flip_profits()
