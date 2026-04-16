# Threshold Trigger Test Report

Last rewritten: 2026-04-16 07:12:40 Atlantic Daylight Time

Scope: threshold alert trigger behavior.

This file is rewritten whenever the suite runs.

## Suite Summary
- Status: completed in the test runner

## all_items_too_small
Goal: All-items thresholds should stay quiet when the market move is under the configured threshold.
Expected: False
Observed: []
Setup: No item reaches a +50% move.
Assumptions: Threshold comparisons remain inclusive only at or above the configured value.
Output:
- return=[]

## all_items_percentage_up
Goal: All-items thresholds should return a list of every qualifying item.
Expected: List with two items
Observed: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'threshold': 10.0, 'direction': 'up'}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 240, 'change_percent': 20.0, 'threshold': 10.0, 'direction': 'up'}]
Setup: Two items cross +10%, one item stays below threshold.
Assumptions: The result list should be sorted by absolute change descending.
Output:
- return=[{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'threshold': 10.0, 'direction': 'up'}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 240, 'change_percent': 20.0, 'threshold': 10.0, 'direction': 'up'}]

## single_percentage_below
Goal: A move below the configured percentage should not trigger.
Expected: False
Observed: False
Setup: One item moves +20% against a +25% threshold.
Assumptions: The checker should leave triggered_data empty when nothing passes.
Output:
- return=False

## single_percentage_down
Goal: Single-item percentage threshold should trigger on a move below the configured threshold.
Expected: True
Observed: True with payload {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 90, 'change_percent': -10.0, 'threshold': 5.0, 'direction': 'down'}
Setup: One item, -10% move, downward direction, percentage threshold.
Assumptions: Down direction compares against the low price reference.
Output:
- return=True
- payload={'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 90, 'change_percent': -10.0, 'threshold': 5.0, 'direction': 'down'}

## single_percentage_up
Goal: Single-item percentage threshold should trigger on a move above the configured threshold.
Expected: True
Observed: True with payload {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 150, 'change_percent': 50.0, 'threshold': 20.0, 'direction': 'up'}
Setup: One item, +50% move, upward direction, percentage threshold.
Assumptions: Reference prices are stored in the alert and the checker uses high prices.
Output:
- return=True
- payload={'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 150, 'change_percent': 50.0, 'threshold': 20.0, 'direction': 'up'}

## single_value_missing_target
Goal: A value threshold without a target should not trigger.
Expected: False
Observed: False
Setup: Single-item value threshold missing target_price.
Assumptions: The checker should reject incomplete value-based configs.
Output:
- return=False

## single_value_up
Goal: Value thresholds should trigger once the current price reaches or exceeds the target.
Expected: True
Observed: True with payload {'item_id': '4151', 'item_name': 'Abyssal whip', 'target_price': 120, 'current_price': 150, 'reference_price': 100, 'direction': 'up', 'threshold_type': 'value'}
Setup: One item, target price 120 gp, current high price 150 gp.
Assumptions: Value thresholds use the target_price field and a single item only.
Output:
- return=True
- payload={'item_id': '4151', 'item_name': 'Abyssal whip', 'target_price': 120, 'current_price': 150, 'reference_price': 100, 'direction': 'up', 'threshold_type': 'value'}
