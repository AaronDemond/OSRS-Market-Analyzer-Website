from django.contrib import admin
from .models import Flip


@admin.register(Flip)
class FlipAdmin(admin.ModelAdmin):
    list_display = ('item_name', 'quantity', 'price', 'type', 'date')
    list_filter = ('type', 'date')
    search_fields = ('item_name',)
