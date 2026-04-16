# Alert Volume Threshold Suite

Last rewritten: 2026-04-16 06:54:12 Atlantic Daylight Time

This file is rewritten every time the suite runs.

Scope: threshold alerts and hourly volume restrictions.

## All-items percentage threshold with fresh volume
Goal: Verify an all-items threshold alert returns multiple qualifying items when the hourly volume for each item is fresh.
Explicit check: Multiple items should survive the filter because all of them meet the threshold and the volume gate.
How: Scan the market snapshot with three items, all of which have fresh volume rows.
Setup: Created one all-items alert, three fresh volume rows, and three price snapshots.
Assumptions: The checker should evaluate every item and keep more than one result.
Observed output:
- return value: [{'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 260, 'change_percent': 30.0, 'threshold': 15.0, 'direction': 'up'}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'threshold': 15.0, 'direction': 'up'}]
- triggered item ids: ['11802', '4151']
Result: PASS: expected multiple items and got ['11802', '4151'].

## All-items threshold excludes missing volume
Goal: Verify an all-items threshold alert omits items with no hourly volume record while keeping qualifying items that do have volume.
Explicit check: The missing-volume item must not appear in the triggered list even if its price move qualifies.
How: Check three market items, two with fresh volume rows and one without any volume row.
Setup: Created one alert, two fresh volume rows, one missing volume item, and three qualifying price snapshots.
Assumptions: The checker should quietly skip the item with no volume row.
Observed output:
- return value: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 115, 'change_percent': 15.0, 'threshold': 5.0, 'direction': 'up'}, {'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 215, 'change_percent': 7.5, 'threshold': 5.0, 'direction': 'up'}]
- triggered item ids: ['11802', '4151']
Result: PASS: expected the missing-volume item to be excluded.

## Multi-item percentage threshold with fresh volume
Goal: Verify a multi-item threshold alert returns every qualifying item when each item has fresh volume and meets the percentage threshold.
Explicit check: Both selected items should remain in the triggered list because their hourly volume is fresh.
How: Check two tracked items with fresh hourly volume snapshots and percentage-based reference prices.
Setup: Created one multi-item alert, two fresh volume rows, and two price snapshots.
Assumptions: The checker should compare each item against its stored reference price and keep both when both qualify.
Observed output:
- return value: [{'item_id': '11802', 'item_name': 'Dragon crossbow', 'reference_price': 200, 'current_price': 260, 'change_percent': 30.0, 'threshold': 20.0, 'direction': 'up'}, {'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 120, 'change_percent': 20.0, 'threshold': 20.0, 'direction': 'up'}]
- triggered item ids: ['11802', '4151']
Result: PASS: expected both item IDs and got ['11802', '4151'].

## Multi-item threshold excludes stale volume
Goal: Verify a multi-item threshold alert keeps the fresh item and excludes the stale-volume item.
Explicit check: Only the fresh item should survive the volume filter.
How: Check two selected items with the same price behavior, but only one fresh volume row.
Setup: Created one alert, one fresh volume row, one stale volume row, and two qualifying price snapshots.
Assumptions: The checker should filter the stale item out before returning the triggered list.
Observed output:
- return value: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'reference_price': 100, 'current_price': 150, 'change_percent': 50.0, 'threshold': 15.0, 'direction': 'up'}]
- triggered item ids: ['4151']
Result: PASS: expected only 4151 and got ['4151'].

## Reference price edge case: average
Goal: Verify percentage thresholds compare against the midpoint price when the alert reference is set to average.
Explicit check: The average reference should use the midpoint of high and low prices.
How: Use a price snapshot where the midpoint is above baseline and the alert should cross the threshold exactly as intended.
Setup: Created one alert, one fresh volume row, and one price snapshot with a midpoint high enough to trigger.
Assumptions: Average price should be computed from the two market sides, not from one side alone.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "reference_price": 100, "current_price": 120, "change_percent": 20.0, "threshold": 15.0, "direction": "up"}
Result: PASS: expected True and got True.

## Reference price edge case: high
Goal: Verify percentage thresholds compare against the high price when the alert reference is set to high.
Explicit check: The high reference should drive the percent-change calculation.
How: Use a price snapshot where the high is well above baseline and the low is irrelevant for the calculation.
Setup: Created one alert, one fresh volume row, and one price snapshot with a strong high-side move.
Assumptions: A high reference should make the alert trigger on the buy-side price.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "reference_price": 100, "current_price": 140, "change_percent": 40.0, "threshold": 15.0, "direction": "up"}
Result: PASS: expected True and got True.

## Reference price edge case: low
Goal: Verify percentage thresholds compare against the low price when the alert reference is set to low.
Explicit check: The low reference should drive the percent-change calculation.
How: Use a price snapshot where the low is below baseline and the high is irrelevant for the calculation.
Setup: Created one alert, one fresh volume row, and one price snapshot with a strong low-side move.
Assumptions: A low reference should make the alert trigger on the sell-side price.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "reference_price": 100, "current_price": 90, "change_percent": -10.0, "threshold": 5.0, "direction": "down"}
Result: PASS: expected True and got True.

## Single percentage threshold blocks stale volume
Goal: Verify a single-item percentage threshold does not trigger when the most recent volume snapshot is stale.
Explicit check: A stale hourly volume row must be treated as missing data and block the alert.
How: Check one item whose only volume row is older than the freshness cutoff.
Setup: Created one alert, one stale volume row, and one price snapshot that otherwise qualifies.
Assumptions: Stale volume should be rejected even if the price move is large enough.
Observed output:
- return value: False
- expected: False because the hourly volume snapshot is stale
Result: PASS: expected False and got False.

## Single percentage threshold above
Goal: Verify a single-item percentage threshold fires when the price rises above the configured threshold and hourly volume is fresh.
Explicit check: A +20% threshold should trigger on a +50% change, provided the volume gate is open.
How: Check one item with a fresh hourly volume snapshot and a high reference price.
Setup: Created one threshold alert, one fresh HourlyItemVolume row, and one market snapshot.
Assumptions: Fresh volume should satisfy the filter, and the checker should compare against the high price reference.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "reference_price": 100, "current_price": 150, "change_percent": 50.0, "threshold": 20.0, "direction": "up"}
Result: PASS: expected True and got True.

## Single percentage threshold below
Goal: Verify a single-item percentage threshold fires when the price falls below the configured threshold and hourly volume is fresh.
Explicit check: A -5% threshold should trigger on a -10% move, provided the volume gate is open.
How: Check one item with a fresh hourly volume snapshot and a low reference price.
Setup: Created one threshold alert, one fresh HourlyItemVolume row, and one market snapshot.
Assumptions: Fresh volume should satisfy the filter, and the checker should compare against the low price reference.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "reference_price": 100, "current_price": 90, "change_percent": -10.0, "threshold": 5.0, "direction": "down"}
Result: PASS: expected True and got True.

## Single value threshold blocks missing volume
Goal: Verify a single-item value threshold does not trigger when there is no hourly volume data at all.
Explicit check: A missing hourly volume row must block the alert just like stale data does.
How: Check one item with a valid market move but no saved volume snapshot.
Setup: Created one alert and one qualifying price snapshot, but intentionally no volume row.
Assumptions: No volume should mean the item is treated as ineligible for threshold triggering.
Observed output:
- return value: False
- expected: False because no hourly volume row exists
Result: PASS: expected False and got False.

## Single value threshold above
Goal: Verify a single-item value threshold fires when the current price is at or above the target and the volume gate passes.
Explicit check: A target of 120 gp should trigger when the high price is 150 gp.
How: Check one item with fresh hourly volume and a high reference price.
Setup: Created one value threshold alert and one fresh hourly volume snapshot.
Assumptions: Fresh volume should allow the current price comparison to proceed.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "target_price": 120, "current_price": 150, "reference_price": null, "direction": "up", "threshold_type": "value"}
Result: PASS: expected True and got True.

## Single value threshold below
Goal: Verify a single-item value threshold fires when the current price falls to or below the target and the volume gate passes.
Explicit check: A target of 120 gp should trigger when the low price is 90 gp.
How: Check one item with fresh hourly volume and a low reference price.
Setup: Created one value threshold alert and one fresh hourly volume snapshot.
Assumptions: Fresh volume should allow the current price comparison to proceed.
Observed output:
- return value: True
- triggered_data: {"item_id": "4151", "item_name": "Abyssal whip", "target_price": 120, "current_price": 90, "reference_price": null, "direction": "down", "threshold_type": "value"}
Result: PASS: expected True and got True.

## Suite Summary
- Status: completed in the test runner
