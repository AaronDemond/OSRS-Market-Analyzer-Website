from django.contrib import admin
from .models import (
    Alert,
    AlertGroup,
    AllTimeData,
    FavoriteItem,
    FiveMinTimeSeries,
    Flip,
    FlipJournal,
    FlipJournalExit,
    FlipJournalNote,
    FlipJournalStrategy,
    FlipJournalTag,
    FlipProfit,
    HourlyItemVolume,
    OneHourTimeSeries,
    SixHourTimeSeries,
    TwentyFourHourTimeSeries,
    FlipAlert,
)

@admin.register(FlipProfit)
class FlipProfitAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'average_cost', 'unrealized_net', 'realized_net', 'quantity_held')

@admin.register(Flip)
class FlipAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'quantity', 'price', 'type', 'date')
    list_filter = ('type', 'date')
    search_fields = ('item_name',)


@admin.register(FlipJournal)
class FlipJournalAdmin(admin.ModelAdmin):
    list_display = ('user', 'item_name', 'confidence', 'strategy', 'updated_at')
    list_filter = ('confidence', 'updated_at')
    search_fields = ('item_name', 'user__username')


@admin.register(FlipJournalStrategy)
class FlipJournalStrategyAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'updated_at')
    search_fields = ('title', 'user__username')


@admin.register(FlipJournalTag)
class FlipJournalTagAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'created_at')
    search_fields = ('name', 'user__username')


@admin.register(FlipJournalNote)
class FlipJournalNoteAdmin(admin.ModelAdmin):
    list_display = ('journal', 'created_at', 'updated_at')
    list_filter = ('created_at',)


@admin.register(FlipJournalExit)
class FlipJournalExitAdmin(admin.ModelAdmin):
    list_display = ('journal', 'sell_flip', 'updated_at')
    search_fields = ('journal__item_name',)


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

@admin.register(FiveMinTimeSeries)
class FiveMinTimeSeriesAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'avg_low_price', 'avg_high_price', 'high_price_volume',
                    'low_price_volume', 'timestamp')

@admin.register(OneHourTimeSeries)
class OneHourTimeSeriesAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'avg_low_price', 'avg_high_price', 'high_price_volume',
                    'low_price_volume', 'timestamp')

@admin.register(SixHourTimeSeries)
class SixHourTimeSeriesAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'avg_low_price', 'avg_high_price', 'high_price_volume',
                    'low_price_volume', 'timestamp')

@admin.register(TwentyFourHourTimeSeries)
class TwentyFourHourTimeSeriesAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'item_name', 'avg_low_price', 'avg_high_price', 'high_price_volume',
                    'low_price_volume', 'timestamp')


@admin.register(AllTimeData)
class AllTimeDataAdmin(admin.ModelAdmin):
    """Expose all-time Flip Finder snapshots for spot checks and cleanup."""

    list_display = ('item_id', 'item_name', 'item_price', 'timestamp', 'volume')
    search_fields = ('item_name', 'item_id')
    list_filter = ('timestamp',)

@admin.register(FlipAlert)
class FlipAlertAdmin(admin.ModelAdmin):
    """Expose all-time Flip Finder snapshots for spot checks and cleanup."""

    list_display = ('user', 'tracked_items', 'triggered_items')

