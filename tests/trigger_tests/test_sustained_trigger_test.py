from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume

from .trigger_suite_base import TriggerReportMixin


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "sustained_trigger_test.md"


class SustainedTriggerTests(TriggerReportMixin):
    REPORT_PATH = REPORT_PATH
    REPORT_TITLE = "Sustained Trigger Test Report"
    REPORT_SCOPE = "Scope: sustained alert trigger behavior."

    ITEMS = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11235": "Dragonfire shield",
    }

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="sustained_trigger_tester",
            email="sustained_trigger@example.com",
            password="test-password",
        )

    def _command(self):
        cmd = Command()
        cmd.get_item_mapping = lambda: self.ITEMS
        cmd.sustained_state = {}
        return cmd

    def _prices(self, **items):
        return {str(item_id): {"high": values["high"], "low": values["low"]} for item_id, values in items.items()}

    def _volume(self, item_id, volume, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=int(item_id),
            item_name=self.ITEMS[str(item_id)],
            volume=volume,
            timestamp=(timezone.now() - timedelta(minutes=minutes_ago)).isoformat(),
        )

    def _alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Sustained Trigger Test",
            "type": "sustained",
            "time_frame": 60,
            "min_consecutive_moves": 2,
            "min_move_percentage": 1.0,
            "volatility_buffer_size": 5,
            "volatility_multiplier": 1.0,
            "min_volume": 1_000_000,
            "direction": "up",
            "reference": "high",
            "item_id": None,
            "item_ids": None,
            "sustained_item_ids": None,
            "is_all_items": False,
            "minimum_price": None,
            "maximum_price": None,
            "min_pressure_strength": None,
            "min_pressure_spread_pct": None,
        }
        base.update(overrides)
        if isinstance(base.get("sustained_item_ids"), list):
            base["sustained_item_ids"] = json.dumps(base["sustained_item_ids"])
        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        return Alert.objects.create(**base)

    def _seed_state(self, cmd, alert, item_id, *, last_price, streak_count, streak_direction, streak_start_price, streak_start_time):
        cmd.sustained_state[f"{alert.id}:{item_id}"] = {
            "last_price": last_price,
            "streak_count": streak_count,
            "streak_direction": streak_direction,
            "streak_start_time": streak_start_time,
            "streak_start_price": streak_start_price,
            "volatility_buffer": [5, 5, 5, 5, 5],
        }

    def test_single_item_triggers_after_required_upward_streak(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=1, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        result = cmd.check_sustained_alert(alert, self._prices(**{"4151": {"high": 110, "low": 100}}))
        self._record_case(
            name="single_up_trigger",
            goal="Single-item sustained alerts should trigger when the configured streak completes.",
            expected="True",
            observed=str(result),
            setup="A ready-to-trigger upward streak with fresh volume.",
            assumptions="The seeded state already contains the previous move history.",
            output=[f"return={result}", f"payload={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_single_item_triggers_on_downward_direction(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], direction="down")
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=110, streak_count=1, streak_direction="down", streak_start_price=110, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        result = cmd.check_sustained_alert(alert, self._prices(**{"4151": {"high": 100, "low": 90}}))
        self._record_case(
            name="single_down_trigger",
            goal="Single-item sustained alerts should also trigger on downward streaks when configured.",
            expected="True",
            observed=str(result),
            setup="A ready-to-trigger downward streak with fresh volume.",
            assumptions="Direction 'down' should accept a negative streak.",
            output=[f"return={result}", f"payload={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_multi_item_triggers_when_one_watched_item_meets_conditions(self):
        alert = self._alert(item_ids=[4151, 11802], sustained_item_ids=[4151, 11802], direction="up")
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=1, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._seed_state(cmd, alert, 11802, last_price=200, streak_count=0, streak_direction=None, streak_start_price=200, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        self._volume(11802, 5_000_000)
        result = cmd.check_sustained_alert(
            alert,
            self._prices(**{"4151": {"high": 110, "low": 100}, "11802": {"high": 200, "low": 190}}),
        )
        payload = json.loads(alert.triggered_data)
        self._record_case(
            name="multi_item_trigger",
            goal="Multi-item sustained alerts should trigger when at least one watched item completes a streak.",
            expected="True",
            observed=f"{result} with payload {payload}",
            setup="One watched item is ready to trigger; the other is still warming up.",
            assumptions="Multi-item sustained alerts return True and persist a list payload.",
            output=[f"return={result}", f"payload={payload}"],
        )
        self.assertTrue(result)
        self.assertEqual(len(payload), 1)

    def test_all_items_triggers_and_returns_a_list_payload(self):
        alert = self._alert(is_all_items=True, direction="up")
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=1, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._seed_state(cmd, alert, 11802, last_price=200, streak_count=1, streak_direction="up", streak_start_price=200, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        self._volume(11802, 5_000_000)
        result = cmd.check_sustained_alert(
            alert,
            self._prices(**{"4151": {"high": 110, "low": 100}, "11802": {"high": 220, "low": 200}}),
        )
        self._record_case(
            name="all_items_trigger",
            goal="All-items sustained alerts should return the list of items that passed.",
            expected="List",
            observed=str(result),
            setup="Two all-items candidates both complete the streak.",
            assumptions="All-items mode returns the triggered item list rather than a bare boolean.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertEqual({str(entry["item_id"]) for entry in result}, {"4151", "11802"})

    def test_single_item_does_not_trigger_with_insufficient_consecutive_moves(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=0, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        result = cmd.check_sustained_alert(alert, self._prices(**{"4151": {"high": 102, "low": 100}}))
        self._record_case(
            name="single_no_streak",
            goal="A streak that has not reached the required move count should not trigger.",
            expected="False",
            observed=str(result),
            setup="Only one qualifying move is present.",
            assumptions="The streak counter must reach the configured minimum.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_too_low(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=1, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._volume(4151, 100)
        result = cmd.check_sustained_alert(alert, self._prices(**{"4151": {"high": 110, "low": 100}}))
        self._record_case(
            name="single_low_volume",
            goal="Sustained alerts must block items that do not meet the hourly GP volume gate.",
            expected="False",
            observed=str(result),
            setup="The streak qualifies, but the liquidity gate does not.",
            assumptions="min_volume is enforced after the streak logic.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_direction_mismatches(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], direction="down")
        cmd = self._command()
        now = time.time()
        self._seed_state(cmd, alert, 4151, last_price=100, streak_count=1, streak_direction="up", streak_start_price=100, streak_start_time=now - 30)
        self._volume(4151, 5_000_000)
        result = cmd.check_sustained_alert(alert, self._prices(**{"4151": {"high": 110, "low": 100}}))
        self._record_case(
            name="single_direction_mismatch",
            goal="A streak in the wrong direction should not trigger.",
            expected="False",
            observed=str(result),
            setup="The streak is upward, but the alert is configured for downward moves.",
            assumptions="Direction checks happen after the streak is counted.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)
