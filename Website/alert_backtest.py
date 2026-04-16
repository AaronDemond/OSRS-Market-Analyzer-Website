import copy
import heapq
import json
import os
import types
from bisect import bisect_right
from datetime import datetime, timezone as dt_timezone
from functools import lru_cache
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.db.models import BigIntegerField, F, OuterRef, Subquery
from django.db.models.functions import Cast
from django.utils import timezone

from .management.commands.check_alerts import Command as AlertReplayCommand
from .models import (
    FiveMinTimeSeries,
    HourlyItemVolume,
    OneHourTimeSeries,
    SixHourTimeSeries,
    TwentyFourHourTimeSeries,
)


VOLUME_RECENCY_MINUTES = 130

TIMESTEP_TO_MODEL = {
    '5m': FiveMinTimeSeries,
    '1h': OneHourTimeSeries,
    '6h': SixHourTimeSeries,
    '24h': TwentyFourHourTimeSeries,
}

MODEL_TO_BUCKET_SECONDS = {
    FiveMinTimeSeries: 5 * 60,
    OneHourTimeSeries: 60 * 60,
    SixHourTimeSeries: 6 * 60 * 60,
    TwentyFourHourTimeSeries: 24 * 60 * 60,
}

SPREAD_PRICE_MODELS = [
    FiveMinTimeSeries,
    OneHourTimeSeries,
    SixHourTimeSeries,
    TwentyFourHourTimeSeries,
]

SPREAD_MODEL_FRESHNESS_SECONDS = {
    FiveMinTimeSeries: 15 * 60,
    OneHourTimeSeries: 2 * 60 * 60,
    SixHourTimeSeries: 8 * 60 * 60,
    TwentyFourHourTimeSeries: 30 * 60 * 60,
}

VOLUME_FRESHNESS_SECONDS = VOLUME_RECENCY_MINUTES * 60


@lru_cache(maxsize=1)
def get_local_item_name_mapping():
    mapping_path = os.path.join(settings.BASE_DIR, 'Website', 'static', 'item-mapping.json')
    if not os.path.exists(mapping_path):
        return {}

    try:
        with open(mapping_path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return {str(item.get('id')): item.get('name') for item in data if item.get('id') is not None}


def _noop_save(self, *args, **kwargs):
    return None


def clone_alert_for_backtest(alert):
    clone = copy.copy(alert)
    clone.save = types.MethodType(_noop_save, clone)
    clone.is_triggered = False
    clone.is_dismissed = False
    clone.triggered_data = None
    clone.triggered_at = None
    clone.email_notification = False
    clone.confidence_last_scores = None
    clone.dump_state = None
    clone.pk = alert.pk

    # Single-item dump alerts only return True/False in the live checker.
    # Treat them as a one-item list during backtests so the detail page can render
    # the same payload shape it expects for dump results.
    if clone.type == 'dump' and clone.item_id and not clone.item_ids and not clone.is_all_items:
        clone.item_ids = json.dumps([clone.item_id])

    return clone


def serialize_triggered_data(alert_type, result, alert):
    if isinstance(result, list):
        return json.dumps(result)

    if alert.triggered_data:
        return alert.triggered_data

    if alert_type == 'spread' and alert.item_id:
        return None

    return None


class SpreadBacktestRunner:
    def __init__(self, alert, from_timestamp):
        self.alert = alert
        self.from_timestamp = int(from_timestamp)
        self.item_mapping = get_local_item_name_mapping()

    def with_numeric_timestamp(self, queryset):
        return queryset.annotate(ts_int=Cast('timestamp', BigIntegerField()))

    def _timestamp_key(self, timestamp):
        return str(int(timestamp))

    def _latest_rows_at_or_before(self, model, timestamp, monitored_item_ids, value_fields):
        timestamp_key = self._timestamp_key(timestamp)
        queryset = model.objects.filter(timestamp__lte=timestamp_key)
        if monitored_item_ids is not None:
            queryset = queryset.filter(item_id__in=monitored_item_ids)

        if connection.vendor == 'postgresql':
            return queryset.order_by('item_id', '-timestamp').distinct('item_id').values(
                'item_id',
                'item_name',
                *value_fields,
                'timestamp',
            )

        latest_ts_subquery = model.objects.filter(
            item_id=OuterRef('item_id'),
            timestamp__lte=timestamp_key,
        )
        if monitored_item_ids is not None:
            latest_ts_subquery = latest_ts_subquery.filter(item_id__in=monitored_item_ids)

        latest_ts_subquery = latest_ts_subquery.order_by('-timestamp').values('timestamp')[:1]

        return queryset.annotate(
            latest_before_ts=Subquery(latest_ts_subquery)
        ).filter(
            timestamp=F('latest_before_ts')
        ).values(
            'item_id',
            'item_name',
            *value_fields,
            'timestamp',
        )

    def _latest_side_rows_at_or_before(self, model, timestamp, monitored_item_ids, side_field):
        timestamp_key = self._timestamp_key(timestamp)
        queryset = model.objects.filter(
            timestamp__lte=timestamp_key,
            **{f'{side_field}__isnull': False},
        )
        if monitored_item_ids is not None:
            queryset = queryset.filter(item_id__in=monitored_item_ids)

        if connection.vendor == 'postgresql':
            return queryset.order_by('item_id', '-timestamp').distinct('item_id').values(
                'item_id',
                'item_name',
                side_field,
                'timestamp',
            )

        latest_ts_subquery = model.objects.filter(
            item_id=OuterRef('item_id'),
            timestamp__lte=timestamp_key,
            **{f'{side_field}__isnull': False},
        )
        if monitored_item_ids is not None:
            latest_ts_subquery = latest_ts_subquery.filter(item_id__in=monitored_item_ids)

        latest_ts_subquery = latest_ts_subquery.order_by('-timestamp').values('timestamp')[:1]

        return queryset.annotate(
            latest_before_ts=Subquery(latest_ts_subquery)
        ).filter(
            timestamp=F('latest_before_ts')
        ).values(
            'item_id',
            'item_name',
            side_field,
            'timestamp',
        )

    def _iter_unix_rows(self, queryset, value_fields):
        for row in queryset.values('timestamp', *value_fields).iterator(chunk_size=5000):
            raw_timestamp = row.pop('timestamp', None)
            try:
                row['ts_int'] = int(raw_timestamp)
            except (TypeError, ValueError):
                continue
            yield row

    def _default_item_state(self, item_id, item_name=None):
        return {
            'item_id': item_id,
            'item_name': item_name or self.item_mapping.get(item_id, f'Item {item_id}'),
            'high_sources': {},
            'low_sources': {},
            'volume': None,
            'volume_ts': None,
            'volume_freshness_seconds': VOLUME_FRESHNESS_SECONDS,
        }

    def _get_or_create_item_state(self, current_state, item_id, item_name=None):
        item_state = current_state.get(item_id)
        if item_state is None:
            item_state = self._default_item_state(item_id, item_name=item_name)
            current_state[item_id] = item_state
        elif item_name:
            item_state['item_name'] = item_name
        return item_state

    def _set_price_source(self, item_state, state_key, model, value, timestamp):
        if value is None:
            return
        item_state[f'{state_key}_sources'][model.__name__] = {
            'value': value,
            'ts': int(timestamp),
            'freshness_seconds': SPREAD_MODEL_FRESHNESS_SECONDS[model],
        }

    def _resolve_price_side(self, item_state, state_key, evaluation_timestamp):
        freshest_source = None
        for source in item_state.get(f'{state_key}_sources', {}).values():
            age = int(evaluation_timestamp) - source['ts']
            if age < 0 or age > source['freshness_seconds']:
                continue
            if freshest_source is None or source['ts'] > freshest_source['ts']:
                freshest_source = source
        return freshest_source['value'] if freshest_source else None

    def _resolve_volume(self, item_state, evaluation_timestamp):
        volume = item_state.get('volume')
        volume_ts = item_state.get('volume_ts')
        freshness_seconds = item_state.get('volume_freshness_seconds', VOLUME_FRESHNESS_SECONDS)
        if volume is None or volume_ts is None:
            return None
        age = int(evaluation_timestamp) - int(volume_ts)
        if age < 0 or age > freshness_seconds:
            return None
        return volume

    def get_monitored_item_ids(self):
        if self.alert.is_all_items:
            return None

        if self.alert.item_ids:
            try:
                item_ids = json.loads(self.alert.item_ids)
                if isinstance(item_ids, list):
                    return item_ids
            except (TypeError, ValueError, json.JSONDecodeError):
                return []

        if self.alert.item_id:
            return [self.alert.item_id]

        return []

    def get_initial_price_state(self, monitored_item_ids):
        state = {}
        for side_field, state_key in (
            ('avg_high_price', 'high'),
            ('avg_low_price', 'low'),
        ):
            for model in SPREAD_PRICE_MODELS:
                for row in self._latest_side_rows_at_or_before(
                    model,
                    self.from_timestamp,
                    monitored_item_ids,
                    side_field,
                ):
                    item_id = str(row['item_id'])
                    row_timestamp = int(row['timestamp'])
                    if self.from_timestamp - row_timestamp > SPREAD_MODEL_FRESHNESS_SECONDS[model]:
                        continue
                    item_state = self._get_or_create_item_state(
                        state,
                        item_id,
                        item_name=row['item_name'],
                    )
                    self._set_price_source(item_state, state_key, model, row[side_field], row_timestamp)
        return state

    def get_initial_volume_state(self, monitored_item_ids):
        return {
            str(row['item_id']): {
                'item_name': row['item_name'],
                'volume': row['volume'],
                'timestamp': int(row['timestamp']),
            }
            for row in self._latest_rows_at_or_before(
                HourlyItemVolume,
                self.from_timestamp,
                monitored_item_ids,
                ('volume',),
            )
            if self.from_timestamp - int(row['timestamp']) <= VOLUME_FRESHNESS_SECONDS
        }

    def build_initial_state(self):
        monitored_item_ids = self.get_monitored_item_ids()
        current_state = self.get_initial_price_state(monitored_item_ids)
        for item_id, volume_state in self.get_initial_volume_state(monitored_item_ids).items():
            item_state = self._get_or_create_item_state(
                current_state,
                item_id,
                item_name=volume_state.get('item_name'),
            )
            item_state['volume'] = volume_state.get('volume')
            item_state['volume_ts'] = volume_state.get('timestamp')
            item_state['volume_freshness_seconds'] = VOLUME_FRESHNESS_SECONDS
        return current_state, monitored_item_ids

    def evaluate_item(self, item_state, evaluation_timestamp):
        high = self._resolve_price_side(item_state, 'high', evaluation_timestamp)
        low = self._resolve_price_side(item_state, 'low', evaluation_timestamp)
        if high is None or low is None or low <= 0:
            return None

        if self.alert.minimum_price is not None and (high < self.alert.minimum_price or low < self.alert.minimum_price):
            return None

        if self.alert.maximum_price is not None and (high > self.alert.maximum_price or low > self.alert.maximum_price):
            return None

        spread = ((high - low) / low) * 100
        if spread < (self.alert.percentage or 0):
            return None

        if self.alert.min_volume:
            volume = self._resolve_volume(item_state, evaluation_timestamp)
            if volume is None or volume < self.alert.min_volume:
                return None

        return {
            'item_id': item_state['item_id'],
            'item_name': item_state.get('item_name') or self.item_mapping.get(item_state['item_id'], f'Item {item_state["item_id"]}'),
            'high': high,
            'low': low,
            'spread': round(spread, 2),
        }

    def get_price_events(self, monitored_item_ids):
        iterators = []
        for model in SPREAD_PRICE_MODELS:
            queryset = model.objects.filter(
                timestamp__gt=self._timestamp_key(self.from_timestamp)
            ).order_by('timestamp', 'item_id')
            if monitored_item_ids is not None:
                queryset = queryset.filter(item_id__in=monitored_item_ids)
            iterators.append(
                iter(
                    (
                        dict(
                            row,
                            source_model=model,
                        )
                        for row in self._iter_unix_rows(
                            queryset,
                            ('item_id', 'item_name', 'avg_high_price', 'avg_low_price'),
                        )
                    )
                )
            )

        heap = []
        for index, iterator in enumerate(iterators):
            row = next(iterator, None)
            if row is not None:
                heapq.heappush(heap, (row['ts_int'], str(row['item_id']), index, row))

        while heap:
            _, _, index, row = heapq.heappop(heap)
            yield row
            next_row = next(iterators[index], None)
            if next_row is not None:
                heapq.heappush(heap, (next_row['ts_int'], str(next_row['item_id']), index, next_row))

    def get_volume_events(self, monitored_item_ids):
        queryset = HourlyItemVolume.objects.filter(
            timestamp__gt=self._timestamp_key(self.from_timestamp)
        ).order_by('timestamp', 'item_id')
        if monitored_item_ids is not None:
            queryset = queryset.filter(item_id__in=monitored_item_ids)
        return self._iter_unix_rows(
            queryset,
            ('item_id', 'item_name', 'volume'),
        )

    def merge_events(self, monitored_item_ids):
        price_iter = iter(self.get_price_events(monitored_item_ids))
        volume_iter = iter(self.get_volume_events(monitored_item_ids))
        bucket_seconds = MODEL_TO_BUCKET_SECONDS[FiveMinTimeSeries]

        next_price = next(price_iter, None)
        next_volume = next(volume_iter, None)

        while next_price is not None or next_volume is not None:
            if next_volume is None or (next_price is not None and next_price['ts_int'] <= next_volume['ts_int']):
                current_bucket = next_price['ts_int'] - (next_price['ts_int'] % bucket_seconds)
            else:
                current_bucket = next_volume['ts_int'] - (next_volume['ts_int'] % bucket_seconds)

            price_rows = []
            while next_price is not None:
                next_price_bucket = next_price['ts_int'] - (next_price['ts_int'] % bucket_seconds)
                if next_price_bucket != current_bucket:
                    break
                price_rows.append(next_price)
                next_price = next(price_iter, None)

            volume_rows = []
            while next_volume is not None:
                next_volume_bucket = next_volume['ts_int'] - (next_volume['ts_int'] % bucket_seconds)
                if next_volume_bucket != current_bucket:
                    break
                volume_rows.append(next_volume)
                next_volume = next(volume_iter, None)

            current_ts = max(
                [row['ts_int'] for row in price_rows] + [row['ts_int'] for row in volume_rows]
            )
            yield current_ts, price_rows, volume_rows

    def build_snapshot_price_data(self, qualifying_items):
        if not self.alert.item_id:
            return None

        matching_item = next((item for item in qualifying_items if item['item_id'] == str(self.alert.item_id)), None)
        if not matching_item:
            return None

        return {
            'high': matching_item['high'],
            'low': matching_item['low'],
        }

    def run(self):
        current_state, monitored_item_ids = self.build_initial_state()
        qualifying_items = {}

        for item_id, item_state in current_state.items():
            payload = self.evaluate_item(item_state, self.from_timestamp)
            if payload:
                qualifying_items[item_id] = payload

        if qualifying_items:
            sorted_items = sorted(qualifying_items.values(), key=lambda item: item['spread'], reverse=True)
            return {
                'found': True,
                'first_triggered_ts': self.from_timestamp,
                'triggered_data': json.dumps(sorted_items),
                'snapshot_price_data': self.build_snapshot_price_data(sorted_items),
            }

        for current_ts, price_rows, volume_rows in self.merge_events(monitored_item_ids):
            changed_item_ids = set()

            for row in price_rows:
                item_id = str(row['item_id'])
                item_state = self._get_or_create_item_state(
                    current_state,
                    item_id,
                    item_name=row['item_name'],
                )
                if row.get('avg_high_price') is not None:
                    self._set_price_source(item_state, 'high', row['source_model'], row['avg_high_price'], row['ts_int'])
                if row.get('avg_low_price') is not None:
                    self._set_price_source(item_state, 'low', row['source_model'], row['avg_low_price'], row['ts_int'])
                changed_item_ids.add(item_id)

            for row in volume_rows:
                item_id = str(row['item_id'])
                item_state = self._get_or_create_item_state(
                    current_state,
                    item_id,
                    item_name=row['item_name'],
                )
                item_state['volume'] = row['volume']
                item_state['volume_ts'] = row['ts_int']
                item_state['volume_freshness_seconds'] = VOLUME_FRESHNESS_SECONDS
                changed_item_ids.add(item_id)

            changed_item_ids.update(qualifying_items.keys())
            for item_id in changed_item_ids:
                payload = self.evaluate_item(current_state[item_id], current_ts)
                if payload:
                    qualifying_items[item_id] = payload
                else:
                    qualifying_items.pop(item_id, None)

            if qualifying_items:
                sorted_items = sorted(qualifying_items.values(), key=lambda item: item['spread'], reverse=True)
                return {
                    'found': True,
                    'first_triggered_ts': current_ts,
                    'triggered_data': json.dumps(sorted_items),
                    'snapshot_price_data': self.build_snapshot_price_data(sorted_items),
                }

        return {
            'found': False,
            'first_triggered_ts': None,
            'triggered_data': None,
            'snapshot_price_data': None,
        }


class AlertBacktestRunner:
    def __init__(self, alert, from_timestamp):
        self.alert = alert
        self.from_timestamp = int(from_timestamp)
        self.command = AlertReplayCommand()
        self.command.get_item_mapping = get_local_item_name_mapping
        self.command.send_alert_notification = lambda *args, **kwargs: None

        self.current_timestamp = None
        self._api_series_cache = {}
        self._api_series_timestamps = {}
        self._model_series_cache = {}
        self._model_series_timestamps = {}
        self._volume_cache = {}
        self._volume_timestamps = {}

        self.command.get_volume_from_timeseries = self._get_volume_from_timeseries_at_timestamp
        self.command.fetch_timeseries_from_db = self._fetch_timeseries_from_db_at_timestamp
        self.command._get_latest_5m_bucket = self._get_latest_5m_bucket_at_timestamp
        self.command._check_dump_consistency = self._check_dump_consistency_at_timestamp

    def run(self):
        working_alert = clone_alert_for_backtest(self.alert)

        for timestamp, all_prices in self.iter_price_snapshots():
            self.current_timestamp = timestamp
            with patch('Website.management.commands.check_alerts.time.time', return_value=timestamp):
                result = self.command.check_alert(working_alert, all_prices)

            if result:
                triggered_payload = serialize_triggered_data(working_alert.type, result, working_alert)
                return {
                    'found': True,
                    'first_triggered_ts': timestamp,
                    'triggered_data': triggered_payload,
                    'snapshot_price_data': all_prices.get(str(self.alert.item_id)) if self.alert.item_id else None,
                }

        return {
            'found': False,
            'first_triggered_ts': None,
            'triggered_data': None,
            'snapshot_price_data': None,
        }

    def iter_price_snapshots(self):
        model = self.get_primary_source_model()
        bucket_seconds = self.get_snapshot_bucket_seconds(model)
        monitored_item_ids = self.get_monitored_item_ids()
        current_prices = self.get_initial_price_state(model, monitored_item_ids)
        if current_prices:
            yield self.from_timestamp, dict(current_prices)

        queryset = self.with_numeric_timestamp(model.objects.all()).filter(ts_int__gt=self.from_timestamp)
        if monitored_item_ids is not None:
            queryset = queryset.filter(item_id__in=monitored_item_ids)

        rows = queryset.values(
            'ts_int',
            'item_id',
            'avg_high_price',
            'avg_low_price',
        ).order_by('ts_int', 'item_id').iterator(chunk_size=5000)

        current_bucket_ts = None
        current_snapshot_ts = None
        for row in rows:
            row_ts = row['ts_int']
            bucket_ts = self.normalize_snapshot_timestamp(row_ts, bucket_seconds)
            if current_bucket_ts is None:
                current_bucket_ts = bucket_ts
                current_snapshot_ts = row_ts

            if bucket_ts != current_bucket_ts:
                if current_prices:
                    yield current_snapshot_ts, current_prices
                current_bucket_ts = bucket_ts
                current_snapshot_ts = row_ts
                current_prices = {}
            elif current_snapshot_ts is None or row_ts > current_snapshot_ts:
                current_snapshot_ts = row_ts

            current_prices[str(row['item_id'])] = {
                'high': row['avg_high_price'],
                'low': row['avg_low_price'],
            }

        if current_bucket_ts is not None and current_prices:
            yield current_snapshot_ts, current_prices

    def get_primary_source_model(self):
        if self.alert.type == 'flip_confidence':
            return TIMESTEP_TO_MODEL.get(self.alert.confidence_timestep or '1h', OneHourTimeSeries)
        return FiveMinTimeSeries

    def get_monitored_item_ids(self):
        if self.alert.is_all_items:
            return None

        if self.alert.type == 'sustained' and self.alert.sustained_item_ids:
            try:
                item_ids = json.loads(self.alert.sustained_item_ids)
                if isinstance(item_ids, list):
                    return item_ids
            except (TypeError, ValueError, json.JSONDecodeError):
                return []

        if self.alert.item_ids:
            try:
                item_ids = json.loads(self.alert.item_ids)
                if isinstance(item_ids, list):
                    return item_ids
            except (TypeError, ValueError, json.JSONDecodeError):
                return []

        if self.alert.item_id:
            return [self.alert.item_id]

        return []

    def with_numeric_timestamp(self, queryset):
        return queryset.annotate(ts_int=Cast('timestamp', BigIntegerField()))

    def get_snapshot_bucket_seconds(self, model):
        return MODEL_TO_BUCKET_SECONDS.get(model, 5 * 60)

    def normalize_snapshot_timestamp(self, timestamp, bucket_seconds):
        if bucket_seconds <= 1:
            return int(timestamp)
        return int(timestamp) - (int(timestamp) % bucket_seconds)

    def get_initial_price_state(self, model, monitored_item_ids):
        scoped_queryset = model.objects.all()
        if monitored_item_ids is not None:
            scoped_queryset = scoped_queryset.filter(item_id__in=monitored_item_ids)

        latest_ts_subquery = self.with_numeric_timestamp(
            model.objects.filter(item_id=OuterRef('item_id'))
        ).filter(ts_int__lte=self.from_timestamp)
        if monitored_item_ids is not None:
            latest_ts_subquery = latest_ts_subquery.filter(item_id__in=monitored_item_ids)

        latest_ts_subquery = latest_ts_subquery.order_by('-ts_int').values('ts_int')[:1]

        starting_rows = self.with_numeric_timestamp(scoped_queryset).annotate(
            latest_before_ts=Subquery(latest_ts_subquery)
        ).filter(
            ts_int=F('latest_before_ts')
        ).values(
            'item_id',
            'avg_high_price',
            'avg_low_price',
        )

        return {
            str(row['item_id']): {
                'high': row['avg_high_price'],
                'low': row['avg_low_price'],
            }
            for row in starting_rows
        }

    def _get_volume_from_timeseries_at_timestamp(self, item_id, time_window_minutes):
        history = self._get_volume_history(item_id)
        if not history or self.current_timestamp is None:
            return None

        timestamps = self._volume_timestamps[int(item_id)]
        index = bisect_right(timestamps, self.current_timestamp) - 1
        if index < 0:
            return None

        row = history[index]
        if self.current_timestamp - row['ts_int'] > VOLUME_RECENCY_MINUTES * 60:
            return None

        return row['volume']

    def _fetch_timeseries_from_db_at_timestamp(self, item_id, timestep, lookback_count):
        model = TIMESTEP_TO_MODEL.get(timestep)
        if model is None or self.current_timestamp is None:
            return []

        history = self._get_api_series(model, item_id)
        if not history:
            return []

        timestamps = self._api_series_timestamps[(model.__name__, int(item_id))]
        end_index = bisect_right(timestamps, self.current_timestamp)
        if end_index <= 0:
            return []

        selected = history[max(0, end_index - lookback_count):end_index]
        return [
            {
                'avgHighPrice': row['avgHighPrice'],
                'avgLowPrice': row['avgLowPrice'],
                'highPriceVolume': row['highPriceVolume'],
                'lowPriceVolume': row['lowPriceVolume'],
                'timestamp': row['ts_int'],
            }
            for row in selected
        ]

    def _get_latest_5m_bucket_at_timestamp(self, item_id):
        history = self._get_model_series(FiveMinTimeSeries, item_id)
        if not history or self.current_timestamp is None:
            return None

        timestamps = self._model_series_timestamps[(FiveMinTimeSeries.__name__, int(item_id))]
        index = bisect_right(timestamps, self.current_timestamp) - 1
        if index < 0:
            return None
        return history[index]

    def _check_dump_consistency_at_timestamp(self, item_id):
        history = self._get_model_series(FiveMinTimeSeries, item_id)
        if not history or self.current_timestamp is None:
            return False

        timestamps = self._model_series_timestamps[(FiveMinTimeSeries.__name__, int(item_id))]
        end_index = bisect_right(timestamps, self.current_timestamp)
        if end_index <= 0:
            return False

        recent_buckets = history[max(0, end_index - 12):end_index]
        both_side_count = sum(
            1
            for bucket in recent_buckets
            if (bucket.high_price_volume or 0) > 0 and (bucket.low_price_volume or 0) > 0
        )
        return both_side_count >= 6

    def _get_volume_history(self, item_id):
        item_id_int = int(item_id)
        if item_id_int in self._volume_cache:
            return self._volume_cache[item_id_int]

        queryset = self.with_numeric_timestamp(
            HourlyItemVolume.objects.filter(item_id=item_id_int)
        ).order_by('ts_int').values('ts_int', 'volume')

        rows = list(queryset)
        self._volume_cache[item_id_int] = rows
        self._volume_timestamps[item_id_int] = [row['ts_int'] for row in rows]
        return rows

    def _get_api_series(self, model, item_id):
        item_id_int = int(item_id)
        cache_key = (model.__name__, item_id_int)
        if cache_key in self._api_series_cache:
            return self._api_series_cache[cache_key]

        queryset = self.with_numeric_timestamp(
            model.objects.filter(item_id=item_id_int)
        ).order_by('ts_int').values(
            'ts_int',
            'avg_high_price',
            'avg_low_price',
            'high_price_volume',
            'low_price_volume',
        )

        rows = [
            {
                'ts_int': row['ts_int'],
                'avgHighPrice': row['avg_high_price'],
                'avgLowPrice': row['avg_low_price'],
                'highPriceVolume': row['high_price_volume'],
                'lowPriceVolume': row['low_price_volume'],
            }
            for row in queryset
        ]
        self._api_series_cache[cache_key] = rows
        self._api_series_timestamps[cache_key] = [row['ts_int'] for row in rows]
        return rows

    def _get_model_series(self, model, item_id):
        item_id_int = int(item_id)
        cache_key = (model.__name__, item_id_int)
        if cache_key in self._model_series_cache:
            return self._model_series_cache[cache_key]

        queryset = self.with_numeric_timestamp(model.objects.filter(item_id=item_id_int)).order_by('ts_int')
        rows = list(queryset)
        self._model_series_cache[cache_key] = rows
        self._model_series_timestamps[cache_key] = [row.ts_int for row in rows]
        return rows


def backtest_alert(alert, from_timestamp):
    if alert.type == 'spread':
        return SpreadBacktestRunner(alert, from_timestamp).run()
    runner = AlertBacktestRunner(alert, from_timestamp)
    return runner.run()


def backtest_alerts(alerts, from_timestamp):
    results = {}
    for alert in alerts:
        results[alert.id] = backtest_alert(alert, from_timestamp)
    return results


def unix_to_aware_datetime(timestamp):
    return datetime_from_unix(timestamp) if timestamp is not None else None


def datetime_from_unix(timestamp):
    return datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
