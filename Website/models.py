from django.db import models


class Flip(models.Model):
    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    price_bought = models.IntegerField(null=True, blank=True)
    date = models.DateTimeField()
    quantity = models.IntegerField()
    price_sold = models.IntegerField(null=True, blank=True)
    is_buy = models.BooleanField(default=False)
    is_sell = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"
