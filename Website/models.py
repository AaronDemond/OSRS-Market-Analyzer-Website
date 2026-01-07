from django.db import models


class Flip(models.Model):
    TYPE_CHOICES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]

    item_id = models.IntegerField()
    item_name = models.CharField(max_length=255)
    price = models.IntegerField()
    date = models.DateTimeField()
    quantity = models.IntegerField()
    type = models.CharField(max_length=4, choices=TYPE_CHOICES)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"
