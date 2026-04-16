"""
Sustained alert hourly-volume test suite.

What:
    Dedicated regression tests for sustained alerts and their hourly-volume gating.

Why:
    Sustained alerts use the shared HourlyItemVolume lookup and a stateful streak
    machine. We want explicit coverage that:
      - fresh volume allows sustained alerts to trigger,
      - low, missing, and stale volume prevent triggering,
      - multi-item and all-items sustained alerts respect the same restrictions,
      - volume gating does not wipe out streak state in unexpected ways.

How:
    Each test uses the real check_alerts Command object, real Alert rows, and real
    HourlyItemVolume rows in the Django test database. We seed deterministic price
    sequences to build a sustained streak, then vary only the volume condition.

Report output:
    The test suite rewrites C:\\Users\\19024\\OSRSWebsite\\test_output\\alert_volume_sustained.md
    every time a test case finishes so the run is documented in plain Markdown.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from threading import Lock
from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "test_output" / "alert_volume_sustained.md"
REPORT_LOCK = Lock()
TEST_RUNS = []


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
        "# Sustained Volume Alert Test Report",
        "",
        f"Updated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## Goal",
        "Verify that sustained alerts respect hourly volume restrictions across single-item, multi-item, and all-items flows.",
        "",
        "## Coverage",
        "- fresh volume allows sustained triggers",
        "- low volume blocks sustained triggers",
        "- stale volume blocks sustained triggers",
        "- missing volume blocks sustained triggers",
        "- volume gating does not unexpectedly clear streak state",
        "- multi-item and all-items sustained alerts obey the same restriction path",
        "",
        "## Test Runs",
    ]

    if not TEST_RUNS:
        lines.extend([
            "",
            "_No test cases have been recorded yet. This file is rewritten when the suite runs._",
        ])
    else:
        for run in TEST_RUNS:
            lines.extend([
                "",
                f"### {run['name']}",
                f"- Status: {run['status']}",
                f"- Goal: {run['goal']}",
                f"- Checked: {run['checked']}",
                f"- How: {run['how']}",
                f"- Setup: {run['setup']}",
                f"- Assumptions: {run['assumptions']}",
                "",
                "#### Trace",
            ])
            for entry in run["trace"]:
                lines.append(f"- {entry}")
            lines.extend([
                "",
                "#### Result",
                run["result"],
            ])

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SustainedVolumeTestMixin:
    ITEM_A = 4151
    ITEM_B = 11802

    ITEM_MAPPING = {
        str(ITEM_A): "Abyssal whip",
        str(ITEM_B): "Dragon crossbow",
    }

    DEFAULT_SERIES = [1000, 1020, 1040, 1060, 1080, 1100]
    BELOW_THRESHOLD_SERIES = [1000, 1002, 1004, 1006, 1008, 1010]

    def _begin_case(self, goal, how, setup, assumptions):
        self._report_goal = goal
        self._report_how = how
        self._report_setup = setup
        self._report_assumptions = assumptions
        self._trace = []
        self._report_result = "Pending"

    def _log(self, message):
        self._trace.append(message)

    def _write_case_report(self):
        record = {
            "name": self.id().split(".")[-1],
            "status": "FAIL" if _is_test_failed(self) else "PASS",
            "goal": getattr(self, "_report_goal", "No goal recorded."),
            "checked": self.id(),
            "how": getattr(self, "_report_how", "No method recorded."),
            "setup": getattr(self, "_report_setup", "No setup recorded."),
            "assumptions": getattr(self, "_report_assumptions", "No assumptions recorded."),
            "trace": list(getattr(self, "_trace", [])),
            "result": getattr(self, "_report_result", "No result recorded."),
        }

        with REPORT_LOCK:
            TEST_RUNS.append(record)
            _write_report()

    def _make_command(self):
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        cmd.sustained_state = {}
        cmd.get_item_mapping = lambda: self.ITEM_MAPPING
        return cmd

    def _fresh_volume_timestamp(self):
        fresh_dt = timezone.now() - timedelta(minutes=5)
        return str(int(fresh_dt.timestamp()))

    def _stale_volume_timestamp(self):
        stale_dt = timezone.now() - timedelta(minutes=131)
        return str(int(stale_dt.timestamp()))

    def _create_volume(self, item_id, volume, timestamp):
        item_name = self.ITEM_MAPPING.get(str(item_id), f"Item {item_id}")
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=item_name,
            volume=volume,
            timestamp=timestamp,
        )

    def _create_alert(self, *, item_id=None, item_ids=None, is_all_items=False,
                      min_volume=10_000, direction="up", alert_name="Sustained Volume Test"):
        return Alert.objects.create(
            user=self.user,
            alert_name=alert_name,
            type="sustained",
            item_id=item_id,
            sustained_item_ids=json.dumps(item_ids) if item_ids is not None else None,
            is_all_items=is_all_items,
            time_frame=60,
            min_consecutive_moves=3,
            min_move_percentage=1.0,
            volatility_buffer_size=5,
            volatility_multiplier=0.5,
            min_volume=min_volume,
            direction=direction,
            reference="average",
            minimum_price=1,
            maximum_price=1_000_000_000,
            show_notification=False,
            is_active=True,
        )

    def _price_point(self, price, offset_seconds=0):
        now_ts = int(time.time()) + offset_seconds
        return {
            "high": price,
            "low": price,
            "highTime": now_ts,
            "lowTime": now_ts,
        }

    def _run_series(self, command, alert, series_by_item):
        series_lengths = {len(series) for series in series_by_item.values()}
        self.assertEqual(
            len(series_lengths),
            1,
            "Every sustained test series must have the same length so the call order stays aligned.",
        )

        result = None
        step_count = next(iter(series_lengths))
        for step in range(step_count):
            all_prices = {
                str(item_id): self._price_point(series[step], offset_seconds=step)
                for item_id, series in series_by_item.items()
            }
            self._log(
                f"Step {step + 1}/{step_count}: prices="
                f"{ {item_id: series[step] for item_id, series in series_by_item.items()} }"
            )
            result = command.check_sustained_alert(alert, all_prices)
            self._log(f"Step {step + 1} result: {result}")
        return result

    def tearDown(self):
        self._write_case_report()
        super().tearDown()


class SustainedVolumeAlertTests(SustainedVolumeTestMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with REPORT_LOCK:
            TEST_RUNS.clear()
            _write_report()

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"sustained_volume_{self._testMethodName}",
            email=f"{self._testMethodName}@example.com",
            password="testpass123",
        )

    def test_single_item_triggers_with_fresh_volume_above_threshold(self):
        self._begin_case(
            goal="Confirm a single-item sustained alert triggers when the hourly volume is fresh and above the configured minimum.",
            how="Run a six-step upward price series against a single-item alert with a fresh HourlyItemVolume row above the threshold.",
            setup="Single item, fresh volume row, upward price series, and a sustained config that needs at least three qualifying moves.",
            assumptions="The sustained state machine should allow the trigger once the streak, volatility, and volume checks all pass.",
        )
        command = self._make_command()
        alert = self._create_alert(item_id=self.ITEM_A, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=25_000, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES})
        payload = json.loads(alert.triggered_data)

        self._log(f"Final result: {result}")
        self._log(f"Triggered payload: {payload}")
        self.assertTrue(result)
        self.assertEqual(payload["item_id"], self.ITEM_A)
        self.assertGreaterEqual(payload["streak_count"], 3)
        self.assertEqual(payload["volume"], 25_000)
        self._report_result = "Single-item sustained alert triggered cleanly with fresh volume above threshold."

    def test_single_item_does_not_trigger_when_volume_is_below_threshold(self):
        self._begin_case(
            goal="Confirm a single-item sustained alert stays quiet when the hourly volume is below the threshold.",
            how="Run the same sustained streak with a fresh HourlyItemVolume row that is intentionally under min_volume.",
            setup="Single item, fresh low volume, and a qualifying price streak so the volume gate is the only blocker.",
            assumptions="A low GP volume snapshot should fail the min_volume gate even when price movement is otherwise valid.",
        )
        command = self._make_command()
        alert = self._create_alert(item_id=self.ITEM_A, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=2_500, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES})
        state_key = f"{alert.id}:{self.ITEM_A}"
        state = command.sustained_state.get(state_key, {})

        self._log(f"Final result: {result}")
        self._log(f"State after block: {state}")
        self.assertFalse(result)
        self.assertIsNone(alert.triggered_data)
        self.assertGreater(state.get("streak_count", 0), 0)
        self.assertEqual(state.get("streak_direction"), "up")
        self._report_result = "The alert did not trigger, but the streak state remained intact for later checks."

    def test_single_item_does_not_trigger_when_volume_snapshot_is_stale(self):
        self._begin_case(
            goal="Confirm a stale hourly volume snapshot blocks a single-item sustained alert.",
            how="Seed a high-volume HourlyItemVolume row with an old timestamp and run the same sustained streak.",
            setup="Single item, stale volume snapshot, and a qualifying price series.",
            assumptions="A stale volume row should be treated like missing data and block triggering.",
        )
        command = self._make_command()
        alert = self._create_alert(item_id=self.ITEM_A, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=25_000, timestamp=self._stale_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES})
        lookup_volume = command.get_volume_from_timeseries(self.ITEM_A, 60)

        self._log(f"Final result: {result}")
        self._log(f"Freshness lookup returned: {lookup_volume}")
        self.assertFalse(result)
        self.assertIsNone(lookup_volume)
        self.assertIsNone(alert.triggered_data)
        self._report_result = "Stale volume was rejected and the single-item sustained alert stayed inactive."

    def test_single_item_does_not_trigger_when_volume_snapshot_is_missing(self):
        self._begin_case(
            goal="Confirm missing hourly volume prevents a single-item sustained alert from triggering.",
            how="Run the sustained streak without creating any HourlyItemVolume rows for the item.",
            setup="Single item, no volume row at all, and a qualifying price series.",
            assumptions="Missing volume should behave like None and block the trigger.",
        )
        command = self._make_command()
        alert = self._create_alert(item_id=self.ITEM_A, min_volume=10_000)

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES})
        lookup_volume = command.get_volume_from_timeseries(self.ITEM_A, 60)

        self._log(f"Final result: {result}")
        self._log(f"Freshness lookup returned: {lookup_volume}")
        self.assertFalse(result)
        self.assertIsNone(lookup_volume)
        self.assertIsNone(alert.triggered_data)
        self._report_result = "No volume row existed, so the sustained alert correctly never triggered."

    def test_single_item_volume_gate_keeps_the_existing_streak_state(self):
        self._begin_case(
            goal="Confirm that a volume-gated sustained failure does not wipe out an already-building streak.",
            how="Build a streak with a low-volume snapshot, verify it does not trigger, then swap in fresh volume and confirm the next qualifying move fires.",
            setup="Single item, first with fresh low volume and later with a fresh high-volume row, using the same sustained streak progression.",
            assumptions="Volume gating should block the trigger without clearing the streak counter the state machine already built.",
        )
        command = self._make_command()
        alert = self._create_alert(item_id=self.ITEM_A, min_volume=10_000)
        low_volume_ts = self._fresh_volume_timestamp()
        self._create_volume(self.ITEM_A, volume=2_500, timestamp=low_volume_ts)

        # Build the streak up to the point where the next qualifying move would trigger.
        for step, price in enumerate(self.DEFAULT_SERIES[:-1]):
            all_prices = {str(self.ITEM_A): self._price_point(price, offset_seconds=step)}
            self._log(f"Warm-up step {step + 1}: {all_prices}")
            self.assertFalse(command.check_sustained_alert(alert, all_prices))

        blocked_step_prices = {str(self.ITEM_A): self._price_point(self.DEFAULT_SERIES[-1], offset_seconds=99)}
        blocked_result = command.check_sustained_alert(alert, blocked_step_prices)
        state_key = f"{alert.id}:{self.ITEM_A}"
        blocked_state = command.sustained_state.get(state_key, {})

        self._log(f"Blocked result: {blocked_result}")
        self._log(f"State after blocked trigger: {blocked_state}")
        self.assertFalse(blocked_result)
        self.assertGreaterEqual(blocked_state.get("streak_count", 0), 3)
        self.assertEqual(blocked_state.get("streak_direction"), "up")

        # Replace the stale low volume with a fresh high-volume row and prove the streak still fires.
        self._create_volume(self.ITEM_A, volume=30_000, timestamp=str(int(time.time()) + 1))
        final_result = command.check_sustained_alert(alert, {str(self.ITEM_A): self._price_point(1120, offset_seconds=100)})
        payload = json.loads(alert.triggered_data)

        self._log(f"Final result after fresh volume: {final_result}")
        self._log(f"Triggered payload after fresh volume: {payload}")
        self.assertTrue(final_result)
        self.assertEqual(payload["volume"], 30_000)
        self.assertEqual(payload["streak_direction"], "up")
        self._report_result = "The streak survived the low-volume block and triggered as soon as fresh volume arrived."

    def test_multi_item_sustained_triggers_only_the_item_with_fresh_volume(self):
        self._begin_case(
            goal="Confirm a multi-item sustained alert only returns items whose hourly volume passes the filter.",
            how="Run two monitored items through the same streak; only one item gets a fresh high-volume snapshot.",
            setup="Two monitored items with identical price movement, one fresh and one low-volume.",
            assumptions="The multi-item sustained path should keep the qualifying item and reject the under-volume one.",
        )
        command = self._make_command()
        alert = self._create_alert(item_ids=[self.ITEM_A, self.ITEM_B], min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=30_000, timestamp=self._fresh_volume_timestamp())
        self._create_volume(self.ITEM_B, volume=1_500, timestamp=self._fresh_volume_timestamp())

        series = {
            self.ITEM_A: self.DEFAULT_SERIES,
            self.ITEM_B: self.DEFAULT_SERIES,
        }
        result = self._run_series(command, alert, series)
        payload = json.loads(alert.triggered_data)

        self._log(f"Final result: {result}")
        self._log(f"Triggered payload: {payload}")
        self.assertTrue(result)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["item_id"], self.ITEM_A)
        self.assertEqual(payload[0]["volume"], 30_000)
        self._report_result = "Only the item above min_volume survived the multi-item sustained check."

    def test_multi_item_sustained_blocks_when_every_item_is_below_volume_threshold(self):
        self._begin_case(
            goal="Confirm a multi-item sustained alert stays false when every candidate item is under min_volume.",
            how="Run two items through the same sustained streak, but keep both hourly volume rows below the threshold.",
            setup="Two monitored items, both fresh but both under the required GP volume.",
            assumptions="If every item fails volume gating, the multi-item sustained check should return False.",
        )
        command = self._make_command()
        alert = self._create_alert(item_ids=[self.ITEM_A, self.ITEM_B], min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=2_500, timestamp=self._fresh_volume_timestamp())
        self._create_volume(self.ITEM_B, volume=4_000, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES, self.ITEM_B: self.DEFAULT_SERIES})

        self._log(f"Final result: {result}")
        self.assertFalse(result)
        self.assertIsNone(alert.triggered_data)
        self._report_result = "Both items failed the volume filter, so no multi-item sustained alert fired."

    def test_all_items_sustained_returns_only_items_meeting_volume_threshold(self):
        self._begin_case(
            goal="Confirm an all-items sustained alert only includes items that meet the hourly volume restriction.",
            how="Run the all-items path with one liquid item and one illiquid item using the same price streak.",
            setup="All-items sustained alert, identical price movement, and mixed volume coverage.",
            assumptions="The result list should include only the item whose hourly GP volume clears min_volume.",
        )
        command = self._make_command()
        alert = self._create_alert(is_all_items=True, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=35_000, timestamp=self._fresh_volume_timestamp())
        self._create_volume(self.ITEM_B, volume=800, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES, self.ITEM_B: self.DEFAULT_SERIES})
        payload = json.loads(alert.triggered_data)

        self._log(f"Final result: {result}")
        self._log(f"Triggered payload: {payload}")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(payload[0]["item_id"], self.ITEM_A)
        self.assertEqual(payload[0]["volume"], 35_000)
        self._report_result = "The all-items result list kept only the item above the minimum hourly volume."

    def test_all_items_sustained_blocks_when_every_item_is_under_volume_threshold(self):
        self._begin_case(
            goal="Confirm an all-items sustained alert returns False when no item meets the volume threshold.",
            how="Run the all-items path with two items that both have fresh but low hourly volume rows.",
            setup="All-items sustained alert and no item above min_volume.",
            assumptions="A result list should not be produced when every candidate item fails volume gating.",
        )
        command = self._make_command()
        alert = self._create_alert(is_all_items=True, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=2_500, timestamp=self._fresh_volume_timestamp())
        self._create_volume(self.ITEM_B, volume=5_000, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES, self.ITEM_B: self.DEFAULT_SERIES})

        self._log(f"Final result: {result}")
        self.assertFalse(result)
        self.assertIsNone(alert.triggered_data)
        self._report_result = "No item cleared the hourly volume gate, so the all-items sustained alert stayed quiet."

    def test_all_items_sustained_blocks_stale_volume_even_with_valid_price_streak(self):
        self._begin_case(
            goal="Confirm stale hourly volume snapshots block all-items sustained alerts.",
            how="Run the all-items path with stale volume rows for every item and a valid sustained price streak.",
            setup="All-items sustained alert and stale volume rows for all monitored items.",
            assumptions="Stale data should be treated as missing, even when the price streak is otherwise valid.",
        )
        command = self._make_command()
        alert = self._create_alert(is_all_items=True, min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=35_000, timestamp=self._stale_volume_timestamp())
        self._create_volume(self.ITEM_B, volume=20_000, timestamp=self._stale_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES, self.ITEM_B: self.DEFAULT_SERIES})
        lookup_a = command.get_volume_from_timeseries(self.ITEM_A, 60)
        lookup_b = command.get_volume_from_timeseries(self.ITEM_B, 60)

        self._log(f"Final result: {result}")
        self._log(f"Lookup A: {lookup_a}")
        self._log(f"Lookup B: {lookup_b}")
        self.assertFalse(result)
        self.assertIsNone(lookup_a)
        self.assertIsNone(lookup_b)
        self.assertIsNone(alert.triggered_data)
        self._report_result = "Stale hourly volume was rejected for both items, so the all-items sustained alert did not trigger."

    def test_volume_lookup_prefers_the_newest_fresh_row(self):
        self._begin_case(
            goal="Confirm the sustained alert volume lookup returns the newest fresh HourlyItemVolume row.",
            how="Insert an older low-volume row and then a newer high-volume row for the same item, then query the helper directly.",
            setup="Single item with two real HourlyItemVolume rows and different timestamps.",
            assumptions="The lookup helper should choose the latest parseable fresh snapshot for the item.",
        )
        command = self._make_command()
        self._create_volume(self.ITEM_A, volume=1_000, timestamp=self._fresh_volume_timestamp())
        self._create_volume(self.ITEM_A, volume=50_000, timestamp=str(int(time.time()) + 2))

        volume = command.get_volume_from_timeseries(self.ITEM_A, 60)

        self._log(f"Volume lookup returned: {volume}")
        self.assertEqual(volume, 50_000)
        self._report_result = "The helper returned the newest fresh volume row instead of the older one."

    def test_multi_item_sustained_ignores_missing_volume_for_one_item_but_keeps_the_other(self):
        self._begin_case(
            goal="Confirm a multi-item sustained alert can still trigger for the item that has volume data when a sibling item has none.",
            how="Leave one monitored item without any HourlyItemVolume rows and give the other a fresh high-volume row.",
            setup="Two monitored items, only one with a real volume snapshot.",
            assumptions="Missing volume should only block the item that lacks data, not the whole multi-item alert.",
        )
        command = self._make_command()
        alert = self._create_alert(item_ids=[self.ITEM_A, self.ITEM_B], min_volume=10_000)
        self._create_volume(self.ITEM_A, volume=30_000, timestamp=self._fresh_volume_timestamp())

        result = self._run_series(command, alert, {self.ITEM_A: self.DEFAULT_SERIES, self.ITEM_B: self.DEFAULT_SERIES})
        payload = json.loads(alert.triggered_data)

        self._log(f"Final result: {result}")
        self._log(f"Triggered payload: {payload}")
        self.assertTrue(result)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["item_id"], self.ITEM_A)
        self.assertEqual(payload[0]["volume"], 30_000)
        self._report_result = "The missing-volume item was ignored while the liquid item still triggered."


if __name__ == "__main__":
    _write_report()
