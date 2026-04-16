"""
Collective move trigger-behavior tests.

What:
    A focused 7-test suite covering when collective_move alerts should and
    should not trigger based on the alert configuration and supplied market
    data.

Why:
    Collective move alerts are a pure price-history path. These tests lock down
    the normal trigger cases, the direction rules, and the important failure
    cases so refactors do not change the semantics by accident.

How:
    1. Seed a controlled rolling price history.
    2. Run the collective-move checker directly.
    3. Vary reference type, direction, and calculation method.
    4. Rewrite a markdown report in test_output/ when the suite runs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "test_output" / "collective_move_trigger_test.md"
REPORT_LOCK = Lock()
TEST_CASES = []

ITEM_A = 4151
ITEM_B = 11802
ITEM_C = 11283
ITEM_D = 13576

ITEM_MAPPING = {
    str(ITEM_A): "Abyssal whip",
    str(ITEM_B): "Dragon crossbow",
    str(ITEM_C): "Dragonfire shield",
    str(ITEM_D): "Dragon warhammer",
}

BASE_TIMESTAMP = 1_700_000_000
TIME_FRAME_MINUTES = 3
THRESHOLD = 10.0

SINGLE_UP_SERIES = {
    ITEM_A: [100, 100, 100, 115],
}

SINGLE_DOWN_SERIES = {
    ITEM_A: [
        {"high": 200, "low": 100},
        {"high": 200, "low": 100},
        {"high": 200, "low": 100},
        {"high": 200, "low": 85},
    ],
}

MULTI_UP_SERIES = {
    ITEM_A: [100, 100, 100, 120],
    ITEM_B: [200, 200, 200, 220],
}

ALL_ITEMS_UP_SERIES = {
    ITEM_A: [100, 100, 100, 112],
    ITEM_B: [200, 200, 200, 216],
    ITEM_C: [300, 300, 300, 330],
}

WEIGHTED_SERIES = {
    ITEM_A: [1000, 1000, 1000, 1020],
    ITEM_B: [100, 100, 100, 150],
}

BELOW_THRESHOLD_SERIES = {
    ITEM_A: [100, 100, 100, 104],
}


def _is_test_failed(test_case):
    outcome = getattr(test_case, "_outcome", None)
    result = getattr(outcome, "result", None)
    if result is None:
        return False

    failed_ids = {
        test.id()
        for test, _ in (list(getattr(result, "failures", [])) + list(getattr(result, "errors", [])))
    }
    return test_case.id() in failed_ids


def _write_report():
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Collective Move Trigger Test Report",
        "",
        f"Updated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## Goal",
        "Verify that collective_move alerts trigger on the expected price movements and stay silent when the market data does not meet the alert configuration.",
        "",
        "## Coverage",
        "- single-item collective move triggers",
        "- multi-item collective move triggers",
        "- all-items collective move triggers",
        "- direction rules",
        "- simple vs weighted calculations",
        "- below-threshold behavior",
        "",
        "## Test Runs",
    ]

    if not TEST_CASES:
        lines.extend([
            "",
            "_No test cases have been recorded yet. This file is rewritten when the suite runs._",
        ])
    else:
        lines.append("")
        lines.append("| Test | Result | Scope | Goal |")
        lines.append("| --- | --- | --- | --- |")
        for case in TEST_CASES:
            lines.append(f"| `{case['name']}` | {case['status']} | {case['scope']} | {case['goal']} |")

        for case in TEST_CASES:
            lines.extend([
                "",
                f"### {case['name']}",
                f"- Status: {case['status']}",
                f"- Goal: {case['goal']}",
                f"- Checked: {case['checked']}",
                f"- How: {case['how']}",
                f"- Setup: {case['setup']}",
                f"- Assumptions: {case['assumptions']}",
                "",
                "#### Trace",
            ])
            for entry in case["trace"]:
                lines.append(f"- {entry}")
            lines.extend([
                "",
                "#### Result",
                case["result"],
            ])

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CollectiveMoveTriggerSuite(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with REPORT_LOCK:
            TEST_CASES.clear()
            _write_report()

    @classmethod
    def tearDownClass(cls):
        with REPORT_LOCK:
            _write_report()
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"collective-trigger-{self._testMethodName}",
            password="testpass123",
        )
        self._trace = []
        self._goal = ""
        self._how = ""
        self._setup = ""
        self._assumptions = ""
        self._result = ""

    def _log(self, message):
        print(message)
        self._trace.append(message)

    def _make_command(self):
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        cmd.sustained_state = {}
        cmd.dump_market_state = {"last_mids": {}, "market_drift": 0.0}
        cmd.get_item_mapping = lambda: ITEM_MAPPING
        return cmd

    def _make_alert(self, **overrides):
        defaults = {
            "user": self.user,
            "alert_name": "Collective Move Trigger Test",
            "type": "collective_move",
            "direction": "up",
            "reference": "high",
            "percentage": THRESHOLD,
            "time_frame": TIME_FRAME_MINUTES,
            "calculation_method": "simple",
            "is_all_items": False,
            "item_id": None,
            "item_ids": None,
            "reference_prices": None,
            "minimum_price": 1,
            "maximum_price": 1_000_000_000,
            "min_volume": 10_000_000,
            "show_notification": False,
            "is_active": True,
        }
        defaults.update(overrides)
        if isinstance(defaults.get("item_ids"), list):
            defaults["item_ids"] = json.dumps(defaults["item_ids"])
        if isinstance(defaults.get("reference_prices"), dict):
            defaults["reference_prices"] = json.dumps(defaults["reference_prices"])
        return Alert.objects.create(**defaults)

    def _normalize_step(self, step):
        if isinstance(step, dict):
            high = step.get("high")
            low = step.get("low", high)
            return high, low
        if isinstance(step, tuple):
            return step
        return step, step

    def _make_reference_prices(self, series_map, reference_type="high"):
        reference_prices = {}
        for item_id, steps in series_map.items():
            high, low = self._normalize_step(steps[0])
            if reference_type == "low":
                reference_prices[str(item_id)] = low
            elif reference_type == "average":
                reference_prices[str(item_id)] = (high + low) // 2
            else:
                reference_prices[str(item_id)] = high
        return reference_prices

    def _run_collective(self, command, alert, series_map):
        lengths = {len(series) for series in series_map.values()}
        self.assertEqual(len(lengths), 1, "All series in a collective move test must have the same length.")

        result = None
        step_count = next(iter(lengths))
        for step_index in range(step_count):
            current_ts = BASE_TIMESTAMP + (step_index * 60)
            all_prices = {}
            for item_id, series in series_map.items():
                high, low = self._normalize_step(series[step_index])
                all_prices[str(item_id)] = {
                    "high": high,
                    "low": low,
                    "highTime": current_ts,
                    "lowTime": current_ts,
                }

            self._log(
                f"Step {step_index + 1}/{step_count}: ts={current_ts}, "
                f"prices={ {item_id: all_prices[str(item_id)] for item_id in series_map} }"
            )

            with patch("Website.management.commands.check_alerts.time.time", return_value=current_ts):
                result = command.check_collective_move_alert(alert, all_prices)

            self._log(f"Step {step_index + 1} result: {result!r}")

        payload = json.loads(alert.triggered_data) if alert.triggered_data else None
        self._log(f"Final triggered_data: {payload!r}")
        return result, payload

    def _record_case(self, *, name, scope, status, goal, how, setup, assumptions, result, trace):
        TEST_CASES.append({
            "name": name,
            "scope": scope,
            "status": status,
            "goal": goal,
            "how": how,
            "setup": setup,
            "assumptions": assumptions,
            "result": result,
            "trace": list(trace),
            "checked": self.id(),
        })
        with REPORT_LOCK:
            _write_report()

    def _assert_trigger(self, *, name, goal, how, setup, assumptions, alert_kwargs, series_map, expected_result=True, expected_payload_check=None, scope="single"):
        self._goal = goal
        self._how = how
        self._setup = setup
        self._assumptions = assumptions
        self._log(f"Test: {name}")
        self._log(f"Goal: {goal}")
        self._log(f"How: {how}")
        self._log(f"Setup: {setup}")
        self._log(f"Assumptions: {assumptions}")
        self._log(f"Alert kwargs: {alert_kwargs}")
        command = self._make_command()
        alert = self._make_alert(**alert_kwargs)
        result, payload = self._run_collective(command, alert, series_map)
        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected {expected_result!r}; observed {result!r}."
        self.assertEqual(result, expected_result)
        if expected_result:
            self.assertIsNotNone(payload)
            if expected_payload_check is not None:
                expected_payload_check(payload)
        self._record_case(
            name=name,
            scope=scope,
            status="PASS",
            goal=goal,
            how=how,
            setup=setup,
            assumptions=assumptions,
            result=self._result,
            trace=self._trace,
        )

    def _assert_no_trigger(self, *, name, goal, how, setup, assumptions, alert_kwargs, series_map, scope="single"):
        self._assert_trigger(
            name=name,
            goal=goal,
            how=how,
            setup=setup,
            assumptions=assumptions,
            alert_kwargs=alert_kwargs,
            series_map=series_map,
            expected_result=False,
            expected_payload_check=None,
            scope=scope,
        )

    def test_single_item_up_triggers(self):
        self._assert_trigger(
            name="single_item_up_triggers",
            goal="Confirm a single-item collective move alert triggers on a clear upward move.",
            how="Run a 4-step price history with a 15% rise on one monitored item.",
            setup="Single item, high reference pricing, and no volume fixtures.",
            assumptions="collective_move should use the rolling price history only.",
            alert_kwargs={
                "item_id": ITEM_A,
                "reference_prices": self._make_reference_prices(SINGLE_UP_SERIES),
                "direction": "up",
            },
            series_map=SINGLE_UP_SERIES,
            expected_payload_check=lambda payload: (
                self.assertEqual(payload["items_in_response"], 1),
                self.assertEqual(payload["items"][0]["item_id"], str(ITEM_A)),
            ),
        )

    def test_single_item_down_triggers_with_low_reference(self):
        self._assert_trigger(
            name="single_item_down_triggers_with_low_reference",
            goal="Confirm the single-item path respects downward collective moves.",
            how="Use a low reference price and a 15% fall across the warm window.",
            setup="Single item, low reference type, and a downward price series.",
            assumptions="The low reference path should still trigger when the threshold is met.",
            alert_kwargs={
                "item_id": ITEM_A,
                "reference": "low",
                "direction": "down",
                "reference_prices": self._make_reference_prices(SINGLE_DOWN_SERIES, reference_type="low"),
            },
            series_map=SINGLE_DOWN_SERIES,
            expected_payload_check=lambda payload: (
                self.assertEqual(payload["direction"], "down"),
                self.assertEqual(payload["items_in_response"], 1),
            ),
        )

    def test_multi_item_up_triggers(self):
        self._assert_trigger(
            name="multi_item_up_triggers",
            goal="Confirm the multi-item collective move path triggers when the average change clears the threshold.",
            how="Run two monitored items through the same rising series.",
            setup="Two monitored items, both rising, with a simple arithmetic average.",
            assumptions="Missing volume rows are irrelevant to collective_move.",
            alert_kwargs={
                "item_ids": [ITEM_A, ITEM_B],
                "reference_prices": self._make_reference_prices(MULTI_UP_SERIES),
                "direction": "up",
            },
            series_map=MULTI_UP_SERIES,
            expected_payload_check=lambda payload: (
                self.assertEqual(payload["items_in_response"], 2),
                self.assertEqual({item["item_id"] for item in payload["items"]}, {str(ITEM_A), str(ITEM_B)}),
            ),
            scope="multi",
        )

    def test_all_items_up_triggers(self):
        self._assert_trigger(
            name="all_items_up_triggers",
            goal="Confirm the all-items collective move path triggers when all tracked items move together.",
            how="Run the all-items path across three monitored items, all rising above the threshold.",
            setup="All-items collective move alert and a rising three-item market snapshot.",
            assumptions="The alert should use its price history only.",
            alert_kwargs={
                "is_all_items": True,
                "reference_prices": self._make_reference_prices(ALL_ITEMS_UP_SERIES),
                "direction": "up",
            },
            series_map=ALL_ITEMS_UP_SERIES,
            expected_payload_check=lambda payload: self.assertEqual(payload["items_in_response"], 3),
            scope="all",
        )

    def test_below_threshold_stays_false(self):
        self._assert_no_trigger(
            name="below_threshold_stays_false",
            goal="Confirm collective move stays false when the price change does not reach the threshold.",
            how="Run a 4% move against a 10% threshold.",
            setup="Single-item series that never reaches the trigger threshold.",
            assumptions="No amount of market noise should promote a below-threshold move to a trigger.",
            alert_kwargs={
                "item_id": ITEM_A,
                "percentage": 5.0,
                "reference_prices": self._make_reference_prices(BELOW_THRESHOLD_SERIES),
                "direction": "up",
            },
            series_map=BELOW_THRESHOLD_SERIES,
        )

    def test_direction_mismatch_stays_false(self):
        self._assert_no_trigger(
            name="direction_mismatch_stays_false",
            goal="Confirm a direction mismatch prevents a trigger even when the magnitude is high enough.",
            how="Run an upward price move against a downward-only alert.",
            setup="Single-item upward series and an alert configured for down-only triggers.",
            assumptions="The checker should respect direction after the threshold is satisfied.",
            alert_kwargs={
                "item_id": ITEM_A,
                "direction": "down",
                "reference_prices": self._make_reference_prices(SINGLE_UP_SERIES),
            },
            series_map=SINGLE_UP_SERIES,
        )

    def test_weighted_path_stays_false_when_simple_would_trigger(self):
        self._assert_no_trigger(
            name="weighted_path_stays_false_when_simple_would_trigger",
            goal="Confirm the weighted collective move path can stay below threshold even when the simple average would not.",
            how="Run the same two-item market through a weighted alert that dampens the smaller mover.",
            setup="Two-item market with one large expensive item and one smaller sharper mover.",
            assumptions="Weighted averaging should honor the alert's configuration instead of the simple mean.",
            alert_kwargs={
                "is_all_items": True,
                "calculation_method": "weighted",
                "percentage": 10.0,
                "reference": "average",
                "reference_prices": self._make_reference_prices(WEIGHTED_SERIES, reference_type="average"),
            },
            series_map=WEIGHTED_SERIES,
            scope="all",
        )
