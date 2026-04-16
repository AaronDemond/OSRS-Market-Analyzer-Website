from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume

from .trigger_suite_base import TriggerReportMixin


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "spike_trigger_test.md"


class SpikeTriggerTests(TriggerReportMixin):
    REPORT_PATH = REPORT_PATH
    REPORT_TITLE = "Spike Trigger Test Report"
    REPORT_SCOPE = "Scope: spike alert trigger behavior."

    ITEMS = {
        "100": "Dragon Bones",
        "200": "Abyssal Whip",
        "300": "Bandos Chestplate",
        "400": "Armadyl Godsword",
    }

    TIME_FRAME_MINUTES = 60
    MIN_VOLUME = 1_000_000

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="spike_trigger_tester",
            email="spike_trigger@example.com",
            password="test-password",
        )

    def _command(self):
        cmd = Command()
        cmd.stdout = type("Stdout", (), {"write": lambda self, msg: None})()
        cmd.price_history = defaultdict(list)
        cmd.get_item_mapping = lambda: self.ITEMS
        return cmd

    def _alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Spike Trigger Test",
            "type": "spike",
            "percentage": 10.0,
            "price": self.TIME_FRAME_MINUTES,
            "min_volume": self.MIN_VOLUME,
            "direction": "both",
            "reference": "high",
            "item_id": None,
            "item_ids": None,
            "is_all_items": False,
            "minimum_price": None,
            "maximum_price": None,
        }
        base.update(overrides)
        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        return Alert.objects.create(**base)

    def _prices(self, **items):
        return {
            str(item_id): {"high": values["high"], "low": values.get("low", max(1, values["high"] - 200))}
            for item_id, values in items.items()
        }

    def _seed_baseline(self, cmd, item_id, baseline):
        key = f"{item_id}:high"
        cmd.price_history[key].append((time.time() - (self.TIME_FRAME_MINUTES * 60) - 30, baseline))

    def _volume(self, item_id, volume, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=int(item_id),
            item_name=self.ITEMS[str(item_id)],
            volume=volume,
            timestamp=(timezone.now() - timedelta(minutes=minutes_ago)).isoformat(),
        )

    def test_single_item_triggers_on_upward_spike(self):
        alert = self._alert(item_id=100, item_name=self.ITEMS["100"], direction="up")
        cmd = self._command()
        self._seed_baseline(cmd, "100", 100)
        self._volume("100", 5_000_000)
        result = cmd.check_alert(alert, self._prices(**{"100": {"high": 120}}))
        self._record_case(
            name="single_up_trigger",
            goal="Single-item spike alerts should trigger when the rise meets the threshold.",
            expected="True",
            observed=str(result),
            setup="One item with a 20% upward spike and fresh volume.",
            assumptions="A valid warmup baseline already exists in the command history.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_single_item_triggers_on_downward_spike(self):
        alert = self._alert(item_id=100, item_name=self.ITEMS["100"], direction="down")
        cmd = self._command()
        self._seed_baseline(cmd, "100", 200)
        self._volume("100", 5_000_000)
        result = cmd.check_alert(alert, self._prices(**{"100": {"high": 160}}))
        self._record_case(
            name="single_down_trigger",
            goal="Single-item spike alerts should trigger when the drop meets the threshold.",
            expected="True",
            observed=str(result),
            setup="One item with a 20% downward spike and fresh volume.",
            assumptions="Direction 'down' compares the negative percentage move.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_multi_item_triggers_when_any_item_exceeds_threshold(self):
        alert = self._alert(item_ids=[100, 200], direction="both")
        cmd = self._command()
        self._seed_baseline(cmd, "100", 100)
        self._seed_baseline(cmd, "200", 200)
        self._volume("100", 5_000_000)
        self._volume("200", 5_000_000)
        result = cmd.check_alert(
            alert,
            self._prices(**{"100": {"high": 120}, "200": {"high": 220}}),
        )
        self._record_case(
            name="multi_item_trigger",
            goal="Multi-item spike alerts should trigger when at least one watched item spikes.",
            expected="List with triggered items",
            observed=str(result),
            setup="Two watched items both exceed the 10% threshold.",
            assumptions="Triggered data should include every item that exceeds the threshold.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertEqual({entry["item_id"] for entry in result}, {"100", "200"})

    def test_all_items_triggers_and_sorts_by_absolute_change(self):
        alert = self._alert(is_all_items=True, direction="both")
        cmd = self._command()
        self._seed_baseline(cmd, "100", 100)
        self._seed_baseline(cmd, "200", 200)
        self._volume("100", 5_000_000)
        self._volume("200", 5_000_000)
        result = cmd.check_alert(
            alert,
            self._prices(**{"100": {"high": 130}, "200": {"high": 230}, "300": {"high": 299}}),
        )
        self._record_case(
            name="all_items_trigger",
            goal="All-items spike alerts should return a sorted list of qualifying items.",
            expected="List with qualifying items",
            observed=str(result),
            setup="Two items exceed the threshold and one item stays below it.",
            assumptions="Results are sorted by absolute percent change descending.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)

    def test_single_item_does_not_trigger_below_threshold(self):
        alert = self._alert(item_id=100, item_name=self.ITEMS["100"], direction="up", percentage=25.0)
        cmd = self._command()
        self._seed_baseline(cmd, "100", 100)
        self._volume("100", 5_000_000)
        result = cmd.check_alert(alert, self._prices(**{"100": {"high": 120}}))
        self._record_case(
            name="single_below_threshold",
            goal="A move below the configured spike threshold should stay silent.",
            expected="False",
            observed=str(result),
            setup="One item rises only 20% against a 25% threshold.",
            assumptions="Warmup is valid, but the spike is still too small.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_too_low(self):
        alert = self._alert(item_id=100, item_name=self.ITEMS["100"], direction="up")
        cmd = self._command()
        self._seed_baseline(cmd, "100", 100)
        self._volume("100", 500_000)
        result = cmd.check_alert(alert, self._prices(**{"100": {"high": 130}}))
        self._record_case(
            name="single_low_volume",
            goal="Spike alerts must ignore items that fail the hourly GP volume gate.",
            expected="False",
            observed=str(result),
            setup="The move qualifies, but the item volume is below the minimum.",
            assumptions="Volume checks happen after the spike threshold check.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_without_warmup_history(self):
        alert = self._alert(item_id=100, item_name=self.ITEMS["100"], direction="up")
        cmd = self._command()
        self._volume("100", 5_000_000)
        result = cmd.check_alert(alert, self._prices(**{"100": {"high": 130}}))
        self._record_case(
            name="single_no_warmup",
            goal="Spike alerts should not trigger until the window has warmed up.",
            expected="False",
            observed=str(result),
            setup="No baseline history is seeded into the rolling window.",
            assumptions="The checker requires data from the full lookback window.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)
