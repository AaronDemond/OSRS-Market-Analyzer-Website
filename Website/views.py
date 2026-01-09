from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Sum, F, Value
from django.db.models.functions import Coalesce
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
import requests
import time
from .models import Flip, Alert, AlertGroup


# Cache for item mappings
_item_mapping_cache = None


def get_item_mapping():
    """Fetch and cache item name to ID mapping from RuneScape Wiki API"""
    global _item_mapping_cache
    if _item_mapping_cache is None:
        try:
            response = requests.get(
                'https://prices.runescape.wiki/api/v1/osrs/mapping',
                headers={'User-Agent': 'GE Tracker'}
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
            headers={'User-Agent': 'GE Tracker'}
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
            headers={'User-Agent': 'GE Tracker'}
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
    
    items = []
    total_net = 0
    position_size = 0
    
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
        total_sell_revenue = sells.aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0
        total_sell_revenue_after_tax = int(total_sell_revenue * 0.98)
        
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
        
        # Calculate unrealized value of remaining items (with tax)
        unrealized_value = 0
        if high_price and quantity_held > 0:
            unrealized_value = int(quantity_held * high_price * 0.98)
        
        # Calculate net for this item: (realized sells + unrealized value) - total spent
        item_net = (total_sell_revenue_after_tax + unrealized_value) - total_spent
        total_net += item_net
        
        # Position size is the cost basis of remaining items
        position_size += avg_price * quantity_held
        
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
            'net': item_net,
        })
    
    return render(request, 'flips.html', {
        'items': items,
        'total_net': total_net,
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
    
    return redirect('flips')


def delete_flip(request, item_id):
    """Delete all flips for a specific item"""
    if request.method == 'POST':
        Flip.objects.filter(item_id=item_id).delete()
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
                return redirect('item_detail', item_id=item_id)
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


def alerts(request):
    # Sort alphabetically - "All items" alerts (null item_name) sort after named items
    all_alerts = Alert.objects.all().prefetch_related('groups').order_by(Coalesce('item_name', Value('zzz')).asc())
    active_alerts = Alert.objects.filter(is_active=True)
    triggered_alerts = Alert.objects.filter(is_triggered=True, is_dismissed=False).prefetch_related('groups')
    return render(request, 'alerts.html', {
        'active_alerts': active_alerts,
        'triggered_alerts': triggered_alerts,
        'all_alerts': all_alerts,

    })


def create_alert(request):
    if request.method == 'POST':
        alert_type = request.POST.get('type')
        item_name = request.POST.get('item_name')
        item_id = request.POST.get('item_id')
        price = request.POST.get('price')
        reference = request.POST.get('reference')
        percentage = request.POST.get('percentage')
        is_all_items = request.POST.get('is_all_items') == 'true'
        minimum_price = request.POST.get('minimum_price')
        maximum_price = request.POST.get('maximum_price')
        email_notification = request.POST.get('email_notification') == 'on'
        
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
            price=int(price) if price else None,
            reference=reference if reference else None,
            percentage=float(percentage) if percentage else None,
            is_all_items=is_all_items,
            minimum_price=int(minimum_price) if minimum_price else None,
            maximum_price=int(maximum_price) if maximum_price else None,
            email_notification=email_notification,
            is_active=True,
            is_triggered=False
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
            headers={'User-Agent': 'GE Tracker'}
        )
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                all_prices = data['data']
    except requests.RequestException:
        pass
    
    all_alerts = Alert.objects.all().order_by(Coalesce('item_name', Value('zzz')).asc())
    alerts_data = []
    all_groups_set = set()
    for alert in all_alerts:
        alert_dict = {
            'id': alert.id,
            'text': str(alert),
            'is_triggered': alert.is_triggered,
            'triggered_text': alert.triggered_text() if alert.is_triggered else None,
            'type': alert.type,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price,
            'percentage': alert.percentage,
            'minimum_price': alert.minimum_price,
            'maximum_price': alert.maximum_price,
            'created_at': alert.created_at.isoformat(),
            'last_triggered_at': getattr(alert, 'triggered_at', None),
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
        if alert.type in ['above', 'below'] and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                if alert.reference == 'high':
                    alert_dict['current_price'] = price_data.get('high')
                else:
                    alert_dict['current_price'] = price_data.get('low')
        
        alerts_data.append(alert_dict)
    
    # Get recently triggered alerts (triggered and not dismissed)
    triggered_alerts = Alert.objects.filter(is_triggered=True, is_dismissed=False)
    triggered_data = []
    for alert in triggered_alerts:
        triggered_dict = {
            'id': alert.id,
            'triggered_text': alert.triggered_text(),
            'type': alert.type,
            'is_all_items': alert.is_all_items,
            'triggered_data': alert.triggered_data,
            'reference': alert.reference,
            'price': alert.price
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
        if alert.type in ['above', 'below'] and alert.item_id and all_prices:
            price_data = all_prices.get(str(alert.item_id))
            if price_data:
                if alert.reference == 'high':
                    triggered_dict['current_price'] = price_data.get('high')
                else:
                    triggered_dict['current_price'] = price_data.get('low')
        
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
                
                # Handle price/reference for above/below alerts
                price = data.get('price')
                if price:
                    alert.price = int(price)
                else:
                    alert.price = None
                    
                reference = data.get('reference')
                alert.reference = reference if reference else None
                
                # Handle percentage for spread alerts
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
                alert.save()
    return JsonResponse({'success': True})
