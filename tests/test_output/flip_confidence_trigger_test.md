# Flip Confidence Trigger Test Report

Last rewritten: 2026-04-16 07:12:36 Atlantic Daylight Time

Scope: flip confidence alert trigger behavior.

This file is rewritten whenever the suite runs.

## Suite Summary
- Status: completed in the test runner

## all_items_crosses_above
Goal: All-items flip confidence should return a sorted payload of qualifying items.
Expected: True
Observed: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11235', 'item_name': 'Dragonfire shield', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
Setup: Every item passes the confidence threshold.
Assumptions: All-items mode returns a list of triggered items.
Output:
- return=[{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11235', 'item_name': 'Dragonfire shield', 'confidence_score': 85, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
- triggered_data=None

## multi_crosses_above
Goal: Multi-item flip confidence should trigger when watched items all score above threshold.
Expected: True
Observed: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 82, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'confidence_score': 82, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
Setup: Two watched items share the same high confidence score.
Assumptions: Multi-item mode returns a list of triggered items.
Output:
- return=[{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 82, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'confidence_score': 82, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
- triggered_data=None

## single_below_threshold
Goal: A score below the threshold should not trigger flip confidence.
Expected: False
Observed: False
Setup: The patched score stays below the alert threshold.
Assumptions: Below-threshold scores should leave the alert silent.
Output:
- return=False

## single_concentrated_volume
Goal: Flip confidence should skip items where a single bucket dominates the lookback window.
Expected: False
Observed: False
Setup: The lookback volume is too concentrated in one bucket.
Assumptions: The concentration filter is evaluated before the trigger rule.
Output:
- return=False

## single_low_volume
Goal: Flip confidence should skip items that do not meet the minimum volume gate.
Expected: False
Observed: False
Setup: The score is high, but total GP volume is below the configured minimum.
Assumptions: The volume pre-filter runs before the score comparison.
Output:
- return=False

## single_delta_increase
Goal: Delta-increase mode should trigger when the score rises by the configured amount.
Expected: True
Observed: True
Setup: The score rises from 50 to 80 with a delta threshold of 20.
Assumptions: Previous score state is loaded from confidence_last_scores.
Output:
- return=True
- payload={"item_id": "4151", "item_name": "Abyssal whip", "confidence_score": 80, "previous_score": 50, "trigger_rule": "delta_increase", "threshold": 20.0, "consecutive_passes": 1}

## single_crosses_above
Goal: Single-item flip confidence should trigger when the score crosses the threshold.
Expected: True
Observed: True
Setup: One item with a score above the configured threshold.
Assumptions: The patched confidence score represents the computed market signal.
Output:
- return=True
- payload={"item_id": "4151", "item_name": "Abyssal whip", "confidence_score": 80, "previous_score": null, "trigger_rule": "crosses_above", "threshold": 70.0, "consecutive_passes": 1}
