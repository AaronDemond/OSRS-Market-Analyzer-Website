# Spike Trigger Test Report

Last rewritten: 2026-04-16 07:12:37 Atlantic Daylight Time

Scope: spike alert trigger behavior.

This file is rewritten whenever the suite runs.

## Suite Summary
- Status: completed in the test runner

## all_items_trigger
Goal: All-items spike alerts should return a sorted list of qualifying items.
Expected: List with qualifying items
Observed: [{'item_id': '100', 'item_name': 'Dragon Bones', 'baseline': 100, 'current': 130, 'percent_change': 30.0, 'reference': 'high', 'direction': 'both'}, {'item_id': '200', 'item_name': 'Abyssal Whip', 'baseline': 200, 'current': 230, 'percent_change': 15.0, 'reference': 'high', 'direction': 'both'}]
Setup: Two items exceed the threshold and one item stays below it.
Assumptions: Results are sorted by absolute percent change descending.
Output:
- return=[{'item_id': '100', 'item_name': 'Dragon Bones', 'baseline': 100, 'current': 130, 'percent_change': 30.0, 'reference': 'high', 'direction': 'both'}, {'item_id': '200', 'item_name': 'Abyssal Whip', 'baseline': 200, 'current': 230, 'percent_change': 15.0, 'reference': 'high', 'direction': 'both'}]

## multi_item_trigger
Goal: Multi-item spike alerts should trigger when at least one watched item spikes.
Expected: List with triggered items
Observed: [{'item_id': '100', 'item_name': 'Dragon Bones', 'baseline': 100, 'current': 120, 'percent_change': 20.0, 'reference': 'high', 'direction': 'both'}, {'item_id': '200', 'item_name': 'Abyssal Whip', 'baseline': 200, 'current': 220, 'percent_change': 10.0, 'reference': 'high', 'direction': 'both'}]
Setup: Two watched items both exceed the 10% threshold.
Assumptions: Triggered data should include every item that exceeds the threshold.
Output:
- return=[{'item_id': '100', 'item_name': 'Dragon Bones', 'baseline': 100, 'current': 120, 'percent_change': 20.0, 'reference': 'high', 'direction': 'both'}, {'item_id': '200', 'item_name': 'Abyssal Whip', 'baseline': 200, 'current': 220, 'percent_change': 10.0, 'reference': 'high', 'direction': 'both'}]

## single_below_threshold
Goal: A move below the configured spike threshold should stay silent.
Expected: False
Observed: False
Setup: One item rises only 20% against a 25% threshold.
Assumptions: Warmup is valid, but the spike is still too small.
Output:
- return=False

## single_low_volume
Goal: Spike alerts must ignore items that fail the hourly GP volume gate.
Expected: False
Observed: False
Setup: The move qualifies, but the item volume is below the minimum.
Assumptions: Volume checks happen after the spike threshold check.
Output:
- return=False

## single_no_warmup
Goal: Spike alerts should not trigger until the window has warmed up.
Expected: False
Observed: False
Setup: No baseline history is seeded into the rolling window.
Assumptions: The checker requires data from the full lookback window.
Output:
- return=False

## single_down_trigger
Goal: Single-item spike alerts should trigger when the drop meets the threshold.
Expected: True
Observed: True
Setup: One item with a 20% downward spike and fresh volume.
Assumptions: Direction 'down' compares the negative percentage move.
Output:
- return=True
- triggered_data={"baseline": 200, "current": 160, "percent_change": -20.0, "time_frame_minutes": 60, "reference": "high", "direction": "down"}

## single_up_trigger
Goal: Single-item spike alerts should trigger when the rise meets the threshold.
Expected: True
Observed: True
Setup: One item with a 20% upward spike and fresh volume.
Assumptions: A valid warmup baseline already exists in the command history.
Output:
- return=True
- triggered_data={"baseline": 100, "current": 120, "percent_change": 20.0, "time_frame_minutes": 60, "reference": "high", "direction": "up"}
