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
from .models import Flip, FlipProfit, Alert, AlertGroup, FavoriteItem


# Cache for item mappings
_item_mapping_cache = None


def get_item_mapping():
    """Fetch and cache item name to ID mapping from RuneScape Wiki API"""
    global _item_mapping_cache
    if _item_mapping_cache is None:
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


def get_all_current_prices():
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
    except requests.RequestException:
        pass
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
    """API endpoint for flip data - enables progressive loading"""
    time_filter = request.GET.get('filter', 'current')
    
    # Get current user (or None if not authenticated)
    user = request.user if request.user.is_authenticated else None
    
    # Get all unique items for this user
    flips_qs = Flip.objects.filter(user=user) if user else Flip.objects.none()
    flip_profits_qs = FlipProfit.objects.filter(user=user) if user else FlipProfit.objects.none()
    item_ids = list(flips_qs.values_list('item_id', flat=True).distinct())
    
    # Fetch all current prices in one API call
    all_prices = get_all_current_prices()
    
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
            flip_profit.unrealized_net = flip_profit.quantity_held * ((current_price * 0.98) - flip_profit.average_cost)
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


def add_flip(request):
    if request.method == 'POST':
        # Get current user
        user = request.user if request.user.is_authenticated else None
        
        item_name = request.POST.get('item_name')
        price = int(request.POST.get('price'))
        date = request.POST.get('date')
        quantity = int(request.POST.get('quantity'))
        flip_type = request.POST.get('type')
        
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
        
        # Handle FlipProfit tracking for buys
        if flip_type == 'buy' and item_id != 0:
            flip_profit = FlipProfit.objects.filter(user=user, item_id=item_id).first()
            
            if not flip_profit:
                # Get current price from API (average of high and low)
                current_price = None
                all_prices = get_all_current_prices()
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
                
                # Calculate unrealized net: quantity_held * ((current_price * 0.98) - average_cost)
                if current_price:
                    unrealized_net = quantity * ((current_price * 0.98) - price)
                else:
                    unrealized_net = 0
                
                # Create new FlipProfit
                FlipProfit.objects.create(
                    user=user,
                    item_id=item_id,
                    average_cost=price,
                    unrealized_net=unrealized_net,
                    realized_net=0,
                    quantity_held=quantity
                )
            else:
                # FlipProfit exists - recalculate average_cost and quantity_held
                # New average_cost = ((old_qty * old_avg) + (new_qty * new_price)) / (old_qty + new_qty)
                new_average_cost = ((flip_profit.quantity_held * flip_profit.average_cost) + (quantity * price)) / (flip_profit.quantity_held + quantity)
                new_quantity_held = flip_profit.quantity_held + quantity
                
                flip_profit.average_cost = new_average_cost
                flip_profit.quantity_held = new_quantity_held
                
                # Recalculate unrealized_net with updated values
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
                
                if current_price:
                    flip_profit.unrealized_net = new_quantity_held * ((current_price * 0.98) - new_average_cost)
                else:
                    flip_profit.unrealized_net = 0
                
                flip_profit.save()
        
        # Handle FlipProfit tracking for sells
        if flip_type == 'sell' and item_id != 0:
            flip_profit = FlipProfit.objects.filter(user=user, item_id=item_id).first()
            
            if flip_profit:
                # Calculate realized gain/loss
                # realized_gain = quantity * (sell_price - average_cost)
                current_realized = flip_profit.realized_net
                realized_gain = quantity * ((price * 0.98) - flip_profit.average_cost)
                new_realized_net = current_realized + realized_gain
                
                # Update quantity_held
                new_quantity_held = flip_profit.quantity_held - quantity
                
                flip_profit.realized_net = new_realized_net
                flip_profit.quantity_held = new_quantity_held
                
                # Recalculate unrealized_net with updated quantity_held
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
                
                if current_price and new_quantity_held > 0:
                    flip_profit.unrealized_net = new_quantity_held * ((current_price * 0.98) - flip_profit.average_cost)
                else:
                    flip_profit.unrealized_net = 0
                
                flip_profit.save()
    
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
            realized_gain = flip.quantity * ((flip.price * 0.98) - average_cost)
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
        unrealized_net = quantity_held * ((current_price * 0.98) - average_cost)
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
            flip.date = request.POST.get('date')
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
    return render(request, 'item_search.html')


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
        email_notification = request.POST.get('email_notification') == 'on'
        group_id = request.POST.get('group_id')  # Group to assign alert to
        
        # Sustained Move specific fields
        min_consecutive_moves = request.POST.get('min_consecutive_moves')
        min_move_percentage = request.POST.get('min_move_percentage')
        volatility_buffer_size = request.POST.get('volatility_buffer_size')
        volatility_multiplier = request.POST.get('volatility_multiplier')
        min_volume = request.POST.get('min_volume')
        sustained_item_ids_str = request.POST.get('sustained_item_ids', '')
        min_pressure_strength = request.POST.get('min_pressure_strength') or None
        min_pressure_spread_pct = request.POST.get('min_pressure_spread_pct')
        
        direction_value = None
        if alert_type in ['spike', 'sustained']:
            direction_value = (direction or '').lower()
            if direction_value not in ['up', 'down', 'both']:
                direction_value = 'both'
        
        # Determine all-items flag based on selection
        is_all_items = is_all_items_flag
        if alert_type == 'spike' and number_of_items:
            is_all_items = number_of_items == 'all'
        
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
        
        # For sustained alerts, use multi-item data if available
        final_item_name = sustained_item_name if alert_type == 'sustained' and sustained_item_name else (item_name if not is_all_items else None)
        final_item_id = None
        if alert_type == 'sustained' and sustained_item_ids_json:
            # Store first item ID for backwards compatibility
            item_ids = json_module.loads(sustained_item_ids_json)
            final_item_id = item_ids[0] if item_ids else None
        elif item_id and not is_all_items:
            final_item_id = int(item_id)
        
        # Reference is not used for sustained alerts
        reference_value = reference if reference and alert_type != 'sustained' else None
        
        alert = Alert.objects.create(
            user=user,
            type=alert_type,
            item_name=final_item_name,
            item_id=final_item_id,
            price=price_value,
            reference=reference_value,
            percentage=float(percentage) if percentage else None,
            is_all_items=is_all_items,
            minimum_price=int(minimum_price) if minimum_price else None,
            maximum_price=int(maximum_price) if maximum_price else None,
            email_notification=email_notification,
            is_active=True,
            is_triggered=False,
            direction=direction_value,
            time_frame=time_frame_value,
            # Sustained Move fields
            min_consecutive_moves=int(min_consecutive_moves) if min_consecutive_moves else None,
            min_move_percentage=float(min_move_percentage) if min_move_percentage else None,
            volatility_buffer_size=int(volatility_buffer_size) if volatility_buffer_size else None,
            volatility_multiplier=float(volatility_multiplier) if volatility_multiplier else None,
            min_volume=int(min_volume) if min_volume else None,
            sustained_item_ids=sustained_item_ids_json,
            min_pressure_strength=min_pressure_strength,
            min_pressure_spread_pct=float(min_pressure_spread_pct) if min_pressure_spread_pct else None
        )
        
        # Assign to group if specified
        if group_id:
            from Website.models import AlertGroup
            try:
                group = AlertGroup.objects.get(user=user, name=group_id)
                alert.groups.add(group)
            except AlertGroup.DoesNotExist:
                pass  # Group doesn't exist, skip assignment
        
        messages.success(request, 'Alert created')
        return redirect('alerts')
    
    return redirect('alerts')


def alerts_api(request):
    """API endpoint to fetch current alerts status"""
    from Website.models import get_item_price
    import requests
    
    # Get current user
    user = request.user if request.user.is_authenticated else None
    
    # Fetch all prices once for spread calculations
    all_prices = {}
    try:
        response = requests.get(
            'https://prices.runescape.wiki/api/v1/osrs/latest',
            headers={'User-Agent': 'GE-Tools (not yet live) - demondsoftware@gmail.com'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                all_prices = data['data']
    except requests.RequestException:
        pass
    
    # Get item mapping for icons
    mapping = get_item_mapping()
    
    # Filter alerts by user
    alerts_qs = Alert.objects.filter(user=user) if user else Alert.objects.none()
    all_alerts = alerts_qs.order_by(Coalesce('item_name', Value('All items')).asc())
    alerts_data = []
    all_groups_set = set()
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
            'is_triggered': alert.is_triggered,
            'triggered_text': alert.triggered_text() if alert.is_triggered else None,
            'type': alert.type,
            'direction': alert.direction,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price,
            'percentage': alert.percentage,
            'time_frame': alert.price if alert.type == 'spike' else (alert.time_frame if alert.type == 'sustained' else None),
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
            'min_pressure_spread_pct': alert.min_pressure_spread_pct if alert.type == 'sustained' else None
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
        
        # Add current price for above/below alerts
        if alert.type in ['above', 'below', 'spike'] and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                if alert.reference == 'low':
                    alert_dict['current_price'] = price_data.get('low')
                else:
                    alert_dict['current_price'] = price_data.get('high')
        
        alerts_data.append(alert_dict)
    
    # Get recently triggered alerts for this user (triggered and not dismissed)
    triggered_alerts = alerts_qs.filter(is_triggered=True, is_dismissed=False)
    triggered_data = []
    for alert in triggered_alerts:
        triggered_dict = {
            'id': alert.id,
            'triggered_text': alert.triggered_text(),
            'type': alert.type,
            'direction': alert.direction,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price,
            'time_frame': alert.price if alert.type == 'spike' else (alert.time_frame if alert.type == 'sustained' else None),
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
        
        # Add current price for above/below alerts
        if alert.type in ['above', 'below', 'spike'] and alert.item_id and all_prices:
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


@csrf_exempt
def dismiss_triggered_alert(request):
    """Dismiss a triggered alert notification"""
    if request.method == 'POST':
        import json
        user = request.user if request.user.is_authenticated else None
        data = json.loads(request.body)
        alert_id = data.get('alert_id')
        if alert_id:
            Alert.objects.filter(id=alert_id, user=user).update(is_dismissed=True)
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
                
                # Handle is_all_items
                is_all_items = data.get('is_all_items', False)
                alert.is_all_items = is_all_items
                
                if is_all_items:
                    alert.item_name = None
                    alert.item_id = None
                else:
                    alert.item_name = data.get('item_name', alert.item_name)
                    item_id = data.get('item_id')
                    if item_id:
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
                else:
                    price = data.get('price')
                    alert.price = int(price) if price else None
                    alert.time_frame = None
                
                # Handle reference (not used for sustained)
                if alert.type == 'sustained':
                    alert.reference = None
                else:
                    reference = data.get('reference')
                    alert.reference = reference if reference else None

                # Handle direction for spike and sustained
                direction = data.get('direction')
                if alert.type in ['spike', 'sustained']:
                    direction_value = (direction or '').lower() if isinstance(direction, str) else ''
                    if direction_value not in ['up', 'down', 'both']:
                        direction_value = 'both'
                    alert.direction = direction_value
                else:
                    alert.direction = None
                
                # Handle percentage for spread or spike alerts (not sustained)
                if alert.type in ['spread', 'spike']:
                    percentage = data.get('percentage')
                    alert.percentage = float(percentage) if percentage else None
                else:
                    alert.percentage = None
                
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
                else:
                    # Clear sustained fields for other alert types
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
                
                # Reset triggered state when alert is edited
                alert.is_triggered = False
                alert.is_dismissed = False
                alert.is_active = True
                alert.triggered_data = None
                alert.triggered_at = None
                alert.save()
    return JsonResponse({'success': True})


def alert_detail(request, alert_id):

    """Display detailed view of a single alert"""
    from django.shortcuts import get_object_or_404
    import json
    
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
            if alert.triggered_data:
                try:
                    sustained_data = json.loads(alert.triggered_data)
                    triggered_info['sustained_data'] = sustained_data
                    print(triggered_info['alert_type'])
                    '''
                    triggered_info['sustained_data'] = sustained_data
                    triggered_info['sustained_item_name'] = sustained_data.get('item_name')
                    triggered_info['sustained_direction'] = sustained_data.get('streak_direction')
                    triggered_info['sustained_streak_count'] = sustained_data.get('streak_count')
                    triggered_info['sustained_total_move'] = sustained_data.get('total_move_percent')
                    triggered_info['sustained_start_price'] = sustained_data.get('start_price')
                    triggered_info['sustained_current_price'] = sustained_data.get('current_price')
                    triggered_info['sustained_volume'] = sustained_data.get('volume')
                    '''
                except json.JSONDecodeError:
                    pass

        
        if alert.is_all_items and alert.triggered_data:
            # Parse the JSON triggered data for all-items alerts
            try:
                triggered_info['items'] = json.loads(alert.triggered_data)
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
            elif alert.type in ['above', 'below']:
                triggered_info['threshold_price'] = alert.price
                triggered_info['reference'] = alert.reference
                if alert.reference == 'low':
                    triggered_info['current_price'] = price_data.get('low')
                else:
                    triggered_info['current_price'] = price_data.get('high')
            elif alert.type == 'spike':
                # For spike alerts, triggered_data contains the spike info
                if alert.triggered_data:
                    try:
                        spike_data = json.loads(alert.triggered_data)
                        if spike_data and len(spike_data) > 0:
                            triggered_info['spike_data'] = spike_data[0] if isinstance(spike_data, list) else spike_data
                    except json.JSONDecodeError:
                        pass

    # Check if redirected after save
    edit_saved = request.GET.get('edit_saved') == '1'
    
    context = {
        'alert': alert,
        'current_price': current_price_data,
        'groups': groups,
        'all_groups': all_groups,
        'groups_json': json.dumps(groups),
        'all_groups_json': json.dumps(all_groups),
        'triggered_info': triggered_info,
        'edit_saved': edit_saved,
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
    
    # Handle is_all_items
    is_all_items = data.get('is_all_items', False)
    alert.is_all_items = is_all_items
    
    if is_all_items:
        alert.item_name = None
        alert.item_id = None
    else:
        alert.item_name = data.get('item_name', alert.item_name)
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
    else:
        price = data.get('price')
        alert.price = int(price) if price else None
    
    reference = data.get('reference')
    alert.reference = reference if reference else None
    
    direction = data.get('direction')
    if alert.type == 'spike':
        direction_value = (direction or '').lower() if isinstance(direction, str) else ''
        if direction_value not in ['up', 'down', 'both']:
            direction_value = 'both'
        alert.direction = direction_value
    else:
        alert.direction = None
    
    # Handle percentage
    percentage = data.get('percentage')
    alert.percentage = float(percentage) if percentage else None
    
    # Handle min/max price
    minimum_price = data.get('minimum_price')
    alert.minimum_price = int(minimum_price) if minimum_price else None
    
    maximum_price = data.get('maximum_price')
    alert.maximum_price = int(maximum_price) if maximum_price else None
    
    # Handle email notification
    alert.email_notification = data.get('email_notification', False)
    
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
    
    # Reset triggered state when alert is edited
    alert.is_triggered = False
    alert.is_dismissed = False
    alert.triggered_data = None
    alert.triggered_at = None
    
    alert.save()
    
    return JsonResponse({'success': True})


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
