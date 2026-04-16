# Sustained Volume Alert Test Report

Updated: 2026-04-16 09:54:11 UTC

## Goal
Verify that sustained alerts respect hourly volume restrictions across single-item, multi-item, and all-items flows.

## Coverage
- fresh volume allows sustained triggers
- low volume blocks sustained triggers
- stale volume blocks sustained triggers
- missing volume blocks sustained triggers
- volume gating does not unexpectedly clear streak state
- multi-item and all-items sustained alerts obey the same restriction path

## Test Runs

### test_all_items_sustained_blocks_stale_volume_even_with_valid_price_streak
- Status: PASS
- Goal: Confirm stale hourly volume snapshots block all-items sustained alerts.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_all_items_sustained_blocks_stale_volume_even_with_valid_price_streak
- How: Run the all-items path with stale volume rows for every item and a valid sustained price streak.
- Setup: All-items sustained alert and stale volume rows for all monitored items.
- Assumptions: Stale data should be treated as missing, even when the price streak is otherwise valid.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: False
- Final result: False
- Lookup A: None
- Lookup B: None

#### Result
Stale hourly volume was rejected for both items, so the all-items sustained alert did not trigger.

### test_all_items_sustained_blocks_when_every_item_is_under_volume_threshold
- Status: PASS
- Goal: Confirm an all-items sustained alert returns False when no item meets the volume threshold.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_all_items_sustained_blocks_when_every_item_is_under_volume_threshold
- How: Run the all-items path with two items that both have fresh but low hourly volume rows.
- Setup: All-items sustained alert and no item above min_volume.
- Assumptions: A result list should not be produced when every candidate item fails volume gating.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: False
- Final result: False

#### Result
No item cleared the hourly volume gate, so the all-items sustained alert stayed quiet.

### test_all_items_sustained_returns_only_items_meeting_volume_threshold
- Status: PASS
- Goal: Confirm an all-items sustained alert only includes items that meet the hourly volume restriction.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_all_items_sustained_returns_only_items_meeting_volume_threshold
- How: Run the all-items path with one liquid item and one illiquid item using the same price streak.
- Setup: All-items sustained alert, identical price movement, and mixed volume coverage.
- Assumptions: The result list should include only the item whose hourly GP volume clears min_volume.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 35000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]
- Final result: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 35000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]
- Triggered payload: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 35000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]

#### Result
The all-items result list kept only the item above the minimum hourly volume.

### test_multi_item_sustained_blocks_when_every_item_is_below_volume_threshold
- Status: PASS
- Goal: Confirm a multi-item sustained alert stays false when every candidate item is under min_volume.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_multi_item_sustained_blocks_when_every_item_is_below_volume_threshold
- How: Run two items through the same sustained streak, but keep both hourly volume rows below the threshold.
- Setup: Two monitored items, both fresh but both under the required GP volume.
- Assumptions: If every item fails volume gating, the multi-item sustained check should return False.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: False
- Final result: False

#### Result
Both items failed the volume filter, so no multi-item sustained alert fired.

### test_multi_item_sustained_ignores_missing_volume_for_one_item_but_keeps_the_other
- Status: PASS
- Goal: Confirm a multi-item sustained alert can still trigger for the item that has volume data when a sibling item has none.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_multi_item_sustained_ignores_missing_volume_for_one_item_but_keeps_the_other
- How: Leave one monitored item without any HourlyItemVolume rows and give the other a fresh high-volume row.
- Setup: Two monitored items, only one with a real volume snapshot.
- Assumptions: Missing volume should only block the item that lacks data, not the whole multi-item alert.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: True
- Final result: True
- Triggered payload: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 30000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]

#### Result
The missing-volume item was ignored while the liquid item still triggered.

### test_multi_item_sustained_triggers_only_the_item_with_fresh_volume
- Status: PASS
- Goal: Confirm a multi-item sustained alert only returns items whose hourly volume passes the filter.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_multi_item_sustained_triggers_only_the_item_with_fresh_volume
- How: Run two monitored items through the same streak; only one item gets a fresh high-volume snapshot.
- Setup: Two monitored items with identical price movement, one fresh and one low-volume.
- Assumptions: The multi-item sustained path should keep the qualifying item and reject the under-volume one.

#### Trace
- Step 1/6: prices={4151: 1000, 11802: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020, 11802: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040, 11802: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060, 11802: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080, 11802: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100, 11802: 1100}
- Step 6 result: True
- Final result: True
- Triggered payload: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 30000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]

#### Result
Only the item above min_volume survived the multi-item sustained check.

### test_single_item_does_not_trigger_when_volume_is_below_threshold
- Status: PASS
- Goal: Confirm a single-item sustained alert stays quiet when the hourly volume is below the threshold.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_single_item_does_not_trigger_when_volume_is_below_threshold
- How: Run the same sustained streak with a fresh HourlyItemVolume row that is intentionally under min_volume.
- Setup: Single item, fresh low volume, and a qualifying price streak so the volume gate is the only blocker.
- Assumptions: A low GP volume snapshot should fail the min_volume gate even when price movement is otherwise valid.

#### Trace
- Step 1/6: prices={4151: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100}
- Step 6 result: False
- Final result: False
- State after block: {'last_price': 1100.0, 'streak_count': 5, 'streak_direction': 'up', 'streak_start_time': 1776333246.3240004, 'streak_start_price': 1000.0, 'volatility_buffer': [2.0, 1.9607843137254901, 1.9230769230769231, 1.8867924528301887, 1.8518518518518516]}

#### Result
The alert did not trigger, but the streak state remained intact for later checks.

### test_single_item_does_not_trigger_when_volume_snapshot_is_missing
- Status: PASS
- Goal: Confirm missing hourly volume prevents a single-item sustained alert from triggering.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_single_item_does_not_trigger_when_volume_snapshot_is_missing
- How: Run the sustained streak without creating any HourlyItemVolume rows for the item.
- Setup: Single item, no volume row at all, and a qualifying price series.
- Assumptions: Missing volume should behave like None and block the trigger.

#### Trace
- Step 1/6: prices={4151: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100}
- Step 6 result: False
- Final result: False
- Freshness lookup returned: None

#### Result
No volume row existed, so the sustained alert correctly never triggered.

### test_single_item_does_not_trigger_when_volume_snapshot_is_stale
- Status: PASS
- Goal: Confirm a stale hourly volume snapshot blocks a single-item sustained alert.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_single_item_does_not_trigger_when_volume_snapshot_is_stale
- How: Seed a high-volume HourlyItemVolume row with an old timestamp and run the same sustained streak.
- Setup: Single item, stale volume snapshot, and a qualifying price series.
- Assumptions: A stale volume row should be treated like missing data and block triggering.

#### Trace
- Step 1/6: prices={4151: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100}
- Step 6 result: False
- Final result: False
- Freshness lookup returned: None

#### Result
Stale volume was rejected and the single-item sustained alert stayed inactive.

### test_single_item_triggers_with_fresh_volume_above_threshold
- Status: PASS
- Goal: Confirm a single-item sustained alert triggers when the hourly volume is fresh and above the configured minimum.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_single_item_triggers_with_fresh_volume_above_threshold
- How: Run a six-step upward price series against a single-item alert with a fresh HourlyItemVolume row above the threshold.
- Setup: Single item, fresh volume row, upward price series, and a sustained config that needs at least three qualifying moves.
- Assumptions: The sustained state machine should allow the trigger once the streak, volatility, and volume checks all pass.

#### Trace
- Step 1/6: prices={4151: 1000}
- Step 1 result: False
- Step 2/6: prices={4151: 1020}
- Step 2 result: False
- Step 3/6: prices={4151: 1040}
- Step 3 result: False
- Step 4/6: prices={4151: 1060}
- Step 4 result: False
- Step 5/6: prices={4151: 1080}
- Step 5 result: False
- Step 6/6: prices={4151: 1100}
- Step 6 result: True
- Final result: True
- Triggered payload: {'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 5, 'total_move_percent': 10.0, 'start_price': 1000.0, 'current_price': 1100.0, 'volume': 25000, 'avg_volatility': 1.9245, 'required_move': 0.9623, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}

#### Result
Single-item sustained alert triggered cleanly with fresh volume above threshold.

### test_single_item_volume_gate_keeps_the_existing_streak_state
- Status: PASS
- Goal: Confirm that a volume-gated sustained failure does not wipe out an already-building streak.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_single_item_volume_gate_keeps_the_existing_streak_state
- How: Build a streak with a low-volume snapshot, verify it does not trigger, then swap in fresh volume and confirm the next qualifying move fires.
- Setup: Single item, first with fresh low volume and later with a fresh high-volume row, using the same sustained streak progression.
- Assumptions: Volume gating should block the trigger without clearing the streak counter the state machine already built.

#### Trace
- Warm-up step 1: {'4151': {'high': 1000, 'low': 1000, 'highTime': 1776333250, 'lowTime': 1776333250}}
- Warm-up step 2: {'4151': {'high': 1020, 'low': 1020, 'highTime': 1776333251, 'lowTime': 1776333251}}
- Warm-up step 3: {'4151': {'high': 1040, 'low': 1040, 'highTime': 1776333252, 'lowTime': 1776333252}}
- Warm-up step 4: {'4151': {'high': 1060, 'low': 1060, 'highTime': 1776333253, 'lowTime': 1776333253}}
- Warm-up step 5: {'4151': {'high': 1080, 'low': 1080, 'highTime': 1776333254, 'lowTime': 1776333254}}
- Blocked result: False
- State after blocked trigger: {'last_price': 1100.0, 'streak_count': 5, 'streak_direction': 'up', 'streak_start_time': 1776333250.336893, 'streak_start_price': 1000.0, 'volatility_buffer': [2.0, 1.9607843137254901, 1.9230769230769231, 1.8867924528301887, 1.8518518518518516]}
- Final result after fresh volume: True
- Triggered payload after fresh volume: {'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 6, 'total_move_percent': 12.0, 'start_price': 1000.0, 'current_price': 1120.0, 'volume': 30000, 'avg_volatility': 1.8881, 'required_move': 0.9441, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}

#### Result
The streak survived the low-volume block and triggered as soon as fresh volume arrived.

### test_volume_lookup_prefers_the_newest_fresh_row
- Status: PASS
- Goal: Confirm the sustained alert volume lookup returns the newest fresh HourlyItemVolume row.
- Checked: tests.test_alert_volume_sustained.SustainedVolumeAlertTests.test_volume_lookup_prefers_the_newest_fresh_row
- How: Insert an older low-volume row and then a newer high-volume row for the same item, then query the helper directly.
- Setup: Single item with two real HourlyItemVolume rows and different timestamps.
- Assumptions: The lookup helper should choose the latest parseable fresh snapshot for the item.

#### Trace
- Volume lookup returned: 50000

#### Result
The helper returned the newest fresh volume row instead of the older one.
