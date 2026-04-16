"""
Dump trigger-behavior tests.

What:
    A focused 7-test suite covering when dump alerts should and should not
    trigger based on alert configuration and supplied market data.

Why:
    Dump alerts have several moving parts: liquidity floor, relative volume,
    shock, sell ratio, discount, and confirmation state. These tests lock down
    the main trigger paths and the most important failure cases.

How:
    1. Seed a small synthetic market with a few monitored items.
    2. Run the dump checker in the normal two-step pattern.
    3. Vary alert scope and hourly volume inputs to prove the trigger logic.
    4. Rewrite a markdown report in test_output/ when the suite runs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from pathlib import Path
from threading import Lock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, FiveMinTimeSeries, HourlyItemVolume


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "test_output" / "dump_trigger_test.md"
REPORT_LOCK = Lock()
TEST_CASES = []

ITEM_A_ID = 4151
ITEM_B_ID = 11802
ITEM_C_ID = 13576
ITEM_D_ID = 11832

BACKGROUND_ITEM_IDS = list(range(90201, 90211))

ITEM_MAPPING = {
    str(ITEM_A_ID): "Abyssal whip",
    str(ITEM_B_ID): "Dragon crossbow",
    str(ITEM_C_ID): "Dragon warhammer",
    str(ITEM_D_ID): "Bandos chestplate",
}
ITEM_MAPPING.update({str(item_id): f"Background {item_id}" for item_id in BACKGROUND_ITEM_IDS})

NORMAL_HIGH = 1000
NORMAL_LOW = 1000
DUMP_HIGH = 950
DUMP_LOW = 880
DEFAULT_HIGH_VOL = 30
DEFAULT_LOW_VOL = 170


def _epoch_string(minutes_ago):
    return str(int((timezone.now() - timedelta(minutes=minutes_ago)).timestamp()))


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
        "# Dump Trigger Test Report",
        "",
        f"Updated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## Goal",
        "Verify that dump alerts trigger when the alert configuration and market data support it, and stay silent when volume or alert thresholds block them.",
        "",
        "## Coverage",
        "- single-item dump triggers",
        "- multi-item dump triggers",
        "- all-items dump triggers",
        "- minimum hourly volume",
        "- relative volume gating",
        "- missing and stale hourly volume blocking",
        "- inclusive floor behavior",
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


class DumpTriggerSuite(TestCase):
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
            username=f"dump-trigger-{self._testMethodName}",
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

    def _create_alert(self, **overrides):
        defaults = {
            "user": self.user,
            "alert_name": "Dump Trigger Test",
            "type": "dump",
            "is_active": True,
            "is_triggered": False,
            "minimum_price": 1,
            "maximum_price": 1_000_000_000,
            "dump_discount_min": 0.5,
            "dump_shock_sigma": 0.0,
            "dump_sell_ratio_min": 0.40,
            "dump_rel_vol_min": 0.10,
            "dump_liquidity_floor": 10_000_000,
            "dump_cooldown": 0,
            "dump_confirmation_buckets": 1,
            "dump_consistency_required": False,
            "dump_fair_halflife": 120,
            "dump_vol_halflife": 360,
            "dump_var_halflife": 120,
        }
        defaults.update(overrides)
        return Alert.objects.create(**defaults)

    def _create_volume(self, item_id, volume_gp, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=ITEM_MAPPING.get(str(item_id), f"Item {item_id}"),
            volume=volume_gp,
            timestamp=_epoch_string(minutes_ago),
        )

    def _create_bucket(self, item_id, high=DEFAULT_HIGH_VOL, low=DEFAULT_LOW_VOL):
        return FiveMinTimeSeries.objects.create(
            item_id=item_id,
            item_name=ITEM_MAPPING.get(str(item_id), f"Item {item_id}"),
            avg_high_price=DUMP_HIGH,
            avg_low_price=DUMP_LOW,
            high_price_volume=high,
            low_price_volume=low,
            timestamp=_epoch_string(2),
        )

    def _build_prices(self, include_background=True):
        normal_prices = {}
        dumped_prices = {}
        for item_id in (ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID):
            normal_prices[str(item_id)] = {"high": NORMAL_HIGH, "low": NORMAL_LOW}
            dumped_prices[str(item_id)] = {"high": DUMP_HIGH, "low": DUMP_LOW}

        if include_background:
            for item_id in BACKGROUND_ITEM_IDS:
                normal_prices[str(item_id)] = {"high": NORMAL_HIGH, "low": NORMAL_LOW}
                dumped_prices[str(item_id)] = {"high": NORMAL_HIGH, "low": NORMAL_LOW}

        return normal_prices, dumped_prices

    def _prime_market(self, alert):
        command = self._make_command()
        normal_prices, dumped_prices = self._build_prices()
        self._log(f"Priming alert #{alert.id} with normal market prices.")
        first = command.check_dump_alert(alert, normal_prices)
        self._log(f"First pass result: {first!r}")
        self._log("Running dump market pass.")
        second = command.check_dump_alert(alert, dumped_prices)
        self._log(f"Second pass result: {second!r}")
        return second

    def _extract_ids(self, result):
        if isinstance(result, list):
            return {row["item_id"] for row in result}
        return set()

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

    def _assert_single(self, *, name, goal, how, setup, assumptions, alert_kwargs, expected):
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
        alert = self._create_alert(**alert_kwargs)
        result = self._prime_market(alert)
        self._log(f"Observed result: {result!r}")
        self._result = f"Expected {expected!r}; observed {result!r}."
        self.assertIsInstance(result, bool)
        self.assertEqual(result, expected)
        self._record_case(
            name=name,
            scope="single",
            status="PASS",
            goal=goal,
            how=how,
            setup=setup,
            assumptions=assumptions,
            result=self._result,
            trace=self._trace,
        )

    def _assert_multi(self, *, name, goal, how, setup, assumptions, alert_kwargs, expected_ids):
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
        alert = self._create_alert(**alert_kwargs)
        result = self._prime_market(alert)
        actual_ids = self._extract_ids(result)
        self._log(f"Observed result: {result!r}")
        self._log(f"Observed item ids: {sorted(actual_ids)!r}")
        self._result = f"Expected {sorted(expected_ids)!r}; observed {sorted(actual_ids)!r}."
        self.assertEqual(actual_ids, expected_ids)
        self._record_case(
            name=name,
            scope="multi/all",
            status="PASS",
            goal=goal,
            how=how,
            setup=setup,
            assumptions=assumptions,
            result=self._result,
            trace=self._trace,
        )

    def test_single_item_triggers_above_liquidity_floor(self):
        self._create_volume(ITEM_A_ID, 20_000_000)
        self._create_bucket(ITEM_A_ID)
        self._assert_single(
            name="single_item_triggers_above_liquidity_floor",
            goal="Confirm a single-item dump alert triggers when the item is liquid and the dump conditions are permissive.",
            how="Run the checker twice with a normal first pass and a sharp dump on the second pass.",
            setup="Item A has fresh 20M GP hourly volume and a clear dump bucket.",
            assumptions="The price move, sell ratio, and relative volume are all configured to allow a trigger.",
            alert_kwargs={"item_id": ITEM_A_ID},
            expected=True,
        )

    def test_multi_item_triggers_with_two_liquid_candidates(self):
        self._create_volume(ITEM_A_ID, 20_000_000)
        self._create_volume(ITEM_B_ID, 18_000_000)
        self._create_bucket(ITEM_A_ID)
        self._create_bucket(ITEM_B_ID)
        self._assert_multi(
            name="multi_item_triggers_with_two_liquid_candidates",
            goal="Confirm a multi-item dump alert returns the liquid items that meet the dump conditions.",
            how="Check two monitored items through the same normal-to-dump transition.",
            setup="Item A and Item B both have fresh hourly volume above the liquidity floor.",
            assumptions="Both items should survive the gate and appear in the result list.",
            alert_kwargs={"item_ids": json.dumps([ITEM_A_ID, ITEM_B_ID])},
            expected_ids={str(ITEM_A_ID), str(ITEM_B_ID)},
        )

    def test_all_items_triggers_for_all_liquid_monitored_items(self):
        self._create_volume(ITEM_A_ID, 20_000_000)
        self._create_volume(ITEM_B_ID, 19_000_000)
        self._create_volume(ITEM_C_ID, 21_000_000)
        self._create_bucket(ITEM_A_ID)
        self._create_bucket(ITEM_B_ID)
        self._create_bucket(ITEM_C_ID)
        self._assert_multi(
            name="all_items_triggers_for_all_liquid_monitored_items",
            goal="Confirm the all-items dump path returns every item that clears the liquidity gate and dump conditions.",
            how="Run the checker across the tracked market and let every monitored item dump together.",
            setup="Three tracked items have fresh hourly volume above the configured floor.",
            assumptions="The all-items scan should return all tracked items that satisfy the dump rules.",
            alert_kwargs={"is_all_items": True},
            expected_ids={str(ITEM_A_ID), str(ITEM_B_ID), str(ITEM_C_ID)},
        )

    def test_exact_liquidity_floor_triggers_inclusively(self):
        self._create_volume(ITEM_A_ID, 10_000_000)
        self._create_bucket(ITEM_A_ID)
        self._assert_single(
            name="exact_liquidity_floor_triggers_inclusively",
            goal="Confirm the dump liquidity gate is inclusive at the exact floor value.",
            how="Set the hourly volume to exactly the configured liquidity floor.",
            setup="Item A is exactly at 10,000,000 GP hourly volume.",
            assumptions="Equality to the floor should be accepted, not rejected.",
            alert_kwargs={"item_id": ITEM_A_ID},
            expected=True,
        )

    def test_blocks_when_volume_is_below_floor(self):
        self._create_volume(ITEM_B_ID, 5_000_000)
        self._create_bucket(ITEM_B_ID)
        self._assert_single(
            name="blocks_when_volume_is_below_floor",
            goal="Confirm a dump alert does not trigger when hourly volume is below the configured floor.",
            how="Give the item a dump pattern but leave its hourly volume below the threshold.",
            setup="Item B has only 5M GP hourly volume.",
            assumptions="Low liquidity should block the alert before dump math matters.",
            alert_kwargs={"item_id": ITEM_B_ID},
            expected=False,
        )

    def test_blocks_when_volume_missing(self):
        self._create_bucket(ITEM_C_ID)
        self._assert_single(
            name="blocks_when_volume_missing",
            goal="Confirm missing hourly volume data prevents a dump trigger.",
            how="Leave the item without any HourlyItemVolume row and run the dump transition.",
            setup="Item C has no hourly volume row at all.",
            assumptions="Missing data should behave like unavailable liquidity.",
            alert_kwargs={"item_id": ITEM_C_ID},
            expected=False,
        )

    def test_blocks_when_volume_is_stale(self):
        self._create_volume(ITEM_D_ID, 50_000_000, minutes_ago=180)
        self._create_bucket(ITEM_D_ID)
        self._assert_single(
            name="blocks_when_volume_is_stale",
            goal="Confirm stale hourly volume data is ignored by the dump checker.",
            how="Set a large hourly volume row older than the freshness window and then run the dump transition.",
            setup="Item D has a large volume row, but it is stale.",
            assumptions="Stale volume should be treated as missing, not eligible.",
            alert_kwargs={"item_id": ITEM_D_ID},
            expected=False,
        )
