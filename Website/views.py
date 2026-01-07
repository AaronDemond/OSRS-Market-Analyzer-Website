from django.shortcuts import render, redirect
from django.db.models import Sum, F
import requests
from .models import Flip


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


def test(request):
    return render(request, 'test.html')


def home(request):
    return render(request, 'home.html')


def flips(request):
    # Get all unique items
    item_ids = Flip.objects.values_list('item_id', flat=True).distinct()
    
    items = []
    for item_id in item_ids:
        item_flips = Flip.objects.filter(item_id=item_id)
        item_name = item_flips.first().item_name
        
        # Calculate total bought and spent
        buys = item_flips.filter(type='buy')
        total_bought = buys.aggregate(total=Sum('quantity'))['total'] or 0
        total_spent = buys.aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0
        
        # Calculate total sold
        sells = item_flips.filter(type='sell')
        total_sold = sells.aggregate(total=Sum('quantity'))['total'] or 0
        
        # Average price (of buys)
        avg_price = total_spent // total_bought if total_bought > 0 else 0
        
        # Current quantity held
        quantity_held = total_bought - total_sold
        
        # Fetch current prices from API
        high_price = None
        low_price = None
        try:
            response = requests.get(
                f'https://prices.runescape.wiki/api/v1/osrs/latest?id={item_id}',
                headers={'User-Agent': 'GE Tracker'}
            )
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and str(item_id) in data['data']:
                    price_data = data['data'][str(item_id)]
                    high_price = price_data.get('high')
                    low_price = price_data.get('low')
        except requests.RequestException:
            pass
        
        items.append({
            'name': item_name,
            'avg_price': avg_price,
            'high_price': high_price,
            'low_price': low_price,
            'quantity': quantity_held,
        })
    
    return render(request, 'flips.html', {'items': items})


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


def item_search(request):
    return render(request, 'item_search.html')


def alerts(request):
    return render(request, 'alerts.html')
