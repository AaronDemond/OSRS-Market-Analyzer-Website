from django.contrib import admin
from .models import Flip, Alert, AlertGroup


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
