# Sustained Trigger Test Report

Last rewritten: 2026-04-16 07:12:39 Atlantic Daylight Time

Scope: sustained alert trigger behavior.

This file is rewritten whenever the suite runs.

## Suite Summary
- Status: completed in the test runner

## all_items_trigger
Goal: All-items sustained alerts should return the list of items that passed.
Expected: List
Observed: [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 100, 'current_price': 110, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}, {'item_id': 11802, 'item_name': 'Dragon crossbow', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 200, 'current_price': 220, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]
Setup: Two all-items candidates both complete the streak.
Assumptions: All-items mode returns the triggered item list rather than a bare boolean.
Output:
- return=[{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 100, 'current_price': 110, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}, {'item_id': 11802, 'item_name': 'Dragon crossbow', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 200, 'current_price': 220, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]

## multi_item_trigger
Goal: Multi-item sustained alerts should trigger when at least one watched item completes a streak.
Expected: True
Observed: True with payload [{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 100, 'current_price': 110, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]
Setup: One watched item is ready to trigger; the other is still warming up.
Assumptions: Multi-item sustained alerts return True and persist a list payload.
Output:
- return=True
- payload=[{'item_id': 4151, 'item_name': 'Abyssal whip', 'streak_direction': 'up', 'streak_count': 2, 'total_move_percent': 10.0, 'start_price': 100, 'current_price': 110, 'volume': 5000000, 'avg_volatility': 6.0, 'required_move': 6.0, 'time_window_minutes': 60, 'pressure_direction': None, 'pressure_strength': None}]

## single_direction_mismatch
Goal: A streak in the wrong direction should not trigger.
Expected: False
Observed: False
Setup: The streak is upward, but the alert is configured for downward moves.
Assumptions: Direction checks happen after the streak is counted.
Output:
- return=False

## single_low_volume
Goal: Sustained alerts must block items that do not meet the hourly GP volume gate.
Expected: False
Observed: False
Setup: The streak qualifies, but the liquidity gate does not.
Assumptions: min_volume is enforced after the streak logic.
Output:
- return=False

## single_no_streak
Goal: A streak that has not reached the required move count should not trigger.
Expected: False
Observed: False
Setup: Only one qualifying move is present.
Assumptions: The streak counter must reach the configured minimum.
Output:
- return=False

## single_up_trigger
Goal: Single-item sustained alerts should trigger when the configured streak completes.
Expected: True
Observed: True
Setup: A ready-to-trigger upward streak with fresh volume.
Assumptions: The seeded state already contains the previous move history.
Output:
- return=True
- payload={"item_id": 4151, "item_name": "Abyssal whip", "streak_direction": "up", "streak_count": 2, "total_move_percent": 10.0, "start_price": 100, "current_price": 110, "volume": 5000000, "avg_volatility": 6.0, "required_move": 6.0, "time_window_minutes": 60, "pressure_direction": null, "pressure_strength": null}

## single_down_trigger
Goal: Single-item sustained alerts should also trigger on downward streaks when configured.
Expected: True
Observed: True
Setup: A ready-to-trigger downward streak with fresh volume.
Assumptions: Direction 'down' should accept a negative streak.
Output:
- return=True
- payload={"item_id": 4151, "item_name": "Abyssal whip", "streak_direction": "down", "streak_count": 2, "total_move_percent": 9.0909, "start_price": 110, "current_price": 100, "volume": 5000000, "avg_volatility": 5.8182, "required_move": 5.8182, "time_window_minutes": 60, "pressure_direction": null, "pressure_strength": null}
