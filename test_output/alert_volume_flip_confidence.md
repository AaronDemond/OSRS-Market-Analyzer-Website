# Flip Confidence Volume Restriction Test Suite

Report status: suite_complete
Generated: 2026-04-16T09:53:33.908470+00:00

This file is rewritten every time the suite runs.
It records the goal, setup, assumptions, verbose trace output,
and the final result for each test case.

## 1. All-items mode keeps only liquid items

Goal: An all-items flip-confidence alert should only return market items whose total GP volume clears the floor.
What is being tested: All-items prefilter path, GP-volume enforcement, and list output shape.
How it is being tested: Feed three market items into the live checker, but only two of them are given enough synthetic volume to qualify.
Setup: Create a saved all-items alert with minimum and maximum price filters that allow the synthetic items through.
Assumptions: The checker should scan all market items and return a list containing only the liquid ones.
Output:
- [START] All-items mode keeps only liquid items
- [GOAL] An all-items flip-confidence alert should only return market items whose total GP volume clears the floor.
- [WHAT] All-items prefilter path, GP-volume enforcement, and list output shape.
- [HOW] Feed three market items into the live checker, but only two of them are given enough synthetic volume to qualify.
- [SETUP] Create a saved all-items alert with minimum and maximum price filters that allow the synthetic items through.
- [ASSUMPTIONS] The checker should scan all market items and return a list containing only the liquid ones.
- Configured all-items mode with two liquid items and one filtered-out item.
- Result items: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 87.0, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}, {'item_id': '11212', 'item_name': 'Dragon arrow tips', 'confidence_score': 87.0, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, inspect the all-items branch that prefilters by price and then applies the volume floor to each item.

## 2. Crosses-above still respects the threshold after volume filtering

Goal: A flip-confidence alert should not trigger if the confidence score stays below the configured threshold, even when volume is healthy.
What is being tested: Threshold interaction after the volume gate has passed.
How it is being tested: Use a high-volume series, but force the confidence score to remain under the threshold.
Setup: Create a single-item alert using the default crosses_above trigger rule and a reasonable volume floor.
Assumptions: Healthy volume alone should never be enough to trigger the alert without the score crossing the threshold.
Output:
- [START] Crosses-above still respects the threshold after volume filtering
- [GOAL] A flip-confidence alert should not trigger if the confidence score stays below the configured threshold, even when volume is healthy.
- [WHAT] Threshold interaction after the volume gate has passed.
- [HOW] Use a high-volume series, but force the confidence score to remain under the threshold.
- [SETUP] Create a single-item alert using the default crosses_above trigger rule and a reasonable volume floor.
- [ASSUMPTIONS] Healthy volume alone should never be enough to trigger the alert without the score crossing the threshold.
- Configured crosses_above mode where the score remains under the threshold even though volume is healthy.
- Result: False
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the score-vs-threshold comparison is not being enforced after the volume checks.

## 3. Delta increase mode still obeys the volume floor

Goal: The delta_increase rule should trigger only when the item rises by the configured delta and still meets the GP volume filter.
What is being tested: Trigger-rule interaction with the min-volume gate.
How it is being tested: Seed prior confidence state, force the score upward, and keep the synthetic volume safely above the configured floor.
Setup: Create a single-item alert in delta_increase mode with a prior score recorded in confidence_last_scores.
Assumptions: The checker should compare the new score against the saved prior score only after the volume gate passes.
Output:
- [START] Delta increase mode still obeys the volume floor
- [GOAL] The delta_increase rule should trigger only when the item rises by the configured delta and still meets the GP volume filter.
- [WHAT] Trigger-rule interaction with the min-volume gate.
- [HOW] Seed prior confidence state, force the score upward, and keep the synthetic volume safely above the configured floor.
- [SETUP] Create a single-item alert in delta_increase mode with a prior score recorded in confidence_last_scores.
- [ASSUMPTIONS] The checker should compare the new score against the saved prior score only after the volume gate passes.
- Configured delta_increase mode with a prior score of 40 and a current score above that by 15+.
- Result: True
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, delta_increase may be bypassing the normal prefilters or reading previous scores incorrectly.

## 4. Lookback values below three are clamped to the minimum

Goal: Flip-confidence alerts should normalize tiny lookback settings up to the minimum usable window.
What is being tested: Lookback clamp edge case and its interaction with the volume floor.
How it is being tested: Set confidence_lookback to 1, then verify the fetch hook sees a lookback of 3 and the alert still evaluates normally.
Setup: Create a single-item alert with a deliberately too-small lookback value.
Assumptions: The checker should clamp lookback to 3 before asking for history.
Output:
- [START] Lookback values below three are clamped to the minimum
- [GOAL] Flip-confidence alerts should normalize tiny lookback settings up to the minimum usable window.
- [WHAT] Lookback clamp edge case and its interaction with the volume floor.
- [HOW] Set confidence_lookback to 1, then verify the fetch hook sees a lookback of 3 and the alert still evaluates normally.
- [SETUP] Create a single-item alert with a deliberately too-small lookback value.
- [ASSUMPTIONS] The checker should clamp lookback to 3 before asking for history.
- Configured a lookback shorter than the minimum allowed window.
- Observed lookbacks: [3]
- Result: True
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the lookback normalization path is not protecting compute_flip_confidence from undersized history windows.

## 5. No configured volume floor means no volume rejection

Goal: When confidence_min_volume is not set, a valid flip-confidence alert should be allowed to trigger regardless of GP volume.
What is being tested: Disabled volume gate edge case for a supported single-item mode.
How it is being tested: Leave confidence_min_volume as None and feed the checker a zero-volume series with a high confidence score.
Setup: Create a saved alert with a threshold but no min-volume floor.
Assumptions: The checker should skip the volume gate entirely when the floor is unset.
Output:
- [START] No configured volume floor means no volume rejection
- [GOAL] When confidence_min_volume is not set, a valid flip-confidence alert should be allowed to trigger regardless of GP volume.
- [WHAT] Disabled volume gate edge case for a supported single-item mode.
- [HOW] Leave confidence_min_volume as None and feed the checker a zero-volume series with a high confidence score.
- [SETUP] Create a saved alert with a threshold but no min-volume floor.
- [ASSUMPTIONS] The checker should skip the volume gate entirely when the floor is unset.
- Configured a single-item alert with no configured volume floor.
- Result: True
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the min-volume branch is treating None like a real threshold instead of a disabled filter.

## 6. Missing historical data blocks the alert cleanly

Goal: A flip-confidence alert should not trigger when the requested history is unavailable.
What is being tested: Empty history edge case and the early return that prevents scoring with too few buckets.
How it is being tested: Return an empty timeseries list from the DB fetch stub.
Setup: Create a saved single-item alert with a normal threshold and a minimum volume floor.
Assumptions: The checker should stop before volume math or confidence scoring when there is no historical data.
Output:
- [START] Missing historical data blocks the alert cleanly
- [GOAL] A flip-confidence alert should not trigger when the requested history is unavailable.
- [WHAT] Empty history edge case and the early return that prevents scoring with too few buckets.
- [HOW] Return an empty timeseries list from the DB fetch stub.
- [SETUP] Create a saved single-item alert with a normal threshold and a minimum volume floor.
- [ASSUMPTIONS] The checker should stop before volume math or confidence scoring when there is no historical data.
- Configured a single-item alert whose history lookup returns no rows at all.
- Result: False
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the history-fetch branch is no longer protecting compute_flip_confidence from empty data.

## 7. Multi-item mode keeps only liquid items

Goal: A multi-item flip-confidence alert should return only the items that satisfy the minimum volume gate.
What is being tested: Multi-item return type, per-item volume filtering, and exclusion of low-volume items.
How it is being tested: Provide two selected items with identical confidence scores but very different GP volume totals.
Setup: Create a saved multi-item alert containing two item ids and give one of them a tiny series that falls below the floor.
Assumptions: The checker should evaluate both items and return only the liquid one.
Output:
- [START] Multi-item mode keeps only liquid items
- [GOAL] A multi-item flip-confidence alert should return only the items that satisfy the minimum volume gate.
- [WHAT] Multi-item return type, per-item volume filtering, and exclusion of low-volume items.
- [HOW] Provide two selected items with identical confidence scores but very different GP volume totals.
- [SETUP] Create a saved multi-item alert containing two item ids and give one of them a tiny series that falls below the floor.
- [ASSUMPTIONS] The checker should evaluate both items and return only the liquid one.
- Configured multi-item alert with one liquid item and one illiquid item.
- Result items: [{'item_id': '4151', 'item_name': 'Abyssal whip', 'confidence_score': 88.0, 'previous_score': None, 'trigger_rule': 'crosses_above', 'threshold': 70.0, 'consecutive_passes': 1}]
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, look for a regression in the item loop that applies min_volume after scoring instead of before.

## 8. Single-item alert blocks low GP volume

Goal: A single-item flip-confidence alert should not trigger when the total GP volume is below the configured floor.
What is being tested: Single-mode low-volume rejection and early return before scoring.
How it is being tested: Use a tiny synthetic series whose total GP volume is far below the limit while keeping the confidence score artificially high.
Setup: Create a saved single-item alert with a 10,000 GP minimum and feed it a tiny series that only totals a few hundred GP.
Assumptions: The checker should reject the item before compute_flip_confidence is consulted.
Output:
- [START] Single-item alert blocks low GP volume
- [GOAL] A single-item flip-confidence alert should not trigger when the total GP volume is below the configured floor.
- [WHAT] Single-mode low-volume rejection and early return before scoring.
- [HOW] Use a tiny synthetic series whose total GP volume is far below the limit while keeping the confidence score artificially high.
- [SETUP] Create a saved single-item alert with a 10,000 GP minimum and feed it a tiny series that only totals a few hundred GP.
- [ASSUMPTIONS] The checker should reject the item before compute_flip_confidence is consulted.
- Configured single-item alert with a very low-volume series.
- Result: False
- Expectation: the item should be filtered out before the confidence score is even used.
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, inspect the min-volume branch in check_flip_confidence_alert and the GP volume formula that sums high and low legs.

## 9. Single-item trigger respects the configured volume floor

Goal: A single-item flip-confidence alert should trigger when the item's total GP volume exceeds the configured minimum.
What is being tested: Single-mode trigger path, min-volume filtering, and single-item trigger payload storage.
How it is being tested: Use a synthetic three-bucket series whose GP volume is safely above the floor and force the confidence score above threshold.
Setup: Create a saved single-item alert with min volume 10,000 GP and a score threshold of 75.
Assumptions: The alert checker should accept a normal single-item configuration and return True when the item clears the floor.
Output:
- [START] Single-item trigger respects the configured volume floor
- [GOAL] A single-item flip-confidence alert should trigger when the item's total GP volume exceeds the configured minimum.
- [WHAT] Single-mode trigger path, min-volume filtering, and single-item trigger payload storage.
- [HOW] Use a synthetic three-bucket series whose GP volume is safely above the floor and force the confidence score above threshold.
- [SETUP] Create a saved single-item alert with min volume 10,000 GP and a score threshold of 75.
- [ASSUMPTIONS] The alert checker should accept a normal single-item configuration and return True when the item clears the floor.
- Configured single-item alert with a generous GP volume floor and a high score.
- Result: True
- Fetch calls: 1
- Score calls: 1
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, check the min-volume comparison in check_flip_confidence_alert and confirm the GP volume sum is being computed from all buckets.

## 10. Balanced volume distribution is allowed through

Goal: A concentration filter should not block items that spread volume across several buckets.
What is being tested: confidence_filter_vol_concentration pass path.
How it is being tested: Feed the checker a balanced three-bucket series that stays well below the 75 percent concentration limit.
Setup: Create a single-item alert with the same 75 percent concentration ceiling used in the blocking case.
Assumptions: The checker should evaluate the item and allow the score through when volume is spread out.
Output:
- [START] Balanced volume distribution is allowed through
- [GOAL] A concentration filter should not block items that spread volume across several buckets.
- [WHAT] confidence_filter_vol_concentration pass path.
- [HOW] Feed the checker a balanced three-bucket series that stays well below the 75 percent concentration limit.
- [SETUP] Create a single-item alert with the same 75 percent concentration ceiling used in the blocking case.
- [ASSUMPTIONS] The checker should evaluate the item and allow the score through when volume is spread out.
- Configured a balanced series where no single bucket dominates the total volume.
- Result: True
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the concentration filter may be too aggressive or using the wrong denominator.

## 11. Volume concentration filter rejects a single dominant bucket

Goal: A flip-confidence alert should skip items whose total volume is too concentrated in one bucket.
What is being tested: confidence_filter_vol_concentration rejection path.
How it is being tested: Build a synthetic timeseries where one bucket accounts for more than 75 percent of total trade count.
Setup: Create a single-item alert with a concentration ceiling of 75 percent.
Assumptions: The concentration filter is supposed to run after GP volume passes and before confidence scoring.
Output:
- [START] Volume concentration filter rejects a single dominant bucket
- [GOAL] A flip-confidence alert should skip items whose total volume is too concentrated in one bucket.
- [WHAT] confidence_filter_vol_concentration rejection path.
- [HOW] Build a synthetic timeseries where one bucket accounts for more than 75 percent of total trade count.
- [SETUP] Create a single-item alert with a concentration ceiling of 75 percent.
- [ASSUMPTIONS] The concentration filter is supposed to run after GP volume passes and before confidence scoring.
- Configured a series where one bucket dominates more than 75 percent of the trade count.
- Result: False
- [RESULT] PASS
Result: PASS
Prevention / next check: If this fails, the concentration ratio check or the bucket-volume sum is not being applied correctly.
