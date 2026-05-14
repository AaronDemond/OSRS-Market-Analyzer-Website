from django.db import migrations, models


class Migration(migrations.Migration):
    # This migration adds the persistent all-time source used by Flip Finder and
    # indexes the existing 24h table for the low/high comparisons that power the
    # bounded timeframe filters. No data is backfilled here; ingestion is a
    # separate operational step.

    dependencies = [
        ('Website', '0057_flipprofit_bigint_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='AllTimeData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_id', models.IntegerField(db_index=True)),
                ('item_name', models.CharField(max_length=255)),
                ('item_price', models.BigIntegerField()),
                ('timestamp', models.BigIntegerField()),
            ],
            options={
                'ordering': ['-timestamp', 'item_name'],
                'indexes': [
                    models.Index(fields=['item_id', 'item_price'], name='alltime_item_price_idx'),
                    models.Index(fields=['item_id', '-timestamp'], name='alltime_item_ts_desc'),
                    models.Index(fields=['timestamp'], name='alltime_ts_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=('item_id', 'timestamp'), name='uniq_all_time_item_ts'),
                ],
            },
        ),
        migrations.AddIndex(
            model_name='twentyfourhourtimeseries',
            index=models.Index(fields=['item_id', 'avg_low_price'], name='twentyfour_item_low_idx'),
        ),
        migrations.AddIndex(
            model_name='twentyfourhourtimeseries',
            index=models.Index(fields=['item_id', 'avg_high_price'], name='twentyfour_item_high_idx'),
        ),
    ]
