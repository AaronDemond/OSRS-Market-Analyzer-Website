# HourlyItemVolume CharField Timestamp Analysis

## Problem
The `HourlyItemVolume` model's `timestamp` field was changed from `DateTimeField` to `CharField(max_length=255)`. Need to verify that sustained alerts and spread alerts still grab the correct (most recent) row from the database.

## How Alerts Query Volume

Both sustained and spread alerts use the same method in `check_alerts.py`:

```python
def get_volume_from_timeseries(self, item_id, time_window_minutes):
    latest_volume = HourlyItemVolume.objects.filter(item_id=int(item_id)).first()
    if latest_volume:
        return latest_volume.volume
    return None
```

This relies on `Meta.ordering = ['-timestamp']` so that `.first()` returns the row with the largest timestamp.

## Does Lexicographic Ordering Work?

With a `CharField`, Django uses **lexicographic (string) ordering** instead of chronological ordering.

### For Unix Epoch Integer Strings (e.g., `"1706012400"`)
- All Unix timestamps are currently **10-digit numbers** (and will be until November 2286)
- Lexicographic descending sort on equal-length numeric strings = chronological descending sort
- **Result: `.first()` correctly returns the most recent row** ✅

### For Datetime Strings (e.g., `"2024-01-23 18:00:00+00:00"`)
- The `makeObjects()` function in `get-all-volume.py` stores `datetime.fromtimestamp()` objects
- When saved to a CharField, these become strings like `"2024-01-23 18:00:00+00:00"`
- These strings start with `"2"`, which sorts **after** Unix epoch strings starting with `"1"`
- **This means old backfill rows could appear as "most recent" if mixed with integer timestamps** ⚠️

## Scripts and What They Store

| Script | Function | Timestamp Format |
|--------|----------|-----------------|
| `update_volumes.py` | `fetch_item_volume()` | Raw API integer (e.g., `1706012400`) |
| `get-all-volume.py` | `fetch_latest_volume_snapshot()` | Raw API integer (e.g., `1706012400`) |
| `get-all-volume.py` | `makeObjects()` (legacy) | `datetime` object → string (e.g., `"2024-01-23 18:00:00+00:00"`) |
| `backfill_volumes.py` | Main loop | Raw API integer (stored via `get-all-volume.py` functions) |

## Current Assessment

The **active** scripts (`update_volumes.py` and `fetch_latest_volume_snapshot()`) both store Unix epoch integers as strings. For these, the current `Meta.ordering = ['-timestamp']` + `.first()` pattern works correctly.

**However**, `makeObjects()` in `get-all-volume.py` (legacy, no longer auto-called) stored datetime objects. If that function was previously used to backfill data, those rows have timestamps like `"2024-01-23 18:00:00+00:00"` which lexicographically sort **after** integer strings like `"1706012400"` (because `"2"` > `"1"`). This could cause stale backfill rows to appear as "most recent."

## Proposed Solutions

### Option 1: Minimal — Update Comments Only
- Assumes you're aware of the data format consistency
- Just update comments in `check_alerts.py` and `models.py` to reflect CharField
- No query logic changes needed if all active scripts store integers

### Option 2: Robust — Use `.order_by('-id')` Instead
- Replace reliance on `-timestamp` with `-id` (auto-increment PKs)
- Newer DB rows always have larger IDs regardless of timestamp format
- Protects against mixed timestamp formats from different scripts
- Small change: `HourlyItemVolume.objects.filter(item_id=int(item_id)).order_by('-id').first()`

## Recommendation
**Option 2** is safer and future-proof. It costs nothing in performance (PK lookups are indexed by default) and eliminates any risk from inconsistent timestamp formats.
