from django.contrib import admin
from .models import Flip


@admin.register(Flip)
class FlipAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'quantity', 'price_bought', 'price_sold', 'is_buy', 'is_sell', 'date')
    list_filter = ('is_buy', 'is_sell', 'date')
    search_fields = ('item_name',)
