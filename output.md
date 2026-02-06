# Sustained Alert Volume Debugging — Summary

## The sustained alert code is actually working correctly

I confirmed by manually running it. No crashes, no errors, the volume DB lookup works fine (849,714 records in the `HourlyItemVolume` table).

---

## What's Happening

Every check cycle, prices show `change=0.0000%` because the OSRS Wiki API doesn't update faster than its cache interval. The streaks never build (`streak 0 < 2 required`), so alerts don't trigger. This is **normal sustained alert behavior** — they need real price movement over multiple consecutive checks.

---

## What I Fixed

- **`scripts/update_volumes.py`**: `MAX_WORKERS` was accidentally set to `15` instead of `6` — fixed back to `6`

---

## Debug Statements Added to `check_alerts.py`

1. **Alert entry** — logs all alert config (ID, type, min_volume, min_moves, etc.)
2. **State initialization** — logs when an item is seen for the first time
3. **Every price check** — logs current price, change %, streak count, direction, volatility buffer
4. **Each failure point** — logs exactly WHY an item failed:
   - Time window exceeded
   - Streak too short
   - Direction mismatch
   - Volume too low / no volume data
   - Volatility buffer too small
   - Total move below required threshold
   - Pressure check failed
5. **Volume lookup** — logs the DB query result, comparison against `min_volume`
6. **Trigger success** — logs when an item actually triggers

---

## Next Steps

If the alert still doesn't trigger after running for a while, the debug output will show exactly which gate is blocking it (streak count, volatility buffer, volume, etc.). **Restart `check_alerts.py` and watch the console output.**
