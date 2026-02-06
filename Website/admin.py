from django.contrib import admin
from .models import Flip, Alert, AlertGroup, FlipProfit, FavoriteItem, HourlyItemVolume

@admin.register(FlipProfit)
class FlipProfitAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'average_cost', 'unrealized_net', 'realized_net', 'quantity_held')

@admin.register(Flip)
class FlipAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'quantity', 'price', 'type', 'date')
    list_filter = ('type', 'date')
    search_fields = ('item_name',)


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'direction', 'above_below', 'price', 'reference', 'is_triggered', 'created_at')
    list_filter = ('direction', 'above_below', 'reference', 'is_triggered')
    search_fields = ('item_name',)

@admin.register(AlertGroup)
class AlertGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')


@admin.register(FavoriteItem)
class FavoriteItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'item_id', 'item_name', 'added_at')

@admin.register(HourlyItemVolume)
class HourlyItemVolumeAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'volume', 'timestamp')
