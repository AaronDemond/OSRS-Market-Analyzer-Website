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

## SpreadVolumeCoreTests
- Generated: 2026-04-16 09:53:48
- Covered tests:
  - `test_single_item_does_not_trigger_when_spread_is_below_threshold`
  - `test_single_item_does_not_trigger_when_volume_is_below_threshold`
  - `test_single_item_exact_min_volume_still_triggers`
  - `test_single_item_triggers_when_spread_and_volume_pass`
  - `test_single_item_without_min_volume_ignores_volume_gate`

## SpreadVolumeEdgeTests
- Generated: 2026-04-16 09:53:58
- Covered tests:
  - `test_all_items_payload_includes_volume_for_each_match`
  - `test_all_items_without_min_volume_keeps_low_volume_items`
  - `test_missing_volume_is_rejected`
  - `test_multi_item_returns_false_when_every_match_is_under_volume_threshold`
  - `test_multi_item_returns_only_volume_qualified_items`
  - `test_stale_volume_is_rejected`
  - `test_zero_min_volume_behaves_like_disabled_gate`

