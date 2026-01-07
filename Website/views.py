from django.shortcuts import render
from django.db.models import Sum, F, Case, When, IntegerField
from .models import Flip


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
        
        items.append({
            'name': item_name,
            'avg_price': avg_price,
            'quantity': quantity_held,
        })
    
    return render(request, 'flips.html', {'items': items})


def item_search(request):
    return render(request, 'item_search.html')


def alerts(request):
    return render(request, 'alerts.html')
