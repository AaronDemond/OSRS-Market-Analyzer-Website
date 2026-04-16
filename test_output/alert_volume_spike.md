# Alert Volume Spike Test Report

Generated at: 2026-04-16T09:53:44.390576+00:00

This file is rewritten by `tests/test_alert_volume_spike.py` every time the suite runs.

## 1. all_items_all_low_volume

- Goal: An all-items spike alert should return False when nothing clears the volume filter.
- What is being tested: all-items spike all-low-volume handling
- How it is being tested: Make every candidate spike, but keep every hourly volume row below the minimum.
- Setup: All-items spike alert with only low-volume spiking items.
- Assumptions: The alert should not emit an empty list as if it were a hit.
- Expected result: The alert should return False because no item satisfies the volume restriction.
- Observed result: {
  "result_count": 0,
  "triggered_data": [],
  "triggered_ids": []
}

### Captured Output
```text
(no command output captured)
```

## 2. all_items_mixed_volume

- Goal: An all-items spike alert should include only the items that meet the volume floor.
- What is being tested: all-items spike volume filtering
- How it is being tested: Evaluate four spiking items, then let the hourly volume filter trim the low-volume ones.
- Setup: All-items spike alert with a mix of high-volume, low-volume, and missing-volume candidates.
- Assumptions: The list should include only items that both spike and meet min_volume.
- Expected result: The alert should return a list containing the high-volume items only.
- Observed result: {
  "result_count": 2,
  "triggered_data": [
    {
      "baseline": 10000,
      "current": 12000,
      "direction": "both",
      "item_id": "100",
      "item_name": "Dragon Bones",
      "percent_change": 20.0,
      "reference": "high"
    },
    {
      "baseline": 30000000,
      "current": 36000000,
      "direction": "both",
      "item_id": "400",
      "item_name": "Armadyl Godsword",
      "percent_change": 20.0,
      "reference": "high"
    }
  ],
  "triggered_ids": [
    "100",
    "400"
  ]
}

### Captured Output
```text
(no command output captured)
```

## 3. multi_item_all_low_volume

- Goal: A multi-item spike alert should return False when every spiking item is under volume.
- What is being tested: multi-item spike all-low-volume handling
- How it is being tested: Make every watched item spike hard, but keep all hourly volume rows below the minimum.
- Setup: Multi-item spike alert watching three items, all with low hourly volume.
- Assumptions: Items that spike but fail the volume filter must not appear in the match list.
- Expected result: The alert should return False and should not invent any triggered items.
- Observed result: {
  "result_count": 0,
  "triggered_data": [],
  "triggered_ids": []
}

### Captured Output
```text
(no command output captured)
```

## 4. multi_item_mixed_volume

- Goal: A multi-item spike alert should keep high-volume items and filter low-volume ones.
- What is being tested: multi-item spike volume filtering
- How it is being tested: Trigger three watched items at once, but make one of them fall below the hourly volume floor.
- Setup: Multi-item spike alert watching items 100, 200, and 300 with one low-volume row.
- Assumptions: Every item meets the price spike threshold, so only volume should decide inclusion.
- Expected result: The alert should return a list with the high-volume items only.
- Observed result: {
  "result_count": 2,
  "triggered_data": [
    {
      "baseline": 10000,
      "current": 12000,
      "direction": "both",
      "item_id": "100",
      "item_name": "Dragon Bones",
      "percent_change": 20.0,
      "reference": "high"
    },
    {
      "baseline": 15000000,
      "current": 18000000,
      "direction": "both",
      "item_id": "300",
      "item_name": "Bandos Chestplate",
      "percent_change": 20.0,
      "reference": "high"
    }
  ],
  "triggered_ids": [
    "100",
    "300"
  ]
}

### Captured Output
```text
TRIGGERED (multi-item spike): 2/3 items exceed threshold
```

## 5. fresh_volume_overrides_old_snapshot

- Goal: The command should prefer the freshest parseable volume snapshot, even if an older row is larger.
- What is being tested: volume recency and row ordering edge case
- How it is being tested: Write a stale high-volume row first, then a newer low-volume row and verify the newer row wins.
- Setup: Single-item spike alert with two volume rows for the same item.
- Assumptions: The freshness filter should reject stale volume, not just sort by timestamp text.
- Expected result: The alert should return False because the freshest usable snapshot is below the volume floor.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

### Notes
This is the most important regression guard for the volume-recency fix.

## 6. single_item_warmup_blocks

- Goal: A single spike alert should not trigger until the warmup baseline exists.
- What is being tested: single-item spike warmup interaction
- How it is being tested: Deliberately skip price-history seeding, even though the item has fresh and high volume.
- Setup: Single-item spike alert watching item 100 with good volume but no old baseline price.
- Assumptions: Warmup must happen before volume checks can matter.
- Expected result: The alert should return False because the rolling window is not warmed up.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

## 7. single_item_below_minimum

- Goal: A single spike alert should stay silent when hourly volume falls below the minimum.
- What is being tested: single-item spike below-threshold volume
- How it is being tested: Use the same price spike as the happy path, but give the item only 500,000 GP of hourly volume.
- Setup: Single-item spike alert watching item 100 with a fresh low-volume snapshot.
- Assumptions: The volume filter must be checked after the price spike threshold is met.
- Expected result: The alert should return False because volume is under the configured floor.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

## 8. single_item_missing_volume

- Goal: A single spike alert should not trigger when no hourly volume row exists.
- What is being tested: single-item spike missing-volume handling
- How it is being tested: Provide a valid spike and baseline, but skip creating any HourlyItemVolume row.
- Setup: Single-item spike alert watching item 100 with no volume snapshot at all.
- Assumptions: Missing volume should be treated as unsafe and block the trigger.
- Expected result: The alert should return False because the item has no volume data.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

## 9. single_item_stale_volume

- Goal: A single spike alert should reject stale hourly volume rows.
- What is being tested: single-item spike stale-volume rejection
- How it is being tested: Store a strong spike and baseline, but make the volume snapshot older than the 130-minute freshness window.
- Setup: Single-item spike alert watching item 100 with a 131-minute-old ISO volume timestamp.
- Assumptions: Hourly volume rows older than the freshness window should behave like missing data.
- Expected result: The alert should return False because the volume snapshot is stale.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

## 10. single_item_exact_minimum

- Goal: A single spike alert should trigger when volume matches the minimum exactly.
- What is being tested: single-item spike exact-threshold volume
- How it is being tested: Use the same 20% spike, but set hourly volume to exactly 1,000,000 GP.
- Setup: Single-item spike alert watching item 100 with a volume row equal to min_volume.
- Assumptions: The filter uses a strict less-than comparison, so equality should pass.
- Expected result: The alert should return True because exact-threshold volume is allowed.
- Observed result: {
  "result": true,
  "triggered_data": {
    "baseline": 10000,
    "current": 12000,
    "direction": "both",
    "percent_change": 20.0,
    "reference": "high",
    "time_frame_minutes": 60
  }
}

### Captured Output
```text
(no command output captured)
```

## 11. single_item_above_minimum

- Goal: A single spike alert should trigger when volume is comfortably above the minimum.
- What is being tested: single-item spike volume gating
- How it is being tested: Seed warm price history, provide a 20% spike, and attach a fresh high-volume snapshot.
- Setup: Single-item spike alert watching item 100 with min_volume=1,000,000 and a fresh 5,000,000 GP volume row.
- Assumptions: Hourly volume is stored as a recent Unix epoch string and the warmup window has already elapsed.
- Expected result: The alert should return True and persist a triggered_data payload.
- Observed result: {
  "result": true,
  "triggered_data": {
    "baseline": 10000,
    "current": 12000,
    "direction": "both",
    "percent_change": 20.0,
    "reference": "high",
    "time_frame_minutes": 60
  }
}

### Captured Output
```text
(no command output captured)
```

## 12. spike_requires_min_volume

- Goal: Spike alerts should reject configurations that do not define min_volume.
- What is being tested: spike alert configuration validation
- How it is being tested: Build an otherwise valid spike alert, but leave min_volume unset.
- Setup: Single-item spike alert watching item 100 with a fresh volume row but no minimum volume field.
- Assumptions: The command validates min_volume before it does any real work.
- Expected result: The alert should return False because min_volume is required.
- Observed result: {
  "result": false,
  "triggered_data": {}
}

### Captured Output
```text
(no command output captured)
```

