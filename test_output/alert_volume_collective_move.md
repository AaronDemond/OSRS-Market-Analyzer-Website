# Collective Move Volume Test Report

Updated: 2026-04-16 09:53:14 UTC

## Goal
Verify that collective_move alerts ignore HourlyItemVolume rows and still obey the price-based rules that define the alert.

## Coverage
- single-item collective move alerts
- multi-item collective move alerts
- all-items collective move alerts
- simple vs weighted calculations
- missing, stale, and unrelated HourlyItemVolume rows
- inclusive threshold behavior

## Assumptions
- collective_move does not consult HourlyItemVolume today.
- min_volume is intentionally set in many cases to prove it has no effect on this alert type.

## Test Runs

### test_all_items_up_triggers_without_volume_rows
- Status: PASS
- Goal: Verify the all-items collective move path triggers with a fully liquid-looking price move but no volume data.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_all_items_up_triggers_without_volume_rows
- How: Run the all-items path across three monitored items, all rising above the threshold, with no HourlyItemVolume rows.
- Setup: All-items collective move alert and a rising three-item market snapshot.
- Assumptions: The alert should use its price history only; the absence of volume data should be irrelevant.

#### Trace
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

### test_exact_threshold_is_inclusive_without_volume_rows
- Status: PASS
- Goal: Confirm the collective move threshold is inclusive at equality.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_exact_threshold_is_inclusive_without_volume_rows
- How: Run a 10% change against a 10% threshold and verify the alert fires without any volume rows.
- Setup: Single-item collective move alert and a series that lands exactly on the threshold.
- Assumptions: The checker should treat equality as a valid trigger the same way other alert types do.

#### Trace
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 110, 'low': 110, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 110, 'change_percent': 10.0, 'baseline_value': 100}]}
- Observed result: True
- Observed payload: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 1, 'items_in_response': 1, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 110, 'change_percent': 10.0, 'baseline_value': 100}]}

#### Result
Expected True at exact threshold; observed True.

### test_missing_volume_rows_do_not_block_single_item_trigger
- Status: PASS
- Goal: Confirm that a missing HourlyItemVolume row does not block a collective move trigger.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_missing_volume_rows_do_not_block_single_item_trigger
- How: Run a single-item alert with a huge min_volume value and no volume rows at all.
- Setup: Single item, empty HourlyItemVolume table for that item, and a valid rising series.
- Assumptions: collective_move should ignore the volume gate entirely, so missing data must not matter.

#### Trace
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
Expected True with no volume rows; observed True.

### test_multi_item_up_triggers_without_volume_rows
- Status: PASS
- Goal: Verify the multi-item collective move path triggers when the average change clears the threshold.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_multi_item_up_triggers_without_volume_rows
- How: Run two monitored items through the same rising series with no HourlyItemVolume rows.
- Setup: Two monitored items, both rising, with a simple arithmetic average.
- Assumptions: Missing volume data should not block the alert because collective_move has no volume gate.

#### Trace
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

### test_price_change_below_threshold_stays_false_without_volume_rows
- Status: PASS
- Goal: Confirm collective move still obeys the underlying percentage threshold.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_price_change_below_threshold_stays_false_without_volume_rows
- How: Run a series that only moves 4% against a 10% threshold with no volume rows present.
- Setup: Single-item collective move alert and a price series that never reaches the trigger threshold.
- Assumptions: No amount of missing volume data should turn a below-threshold move into a trigger.

#### Trace
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

### test_single_item_down_triggers_with_low_reference_without_volume_rows
- Status: PASS
- Goal: Verify the single-item path respects downward collective moves.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_single_item_down_triggers_with_low_reference_without_volume_rows
- How: Use a low reference price series that falls 15% across the warm window with no volume rows present.
- Setup: Single item, low reference type, and a downward price series.
- Assumptions: The low reference path should behave like the live checker and still ignore volume data.

#### Trace
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

### test_single_item_up_triggers_without_volume_rows
- Status: PASS
- Goal: Verify a single-item collective move alert triggers on a clear upward move.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_single_item_up_triggers_without_volume_rows
- How: Run a 4-step price history with a 15% rise on one monitored item and no HourlyItemVolume rows.
- Setup: Single item, high reference pricing, and no volume fixtures at all.
- Assumptions: collective_move should not consult HourlyItemVolume, so the missing rows should not matter.

#### Trace
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

### test_stale_volume_rows_do_not_change_all_items_result
- Status: PASS
- Goal: Confirm that stale HourlyItemVolume rows do not alter the all-items collective move result.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_stale_volume_rows_do_not_change_all_items_result
- How: Run the same all-items series twice, once clean and once with stale volume rows for the monitored items.
- Setup: All-items alert, valid rising series, and stale volume rows older than the freshness window.
- Assumptions: Since collective_move ignores volume entirely, stale rows should be a pure no-op.

#### Trace
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 112, 'low': 112, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 216, 'low': 216, 'highTime': 1700000180, 'lowTime': 1700000180}, 11283: {'high': 330, 'low': 330, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}, 11283: {'high': 300, 'low': 300, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 112, 'low': 112, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 216, 'low': 216, 'highTime': 1700000180, 'lowTime': 1700000180}, 11283: {'high': 330, 'low': 330, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}
- Baseline result: True
- Stale-volume result: True
- Baseline payload: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}
- Stale-volume payload: {'average_change': 10.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 3, 'items_in_response': 3, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 112, 'change_percent': 12.0, 'baseline_value': 100}, {'item_id': '11283', 'item_name': 'Dragonfire shield', 'reference_price': 300, 'current_price': 330, 'change_percent': 10.0, 'baseline_value': 300}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 216, 'change_percent': 8.0, 'baseline_value': 200}]}

#### Result
Expected identical results with and without stale volume rows.

### test_unrelated_volume_rows_do_not_change_multi_item_result
- Status: PASS
- Goal: Confirm that volume rows for unrelated items do not alter the collective move result.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_unrelated_volume_rows_do_not_change_multi_item_result
- How: Run the same multi-item series twice, once with no volume rows and once with unrelated rows only.
- Setup: Two monitored items, plus HourlyItemVolume rows for items outside the alert scope.
- Assumptions: Unrelated volume rows should be a no-op because collective_move never reads them.

#### Trace
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 120, 'low': 120, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 220, 'low': 220, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}
- Step 1/4: ts=1700000000, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 200, 'low': 200, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 120, 'low': 120, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 220, 'low': 220, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}
- Baseline result: True
- Volume-row result: True
- Baseline payload: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}
- Volume-row payload: {'average_change': 15.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'high', 'time_frame_minutes': 3, 'items': [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'baseline_value': 100}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 220, 'change_percent': 10.0, 'baseline_value': 200}]}

#### Result
Expected identical results with and without unrelated volume rows.

### test_weighted_all_items_differs_from_simple_average
- Status: PASS
- Goal: Verify the weighted collective move path still obeys its own price rule and can differ from simple averaging.
- Checked: tests.test_alert_volume_collective_move.CollectiveMoveVolumeTests.test_weighted_all_items_differs_from_simple_average
- How: Run the same two-item market through simple and weighted alerts, then compare the outcomes.
- Setup: Two all-items alerts, same price data, one simple and one weighted.
- Assumptions: The weighted path should still be a pure price rule and not be influenced by HourlyItemVolume.

#### Trace
- Step 1/4: ts=1700000000, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 1020, 'low': 1020, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 150, 'low': 150, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: True
- Final triggered_data: {'average_change': 26.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'average', 'time_frame_minutes': 3, 'items': [{'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 100, 'current_price': 150, 'change_percent': 50.0, 'baseline_value': 100}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 1000, 'current_price': 1020, 'change_percent': 2.0, 'baseline_value': 1000}]}
- Step 1/4: ts=1700000000, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000000, 'lowTime': 1700000000}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000000, 'lowTime': 1700000000}}
- Step 1 result: False
- Step 2/4: ts=1700000060, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000060, 'lowTime': 1700000060}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000060, 'lowTime': 1700000060}}
- Step 2 result: False
- Step 3/4: ts=1700000120, prices={4151: {'high': 1000, 'low': 1000, 'highTime': 1700000120, 'lowTime': 1700000120}, 11802: {'high': 100, 'low': 100, 'highTime': 1700000120, 'lowTime': 1700000120}}
- Step 3 result: False
- Step 4/4: ts=1700000180, prices={4151: {'high': 1020, 'low': 1020, 'highTime': 1700000180, 'lowTime': 1700000180}, 11802: {'high': 150, 'low': 150, 'highTime': 1700000180, 'lowTime': 1700000180}}
- Step 4 result: False
- Final triggered_data: None
- Simple result: True
- Weighted result: False
- Simple payload: {'average_change': 26.0, 'calculation_method': 'simple', 'direction': 'up', 'effective_direction': 'up', 'threshold': 10.0, 'total_items_checked': 2, 'items_in_response': 2, 'reference_type': 'average', 'time_frame_minutes': 3, 'items': [{'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 100, 'current_price': 150, 'change_percent': 50.0, 'baseline_value': 100}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 1000, 'current_price': 1020, 'change_percent': 2.0, 'baseline_value': 1000}]}
- Weighted payload: None

#### Result
Expected simple=True and weighted=False; observed simple=True, weighted=False.
