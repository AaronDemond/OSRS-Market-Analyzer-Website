from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Sum, F, Value
from django.db.models.functions import Coalesce
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
import requests
import time
from .models import Flip, FlipProfit, Alert, AlertGroup


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
    return render(request, 'home.html')


def flips(request):
    # Get time filter from query params
    time_filter = request.GET.get('filter', 'current')
    
    # Get all unique items
    item_ids = Flip.objects.values_list('item_id', flat=True).distinct()
    
    # Fetch all current prices in one API call
    all_prices = get_all_current_prices()
    
    # Recalculate unrealized_net for all FlipProfit objects
    for flip_profit in FlipProfit.objects.all():
        current_high = None
        if str(flip_profit.item_id) in all_prices:
            current_high = all_prices[str(flip_profit.item_id)].get('high')
        
        if current_high and flip_profit.quantity_held > 0:
            flip_profit.unrealized_net = flip_profit.quantity_held * ((current_high * 0.98) - flip_profit.average_cost)
        else:
            flip_profit.unrealized_net = 0
        flip_profit.save()
    
    items = []
    
    # Calculate totals from FlipProfit
    total_unrealized = FlipProfit.objects.aggregate(total=Sum('unrealized_net'))['total'] or 0
    total_realized = FlipProfit.objects.aggregate(total=Sum('realized_net'))['total'] or 0
    position_size = FlipProfit.objects.aggregate(total=Sum(F('quantity_held') * F('average_cost')))['total'] or 0
    
    for item_id in item_ids:
        item_flips = Flip.objects.filter(item_id=item_id)
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
        
        # Get FlipProfit for this item
        flip_profit = FlipProfit.objects.filter(item_id=item_id).first()
        item_unrealized = flip_profit.unrealized_net if flip_profit else 0
        item_realized = flip_profit.realized_net if flip_profit else 0
        
        # Get first buy date for time held calculation
        first_buy = buys.order_by('date').first()
        first_buy_timestamp = first_buy.date.timestamp() if first_buy else None
        
        items.append({
            'item_id': item_id,
            'name': item_name,
            'avg_price': avg_price,
            'high_price': high_price,
            'low_price': low_price,
            'quantity': quantity_held,
            'quantity_holding': quantity_held,
            'total_bought': total_bought,
            'total_sold': total_sold,
            'unrealized_net': item_unrealized,
            'realized_net': item_realized,
            'first_buy_timestamp': first_buy_timestamp,
            'position_size': avg_price * quantity_held,
        })
    
    return render(request, 'flips.html', {
        'items': items,
        'total_unrealized': total_unrealized,
        'total_realized': total_realized,
        'position_size': position_size,
        'time_filter': time_filter,
    })


def add_flip(request):
    if request.method == 'POST':
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
            item_id=item_id,
            item_name=canonical_name,
            price=price,
            date=date,
            quantity=quantity,
            type=flip_type
        )
        
        # Handle FlipProfit tracking for buys
        if flip_type == 'buy' and item_id != 0:
            flip_profit = FlipProfit.objects.filter(item_id=item_id).first()
            
            if not flip_profit:
                # Get current high price from API
                current_high = None
                all_prices = get_all_current_prices()
                if str(item_id) in all_prices:
                    current_high = all_prices[str(item_id)].get('high')
                
                # Calculate unrealized net: quantity_held * ((currentHigh * 0.98) - average_cost)
                if current_high:
                    unrealized_net = quantity * ((current_high * 0.98) - price)
                else:
                    unrealized_net = 0
                
                # Create new FlipProfit
                FlipProfit.objects.create(
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
                current_high = None
                if str(item_id) in all_prices:
                    current_high = all_prices[str(item_id)].get('high')
                
                if current_high:
                    flip_profit.unrealized_net = new_quantity_held * ((current_high * 0.98) - new_average_cost)
                else:
                    flip_profit.unrealized_net = 0
                
                flip_profit.save()
        
        # Handle FlipProfit tracking for sells
        if flip_type == 'sell' and item_id != 0:
            flip_profit = FlipProfit.objects.filter(item_id=item_id).first()
            
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
                current_high = None
                if str(item_id) in all_prices:
                    current_high = all_prices[str(item_id)].get('high')
                
                if current_high and new_quantity_held > 0:
                    flip_profit.unrealized_net = new_quantity_held * ((current_high * 0.98) - flip_profit.average_cost)
                else:
                    flip_profit.unrealized_net = 0
                
                flip_profit.save()
    
    return redirect('flips')


def recalculate_flip_profit(item_id):
    """Recalculate FlipProfit for an item by replaying all flips in chronological order"""
    # Delete existing FlipProfit for this item
    FlipProfit.objects.filter(item_id=item_id).delete()
    
    # Get all flips for this item ordered by date
    flips = Flip.objects.filter(item_id=item_id).order_by('date')
    
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
            realized_gain = flip.quantity * (flip.price - average_cost)
            realized_net = realized_net + realized_gain
            quantity_held = quantity_held - flip.quantity
    
    # Calculate unrealized_net with current prices
    all_prices = get_all_current_prices()
    current_high = None
    if str(item_id) in all_prices:
        current_high = all_prices[str(item_id)].get('high')
    
    if current_high and quantity_held > 0:
        unrealized_net = quantity_held * ((current_high * 0.98) - average_cost)
    else:
        unrealized_net = 0
    
    # Create new FlipProfit
    FlipProfit.objects.create(
        item_id=item_id,
        average_cost=average_cost,
        unrealized_net=unrealized_net,
        realized_net=realized_net,
        quantity_held=quantity_held
    )


def delete_flip(request, item_id):
    """Delete all flips for a specific item"""
    if request.method == 'POST':
        Flip.objects.filter(item_id=item_id).delete()
        # Also delete the FlipProfit for this item
        FlipProfit.objects.filter(item_id=item_id).delete()
    return redirect('flips')


def delete_single_flip(request):
    """Delete a single flip by ID"""
    if request.method == 'POST':
        flip_id = request.POST.get('flip_id')
        flip = Flip.objects.filter(id=flip_id).first()
        if flip:
            item_id = flip.item_id
            flip.delete()
            # Check if there are any remaining flips for this item
            if Flip.objects.filter(item_id=item_id).exists():
                # Recalculate FlipProfit for this item
                recalculate_flip_profit(item_id)
                return redirect('item_detail', item_id=item_id)
            else:
                # No more flips, delete FlipProfit
                FlipProfit.objects.filter(item_id=item_id).delete()
    return redirect('flips')


def edit_flip(request):
    """Edit a single flip"""
    if request.method == 'POST':
        flip_id = request.POST.get('flip_id')
        flip = Flip.objects.filter(id=flip_id).first()
        if flip:
            flip.price = int(request.POST.get('price'))
            flip.date = request.POST.get('date')
            flip.quantity = int(request.POST.get('quantity'))
            flip.type = request.POST.get('type')
            flip.save()
            # Recalculate FlipProfit for this item
            recalculate_flip_profit(flip.item_id)
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
    flips = Flip.objects.filter(item_id=item_id).order_by('-date')
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
    active_alerts = Alert.objects.filter(is_active=True)
    triggered_alerts = Alert.objects.filter(is_triggered=True, is_dismissed=False).prefetch_related('groups')
    has_alerts = Alert.objects.exists()
    return render(request, 'alerts.html', {
        'active_alerts': active_alerts,
        'triggered_alerts': triggered_alerts,
        'has_alerts': has_alerts,
    })


def create_alert(request):
    if request.method == 'POST':
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
        direction_value = None
        if alert_type == 'spike':
            direction_value = (direction or '').lower()
            if direction_value not in ['up', 'down', 'both']:
                direction_value = 'both'
        
        # Determine all-items flag based on selection
        is_all_items = is_all_items_flag
        if alert_type == 'spike' and number_of_items:
            is_all_items = number_of_items == 'all'
        
        # Look up item ID from name if not provided
        if not item_id and item_name:
            mapping = get_item_mapping()
            item_data = mapping.get(item_name.lower())
            if item_data:
                item_id = item_data['id']
                item_name = item_data['name']
        
        Alert.objects.create(
            type=alert_type,
            item_name=item_name if not is_all_items else None,
            item_id=int(item_id) if item_id and not is_all_items else None,
            price=int(time_frame if alert_type == 'spike' else price) if (time_frame if alert_type == 'spike' else price) else None,
            reference=reference if reference else None,
            percentage=float(percentage) if percentage else None,
            is_all_items=is_all_items,
            minimum_price=int(minimum_price) if minimum_price else None,
            maximum_price=int(maximum_price) if maximum_price else None,
            email_notification=email_notification,
            is_active=True,
            is_triggered=False,
            direction=direction_value
        )
        messages.success(request, 'Alert created')
        return redirect('alerts')
    
    return redirect('alerts')


def alerts_api(request):
    """API endpoint to fetch current alerts status"""
    from Website.models import get_item_price
    import requests
    
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
    
    all_alerts = Alert.objects.all().order_by(Coalesce('item_name', Value('All items')).asc())
    alerts_data = []
    all_groups_set = set()
    for alert in all_alerts:
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
            'time_frame': alert.price if alert.type == 'spike' else None,
            'minimum_price': alert.minimum_price,
            'maximum_price': alert.maximum_price,
            'created_at': alert.created_at.isoformat(),
            'last_triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
            'groups': list(alert.groups.values_list('name', flat=True))
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
    
    # Get recently triggered alerts (triggered and not dismissed)
    triggered_alerts = Alert.objects.filter(is_triggered=True, is_dismissed=False)
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
            'time_frame': alert.price if alert.type == 'spike' else None,
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
        
        triggered_data.append(triggered_dict)
    
    all_groups = sorted(all_groups_set)
    return JsonResponse({'alerts': alerts_data, 'triggered': triggered_data, 'groups': all_groups})


@csrf_exempt
def dismiss_triggered_alert(request):
    """Dismiss a triggered alert notification"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        alert_id = data.get('alert_id')
        if alert_id:
            Alert.objects.filter(id=alert_id).update(is_dismissed=True)
    return JsonResponse({'success': True})


@csrf_exempt
def delete_alerts(request):
    print("Delete alerts called")
    """Delete multiple alerts"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        alert_ids = data.get('alert_ids', [])
        if alert_ids:
            print(alert_ids)
            Alert.objects.filter(id__in=alert_ids).delete()
    return JsonResponse({'success': True})


@csrf_exempt
def group_alerts(request):
    """Assign alerts to one or more groups (creates groups as needed)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    import json
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

    # Ensure groups exist
    group_objs = []
    for name in group_names:
        group_obj, _ = AlertGroup.objects.get_or_create(name=name)
        group_objs.append(group_obj)

    alerts = Alert.objects.filter(id__in=alert_ids)
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
        count, _ = AlertGroup.objects.filter(name__iexact=name).delete()
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
        alert = Alert.objects.get(id=alert_id)
    except Alert.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Alert not found'}, status=404)

    # Find the group objects and remove them from the alert
    cleaned = [g.strip() for g in groups if isinstance(g, str) and g.strip()]
    group_objs = AlertGroup.objects.filter(name__in=cleaned)
    
    for group in group_objs:
        alert.groups.remove(group)

    return JsonResponse({'success': True, 'unlinked_groups': cleaned})


@csrf_exempt
def update_alert(request):
    """Update an existing alert"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        alert_id = data.get('alert_id')
        if alert_id:
            alert = Alert.objects.filter(id=alert_id).first()
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
                
                # Handle percentage for spread or spike alerts
                percentage = data.get('percentage')
                if percentage:
                    alert.percentage = float(percentage)
                else:
                    alert.percentage = None
                
                # Handle min/max price for spread all items alerts
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
    
    alert = get_object_or_404(Alert, id=alert_id)
    
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
    
    # Get alert groups
    groups = list(alert.groups.values_list('name', flat=True))
    all_groups = list(AlertGroup.objects.values_list('name', flat=True))
    
    # Build triggered data for display
    triggered_info = None
    if alert.is_triggered:
        triggered_info = {
            'triggered_at': alert.triggered_at,
            'is_all_items': alert.is_all_items,
            'alert_type': alert.type,
        }
        
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
    
    alert = get_object_or_404(Alert, id=alert_id)
    
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
            group, _ = AlertGroup.objects.get_or_create(name=name)
            alert.groups.add(group)
    
    # Reset triggered state when alert is edited
    alert.is_triggered = False
    alert.is_dismissed = False
    alert.triggered_data = None
    alert.triggered_at = None
    
    alert.save()
    
    return JsonResponse({'success': True})
