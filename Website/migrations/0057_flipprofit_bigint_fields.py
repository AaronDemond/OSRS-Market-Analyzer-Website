from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Website', '0056_alter_alert_is_active_alter_alert_type_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flipprofit',
            name='quantity_held',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='flipprofit',
            name='realized_net',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='flipprofit',
            name='unrealized_net',
            field=models.BigIntegerField(default=0),
        ),
    ]