from django.db import migrations, models


class Migration(migrations.Migration):
    # Adds an optional all-time volume column. Existing imports leave this blank
    # until a trustworthy all-time volume source is available.

    dependencies = [
        ('Website', '0058_alltimedata_twentyfour_price_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='alltimedata',
            name='volume',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
