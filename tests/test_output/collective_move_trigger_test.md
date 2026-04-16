# Collective Move Trigger Test Report

Updated: 2026-04-16 10:12:29 UTC

## Goal
Verify that collective_move alerts trigger on the expected price movements and stay silent when the market data does not meet the alert configuration.

## Coverage
- single-item collective move triggers
- multi-item collective move triggers
- all-items collective move triggers
- direction rules
- simple vs weighted calculations
- below-threshold behavior

## Test Runs

| Test | Result | Scope | Goal |
| --- | --- | --- | --- |
| `all_items_up_triggers` | PASS | all | Confirm the all-items collective move path triggers when all tracked items move together. |
| `below_threshold_stays_false` | PASS | single | Confirm collective move stays false when the price change does not reach the threshold. |
| `direction_mismatch_stays_false` | PASS | single | Confirm a direction mismatch prevents a trigger even when the magnitude is high enough. |
| `multi_item_up_triggers` | PASS | multi | Confirm the multi-item collective move path triggers when the average change clears the threshold. |
| `single_item_down_triggers_with_low_reference` | PASS | single | Confirm the single-item path respects downward collective moves. |
| `single_item_up_triggers` | PASS | single | Confirm a single-item collective move alert triggers on a clear upward move. |
| `weighted_path_stays_false_when_simple_would_trigger` | PASS | all | Confirm the weighted collective move path can stay below threshold even when the simple average would not. |

### all_items_up_triggers
- Status: PASS
- Goal: Confirm the all-items collective move path triggers when all tracked items move together.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_all_items_up_triggers
- How: Run the all-items path across three monitored items, all rising above the threshold.
- Setup: All-items collective move alert and a rising three-item market snapshot.
- Assumptions: The alert should use its price history only.

#### Trace
- Test: all_items_up_triggers
- Goal: Confirm the all-items collective move path triggers when all tracked items move together.
- How: Run the all-items path across three monitored items, all rising above the threshold.
- Setup: All-items collective move alert and a rising three-item market snapshot.
- Assumptions: The alert should use its price history only.
- Alert kwargs: {'is_all_items': True, 'reference_prices': {'4151': 100, '11802': 200, '11283': 300}, 'direction': 'up'}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 112, 'low': 112, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 216, 'low': 216, 'highTime': 1700000180, 'lowTime': 1700000180}, 11283: {'high': 330, 'low': 330, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}
- Observed result: True
- Observed payload: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}

#### Result
Expected True; observed True.

### below_threshold_stays_false
- Status: PASS
- Goal: Confirm collective move stays false when the price change does not reach the threshold.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_below_threshold_stays_false
- How: Run a 4% move against a 10% threshold.
- Setup: Single-item series that never reaches the trigger threshold.
- Assumptions: No amount of market noise should promote a below-threshold move to a trigger.

#### Trace
- Test: below_threshold_stays_false
- Goal: Confirm collective move stays false when the price change does not reach the threshold.
- How: Run a 4% move against a 10% threshold.
- Setup: Single-item series that never reaches the trigger threshold.
- Assumptions: No amount of market noise should promote a below-threshold move to a trigger.
- Alert kwargs: {'item_id': 4151, 'percentage': 5.0, 'reference_prices': {'4151': 100}, 'direction': 'up'}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 104, 'low': 104, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: False
- Final triggered_data: None
- Observed result: False
- Observed payload: None

#### Result
Expected False; observed False.

### direction_mismatch_stays_false
- Status: PASS
- Goal: Confirm a direction mismatch prevents a trigger even when the magnitude is high enough.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_direction_mismatch_stays_false
- How: Run an upward price move against a downward-only alert.
- Setup: Single-item upward series and an alert configured for down-only triggers.
- Assumptions: The checker should respect direction after the threshold is satisfied.

#### Trace
- Test: direction_mismatch_stays_false
- Goal: Confirm a direction mismatch prevents a trigger even when the magnitude is high enough.
- How: Run an upward price move against a downward-only alert.
- Setup: Single-item upward series and an alert configured for down-only triggers.
- Assumptions: The checker should respect direction after the threshold is satisfied.
- Alert kwargs: {'item_id': 4151, 'direction': 'down', 'reference_prices': {'4151': 100}}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 115, 'low': 115, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: False
- Final triggered_data: None
- Observed result: False
- Observed payload: None

#### Result
Expected False; observed False.

### multi_item_up_triggers
- Status: PASS
- Goal: Confirm the multi-item collective move path triggers when the average change clears the threshold.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_multi_item_up_triggers
- How: Run two monitored items through the same rising series.
- Setup: Two monitored items, both rising, with a simple arithmetic average.
- Assumptions: Missing volume rows are irrelevant to collective_move.

#### Trace
- Test: multi_item_up_triggers
- Goal: Confirm the multi-item collective move path triggers when the average change clears the threshold.
- How: Run two monitored items through the same rising series.
- Setup: Two monitored items, both rising, with a simple arithmetic average.
- Assumptions: Missing volume rows are irrelevant to collective_move.
- Alert kwargs: {'item_ids': [4151, 11802], 'reference_prices': {'4151': 100, '11802': 200}, 'direction': 'up'}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 120, 'low': 120, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 220, 'low': 220, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}
- Observed result: True
- Observed payload: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}

#### Result
Expected True; observed True.

### single_item_down_triggers_with_low_reference
- Status: PASS
- Goal: Confirm the single-item path respects downward collective moves.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_single_item_down_triggers_with_low_reference
- How: Use a low reference price and a 15% fall across the warm window.
- Setup: Single item, low reference type, and a downward price series.
- Assumptions: The low reference path should still trigger when the threshold is met.

#### Trace
- Test: single_item_down_triggers_with_low_reference
- Goal: Confirm the single-item path respects downward collective moves.
- How: Use a low reference price and a 15% fall across the warm window.
- Setup: Single item, low reference type, and a downward price series.
- Assumptions: The low reference path should still trigger when the threshold is met.
- Alert kwargs: {'item_id': 4151, 'reference': 'low', 'direction': 'down', 'reference_prices': {'4151': 100}}
- Step 1/4: ts=1700000000, prices={4151: {'high': 200, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 200, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 200, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 200, 'low': 85, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': -15.0, 'calculation_method': 'simple', 'direction': 'down', 'effective_direction': 'down', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'low', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 85, 'change_percent': -15.0, 'baseline_value': 100}]}
- Observed result: True
- Observed payload: {'average_change': -15.0, 'calculation_method': 'simple', 'direction': 'down', 'effective_direction': 'down', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'low', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 85, 'change_percent': -15.0, 'baseline_value': 100}]}

#### Result
Expected True; observed True.

### single_item_up_triggers
- Status: PASS
- Goal: Confirm a single-item collective move alert triggers on a clear upward move.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_single_item_up_triggers
- How: Run a 4-step price history with a 15% rise on one monitored item.
- Setup: Single item, high reference pricing, and no volume fixtures.
- Assumptions: collective_move should use the rolling price history only.

#### Trace
- Test: single_item_up_triggers
- Goal: Confirm a single-item collective move alert triggers on a clear upward move.
- How: Run a 4-step price history with a 15% rise on one monitored item.
- Setup: Single item, high reference pricing, and no volume fixtures.
- Assumptions: collective_move should use the rolling price history only.
- Alert kwargs: {'item_id': 4151, 'reference_prices': {'4151': 100}, 'direction': 'up'}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 115, 'low': 115, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 115, 'change_percent': 15.0, 'baseline_value': 100}]}
- Observed result: True
- Observed payload: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 115, 'change_percent': 15.0, 'baseline_value': 100}]}

#### Result
Expected True; observed True.

### weighted_path_stays_false_when_simple_would_trigger
- Status: PASS
- Goal: Confirm the weighted collective move path can stay below threshold even when the simple average would not.
- Checked: tests.trigger_tests.test_collective_move_trigger_test.CollectiveMoveTriggerSuite.test_weighted_path_stays_false_when_simple_would_trigger
- How: Run the same two-item market through a weighted alert that dampens the smaller mover.
- Setup: Two-item market with one large expensive item and one smaller sharper mover.
- Assumptions: Weighted averaging should honor the alert's configuration instead of the simple mean.

#### Trace
- Test: weighted_path_stays_false_when_simple_would_trigger
- Goal: Confirm the weighted collective move path can stay below threshold even when the simple average would not.
- How: Run the same two-item market through a weighted alert that dampens the smaller mover.
- Setup: Two-item market with one large expensive item and one smaller sharper mover.
- Assumptions: Weighted averaging should honor the alert's configuration instead of the simple mean.
- Alert kwargs: {'is_all_items': True, 'calculation_method': 'weighted', 'percentage': 10.0, 'reference': 'average', 'reference_prices': {'4151': 1000, '11802': 100}}
- Step 1/4: ts=1700000000, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 1020, 'low': 1020, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 150, 'low': 150, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: False
- Final triggered_data: None
- Observed result: False
- Observed payload: None

#### Result
Expected False; observed False.
