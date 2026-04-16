# Dump Alert Volume Test Report

Generated: 2026-04-16 09:53:24 UTC

## Summary

| Test | Result | Focus |
| --- | --- | --- |
| `all_items_blocks_when_every_candidate_lacks_volume` | PASS | Confirm all-items dump alerts return False when no item clears the liquidity floor. |
| `all_items_returns_only_high_volume_items` | PASS | Confirm all-items dump alerts only return items that clear the liquidity floor. |
| `multi_item_blocks_when_every_candidate_lacks_volume` | PASS | Confirm a multi-item dump alert returns False when every selected item fails the hourly volume gate. |
| `multi_item_filters_low_volume_peer` | PASS | Confirm multi-item dump alerts keep the high-volume item and drop the low-volume peer. |
| `single_item_blocks_when_relative_volume_is_too_high` | PASS | Confirm dump alerts reject items when the relative-volume minimum is not satisfied. |
| `single_item_blocks_when_volume_below_floor` | PASS | Confirm a single-item dump alert does not trigger when hourly volume is below the floor. |
| `single_item_blocks_when_volume_is_stale` | PASS | Confirm stale hourly volume data is ignored by the dump checker. |
| `single_item_blocks_when_volume_missing` | PASS | Confirm missing hourly volume data prevents a dump trigger. |
| `single_item_passes_when_volume_equals_floor` | PASS | Confirm the liquidity gate is inclusive at the exact floor value. |
| `single_item_triggers_above_liquidity_floor` | PASS | Confirm a dump alert still fires when hourly GP volume is comfortably above the liquidity floor. |
| `single_item_triggers_with_loose_relative_volume_minimum` | PASS | Confirm a healthy item still triggers when relative volume is permissive. |

## Cases

### all_items_blocks_when_every_candidate_lacks_volume

- Goal: Confirm all-items dump alerts return False when no item clears the liquidity floor.
- Scope: multi/all
- Setup: All four tracked items are either below the floor, missing, or stale.
- Assumptions: The all-items scan should end with no triggered rows.
- Output:
  - Test: all_items_blocks_when_every_candidate_lacks_volume
  - Goal: Confirm all-items dump alerts return False when no item clears the liquidity floor.
  - Setup: All four tracked items are either below the floor, missing, or stale.
  - Assumptions: The all-items scan should end with no triggered rows.
  - Alert kwargs: {'is_all_items': True, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #125 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #125 (Dump Volume Test)
  - Call 2 result: False
- Expected: []
- Actual: []
- Result: PASS

### all_items_returns_only_high_volume_items

- Goal: Confirm all-items dump alerts only return items that clear the liquidity floor.
- Scope: multi/all
- Setup: Item A is liquid; Item B is under the floor; Item C has no volume row; Item D is stale.
- Assumptions: Only Item A should survive the hourly-volume gate.
- Output:
  - Test: all_items_returns_only_high_volume_items
  - Goal: Confirm all-items dump alerts only return items that clear the liquidity floor.
  - Setup: Item A is liquid; Item B is under the floor; Item C has no volume row; Item D is stale.
  - Assumptions: Only Item A should survive the hourly-volume gate.
  - Alert kwargs: {'is_all_items': True, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #126 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #126 (Dump Volume Test)
  - Call 2 result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 997.0, 'current_low': 880, 'discount_pct': 11.75, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Expected: ['4151']
- Actual: ['4151']
- Result: PASS

### multi_item_blocks_when_every_candidate_lacks_volume

- Goal: Confirm a multi-item dump alert returns False when every selected item fails the hourly volume gate.
- Scope: multi/all
- Setup: Item B is below the floor, Item C is missing, and Item D is stale.
- Assumptions: The alert should not leak any item through when no candidate is liquid enough.
- Output:
  - Test: multi_item_blocks_when_every_candidate_lacks_volume
  - Goal: Confirm a multi-item dump alert returns False when every selected item fails the hourly volume gate.
  - Setup: Item B is below the floor, Item C is missing, and Item D is stale.
  - Assumptions: The alert should not leak any item through when no candidate is liquid enough.
  - Alert kwargs: {'item_ids': '[11802, 13576, 11832]', 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #127 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #127 (Dump Volume Test)
  - Call 2 result: False
- Expected: []
- Actual: []
- Result: PASS

### multi_item_filters_low_volume_peer

- Goal: Confirm multi-item dump alerts keep the high-volume item and drop the low-volume peer.
- Scope: multi/all
- Setup: Item A has 20M GP hourly volume; Item B has 5M GP hourly volume.
- Assumptions: Both items otherwise satisfy dump conditions.
- Output:
  - Test: multi_item_filters_low_volume_peer
  - Goal: Confirm multi-item dump alerts keep the high-volume item and drop the low-volume peer.
  - Setup: Item A has 20M GP hourly volume; Item B has 5M GP hourly volume.
  - Assumptions: Both items otherwise satisfy dump conditions.
  - Alert kwargs: {'item_ids': '[4151, 11802]', 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #128 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #128 (Dump Volume Test)
  - Call 2 result: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'fair_value': 997.0, 'current_low': 880, 'discount_pct': 11.75, 'sell_ratio': 0.85, 'rel_vol': 1.0, 'shock_sigma': -1.0}]
- Expected: ['4151']
- Actual: ['4151']
- Result: PASS

### single_item_blocks_when_relative_volume_is_too_high

- Goal: Confirm dump alerts reject items when the relative-volume minimum is not satisfied.
- Scope: single
- Setup: Item A has a normal bucket volume ratio around 1.0, but the threshold is raised above that.
- Assumptions: This checks the relative volume gate rather than the liquidity floor.
- Output:
  - Test: single_item_blocks_when_relative_volume_is_too_high
  - Goal: Confirm dump alerts reject items when the relative-volume minimum is not satisfied.
  - Setup: Item A has a normal bucket volume ratio around 1.0, but the threshold is raised above that.
  - Assumptions: This checks the relative volume gate rather than the liquidity floor.
  - Alert kwargs: {'item_id': 4151, 'dump_liquidity_floor': 1, 'dump_rel_vol_min': 1.5}
  - Running call 1 for alert #129 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #129 (Dump Volume Test)
  - Call 2 result: False
- Expected: False
- Actual: False
- Result: PASS

### single_item_blocks_when_volume_below_floor

- Goal: Confirm a single-item dump alert does not trigger when hourly volume is below the floor.
- Scope: single
- Setup: Item B only has 5M GP hourly volume.
- Assumptions: A low-volume item should be filtered before dump math matters.
- Output:
  - Test: single_item_blocks_when_volume_below_floor
  - Goal: Confirm a single-item dump alert does not trigger when hourly volume is below the floor.
  - Setup: Item B only has 5M GP hourly volume.
  - Assumptions: A low-volume item should be filtered before dump math matters.
  - Alert kwargs: {'item_id': 11802, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #130 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #130 (Dump Volume Test)
  - Call 2 result: False
- Expected: False
- Actual: False
- Result: PASS

### single_item_blocks_when_volume_is_stale

- Goal: Confirm stale hourly volume data is ignored by the dump checker.
- Scope: single
- Setup: Item D has a large hourly volume row, but it is older than the freshness window.
- Assumptions: Stale volume should be treated as missing, not eligible.
- Output:
  - Test: single_item_blocks_when_volume_is_stale
  - Goal: Confirm stale hourly volume data is ignored by the dump checker.
  - Setup: Item D has a large hourly volume row, but it is older than the freshness window.
  - Assumptions: Stale volume should be treated as missing, not eligible.
  - Alert kwargs: {'item_id': 11832, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #131 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #131 (Dump Volume Test)
  - Call 2 result: False
- Expected: False
- Actual: False
- Result: PASS

### single_item_blocks_when_volume_missing

- Goal: Confirm missing hourly volume data prevents a dump trigger.
- Scope: single
- Setup: Item C has no HourlyItemVolume row at all.
- Assumptions: Missing data should behave like unavailable liquidity.
- Output:
  - Test: single_item_blocks_when_volume_missing
  - Goal: Confirm missing hourly volume data prevents a dump trigger.
  - Setup: Item C has no HourlyItemVolume row at all.
  - Assumptions: Missing data should behave like unavailable liquidity.
  - Alert kwargs: {'item_id': 13576, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #132 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #132 (Dump Volume Test)
  - Call 2 result: False
- Expected: False
- Actual: False
- Result: PASS

### single_item_passes_when_volume_equals_floor

- Goal: Confirm the liquidity gate is inclusive at the exact floor value.
- Scope: single
- Setup: Item A volume is set to exactly 10,000,000 GP.
- Assumptions: Equality to the floor should be accepted, not rejected.
- Output:
  - Test: single_item_passes_when_volume_equals_floor
  - Goal: Confirm the liquidity gate is inclusive at the exact floor value.
  - Setup: Item A volume is set to exactly 10,000,000 GP.
  - Assumptions: Equality to the floor should be accepted, not rejected.
  - Alert kwargs: {'item_id': 4151, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #133 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #133 (Dump Volume Test)
  - Call 2 result: True
- Expected: True
- Actual: True
- Result: PASS

### single_item_triggers_above_liquidity_floor

- Goal: Confirm a dump alert still fires when hourly GP volume is comfortably above the liquidity floor.
- Scope: single
- Setup: Item A has fresh 20M GP hourly volume and a clear dump bucket.
- Assumptions: All other dump thresholds are loose enough to let volume be the deciding factor.
- Output:
  - Test: single_item_triggers_above_liquidity_floor
  - Goal: Confirm a dump alert still fires when hourly GP volume is comfortably above the liquidity floor.
  - Setup: Item A has fresh 20M GP hourly volume and a clear dump bucket.
  - Assumptions: All other dump thresholds are loose enough to let volume be the deciding factor.
  - Alert kwargs: {'item_id': 4151, 'dump_liquidity_floor': 10000000, 'dump_rel_vol_min': 0.1}
  - Running call 1 for alert #134 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #134 (Dump Volume Test)
  - Call 2 result: True
- Expected: True
- Actual: True
- Result: PASS

### single_item_triggers_with_loose_relative_volume_minimum

- Goal: Confirm a healthy item still triggers when relative volume is permissive.
- Scope: single
- Setup: Item A has a current bucket volume that matches its expected EWMA volume.
- Assumptions: Relative volume is intentionally loose so the alert should pass.
- Output:
  - Test: single_item_triggers_with_loose_relative_volume_minimum
  - Goal: Confirm a healthy item still triggers when relative volume is permissive.
  - Setup: Item A has a current bucket volume that matches its expected EWMA volume.
  - Assumptions: Relative volume is intentionally loose so the alert should pass.
  - Alert kwargs: {'item_id': 4151, 'dump_liquidity_floor': 1, 'dump_rel_vol_min': 0.5}
  - Running call 1 for alert #135 (Dump Volume Test)
  - Call 1 result: False
  - Running call 2 for alert #135 (Dump Volume Test)
  - Call 2 result: True
- Expected: True
- Actual: True
- Result: PASS
