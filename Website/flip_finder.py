"""
Backend helpers for the Flip Finder page.

What: Build result-table and chart-history payloads from local database tables.
Why: The Flip Finder should compare items against historical lows/highs without
    calling the OSRS Wiki price API during page interaction.
How: Use TwentyFourHourTimeSeries for bounded timeframes and AllTimeData for
    the all-time range, then normalize both sources into the same API shape.
"""

from datetime import datetime, timezone

from django.db import connection
from django.db.models import F, Max, Min, Window
from django.db.models.functions import RowNumber

from .models import AllTimeData, TwentyFourHourTimeSeries


FLIP_FINDER_RESULT_LIMIT = 50
# The 24h table stores one point per day, so 430 snapshots comfortably covers a
# one-year range plus gaps without scanning every distinct timestamp ever saved.
FLIP_FINDER_TIMESTAMP_SEARCH_LIMIT = 430
FLIP_FINDER_DEFAULT_TIMEFRAME = '24h'
# Supported bounded ranges are expressed in seconds so stale local datasets can
# be anchored to their latest stored snapshot instead of wall-clock "now".
FLIP_FINDER_TIMEFRAME_SECONDS = {
    '24h': 24 * 60 * 60,
    '7d': 7 * 24 * 60 * 60,
    '30d': 30 * 24 * 60 * 60,
    '90d': 90 * 24 * 60 * 60,
    '1y': 365 * 24 * 60 * 60,
}
FLIP_FINDER_SUPPORTED_TIMEFRAMES = set(FLIP_FINDER_TIMEFRAME_SECONDS) | {'all', 'custom'}
FLIP_FINDER_SUPPORTED_SIGNALS = {'low', 'high', 'both'}
FLIP_FINDER_SUPPORTED_SORTS = {'closest', 'name', 'signal', 'low', 'high', 'current', 'volume'}
FLIP_FINDER_SUPPORTED_DIRECTIONS = {'asc', 'desc'}
FLIP_FINDER_MAX_MIN_PRICE = 2_147_483_647
FLIP_FINDER_MAX_MIN_VOLUME = 9_000_000_000_000_000


class FlipFinderParamError(ValueError):
    """Raised when request parameters would produce an ambiguous API query."""


def build_flip_finder_results(query_params, metadata_by_id=None):
    """
    Build the complete results payload for the Flip Finder table.

    What: Validate query params, choose the correct data source, compute each
          item's current price, period low/high, signal, sort order, and counts.
    Why: Keeping this in a small service module makes the Django view thin and
         lets tests exercise the market logic without rendering templates.
    How: Normalize all supported sources into summary dictionaries, then pass
         them through the same distance and signal calculation pipeline.
    """
    params = _normalize_result_params(query_params)
    metadata_by_id = metadata_by_id or {}

    if params['timeframe'] in {'all', 'custom'}:
        # All-time rows already use numeric timestamps and a single item_price.
        # Custom ranges reuse that source so arbitrary start dates are not
        # limited by the bounded 24h snapshot window.
        summaries = _get_all_time_summaries(params)
        updated_timestamp = max(
            (summary['current_timestamp'] for summary in summaries if summary['current_timestamp'] is not None),
            default=None,
        )
        return _build_results_payload(
            summaries=summaries,
            params=params,
            metadata_by_id=metadata_by_id,
            source='all_time_data',
            price_basis='item_price',
            range_start=params['custom_start_timestamp'],
            range_end=updated_timestamp,
        )

    # Bounded ranges use the 24h model and midpoint pricing. The helper returns
    # raw CharField timestamps plus parsed ints so filtering and metadata stay
    # consistent with the existing table shape.
    timestamp_pairs = _get_twentyfour_timestamp_pairs(params['timeframe'])
    if not timestamp_pairs:
        return _empty_results_payload(
            params=params,
            source='twenty_four_hour_time_series',
            price_basis='midpoint',
            range_start=None,
            range_end=None,
        )

    summaries = _get_twentyfour_summaries(params, timestamp_pairs)
    parsed_timestamps = [parsed_timestamp for _, parsed_timestamp in timestamp_pairs]
    return _build_results_payload(
        summaries=summaries,
        params=params,
        metadata_by_id=metadata_by_id,
        source='twenty_four_hour_time_series',
        price_basis='midpoint',
        range_start=min(parsed_timestamps),
        range_end=max(parsed_timestamps),
    )


def build_flip_finder_history(query_params):
    """
    Build chart history for one item and one selected timeframe.

    What: Return ascending price points plus period low/high metadata.
    Why: The selected-item chart should be driven by the same local source and
        timeframe semantics as the result table.
    How: Query all-time prices directly for `all`, otherwise restrict 24h rows
        to the anchored timestamp window used by result calculations.
    """
    params = _normalize_history_params(query_params)
    item_id = params['item_id']

    if params['timeframe'] in {'all', 'custom'}:
        # All-time history is intentionally unbounded, but the database can drop
        # non-positive prices before Chart.js ever sees them.
        rows_query = AllTimeData.objects.filter(item_id=item_id, item_price__gt=0)
        if params['custom_start_timestamp'] is not None:
            rows_query = rows_query.filter(timestamp__gte=params['custom_start_timestamp'])

        rows = list(
            rows_query
            .order_by('timestamp')
            .values('item_id', 'item_name', 'item_price', 'timestamp')
        )
        points = [
            _serialize_history_point(row['timestamp'], row['item_price'])
            for row in rows
        ]
        item_name = rows[-1]['item_name'] if rows else None
        return _build_history_payload(
            item_id=item_id,
            item_name=item_name,
            timeframe=params['timeframe'],
            points=points,
            source='all_time_data',
            price_basis='item_price',
        )

    # For bounded timeframes, reuse the same timestamp selection logic as the
    # result endpoint so table distances and chart extrema agree.
    timestamp_pairs = _get_twentyfour_timestamp_pairs(params['timeframe'])
    timestamp_values = [raw_timestamp for raw_timestamp, _ in timestamp_pairs]
    rows = list(
        TwentyFourHourTimeSeries.objects
        .filter(item_id=item_id, timestamp__in=timestamp_values)
        .values('item_id', 'item_name', 'avg_high_price', 'avg_low_price', 'timestamp')
    )
    rows_with_price = []
    for row in rows:
        parsed_timestamp = parse_snapshot_timestamp(row['timestamp'])
        price = _twentyfour_midpoint(row)
        if parsed_timestamp is None or price is None:
            continue
        rows_with_price.append((parsed_timestamp, row['item_name'], price))

    rows_with_price.sort(key=lambda item: item[0])
    points = [
        _serialize_history_point(parsed_timestamp, price)
        for parsed_timestamp, _, price in rows_with_price
    ]
    item_name = rows_with_price[-1][1] if rows_with_price else None
    return _build_history_payload(
        item_id=item_id,
        item_name=item_name,
        timeframe=params['timeframe'],
        points=points,
        source='twenty_four_hour_time_series',
        price_basis='midpoint',
    )


def parse_snapshot_timestamp(raw_timestamp):
    """
    Convert stored snapshot values into integer Unix timestamps.

    What: Safely parse the CharField timestamps used by existing time-series
          models.
    Why: Range math requires numeric timestamps, but ingestion may leave bad or
         blank values behind.
    How: Strip and cast values to int, returning None when a row is unusable.
    """
    try:
        return int(str(raw_timestamp).strip())
    except (TypeError, ValueError):
        return None


def _normalize_result_params(query_params):
    """Validate and normalize result-table query parameters."""
    timeframe = _clean_query_value(query_params.get('timeframe'), FLIP_FINDER_DEFAULT_TIMEFRAME).lower()
    if timeframe not in FLIP_FINDER_SUPPORTED_TIMEFRAMES:
        raise FlipFinderParamError(f'Unsupported timeframe: {timeframe}')

    signal = _clean_query_value(query_params.get('signal'), 'low').lower()
    if signal not in FLIP_FINDER_SUPPORTED_SIGNALS:
        raise FlipFinderParamError(f'Unsupported signal: {signal}')

    sort_key = _clean_query_value(query_params.get('sort'), 'closest').lower()
    if sort_key not in FLIP_FINDER_SUPPORTED_SORTS:
        raise FlipFinderParamError(f'Unsupported sort: {sort_key}')

    sort_direction = _clean_query_value(query_params.get('sortDirection'), 'asc').lower()
    if sort_direction not in FLIP_FINDER_SUPPORTED_DIRECTIONS:
        raise FlipFinderParamError(f'Unsupported sort direction: {sort_direction}')

    return {
        'timeframe': timeframe,
        'custom_start_timestamp': _normalize_custom_start_timestamp(
            timeframe,
            _get_query_alias(query_params, 'customDate', 'custom_date', 'customStartDate', 'custom_start_date'),
        ),
        'percent': _normalize_percent(query_params.get('percent')),
        'signal': signal,
        'search': _clean_query_value(query_params.get('search'), '').strip(),
        'sort': sort_key,
        'sortDirection': sort_direction,
        'page': _normalize_page(query_params.get('page')),
        'min_price': _normalize_minimum_integer(
            _get_query_alias(query_params, 'minPrice', 'min_price'),
            FLIP_FINDER_MAX_MIN_PRICE,
        ),
        'min_volume': _normalize_minimum_integer(
            _get_query_alias(query_params, 'minVolume', 'min_volume'),
            FLIP_FINDER_MAX_MIN_VOLUME,
        ),
    }


def _normalize_history_params(query_params):
    """Validate the selected item and timeframe for chart-history requests."""
    timeframe = _clean_query_value(query_params.get('timeframe'), FLIP_FINDER_DEFAULT_TIMEFRAME).lower()
    if timeframe not in FLIP_FINDER_SUPPORTED_TIMEFRAMES:
        raise FlipFinderParamError(f'Unsupported timeframe: {timeframe}')

    raw_item_id = query_params.get('itemId') or query_params.get('item_id')
    try:
        item_id = int(raw_item_id)
    except (TypeError, ValueError):
        raise FlipFinderParamError('A valid itemId is required')

    return {
        'timeframe': timeframe,
        'custom_start_timestamp': _normalize_custom_start_timestamp(
            timeframe,
            _get_query_alias(query_params, 'customDate', 'custom_date', 'customStartDate', 'custom_start_date'),
        ),
        'item_id': item_id,
    }


def _clean_query_value(value, fallback):
    """Return a stripped query value, falling back when it is missing or blank."""
    if value is None:
        return fallback
    return str(value).strip() or fallback


def _get_query_alias(query_params, *names):
    """Read the first non-blank value from a set of supported query names."""
    for name in names:
        value = query_params.get(name)
        if value is not None and str(value).strip():
            return value
    return None


def _normalize_percent(raw_percent):
    """
    Normalize the percentage threshold used for near-low/near-high matching.

    The clamp mirrors the UI control range so manually edited query strings
    cannot request a negative or overly broad comparison window.
    """
    try:
        percent = float(raw_percent)
    except (TypeError, ValueError):
        return 5.0
    return max(0.1, min(25.0, percent))


def _normalize_minimum_integer(raw_value, max_value):
    """Clamp optional minimum filter values so bad query strings stay harmless."""
    if raw_value is None:
        return 0
    try:
        raw_text = str(raw_value).strip()
        normalized_value = int(raw_text) if raw_text.isdecimal() else int(float(raw_text))
    except (TypeError, ValueError):
        return 0
    return max(0, min(max_value, normalized_value))


def _normalize_page(raw_page):
    """Return a one-based results page number for paginated table requests."""
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return 1
    return max(1, page)


def _normalize_custom_start_timestamp(timeframe, raw_value):
    """Return the UTC start timestamp for a custom date range."""
    if timeframe != 'custom':
        return None

    raw_text = str(raw_value).strip() if raw_value is not None else ''
    if not raw_text:
        raise FlipFinderParamError('A valid customDate is required for custom timeframe')

    numeric_timestamp = parse_snapshot_timestamp(raw_text)
    if numeric_timestamp is not None:
        return numeric_timestamp

    try:
        parsed_datetime = datetime.fromisoformat(raw_text.replace('Z', '+00:00'))
    except ValueError:
        raise FlipFinderParamError('A valid customDate is required for custom timeframe')

    if parsed_datetime.tzinfo is None:
        parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
    else:
        parsed_datetime = parsed_datetime.astimezone(timezone.utc)
    return int(parsed_datetime.timestamp())


def _get_twentyfour_timestamp_pairs(timeframe):
    """
    Select the stored 24h timestamps that belong to a requested timeframe.

    What: Return pairs of (raw CharField timestamp, parsed integer timestamp).
    Why: The database field is text, but timeframe comparisons need arithmetic.
    How: Parse recent distinct snapshots, anchor the window to the newest valid
         snapshot, and keep only timestamps inside the requested lookback.
    """
    recent_timestamps = list(
        TwentyFourHourTimeSeries.objects
        .values_list('timestamp', flat=True)
        .order_by('-timestamp')
        .distinct()[:FLIP_FINDER_TIMESTAMP_SEARCH_LIMIT]
    )

    timestamp_pairs = []
    seen_values = set()
    for raw_timestamp in recent_timestamps:
        parsed_timestamp = parse_snapshot_timestamp(raw_timestamp)
        if parsed_timestamp is None or parsed_timestamp in seen_values:
            continue
        timestamp_pairs.append((raw_timestamp, parsed_timestamp))
        seen_values.add(parsed_timestamp)

    timestamp_pairs.sort(key=lambda item: item[1], reverse=True)
    if not timestamp_pairs:
        return []

    latest_timestamp = timestamp_pairs[0][1]
    earliest_timestamp = latest_timestamp - FLIP_FINDER_TIMEFRAME_SECONDS[timeframe]
    return [
        (raw_timestamp, parsed_timestamp)
        for raw_timestamp, parsed_timestamp in timestamp_pairs
        if parsed_timestamp >= earliest_timestamp
    ]


def _get_twentyfour_summaries(params, timestamp_pairs):
    """
    Summarize bounded timeframe data into one comparison row per item.

    What: Compute latest/current price, period low, period high, and latest
          24h traded GP volume for each item in the selected window.
    Why: The result table needs per-item extrema, not one row per snapshot.
    How: Iterate the filtered rows once and update each item's summary as newer
         snapshots or new price extrema are encountered.
    """
    timestamp_values = [raw_timestamp for raw_timestamp, _ in timestamp_pairs]
    rows = (
        TwentyFourHourTimeSeries.objects
        .filter(timestamp__in=timestamp_values)
        .values(
            'item_id',
            'item_name',
            'avg_high_price',
            'avg_low_price',
            'high_price_volume',
            'low_price_volume',
            'timestamp',
        )
    )
    if params['search']:
        rows = rows.filter(item_name__icontains=params['search'])

    summaries_by_item = {}
    for row in rows:
        parsed_timestamp = parse_snapshot_timestamp(row['timestamp'])
        price = _twentyfour_midpoint(row)
        if parsed_timestamp is None or price is None:
            continue

        summary = summaries_by_item.setdefault(
            row['item_id'],
            {
                'item_id': row['item_id'],
                'item_name': row['item_name'],
                'current_price': price,
                'current_timestamp': parsed_timestamp,
                'period_low': price,
                'period_high': price,
                'volume': 0,
            },
        )
        summary['period_low'] = min(summary['period_low'], price)
        summary['period_high'] = max(summary['period_high'], price)

        if parsed_timestamp >= summary['current_timestamp']:
            summary['item_name'] = row['item_name']
            summary['current_price'] = price
            summary['current_timestamp'] = parsed_timestamp
            summary['volume'] = _row_volume(row)

    return list(summaries_by_item.values())


def _get_all_time_summaries(params):
    """
    Summarize all-time data into one comparison row per item.

    What: Compute current price and full-table low/high from AllTimeData.
    Why: The all-time range uses a dedicated storage model with numeric prices
        and timestamps instead of the 24h midpoint series.
    How: Aggregate extrema once per item, then fetch latest rows in a second
        query. This keeps PostgreSQL from repeating correlated latest-row
        subqueries for item name, current price, and timestamp.
    """
    rows = AllTimeData.objects.filter(item_price__gt=0)
    if params['custom_start_timestamp'] is not None:
        rows = rows.filter(timestamp__gte=params['custom_start_timestamp'])
    if params['search']:
        # Search picks the item set, while low/high comparisons still use that
        # item's full all-time history so the selected timeframe remains honest.
        matching_item_ids = rows.filter(item_name__icontains=params['search']).values('item_id').distinct()
        rows = rows.filter(item_id__in=matching_item_ids)

    extrema_rows = (
        rows.values('item_id')
        .annotate(
            period_low=Min('item_price'),
            period_high=Max('item_price'),
        )
    )
    summaries_by_item = {
        row['item_id']: {
            'item_id': row['item_id'],
            'item_name': None,
            'current_price': None,
            'current_timestamp': None,
            'period_low': row['period_low'],
            'period_high': row['period_high'],
            'volume': None,
        }
        for row in extrema_rows
        if row['period_low'] is not None and row['period_high'] is not None
    }

    for row in _get_latest_all_time_rows(summaries_by_item.keys(), params['custom_start_timestamp']):
        summary = summaries_by_item.get(row['item_id'])
        if summary is None:
            continue
        summary['item_name'] = row['item_name']
        summary['current_price'] = row['item_price']
        summary['current_timestamp'] = row['timestamp']

    return [
        summary
        for summary in summaries_by_item.values()
        if summary['current_price'] is not None
    ]


def _get_latest_all_time_rows(item_ids, start_timestamp=None):
    """
    Return the latest valid AllTimeData row for each requested item.

    PostgreSQL can use DISTINCT ON with the existing (item_id, -timestamp)
    index, which is cheaper than asking for three correlated subqueries per
    item. The window-function fallback keeps tests and local non-PostgreSQL
    environments exercising the same behavior.
    """
    item_ids = list(item_ids)
    if not item_ids:
        return []

    latest_rows = AllTimeData.objects.filter(item_id__in=item_ids, item_price__gt=0)
    if start_timestamp is not None:
        latest_rows = latest_rows.filter(timestamp__gte=start_timestamp)
    if connection.vendor == 'postgresql':
        latest_rows = latest_rows.order_by('item_id', '-timestamp').distinct('item_id')
    else:
        latest_rows = latest_rows.annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=[F('item_id')],
                order_by=F('timestamp').desc(),
            )
        ).filter(row_number=1)

    return latest_rows.values('item_id', 'item_name', 'item_price', 'timestamp')


def _build_results_payload(summaries, params, metadata_by_id, source, price_basis, range_start, range_end):
    """Convert normalized item summaries into the public results API shape."""
    results = []
    for summary in summaries:
        result = _build_result(summary, params, metadata_by_id)
        if result is None or not _result_matches_signal(result, params['signal']):
            continue
        results.append(result)

    _sort_results(results, params)
    distribution = _build_distribution(results)
    total_matches = len(results)
    page = params['page']
    page_size = FLIP_FINDER_RESULT_LIMIT
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    limited_results = results[start_index:end_index]

    return {
        'results': limited_results,
        'totalMatches': total_matches,
        'resultLimit': page_size,
        'page': page,
        'pageSize': page_size,
        'totalPages': max(1, (total_matches + page_size - 1) // page_size),
        'hasNextPage': end_index < total_matches,
        'hasPreviousPage': page > 1,
        'truncated': end_index < total_matches,
        'distribution': distribution,
        'meta': _build_meta(params, source, price_basis, range_start, range_end),
    }


def _empty_results_payload(params, source, price_basis, range_start, range_end):
    """Return a stable empty payload so the frontend can render no-data states."""
    return {
        'results': [],
        'totalMatches': 0,
        'resultLimit': FLIP_FINDER_RESULT_LIMIT,
        'page': params['page'],
        'pageSize': FLIP_FINDER_RESULT_LIMIT,
        'totalPages': 1,
        'hasNextPage': False,
        'hasPreviousPage': params['page'] > 1,
        'truncated': False,
        'distribution': {'low': 0, 'high': 0, 'both': 0},
        'meta': _build_meta(params, source, price_basis, range_start, range_end),
    }


def _build_result(summary, params, metadata_by_id):
    """
    Build a single table row from an item summary.

    What: Calculate distance from the period low/high and classify the result.
    Why: The UI needs to distinguish buy-candidate lows, sell-candidate highs,
        and flat/narrow-range items that qualify for both.
    How: Compare the current price against each extrema as a percentage; rows
        outside the selected threshold are dropped by returning None.
    """
    current_price = _valid_price(summary['current_price'])
    period_low = _valid_price(summary['period_low'])
    period_high = _valid_price(summary['period_high'])
    if current_price is None or period_low is None or period_high is None:
        return None

    item_name = _valid_item_name(summary.get('item_name'))
    if item_name is None:
        return None

    if current_price < params['min_price']:
        return None

    volume = _valid_volume(summary.get('volume'))
    if volume is not None and volume < params['min_volume']:
        return None

    distance_from_low = ((current_price - period_low) / period_low) * 100
    distance_from_high = ((period_high - current_price) / period_high) * 100
    near_low = distance_from_low <= params['percent']
    near_high = distance_from_high <= params['percent']
    if not near_low and not near_high:
        return None
    if near_low and near_high:
        signal = 'both'
    elif near_low:
        signal = 'low'
    else:
        signal = 'high'

    metadata = _metadata_for_item(summary['item_id'], metadata_by_id)
    return {
        'id': summary['item_id'],
        'name': item_name,
        'signal': signal,
        'currentPrice': _serialize_price(current_price),
        'periodLow': _serialize_price(period_low),
        'periodHigh': _serialize_price(period_high),
        'distanceFromLow': round(max(0, distance_from_low), 2),
        'distanceFromHigh': round(max(0, distance_from_high), 2),
        'closestDistance': round(max(0, min(distance_from_low, distance_from_high)), 2),
        'volume': volume,
        'latestTimestamp': summary.get('current_timestamp'),
        'updatedAt': _timestamp_to_iso(summary.get('current_timestamp')),
        'icon': metadata.get('icon'),
        'members': metadata.get('members'),
        'buyLimit': metadata.get('limit') or metadata.get('buy_limit'),
    }


def _result_matches_signal(result, signal):
    """Apply the selected signal filter while keeping `both` visible in either side."""
    if signal == 'low':
        return result['signal'] in {'low', 'both'}
    if signal == 'high':
        return result['signal'] in {'high', 'both'}
    return result['signal'] in {'low', 'high', 'both'}


def _sort_results(results, params):
    """
    Sort result rows with name as the deterministic tie-breaker.

    Python's sort is stable, so sorting by name first keeps equal distances or
    equal signal groups predictable after the primary sort is applied.
    """
    sort_direction = params['sortDirection']
    reverse = sort_direction == 'desc'
    results.sort(key=lambda result: result['name'].lower())

    if params['sort'] == 'volume':
        # Keep items without volume at the end for either direction so `All`
        # and `custom` remain predictable when their rows show `--`.
        results.sort(key=lambda result: result['volume'] if result['volume'] is not None else -1, reverse=reverse)
        results.sort(key=lambda result: result['volume'] is None)
        return

    results.sort(key=lambda result: _sort_value(result, params['sort'], params['signal']), reverse=reverse)


def _sort_value(result, sort_key, signal):
    """Return the comparison value for the requested result sort mode."""
    if sort_key == 'name':
        return result['name'].lower()
    if sort_key == 'signal':
        return {'low': 0, 'high': 1, 'both': 2}.get(result['signal'], 3)
    if sort_key == 'low':
        return result['distanceFromLow']
    if sort_key == 'high':
        return result['distanceFromHigh']
    if sort_key == 'current':
        return result['currentPrice']
    if sort_key == 'volume':
        return result['volume'] if result['volume'] is not None else -1
    if signal == 'high':
        return result['distanceFromHigh']
    if signal == 'low':
        return result['distanceFromLow']
    return result['closestDistance']


def _build_distribution(results):
    """Count visible result signals for the small distribution chart."""
    distribution = {'low': 0, 'high': 0, 'both': 0}
    for result in results:
        distribution[result['signal']] = distribution.get(result['signal'], 0) + 1
    return distribution


def _build_meta(params, source, price_basis, range_start, range_end):
    """Build source/range metadata shared by the results response."""
    return {
        'timeframe': params['timeframe'],
        'percent': params.get('percent'),
        'signal': params.get('signal'),
        'sort': params.get('sort'),
        'sortDirection': params.get('sortDirection'),
        'minPrice': params.get('min_price'),
        'minVolume': params.get('min_volume'),
        'volumeFilterApplied': params.get('min_volume', 0) > 0 and source != 'all_time_data',
        'source': source,
        'priceBasis': price_basis,
        'rangeStart': range_start,
        'rangeEnd': range_end,
        'rangeStartIso': _timestamp_to_iso(range_start),
        'rangeEndIso': _timestamp_to_iso(range_end),
        'customStartTimestamp': params.get('custom_start_timestamp'),
        'customStartIso': _timestamp_to_iso(params.get('custom_start_timestamp')),
    }


def _build_history_payload(item_id, item_name, timeframe, points, source, price_basis):
    """Package selected-item chart points and extrema into the history API shape."""
    prices = [point['price'] for point in points]
    current_point = points[-1] if points else None
    return {
        'itemId': item_id,
        'itemName': item_name,
        'timeframe': timeframe,
        'source': source,
        'priceBasis': price_basis,
        'points': points,
        'currentPrice': current_point['price'] if current_point else None,
        'periodLow': min(prices) if prices else None,
        'periodHigh': max(prices) if prices else None,
        'updatedAt': current_point['isoTimestamp'] if current_point else None,
    }


def _serialize_history_point(timestamp, price):
    """Serialize one chart point with machine and display timestamp fields."""
    return {
        'timestamp': timestamp,
        'isoTimestamp': _timestamp_to_iso(timestamp),
        'label': _timestamp_label(timestamp),
        'price': _serialize_price(price),
    }


def _twentyfour_midpoint(row):
    """
    Return the midpoint price for a 24h snapshot row.

    The 24h source stores averaged high and low prices separately. Using their
    midpoint gives the Flip Finder one comparable price series while still
    tolerating partial rows where only one side was ingested.
    """
    high_price = _valid_price(row.get('avg_high_price'))
    low_price = _valid_price(row.get('avg_low_price'))
    if high_price is not None and low_price is not None:
        return (high_price + low_price) / 2
    if high_price is not None:
        return high_price
    return low_price


def _valid_price(value):
    """Return a positive numeric price, or None for blank/zero/bad values."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def _valid_item_name(value):
    """Return a displayable item name, or None for blank local data rows."""
    if value is None:
        return None
    item_name = str(value).strip()
    return item_name or None


def _serialize_price(value):
    """Convert internal float math back to integer GP values for the API."""
    return int(round(float(value)))


def _valid_volume(value):
    """Return a non-negative volume integer, or None when the source lacks volume."""
    if value is None:
        return None
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, volume)


def _row_volume(row):
    """Use high-side and low-side price * quantity as traded GP volume."""
    high_price = _valid_price(row.get('avg_high_price'))
    low_price = _valid_price(row.get('avg_low_price'))
    return (
        _valid_quantity(row.get('high_price_volume')) * (_serialize_price(high_price) if high_price is not None else 0)
        + _valid_quantity(row.get('low_price_volume')) * (_serialize_price(low_price) if low_price is not None else 0)
    )


def _valid_quantity(value):
    """Return a non-negative traded item quantity for volume calculations."""
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, quantity)


def _metadata_for_item(item_id, metadata_by_id):
    """Look up optional item metadata regardless of int/string key shape."""
    return metadata_by_id.get(item_id) or metadata_by_id.get(str(item_id)) or {}


def _timestamp_to_iso(timestamp_value):
    """Convert a Unix timestamp to a UTC ISO string for display/debug metadata."""
    if timestamp_value is None:
        return None
    try:
        timestamp_number = int(timestamp_value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp_number, tz=timezone.utc).isoformat().replace('+00:00', 'Z')


def _timestamp_label(timestamp_value):
    """Return the compact chart-axis label for a Unix timestamp."""
    if timestamp_value is None:
        return ''
    try:
        timestamp_number = int(timestamp_value)
    except (TypeError, ValueError):
        return ''
    return datetime.fromtimestamp(timestamp_number, tz=timezone.utc).strftime('%b %d')
