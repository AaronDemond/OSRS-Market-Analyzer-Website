# Spread Trigger Test Report

Last rewritten: 2026-04-16 07:12:38 Atlantic Daylight Time

Scope: spread alert trigger behavior.

This file is rewritten whenever the suite runs.

## Suite Summary
- Status: completed in the test runner

## all_items_trigger_sorted
Goal: All-items spread alerts should return every qualifying item sorted by spread descending.
Expected: List of three items ordered by spread descending
Observed: [{'item_id': '11235', 'item_name': 'Dragonfire shield', 'high': 140, 'low': 100, 'spread': 40.0, 'volume': 5000000}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'high': 112, 'low': 100, 'spread': 12.0, 'volume': 2500000}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'high': 155, 'low': 140, 'spread': 10.71, 'volume': 2000000}]
Setup: Three items all pass spread and volume with clearly different spreads.
Assumptions: Triggered payload ordering reflects highest spreads first.
Output:
- return=[{'item_id': '11235', 'item_name': 'Dragonfire shield', 'high': 140, 'low': 100, 'spread': 40.0, 'volume': 5000000}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'high': 112, 'low': 100, 'spread': 12.0, 'volume': 2500000}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'high': 155, 'low': 140, 'spread': 10.71, 'volume': 2000000}]

## multi_trigger_watched_items
Goal: Multi-item spread alerts should return all watched items that qualify.
Expected: List containing both watched items
Observed: [{'item_id': '11802', 'item_name': 'Dragon crossbow', 'high': 160, 'low': 140, 'spread': 14.29, 'volume': 3000000}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'high': 112, 'low': 100, 'spread': 12.0, 'volume': 2000000}]
Setup: Two watched items both clear spread and volume; an unwatched item is also present in market data.
Assumptions: Only item_ids members are considered for multi-item spread alerts.
Output:
- return=[{'item_id': '11802', 'item_name': 'Dragon crossbow', 'high': 160, 'low': 140, 'spread': 14.29, 'volume': 3000000}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'high': 112, 'low': 100, 'spread': 12.0, 'volume': 2000000}]

## single_no_trigger_below_threshold
Goal: A spread below the configured threshold should not trigger.
Expected: False
Observed: False
Setup: One watched item at 6% spread against a 10% threshold.
Assumptions: Volume passes, so the spread comparison alone decides the outcome.
Output:
- return=False

## single_no_trigger_missing_low
Goal: Spread alerts should not trigger when market data is incomplete.
Expected: False
Observed: False
Setup: The watched item has a high price but no low price in the market snapshot.
Assumptions: Spread calculation returns None when low is missing.
Output:
- return=False

## single_no_trigger_low_volume
Goal: Spread alerts should stay silent when the item fails the minimum hourly volume requirement.
Expected: False
Observed: False
Setup: One watched item clears spread but is one unit under the hourly volume minimum.
Assumptions: Volume gating happens before the item is accepted into triggered_data.
Output:
- return=False

## single_trigger_exact_threshold
Goal: Spread thresholds should trigger when the spread exactly matches the configured percentage.
Expected: True
Observed: True
Setup: One watched item at exactly 6% spread with volume exactly at the threshold.
Assumptions: Both spread and min_volume comparisons are inclusive.
Output:
- return=True
- triggered_data=None

## single_trigger_basic
Goal: Single-item spread alerts should trigger when spread and volume both pass.
Expected: True
Observed: True
Setup: One watched item at 12% spread with fresh volume above the minimum.
Assumptions: Spread uses ((high - low) / low) * 100 and the volume gate is inclusive.
Output:
- return=True
- triggered_data=None
