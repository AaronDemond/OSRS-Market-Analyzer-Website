# Dump Trigger Test Report

Updated: 2026-04-16 10:12:35 UTC

## Goal
Verify that dump alerts trigger when the alert configuration and market data support it, and stay silent when volume or alert thresholds block them.

## Coverage
- single-item dump triggers
- multi-item dump triggers
- all-items dump triggers
- minimum hourly volume
- relative volume gating
- missing and stale hourly volume blocking
- inclusive floor behavior

## Test Runs

| Test | Result | Scope | Goal |
| --- | --- | --- | --- |
| `all_items_triggers_for_all_liquid_monitored_items` | PASS | multi/all | Confirm the all-items dump path returns every item that clears the liquidity gate and dump conditions. |
| `blocks_when_volume_is_below_floor` | PASS | single | Confirm a dump alert does not trigger when hourly volume is below the configured floor. |
| `blocks_when_volume_is_stale` | PASS | single | Confirm stale hourly volume data is ignored by the dump checker. |
| `blocks_when_volume_missing` | PASS | single | Confirm missing hourly volume data prevents a dump trigger. |
| `exact_liquidity_floor_triggers_inclusively` | PASS | single | Confirm the dump liquidity gate is inclusive at the exact floor value. |
| `multi_item_triggers_with_two_liquid_candidates` | PASS | multi/all | Confirm a multi-item dump alert returns the liquid items that meet the dump conditions. |
| `single_item_triggers_above_liquidity_floor` | PASS | single | Confirm a single-item dump alert triggers when the item is liquid and the dump conditions are permissive. |

### all_items_triggers_for_all_liquid_monitored_items
- Status: PASS
- Goal: Confirm the all-items dump path returns every item that clears the liquidity gate and dump conditions.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_all_items_triggers_for_all_liquid_monitored_items
- How: Run the checker across the tracked market and let every monitored item dump together.
- Setup: Three tracked items have fresh hourly volume above the configured floor.
- Assumptions: The all-items scan should return all tracked items that satisfy the dump rules.

#### Trace
- Test: all_items_triggers_for_all_liquid_monitored_items
- Goal: Confirm the all-items dump path returns every item that clears the liquidity gate and dump conditions.
- How: Run the checker across the tracked market and let every monitored item dump together.
- Setup: Three tracked items have fresh hourly volume above the configured floor.
- Assumptions: The all-items scan should return all tracked items that satisfy the dump rules.
- Alert kwargs: {'is_all_items': True}
- Priming alert #8 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '13576', 'item_name': 'Dragon warhammer', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Observed result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '13576', 'item_name': 'Dragon warhammer', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Observed item ids: ['11802', '13576', '4151']

#### Result
Expected ['11802', '13576', '4151']; observed ['11802', '13576', '4151'].

### blocks_when_volume_is_below_floor
- Status: PASS
- Goal: Confirm a dump alert does not trigger when hourly volume is below the configured floor.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_blocks_when_volume_is_below_floor
- How: Give the item a dump pattern but leave its hourly volume below the threshold.
- Setup: Item B has only 5M GP hourly volume.
- Assumptions: Low liquidity should block the alert before dump math matters.

#### Trace
- Test: blocks_when_volume_is_below_floor
- Goal: Confirm a dump alert does not trigger when hourly volume is below the configured floor.
- How: Give the item a dump pattern but leave its hourly volume below the threshold.
- Setup: Item B has only 5M GP hourly volume.
- Assumptions: Low liquidity should block the alert before dump math matters.
- Alert kwargs: {'item_id': 11802}
- Priming alert #9 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: False
- Observed result: False

#### Result
Expected False; observed False.

### blocks_when_volume_is_stale
- Status: PASS
- Goal: Confirm stale hourly volume data is ignored by the dump checker.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_blocks_when_volume_is_stale
- How: Set a large hourly volume row older than the freshness window and then run the dump transition.
- Setup: Item D has a large volume row, but it is stale.
- Assumptions: Stale volume should be treated as missing, not eligible.

#### Trace
- Test: blocks_when_volume_is_stale
- Goal: Confirm stale hourly volume data is ignored by the dump checker.
- How: Set a large hourly volume row older than the freshness window and then run the dump transition.
- Setup: Item D has a large volume row, but it is stale.
- Assumptions: Stale volume should be treated as missing, not eligible.
- Alert kwargs: {'item_id': 11832}
- Priming alert #10 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: False
- Observed result: False

#### Result
Expected False; observed False.

### blocks_when_volume_missing
- Status: PASS
- Goal: Confirm missing hourly volume data prevents a dump trigger.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_blocks_when_volume_missing
- How: Leave the item without any HourlyItemVolume row and run the dump transition.
- Setup: Item C has no hourly volume row at all.
- Assumptions: Missing data should behave like unavailable liquidity.

#### Trace
- Test: blocks_when_volume_missing
- Goal: Confirm missing hourly volume data prevents a dump trigger.
- How: Leave the item without any HourlyItemVolume row and run the dump transition.
- Setup: Item C has no hourly volume row at all.
- Assumptions: Missing data should behave like unavailable liquidity.
- Alert kwargs: {'item_id': 13576}
- Priming alert #11 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: False
- Observed result: False

#### Result
Expected False; observed False.

### exact_liquidity_floor_triggers_inclusively
- Status: PASS
- Goal: Confirm the dump liquidity gate is inclusive at the exact floor value.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_exact_liquidity_floor_triggers_inclusively
- How: Set the hourly volume to exactly the configured liquidity floor.
- Setup: Item A is exactly at 10,000,000 GP hourly volume.
- Assumptions: Equality to the floor should be accepted, not rejected.

#### Trace
- Test: exact_liquidity_floor_triggers_inclusively
- Goal: Confirm the dump liquidity gate is inclusive at the exact floor value.
- How: Set the hourly volume to exactly the configured liquidity floor.
- Setup: Item A is exactly at 10,000,000 GP hourly volume.
- Assumptions: Equality to the floor should be accepted, not rejected.
- Alert kwargs: {'item_id': 4151}
- Priming alert #12 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: True
- Observed result: True

#### Result
Expected True; observed True.

### multi_item_triggers_with_two_liquid_candidates
- Status: PASS
- Goal: Confirm a multi-item dump alert returns the liquid items that meet the dump conditions.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_multi_item_triggers_with_two_liquid_candidates
- How: Check two monitored items through the same normal-to-dump transition.
- Setup: Item A and Item B both have fresh hourly volume above the liquidity floor.
- Assumptions: Both items should survive the gate and appear in the result list.

#### Trace
- Test: multi_item_triggers_with_two_liquid_candidates
- Goal: Confirm a multi-item dump alert returns the liquid items that meet the dump conditions.
- How: Check two monitored items through the same normal-to-dump transition.
- Setup: Item A and Item B both have fresh hourly volume above the liquidity floor.
- Assumptions: Both items should survive the gate and appear in the result list.
- Alert kwargs: {'item_ids': '[4151, 11802]'}
- Priming alert #13 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Observed result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'fair_value': 998.0, 'current_low': 880, 'discount_pct': 11.79, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Observed item ids: ['11802', '4151']

#### Result
Expected ['11802', '4151']; observed ['11802', '4151'].

### single_item_triggers_above_liquidity_floor
- Status: PASS
- Goal: Confirm a single-item dump alert triggers when the item is liquid and the dump conditions are permissive.
- Checked: tests.trigger_tests.test_dump_trigger_test.DumpTriggerSuite.test_single_item_triggers_above_liquidity_floor
- How: Run the checker twice with a normal first pass and a sharp dump on the second pass.
- Setup: Item A has fresh 20M GP hourly volume and a clear dump bucket.
- Assumptions: The price move, sell ratio, and relative volume are all configured to allow a trigger.

#### Trace
- Test: single_item_triggers_above_liquidity_floor
- Goal: Confirm a single-item dump alert triggers when the item is liquid and the dump conditions are permissive.
- How: Run the checker twice with a normal first pass and a sharp dump on the second pass.
- Setup: Item A has fresh 20M GP hourly volume and a clear dump bucket.
- Assumptions: The price move, sell ratio, and relative volume are all configured to allow a trigger.
- Alert kwargs: {'item_id': 4151}
- Priming alert #14 with normal market prices.
- First pass result: False
- Running dump market pass.
- Second pass result: True
- Observed result: True

#### Result
Expected True; observed True.
