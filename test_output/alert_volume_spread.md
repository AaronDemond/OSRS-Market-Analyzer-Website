# Alert Spread Volume Tests

This file is rewritten whenever `tests.test_alert_volume_spread` runs.

## Scope
- Single-item spread alerts
- Multi-item spread alerts
- All-items spread alerts
- Fresh, stale, missing, and optional volume behavior

## Assumptions
- Hourly volume means GP volume, not item count.
- `min_volume=None` and `min_volume=0` both behave as disabled volume gates in the current checker.

