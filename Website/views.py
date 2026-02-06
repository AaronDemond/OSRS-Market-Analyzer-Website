from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Sum, F, Value
from django.db.models.functions import Coalesce
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
import requests
import time
import re
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from .models import Flip, FlipProfit, Alert, AlertGroup, FavoriteItem


# =============================================================================
# CACHE CONFIGURATION FOR ITEM MAPPINGS
# =============================================================================
# What: Module-level caches for item mapping data fetched from local JSON file
# Why: Avoids redundant file reads on every page load
# How: First request loads from file and caches; subsequent requests use cached data
# Note: Cache persists for Python process lifetime; restarting server clears it

# _item_mapping_cache: Dictionary mapping item name (lowercase) to item data
# Contains: {'item_name_lower': {'id': int, 'name': str, 'icon': str, ...}}
_item_mapping_cache = None

# _item_id_to_name_cache: Dictionary mapping item ID (string) to item name

# =============================================================================
# PRICE CACHE - Short-term to prevent duplicate API calls during navigation
# =============================================================================
# What: Short-term cache for price data from external API
# Why: When user navigates between pages quickly, prevents duplicate external API calls
#      that block Django's single-threaded dev server
# How: Cache prices for 5 seconds - enough to prevent duplicate calls during navigation
#      but short enough that prices are always "fresh enough" for display
# Note: This does NOT affect alert triggering (that happens in background job)
_price_cache = None
_price_cache_time = 0
PRICE_CACHE_TTL = 5  # seconds - very short, just to prevent navigation blocking
# Contains: {'item_id_str': 'Item Name'}
_item_id_to_name_cache = None


def get_item_mapping():
    """
    Load and cache item name to ID/icon mapping.
    
    What: Returns a dictionary mapping item name (lowercase) to item data
    Why: Used for icon lookup and item search functionality
    How: Loads from local JSON file for performance (avoids ~500ms API call)
    
    Returns:
        dict: Mapping of item_name_lower -> {'id': int, 'name': str, 'icon': str, ...}
    
    Note: Once the user saves the API response from 
          https://prices.runescape.wiki/api/v1/osrs/mapping
          to Website/static/item-mapping.json, this will load from that file.
          Until then, falls back to the API.
    """
    global _item_mapping_cache
    if _item_mapping_cache is None:
        import os
        from django.conf import settings
        
        # json_file_path: Path to local JSON file with item mapping data
        # Format: Array of objects with id, name, examine, members, lowalch, highalch, limit, icon
        json_file_path = os.path.join(settings.BASE_DIR, 'Website', 'static', 'item-mapping.json')
        
        # Try to load from local JSON file first (much faster than API)
        if os.path.exists(json_file_path):
            try:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Build cache mapping item name (lowercase) to full item data
                _item_mapping_cache = {item['name'].lower(): item for item in data}
                return _item_mapping_cache
            except (json.JSONDecodeError, IOError, KeyError) as e:
                # If file is corrupted or malformed, fall back to API
                print(f"Warning: Could not load item-mapping.json: {e}")
        
        # Fallback to API if local file doesn't exist
        try:
            response = requests.get(
                'https://prices.runescape.wiki/api/v1/osrs/mapping',
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
            )
            if response.status_code == 200:
                data = response.json()
                _item_mapping_cache = {item['name'].lower(): item for item in data}
        except requests.RequestException:
            _item_mapping_cache = {}
    return _item_mapping_cache


def get_item_id_to_name_mapping():
    """
    Fetch and cache item ID to name mapping from RuneScape Wiki API.
    
    What: Returns a dictionary mapping item ID (as string) to item name
    Why: Needed to look up item names when we have item IDs (e.g., for multi-item alerts)
    How: Fetches the same API data as get_item_mapping but keys by ID instead of name
    
    Returns:
        dict: Mapping of item_id (str) -> item_name (str)
    """
    global _item_id_to_name_cache
    if _item_id_to_name_cache is None:
        try:
            response = requests.get(
                'https://prices.runescape.wiki/api/v1/osrs/mapping',
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
            )
            if response.status_code == 200:
                data = response.json()
                # _item_id_to_name_cache: Dictionary mapping item ID (string) to item name
                _item_id_to_name_cache = {str(item['id']): item['name'] for item in data}
        except requests.RequestException:
            _item_id_to_name_cache = {}
    return _item_id_to_name_cache


def get_all_current_prices():
    """
    Fetch all current prices in one API call with short-term caching.
    
    What: Returns a dictionary of all OSRS item prices (high/low) from the Wiki API.
    Why: Needed for spread calculations, spike alerts, and threshold distance display.
    How: Makes a single HTTP request to the Wiki prices API, caches for 5 seconds.
    
    PERFORMANCE: 5-second cache prevents duplicate API calls during page navigation.
    When user clicks from flips → alerts quickly, both pages need prices.
    Without cache: Two slow external API calls (each 100-1000ms) that block Django.
    With cache: Second call returns instantly from cache.
    
    Note: 5 seconds is short enough that displayed prices are always current.
          Alert triggering happens in a separate background job, not affected by this.
    
    Returns:
        dict: Dictionary mapping item_id (string) to price data
              Format: {'item_id': {'high': int, 'low': int, 'highTime': int, 'lowTime': int}}
              Returns empty dict {} if API call fails
    """
    global _price_cache, _price_cache_time
    
    # Check if cache is still valid (within TTL)
    current_time = time.time()
    if _price_cache is not None and (current_time - _price_cache_time) < PRICE_CACHE_TTL:
        return _price_cache
    
    # Cache expired or empty - fetch fresh data
    try:
        response = requests.get(
            'https://prices.runescape.wiki/api/v1/osrs/latest',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                _price_cache = data['data']
                _price_cache_time = current_time
                return _price_cache
    except requests.RequestException:
        pass
    
    # If fetch failed but we have stale cache, return it
    if _price_cache is not None:
        return _price_cache
    
    return {}


def get_historical_price(item_id, time_filter):
    """Fetch historical price for an item based on time filter"""
    try:
        response = requests.get(
            f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=24h&id={item_id}',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                now = time.time()
                if time_filter == 'week':
                    target_time = now - (7 * 24 * 60 * 60)
                elif time_filter == 'month':
                    target_time = now - (30 * 24 * 60 * 60)
                elif time_filter == 'year':
                    target_time = now - (365 * 24 * 60 * 60)
                else:
                    return None, None
                
                # Find the closest data point to target time
                closest = None
                closest_diff = float('inf')
                for point in data['data']:
                    diff = abs(point['timestamp'] - target_time)
                    if diff < closest_diff:
                        closest_diff = diff
                        closest = point
                
                if closest:
                    return closest.get('avgHighPrice'), closest.get('avgLowPrice')
    except requests.RequestException:
        pass
    return None, None


# =============================================================================
# TRENDING ITEMS - Top Movers (Read from Pre-computed JSON)
# =============================================================================
# What: Reads trending items data from a JSON file generated by background script
# Why: Avoids expensive API calls during web requests - data is pre-computed hourly
# How: Background script (scripts/update_trending.py) runs hourly and writes JSON file
# Note: If file doesn't exist or is stale, returns empty data gracefully

# _trending_cache: Module-level cache to avoid repeated file reads within same request
_trending_cache = None
_trending_cache_time = 0
TRENDING_CACHE_TTL = 60  # Re-read file at most once per minute

def get_trending_items():
    """
    Get top 3 price gainers and top 3 losers from pre-computed JSON file.
    
    What: Reads trending items from static JSON file
    Why: Displays trending items on search page without blocking API calls
    How: 
        1. Check module-level cache (60 second TTL)
        2. If cache miss, read from static/data/trending_items.json
        3. Return data or empty dict if file doesn't exist
    
    Returns:
        dict: {
            'gainers': [{'id': int, 'name': str, 'icon': str, 'change': float, 'price': int}, ...],
            'losers': [{'id': int, 'name': str, 'icon': str, 'change': float, 'price': int}, ...],
            'last_updated': str (ISO timestamp)
        }
        Returns empty lists if data file doesn't exist.
    
    Note: Data is generated by scripts/update_trending.py which should run hourly
    """
    global _trending_cache, _trending_cache_time
    
    # Check module-level cache first (avoid re-reading file on every request)
    current_time = time.time()
    if _trending_cache is not None and (current_time - _trending_cache_time) < TRENDING_CACHE_TTL:
        return _trending_cache
    
    # TRENDING_FILE: Path to pre-computed trending data JSON
    # Generated by scripts/update_trending.py running as scheduled task
    import os
    from django.conf import settings
    
    trending_file = os.path.join(settings.BASE_DIR, 'Website', 'static', 'data', 'trending_items.json')
    
    try:
        with open(trending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Cache the data
        _trending_cache = data
        _trending_cache_time = current_time
        
        return data
        
    except FileNotFoundError:
        # File doesn't exist yet - script hasn't run
        # Return empty data, don't crash the page
        return {'gainers': [], 'losers': [], 'last_updated': None}
        
    except json.JSONDecodeError:
        # File is corrupted or being written - return empty
        return {'gainers': [], 'losers': [], 'last_updated': None}
        
    except Exception as e:
        # Any other error - log and return empty
        print(f"Error reading trending items: {e}")
        return {'gainers': [], 'losers': [], 'last_updated': None}


def test(request):
    return render(request, 'test.html')


def home(request):
    from .models import FlipProfit, Alert, Flip
    from django.db.models import Sum
    
    # Get current user (or None if not authenticated)
    user = request.user if request.user.is_authenticated else None
    
    # Get flip profit summary (filtered by user) - fast DB queries only
    flip_profits = FlipProfit.objects.filter(user=user) if user else FlipProfit.objects.none()
    total_unrealized = flip_profits.aggregate(total=Sum('unrealized_net'))['total'] or 0
    total_realized = flip_profits.aggregate(total=Sum('realized_net'))['total'] or 0
    position_size = flip_profits.aggregate(total=Sum(F('quantity_held') * F('average_cost')))['total'] or 0
    
    # Get total alerts stats (filtered by user) - fast DB queries only
    alerts_qs = Alert.objects.filter(user=user) if user else Alert.objects.none()
    total_alerts = alerts_qs.filter(is_active=True).count()
    triggered_alerts = alerts_qs.filter(is_triggered=True, is_dismissed=False).count()
    
    return render(request, 'home.html', {
        'total_unrealized': total_unrealized,
        'total_realized': total_realized,
        'position_size': position_size,
        'total_alerts': total_alerts,
        'triggered_alerts': triggered_alerts,
    })


def dashboard_content_api(request):
    """API endpoint for dashboard content - positions, alerts, activity"""
    from .models import FlipProfit, Alert, Flip
    from datetime import datetime, timedelta
    from django.utils import timezone
    import json
    
    user = request.user if request.user.is_authenticated else None
    
    # Fetch all current prices (this is the slow part)
    all_prices = get_all_current_prices()
    
    # Get flip profits for positions
    flip_profits = FlipProfit.objects.filter(user=user) if user else FlipProfit.objects.none()
    flips_qs = Flip.objects.filter(user=user) if user else Flip.objects.none()
    
    # Get profitable flips
    profitable_flips = []
    for fp in flip_profits.filter(quantity_held__gt=0).order_by('-unrealized_net')[:10]:
        item_id = str(fp.item_id)
        high_price = all_prices.get(item_id, {}).get('high')
        low_price = all_prices.get(item_id, {}).get('low')
        
        item_name = fp.item_name
        if not item_name:
            flip = flips_qs.filter(item_id=fp.item_id).first()
            item_name = flip.item_name if flip else f"Item {fp.item_id}"
        
        if fp.average_cost > 0 and high_price:
            profit_pct = ((high_price * 0.98 - fp.average_cost) / fp.average_cost) * 100
        else:
            profit_pct = 0
            
        profitable_flips.append({
            'item_id': fp.item_id,
            'item_name': item_name,
            'quantity_held': fp.quantity_held,
            'average_cost': fp.average_cost,
            'unrealized_net': fp.unrealized_net,
            'high_price': high_price,
            'low_price': low_price,
            'profit_pct': round(profit_pct, 1),
            'position_size': fp.quantity_held * fp.average_cost,
        })
    
    # Get recent triggered alerts
    alerts_qs = Alert.objects.filter(user=user) if user else Alert.objects.none()
    recent_alerts = alerts_qs.filter(
        is_triggered=True,
        is_dismissed=False
    ).order_by('-triggered_at')[:5]
    
    alert_list = []
    for alert in recent_alerts:
        alert_list.append({
            'id': alert.id,
            'text': str(alert),
            'triggered_text': alert.triggered_text(),
            'type': alert.type,
            'triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
        })
    
    # Get recent activity
    recent_flips = flips_qs.order_by('-date')[:5]
    recent_activity = []
    for flip in recent_flips:
        recent_activity.append({
            'item_name': flip.item_name,
            'item_id': flip.item_id,
            'type': flip.type,
            'quantity': flip.quantity,
            'price': flip.price,
            'date': flip.date.isoformat() if flip.date else None,
            'total': flip.quantity * flip.price,
        })
    
    return JsonResponse({
        'profitable_flips': profitable_flips,
        'recent_alerts': alert_list,
        'recent_activity': recent_activity,
    })


def flips(request):
    # Return lightweight template - data loaded via AJAX
    time_filter = request.GET.get('filter', 'current')
    return render(request, 'flips.html', {
        'time_filter': time_filter,
    })


def flips_stats_api(request):
    """Fast API endpoint for stats only - loads instantly without price fetching"""
    user = request.user if request.user.is_authenticated else None
    
    if not user:
        return JsonResponse({
            'total_unrealized': 0,
            'total_realized': 0,
            'position_size': 0,
        })
    
    flip_profits_qs = FlipProfit.objects.filter(user=user)
    
    # Use cached values from database - no external API calls
    total_unrealized = flip_profits_qs.aggregate(total=Sum('unrealized_net'))['total'] or 0
    total_realized = flip_profits_qs.aggregate(total=Sum('realized_net'))['total'] or 0
    position_size = flip_profits_qs.aggregate(total=Sum(F('quantity_held') * F('average_cost')))['total'] or 0
    
    return JsonResponse({
        'total_unrealized': total_unrealized,
        'total_realized': total_realized,
        'position_size': position_size,
    })


def flips_data_api(request):
    """
    API endpoint for flip data - enables progressive loading.
    
    Returns JSON containing:
    - items: List of flip items with prices, quantities, P&L, and icon data
    - stats: Aggregated statistics (total unrealized, realized, position size)
    
    The icon field is used by the frontend to display item images from the OSRS Wiki.
    """
    time_filter = request.GET.get('filter', 'current')
    
    # Get current user (or None if not authenticated)
    user = request.user if request.user.is_authenticated else None
    
    # Get all unique items for this user
    flips_qs = Flip.objects.filter(user=user) if user else Flip.objects.none()
    flip_profits_qs = FlipProfit.objects.filter(user=user) if user else FlipProfit.objects.none()
    item_ids = list(flips_qs.values_list('item_id', flat=True).distinct())
    
    # Fetch all current prices in one API call
    all_prices = get_all_current_prices()
    
    # Get item mapping for icon data - this mapping contains item metadata from the OSRS Wiki API
    # including the 'icon' field which is the filename of the item's image on the wiki
    item_mapping = get_item_mapping()
    
    # GE tax is 2% capped at 5M per transaction
    TAX_CAP = 5000000
    
    # Recalculate unrealized_net for all FlipProfit objects for this user
    for flip_profit in flip_profits_qs:
        current_price = None
        if str(flip_profit.item_id) in all_prices:
            price_data = all_prices[str(flip_profit.item_id)]
            high = price_data.get('high')
            low = price_data.get('low')
            if high and low:
                current_price = (high + low) / 2
            elif high:
                current_price = high
            elif low:
                current_price = low
        
        if current_price and flip_profit.quantity_held > 0:
            # Calculate unrealized with 5M tax cap
            gross_value = current_price * flip_profit.quantity_held
            tax = min(gross_value * 0.02, TAX_CAP)
            net_value = gross_value - tax
            flip_profit.unrealized_net = net_value - (flip_profit.average_cost * flip_profit.quantity_held)
        else:
            flip_profit.unrealized_net = 0
        flip_profit.save()
    
    items = []
    
    # Calculate totals from FlipProfit for this user
    total_unrealized = flip_profits_qs.aggregate(total=Sum('unrealized_net'))['total'] or 0
    total_realized = flip_profits_qs.aggregate(total=Sum('realized_net'))['total'] or 0
    position_size = flip_profits_qs.aggregate(total=Sum(F('quantity_held') * F('average_cost')))['total'] or 0
    
    for item_id in item_ids:
        item_flips = flips_qs.filter(item_id=item_id)
        item_name = item_flips.first().item_name
        
        # Look up the item icon from the mapping using the item name (case-insensitive)
        # The mapping is keyed by lowercase item names and contains an 'icon' field
        # with the wiki image filename (e.g., "Abyssal_whip.png")
        icon = None
        if item_name and item_mapping:
            item_data = item_mapping.get(item_name.lower())
            if item_data:
                icon = item_data.get('icon')
        
        # Calculate total bought and spent
        buys = item_flips.filter(type='buy')
        total_bought = buys.aggregate(total=Sum('quantity'))['total'] or 0
        total_spent = buys.aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0
        
        # Calculate total sold and revenue (with tax)
        sells = item_flips.filter(type='sell')
        total_sold = sells.aggregate(total=Sum('quantity'))['total'] or 0
        
        # Average price (of buys)
        avg_price = total_spent // total_bought if total_bought > 0 else 0
        
        # Current quantity held
        quantity_held = total_bought - total_sold
        
        # Get current prices from cached data
        high_price = None
        low_price = None
        price_data = all_prices.get(str(item_id))
        if price_data:
            high_price = price_data.get('high')
            low_price = price_data.get('low')
        
        # Get historical prices if filter is not current
        if time_filter != 'current':
            hist_high, hist_low = get_historical_price(item_id, time_filter)
            if hist_high is not None:
                high_price = hist_high
            if hist_low is not None:
                low_price = hist_low
        
        # Get FlipProfit for this item and user
        flip_profit = flip_profits_qs.filter(item_id=item_id).first()
        item_unrealized = flip_profit.unrealized_net if flip_profit else 0
        item_realized = flip_profit.realized_net if flip_profit else 0
        
        # Get first buy date for time held calculation
        first_buy = buys.order_by('date').first()
        first_buy_timestamp = first_buy.date.timestamp() if first_buy else None
        
        items.append({
            'item_id': item_id,
            'name': item_name,
            'icon': icon,  # Wiki image filename for displaying item icon in the UI
            'avg_price': int(avg_price),
            'high_price': high_price,
            'low_price': low_price,
            'quantity': quantity_held,
            'quantity_holding': quantity_held,
            'total_bought': total_bought,
            'total_sold': total_sold,
            'unrealized_net': round(item_unrealized),
            'realized_net': round(item_realized),
            'first_buy_timestamp': first_buy_timestamp,
            'position_size': int(avg_price * quantity_held),
        })
    
    return JsonResponse({
        'items': items,
        'stats': {
            'total_unrealized': round(total_unrealized),
            'total_realized': round(total_realized),
            'position_size': int(position_size) if position_size else 0,
        }
    })


def get_historical_prices_for_date(item_id, target_timestamp):
    """
    Fetch historical high and low prices for an item at a specific date.
    
    What: Retrieves price data from OSRS Wiki timeseries API for a given item at a target date.
    
    Why: Needed for the Historical View feature to calculate what unrealized P&L would have
         been at a specific point in the past.
    
    How: 
        1. Calls the OSRS Wiki timeseries API with 24h timestep (as per requirements)
        2. Iterates through returned data points to find the one closest to target_timestamp
        3. Returns the avgHighPrice and avgLowPrice from that data point
    
    Args:
        item_id: The OSRS item ID to fetch prices for
        target_timestamp: Unix timestamp of the historical date to look up
        
    Returns:
        tuple: (high_price, low_price) or (None, None) if data unavailable
    """
    try:
        # Always use 24h timestep as per requirements (smallest unit is 1 day)
        response = requests.get(
            f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=24h&id={item_id}',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and data['data']:
                # closest: Will hold the data point closest to our target timestamp
                closest = None
                # closest_diff: Tracks the smallest time difference found so far
                closest_diff = float('inf')
                
                # Iterate through all data points to find the one closest to target_timestamp
                for point in data['data']:
                    # diff: Absolute time difference between this point and our target
                    diff = abs(point['timestamp'] - target_timestamp)
                    if diff < closest_diff:
                        closest_diff = diff
                        closest = point
                
                if closest:
                    # Return the average high and low prices from the closest data point
                    return closest.get('avgHighPrice'), closest.get('avgLowPrice')
    except requests.RequestException:
        # If API call fails, return None values (item will be skipped)
        pass
    return None, None


def calculate_position_at_date(item_id, user, cutoff_datetime, flips_qs=None):
    """
    Calculate what a user's position in an item looked like at a specific historical date.
    
    What: Replays all buy/sell transactions for an item up to a cutoff date to determine
          the exact state of the position (avg_cost, quantity_held, realized_net) as it
          was on that date. This is a "time-travel" calculation.
    
    Why: The Historical View feature needs to show users exactly what their portfolio
         looked like on a past date - not just current holdings with historical prices,
         but the actual holdings, cost basis, and realized gains as of that date.
    
    How:
        1. Fetches all Flip records for the item/user, ordered chronologically by date
        2. Iterates through each transaction that occurred BEFORE the cutoff date:
           - BUY: Updates average cost using weighted average formula:
                  new_avg_cost = ((qty * avg_cost) + (buy_qty * buy_price)) / (qty + buy_qty)
                  new_qty = qty + buy_qty
           - SELL: Calculates realized gain with 2% GE tax (capped at 5M per transaction):
                   gross_revenue = sell_price * sell_qty
                   tax = min(gross_revenue * 0.02, 5000000)
                   realized_gain = (gross_revenue - tax) - (avg_cost * sell_qty)
                   new_qty = qty - sell_qty
                   avg_cost remains unchanged
        3. Stops processing when transaction date exceeds cutoff_datetime
        4. Returns the calculated state as of the cutoff date
    
    Args:
        item_id: The OSRS item ID to calculate position for
        user: The Django User object (or None for anonymous)
        cutoff_datetime: A timezone-aware datetime object representing the cutoff date/time
                         Only transactions with date <= cutoff_datetime are processed
        flips_qs: Optional pre-filtered QuerySet of Flip objects for this user
                  If not provided, will query the database directly
    
    Returns:
        dict: A dictionary containing the position state at the cutoff date:
            - 'average_cost': float - The weighted average cost per unit
            - 'quantity_held': int - Number of units held at that date
            - 'realized_net': float - Total realized gains/losses from sells up to that date
            - 'total_bought': int - Total quantity purchased up to that date
            - 'total_sold': int - Total quantity sold up to that date
            - 'first_buy_timestamp': float or None - Unix timestamp of the first buy transaction
            - 'item_name': str - The name of the item (from the first transaction found)
            - 'has_transactions': bool - True if at least one transaction exists before cutoff
    
    Notes:
        - If no transactions exist before the cutoff date, returns has_transactions=False
        - The 5M tax cap applies PER SELL TRANSACTION, not per item or total
        - Average cost persists through sells (doesn't change when you sell)
    """
    # =========================================================================
    # CONSTANTS
    # =========================================================================
    # TAX_RATE: The Grand Exchange charges 2% tax on all sell transactions
    TAX_RATE = 0.02
    # TAX_CAP: Maximum tax per single sell transaction is 5 million GP
    TAX_CAP = 5000000
    
    # =========================================================================
    # GET TRANSACTIONS FOR THIS ITEM
    # =========================================================================
    # If a pre-filtered QuerySet wasn't provided, query the database
    if flips_qs is None:
        flips_qs = Flip.objects.filter(user=user)
    
    # item_flips: All transactions for this specific item, ordered chronologically
    # Why ordered by date: We must process transactions in the order they occurred
    # to correctly calculate running average cost and realized gains
    item_flips = flips_qs.filter(item_id=item_id).order_by('date')
    
    # =========================================================================
    # INITIALIZE TRACKING VARIABLES
    # =========================================================================
    # average_cost: The weighted average cost per unit held
    # Starts at 0, gets set on first buy, then updated on subsequent buys
    average_cost = 0.0
    
    # quantity_held: Current number of units the user holds
    # Increases on buys, decreases on sells
    quantity_held = 0
    
    # realized_net: Running total of all realized gains/losses from completed sells
    # Each sell adds: (net_revenue_after_tax) - (cost_basis_of_sold_units)
    realized_net = 0.0
    
    # total_bought: Cumulative quantity purchased (for display purposes)
    total_bought = 0
    
    # total_sold: Cumulative quantity sold (for display purposes)
    total_sold = 0
    
    # first_buy_timestamp: Unix timestamp of the very first buy transaction
    # Used for "Time Held" calculation in the UI
    first_buy_timestamp = None
    
    # item_name: Name of the item (captured from first transaction)
    item_name = None
    
    # has_transactions: Flag to track if any transactions existed before cutoff
    has_transactions = False
    
    # =========================================================================
    # REPLAY TRANSACTIONS UP TO CUTOFF DATE
    # =========================================================================
    for flip in item_flips:
        # Check if this transaction occurred after our cutoff date
        # If so, stop processing - we only want the state AS OF the cutoff date
        if flip.date > cutoff_datetime:
            break
        
        # Mark that we found at least one transaction before the cutoff
        has_transactions = True
        
        # Capture item name from first transaction we see
        if item_name is None:
            item_name = flip.item_name
        
        # =====================================================================
        # PROCESS BUY TRANSACTION
        # =====================================================================
        if flip.type == 'buy':
            # Track first buy timestamp for time held calculation
            if first_buy_timestamp is None:
                first_buy_timestamp = flip.date.timestamp()
            
            # Add to total bought counter
            total_bought += flip.quantity
            
            if quantity_held == 0:
                # First purchase (or first after selling everything):
                # Average cost is simply the purchase price
                average_cost = float(flip.price)
                quantity_held = flip.quantity
            else:
                # Subsequent purchase: Calculate new weighted average cost
                # Formula: new_avg = ((old_qty * old_avg) + (new_qty * new_price)) / total_qty
                # Why: This gives us the true average cost across all units we hold
                total_cost_before = quantity_held * average_cost
                new_purchase_cost = flip.quantity * flip.price
                new_total_quantity = quantity_held + flip.quantity
                average_cost = (total_cost_before + new_purchase_cost) / new_total_quantity
                quantity_held = new_total_quantity
        
        # =====================================================================
        # PROCESS SELL TRANSACTION
        # =====================================================================
        elif flip.type == 'sell':
            # Add to total sold counter
            total_sold += flip.quantity
            
            # Calculate gross revenue from the sale
            # gross_revenue: Total GP received before tax
            gross_revenue = flip.price * flip.quantity
            
            # Calculate GE tax with 5M cap per transaction
            # tax: The amount deducted by the Grand Exchange (2%, max 5M)
            tax = min(gross_revenue * TAX_RATE, TAX_CAP)
            
            # Calculate net revenue after tax
            # net_revenue: Actual GP received after tax deduction
            net_revenue = gross_revenue - tax
            
            # Calculate cost basis of the units being sold
            # cost_basis: What we originally paid for these specific units (at avg cost)
            cost_basis = average_cost * flip.quantity
            
            # Calculate realized gain/loss for this transaction
            # realized_gain: Profit (positive) or loss (negative) from this sale
            realized_gain = net_revenue - cost_basis
            
            # Add to running total of realized gains
            realized_net += realized_gain
            
            # Reduce quantity held (average_cost stays the same for remaining units)
            # Why avg_cost unchanged: The cost basis of remaining shares doesn't change
            # when you sell some - it's still what you paid for them
            quantity_held -= flip.quantity
    
    # =========================================================================
    # RETURN POSITION STATE AT CUTOFF DATE
    # =========================================================================
    return {
        'average_cost': average_cost,
        'quantity_held': quantity_held,
        'realized_net': realized_net,
        'total_bought': total_bought,
        'total_sold': total_sold,
        'first_buy_timestamp': first_buy_timestamp,
        'item_name': item_name,
        'has_transactions': has_transactions,
    }


def flips_historical_api(request):
    """
    API endpoint for historical flip data - "Time Travel" view of portfolio at a past date.
    
    What: Returns flip data showing exactly what the user's portfolio looked like on a 
          specific historical date. This includes:
          - What items they held (quantity_held as of that date)
          - Their cost basis (average_cost calculated from transactions up to that date)
          - Their realized gains (from sells completed before that date)
          - Unrealized P&L (calculated using historical prices from that date)
          
          This is a READ-ONLY operation - NO database records are modified.
    
    Why: Allows users to see their actual portfolio state at any point in the past.
         Unlike the previous implementation which showed current holdings with historical
         prices, this shows what they ACTUALLY held on that date. Useful for:
         - Understanding how positions have evolved over time
         - Analyzing past decisions (e.g., "what if I had sold on this date?")
         - Reviewing historical performance accurately
    
    How:
        1. Accepts a 'date' GET parameter (ISO format: YYYY-MM-DD)
        2. Converts date to datetime (end of day) for cutoff comparison
        3. Gets all unique item_ids from user's Flip transaction history
        4. For each item, calls calculate_position_at_date() to replay transactions
           up to the cutoff date and determine historical position state
        5. Filters results:
           - Items with NO transactions before cutoff date are HIDDEN (not shown)
           - Items with 0 quantity but realized gains ARE shown (fully sold items)
        6. Fetches historical prices from OSRS Wiki API IN PARALLEL for efficiency
        7. Calculates historical unrealized P&L for items with quantity_held > 0
        8. Returns JSON with complete historical snapshot
    
    Performance: Uses concurrent.futures.ThreadPoolExecutor to fetch all item prices
                 in parallel, significantly reducing load time for users with many items.
    
    Parameters:
        date (GET): ISO format date string (YYYY-MM-DD) for the historical snapshot
        
    Returns:
        JSON containing:
        - items: List of items with historical positions, prices, and calculated P&L
        - stats: Aggregated totals (unrealized, realized, position_size) as of that date
        - skipped_items: List of items excluded due to missing historical price data
        - historical_date: The date being viewed (for display purposes)
        - is_historical: Boolean flag indicating this is historical data (always True)
    
    Important Notes:
        - Items bought AFTER the historical date are completely hidden
        - Items fully sold BEFORE the historical date are shown (with 0 qty, realized gains)
        - Time Held is calculated from first buy to the HISTORICAL date (not today)
        - All totals/aggregates reflect the state AS OF the historical date
    """
    # =========================================================================
    # PARSE AND VALIDATE DATE PARAMETER
    # =========================================================================
    # date_str: The historical date requested by the user in ISO format (YYYY-MM-DD)
    date_str = request.GET.get('date')
    
    if not date_str:
        return JsonResponse({'error': 'Date parameter is required'}, status=400)
    
    try:
        # Parse the date string and convert to datetime for cutoff comparison
        # We set time to end of day (23:59:59) to include all transactions on that day
        from datetime import datetime as dt
        from django.utils import timezone
        
        # historical_date: Naive datetime parsed from user input
        historical_date = dt.strptime(date_str, '%Y-%m-%d')
        
        # cutoff_datetime: Timezone-aware datetime representing end of the selected day
        # Why end of day: We want to include ALL transactions that occurred on this date
        # Why timezone-aware: Django stores datetimes as timezone-aware, so comparison must match
        cutoff_datetime = timezone.make_aware(
            historical_date.replace(hour=23, minute=59, second=59)
        )
        
        # target_timestamp: Unix timestamp for the OSRS Wiki API price lookup
        # This is used to find the closest price data point to our target date
        target_timestamp = cutoff_datetime.timestamp()
        
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
    
    # =========================================================================
    # GET USER AND TRANSACTION DATA
    # =========================================================================
    # user: The currently authenticated user, or None for anonymous sessions
    user = request.user if request.user.is_authenticated else None
    
    # flips_qs: QuerySet of all Flip (transaction) records for this user
    # This will be reused across multiple calculate_position_at_date() calls
    flips_qs = Flip.objects.filter(user=user) if user else Flip.objects.none()
    
    # item_ids: List of all unique item IDs the user has ever traded
    # We need to check each one to see if it had activity before the cutoff date
    item_ids = list(flips_qs.values_list('item_id', flat=True).distinct())
    
    # item_mapping: Dictionary for looking up item icons from OSRS Wiki
    # Maps lowercase item names to metadata including the 'icon' filename
    item_mapping = get_item_mapping()
    
    # TAX_CAP: Maximum GE tax per transaction (2% capped at 5M gp)
    # Used for calculating unrealized P&L on potential sales
    TAX_CAP = 5000000
    
    # =========================================================================
    # CALCULATE HISTORICAL POSITIONS FOR ALL ITEMS
    # =========================================================================
    # What: Replay transactions for each item to determine state at cutoff date
    # Why: We need to know what the user held, their cost basis, and realized gains
    #      as they actually were on the historical date
    # How: Call calculate_position_at_date() for each unique item_id
    
    # historical_positions: Dictionary mapping item_id -> position state at cutoff
    # This will be populated by calling calculate_position_at_date() for each item
    historical_positions = {}
    
    # items_with_activity: List of item_ids that had transactions before cutoff
    # Items with no activity before cutoff will be hidden entirely
    items_with_activity = []
    
    for item_id in item_ids:
        # Calculate what the position looked like at the cutoff date
        position = calculate_position_at_date(
            item_id=item_id,
            user=user,
            cutoff_datetime=cutoff_datetime,
            flips_qs=flips_qs
        )
        
        # Only include items that had at least one transaction before the cutoff
        # Items bought AFTER the historical date should be hidden
        if position['has_transactions']:
            historical_positions[item_id] = position
            items_with_activity.append(item_id)
    
    # =========================================================================
    # PARALLEL PRICE FETCHING FOR ITEMS WITH HOLDINGS
    # =========================================================================
    # What: Fetches historical prices for all items with quantity_held > 0
    # Why: We need historical prices to calculate unrealized P&L
    # How: Uses ThreadPoolExecutor to run get_historical_prices_for_date() for all
    #      items simultaneously, then collects results into a dictionary
    # Note: We only fetch prices for items with holdings (qty > 0) since items
    #       fully sold don't need price data for unrealized calculation
    
    # item_ids_to_fetch: List of item IDs that need historical price lookup
    # Only items with quantity_held > 0 need prices for unrealized P&L
    item_ids_to_fetch = [
        item_id for item_id in items_with_activity
        if historical_positions[item_id]['quantity_held'] > 0
    ]
    
    # historical_prices: Dictionary mapping item_id -> (high_price, low_price)
    # This will be populated by the parallel fetch
    historical_prices = {}
    
    # Use ThreadPoolExecutor to fetch all prices in parallel
    # max_workers=10: Limit concurrent connections to be respectful to the API
    if item_ids_to_fetch:
        with ThreadPoolExecutor(max_workers=10) as executor:
            # future_to_item_id: Maps each Future object to its corresponding item_id
            # Why: We need to know which item_id each result belongs to when collecting
            future_to_item_id = {
                executor.submit(get_historical_prices_for_date, item_id, target_timestamp): item_id
                for item_id in item_ids_to_fetch
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_item_id):
                item_id = future_to_item_id[future]
                try:
                    # Get the (high, low) tuple result from the completed future
                    high, low = future.result()
                    historical_prices[item_id] = (high, low)
                except Exception as e:
                    # If an error occurred, store None values (item will be skipped)
                    historical_prices[item_id] = (None, None)
    
    # =========================================================================
    # BUILD RESPONSE DATA
    # =========================================================================
    # What: Process each item's historical position and build the response
    # Why: Frontend needs structured data to display the historical snapshot
    # How: For each item with activity, create an item dict with all needed fields
    
    # items: List to hold the processed item data for response
    items = []
    
    # skipped_items: List of items that couldn't be processed due to missing price data
    # These had quantity_held > 0 but no price data was available
    skipped_items = []
    
    # Aggregated stats across all items (as of historical date)
    # total_historical_unrealized: Sum of all items' unrealized P&L
    total_historical_unrealized = 0
    # total_realized: Sum of all items' realized gains/losses up to cutoff
    total_realized = 0
    # position_size: Sum of all items' (avg_cost * quantity_held)
    position_size = 0
    
    for item_id in items_with_activity:
        # position: The calculated state of this item at the cutoff date
        position = historical_positions[item_id]
        
        # Extract values from position dictionary
        avg_cost = position['average_cost']
        qty_held = position['quantity_held']
        realized_net = position['realized_net']
        total_bought = position['total_bought']
        total_sold = position['total_sold']
        first_buy_ts = position['first_buy_timestamp']
        item_name = position['item_name']
        
        # Always add realized gains to total (even for fully sold items)
        total_realized += realized_net
        
        # Initialize unrealized P&L and prices (will be calculated for items with holdings)
        historical_unrealized = 0
        historical_high = None
        historical_low = None
        item_position_size = 0
        
        # =====================================================================
        # CALCULATE UNREALIZED P&L FOR ITEMS WITH HOLDINGS
        # =====================================================================
        if qty_held > 0:
            # Get the pre-fetched historical prices for this item
            historical_high, historical_low = historical_prices.get(item_id, (None, None))
            
            # If no historical price data available, skip this item
            if historical_high is None and historical_low is None:
                skipped_items.append({
                    'item_id': item_id,
                    'item_name': item_name or f"Item {item_id}",
                    'reason': 'No historical price data available for this date'
                })
                continue
            
            # Calculate average historical price from high and low
            # historical_avg_price: The average of high and low, used for unrealized calc
            if historical_high and historical_low:
                historical_avg_price = (historical_high + historical_low) / 2
            elif historical_high:
                historical_avg_price = historical_high
            elif historical_low:
                historical_avg_price = historical_low
            else:
                # Should not reach here due to earlier check, but safety fallback
                continue
            
            # Calculate historical unrealized P&L with GE tax
            # gross_value: Total value if sold at historical price (before tax)
            gross_value = historical_avg_price * qty_held
            # tax: 2% GE tax, capped at 5M per transaction
            tax = min(gross_value * 0.02, TAX_CAP)
            # net_value: Value after tax deduction
            net_value = gross_value - tax
            # historical_unrealized: Profit/loss = net sale value - total cost basis
            historical_unrealized = net_value - (avg_cost * qty_held)
            
            # Add to running totals
            total_historical_unrealized += historical_unrealized
            
            # Calculate position size (cost-based)
            item_position_size = avg_cost * qty_held
            position_size += item_position_size
        
        # =====================================================================
        # LOOK UP ITEM ICON
        # =====================================================================
        icon = None
        if item_name and item_mapping:
            item_data = item_mapping.get(item_name.lower())
            if item_data:
                icon = item_data.get('icon')
        
        # =====================================================================
        # BUILD ITEM DATA OBJECT
        # =====================================================================
        items.append({
            'item_id': item_id,
            'name': item_name or f"Item {item_id}",
            'icon': icon,
            # avg_price: The user's historical cost basis (what they paid on average)
            'avg_price': int(avg_cost) if avg_cost else 0,
            # high_price/low_price: Historical market prices from the selected date
            'high_price': historical_high,
            'low_price': historical_low,
            # quantity/quantity_holding: How many units held AS OF the historical date
            'quantity': qty_held,
            'quantity_holding': qty_held,
            # total_bought/total_sold: Cumulative quantities up to historical date
            'total_bought': total_bought,
            'total_sold': total_sold,
            # unrealized_net: P&L if sold at historical prices (only for items with holdings)
            'unrealized_net': round(historical_unrealized),
            # realized_net: Actual gains/losses from sells completed before cutoff
            'realized_net': round(realized_net),
            # first_buy_timestamp: When user first bought this item (for time held calc)
            'first_buy_timestamp': first_buy_ts,
            # position_size: Cost basis of current holdings (avg_cost * qty_held)
            'position_size': int(item_position_size),
        })
    
    # =========================================================================
    # RETURN JSON RESPONSE
    # =========================================================================
    # IMPORTANT: No database records are modified by this endpoint
    # This is a pure read/calculation operation for historical analysis
    return JsonResponse({
        'items': items,
        'stats': {
            'total_unrealized': round(total_historical_unrealized),
            'total_realized': round(total_realized),
            'position_size': int(position_size) if position_size else 0,
        },
        'skipped_items': skipped_items,
        'historical_date': date_str,
        'is_historical': True,
    })


def add_flip(request):
    if request.method == 'POST':
        # Get current user
        user = request.user if request.user.is_authenticated else None
        
        item_name = request.POST.get('item_name')
        price = int(request.POST.get('price'))
        date_str = request.POST.get('date')
        quantity = int(request.POST.get('quantity'))
        flip_type = request.POST.get('type')
        
        # Parse datetime-local format (YYYY-MM-DDTHH:MM)
        date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        
        # Look up item ID from name
        mapping = get_item_mapping()
        item_data = mapping.get(item_name.lower())
        
        if item_data:
            item_id = item_data['id']
            canonical_name = item_data['name']
        else:
            # If not found, use 0 as ID and keep user's name
            item_id = 0
            canonical_name = item_name
        
        Flip.objects.create(
            user=user,
            item_id=item_id,
            item_name=canonical_name,
            price=price,
            date=date,
            quantity=quantity,
            type=flip_type
        )
        
        # Recalculate FlipProfit by replaying all flips in chronological order
        # This ensures correct calculations even if flips are entered out of order
        if item_id != 0:
            recalculate_flip_profit(item_id, user)
    
    messages.success(request, 'Flip added successfully')
    return redirect('flips')


def recalculate_flip_profit(item_id, user=None):
    """Recalculate FlipProfit for an item by replaying all flips in chronological order"""
    # Delete existing FlipProfit for this item and user
    FlipProfit.objects.filter(user=user, item_id=item_id).delete()
    
    # Get all flips for this item and user ordered by date
    flips = Flip.objects.filter(user=user, item_id=item_id).order_by('date')
    
    if not flips.exists():
        return
    
    # Initialize tracking variables
    average_cost = 0
    quantity_held = 0
    realized_net = 0
    
    # GE tax is 2% capped at 5M per transaction
    TAX_CAP = 5000000
    
    # Replay all flips
    for flip in flips:
        if flip.type == 'buy':
            if quantity_held == 0:
                average_cost = flip.price
                quantity_held = flip.quantity
            else:
                average_cost = ((quantity_held * average_cost) + (flip.quantity * flip.price)) / (quantity_held + flip.quantity)
                quantity_held = quantity_held + flip.quantity
        
        elif flip.type == 'sell':
            # Calculate tax with 5M cap
            gross_revenue = flip.price * flip.quantity
            tax = min(gross_revenue * 0.02, TAX_CAP)
            net_revenue = gross_revenue - tax
            realized_gain = net_revenue - (average_cost * flip.quantity)
            realized_net = realized_net + realized_gain
            quantity_held = quantity_held - flip.quantity
    
    # Calculate unrealized_net with current prices (average of high and low)
    all_prices = get_all_current_prices()
    current_price = None
    if str(item_id) in all_prices:
        price_data = all_prices[str(item_id)]
        high = price_data.get('high')
        low = price_data.get('low')
        if high and low:
            current_price = (high + low) / 2
        elif high:
            current_price = high
        elif low:
            current_price = low
    
    if current_price and quantity_held > 0:
        # Calculate unrealized with 5M tax cap
        gross_value = current_price * quantity_held
        tax = min(gross_value * 0.02, TAX_CAP)
        net_value = gross_value - tax
        unrealized_net = net_value - (average_cost * quantity_held)
    else:
        unrealized_net = 0
    
    # Create new FlipProfit
    FlipProfit.objects.create(
        user=user,
        item_id=item_id,
        average_cost=average_cost,
        unrealized_net=unrealized_net,
        realized_net=realized_net,
        quantity_held=quantity_held
    )


def delete_flip(request, item_id):
    """Delete all flips for a specific item"""
    if request.method == 'POST':
        user = request.user if request.user.is_authenticated else None
        Flip.objects.filter(user=user, item_id=item_id).delete()
        # Also delete the FlipProfit for this item
        FlipProfit.objects.filter(user=user, item_id=item_id).delete()
        messages.success(request, 'Flip deleted successfully')
    return redirect('flips')


def delete_single_flip(request):
    """Delete a single flip by ID"""
    if request.method == 'POST':
        user = request.user if request.user.is_authenticated else None
        flip_id = request.POST.get('flip_id')
        flip = Flip.objects.filter(id=flip_id, user=user).first()
        if flip:
            item_id = flip.item_id
            flip.delete()
            # Check if there are any remaining flips for this item
            if Flip.objects.filter(user=user, item_id=item_id).exists():
                # Recalculate FlipProfit for this item
                recalculate_flip_profit(item_id, user)
                return redirect('item_detail', item_id=item_id)
            else:
                # No more flips, delete FlipProfit
                FlipProfit.objects.filter(user=user, item_id=item_id).delete()
    return redirect('flips')


def edit_flip(request):
    """Edit a single flip"""
    if request.method == 'POST':
        user = request.user if request.user.is_authenticated else None
        flip_id = request.POST.get('flip_id')
        flip = Flip.objects.filter(id=flip_id, user=user).first()
        if flip:
            flip.price = int(request.POST.get('price'))
            date_str = request.POST.get('date')
            flip.date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
            flip.quantity = int(request.POST.get('quantity'))
            flip.type = request.POST.get('type')
            flip.save()
            # Recalculate FlipProfit for this item
            recalculate_flip_profit(flip.item_id, user)
            return redirect('item_detail', item_id=flip.item_id)
    return redirect('flips')


def item_search_api(request):
    """API endpoint for item name autocomplete"""
    query = request.GET.get('q', '').lower()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    
    mapping = get_item_mapping()
    matches = [
        {'name': item['name'], 'id': item['id']}
        for name, item in mapping.items()
        if query in name
    ][:15]  # Limit to 15 results
    
    return JsonResponse(matches, safe=False)


def random_item_api(request):
    """API endpoint to get a random item"""
    import random
    mapping = get_item_mapping()
    if not mapping:
        return JsonResponse({'error': 'No items available'}, status=500)
    
    items = list(mapping.values())
    random_item = random.choice(items)
    return JsonResponse({'name': random_item['name'], 'id': random_item['id']})


def item_detail(request, item_id):
    """Show all flips for a specific item"""
    user = request.user if request.user.is_authenticated else None
    flips = Flip.objects.filter(user=user, item_id=item_id).order_by('-date')
    item_name = flips.first().item_name if flips.exists() else 'Unknown Item'
    
    return render(request, 'item_detail.html', {
        'flips': flips,
        'item_name': item_name,
        'item_id': item_id,
    })


def item_search(request):
    """
    Render the item search page with trending items data.
    
    What: Main page for searching OSRS items and viewing price data
    Why: Entry point for users to explore item prices and market trends
    How: Fetches cached trending items data and passes to template
    
    Context passed to template:
        - trending: dict with 'gainers', 'losers', 'last_updated' from get_trending_items()
    """
    # Get trending items (cached for 1 hour, won't slow down page load)
    trending = get_trending_items()
    
    return render(request, 'item_search.html', {
        'trending': trending
    })


def item_data_api(request):
    """API endpoint to get detailed item data including current prices, volume, and GE limit"""
    item_id = request.GET.get('id')
    if not item_id:
        return JsonResponse({'error': 'Item ID required'}, status=400)
    
    try:
        # Get item mapping for GE limit and other metadata
        mapping = get_item_mapping()
        item_info = None
        for name, item in mapping.items():
            if str(item['id']) == str(item_id):
                item_info = item
                break
        
        if not item_info:
            return JsonResponse({'error': 'Item not found'}, status=404)
        
        # Get current prices
        prices = get_all_current_prices()
        price_data = prices.get(str(item_id), {})
        
        # Get 1-hour volume data
        volume = None
        try:
            response = requests.get(
                'https://prices.runescape.wiki/api/v1/osrs/1h',
                headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
            )
            if response.status_code == 200:
                hour_data = response.json()
                if 'data' in hour_data and str(item_id) in hour_data['data']:
                    item_hour = hour_data['data'][str(item_id)]
                    # Volume is sum of high and low volume
                    high_vol = item_hour.get('highPriceVolume', 0) or 0
                    low_vol = item_hour.get('lowPriceVolume', 0) or 0
                    volume = high_vol + low_vol
        except requests.RequestException:
            pass
        
        return JsonResponse({
            'id': item_info['id'],
            'name': item_info['name'],
            'examine': item_info.get('examine', ''),
            'icon': item_info.get('icon', ''),
            'limit': item_info.get('limit'),
            'members': item_info.get('members', False),
            'highalch': item_info.get('highalch'),
            'lowalch': item_info.get('lowalch'),
            'high': price_data.get('high'),
            'low': price_data.get('low'),
            'highTime': price_data.get('highTime'),
            'lowTime': price_data.get('lowTime'),
            'volume': volume
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def item_history_api(request):
    """API endpoint to get item price history for charting"""
    item_id = request.GET.get('id')
    timestep = request.GET.get('timestep', '24h')  # '5m', '1h', or '24h'
    
    if not item_id:
        return JsonResponse({'error': 'Item ID required'}, status=400)
    
    if timestep not in ['5m', '1h', '24h']:
        timestep = '24h'
    
    try:
        response = requests.get(
            f'https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            return JsonResponse(data)
        else:
            return JsonResponse({'error': 'Failed to fetch price history'}, status=response.status_code)
    except requests.RequestException as e:
        return JsonResponse({'error': str(e)}, status=500)


def alerts(request):
    # Render page instantly with no database calls - data loads via JavaScript
    return render(request, 'alerts.html', {})


def create_alert(request):
    if request.method == 'POST':
        import json as json_module
        
        # Get current user
        user = request.user if request.user.is_authenticated else None
        
        alert_name_type = request.POST.get('alert_name_type', 'default')
        alert_name = request.POST.get('alert_name', '').strip()
        # If default selected or no custom name provided, use 'Default'
        if alert_name_type == 'default' or not alert_name:
            alert_name = 'Default'
        
        alert_type = request.POST.get('type')
        item_name = request.POST.get('item_name')
        item_id = request.POST.get('item_id')
        price = request.POST.get('price')
        reference = request.POST.get('reference')
        percentage = request.POST.get('percentage')
        time_frame = request.POST.get('time_frame')
        number_of_items = request.POST.get('number_of_items')
        direction = request.POST.get('direction')
        is_all_items_flag = request.POST.get('is_all_items') == 'true'
        minimum_price = request.POST.get('minimum_price')
        maximum_price = request.POST.get('maximum_price')
        # min_volume: Minimum hourly trading volume in GP (required for spike alerts)
        # What: Captures the user-entered min hourly volume filter from the form
        # Why: Spike alerts now require this value; sustained/spread may also use it
        # How: Read directly from POST data so validation can occur before alert creation
        min_volume = request.POST.get('min_volume')
        
        # min_volume_value: Parsed integer value for min_volume when validation succeeds
        # What: Stores the numeric minimum hourly volume in GP (only set when parsed successfully)
        # Why: Avoids double-casting and keeps spike validation consistent with the saved value
        # How: Set during spike validation; otherwise remains None for non-spike alerts
        min_volume_value = None
        email_notification = request.POST.get('email_notification') == 'on'
        group_id = request.POST.get('group_id')  # Group to assign alert to
        
        # =============================================================================
        # SERVER-SIDE VALIDATION: ALL ITEMS REQUIRES MIN/MAX PRICE
        # =============================================================================
        # What: Validates that both minimum and maximum price fields have values when
        #       "All Items" is selected for any alert type
        # Why: This is a critical server-side backup validation in case client-side
        #       validation is bypassed (e.g., disabled JavaScript, direct API calls)
        #       When monitoring all items, price range filters are REQUIRED to narrow
        #       down the items being tracked and prevent noisy alerts
        # How: Check if is_all_items_flag is True, and if so, verify both minimum_price
        #       and maximum_price have non-empty values. If validation fails, add an
        #       error message and redirect back to the alerts page
        # Note: This validation applies to ALL alert types (spread, spike, sustained, threshold)
        if is_all_items_flag:
            # Check if either minimum_price or maximum_price is missing or empty
            # minimum_price and maximum_price come as strings from POST, so we check
            # for None, empty string, or whitespace-only values
            if not minimum_price or not minimum_price.strip() or not maximum_price or not maximum_price.strip():
                messages.error(request, 'Minimum Price and Maximum Price are required when tracking All Items')
                return redirect('alerts')
        
        # =============================================================================
        # SERVER-SIDE VALIDATION: SPIKE ALERTS REQUIRE MIN HOURLY VOLUME
        # =============================================================================
        # What: Ensures spike alerts always provide a minimum hourly volume (GP) value
        # Why: Spike alerts must filter out low-activity items; missing volume would make
        #      the alert configuration invalid and inconsistent with the required UI field
        # How: If alert_type is 'spike', verify min_volume is non-empty; otherwise return
        #      an error message and redirect back to the alerts page
        if alert_type == 'spike':
            # min_volume: Raw string value submitted from the form input
            # What: Holds the user-entered minimum hourly volume in GP
            # Why: We need to confirm it exists before converting to an integer later
            # How: Check for None, empty string, or whitespace-only values
            if not min_volume or not min_volume.strip():
                messages.error(request, 'Min Hourly Volume (GP) is required for spike alerts')
                return redirect('alerts')
            
            # What: Validate that the min_volume value is numeric
            # Why: Non-numeric values would raise a ValueError when we cast to int for storage
            # How: Attempt int conversion and handle failures with a user-facing error
            try:
                min_volume_value = int(min_volume)
            except (TypeError, ValueError):
                messages.error(request, 'Min Hourly Volume (GP) must be a whole number')
                return redirect('alerts')
        
        # show_notification: Controls whether a notification banner appears when alert triggers
        # What: Boolean flag from checkbox input
        # Why: Users may want alerts to track data without notification banners
        # How: If unchecked, is_dismissed will be set to True so notification never shows
        show_notification = request.POST.get('show_notification') == 'on'
        
        # Sustained Move specific fields
        min_consecutive_moves = request.POST.get('min_consecutive_moves')
        min_move_percentage = request.POST.get('min_move_percentage')
        volatility_buffer_size = request.POST.get('volatility_buffer_size')
        volatility_multiplier = request.POST.get('volatility_multiplier')
        sustained_item_ids_str = request.POST.get('sustained_item_ids', '')
        min_pressure_strength = request.POST.get('min_pressure_strength') or None
        min_pressure_spread_pct = request.POST.get('min_pressure_spread_pct')
        
        # Spread multi-item selection (when "Specific Item(s)" is chosen for spread alerts)
        # spread_item_ids_str: Comma-separated list of item IDs from the multi-item selector
        spread_item_ids_str = request.POST.get('spread_item_ids', '')
        # spread_scope: The scope selection from the dropdown (all, specific, multiple)
        spread_scope = request.POST.get('spread_scope', 'all')
        
        # =============================================================================
        # SPIKE ALERT SPECIFIC FIELDS
        # =============================================================================
        # What: Extract form data specific to spike alerts with multi-item support
        # Why: Spike alerts can now monitor multiple specific items instead of just one or all
        # How: Parse spike_scope dropdown and spike_item_ids from multi-item selector
        
        # spike_scope: 'all' for monitoring all items, 'specific' for single item, 'multiple' for multi-item
        spike_scope = request.POST.get('spike_scope', 'specific')
        # spike_item_ids_str: Comma-separated list of item IDs from the multi-item selector
        spike_item_ids_str = request.POST.get('spike_item_ids', '')
        
        # =============================================================================
        # THRESHOLD ALERT SPECIFIC FIELDS
        # =============================================================================
        # What: Extract form data specific to threshold alerts
        # Why: Threshold alerts have unique configuration options for monitoring price changes
        # How: Parse each field from POST data and validate/convert as needed
        
        # threshold_items_tracked: 'all' for monitoring all items, 'specific' for selected items
        threshold_items_tracked = request.POST.get('threshold_items_tracked', 'all')
        # threshold_item_ids_str: Comma-separated list of item IDs from the multi-item selector
        threshold_item_ids_str = request.POST.get('threshold_item_ids', '')
        # threshold_type: 'percentage' for percentage-based threshold, 'value' for absolute gold value
        threshold_type = request.POST.get('threshold_type', 'percentage')
        # threshold_direction: 'up' for price increases, 'down' for price decreases
        threshold_direction = request.POST.get('threshold_direction', 'up')
        # threshold_value: The actual threshold amount (percentage or gold value)
        threshold_value = request.POST.get('threshold_value')
        # threshold_reference: Which price to monitor - 'high' (instant sell), 'low' (instant buy), 'average'
        threshold_reference = request.POST.get('threshold_reference', 'high')
        
        # =============================================================================
        # COLLECTIVE MOVE ALERT SPECIFIC FIELDS
        # =============================================================================
        # What: Extract form data specific to collective_move alerts
        # Why: Collective move alerts monitor average percentage change across multiple items
        # How: Parse scope, item IDs, calculation method, direction, and threshold
        
        # collective_scope: 'all' for monitoring all items, 'specific' for selected items
        collective_scope = request.POST.get('collective_scope', 'specific')
        # collective_item_ids_str: Comma-separated list of item IDs from the multi-item selector
        collective_item_ids_str = request.POST.get('collective_item_ids', '')
        # collective_calculation_method: 'simple' for arithmetic mean, 'weighted' for value-weighted
        collective_calculation_method = request.POST.get('collective_calculation_method', 'simple')
        # collective_direction: 'up' for increases, 'down' for decreases, 'both' for either
        collective_direction = request.POST.get('collective_direction', 'both')
        # collective_threshold: The percentage threshold to trigger the alert
        collective_threshold = request.POST.get('collective_threshold')
        # collective_reference: Which price to monitor - 'high', 'low', or 'average'
        collective_reference = request.POST.get('collective_reference', 'average')
        
        direction_value = None
        if alert_type in ['spike', 'sustained']:
            direction_value = (direction or '').lower()
            if direction_value not in ['up', 'down', 'both']:
                direction_value = 'both'
        # For threshold alerts, use the threshold_direction field
        elif alert_type == 'threshold':
            direction_value = (threshold_direction or '').lower()
            if direction_value not in ['up', 'down']:
                direction_value = 'up'
        # For collective_move alerts, use the collective_direction field
        elif alert_type == 'collective_move':
            direction_value = (collective_direction or '').lower()
            if direction_value not in ['up', 'down', 'both']:
                direction_value = 'both'
        
        # Determine all-items flag based on selection
        is_all_items = is_all_items_flag
        # For spike alerts, use spike_scope to determine all-items flag
        # What: Spike alerts now use a 3-option dropdown (all, specific, multiple)
        # Why: Users can monitor all items, one item, or a curated list of items
        # How: Check spike_scope value to set is_all_items appropriately
        if alert_type == 'spike':
            is_all_items = (spike_scope == 'all')
        # For threshold alerts, use the threshold_items_tracked field to determine all-items flag
        elif alert_type == 'threshold':
            is_all_items = (threshold_items_tracked == 'all')
        # For collective_move alerts, use the collective_scope field to determine all-items flag
        elif alert_type == 'collective_move':
            is_all_items = (collective_scope == 'all')
        
        # Handle sustained move multi-item selection
        sustained_item_ids_json = None
        sustained_item_name = None
        if alert_type == 'sustained' and not is_all_items and sustained_item_ids_str:
            item_ids = [int(x) for x in sustained_item_ids_str.split(',') if x.strip()]
            if item_ids:
                sustained_item_ids_json = json_module.dumps(item_ids)
                # Get first item name for display
                mapping = get_item_mapping()
                for name, item in mapping.items():
                    if item['id'] == item_ids[0]:
                        sustained_item_name = item['name']
                        break
        
        # =============================================================================
        # HANDLE SPIKE MULTI-ITEM SELECTION
        # =============================================================================
        # What: Process spike_item_ids when user selects "Specific Item(s)" for spike alerts
        # Why: Spike alerts can now monitor multiple specific items for price changes over time
        # How: Parse comma-separated IDs, convert to JSON array, get first item name for display
        spike_item_ids_json = None
        spike_item_name = None
        if alert_type == 'spike' and spike_scope == 'multiple' and spike_item_ids_str:
            # Parse comma-separated item IDs from the multi-item selector
            item_ids = [int(x) for x in spike_item_ids_str.split(',') if x.strip()]
            if item_ids:
                spike_item_ids_json = json_module.dumps(item_ids)
                # Get first item name for display purposes in alert list
                mapping = get_item_mapping()
                for name, item in mapping.items():
                    if item['id'] == item_ids[0]:
                        spike_item_name = item['name']
                        break
        
        # Handle spread multi-item selection
        # What: Process the spread_item_ids when user selects "Specific Item(s)" for spread alerts
        # Why: Allows monitoring multiple specific items for spread threshold
        # How: Parse comma-separated IDs, convert to JSON array, get first item name for display
        spread_item_ids_json = None
        spread_item_name = None
        if alert_type == 'spread' and spread_scope == 'multiple' and spread_item_ids_str:
            # Parse comma-separated item IDs from the multi-item selector
            item_ids = [int(x) for x in spread_item_ids_str.split(',') if x.strip()]
            if item_ids:
                spread_item_ids_json = json_module.dumps(item_ids)
                # Get first item name for display purposes
                mapping = get_item_mapping()
                for name, item in mapping.items():
                    if item['id'] == item_ids[0]:
                        spread_item_name = item['name']
                        break
        
        # =============================================================================
        # HANDLE THRESHOLD MULTI-ITEM SELECTION
        # =============================================================================
        # What: Process threshold_item_ids when user selects "Specific Items" for threshold alerts
        # Why: Threshold alerts can monitor multiple specific items for price changes
        # How: Parse comma-separated IDs, convert to JSON array, get first item name for display
        threshold_item_ids_json = None
        threshold_item_name = None
        threshold_is_all_items = (threshold_items_tracked == 'all')
        
        if alert_type == 'threshold':
            if threshold_items_tracked == 'specific' and threshold_item_ids_str:
                # Parse comma-separated item IDs from the multi-item selector
                item_ids = [int(x) for x in threshold_item_ids_str.split(',') if x.strip()]
                if item_ids:
                    threshold_item_ids_json = json_module.dumps(item_ids)
                    # Get first item name for display purposes in alert list
                    mapping = get_item_mapping()
                    for name, item in mapping.items():
                        if item['id'] == item_ids[0]:
                            threshold_item_name = item['name']
                            break
        
        # =============================================================================
        # HANDLE COLLECTIVE MOVE MULTI-ITEM SELECTION
        # =============================================================================
        # What: Process collective_item_ids when user selects "Specific Item(s)" for collective_move alerts
        # Why: Collective move alerts track average change across multiple items
        # How: Parse comma-separated IDs, convert to JSON array, get first item name for display
        collective_item_ids_json = None
        collective_item_name = None
        if alert_type == 'collective_move' and collective_scope == 'specific' and collective_item_ids_str:
            # Parse comma-separated item IDs from the multi-item selector
            item_ids = [int(x) for x in collective_item_ids_str.split(',') if x.strip()]
            if item_ids:
                collective_item_ids_json = json_module.dumps(item_ids)
                # Get first item name for display purposes in alert list
                mapping = get_item_mapping()
                for name, item in mapping.items():
                    if item['id'] == item_ids[0]:
                        collective_item_name = item['name']
                        break
        
        # Look up item ID from name if not provided (for non-sustained alerts)
        if not item_id and item_name and alert_type != 'sustained':
            mapping = get_item_mapping()
            item_data = mapping.get(item_name.lower())
            if item_data:
                item_id = item_data['id']
                item_name = item_data['name']
        
        # Determine price field value (time_frame for spike, price for others)
        price_value = None
        if alert_type == 'spike':
            price_value = int(time_frame) if time_frame else None
        elif alert_type != 'sustained' and price:
            price_value = int(price)
        
        # For sustained alerts, store time_frame in dedicated field
        time_frame_value = None
        if alert_type == 'sustained' and time_frame:
            time_frame_value = int(time_frame)
        elif alert_type == 'collective_move' and time_frame:
            # collective_time_frame: Time window for collective move comparisons
            # What: Stores the time frame in minutes for rolling baseline checks
            # Why: Collective move alerts compare against price from X minutes ago
            # How: Parse the time_frame input and store in the time_frame field
            time_frame_value = int(time_frame)
        
        # Determine final item name and ID based on alert type and scope
        # final_item_name: The display name for the alert (first item name or None for all-items)
        # final_item_id: The primary item ID (first item for multi-item, or single item ID)
        final_item_name = None
        final_item_id = None
        
        if alert_type == 'sustained' and sustained_item_name:
            final_item_name = sustained_item_name
        elif alert_type == 'spread' and spread_item_name:
            final_item_name = spread_item_name
        elif alert_type == 'spike' and spike_item_name:
            # For spike alerts with specific items, use first item name
            final_item_name = spike_item_name
        elif alert_type == 'threshold' and threshold_item_name:
            # For threshold alerts with specific items, use first item name
            final_item_name = threshold_item_name
        elif alert_type == 'collective_move' and collective_item_name:
            # For collective_move alerts with specific items, use first item name
            final_item_name = collective_item_name
        elif not is_all_items:
            final_item_name = item_name
        
        if alert_type == 'sustained' and sustained_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(sustained_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif alert_type == 'spread' and spread_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(spread_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif alert_type == 'spike' and spike_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(spike_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif alert_type == 'threshold' and threshold_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(threshold_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif alert_type == 'collective_move' and collective_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(collective_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif item_id and not is_all_items:
            final_item_id = int(item_id)
        
        # =============================================================================
        # DETERMINE REFERENCE VALUE
        # =============================================================================
        # What: Determine which price type (high/low/average) to use for the alert
        # Why: Users can choose to monitor high price (instant buy), low price (instant sell), or average
        # How: For threshold alerts, use the threshold_reference field; for all other alerts use reference
        # Note: All alert types now support reference selection; default to 'average' if not specified
        # =============================================================================
        if alert_type == 'threshold':
            # Threshold alerts use their own reference field from the form
            reference_value = threshold_reference if threshold_reference else 'average'
        elif alert_type == 'collective_move':
            # Collective move alerts use their own reference field from the form
            reference_value = collective_reference if collective_reference else 'average'
        else:
            # Spike and Sustained alerts use the generic reference field
            # Default to 'average' if not specified (previously defaulted to 'high' for spike)
            reference_value = reference if reference else 'average'
        
        # =============================================================================
        # DETERMINE PERCENTAGE VALUE
        # =============================================================================
        # What: Calculate the percentage/threshold value to store
        # Why: Different alert types use the percentage field for different purposes
        # How: For threshold alerts, use threshold_value; for others use percentage
        # =============================================================================
        # IMPORTANT: For threshold alerts, we must store in the correct field based on threshold_type:
        #   - 'percentage' type: Store in percentage field, target_price should be None
        #   - 'value' type: Store in target_price field, percentage should be None
        # This ensures data integrity and prevents confusion about which field is authoritative
        percentage_value = None
        target_price_value = None
        
        if alert_type == 'threshold' and threshold_value:
            # For threshold alerts, determine which field to store the value in
            if threshold_type == 'value':
                # Value-based threshold: Store in target_price, leave percentage as None
                target_price_value = int(float(threshold_value))
            else:
                # Percentage-based threshold: Store in percentage, leave target_price as None
                percentage_value = float(threshold_value)
        elif alert_type == 'collective_move' and collective_threshold:
            # Collective move alerts use percentage field for their threshold
            percentage_value = float(collective_threshold)
        elif percentage:
            # Non-threshold alerts use percentage field normally
            percentage_value = float(percentage)
        
        # =============================================================================
        # DETERMINE ITEM_IDS VALUE
        # =============================================================================
        # What: Determine which item_ids JSON to store based on alert type
        # Why: Different alert types (spread, threshold, spike, collective_move) use the same item_ids field
        # How: Check alert type and use the appropriate item_ids variable
        item_ids_json = None
        if alert_type == 'threshold' and threshold_item_ids_json:
            item_ids_json = threshold_item_ids_json
        elif alert_type == 'spread' and spread_item_ids_json:
            item_ids_json = spread_item_ids_json
        elif alert_type == 'spike' and spike_item_ids_json:
            item_ids_json = spike_item_ids_json
        elif alert_type == 'collective_move' and collective_item_ids_json:
            item_ids_json = collective_item_ids_json
        
        alert = Alert.objects.create(
            user=user,
            alert_name=alert_name,
            type=alert_type,
            item_name=final_item_name,
            item_id=final_item_id,
            price=price_value,
            reference=reference_value,
            percentage=percentage_value,
            # target_price: Set only for value-based threshold alerts, None otherwise
            target_price=target_price_value,
            is_all_items=is_all_items,
            minimum_price=int(minimum_price) if minimum_price else None,
            maximum_price=int(maximum_price) if maximum_price else None,
            email_notification=email_notification,
            is_active=True,
            is_triggered=False,
            # is_dismissed: Set to True if show_notification is False to prevent notification
            # What: Controls whether notification banner appears
            # Why: If user unchecks "Show Alert Notification", they don't want banners
            # How: Setting is_dismissed=True means notification won't display even when triggered
            is_dismissed=not show_notification,
            show_notification=show_notification,
            direction=direction_value,
            time_frame=time_frame_value,
            # Sustained Move fields
            min_consecutive_moves=int(min_consecutive_moves) if min_consecutive_moves else None,
            min_move_percentage=float(min_move_percentage) if min_move_percentage else None,
            volatility_buffer_size=int(volatility_buffer_size) if volatility_buffer_size else None,
            volatility_multiplier=float(volatility_multiplier) if volatility_multiplier else None,
            # min_volume: Use the validated integer for spike alerts; parse for other alert types if provided
            # What: Avoid parsing empty strings for non-spike alerts
            # Why: Non-spike alerts may omit min_volume entirely, so we guard against empty values
            # How: Only cast to int when min_volume is present and non-empty after trimming
            min_volume=(
                min_volume_value
                if min_volume_value is not None
                else (int(min_volume) if min_volume and str(min_volume).strip() else None)
            ),
            sustained_item_ids=sustained_item_ids_json,
            min_pressure_strength=min_pressure_strength,
            min_pressure_spread_pct=float(min_pressure_spread_pct) if min_pressure_spread_pct else None,
            # item_ids: JSON array of item IDs for multi-item alerts (spread, threshold, spike, collective_move)
            item_ids=item_ids_json,
            # threshold_type: 'percentage' or 'value' for threshold alerts only
            threshold_type=threshold_type if alert_type == 'threshold' else None,
            # baseline_method: How to calculate baseline for spike alerts
            # What: Specifies comparison method for spike alerts (single_point, average, min_max)
            # Why: Different comparison methods may be useful for different trading strategies
            # How: Currently defaults to 'single_point' (compare to price at exactly [timeframe] ago)
            baseline_method='single_point' if alert_type == 'spike' else None,
            # calculation_method: 'simple' or 'weighted' for collective_move alerts only
            # What: Determines how average is calculated (arithmetic mean vs value-weighted mean)
            # Why: Users may want expensive items to count more in the average
            # How: 'simple' = sum(changes)/count, 'weighted' = sum(change*value)/sum(values)
            calculation_method=collective_calculation_method if alert_type == 'collective_move' else None
        )
        
        # =============================================================================
        # SPIKE ALERT: CAPTURE BASELINE PRICES
        # =============================================================================
        # What: For spike alerts with specific items, capture initial baseline prices at creation
        # Why: The rolling window comparison needs a starting baseline for each monitored item
        #      Until the full timeframe has passed, we'll use the creation-time price as baseline
        # How: Fetch current prices for monitored items and store in baseline_prices JSON field
        # Note: For all-items spike alerts, baselines are managed by check_alerts.py price_history
        if alert_type == 'spike' and not is_all_items:
            all_prices = get_all_current_prices()
            
            if all_prices:
                import time as time_module
                baseline_prices_dict = {}
                current_timestamp = int(time_module.time())
                
                # Determine which items to capture baseline prices for
                # items_to_capture: List of item IDs to get baseline prices for
                items_to_capture = []
                
                if spike_item_ids_json:
                    # Multi-item spike: capture prices for all selected items
                    items_to_capture = [str(x) for x in json_module.loads(spike_item_ids_json)]
                elif final_item_id:
                    # Single-item spike: capture price for just that item
                    items_to_capture = [str(final_item_id)]
                
                # Capture baseline prices for each item
                # What: Get the initial baseline price using the user's chosen reference type
                # Why: This is the starting point for the rolling window comparison
                # How: For each item, get high/low/average price based on reference setting
                for item_id in items_to_capture:
                    item_id_str = str(item_id)
                    price_data = all_prices.get(item_id_str)
                    
                    if not price_data:
                        # Skip items where price data is unavailable
                        continue
                    
                    # Get the appropriate reference price based on user's selection
                    # baseline_price: The initial baseline price for this item
                    high = price_data.get('high')
                    low = price_data.get('low')
                    
                    if reference_value == 'high':
                        baseline_price = high
                    elif reference_value == 'low':
                        baseline_price = low
                    elif reference_value == 'average':
                        # Average of high and low prices
                        if high is not None and low is not None:
                            baseline_price = (high + low) // 2
                        else:
                            baseline_price = high or low
                    else:
                        baseline_price = high  # Default to high
                    
                    if baseline_price is not None:
                        # Store both the price and timestamp for the rolling window
                        # What: Each baseline entry contains price and when it was recorded
                        # Why: The check_alerts.py needs to know when this baseline was set
                        #      to determine if it's old enough to be used as comparison point
                        # How: JSON structure allows storing both values per item
                        baseline_prices_dict[item_id_str] = {
                            'price': baseline_price,
                            'timestamp': current_timestamp
                        }
                
                # Store the baseline prices if any were captured
                if baseline_prices_dict:
                    alert.baseline_prices = json_module.dumps(baseline_prices_dict)
                    alert.save()
        
        # =============================================================================
        # THRESHOLD ALERT: CAPTURE REFERENCE PRICES OR VALIDATE TARGET PRICE
        # =============================================================================
        # What: For threshold alerts, capture baseline prices for percentage-based OR validate value-based
        # Why: Percentage-based thresholds need a baseline to calculate % change from
        #      Value-based thresholds already have target_price set from creation
        # How: 
        #      - For percentage: Fetch current prices and store in reference_prices JSON dict
        #      - For value: Just ensure reference_prices is cleared (target_price already set above)
        if alert_type == 'threshold':
            # Validate: Value-based thresholds only allowed for single items
            # What: Block value-based threshold with multiple items
            # Why: Value-based thresholds don't make sense for multiple items with different prices
            # How: Check if threshold_type is 'value' and there are multiple items selected
            has_multiple_items = (
                threshold_is_all_items or 
                (threshold_item_ids_json and len(json_module.loads(threshold_item_ids_json)) > 1)
            )
            
            if threshold_type == 'value' and has_multiple_items:
                # This shouldn't happen if the UI is working correctly, but handle it gracefully
                # Force switch to percentage mode: move value from target_price to percentage
                # What: Convert value-based alert to percentage-based when multiple items detected
                # Why: Value-based thresholds are only valid for single items
                # How: Transfer the value to percentage field, clear target_price, update threshold_type
                alert.threshold_type = 'percentage'
                alert.percentage = float(alert.target_price) if alert.target_price else float(threshold_value) if threshold_value else None
                alert.target_price = None
                threshold_type = 'percentage'
                alert.save()
            
            if threshold_type == 'value':
                # =============================================================================
                # VALUE-BASED THRESHOLD: CAPTURE BASELINE REFERENCE PRICE
                # =============================================================================
                # What: Capture the current market price as a baseline for value-based threshold alerts
                # Why: Even though value-based thresholds compare against a user-defined target_price,
                #      users want to see what the item's price was at the time the alert was created.
                #      This "baseline price" provides context — e.g., "I set a target of 15M when the
                #      item was at 12M, and now it hit 15M". Without the baseline, users only see the
                #      target and current price but not where the price started from.
                # How: Fetch current prices from the API and store the baseline in reference_prices
                #      JSON dict (same field used by percentage-based thresholds). The check_alerts
                #      command will include this baseline in triggered_data when the alert fires.
                # Note: Previously this was set to None. Now we capture it for display purposes only —
                #       the trigger logic itself still compares current_price vs target_price.
                # =============================================================================
                all_prices = get_all_current_prices()
                if all_prices and final_item_id:
                    item_id_str = str(final_item_id)
                    price_data = all_prices.get(item_id_str)
                    if price_data:
                        # baseline_price: The item's current price at alert creation time,
                        # using the user's chosen reference type (high/low/average)
                        if reference_value == 'low':
                            baseline_price = price_data.get('low')
                        elif reference_value == 'average':
                            high = price_data.get('high')
                            low = price_data.get('low')
                            baseline_price = (high + low) // 2 if high and low else None
                        else:
                            baseline_price = price_data.get('high')
                        
                        if baseline_price:
                            alert.reference_prices = json_module.dumps({item_id_str: baseline_price})
                        else:
                            alert.reference_prices = None
                    else:
                        alert.reference_prices = None
                else:
                    alert.reference_prices = None
                alert.save()
            else:
                # Percentage-based threshold: Capture reference prices for all monitored items
                # What: Fetch current prices and store as baseline for % calculations
                # Why: Need to know what prices were at creation to calculate % change later
                # How: Get all prices from API, filter to monitored items, store as JSON dict
                all_prices = get_all_current_prices()
                
                if all_prices:
                    reference_prices_dict = {}
                    
                    # Determine which items to capture reference prices for
                    # items_to_capture: List of item IDs to get reference prices for
                    items_to_capture = []
                    
                    if threshold_is_all_items:
                        # All items mode: capture prices for all items (respecting min/max filters)
                        # What: Get baseline prices for entire market
                        # Why: User wants to monitor ALL items for threshold changes
                        # How: Iterate all prices, apply min/max filters if set
                        for item_id, price_data in all_prices.items():
                            # Apply min/max price filters if configured
                            # What: Skip items outside the user's price range
                            # Why: User may only want to monitor items in a specific price range
                            high = price_data.get('high')
                            low = price_data.get('low')
                            
                            if alert.minimum_price is not None:
                                if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                                    continue
                            if alert.maximum_price is not None:
                                if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                                    continue
                            
                            items_to_capture.append(item_id)
                    elif threshold_item_ids_json:
                        # Specific items mode: capture prices for selected items only
                        # What: Get baseline prices for user-selected items
                        # Why: User wants to monitor specific items
                        # How: Parse the item_ids JSON and use those
                        items_to_capture = [str(x) for x in json_module.loads(threshold_item_ids_json)]
                    elif final_item_id:
                        # =============================================================================
                        # SINGLE-ITEM THRESHOLD ALERT: CAPTURE REFERENCE PRICE
                        # =============================================================================
                        # What: Add the single item ID to items_to_capture for reference price capture
                        # Why: Single-item percentage-based threshold alerts need a reference price to
                        #      calculate percentage change. Without this, the alert will never trigger
                        #      because reference_prices will be empty.
                        # How: Check if final_item_id is set (single-item mode) and add it to the list
                        # Note: This case was previously missing, causing single-item percentage threshold
                        #       alerts to never capture their baseline price and thus never trigger
                        # =============================================================================
                        items_to_capture = [str(final_item_id)]
                    
                    # Capture reference prices for each item
                    # What: Get the baseline price using the user's chosen reference type
                    # Why: This is the price we'll compare against to calculate % change
                    # How: For each item, get the high/low/average price based on reference setting
                    for item_id in items_to_capture:
                        item_id_str = str(item_id)
                        price_data = all_prices.get(item_id_str)
                        
                        if not price_data:
                            # Skip items where price data is unavailable
                            continue
                        
                        # Get the appropriate reference price based on user's selection
                        # reference_price: The baseline price for this item
                        high = price_data.get('high')
                        low = price_data.get('low')
                        
                        if threshold_reference == 'high':
                            reference_price = high
                        elif threshold_reference == 'low':
                            reference_price = low
                        elif threshold_reference == 'average':
                            # Average of high and low prices
                            if high is not None and low is not None:
                                reference_price = (high + low) // 2
                            else:
                                reference_price = high or low
                        else:
                            reference_price = high  # Default to high
                        
                        if reference_price is not None:
                            reference_prices_dict[item_id_str] = reference_price
                    
                    # Store the reference prices if any were captured
                    if reference_prices_dict:
                        alert.reference_prices = json_module.dumps(reference_prices_dict)
                        alert.target_price = None  # Clear target price for percentage mode
                        alert.save()
        
        # =============================================================================
        # COLLECTIVE MOVE ALERT: CAPTURE REFERENCE PRICES (BASELINES)
        # =============================================================================
        # What: For collective_move alerts, capture baseline prices for all monitored items
        # Why: Collective move alerts calculate average percentage change from baseline
        #      Each item needs its own baseline price to calculate individual % change
        # How: Fetch current prices and store in reference_prices JSON dict, same as threshold
        # Note: Uses the collective_reference setting (high/low/average) for baseline price type
        if alert_type == 'collective_move':
            all_prices = get_all_current_prices()
            
            if all_prices:
                reference_prices_dict = {}
                
                # Determine which items to capture reference prices for
                # items_to_capture: List of item IDs to get reference prices for
                items_to_capture = []
                
                if is_all_items:
                    # All items mode: capture prices for all items (respecting min/max filters)
                    # What: Get baseline prices for entire market
                    # Why: User wants to monitor ALL items for collective average change
                    # How: Iterate all prices, apply min/max filters if set
                    for item_id, price_data in all_prices.items():
                        # Apply min/max price filters if configured
                        # What: Skip items outside the user's price range
                        # Why: User may only want to monitor items in a specific price range
                        high = price_data.get('high')
                        low = price_data.get('low')
                        
                        if alert.minimum_price is not None:
                            if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                                continue
                        if alert.maximum_price is not None:
                            if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                                continue
                        
                        items_to_capture.append(item_id)
                elif collective_item_ids_json:
                    # Specific items mode: capture prices for selected items only
                    # What: Get baseline prices for user-selected items
                    # Why: User wants to monitor specific group of items
                    # How: Parse the item_ids JSON and use those
                    items_to_capture = [str(x) for x in json_module.loads(collective_item_ids_json)]
                
                # Capture reference prices for each item
                # What: Get the baseline price using the user's chosen reference type
                # Why: This is the price we'll compare against to calculate % change
                # How: For each item, get the high/low/average price based on reference setting
                for item_id in items_to_capture:
                    item_id_str = str(item_id)
                    price_data = all_prices.get(item_id_str)
                    
                    if not price_data:
                        # Skip items where price data is unavailable
                        continue
                    
                    # Get the appropriate reference price based on user's selection
                    # reference_price: The baseline price for this item
                    high = price_data.get('high')
                    low = price_data.get('low')
                    
                    if collective_reference == 'high':
                        reference_price = high
                    elif collective_reference == 'low':
                        reference_price = low
                    elif collective_reference == 'average':
                        # Average of high and low prices
                        if high is not None and low is not None:
                            reference_price = (high + low) // 2
                        else:
                            reference_price = high or low
                    else:
                        reference_price = high  # Default to high
                    
                    if reference_price is not None:
                        reference_prices_dict[item_id_str] = reference_price
                
                # Store the reference prices if any were captured
                if reference_prices_dict:
                    alert.reference_prices = json_module.dumps(reference_prices_dict)
                    alert.save()
        
        # Assign to group if specified
        if group_id:
            from Website.models import AlertGroup
            # Use get_or_create to create the group if it doesn't exist
            # What: Creates the group if it's new, or retrieves it if it already exists
            # Why: User may have typed a new group name in the modal - need to create it
            # How: get_or_create returns (object, created_bool), we only need the object
            group, created = AlertGroup.objects.get_or_create(user=user, name=group_id)
            alert.groups.add(group)
        
        messages.success(request, 'Alert created')
        return redirect('alerts')
    
    return redirect('alerts')


def alerts_api(request):
    """
    API endpoint to fetch current alerts status.
    
    What: Returns JSON data containing all user alerts and triggered notifications.
    
    Why: This endpoint is called on every page load and every 30 seconds (polling),
         so performance is critical. Optimizations applied:
         1. Load item mapping from local JSON file (not API)
         2. Use prefetch_related to avoid N+1 queries on alert.groups
         3. Reuse fetched data instead of duplicate queries
    
    How: 
        - Load item mapping from local JSON file - avoids ~500ms API call
        - Query alerts with prefetch_related('groups') - single JOIN instead of N queries
        - Build triggered_data from already-fetched alerts - no duplicate query
    
    Returns:
        JsonResponse with structure:
        {
            'alerts': [...],      # All alerts for user
            'triggered': [...],   # Triggered and non-dismissed alerts
            'groups': [...]       # Unique group names
        }
    """
    from Website.models import get_item_price
    
    # Get current user
    user = request.user if request.user.is_authenticated else None
    
    # =============================================================================
    # FETCH CURRENT PRICES FROM EXTERNAL API (NO CACHING - USER REQUIREMENT)
    # =============================================================================
    # What: Fetch fresh prices from the Wiki API on every request
    # Why: User requires real-time price updates, caching would cause stale data
    # How: Direct API call to prices.runescape.wiki/api/v1/osrs/latest
    # Note: This adds ~200-500ms latency but ensures prices are always current
    all_prices = get_all_current_prices()
    
    # Get item mapping for icons (loaded from local JSON file for performance)
    mapping = get_item_mapping()
    
    # =============================================================================
    # PERFORMANCE FIX: Use prefetch_related to avoid N+1 queries
    # =============================================================================
    # What: Add prefetch_related('groups') to the queryset
    # Why: Without prefetch_related, accessing alert.groups for each alert triggers
    #      a separate database query. For 50 alerts, that's 50 extra queries!
    # How: prefetch_related fetches all group relationships in a single query
    #      and caches them, so subsequent .groups access is O(1) memory lookup
    # Impact: Reduces database queries from O(N) to O(1) for N alerts
    
    # alerts_qs: QuerySet for user's alerts, or empty queryset if not authenticated
    alerts_qs = Alert.objects.filter(user=user).prefetch_related('groups') if user else Alert.objects.none()
    
    # all_alerts: Ordered list of all alerts for this user
    # Ordering: Alphabetically by item_name, with NULL/All items sorted first
    all_alerts = list(alerts_qs.order_by(Coalesce('item_name', Value('All items')).asc()))
    
    # alerts_data: List to accumulate alert dictionaries for JSON response
    alerts_data = []
    
    # all_groups_set: Set of unique group names across all alerts (for filters)
    all_groups_set = set()
    
    # =============================================================================
    # PERFORMANCE FIX #3: Build triggered_data from already-fetched alerts
    # =============================================================================
    # What: Collect triggered alerts while iterating through all_alerts
    # Why: Previously, there was a SECOND database query to get triggered alerts:
    #      triggered_alerts = alerts_qs.filter(is_triggered=True, is_dismissed=False)
    #      This caused N+1 queries again since prefetch wasn't applied
    # How: Check is_triggered and is_dismissed on each alert as we iterate,
    #      and collect those that match into triggered_alerts_list
    # Impact: Eliminates redundant database query and its N+1 group lookups
    
    # triggered_alerts_list: Alerts that are triggered and not dismissed
    # Built during the main loop instead of a separate query
    triggered_alerts_list = []
    
    for alert in all_alerts:
        # Get icon for item if available
        icon = None
        if alert.item_name and mapping:
            item_data = mapping.get(alert.item_name.lower())
            if item_data:
                icon = item_data.get('icon')
        
        alert_dict = {
            'id': alert.id,
            'text': str(alert),
            'alert_name': alert.alert_name,
            'is_triggered': alert.is_triggered,
            'is_active': alert.is_active,
            'triggered_text': alert.triggered_text() if alert.is_triggered else None,
            'type': alert.type,
            'direction': alert.direction,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price,
            'percentage': alert.percentage,
            'time_frame': alert.price if alert.type == 'spike' else (alert.time_frame if alert.type in ['sustained', 'collective_move'] else None),
            'minimum_price': alert.minimum_price,
            'maximum_price': alert.maximum_price,
            'created_at': alert.created_at.isoformat(),
            'last_triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
            'groups': list(alert.groups.values_list('name', flat=True)),
            'item_id': alert.item_id,
            'icon': icon,
            # Sustained-specific fields
            'min_consecutive_moves': alert.min_consecutive_moves if alert.type == 'sustained' else None,
            'min_move_percentage': alert.min_move_percentage if alert.type == 'sustained' else None,
            'min_volume': alert.min_volume if alert.type == 'sustained' else None,
            'volatility_buffer_size': alert.volatility_buffer_size if alert.type == 'sustained' else None,
            'volatility_multiplier': alert.volatility_multiplier if alert.type == 'sustained' else None,
            'min_pressure_strength': alert.min_pressure_strength if alert.type == 'sustained' else None,
            'min_pressure_spread_pct': alert.min_pressure_spread_pct if alert.type == 'sustained' else None,
            # email_notification: Whether SMS/email alerts are enabled
            'email_notification': alert.email_notification,
            # show_notification: Whether notification banner appears when alert triggers
            'show_notification': alert.show_notification if alert.show_notification is not None else True,
            # Threshold-specific fields
            # threshold_type: 'percentage' or 'value' - how threshold is measured
            'threshold_type': alert.threshold_type if alert.type == 'threshold' else None,
            # target_price: The target price for value-based threshold alerts
            'target_price': alert.target_price if alert.type == 'threshold' else None,
            # reference_prices: JSON dict of baseline prices for percentage-based threshold alerts
            'reference_prices': alert.reference_prices if alert.type == 'threshold' else None,
            # item_ids: JSON array of item IDs for multi-item alerts (spread, threshold, spike)
            # What: Returns the item_ids field if present, used to determine if alert tracks multiple items
            # Why: Frontend needs to know if this is a multi-item alert to show appropriate UI
            #      (e.g., threshold distance is only calculable for single-item alerts)
            'item_ids': alert.item_ids
        }

        for g in alert_dict['groups']:
            all_groups_set.add(g)
        
        # Add spread data for single item spread alerts
        if alert.type == 'spread' and not alert.is_all_items and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                high = price_data.get('high')
                low = price_data.get('low')
                if high and low and low > 0:
                    spread = round(((high - low) / low) * 100, 2)
                    alert_dict['spread_high'] = high
                    alert_dict['spread_low'] = low
                    alert_dict['spread_percentage'] = spread
        
        # Add current price for spike alerts
        # What: Include the current reference price (high/low) in the API response for spike alerts.
        # Why: The front-end uses this to show context/progress for a spike alert on a specific item.
        # How: Read from the cached all_prices mapping; choose low/high based on the alert's reference.
        if alert.type == 'spike' and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                if alert.reference == 'low':
                    alert_dict['current_price'] = price_data.get('low')
                else:
                    alert_dict['current_price'] = price_data.get('high')
        
        # Add current price for single-item threshold alerts
        # What: Include current price for threshold alerts to show progress in UI
        # Why: Users want to see how close the price is to their threshold
        # How: Similar to spike alerts, get price based on reference type
        # Note: Only include for single-item alerts (item_id set, and either no item_ids or item_ids has exactly 1 item)
        if alert.type == 'threshold' and alert.item_id and all_prices and not alert.is_all_items:
            # Check if this is a multi-item alert by examining item_ids
            # What: Determine if alert tracks multiple specific items
            # Why: current_price only makes sense for single-item alerts
            # How: Parse item_ids JSON and check if it has more than 1 item
            is_multi_item = False
            if alert.item_ids:
                try:
                    item_ids_list = json.loads(alert.item_ids)
                    is_multi_item = isinstance(item_ids_list, list) and len(item_ids_list) > 1
                except (json.JSONDecodeError, TypeError):
                    pass
            
            if not is_multi_item:
                price_data = all_prices.get(str(alert.item_id))
                if price_data:
                    if alert.reference == 'low':
                        alert_dict['current_price'] = price_data.get('low')
                    elif alert.reference == 'average':
                        high = price_data.get('high')
                        low = price_data.get('low')
                        if high and low:
                            alert_dict['current_price'] = (high + low) // 2
                    else:
                        alert_dict['current_price'] = price_data.get('high')
        
        alerts_data.append(alert_dict)
        
        # =============================================================================
        # COLLECT TRIGGERED ALERTS DURING ITERATION (Performance Fix #3)
        # =============================================================================
        # What: Check if this alert should be included in the triggered list
        # Why: Eliminates the need for a separate database query for triggered alerts
        # How: Check is_triggered=True AND is_dismissed=False, then add to list
        if alert.is_triggered and not alert.is_dismissed:
            triggered_alerts_list.append(alert)
    
    # =============================================================================
    # BUILD TRIGGERED ALERTS DATA FROM COLLECTED LIST
    # =============================================================================
    # What: Build the triggered_data response from alerts collected during main loop
    # Why: Previously this used a separate query: alerts_qs.filter(is_triggered=True, is_dismissed=False)
    #      That query didn't have prefetch_related, causing N+1 queries again
    # How: Iterate over triggered_alerts_list (already fetched with prefetch_related)
    #      and build the response dictionaries
    # Note: All alert objects in triggered_alerts_list already have .groups prefetched
    
    triggered_data = []
    for alert in triggered_alerts_list:
        triggered_dict = {
            'id': alert.id,
            'triggered_text': alert.triggered_text(),
            'type': alert.type,
            'direction': alert.direction,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price,
            'time_frame': alert.price if alert.type == 'spike' else (alert.time_frame if alert.type in ['sustained', 'collective_move'] else None),
            'percentage': alert.percentage
        }

        
        # Add spread data for single item spread alerts
        if alert.type == 'spread' and not alert.is_all_items and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                high = price_data.get('high')
                low = price_data.get('low')
                if high and low and low > 0:
                    spread = round(((high - low) / low) * 100, 2)
                    triggered_dict['spread_high'] = high
                    triggered_dict['spread_low'] = low
                    triggered_dict['spread_percentage'] = spread
        
        # Add current price for spike alerts
        # What: Include current reference price (high/low) for triggered spike alerts.
        # Why: The triggered alerts list shows additional context for spike alerts.
        # How: Read from cached all_prices; choose low/high based on alert.reference.
        if alert.type == 'spike' and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                if alert.reference == 'low':
                    triggered_dict['current_price'] = price_data.get('low')
                else:
                    triggered_dict['current_price'] = price_data.get('high')
        
        # Add sustained move data
        if alert.type == 'sustained':
            triggered_dict['min_consecutive_moves'] = alert.min_consecutive_moves
            triggered_dict['min_move_percentage'] = alert.min_move_percentage
            triggered_dict['min_volume'] = alert.min_volume
            triggered_dict['volatility_buffer_size'] = alert.volatility_buffer_size
            triggered_dict['volatility_multiplier'] = alert.volatility_multiplier
            
            # Parse triggered_data for sustained alert details
            if alert.triggered_data:
                try:
                    import json as json_module
                    sustained_data = json_module.loads(alert.triggered_data)
                    triggered_dict['sustained_item_name'] = sustained_data.get('item_name')
                    triggered_dict['sustained_direction'] = sustained_data.get('streak_direction')
                    triggered_dict['sustained_streak_count'] = sustained_data.get('streak_count')
                    triggered_dict['sustained_total_move'] = sustained_data.get('total_move_percent')
                    triggered_dict['sustained_start_price'] = sustained_data.get('start_price')
                    triggered_dict['sustained_current_price'] = sustained_data.get('current_price')
                    triggered_dict['sustained_volume'] = sustained_data.get('volume')
                except:
                    pass

        triggered_data.append(triggered_dict)
    
    all_groups = sorted(all_groups_set)
    return JsonResponse({'alerts': alerts_data, 'triggered': triggered_data, 'groups': all_groups})


def alerts_api_minimal(request):
    """
    MINIMAL API endpoint for alerts list view - optimized for INSTANT page loads.
    
    What: Returns alerts data WITHOUT waiting for external price API.
    
    Why: The external price API (prices.runescape.wiki) has variable latency (100-1000ms).
         By not waiting for prices, the alerts list renders instantly.
         Price-dependent data (current_price, spread_percentage) is fetched separately
         by the frontend via /api/alerts/prices/ endpoint.
    
    How: 
        - Returns core alert fields needed for list rendering
        - Does NOT call get_all_current_prices() - that's deferred to separate endpoint
        - Includes reference field so frontend can fetch correct price later
        
    Performance Impact:
        - Eliminates 100-1000ms external API latency from initial load
        - List renders instantly, price data fills in ~1 second later
    
    Returns:
        JsonResponse with structure:
        {
            'alerts': [...],      # Minimal alert objects (no price data)
            'triggered': [...],   # Triggered alert IDs and basic info
            'groups': [...]       # Unique group names
        }
    """
    # =============================================================================
    # GET CURRENT USER
    # =============================================================================
    user = request.user if request.user.is_authenticated else None
    
    # =============================================================================
    # LOAD ITEM MAPPING (LOCAL FILE - INSTANT)
    # =============================================================================
    # mapping: Dict mapping item_name_lower -> item data including 'icon' field
    # Loaded from local JSON file - no external API call
    mapping = get_item_mapping()
    
    # =============================================================================
    # QUERY ALERTS WITH PREFETCH
    # =============================================================================
    # alerts_qs: QuerySet with prefetch_related to avoid N+1 on groups
    alerts_qs = Alert.objects.filter(user=user).prefetch_related('groups') if user else Alert.objects.none()
    
    # all_alerts: List of alert objects ordered alphabetically
    all_alerts = list(alerts_qs.order_by(Coalesce('item_name', Value('All items')).asc()))
    
    # =============================================================================
    # BUILD MINIMAL RESPONSE (NO PRICE DATA)
    # =============================================================================
    # alerts_data: List of minimal alert dictionaries
    alerts_data = []
    
    # all_groups_set: Set of unique group names for filter dropdown
    all_groups_set = set()
    
    # triggered_alerts_list: Collect triggered alerts during iteration
    triggered_alerts_list = []
    
    for alert in all_alerts:
        # ---------------------------------------------------------------------
        # ICON LOOKUP
        # ---------------------------------------------------------------------
        # icon: Filename of item icon from mapping (e.g., "Abyssal_whip.png")
        icon = None
        if alert.item_name and mapping:
            item_data = mapping.get(alert.item_name.lower())
            if item_data:
                icon = item_data.get('icon')
        
        # ---------------------------------------------------------------------
        # BUILD MINIMAL ALERT DICT (NO PRICE DATA)
        # ---------------------------------------------------------------------
        alert_dict = {
            # Core identity fields
            'id': alert.id,
            'text': str(alert),
            'alert_name': alert.alert_name,
            'type': alert.type,
            
            # Status fields for badges/display
            'is_triggered': alert.is_triggered,
            'is_active': alert.is_active,
            'is_all_items': alert.is_all_items,
            
            # Item identification for icon display
            'item_id': alert.item_id,
            'item_name': alert.item_name,
            'icon': icon,
            
            # Groups for filtering/grouping
            'groups': list(alert.groups.values_list('name', flat=True)),
            
            # Timestamps for sorting
            'created_at': alert.created_at.isoformat(),
            'last_triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
            
            # Fields needed for threshold distance sorting (price data added later)
            'price': alert.price,
            'percentage': alert.percentage,
            'threshold_type': alert.threshold_type if alert.type == 'threshold' else None,
            'target_price': alert.target_price if alert.type == 'threshold' else None,
            'item_ids': alert.item_ids,  # For multi-item detection
            'reference': alert.reference,  # Needed to know which price to fetch later
        }
        
        # Collect group names
        for g in alert_dict['groups']:
            all_groups_set.add(g)
        
        alerts_data.append(alert_dict)
        
        # Collect triggered alerts for the triggered section
        if alert.is_triggered and not alert.is_dismissed:
            triggered_alerts_list.append(alert)
    
    # =============================================================================
    # BUILD MINIMAL TRIGGERED DATA
    # =============================================================================
    triggered_data = []
    for alert in triggered_alerts_list:
        triggered_dict = {
            'id': alert.id,
            'triggered_text': alert.triggered_text(),
            'type': alert.type,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data if alert.is_all_items else None,
        }
        triggered_data.append(triggered_dict)
    
    # =============================================================================
    # INCLUDE ALL USER GROUPS (EVEN EMPTY ONES)
    # =============================================================================
    # What: Fetch all AlertGroup records for this user, not just those with alerts
    # Why: Users may have created groups that don't have any alerts yet
    #      The dropdown should show ALL available groups for assignment
    # How: Query AlertGroup directly and merge with groups found from alerts
    if user:
        from Website.models import AlertGroup
        all_user_groups = AlertGroup.objects.filter(user=user).values_list('name', flat=True)
        for group_name in all_user_groups:
            all_groups_set.add(group_name)
    
    all_groups = sorted(all_groups_set)
    return JsonResponse({'alerts': alerts_data, 'triggered': triggered_data, 'groups': all_groups})


def alerts_api_prices(request):
    """
    Fetch current prices for alerts - called AFTER initial render.
    
    What: Returns price data for all user's alert items.
    
    Why: Separating price fetching from alert list allows instant initial render.
         This endpoint is called in the background after the list is displayed.
    
    How: Fetches prices from external API, returns dict of item_id -> price data
    
    Returns:
        JsonResponse with structure:
        {
            'prices': {
                'item_id': {'high': int, 'low': int},
                ...
            }
        }
    """
    # Fetch all current prices from external API
    all_prices = get_all_current_prices()
    
    # Return the prices dict - frontend will match to alerts by item_id
    return JsonResponse({'prices': all_prices})


@csrf_exempt
def dismiss_triggered_alert(request):
    """
    Dismiss a triggered alert notification.
    
    What: Sets is_dismissed=True AND show_notification=False for a specific alert 
          when the user clicks the X button on a notification.
    Why: Users need to permanently dismiss notifications. Setting show_notification=False
         ensures the notification won't reappear even if the alert re-triggers.
         The is_dismissed flag handles the current notification state, while 
         show_notification controls whether future notifications should appear.
    How: Receives alert_id via POST, updates both fields in the Alert record.
    """
    if request.method == 'POST':
        import json
        
        # Get the authenticated user, or None if not logged in
        user = request.user if request.user.is_authenticated else None
        
        # Parse the JSON body to get the alert_id
        data = json.loads(request.body)
        alert_id = data.get('alert_id')
        
        # DEBUG: Log the dismiss request details
        print(f"[DISMISS DEBUG] dismiss_notification called with alert_id={alert_id}, user={user}")
        
        if alert_id:
            # Perform the update - filter by both alert_id AND user for security
            # What: Update both is_dismissed and show_notification flags
            # Why: is_dismissed=True hides the current notification
            #      show_notification=False prevents future notifications from appearing
            # How: Single update query sets both fields atomically
            rows_updated = Alert.objects.filter(id=alert_id, user=user).update(
                is_dismissed=True,
                show_notification=False
            )
            
            # DEBUG: Log how many rows were updated
            print(f"[DISMISS DEBUG] Rows updated: {rows_updated}")
            
            # DEBUG: Verify the alert state after update
            try:
                alert = Alert.objects.get(id=alert_id)
                print(f"[DISMISS DEBUG] After update: is_dismissed={alert.is_dismissed}, show_notification={alert.show_notification}, is_triggered={alert.is_triggered}")
            except Alert.DoesNotExist:
                print(f"[DISMISS DEBUG] Alert {alert_id} not found after update")
            
            return JsonResponse({'success': True, 'rows_updated': rows_updated})
    
    return JsonResponse({'success': True})


@csrf_exempt
def delete_alerts(request):
    print("Delete alerts called")
    """Delete multiple alerts"""
    if request.method == 'POST':
        import json
        user = request.user if request.user.is_authenticated else None
        data = json.loads(request.body)
        alert_ids = data.get('alert_ids', [])
        if alert_ids:
            print(alert_ids)
            Alert.objects.filter(id__in=alert_ids, user=user).delete()
    return JsonResponse({'success': True})


@csrf_exempt
def group_alerts(request):
    """Assign alerts to one or more groups (creates groups as needed)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    import json
    user = request.user if request.user.is_authenticated else None
    data = json.loads(request.body)
    alert_ids = data.get('alert_ids', [])
    existing_groups = data.get('groups', [])
    new_groups = data.get('new_groups', [])

    if not alert_ids:
        return JsonResponse({'success': False, 'error': 'No alerts selected'}, status=400)

    # Normalize and dedupe group names
    group_names = []
    for name in (existing_groups or []) + (new_groups or []):
        if name and isinstance(name, str):
            cleaned = name.strip()
            if cleaned and cleaned not in group_names:
                group_names.append(cleaned)

    if not group_names:
        return JsonResponse({'success': False, 'error': 'No groups provided'}, status=400)

    # Ensure groups exist for this user
    group_objs = []
    for name in group_names:
        group_obj, _ = AlertGroup.objects.get_or_create(user=user, name=name)
        group_objs.append(group_obj)

    alerts = Alert.objects.filter(id__in=alert_ids, user=user)
    for alert in alerts:
        alert.groups.add(*group_objs)

    return JsonResponse({
        'success': True,
        'groups': group_names
    })


@csrf_exempt
def delete_groups(request):
    """Delete alert groups by name."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    import json
    user = request.user if request.user.is_authenticated else None
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    groups = data.get('groups', [])
    if not groups:
        return JsonResponse({'success': False, 'error': 'No groups provided'}, status=400)

    cleaned = [g.strip() for g in groups if isinstance(g, str) and g.strip()]
    if not cleaned:
        return JsonResponse({'success': False, 'error': 'No groups provided'}, status=400)

    deleted_count = 0
    for name in cleaned:
        count, _ = AlertGroup.objects.filter(user=user, name__iexact=name).delete()
        deleted_count += count

    if deleted_count == 0:
        return JsonResponse({'success': False, 'error': 'No groups deleted'}, status=404)

    return JsonResponse({'success': True, 'groups': cleaned})


@csrf_exempt
def unlink_groups(request):
    """Unlink an alert from specified groups (remove alert from groups without deleting groups)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    import json
    user = request.user if request.user.is_authenticated else None
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    
    alert_id = data.get('alert_id')
    groups = data.get('groups', [])
    
    if not alert_id:
        return JsonResponse({'success': False, 'error': 'No alert_id provided'}, status=400)
    
    if not groups:
        return JsonResponse({'success': False, 'error': 'No groups provided'}, status=400)

    try:
        alert = Alert.objects.get(id=alert_id, user=user)
    except Alert.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Alert not found'}, status=404)

    # Find the group objects and remove them from the alert
    cleaned = [g.strip() for g in groups if isinstance(g, str) and g.strip()]
    group_objs = AlertGroup.objects.filter(user=user, name__in=cleaned)
    
    for group in group_objs:
        alert.groups.remove(group)

    return JsonResponse({'success': True, 'unlinked_groups': cleaned})


@csrf_exempt
def update_alert(request):
    """Update an existing alert"""
    if request.method == 'POST':
        import json
        user = request.user if request.user.is_authenticated else None
        data = json.loads(request.body)
        alert_id = data.get('alert_id')
        if alert_id:
            alert = Alert.objects.filter(id=alert_id, user=user).first()
            if alert:
                alert.type = data.get('type', alert.type)
                
                # Handle alert name (user-editable)
                # name: User-defined name for the alert, allows customization for identification
                name = data.get('name')
                if name is not None:
                    alert.name = name if name else None
                
                # Handle is_all_items
                is_all_items = data.get('is_all_items', False)
                
                # =============================================================================
                # SERVER-SIDE VALIDATION: ALL ITEMS REQUIRES MIN/MAX PRICE
                # =============================================================================
                # What: Validates that both minimum and maximum price fields have values when
                #       "All Items" is selected for any alert type during an UPDATE operation
                # Why: This is a critical server-side backup validation in case client-side
                #       validation is bypassed (e.g., disabled JavaScript, direct API calls)
                #       When monitoring all items, price range filters are REQUIRED to narrow
                #       down the items being tracked and prevent noisy alerts
                # How: Check if is_all_items is True, and if so, verify both minimum_price
                #       and maximum_price have non-empty values in the request data.
                #       If validation fails, return a JSON error response with redirect URL
                # Note: This validation applies to ALL alert types (spread, spike, sustained, threshold)
                if is_all_items:
                    # minimum_price and maximum_price: Extract from request data
                    # These values may be None (not provided), empty string (cleared), or a valid number
                    minimum_price_val = data.get('minimum_price')
                    maximum_price_val = data.get('maximum_price')
                    
                    # Check if either value is missing, None, or empty string
                    # We need to handle both None and empty string cases
                    min_missing = minimum_price_val is None or (isinstance(minimum_price_val, str) and not minimum_price_val.strip())
                    max_missing = maximum_price_val is None or (isinstance(maximum_price_val, str) and not maximum_price_val.strip())
                    
                    if min_missing or max_missing:
                        return JsonResponse({
                            'status': 'error',
                            'error': 'Minimum Price and Maximum Price are required when tracking All Items',
                            'redirect': '/alerts/'
                        }, status=400)
                
                # =============================================================================
                # SERVER-SIDE VALIDATION: SPIKE ALERTS REQUIRE MIN HOURLY VOLUME
                # =============================================================================
                # What: Ensures spike alerts always provide a minimum hourly volume (GP) value
                # Why: Spike alerts must filter out low-activity items; missing volume would make
                #      the alert configuration invalid and inconsistent with the required UI field
                # How: If alert.type is 'spike', verify min_volume is non-empty; otherwise return
                #      a JSON error response so the UI can show validation feedback
                # min_volume_int: Parsed integer value for spike min_volume validation
                # What: Stores the numeric minimum hourly volume for spike alerts after validation
                # Why: Allows reuse later when saving the alert without re-parsing the value
                # How: Set during the spike validation block below
                min_volume_int = None
                
                if alert.type == 'spike':
                    # min_volume_val: Raw string value submitted for minimum hourly volume
                    # What: Holds the user-entered minimum hourly volume in GP
                    # Why: We need to confirm it exists before converting to an integer later
                    # How: Check for None, empty string, or whitespace-only values
                    min_volume_val = data.get('min_volume')
                    min_volume_missing = (
                        min_volume_val is None
                        or (isinstance(min_volume_val, str) and not min_volume_val.strip())
                    )
                    if min_volume_missing:
                        return JsonResponse({
                            'status': 'error',
                            'error': 'Min Hourly Volume (GP) is required for spike alerts',
                            'redirect': '/alerts/'
                        }, status=400)
                    
                    # What: Validate that the min_volume value is numeric
                    # Why: Non-numeric values would raise a ValueError when we cast to int for storage
                    # How: Attempt int conversion and handle failures with a JSON error response
                    try:
                        min_volume_int = int(min_volume_val)
                    except (TypeError, ValueError):
                        return JsonResponse({
                            'status': 'error',
                            'error': 'Min Hourly Volume (GP) must be a whole number',
                            'redirect': '/alerts/'
                        }, status=400)
                
                alert.is_all_items = is_all_items
                
                # Handle item_ids for multi-item alerts
                # item_ids: Comma-separated string of item IDs from the frontend multi-item selector
                # What: Stores multiple item IDs as JSON array for multi-item alerts
                # Why: Allows alerts to monitor multiple specific items instead of all or one
                # How: Parse comma-separated string, convert to JSON array, store in item_ids field
                item_ids_str = data.get('item_ids')
                
                # item_ids_str can be:
                # - None: field not provided (single item mode or unchanged)
                # - '': empty string (all items removed, switch to single item mode)
                # - '123,456': comma-separated IDs (multi-item mode)
                if item_ids_str is not None:
                    if item_ids_str == '':
                        # All items were removed - clear item_ids field
                        alert.item_ids = None
                    else:
                        # Parse comma-separated item IDs and store as JSON array
                        item_ids_list = [int(x.strip()) for x in item_ids_str.split(',') if x.strip()]
                        if item_ids_list:
                            import json as json_module
                            
                            alert.item_ids = json_module.dumps(item_ids_list)
                            # Set first item as item_id for display/fallback purposes
                            # Get item name for the first item using ID-to-name mapping
                            id_to_name_mapping = get_item_id_to_name_mapping()
                            try:
                                item_name = id_to_name_mapping.get(str(item_ids_list[0]), f'Item {item_ids_list[0]}')
                                alert.item_id = item_ids_list[0]
                            except:
                                item_name = None
                                alert.item_id = None
                            alert.item_name = item_name
                        else:
                            alert.item_ids = None
                
                if is_all_items:
                    alert.item_name = None
                    alert.item_id = None
                    alert.item_ids = None  # Clear multi-item selection when switching to all items
                elif item_ids_str is None or item_ids_str == '':
                    # Single item mode (no item_ids provided or all were removed)
                    # Only update item_name/item_id if explicitly provided
                    if data.get('item_name') is not None:
                        alert.item_name = data.get('item_name') or alert.item_name
                    if data.get('item_id'):
                        item_id = data.get('item_id')
                        alert.item_id = int(item_id)
                    elif data.get('item_name'):
                        # Look up item ID if name changed but ID not provided
                        mapping = get_item_mapping()
                        item_data = mapping.get(data.get('item_name').lower())
                        if item_data:
                            alert.item_id = item_data['id']
                            alert.item_name = item_data['name']
                
                # Handle price/reference for alerts
                if alert.type == 'spike':
                    time_frame = data.get('time_frame') or data.get('price')
                    alert.price = int(time_frame) if time_frame else None
                    alert.time_frame = None  # Spike uses price field for time_frame
                elif alert.type == 'sustained':
                    alert.price = None  # Sustained doesn't use price
                    time_frame = data.get('time_frame')
                    alert.time_frame = int(time_frame) if time_frame else None
                elif alert.type == 'collective_move':
                    # collective_time_frame: Time window for collective move comparisons
                    # What: Store time_frame in dedicated field for collective move alerts
                    # Why: Collective move comparisons require a rolling baseline window
                    # How: Parse time_frame from request data and store in alert.time_frame
                    alert.price = None
                    time_frame = data.get('time_frame')
                    alert.time_frame = int(time_frame) if time_frame else None
                else:
                    price = data.get('price')
                    alert.price = int(price) if price else None
                    alert.time_frame = None
                
                # =============================================================================
                # HANDLE REFERENCE FOR ALL ALERT TYPES
                # =============================================================================
                # What: Update the reference price type (high/low/average) for the alert
                # Why: All alert types (spike, sustained, threshold) now support reference selection
                # How: Get reference from request data, default to 'average' if not specified
                # Note: Previously sustained alerts were excluded - now they support reference too
                # =============================================================================
                reference = data.get('reference')
                alert.reference = reference if reference else 'average'

                # Handle direction for spike, sustained, and collective_move
                direction = data.get('direction')
                if alert.type in ['spike', 'sustained', 'collective_move']:
                    direction_value = (direction or '').lower() if isinstance(direction, str) else ''
                    if direction_value not in ['up', 'down', 'both']:
                        direction_value = 'both'
                    alert.direction = direction_value
                else:
                    alert.direction = None
                
                # Handle percentage for spread, spike, or collective_move alerts (not sustained)
                if alert.type in ['spread', 'spike', 'collective_move']:
                    percentage = data.get('percentage')
                    alert.percentage = float(percentage) if percentage else None
                else:
                    alert.percentage = None
                
                # =============================================================================
                # HANDLE CALCULATION_METHOD FOR COLLECTIVE_MOVE ALERTS
                # =============================================================================
                # What: Update the calculation method (simple vs weighted) for collective_move alerts
                # Why: Users can change how the average is computed between simple arithmetic mean
                #      and value-weighted mean (where expensive items count more)
                # How: Get calculation_method from request data, default to 'simple' if not specified
                if alert.type == 'collective_move':
                    calculation_method = data.get('calculation_method')
                    if calculation_method in ['simple', 'weighted']:
                        alert.calculation_method = calculation_method
                    else:
                        alert.calculation_method = 'simple'
                else:
                    alert.calculation_method = None
                
                # Handle min/max price for all items alerts
                minimum_price = data.get('minimum_price')
                if minimum_price:
                    alert.minimum_price = int(minimum_price)
                else:
                    alert.minimum_price = None
                    
                maximum_price = data.get('maximum_price')
                if maximum_price:
                    alert.maximum_price = int(maximum_price)
                else:
                    alert.maximum_price = None
                
                # Handle sustained-specific fields
                if alert.type == 'sustained':
                    min_consecutive_moves = data.get('min_consecutive_moves')
                    alert.min_consecutive_moves = int(min_consecutive_moves) if min_consecutive_moves else None
                    
                    min_move_percentage = data.get('min_move_percentage')
                    alert.min_move_percentage = float(min_move_percentage) if min_move_percentage else None
                    
                    # min_volume is handled below for both sustained and spread alerts
                    min_volume = data.get('min_volume')
                    alert.min_volume = int(min_volume) if min_volume else None
                    
                    volatility_buffer_size = data.get('volatility_buffer_size')
                    alert.volatility_buffer_size = int(volatility_buffer_size) if volatility_buffer_size else None
                    
                    volatility_multiplier = data.get('volatility_multiplier')
                    alert.volatility_multiplier = float(volatility_multiplier) if volatility_multiplier else None
                    
                    min_pressure_strength = data.get('min_pressure_strength')
                    alert.min_pressure_strength = min_pressure_strength if min_pressure_strength else None
                    
                    min_pressure_spread_pct = data.get('min_pressure_spread_pct')
                    alert.min_pressure_spread_pct = float(min_pressure_spread_pct) if min_pressure_spread_pct else None
                elif alert.type == 'spread':
                    # =============================================================================
                    # SPREAD ALERT MIN VOLUME HANDLING
                    # What: Save the min_volume field when editing a spread alert
                    # Why: Spread alerts now support optional minimum hourly volume (GP) filtering
                    #      to ensure only actively-traded items trigger spread alerts. The min_volume
                    #      field is shared with sustained alerts on the Alert model.
                    # How: Read min_volume from the request data and save it. Clear sustained-only
                    #      fields that don't apply to spread alerts.
                    # =============================================================================
                    min_volume = data.get('min_volume')
                    alert.min_volume = int(min_volume) if min_volume else None
                    # Clear sustained-only fields that don't apply to spread alerts
                    alert.min_consecutive_moves = None
                    alert.min_move_percentage = None
                    alert.volatility_buffer_size = None
                    alert.volatility_multiplier = None
                    alert.sustained_item_ids = None
                    alert.min_pressure_strength = None
                    alert.min_pressure_spread_pct = None
                elif alert.type == 'spike':
                    # =============================================================================
                    # SPIKE ALERT MIN VOLUME HANDLING
                    # What: Save the required min_volume field when editing a spike alert
                    # Why: Spike alerts now enforce a minimum hourly volume (GP) threshold
                    # How: Reuse the validated min_volume_int from the earlier validation block
                    #      and clear sustained-only fields that don't apply to spike alerts.
                    # =============================================================================
                    # min_volume_int: Parsed integer value from earlier validation
                    # What: Reuse the validated integer instead of re-parsing the string
                    # Why: Keeps validation and persistence consistent for spike alerts
                    # How: Assign the cached integer value from the spike validation block
                    alert.min_volume = min_volume_int
                    # Clear sustained-only fields that don't apply to spike alerts
                    alert.min_consecutive_moves = None
                    alert.min_move_percentage = None
                    alert.volatility_buffer_size = None
                    alert.volatility_multiplier = None
                    alert.sustained_item_ids = None
                    alert.min_pressure_strength = None
                    alert.min_pressure_spread_pct = None
                else:
                    # Clear sustained/spread fields for other alert types (threshold, collective_move)
                    # What: Reset all sustained-specific and min_volume fields when the alert
                    #       type is not sustained or spread
                    # Why: Prevents stale data from a previous type from affecting the alert
                    # How: Set all sustained-specific fields and min_volume to None
                    alert.min_consecutive_moves = None
                    alert.min_move_percentage = None
                    alert.min_volume = None
                    alert.volatility_buffer_size = None
                    alert.volatility_multiplier = None
                    alert.sustained_item_ids = None
                    alert.min_pressure_strength = None
                    alert.min_pressure_spread_pct = None
                
                # Handle email notification preference
                alert.email_notification = data.get('email_notification', False)
                
                # Handle show_notification preference
                # What: Controls whether notification banner appears when alert triggers
                # Why: Users may want to track alerts without seeing notification banners
                # How: If False, is_dismissed is set to True so notification never displays
                show_notification = data.get('show_notification', True)
                alert.show_notification = show_notification
                
                # =============================================================================
                # RESET TRIGGERED STATE ON EVERY EDIT
                # =============================================================================
                # What: Clear all triggered state whenever an alert is edited
                # Why: Simpler and cleaner than trying to selectively clean triggered_data.
                #      The check_alerts script will correctly repopulate triggered_data on
                #      the very next cycle, so this ensures clean, fresh data after any edit.
                # How: Set is_triggered=False, is_dismissed=False, clear triggered_data and triggered_at
                # Note: is_dismissed=False ensures the notification CAN show when it re-triggers
                #       (unless show_notification is False, in which case it won't appear anyway)
                
                # DEBUG: Log the reset operation
                print(f"[UPDATE_ALERT DEBUG] Resetting triggered state for alert {alert.id}")
                print(f"[UPDATE_ALERT DEBUG] BEFORE: is_triggered={alert.is_triggered}, is_dismissed={alert.is_dismissed}, triggered_data={alert.triggered_data is not None}")
                
                alert.is_triggered = False
                alert.is_dismissed = False
                alert.triggered_data = None
                alert.triggered_at = None
                alert.is_active = True
                
                print(f"[UPDATE_ALERT DEBUG] AFTER: is_triggered={alert.is_triggered}, is_dismissed={alert.is_dismissed}, triggered_data={alert.triggered_data}")
                
                alert.save()
                
                # DEBUG: Verify the save worked by re-fetching
                saved_alert = Alert.objects.get(id=alert.id)
                print(f"[UPDATE_ALERT DEBUG] VERIFIED: is_triggered={saved_alert.is_triggered}, is_dismissed={saved_alert.is_dismissed}")
                
    return JsonResponse({'success': True})


def alert_detail(request, alert_id):

    """Display detailed view of a single alert"""
    from django.shortcuts import get_object_or_404
    import json
    
    # What: Helper function to sort triggered items from biggest increase to biggest decrease
    # Why: Users want to see the most significant changes first (biggest gains at top, biggest losses at bottom)
    # How: Sort by the appropriate field for each alert type in descending order (highest to lowest)
    #      - spread: sort by 'spread' (spread percentage)
    #      - spike: sort by 'percent_change' (percentage change from baseline)
    #      - sustained: sort by 'total_move_percent' (total percentage move)
    #      - threshold: sort by 'change_percent' (percentage change from reference)
    # Note: Uses negative values for 'down' movements, so higher values = bigger increase, lower values = bigger decrease
    def sort_triggered_items(items, alert_type):
        """Sort triggered items from biggest increase to biggest decrease based on alert type"""
        if not items or not isinstance(items, list):
            return items
        
        # Determine which field to sort by based on alert type
        if alert_type == 'spread':
            # For spread alerts, sort by spread percentage (descending)
            return sorted(items, key=lambda x: x.get('spread', 0), reverse=True)
        elif alert_type == 'spike':
            # For spike alerts, sort by percent_change (descending - positive changes first)
            return sorted(items, key=lambda x: x.get('percent_change', 0), reverse=True)
        elif alert_type == 'sustained':
            # For sustained alerts, sort by total_move_percent (descending - positive changes first)
            return sorted(items, key=lambda x: x.get('total_move_percent', 0), reverse=True)
        elif alert_type == 'threshold':
            # For threshold alerts, sort by change_percent (descending - positive changes first)
            return sorted(items, key=lambda x: x.get('change_percent', 0), reverse=True)
        else:
            # Unknown alert type - return unsorted
            return items
    
    user = request.user if request.user.is_authenticated else None
    alert = get_object_or_404(Alert, id=alert_id, user=user)
    
    # Get current price data if alert has an item
    current_price_data = {}
    all_prices = get_all_current_prices()
    
    if alert.item_id:
        price_data = all_prices.get(str(alert.item_id), {})
        current_price_data = {
            'high': price_data.get('high'),
            'low': price_data.get('low'),
            'highTime': price_data.get('highTime'),
            'lowTime': price_data.get('lowTime'),
        }
        if current_price_data['high'] and current_price_data['low'] and current_price_data['low'] > 0:
            current_price_data['spread'] = round(((current_price_data['high'] - current_price_data['low']) / current_price_data['low']) * 100, 2)
    
    # Get alert groups for this user
    groups = list(alert.groups.values_list('name', flat=True))
    all_groups = list(AlertGroup.objects.filter(user=user).values_list('name', flat=True))
    
    # Build triggered data for display
    triggered_info = None
    if alert.is_triggered:
        triggered_info = {
            'triggered_at': alert.triggered_at,
            'is_all_items': alert.is_all_items,
            'alert_type': alert.type,
        }

        if alert.type == 'sustained':
            # For sustained alerts, triggered_data contains the sustained move info
            # What: Parse the triggered_data JSON and extract individual fields for template display
            # Why: The template expects individual fields like sustained_item_name, sustained_direction, etc.
            #      to render the sustained alert triggered data section
            # How: Parse the JSON and map each field from the stored data to the triggered_info dict
            # Note: triggered_data can be either a single object (single item) or a list (multi-item/all-items)
            if alert.triggered_data:
                try:
                    sustained_data = json.loads(alert.triggered_data)
                    
                    # sustained_data can be either:
                    # - A single dict for single-item sustained alerts
                    # - A list of dicts for multi-item or all-items sustained alerts
                    if isinstance(sustained_data, list):
                        # Multi-item or all-items sustained alert - store items list for template
                        # triggered_info['items']: List of all sustained move triggers for multi-item display
                        # Sort items from biggest increase to biggest decrease
                        triggered_info['items'] = sort_triggered_items(sustained_data, 'sustained')
                        triggered_info['sustained_data'] = sustained_data
                        
                        # For backwards compatibility, also populate individual fields from first item
                        # This allows templates that expect single-item fields to still work
                        if sustained_data:
                            first_item = sustained_data[0]
                            triggered_info['sustained_item_name'] = first_item.get('item_name')
                            triggered_info['sustained_direction'] = first_item.get('streak_direction')
                            triggered_info['sustained_streak_count'] = first_item.get('streak_count')
                            triggered_info['sustained_total_move'] = first_item.get('total_move_percent')
                            triggered_info['sustained_start_price'] = first_item.get('start_price')
                            triggered_info['sustained_current_price'] = first_item.get('current_price')
                            triggered_info['sustained_volume'] = first_item.get('volume')
                    else:
                        # Single item sustained alert - sustained_data is a dict
                        # sustained_data: The parsed JSON object containing all sustained alert trigger info
                        triggered_info['sustained_data'] = sustained_data
                        # sustained_item_name: Name of the item that triggered the sustained move alert
                        triggered_info['sustained_item_name'] = sustained_data.get('item_name')
                        # sustained_direction: Direction of the streak ('up' or 'down')
                        triggered_info['sustained_direction'] = sustained_data.get('streak_direction')
                        # sustained_streak_count: Number of consecutive time periods the price moved in this direction
                        triggered_info['sustained_streak_count'] = sustained_data.get('streak_count')
                        # sustained_total_move: Total percentage change from start to current price
                        triggered_info['sustained_total_move'] = sustained_data.get('total_move_percent')
                        # sustained_start_price: Price at the start of the sustained move
                        triggered_info['sustained_start_price'] = sustained_data.get('start_price')
                        # sustained_current_price: Current price at time of trigger
                        triggered_info['sustained_current_price'] = sustained_data.get('current_price')
                        # sustained_volume: Trading volume during the sustained move period (optional)
                        triggered_info['sustained_volume'] = sustained_data.get('volume')
                except json.JSONDecodeError:
                    pass

        # =============================================================================
        # COLLECTIVE MOVE ALERT TRIGGERED INFO
        # What: Populate triggered_info with collective_move data for template display
        # Why: Template needs average change, threshold, items list, and calculation details
        # How: Parse triggered_data JSON which contains the collective average and items
        # Note: This is handled separately because collective_move alerts have a unique
        #       triggered_data structure with average_change, items array, etc.
        # =============================================================================
        if alert.type == 'collective_move':
            if alert.triggered_data:
                try:
                    collective_data = json.loads(alert.triggered_data)
                    if isinstance(collective_data, dict):
                        triggered_info['collective_data'] = collective_data
                except json.JSONDecodeError:
                    triggered_info['collective_data'] = None
            else:
                triggered_info['collective_data'] = None

        
        # has_multiple_items: Boolean indicating if this alert monitors multiple specific items
        # This is True when item_ids contains a JSON array of item IDs (Specific Item(s) mode)
        # For sustained alerts, we also check sustained_item_ids field
        # Used to determine if we should show the multi-item list view in the template
        has_multiple_items = False
        if alert.item_ids:
            try:
                item_ids_list = json.loads(alert.item_ids)
                has_multiple_items = isinstance(item_ids_list, list) and len(item_ids_list) > 0
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Also check sustained_item_ids for sustained alerts
        # sustained_item_ids: JSON array of item IDs for sustained alerts monitoring multiple specific items
        if not has_multiple_items and hasattr(alert, 'sustained_item_ids') and alert.sustained_item_ids:
            try:
                sustained_ids_list = json.loads(alert.sustained_item_ids)
                has_multiple_items = isinstance(sustained_ids_list, list) and len(sustained_ids_list) > 0
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Add has_multiple_items to triggered_info for template rendering
        # This allows the template to show the multi-item list even when is_all_items is False
        triggered_info['has_multiple_items'] = has_multiple_items
        
        if alert.is_all_items and alert.triggered_data and alert.type != 'sustained':
            # Parse the JSON triggered data for all-items alerts (non-sustained)
            # What: Parse triggered_data JSON into items list for template display
            # Why: All-items alerts store triggered items as JSON array in triggered_data
            # Note: Sustained alerts are handled separately above because they need special field extraction
            try:
                items = json.loads(alert.triggered_data)
                # Sort items from biggest increase to biggest decrease
                triggered_info['items'] = sort_triggered_items(items, alert.type)
            except json.JSONDecodeError:
                triggered_info['items'] = []
        elif has_multiple_items and alert.triggered_data and alert.type != 'sustained':
            # Multi-item specific alert (Specific Item(s) mode with item_ids set)
            # What: Parse triggered_data JSON for multi-item spread/threshold/spike alerts
            # Why: When user selects "Specific Item(s)", the triggered_data contains
            #      a JSON array of items that met the threshold
            # How: Same format as all-items alerts - array of item objects with
            #      item_id, item_name, and type-specific fields
            # Note: Sustained alerts are handled separately above
            # =============================================================================
            # IMPORTANT: Only set items if triggered_data is actually a list
            # Why: Single-item alerts now store triggered_data as a dict (not a list)
            #      If we set triggered_info['items'] = dict, Django template will iterate
            #      over the dict keys (e.g., 'item_id', 'item_name') showing 7-8 "items"
            # How: Check isinstance before assigning to items
            # =============================================================================
            try:
                parsed_data = json.loads(alert.triggered_data)
                if isinstance(parsed_data, list):
                    # Multi-item: triggered_data is a list of item dicts
                    # Sort items from biggest increase to biggest decrease
                    triggered_info['items'] = sort_triggered_items(parsed_data, alert.type)
                else:
                    # =============================================================================
                    # SINGLE-ITEM THRESHOLD WITH ITEM_IDS SET
                    # =============================================================================
                    # What: Handle case where item_ids has 1 item but triggered_data is a dict
                    # Why: When user selects "Specific Items" with only 1 item, item_ids is still
                    #      a JSON array like [123], making has_multiple_items=True, but triggered_data
                    #      is stored as a dict (single item format)
                    # How: Reset has_multiple_items flag and process as single-item threshold alert
                    # =============================================================================
                    triggered_info['has_multiple_items'] = False
                    
                    # Process single-item threshold data if this is a threshold alert
                    if alert.type == 'threshold':
                        triggered_info['reference'] = alert.reference
                        triggered_info['threshold_value'] = alert.percentage
                        triggered_info['threshold_type'] = alert.threshold_type
                        
                        # parsed_data is the single-item triggered_data dict
                        if parsed_data.get('threshold_type') == 'value':
                            # Value-based threshold: use target_price instead of reference_price
                            triggered_info['threshold_target_price'] = parsed_data.get('target_price')
                            triggered_info['threshold_current_price'] = parsed_data.get('current_price')
                            triggered_info['threshold_direction'] = parsed_data.get('direction')
                            # threshold_baseline_price: The item's price at alert creation time
                            # Why: Provides context for value-based alerts (may be None for older alerts)
                            triggered_info['threshold_baseline_price'] = parsed_data.get('reference_price')
                            # Secondary fallback: If triggered_data didn't have reference_price,
                            # try getting it from alert.reference_prices (same pattern as single-item path)
                            if not triggered_info.get('threshold_baseline_price') and alert.reference_prices and alert.item_id:
                                try:
                                    ref_prices = json.loads(alert.reference_prices)
                                    triggered_info['threshold_baseline_price'] = ref_prices.get(str(alert.item_id))
                                except json.JSONDecodeError:
                                    pass
                        else:
                            # Percentage-based threshold
                            triggered_info['threshold_reference_price'] = parsed_data.get('reference_price')
                            triggered_info['threshold_current_price'] = parsed_data.get('current_price')
                            triggered_info['threshold_change_percent'] = parsed_data.get('change_percent')
                            triggered_info['threshold_direction'] = parsed_data.get('direction')
            except json.JSONDecodeError:
                triggered_info['items'] = []
        elif not alert.is_all_items and alert.item_id:
            # Single item alert - get current price info
            price_data = all_prices.get(str(alert.item_id), {})
            
            if alert.type == 'spread':
                high = price_data.get('high')
                low = price_data.get('low')
                if high and low and low > 0:
                    triggered_info['spread_high'] = high
                    triggered_info['spread_low'] = low
                    triggered_info['spread_percentage'] = round(((high - low) / low) * 100, 2)
            elif alert.type == 'spike':
                # For spike alerts, triggered_data contains the spike info
                if alert.triggered_data:
                    try:
                        spike_data = json.loads(alert.triggered_data)
                        if spike_data and len(spike_data) > 0:
                            triggered_info['spike_data'] = spike_data[0] if isinstance(spike_data, list) else spike_data
                    except json.JSONDecodeError:
                        pass
            elif alert.type == 'threshold':
                # =============================================================================
                # THRESHOLD ALERT TRIGGERED INFO
                # What: Populate triggered_info with threshold-specific data for template display
                # Why: Template needs reference price, current price, threshold value, and change %
                # How: Parse triggered_data if available, or fall back to calculating from alert fields
                # =============================================================================
                triggered_info['reference'] = alert.reference
                triggered_info['threshold_value'] = alert.percentage
                triggered_info['threshold_type'] = alert.threshold_type
                
                # Check if multi-item or all-items threshold
                if (alert.is_all_items or alert.item_ids) and alert.triggered_data:
                    try:
                        threshold_data = json.loads(alert.triggered_data)
                        if isinstance(threshold_data, list):
                            # Sort items from biggest increase to biggest decrease
                            triggered_info['items'] = sort_triggered_items(threshold_data, 'threshold')
                            # For backwards compatibility, populate single item fields from first item
                            if threshold_data:
                                first_item = threshold_data[0]
                                triggered_info['threshold_reference_price'] = first_item.get('reference_price')
                                triggered_info['threshold_current_price'] = first_item.get('current_price')
                                triggered_info['threshold_change_percent'] = first_item.get('change_percent')
                    except json.JSONDecodeError:
                        pass
                else:
                    # Single item threshold alert
                    # =============================================================================
                    # SINGLE-ITEM THRESHOLD TRIGGERED DATA HANDLING
                    # What: Extract triggered data from stored triggered_data JSON if available
                    # Why: triggered_data now stores the exact values at trigger time, which is
                    #      more accurate than recalculating from current prices
                    # How: Try to parse triggered_data first; if not available or invalid,
                    #      fall back to the old method of calculating from reference_prices and
                    #      current API prices
                    # Note: triggered_data can be a dict (single item) with fields:
                    #       - For percentage-based: item_id, item_name, reference_price, current_price, 
                    #         change_percent, threshold, direction
                    #       - For value-based: item_id, item_name, target_price, current_price, 
                    #         reference_price (baseline at creation), direction, threshold_type
                    # =============================================================================
                    triggered_data_parsed = False
                    
                    if alert.triggered_data:
                        try:
                            # triggered_data_dict: The parsed JSON dict containing trigger details
                            triggered_data_dict = json.loads(alert.triggered_data)
                            
                            if isinstance(triggered_data_dict, dict):
                                # Successfully parsed single-item triggered_data
                                # Check if this is a value-based or percentage-based threshold
                                if triggered_data_dict.get('threshold_type') == 'value':
                                    # Value-based threshold: use target_price instead of reference_price
                                    triggered_info['threshold_target_price'] = triggered_data_dict.get('target_price')
                                    triggered_info['threshold_current_price'] = triggered_data_dict.get('current_price')
                                    triggered_info['threshold_direction'] = triggered_data_dict.get('direction')
                                    # threshold_baseline_price: The item's price at alert creation time.
                                    # Why: Provides context by showing where the price started relative
                                    #      to the target and current prices. May be None for alerts
                                    #      created before this feature was added (backwards compatibility).
                                    triggered_info['threshold_baseline_price'] = triggered_data_dict.get('reference_price')
                                else:
                                    # Percentage-based threshold
                                    triggered_info['threshold_reference_price'] = triggered_data_dict.get('reference_price')
                                    triggered_info['threshold_current_price'] = triggered_data_dict.get('current_price')
                                    triggered_info['threshold_change_percent'] = triggered_data_dict.get('change_percent')
                                    triggered_info['threshold_direction'] = triggered_data_dict.get('direction')
                                
                                triggered_data_parsed = True
                        except json.JSONDecodeError:
                            # triggered_data exists but couldn't be parsed - fall through to fallback
                            pass
                    
                    # =============================================================================
                    # SECONDARY FALLBACK FOR BASELINE PRICE (VALUE-BASED THRESHOLD ONLY)
                    # What: If triggered_data was successfully parsed but didn't contain
                    #       reference_price (e.g., alert was triggered before we started storing
                    #       baseline in triggered_data), try to get it from alert.reference_prices
                    # Why: The configuration card shows baseline from alert.reference_prices,
                    #      so the triggered data card should show it too for consistency.
                    #      This handles the gap between when reference_prices was stored at creation
                    #      vs when triggered_data started including reference_price.
                    # How: Only runs when triggered_data was parsed but baseline is still missing.
                    #      Reads directly from the alert model's reference_prices JSON field.
                    # =============================================================================
                    if (triggered_data_parsed 
                        and alert.threshold_type == 'value' 
                        and not triggered_info.get('threshold_baseline_price') 
                        and alert.reference_prices 
                        and alert.item_id):
                        try:
                            ref_prices = json.loads(alert.reference_prices)
                            triggered_info['threshold_baseline_price'] = ref_prices.get(str(alert.item_id))
                        except json.JSONDecodeError:
                            pass
                    
                    # Fallback: Calculate values from reference_prices and current API data
                    # Why: For backwards compatibility with alerts triggered before this fix,
                    #      or if triggered_data parsing fails for any reason
                    if not triggered_data_parsed:
                        # Get reference price from stored reference_prices
                        if alert.reference_prices and alert.item_id:
                            try:
                                ref_prices = json.loads(alert.reference_prices)
                                # baseline_ref: The baseline price at alert creation time
                                baseline_ref = ref_prices.get(str(alert.item_id))
                                triggered_info['threshold_reference_price'] = baseline_ref
                                # For value-based thresholds, also populate the baseline price field
                                # Why: Value-based thresholds now display baseline price in the template
                                # How: Use the same reference_prices data that percentage-based alerts use
                                if alert.threshold_type == 'value' and baseline_ref:
                                    triggered_info['threshold_baseline_price'] = baseline_ref
                            except json.JSONDecodeError:
                                pass
                        
                        # Get current price
                        if alert.reference == 'low':
                            triggered_info['threshold_current_price'] = price_data.get('low')
                        elif alert.reference == 'average':
                            high = price_data.get('high')
                            low = price_data.get('low')
                            if high and low:
                                triggered_info['threshold_current_price'] = (high + low) // 2
                        else:
                            triggered_info['threshold_current_price'] = price_data.get('high')
                        
                        # Calculate change percent
                        ref_price = triggered_info.get('threshold_reference_price')
                        curr_price = triggered_info.get('threshold_current_price')
                        if ref_price and curr_price and ref_price > 0:
                            change_pct = ((curr_price - ref_price) / ref_price) * 100
                            triggered_info['threshold_change_percent'] = round(change_pct, 2)

    # Check if redirected after save
    edit_saved = request.GET.get('edit_saved') == '1'
    
    # Build item_ids_data for the edit form multi-item selector
    # What: Creates a list of {id, name} objects for items in item_ids or sustained_item_ids field
    # Why: The edit form needs this data to pre-populate the multi-item selector chips
    # How: Parse item_ids JSON (or sustained_item_ids for sustained alerts), look up item names
    #      from ID-to-name mapping, return as JSON for JavaScript
    item_ids_data = []
    
    # Determine which field to use for multi-item data
    # What: Sustained alerts use sustained_item_ids, other alerts use item_ids
    # Why: Historical design decision - sustained alerts have their own item_ids field
    # How: Check alert type and use appropriate field
    item_ids_field = alert.sustained_item_ids if alert.type == 'sustained' else alert.item_ids
    
    if item_ids_field:
        try:
            item_ids_list = json.loads(item_ids_field)
            if isinstance(item_ids_list, list):
                # Get item ID-to-name mapping to convert IDs to names
                id_to_name_mapping = get_item_id_to_name_mapping()
                for item_id in item_ids_list:
                    item_name = id_to_name_mapping.get(str(item_id), f'Item {item_id}')
                    item_ids_data.append({'id': str(item_id), 'name': item_name})
        except (json.JSONDecodeError, TypeError):
            pass
    
    # =============================================================================
    # THRESHOLD ALERT CONTEXT DATA
    # What: Prepare threshold-specific data for the edit form JavaScript
    # Why: Threshold alerts need reference_prices displayed and item name mapping
    # How: Serialize reference_prices JSON and build item ID to name mapping
    # =============================================================================
    reference_prices_json = 'null'
    item_id_to_name_mapping_json = '{}'
    
    if alert.type == 'threshold':
        # Get reference_prices for display
        if alert.reference_prices:
            reference_prices_json = alert.reference_prices  # Already JSON string
        else:
            reference_prices_json = 'null'
        
        # Build item ID to name mapping for reference prices display
        # What: Maps item IDs to names so we can show names instead of IDs
        # Why: Users want to see "Berserker ring" not "6737"
        # How: Get IDs from reference_prices keys, look up names from mapping
        id_to_name_mapping = get_item_id_to_name_mapping()
        item_id_to_name_dict = {}
        
        if alert.reference_prices:
            try:
                ref_prices = json.loads(alert.reference_prices)
                for item_id in ref_prices.keys():
                    item_name = id_to_name_mapping.get(str(item_id), f'Item {item_id}')
                    item_id_to_name_dict[str(item_id)] = item_name
            except json.JSONDecodeError:
                pass
        
        item_id_to_name_mapping_json = json.dumps(item_id_to_name_dict)
    
    context = {
        'alert': alert,
        'current_price': current_price_data,
        'groups': groups,
        'all_groups': all_groups,
        'groups_json': json.dumps(groups),
        'all_groups_json': json.dumps(all_groups),
        'triggered_info': triggered_info,
        'edit_saved': edit_saved,
        # item_ids_data: List of {id, name} dicts for multi-item display (used in template)
        'item_ids_data': item_ids_data,
        # item_ids_data_json: JSON array of {id, name} objects for multi-item selector JavaScript
        'item_ids_data_json': json.dumps(item_ids_data),
        # Threshold-specific context data
        # reference_prices_json: JSON string of reference prices for display (or 'null')
        'reference_prices_json': reference_prices_json,
        # item_id_to_name_mapping_json: JSON object mapping item IDs to names for reference prices
        'item_id_to_name_mapping_json': item_id_to_name_mapping_json,
    }
    
    return render(request, 'alert_detail.html', context)


@csrf_exempt
def update_single_alert(request, alert_id):
    """API endpoint to update a single alert"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from django.shortcuts import get_object_or_404
    
    user = request.user if request.user.is_authenticated else None
    alert = get_object_or_404(Alert, id=alert_id, user=user)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    
    # Update alert fields
    alert.type = data.get('type', alert.type)
    
    # Handle alert name (user-editable)
    # alert_name: User-defined name for the alert (field is named alert_name in model)
    if 'name' in data:
        alert.alert_name = data.get('name') or 'Default'
    
    # Handle is_all_items
    is_all_items = data.get('is_all_items', False)
    alert.is_all_items = is_all_items
    
    # Handle item_ids for multi-item alerts (spread, spike, sustained, threshold)
    # What: Stores multiple item IDs as JSON array for multi-item alerts
    # Why: Allows alerts to monitor multiple specific items instead of all or one
    # How: Parse comma-separated string, convert to JSON array, store in appropriate field
    #      NOTE: Sustained alerts use sustained_item_ids field, all others use item_ids field
    item_ids_str = data.get('item_ids')
    
    # is_sustained: Flag to determine which field to use for storing item IDs
    # What: Sustained alerts historically use a different field (sustained_item_ids)
    # Why: Historical design decision - sustained alerts were created before unified item_ids
    # How: Check alert type and use appropriate field for reading/writing
    is_sustained = alert.type == 'sustained'
    
    if item_ids_str is not None:
        if item_ids_str == '' and not is_all_items:
            # All items were removed AND not in "all items" mode - delete the alert
            # What: Deletes the alert when all tracked items have been removed
            # Why: An alert with no items to track has no purpose and would cause errors
            # How: Delete the alert and return a JSON response with redirect info
            #      The JavaScript handler will see the 'deleted' flag and redirect the user
            # Note: We return JSON (not a Django redirect) because this is an AJAX endpoint
            # IMPORTANT: Only delete if NOT in "all items" mode - empty item_ids is valid for all-items alerts
            alert.delete()
            return JsonResponse({
                'success': True,
                'deleted': True,
                'redirect': '/alerts/',
                'message': 'Alert deleted'
            })
        else:
            # Parse comma-separated item IDs and store as JSON array
            item_ids_list = [int(x.strip()) for x in item_ids_str.split(',') if x.strip()]
            print("DEBUG 2")
            print(item_ids_list)
            if item_ids_list:
                # Get the old item_ids to compare what was removed
                # old_item_ids: Set of item IDs currently stored in the alert before this update
                # Why: We need to compare old vs new to determine which items were removed
                # How: Parse the existing item_ids JSON array and convert to a set of integers
                #      NOTE: Sustained alerts store IDs in sustained_item_ids, others in item_ids
                old_item_ids = set()
                # old_item_ids_field: The appropriate field to read old IDs from based on alert type
                old_item_ids_field = alert.sustained_item_ids if is_sustained else alert.item_ids
                if old_item_ids_field:
                    try:
                        # old_item_ids_list: The raw parsed list from JSON (may contain strings or ints)
                        old_item_ids_list = json.loads(old_item_ids_field)
                        # Convert each ID to int and add to the set for comparison
                        for i in old_item_ids_list:
                            old_item_ids.add(int(i))
                        
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                # new_item_ids: Set of item IDs that will be stored after this update
                new_item_ids = set(item_ids_list)
                # removed_item_ids: Items that were in the old set but not in the new set (user removed them)
                removed_item_ids = old_item_ids - new_item_ids
                
                # Clean up reference_prices for threshold alerts when items are removed
                # What: Remove baseline prices for items that were removed from the alert
                # Why: Reference prices should only exist for items currently being monitored
                # How: Use the Alert model's cleanup_reference_prices_for_removed_items method
                # Note: triggered_data cleanup is not needed here - we do a full reset at the end
                if removed_item_ids and alert.type == 'threshold':
                    alert.cleanup_reference_prices_for_removed_items(removed_item_ids)
                
                # For threshold alerts, capture reference prices for newly added items
                # What: When items are added to an existing threshold alert, capture their baseline prices
                # Why: New items need baseline prices for percentage calculations
                # How: Find items in new_item_ids that aren't in old_item_ids, fetch their prices
                if alert.type == 'threshold' and alert.threshold_type == 'percentage':
                    added_item_ids = new_item_ids - old_item_ids
                    if added_item_ids:
                        # Fetch current prices to get baselines for new items
                        all_prices = get_all_current_prices()
                        if all_prices:
                            # Load existing reference_prices or start fresh
                            existing_reference_prices = {}
                            if alert.reference_prices:
                                try:
                                    existing_reference_prices = json.loads(alert.reference_prices)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            
                            # Capture reference price for each newly added item
                            # What: Get baseline price using the alert's reference type (high/low/average)
                            # Why: New items need a baseline to calculate % change from
                            reference_type = alert.reference or 'high'
                            for item_id in added_item_ids:
                                item_id_str = str(item_id)
                                price_data = all_prices.get(item_id_str)
                                
                                if not price_data:
                                    # Skip items where price data is unavailable
                                    continue
                                
                                # Get the appropriate reference price
                                high = price_data.get('high')
                                low = price_data.get('low')
                                
                                if reference_type == 'high':
                                    reference_price = high
                                elif reference_type == 'low':
                                    reference_price = low
                                elif reference_type == 'average':
                                    if high is not None and low is not None:
                                        reference_price = (high + low) // 2
                                    else:
                                        reference_price = high or low
                                else:
                                    reference_price = high
                                
                                if reference_price is not None:
                                    existing_reference_prices[item_id_str] = reference_price
                            
                            # Save updated reference_prices
                            if existing_reference_prices:
                                alert.reference_prices = json.dumps(existing_reference_prices)
                
                # Store item IDs to the appropriate field based on alert type
                # What: Sustained alerts use sustained_item_ids, all other types use item_ids
                # Why: Historical design - sustained alerts have their own dedicated field
                # How: Check is_sustained flag and write to correct field
                if is_sustained:
                    alert.sustained_item_ids = json.dumps(item_ids_list)
                else:
                    alert.item_ids = json.dumps(item_ids_list)
                # Set first item as item_id for display/fallback purposes
                if len(item_ids_list) == 1:
                    alert.item_id = item_ids_list[0]
                else:
                    alert.item_id = None
                # Get item name for the first item using ID-to-name mapping
                id_to_name_mapping = get_item_id_to_name_mapping()
                item_name = id_to_name_mapping.get(str(item_ids_list[0]), f'Item {item_ids_list[0]}')
                alert.item_name = item_name
            else:
                # Clear the appropriate field when no items remain
                if is_sustained:
                    alert.sustained_item_ids = None
                else:
                    alert.item_ids = None
    
    if is_all_items:
        alert.item_name = None
        alert.item_id = None
        # Clear the appropriate multi-item field when switching to all items
        if is_sustained:
            alert.sustained_item_ids = None
        else:
            alert.item_ids = None
    elif item_ids_str is None or item_ids_str == '':
        # Single item mode (no item_ids provided or all were removed)
        if data.get('item_name') is not None:
            alert.item_name = data.get('item_name') or alert.item_name
        item_id = data.get('item_id')
        if item_id:
            alert.item_id = int(item_id)
        elif data.get('item_name'):
            mapping = get_item_mapping()
            item_data = mapping.get(data.get('item_name').lower())
            if item_data:
                alert.item_id = item_data['id']
                alert.item_name = item_data['name']
    
    # Handle price/reference for alerts
    if alert.type == 'spike':
        time_frame = data.get('time_frame') or data.get('price')
        alert.price = int(time_frame) if time_frame else None
        alert.time_frame = None
    elif alert.type == 'collective_move':
        # collective_time_frame: Time window for collective move comparisons
        # What: Store time_frame in dedicated field for collective move alerts
        # Why: Collective move comparisons require a rolling baseline window
        # How: Parse time_frame from request data and store in alert.time_frame
        time_frame = data.get('time_frame')
        alert.time_frame = int(time_frame) if time_frame else None
        alert.price = None
    else:
        price = data.get('price')
        alert.price = int(price) if price else None
        alert.time_frame = None
    
    reference = data.get('reference')
    alert.reference = reference if reference else None
    
    # =============================================================================
    # HANDLE DIRECTION FOR SPIKE, SUSTAINED, AND COLLECTIVE_MOVE ALERTS
    # =============================================================================
    # What: Set the direction field for alert types that support it
    # Why: Spike, sustained, and collective_move alerts can filter by price direction
    # How: Validate direction value and store it, default to 'both' if invalid
    direction = data.get('direction')
    if alert.type in ['spike', 'sustained', 'collective_move']:
        direction_value = (direction or '').lower() if isinstance(direction, str) else ''
        if direction_value not in ['up', 'down', 'both']:
            direction_value = 'both'
        alert.direction = direction_value
    else:
        alert.direction = None
    
    # =============================================================================
    # HANDLE CALCULATION_METHOD FOR COLLECTIVE_MOVE ALERTS
    # =============================================================================
    # What: Set the calculation method (simple vs weighted) for collective_move alerts
    # Why: Users can choose how the average is computed:
    #      - 'simple': Arithmetic mean - each item counts equally
    #      - 'weighted': Value-weighted mean - expensive items count more
    # How: Get calculation_method from request data, validate, default to 'simple'
    if alert.type == 'collective_move':
        calculation_method = data.get('calculation_method')
        if calculation_method in ['simple', 'weighted']:
            alert.calculation_method = calculation_method
        else:
            alert.calculation_method = 'simple'
    else:
        alert.calculation_method = None
    
    # =============================================================================
    # HANDLE PERCENTAGE/TARGET_PRICE BASED ON ALERT TYPE AND THRESHOLD_TYPE
    # =============================================================================
    # What: Set the correct field (percentage or target_price) based on alert configuration
    # Why: For threshold alerts, only one of these fields should be populated:
    #      - 'percentage' type: Store in percentage field, target_price should be None
    #      - 'value' type: Store in target_price field, percentage should be None
    #      This ensures data integrity and prevents confusion about which field is authoritative
    # How: Check alert type and threshold_type to determine which field to update
    percentage = data.get('percentage')
    
    if alert.type == 'threshold':
        # Threshold alerts: Determine which field to use based on threshold_type
        new_threshold_type = data.get('threshold_type') or alert.threshold_type or 'percentage'
        
        if new_threshold_type == 'value':
            # Value-based: Store in target_price, clear percentage
            # Note: target_price is handled separately below in the threshold-specific section
            alert.percentage = None
        else:
            # Percentage-based: Store in percentage, clear target_price
            alert.percentage = float(percentage) if percentage else None
            # Note: target_price clearing is handled in the threshold-specific section below
    else:
        # Non-threshold alerts use percentage field normally
        alert.percentage = float(percentage) if percentage else None
    
    # =============================================================================
    # THRESHOLD ALERT: HANDLE THRESHOLD_TYPE CHANGES AND TARGET_PRICE
    # =============================================================================
    # What: Handle threshold-specific field updates when editing a threshold alert
    # Why: Users may change threshold_type from percentage to value (or vice versa)
    #      which requires clearing/recapturing reference prices and target price
    # How: Check for threshold_type changes and update related fields accordingly
    if alert.type == 'threshold':
        new_threshold_type = data.get('threshold_type')
        old_threshold_type = alert.threshold_type
        
        # Handle direction for threshold alerts (they support up/down, not 'both')
        threshold_direction = data.get('direction')
        if threshold_direction:
            direction_value = threshold_direction.lower() if isinstance(threshold_direction, str) else 'up'
            if direction_value not in ['up', 'down']:
                direction_value = 'up'
            alert.direction = direction_value
        
        # Determine if this alert has multiple items
        # What: Check if alert monitors more than one item
        # Why: Value-based thresholds are not allowed for multi-item alerts
        has_multiple_items = alert.is_all_items
        if alert.item_ids:
            try:
                item_ids_list = json.loads(alert.item_ids)
                has_multiple_items = has_multiple_items or (isinstance(item_ids_list, list) and len(item_ids_list) > 1)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Block value-based threshold for multi-item alerts
        # What: Force percentage mode if user tries to set value mode with multiple items
        # Why: Value-based thresholds don't make sense for items with different prices
        if new_threshold_type == 'value' and has_multiple_items:
            return JsonResponse({
                'success': False, 
                'error': 'Value-based threshold is only allowed for single-item alerts. Please select percentage mode or choose a single item.'
            }, status=400)
        
        if new_threshold_type and new_threshold_type != old_threshold_type:
            alert.threshold_type = new_threshold_type
            
            if new_threshold_type == 'value':
                # Switching to value-based: clear reference_prices and percentage, set target_price
                # What: When changing to value mode, baseline prices and percentage are no longer needed
                # Why: Value mode compares against a fixed target price, not % from baseline
                alert.reference_prices = None
                alert.percentage = None  # Clear percentage field for value-based alerts
                target_price = data.get('target_price') or data.get('percentage')
                if target_price:
                    alert.target_price = int(float(target_price))
            else:
                # Switching to percentage-based: clear target_price, recapture reference_prices
                # What: When changing to percentage mode, need to capture new baselines
                # Why: Baselines are needed to calculate % change
                alert.target_price = None  # Clear target_price field for percentage-based alerts
                
                # Recapture reference prices for all monitored items
                all_prices = get_all_current_prices()
                if all_prices:
                    reference_prices_dict = {}
                    items_to_capture = []
                    
                    if alert.is_all_items:
                        # Capture for all items (respecting min/max filters)
                        for item_id, price_data in all_prices.items():
                            high = price_data.get('high')
                            low = price_data.get('low')
                            
                            if alert.minimum_price is not None:
                                if high is None or low is None or high < alert.minimum_price or low < alert.minimum_price:
                                    continue
                            if alert.maximum_price is not None:
                                if high is None or low is None or high > alert.maximum_price or low > alert.maximum_price:
                                    continue
                            
                            items_to_capture.append(item_id)
                    elif alert.item_ids:
                        items_to_capture = [str(x) for x in json.loads(alert.item_ids)]
                    elif alert.item_id:
                        items_to_capture = [str(alert.item_id)]
                    
                    reference_type = alert.reference or 'high'
                    for item_id in items_to_capture:
                        item_id_str = str(item_id)
                        price_data = all_prices.get(item_id_str)
                        if not price_data:
                            continue
                        
                        high = price_data.get('high')
                        low = price_data.get('low')
                        
                        if reference_type == 'high':
                            reference_price = high
                        elif reference_type == 'low':
                            reference_price = low
                        elif reference_type == 'average':
                            if high is not None and low is not None:
                                reference_price = (high + low) // 2
                            else:
                                reference_price = high or low
                        else:
                            reference_price = high
                        
                        if reference_price is not None:
                            reference_prices_dict[item_id_str] = reference_price
                    
                    if reference_prices_dict:
                        alert.reference_prices = json.dumps(reference_prices_dict)
        
        # If threshold_type is value and target_price is provided, update it
        elif new_threshold_type == 'value' or (not new_threshold_type and alert.threshold_type == 'value'):
            target_price = data.get('target_price')
            if target_price is not None:
                alert.target_price = int(float(target_price)) if target_price else None
    
    # Handle min/max price
    minimum_price = data.get('minimum_price')
    alert.minimum_price = int(minimum_price) if minimum_price else None
    
    maximum_price = data.get('maximum_price')
    alert.maximum_price = int(maximum_price) if maximum_price else None
    
    # Handle email notification
    alert.email_notification = data.get('email_notification', False)
    
    # Handle show_notification
    # show_notification: Controls whether notification banner appears when alert triggers
    if 'show_notification' in data:
        alert.show_notification = data.get('show_notification', True)
    
    # Handle is_active
    if 'is_active' in data:
        alert.is_active = data.get('is_active', True)
    
    # Handle groups
    if 'groups' in data:
        group_names = data.get('groups', [])
        alert.groups.clear()
        for name in group_names:
            group, _ = AlertGroup.objects.get_or_create(user=user, name=name)
            alert.groups.add(group)
    
    # =============================================================================
    # RESET TRIGGERED STATE ON EVERY EDIT
    # =============================================================================
    # What: Clear all triggered state whenever an alert is edited
    # Why: Simpler and cleaner than trying to selectively clean triggered_data.
    #      The check_alerts script will correctly repopulate triggered_data on
    #      the very next cycle, so this ensures clean, fresh data after any edit.
    # How: Set is_triggered=False, is_dismissed=False, clear triggered_data and triggered_at
    # Note: is_dismissed=False ensures the notification CAN show when it re-triggers
    #       (unless show_notification is False, in which case it won't appear anyway)
    
    # DEBUG: Log the reset operation
    print(f"[UPDATE_SINGLE_ALERT DEBUG] Resetting triggered state for alert {alert.id}")
    print(f"[UPDATE_SINGLE_ALERT DEBUG] BEFORE: is_triggered={alert.is_triggered}, is_dismissed={alert.is_dismissed}")
    
    alert.is_triggered = False
    alert.is_dismissed = False
    alert.triggered_data = None
    alert.triggered_at = None
    
    print(f"[UPDATE_SINGLE_ALERT DEBUG] AFTER: is_triggered={alert.is_triggered}, is_dismissed={alert.is_dismissed}")
    
    alert.save()
    
    # DEBUG: Verify the save worked
    saved_alert = Alert.objects.get(id=alert.id)
    print(f"[UPDATE_SINGLE_ALERT DEBUG] VERIFIED: is_triggered={saved_alert.is_triggered}, is_dismissed={saved_alert.is_dismissed}")
    
    return JsonResponse({'success': True})


# =============================================================================
# ITEM COLLECTION API ENDPOINTS
# =============================================================================
# What: API endpoints for managing user item collections
# Why: Users need to create, list, and delete collections of items that can be
#      quickly applied to alerts. These endpoints support the "Item Collection"
#      modal on the alerts page.
# How: Three endpoints - list (GET), create (POST), delete (DELETE)
# Note: All endpoints require authentication (no anonymous access)
# =============================================================================

def list_item_collections(request):
    """
    List all item collections for the current user.
    
    What: Returns JSON array of all collections owned by the authenticated user
    Why: The Item Collection modal needs to display existing collections for selection
    How: Query ItemCollection model filtered by user, serialize to JSON
    
    Request: GET /api/item-collections/
    
    Response (200 OK):
        {
            "success": true,
            "collections": [
                {
                    "id": 1,
                    "name": "High-value weapons",
                    "item_ids": [4151, 11802, 12924],
                    "item_names": ["Abyssal whip", "Armadyl godsword", "Dragonfire shield"],
                    "item_count": 3
                },
                ...
            ]
        }
    
    Response (401 Unauthorized) - if user not authenticated:
        {"success": false, "error": "Authentication required"}
    """
    import json
    from .models import ItemCollection
    
    # Check authentication - this feature is only for logged-in users
    # What: Verify user is authenticated before allowing access
    # Why: Collections are personal to each user; anonymous users cannot have persistent collections
    # How: Check request.user.is_authenticated; return 401 if not
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required'
        }, status=401)
    
    # Query all collections for this user
    # collections_qs: QuerySet of ItemCollection objects belonging to the user
    # Why: Filter by user to ensure users only see their own collections
    # How: Django ORM filter on user field
    collections_qs = ItemCollection.objects.filter(user=request.user)
    
    # Build response data
    # collections_data: List of dictionaries containing collection info for JSON response
    # Why: Need to serialize model data to JSON-compatible format
    # How: Iterate through queryset, parse JSON fields, build dict for each collection
    collections_data = []
    for collection in collections_qs:
        try:
            # Parse JSON fields to return as actual arrays (not strings)
            # item_ids_list: Parsed list of item IDs from JSON string
            # item_names_list: Parsed list of item names from JSON string
            item_ids_list = json.loads(collection.item_ids)
            item_names_list = json.loads(collection.item_names)
        except (json.JSONDecodeError, TypeError):
            # If JSON parsing fails, use empty arrays
            # Why: Gracefully handle corrupted data rather than crashing
            item_ids_list = []
            item_names_list = []
        
        collections_data.append({
            'id': collection.id,
            'name': collection.name,
            'item_ids': item_ids_list,
            'item_names': item_names_list,
            'item_count': len(item_ids_list)
        })
    
    return JsonResponse({
        'success': True,
        'collections': collections_data
    })


@csrf_exempt
def create_item_collection(request):
    """
    Create a new item collection.
    
    What: Creates a new ItemCollection record in the database
    Why: Users need to save collections of items for future use
    How: Parse JSON body, validate data, create ItemCollection model instance
    
    Request: POST /api/item-collections/create/
    Body (JSON):
        {
            "name": "High-value weapons",
            "item_ids": "4151,11802,12924",  // Comma-separated string
            "item_names": "Abyssal whip,Armadyl godsword,Dragonfire shield"  // Comma-separated
        }
    
    Response (200 OK):
        {
            "success": true,
            "collection": {
                "id": 1,
                "name": "High-value weapons",
                "item_ids": [4151, 11802, 12924],
                "item_names": ["Abyssal whip", "Armadyl godsword", "Dragonfire shield"],
                "item_count": 3
            }
        }
    
    Response (400 Bad Request) - if validation fails:
        {"success": false, "error": "Collection name is required"}
    
    Response (401 Unauthorized) - if user not authenticated:
        {"success": false, "error": "Authentication required"}
    
    Response (409 Conflict) - if collection name already exists:
        {"success": false, "error": "A collection with this name already exists"}
    """
    import json
    from .models import ItemCollection
    
    # Only allow POST requests
    # What: Enforce HTTP method restriction
    # Why: Create operations should use POST for RESTful design
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'POST required'
        }, status=405)
    
    # Check authentication
    # What: Verify user is authenticated before allowing collection creation
    # Why: Collections must be tied to a user account for persistence
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required'
        }, status=401)
    
    try:
        # Parse request body
        # data: Dictionary parsed from JSON request body
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    
    # Extract and validate fields
    # name: User-provided name for the collection (required)
    # item_ids_str: Comma-separated string of item IDs (required)
    # item_names_str: Comma-separated string of item names (required)
    name = data.get('name', '').strip()
    item_ids_data = data.get('item_ids', [])
    item_names_data = data.get('item_names', [])
    
    # Validate required fields
    # What: Ensure all required data is present
    # Why: Cannot create a valid collection without name and items
    if not name:
        return JsonResponse({
            'success': False,
            'error': 'Collection name is required'
        }, status=400)
    
    if not item_ids_data:
        return JsonResponse({
            'success': False,
            'error': 'At least one item is required'
        }, status=400)
    
    # Parse item data - handles both JSON arrays and comma-separated strings
    # item_ids_list: List of integer item IDs
    # item_names_list: List of item name strings
    # Why: Frontend sends JSON arrays; we validate and convert to proper format
    try:
        # If item_ids_data is already a list (from JSON), use it directly
        # Otherwise, parse as comma-separated string for backwards compatibility
        if isinstance(item_ids_data, list):
            item_ids_list = [int(x) for x in item_ids_data]
        else:
            item_ids_list = [int(x.strip()) for x in str(item_ids_data).split(',') if x.strip()]
    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'error': 'Invalid item IDs'
        }, status=400)
    
    # Parse item names - handles both JSON arrays and comma-separated strings
    if isinstance(item_names_data, list):
        item_names_list = [str(x).strip() for x in item_names_data]
    else:
        item_names_list = [x.strip() for x in str(item_names_data).split(',') if x.strip()]
    
    # Validate that we have matching counts
    # What: Ensure item_ids and item_names arrays have the same length
    # Why: Each item ID should have a corresponding name; mismatched counts indicate an error
    if len(item_ids_list) != len(item_names_list):
        return JsonResponse({
            'success': False,
            'error': 'Item IDs and names count mismatch'
        }, status=400)
    
    if not item_ids_list:
        return JsonResponse({
            'success': False,
            'error': 'At least one item is required'
        }, status=400)
    
    # Check for duplicate collection name
    # What: Verify this user doesn't already have a collection with this name
    # Why: Collection names must be unique per user (enforced by unique_together)
    # How: Query database for existing collection with same user+name
    if ItemCollection.objects.filter(user=request.user, name=name).exists():
        return JsonResponse({
            'success': False,
            'error': 'A collection with this name already exists'
        }, status=409)
    
    # Create the collection
    # collection: New ItemCollection model instance
    # Why: Store the collection in the database for future use
    # How: Create model instance with JSON-serialized arrays
    collection = ItemCollection.objects.create(
        user=request.user,
        name=name,
        item_ids=json.dumps(item_ids_list),
        item_names=json.dumps(item_names_list)
    )
    
    # Return the created collection data
    # Why: Frontend needs the new collection's ID and data to update UI
    return JsonResponse({
        'success': True,
        'collection': {
            'id': collection.id,
            'name': collection.name,
            'item_ids': item_ids_list,
            'item_names': item_names_list,
            'item_count': len(item_ids_list)
        }
    })


@csrf_exempt
def delete_item_collection(request, collection_id):
    """
    Delete an item collection.
    
    What: Deletes an ItemCollection record from the database
    Why: Users need to be able to remove collections they no longer need
    How: Find collection by ID, verify ownership, delete
    
    Request: POST /api/item-collections/<id>/delete/
    
    Response (200 OK):
        {"success": true}
    
    Response (401 Unauthorized) - if user not authenticated:
        {"success": false, "error": "Authentication required"}
    
    Response (404 Not Found) - if collection doesn't exist or doesn't belong to user:
        {"success": false, "error": "Collection not found"}
    """
    from .models import ItemCollection
    
    # Only allow POST requests (using POST instead of DELETE for simplicity with CSRF)
    # What: Enforce HTTP method restriction
    # Why: Destructive operations should be explicit; POST works better with Django CSRF
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'POST required'
        }, status=405)
    
    # Check authentication
    # What: Verify user is authenticated before allowing deletion
    # Why: Users should only be able to delete their own collections
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required'
        }, status=401)
    
    # Find the collection
    # What: Query for the collection by ID, filtered by user
    # Why: Filtering by user ensures users can only delete their own collections
    # How: Use filter().first() to get None if not found (instead of exception)
    collection = ItemCollection.objects.filter(
        id=collection_id,
        user=request.user
    ).first()
    
    if not collection:
        return JsonResponse({
            'success': False,
            'error': 'Collection not found'
        }, status=404)
    
    # Delete the collection
    # What: Remove the collection record from the database
    # Why: User requested deletion; collection is no longer needed
    collection.delete()
    
    return JsonResponse({'success': True})


def update_item_collection(request, collection_id):
    """
    Update an existing item collection.
    
    What: Updates an existing ItemCollection record in the database
    Why: Users need to be able to modify their saved collections (add/remove items, rename)
    How: Find collection by ID, verify ownership, update fields, save
    
    Request: POST /api/item-collections/<id>/update/
    Body (JSON):
        {
            "name": "Updated collection name",
            "item_ids": [4151, 11802],  // Array of item IDs
            "item_names": ["Abyssal whip", "Armadyl godsword"]  // Array of item names
        }
    
    Response (200 OK):
        {
            "success": true,
            "collection": {
                "id": 1,
                "name": "Updated collection name",
                "item_ids": [4151, 11802],
                "item_names": ["Abyssal whip", "Armadyl godsword"],
                "item_count": 2
            }
        }
    
    Response (400 Bad Request) - if validation fails:
        {"success": false, "error": "Collection name is required"}
    
    Response (401 Unauthorized) - if user not authenticated:
        {"success": false, "error": "Authentication required"}
    
    Response (404 Not Found) - if collection doesn't exist or doesn't belong to user:
        {"success": false, "error": "Collection not found"}
    
    Response (409 Conflict) - if new name conflicts with another collection:
        {"success": false, "error": "A collection with this name already exists"}
    """
    import json
    from .models import ItemCollection
    
    # Only allow POST requests
    # What: Enforce HTTP method restriction
    # Why: Update operations should use POST for simplicity with Django CSRF
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'error': 'POST required'
        }, status=405)
    
    # Check authentication
    # What: Verify user is authenticated before allowing collection update
    # Why: Users should only be able to update their own collections
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required'
        }, status=401)
    
    # Find the collection
    # What: Query for the collection by ID, filtered by user
    # Why: Filtering by user ensures users can only update their own collections
    # How: Use filter().first() to get None if not found (instead of exception)
    # collection: The ItemCollection instance to update, or None if not found
    collection = ItemCollection.objects.filter(
        id=collection_id,
        user=request.user
    ).first()
    
    if not collection:
        return JsonResponse({
            'success': False,
            'error': 'Collection not found'
        }, status=404)
    
    try:
        # Parse request body
        # data: Dictionary parsed from JSON request body containing updated fields
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    
    # Extract and validate fields
    # name: Updated name for the collection (required)
    # item_ids_data: Array of item IDs (required)
    # item_names_data: Array of item names (required)
    name = data.get('name', '').strip()
    item_ids_data = data.get('item_ids', [])
    item_names_data = data.get('item_names', [])
    
    # Validate required fields
    # What: Ensure all required data is present
    # Why: Cannot update a collection without name and items
    if not name:
        return JsonResponse({
            'success': False,
            'error': 'Collection name is required'
        }, status=400)
    
    if not item_ids_data:
        return JsonResponse({
            'success': False,
            'error': 'At least one item is required'
        }, status=400)
    
    # Check for duplicate name (excluding current collection)
    # What: Ensure no other collection by this user has the same name
    # Why: Collection names should be unique per user for identification
    # How: Query for collections with same name, exclude current collection ID
    # existing: QuerySet of collections with matching name (excluding current)
    existing = ItemCollection.objects.filter(
        user=request.user,
        name__iexact=name
    ).exclude(id=collection_id)
    
    if existing.exists():
        return JsonResponse({
            'success': False,
            'error': 'A collection with this name already exists'
        }, status=409)

    
    # Parse item IDs - handle both arrays and comma-separated strings
    # What: Convert item_ids_data into a list of integers
    # Why: Frontend may send JSON array or comma-separated string
    # How: Check type and parse accordingly
    # item_ids_list: List of integer item IDs
    if isinstance(item_ids_data, list):
        item_ids_list = [int(x) for x in item_ids_data]
    else:
        item_ids_str = str(item_ids_data)
        item_ids_list = [int(x.strip()) for x in item_ids_str.split(',') if x.strip()]
    
    # Parse item names - handle both arrays and comma-separated strings
    # What: Convert item_names_data into a list of strings
    # Why: Frontend may send JSON array or comma-separated string
    # How: Check type and parse accordingly
    # item_names_list: List of item name strings
    if isinstance(item_names_data, list):
        item_names_list = [str(x) for x in item_names_data]
    else:
        item_names_str = str(item_names_data)
        item_names_list = [x.strip() for x in item_names_str.split(',') if x.strip()]
    
    # Update collection fields
    # What: Update the collection instance with new values
    # Why: Apply the user's changes to the database record
    # How: JSON-serialize the lists before saving (TextField stores JSON strings)
    collection.name = name
    collection.item_ids = json.dumps(item_ids_list)
    collection.item_names = json.dumps(item_names_list)
    collection.save()
    
    # Return success response with updated collection data
    # What: Respond with the updated collection details
    # Why: Frontend may need the updated data for display
    # Note: Return the Python lists (not JSON strings) for easier frontend consumption
    return JsonResponse({
        'success': True,
        'collection': {
            'id': collection.id,
            'name': collection.name,
            'item_ids': item_ids_list,
            'item_names': item_names_list,
            'item_count': len(item_ids_list)
        }
    })


@csrf_exempt
def add_favorite(request):
    """API endpoint to add an item to favorites"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from .models import FavoriteItem, FavoriteGroup
    
    user = request.user if request.user.is_authenticated else None
    
    try:
        data = json.loads(request.body)
        item_id = data.get('item_id')
        item_name = data.get('item_name')
        group_ids = data.get('group_ids', [])  # List of group IDs
        new_group_name = data.get('new_group_name')
        
        if not item_id or not item_name:
            return JsonResponse({'success': False, 'error': 'item_id and item_name required'}, status=400)
        
        # Handle new group creation
        groups_to_add = []
        if new_group_name and user:
            new_group, _ = FavoriteGroup.objects.get_or_create(user=user, name=new_group_name.strip())
            groups_to_add.append(new_group)
        
        # Get existing groups by IDs
        if group_ids and user:
            existing_groups = FavoriteGroup.objects.filter(id__in=group_ids, user=user)
            groups_to_add.extend(existing_groups)
        
        favorite, created = FavoriteItem.objects.get_or_create(
            user=user,
            item_id=item_id,
            defaults={'item_name': item_name}
        )
        
        # Add groups to the item
        if groups_to_add:
            favorite.groups.add(*groups_to_add)
        
        return JsonResponse({'success': True, 'created': created})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def remove_favorite(request):
    """API endpoint to remove an item from favorites"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from .models import FavoriteItem
    
    user = request.user if request.user.is_authenticated else None
    
    try:
        data = json.loads(request.body)
        item_id = data.get('item_id')
        
        if not item_id:
            return JsonResponse({'success': False, 'error': 'item_id required'}, status=400)
        
        deleted, _ = FavoriteItem.objects.filter(user=user, item_id=item_id).delete()
        
        return JsonResponse({'success': True, 'deleted': deleted > 0})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def delete_favorite_group(request):
    """API endpoint to delete a favorite group"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from .models import FavoriteGroup, FavoriteItem
    
    user = request.user if request.user.is_authenticated else None
    if not user:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        
        if not group_id:
            return JsonResponse({'success': False, 'error': 'group_id required'}, status=400)
        
        # Set items in this group to have no group (don't delete them)
        FavoriteItem.objects.filter(user=user, group_id=group_id).update(group=None)
        
        # Delete the group
        deleted, _ = FavoriteGroup.objects.filter(user=user, id=group_id).delete()
        
        return JsonResponse({'success': True, 'deleted': deleted > 0})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def update_favorite_group_name(request):
    """API endpoint to update a favorite group's name"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from .models import FavoriteGroup
    
    user = request.user if request.user.is_authenticated else None
    if not user:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        group_id = data.get('group_id')
        name = data.get('name')
        
        if not group_id:
            return JsonResponse({'success': False, 'error': 'group_id required'}, status=400)
        
        if not name or not name.strip():
            return JsonResponse({'success': False, 'error': 'name required'}, status=400)
        
        name = name.strip()
        
        # Check if group exists for this user
        group = FavoriteGroup.objects.filter(user=user, id=group_id).first()
        if not group:
            return JsonResponse({'success': False, 'error': 'Group not found'}, status=404)
        
        # Check if another group with same name already exists for this user
        existing = FavoriteGroup.objects.filter(user=user, name=name).exclude(id=group_id).first()
        if existing:
            return JsonResponse({'success': False, 'error': 'A group with this name already exists'}, status=400)
        
        # Update the group name
        group.name = name
        group.save()
        
        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
def update_favorite_group(request):
    """API endpoint to update a favorite's groups"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    import json
    from .models import FavoriteGroup, FavoriteItem
    
    user = request.user if request.user.is_authenticated else None
    if not user:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        item_id = data.get('item_id')
        group_ids = data.get('group_ids', [])  # List of group IDs to set
        new_group_name = data.get('new_group_name')
        
        if not item_id:
            return JsonResponse({'success': False, 'error': 'item_id required'}, status=400)
        
        favorite = FavoriteItem.objects.filter(user=user, item_id=item_id).first()
        if not favorite:
            return JsonResponse({'success': False, 'error': 'Favorite not found'}, status=404)
        
        # Handle new group creation
        if new_group_name:
            new_group, _ = FavoriteGroup.objects.get_or_create(user=user, name=new_group_name.strip())
            group_ids.append(new_group.id)
        
        # Get groups and set them
        if group_ids:
            groups = FavoriteGroup.objects.filter(id__in=group_ids, user=user)
            favorite.groups.set(groups)
        else:
            favorite.groups.clear()
        
        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def favorites_page(request):
    """Display the favorites page - renders instantly, data loads via JavaScript"""
    return render(request, 'favorites.html', {})


def favorites_data_api(request):
    """API endpoint for favorites data"""
    from .models import FavoriteGroup
    
    user = request.user if request.user.is_authenticated else None
    
    # Get all current prices
    all_prices = get_all_current_prices()
    
    # Get favorite groups for this user
    groups = []
    if user:
        groups = list(FavoriteGroup.objects.filter(user=user).values('id', 'name'))
    
    # Get favorite items with current prices (filtered by user)
    favorites = []
    ungrouped_favorites = []
    grouped_favorites = {}  # group_id -> list of favorites
    
    favorites_qs = FavoriteItem.objects.filter(user=user).prefetch_related('groups') if user else FavoriteItem.objects.none()
    for fav in favorites_qs:
        item_id = str(fav.item_id)
        price_data = all_prices.get(item_id, {})
        high_price = price_data.get('high')
        low_price = price_data.get('low')
        
        # Calculate spread
        if high_price and low_price and low_price > 0:
            spread = high_price - low_price
            spread_pct = round((spread / low_price) * 100, 1)
        else:
            spread = 0
            spread_pct = 0
        
        fav_groups = list(fav.groups.all())
        fav_group_ids = [g.id for g in fav_groups]
        
        fav_data = {
            'item_id': fav.item_id,
            'item_name': fav.item_name,
            'high_price': high_price,
            'low_price': low_price,
            'spread': spread,
            'spread_pct': spread_pct,
            'group_ids': fav_group_ids,
            'group_names': [g.name for g in fav_groups],
        }
        
        favorites.append(fav_data)
        
        # Add to each group it belongs to
        if fav_groups:
            for group in fav_groups:
                if group.id not in grouped_favorites:
                    grouped_favorites[group.id] = []
                grouped_favorites[group.id].append(fav_data)
        else:
            ungrouped_favorites.append(fav_data)
    
    # Convert grouped_favorites keys to strings for JSON
    grouped_favorites_json = {str(k): v for k, v in grouped_favorites.items()}
    
    return JsonResponse({
        'favorites': favorites,
        'ungrouped_favorites': ungrouped_favorites,
        'grouped_favorites': grouped_favorites_json,
        'groups': groups,
    })


def auth_page(request):
    """Display login/signup page"""
    show_signup = request.GET.get('signup', '').lower() == 'true'
    return render(request, 'auth.html', {'show_signup': show_signup})


def login_view(request):
    """Handle login form submission"""
    if request.method != 'POST':
        return redirect('auth')
    
    email = request.POST.get('email', '').strip().lower()
    password = request.POST.get('password', '')
    
    if not email or not password:
        messages.error(request, 'Please enter both email and password.')
        return redirect('auth')
    
    # Django's User model uses username, so we use email as username
    user = authenticate(request, username=email, password=password)
    
    if user is not None:
        login(request, user)
        messages.success(request, 'Welcome back!')
        return redirect('home')
    else:
        messages.error(request, 'Invalid email or password.')
        return redirect('auth')


def signup_view(request):
    """Handle signup form submission"""
    if request.method != 'POST':
        return redirect('auth')
    
    email = request.POST.get('email', '').strip().lower()
    password = request.POST.get('password', '')
    password_confirm = request.POST.get('password_confirm', '')
    
    # Validation
    if not email or not password or not password_confirm:
        messages.error(request, 'Please fill in all fields.')
        return redirect('auth')
    
    # Validate email format
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        messages.error(request, 'Please enter a valid email address.')
        return redirect('auth')
    
    # Check if passwords match
    if password != password_confirm:
        messages.error(request, 'Passwords do not match.')
        return redirect('auth')
    
    # Validate password requirements
    if len(password) < 8:
        messages.error(request, 'Password must be at least 8 characters long.')
        return redirect('auth')
    
    if not re.search(r'\d', password):
        messages.error(request, 'Password must contain at least one number.')
        return redirect('auth')
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', password):
        messages.error(request, 'Password must contain at least one symbol.')
        return redirect('auth')
    
    # Check if email already exists
    if User.objects.filter(username=email).exists():
        messages.error(request, 'An account with this email already exists.')
        return redirect('auth')
    
    # Create user
    try:
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password
        )
        # Log the user in
        login(request, user)
        messages.success(request, 'Account created successfully! Welcome to GE Tools.')
        return redirect('home')
    except Exception as e:
        messages.error(request, f'Error creating account: {str(e)}')
        return redirect('auth')


def logout_view(request):
    """Handle logout"""
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('auth')


def settings_view(request):
    """Display user settings page"""
    if not request.user.is_authenticated:
        return redirect('auth')
    return render(request, 'settings.html')


def change_email_view(request):
    """Handle email change"""
    if not request.user.is_authenticated:
        return redirect('auth')
    
    if request.method != 'POST':
        return redirect('settings')
    
    new_email = request.POST.get('new_email', '').strip().lower()
    password = request.POST.get('password', '')
    
    # Validate password
    if not request.user.check_password(password):
        messages.error(request, 'Incorrect password.')
        return redirect('settings')
    
    # Validate email format
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
        messages.error(request, 'Please enter a valid email address.')
        return redirect('settings')
    
    # Check if email already exists
    if User.objects.filter(username=new_email).exclude(pk=request.user.pk).exists():
        messages.error(request, 'This email is already in use.')
        return redirect('settings')
    
    # Update email
    request.user.username = new_email
    request.user.email = new_email
    request.user.save()
    
    messages.success(request, 'Email address updated successfully.')
    return redirect('settings')


def request_password_reset_view(request):
    """Send password reset email"""
    from .models import PasswordResetToken
    import secrets
    from django.core.mail import send_mail
    from django.conf import settings as django_settings
    
    if not request.user.is_authenticated:
        return redirect('auth')
    
    if request.method != 'POST':
        return redirect('settings')
    
    # Generate secure random token
    token = secrets.token_urlsafe(48)
    
    # Create token record
    PasswordResetToken.objects.create(
        user=request.user,
        token=token
    )
    
    # Build reset URL
    reset_url = request.build_absolute_uri(f'/reset-password/{token}/')
    
    # Send email
    try:
        send_mail(
            subject='GE Tools - Password Reset Request',
            message=f'''You requested a password reset for your GE Tools account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you did not request this password reset, please ignore this email.

- GE Tools Team''',
            from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@getools.com'),
            recipient_list=[request.user.email],
            fail_silently=False,
        )
        messages.success(request, 'Password reset link sent to your email.')
    except Exception as e:
        messages.error(request, f'Failed to send email. Please try again later.')
    
    return redirect('settings')


def reset_password_view(request, token):
    """Handle password reset from email link"""
    from .models import PasswordResetToken
    
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
    except PasswordResetToken.DoesNotExist:
        return render(request, 'reset_password.html', {'valid': False})
    
    if not reset_token.is_valid():
        return render(request, 'reset_password.html', {'valid': False})
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        # Validate passwords match
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'reset_password.html', {
                'valid': True,
                'token': token,
                'email': reset_token.user.email
            })
        
        # Validate password requirements
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'reset_password.html', {
                'valid': True,
                'token': token,
                'email': reset_token.user.email
            })
        
        if not re.search(r'\d', new_password):
            messages.error(request, 'Password must contain at least one number.')
            return render(request, 'reset_password.html', {
                'valid': True,
                'token': token,
                'email': reset_token.user.email
            })
        
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', new_password):
            messages.error(request, 'Password must contain at least one symbol.')
            return render(request, 'reset_password.html', {
                'valid': True,
                'token': token,
                'email': reset_token.user.email
            })
        
        # Update password
        user = reset_token.user
        user.set_password(new_password)
        user.save()
        
        # Mark token as used
        reset_token.used = True
        reset_token.save()
        
        # Log the user in
        login(request, user)
        
        messages.success(request, 'Password updated successfully.')
        return redirect('settings')
    
    return render(request, 'reset_password.html', {
        'valid': True,
        'token': token,
        'email': reset_token.user.email
    })


def delete_account_view(request):
    """Handle account deletion"""
    if not request.user.is_authenticated:
        return redirect('auth')
    
    if request.method != 'POST':
        return redirect('settings')
    
    password = request.POST.get('password', '')
    confirm_text = request.POST.get('confirm_text', '')
    
    # Validate password
    if not request.user.check_password(password):
        messages.error(request, 'Incorrect password.')
        return redirect('settings')
    
    # Validate confirmation text
    if confirm_text != 'DELETE':
        messages.error(request, 'Please type DELETE to confirm.')
        return redirect('settings')
    
    # Delete user (cascades to related data)
    user = request.user
    logout(request)
    user.delete()
    
    messages.success(request, 'Your account has been deleted.')
    return redirect('auth')
