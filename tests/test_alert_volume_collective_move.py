"""
Collective move volume-behavior test suite.

What:
    Dedicated coverage for collective_move alerts proving that HourlyItemVolume
    data is not part of this checker path, while the actual price-based rules
    still behave normally across single-item, multi-item, and all-items scopes.

Why:
    Collective move alerts do not have an explicit hourly-volume restriction in
    check_alerts.py. These tests lock that behavior down so future refactors do
    not accidentally add a hidden volume gate or let unrelated volume rows alter
    the result.

How:
    Build real Alert fixtures, seed the command's rolling price history with
    controlled time steps, and call Command.check_collective_move_alert()
    directly. A markdown report is rewritten every time the suite runs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "test_output" / "alert_volume_collective_move.md"
REPORT_LOCK = Lock()
TEST_CASES = []

ITEM_A = 4151
ITEM_B = 11802
ITEM_C = 11283
ITEM_D = 13576
OTHER_ITEM_A = 90001
OTHER_ITEM_B = 90002

ITEM_MAPPING = {
    str(ITEM_A): "Abyssal whip",
    str(ITEM_B): "Dragon crossbow",
    str(ITEM_C): "Dragonfire shield",
    str(ITEM_D): "Dragon warhammer",
    str(OTHER_ITEM_A): "Unrelated item A",
    str(OTHER_ITEM_B): "Unrelated item B",
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
        "# Collective Move Volume Test Report",
        "",
        f"Updated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## Goal",
        "Verify that collective_move alerts ignore HourlyItemVolume rows and still obey the price-based rules that define the alert.",
        "",
        "## Coverage",
        "- single-item collective move alerts",
        "- multi-item collective move alerts",
        "- all-items collective move alerts",
        "- simple vs weighted calculations",
        "- missing, stale, and unrelated HourlyItemVolume rows",
        "- inclusive threshold behavior",
        "",
        "## Assumptions",
        "- collective_move does not consult HourlyItemVolume today.",
        "- min_volume is intentionally set in many cases to prove it has no effect on this alert type.",
        "",
        "## Test Runs",
    ]

    if not TEST_CASES:
        lines.extend([
            "",
            "_No test cases have been recorded yet. This file is rewritten when the suite runs._",
        ])
    else:
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


class CollectiveMoveVolumeMixin:
    TIME_FRAME_MINUTES = 3
    THRESHOLD = 10.0
    MIN_VOLUME = 10_000_000
    BASE_TIMESTAMP = 1_700_000_000

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

    EXACT_THRESHOLD_SERIES = {
        ITEM_A: [100, 100, 100, 110],
    }

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"collective-volume-{self._testMethodName}",
            email=f"{self._testMethodName}@example.com",
            password="testpass123",
        )
        self._trace = []

    def _begin_case(self, goal, how, setup, assumptions):
        self._goal = goal
        self._how = how
        self._setup = setup
        self._assumptions = assumptions
        self._trace = []
        self._result = "Pending"

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

    def _create_volume(self, item_id, volume, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=ITEM_MAPPING.get(str(item_id), f"Item {item_id}"),
            volume=volume,
            timestamp=str(int((timezone.now() - timedelta(minutes=minutes_ago)).timestamp())),
        )

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

    def _make_alert(self, **overrides):
        defaults = {
            "user": self.user,
            "alert_name": "Collective Move Volume Test",
            "type": "collective_move",
            "direction": "up",
            "reference": "high",
            "percentage": self.THRESHOLD,
            "time_frame": self.TIME_FRAME_MINUTES,
            "calculation_method": "simple",
            "is_all_items": False,
            "item_id": None,
            "item_ids": None,
            "reference_prices": None,
            "minimum_price": 1,
            "maximum_price": 1_000_000_000,
            "min_volume": self.MIN_VOLUME,
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

    def _run_collective(self, command, alert, series_map):
        lengths = {len(series) for series in series_map.values()}
        self.assertEqual(len(lengths), 1, "All series in a collective move test must have the same length.")

        result = None
        step_count = next(iter(lengths))
        for step_index in range(step_count):
            current_ts = self.BASE_TIMESTAMP + (step_index * 60)
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

    def _compare_runs(self, baseline, comparison):
        self.assertEqual(baseline[0], comparison[0])
        self.assertEqual(baseline[1], comparison[1])

    def tearDown(self):
        record = {
            "name": self.id().split(".")[-1],
            "status": "FAIL" if _is_test_failed(self) else "PASS",
            "goal": getattr(self, "_goal", "No goal recorded."),
            "checked": self.id(),
            "how": getattr(self, "_how", "No method recorded."),
            "setup": getattr(self, "_setup", "No setup recorded."),
            "assumptions": getattr(self, "_assumptions", "No assumptions recorded."),
            "trace": list(getattr(self, "_trace", [])),
            "result": getattr(self, "_result", "No result recorded."),
        }

        with REPORT_LOCK:
            TEST_CASES.append(record)
            _write_report()

        super().tearDown()


class CollectiveMoveVolumeTests(CollectiveMoveVolumeMixin, TestCase):
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

    def test_single_item_up_triggers_without_volume_rows(self):
        self._begin_case(
            goal="Verify a single-item collective move alert triggers on a clear upward move.",
            how="Run a 4-step price history with a 15% rise on one monitored item and no HourlyItemVolume rows.",
            setup="Single item, high reference pricing, and no volume fixtures at all.",
            assumptions="collective_move should not consult HourlyItemVolume, so the missing rows should not matter.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_id=ITEM_A,
            reference_prices=self._make_reference_prices(self.SINGLE_UP_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.SINGLE_UP_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["items_in_response"], 1)
        self.assertEqual(payload["items"][0]["item_id"], str(ITEM_A))

    def test_single_item_down_triggers_with_low_reference_without_volume_rows(self):
        self._begin_case(
            goal="Verify the single-item path respects downward collective moves.",
            how="Use a low reference price series that falls 15% across the warm window with no volume rows present.",
            setup="Single item, low reference type, and a downward price series.",
            assumptions="The low reference path should behave like the live checker and still ignore volume data.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_id=ITEM_A,
            reference="low",
            direction="down",
            reference_prices=self._make_reference_prices(self.SINGLE_DOWN_SERIES, reference_type="low"),
        )

        result, payload = self._run_collective(command, alert, self.SINGLE_DOWN_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["direction"], "down")
        self.assertEqual(payload["items_in_response"], 1)

    def test_multi_item_up_triggers_without_volume_rows(self):
        self._begin_case(
            goal="Verify the multi-item collective move path triggers when the average change clears the threshold.",
            how="Run two monitored items through the same rising series with no HourlyItemVolume rows.",
            setup="Two monitored items, both rising, with a simple arithmetic average.",
            assumptions="Missing volume data should not block the alert because collective_move has no volume gate.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_ids=[ITEM_A, ITEM_B],
            reference_prices=self._make_reference_prices(self.MULTI_UP_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.MULTI_UP_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["items_in_response"], 2)
        self.assertEqual({item["item_id"] for item in payload["items"]}, {str(ITEM_A), str(ITEM_B)})

    def test_all_items_up_triggers_without_volume_rows(self):
        self._begin_case(
            goal="Verify the all-items collective move path triggers with a fully liquid-looking price move but no volume data.",
            how="Run the all-items path across three monitored items, all rising above the threshold, with no HourlyItemVolume rows.",
            setup="All-items collective move alert and a rising three-item market snapshot.",
            assumptions="The alert should use its price history only; the absence of volume data should be irrelevant.",
        )
        command = self._make_command()
        alert = self._make_alert(
            is_all_items=True,
            reference_prices=self._make_reference_prices(self.ALL_ITEMS_UP_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.ALL_ITEMS_UP_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["items_in_response"], 3)
        self.assertEqual({item["item_id"] for item in payload["items"]}, {str(ITEM_A), str(ITEM_B), str(ITEM_C)})

    def test_weighted_all_items_differs_from_simple_average(self):
        self._begin_case(
            goal="Verify the weighted collective move path still obeys its own price rule and can differ from simple averaging.",
            how="Run the same two-item market through simple and weighted alerts, then compare the outcomes.",
            setup="Two all-items alerts, same price data, one simple and one weighted.",
            assumptions="The weighted path should still be a pure price rule and not be influenced by HourlyItemVolume.",
        )
        series = {
            ITEM_A: [1000, 1000, 1000, 1020],
            ITEM_B: [100, 100, 100, 150],
        }
        simple_command = self._make_command()
        weighted_command = self._make_command()
        simple_alert = self._make_alert(
            is_all_items=True,
            calculation_method="simple",
            percentage=10.0,
            reference="average",
            reference_prices=self._make_reference_prices(series, reference_type="average"),
        )
        weighted_alert = self._make_alert(
            is_all_items=True,
            calculation_method="weighted",
            percentage=10.0,
            reference="average",
            reference_prices=self._make_reference_prices(series, reference_type="average"),
        )

        simple_result, simple_payload = self._run_collective(simple_command, simple_alert, series)
        weighted_result, weighted_payload = self._run_collective(weighted_command, weighted_alert, series)

        self._log(f"Simple result: {simple_result!r}")
        self._log(f"Weighted result: {weighted_result!r}")
        self._log(f"Simple payload: {simple_payload!r}")
        self._log(f"Weighted payload: {weighted_payload!r}")
        self._result = (
            f"Expected simple=True and weighted=False; observed simple={simple_result!r}, "
            f"weighted={weighted_result!r}."
        )

        self.assertTrue(simple_result)
        self.assertFalse(weighted_result)
        self.assertIsInstance(simple_payload, dict)
        self.assertIsNone(weighted_payload)

    def test_missing_volume_rows_do_not_block_single_item_trigger(self):
        self._begin_case(
            goal="Confirm that a missing HourlyItemVolume row does not block a collective move trigger.",
            how="Run a single-item alert with a huge min_volume value and no volume rows at all.",
            setup="Single item, empty HourlyItemVolume table for that item, and a valid rising series.",
            assumptions="collective_move should ignore the volume gate entirely, so missing data must not matter.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_id=ITEM_A,
            min_volume=99_999_999,
            reference_prices=self._make_reference_prices(self.SINGLE_UP_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.SINGLE_UP_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True with no volume rows; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)

    def test_unrelated_volume_rows_do_not_change_multi_item_result(self):
        self._begin_case(
            goal="Confirm that volume rows for unrelated items do not alter the collective move result.",
            how="Run the same multi-item series twice, once with no volume rows and once with unrelated rows only.",
            setup="Two monitored items, plus HourlyItemVolume rows for items outside the alert scope.",
            assumptions="Unrelated volume rows should be a no-op because collective_move never reads them.",
        )
        base_series = self.MULTI_UP_SERIES

        baseline_command = self._make_command()
        baseline_alert = self._make_alert(
            item_ids=[ITEM_A, ITEM_B],
            reference_prices=self._make_reference_prices(base_series),
            direction="up",
        )
        baseline_result, baseline_payload = self._run_collective(baseline_command, baseline_alert, base_series)

        self._create_volume(OTHER_ITEM_A, 5, minutes_ago=5)
        self._create_volume(OTHER_ITEM_B, 2, minutes_ago=180)

        volume_command = self._make_command()
        volume_alert = self._make_alert(
            item_ids=[ITEM_A, ITEM_B],
            reference_prices=self._make_reference_prices(base_series),
            direction="up",
        )
        volume_result, volume_payload = self._run_collective(volume_command, volume_alert, base_series)

        self._log(f"Baseline result: {baseline_result!r}")
        self._log(f"Volume-row result: {volume_result!r}")
        self._log(f"Baseline payload: {baseline_payload!r}")
        self._log(f"Volume-row payload: {volume_payload!r}")
        self._result = "Expected identical results with and without unrelated volume rows."

        self._compare_runs((baseline_result, baseline_payload), (volume_result, volume_payload))

    def test_stale_volume_rows_do_not_change_all_items_result(self):
        self._begin_case(
            goal="Confirm that stale HourlyItemVolume rows do not alter the all-items collective move result.",
            how="Run the same all-items series twice, once clean and once with stale volume rows for the monitored items.",
            setup="All-items alert, valid rising series, and stale volume rows older than the freshness window.",
            assumptions="Since collective_move ignores volume entirely, stale rows should be a pure no-op.",
        )
        base_series = self.ALL_ITEMS_UP_SERIES

        baseline_command = self._make_command()
        baseline_alert = self._make_alert(
            is_all_items=True,
            reference_prices=self._make_reference_prices(base_series),
            direction="up",
        )
        baseline_result, baseline_payload = self._run_collective(baseline_command, baseline_alert, base_series)

        for item_id in (ITEM_A, ITEM_B, ITEM_C):
            self._create_volume(item_id, 50_000, minutes_ago=180)

        stale_command = self._make_command()
        stale_alert = self._make_alert(
            is_all_items=True,
            reference_prices=self._make_reference_prices(base_series),
            direction="up",
        )
        stale_result, stale_payload = self._run_collective(stale_command, stale_alert, base_series)

        self._log(f"Baseline result: {baseline_result!r}")
        self._log(f"Stale-volume result: {stale_result!r}")
        self._log(f"Baseline payload: {baseline_payload!r}")
        self._log(f"Stale-volume payload: {stale_payload!r}")
        self._result = "Expected identical results with and without stale volume rows."

        self._compare_runs((baseline_result, baseline_payload), (stale_result, stale_payload))

    def test_price_change_below_threshold_stays_false_without_volume_rows(self):
        self._begin_case(
            goal="Confirm collective move still obeys the underlying percentage threshold.",
            how="Run a series that only moves 4% against a 10% threshold with no volume rows present.",
            setup="Single-item collective move alert and a price series that never reaches the trigger threshold.",
            assumptions="No amount of missing volume data should turn a below-threshold move into a trigger.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_id=ITEM_A,
            percentage=5.0,
            reference_prices=self._make_reference_prices(self.BELOW_THRESHOLD_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.BELOW_THRESHOLD_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected False; observed {result!r}."
        self.assertFalse(result)
        self.assertIsNone(payload)

    def test_exact_threshold_is_inclusive_without_volume_rows(self):
        self._begin_case(
            goal="Confirm the collective move threshold is inclusive at equality.",
            how="Run a 10% change against a 10% threshold and verify the alert fires without any volume rows.",
            setup="Single-item collective move alert and a series that lands exactly on the threshold.",
            assumptions="The checker should treat equality as a valid trigger the same way other alert types do.",
        )
        command = self._make_command()
        alert = self._make_alert(
            item_id=ITEM_A,
            percentage=10.0,
            reference_prices=self._make_reference_prices(self.EXACT_THRESHOLD_SERIES),
            direction="up",
        )

        result, payload = self._run_collective(command, alert, self.EXACT_THRESHOLD_SERIES)

        self._log(f"Observed result: {result!r}")
        self._log(f"Observed payload: {payload!r}")
        self._result = f"Expected True at exact threshold; observed {result!r}."
        self.assertTrue(result)
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["items_in_response"], 1)
