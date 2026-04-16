from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume

from .trigger_suite_base import TriggerReportMixin


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "threshold_trigger_test.md"


class ThresholdTriggerTests(TriggerReportMixin):
    REPORT_PATH = REPORT_PATH
    REPORT_TITLE = "Threshold Trigger Test Report"
    REPORT_SCOPE = "Scope: threshold alert trigger behavior."

    ITEMS = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11235": "Dragonfire shield",
        "2001": "Bronze arrow",
    }

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="threshold_trigger_tester",
            email="threshold_trigger@example.com",
            password="test-password",
        )

    def _command(self):
        cmd = Command()
        cmd.get_item_mapping = lambda: self.ITEMS
        return cmd

    def _prices(self, **items):
        return {
            str(item_id): {"high": values["high"], "low": values["low"]}
            for item_id, values in items.items()
        }

    def _volume(self, item_id, volume, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=int(item_id),
            item_name=self.ITEMS[str(item_id)],
            volume=volume,
            timestamp=str(int((timezone.now() - timedelta(minutes=minutes_ago)).timestamp())),
        )

    def _alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Threshold Trigger Test",
            "type": "threshold",
            "direction": "up",
            "threshold_type": "percentage",
            "percentage": 10.0,
            "reference": "high",
            "min_volume": 1,
            "minimum_price": None,
            "maximum_price": None,
            "item_id": None,
            "item_ids": None,
            "is_all_items": False,
            "reference_prices": json.dumps({"4151": 100, "11802": 200, "11235": 300, "2001": 400}),
        }
        base.update(overrides)
        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        return Alert.objects.create(**base)

    def test_single_percentage_triggers_when_price_rises_above_target(self):
        alert = self._alert(item_id=4151, item_name="Abyssal whip", direction="up", percentage=20.0)
        self._volume("4151", 5_000_000)
        result = self._command().check_threshold_alert(alert, self._prices(**{"4151": {"high": 150, "low": 90}}))
        payload = json.loads(alert.triggered_data)
        self._record_case(
            name="single_percentage_up",
            goal="Single-item percentage threshold should trigger on a move above the configured threshold.",
            expected="True",
            observed=f"{result} with payload {payload}",
            setup="One item, +50% move, upward direction, percentage threshold.",
            assumptions="Reference prices are stored in the alert and the checker uses high prices.",
            output=[f"return={result}", f"payload={payload}"],
        )
        self.assertTrue(result)
        self.assertEqual(payload["item_id"], "4151")

    def test_single_percentage_triggers_when_price_falls_below_target(self):
        alert = self._alert(item_id=4151, item_name="Abyssal whip", direction="down", percentage=5.0, reference="low")
        self._volume("4151", 5_000_000)
        result = self._command().check_threshold_alert(alert, self._prices(**{"4151": {"high": 150, "low": 90}}))
        payload = json.loads(alert.triggered_data)
        self._record_case(
            name="single_percentage_down",
            goal="Single-item percentage threshold should trigger on a move below the configured threshold.",
            expected="True",
            observed=f"{result} with payload {payload}",
            setup="One item, -10% move, downward direction, percentage threshold.",
            assumptions="Down direction compares against the low price reference.",
            output=[f"return={result}", f"payload={payload}"],
        )
        self.assertTrue(result)
        self.assertEqual(payload["direction"], "down")

    def test_single_value_triggers_when_current_price_reaches_target(self):
        alert = self._alert(
            item_id=4151,
            item_name="Abyssal whip",
            threshold_type="value",
            target_price=120,
            direction="up",
            reference_prices=json.dumps({"4151": 100}),
        )
        self._volume("4151", 5_000_000)
        result = self._command().check_threshold_alert(alert, self._prices(**{"4151": {"high": 150, "low": 90}}))
        payload = json.loads(alert.triggered_data)
        self._record_case(
            name="single_value_up",
            goal="Value thresholds should trigger once the current price reaches or exceeds the target.",
            expected="True",
            observed=f"{result} with payload {payload}",
            setup="One item, target price 120 gp, current high price 150 gp.",
            assumptions="Value thresholds use the target_price field and a single item only.",
            output=[f"return={result}", f"payload={payload}"],
        )
        self.assertTrue(result)
        self.assertEqual(payload["threshold_type"], "value")

    def test_all_items_triggers_and_returns_every_match(self):
        alert = self._alert(is_all_items=True, direction="up", percentage=10.0)
        alert.reference_prices = json.dumps({"4151": 100, "11802": 200})
        self._volume("4151", 5_000_000)
        self._volume("11802", 5_000_000)
        result = self._command().check_threshold_alert(
            alert,
            self._prices(
                **{
                    "4151": {"high": 120, "low": 100},
                    "11802": {"high": 240, "low": 200},
                    "11235": {"high": 302, "low": 300},
                }
            ),
        )
        self._record_case(
            name="all_items_percentage_up",
            goal="All-items thresholds should return a list of every qualifying item.",
            expected="List with two items",
            observed=f"{result}",
            setup="Two items cross +10%, one item stays below threshold.",
            assumptions="The result list should be sorted by absolute change descending.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertEqual({str(entry["item_id"]) for entry in result}, {"4151", "11802"})

    def test_single_percentage_does_not_trigger_below_threshold(self):
        alert = self._alert(item_id=4151, item_name="Abyssal whip", percentage=25.0)
        result = self._command().check_threshold_alert(alert, self._prices(**{"4151": {"high": 120, "low": 100}}))
        self._record_case(
            name="single_percentage_below",
            goal="A move below the configured percentage should not trigger.",
            expected="False",
            observed=str(result),
            setup="One item moves +20% against a +25% threshold.",
            assumptions="The checker should leave triggered_data empty when nothing passes.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_value_does_not_trigger_without_target_price(self):
        alert = self._alert(
            item_id=4151,
            item_name="Abyssal whip",
            threshold_type="value",
            target_price=None,
            direction="up",
            reference_prices=json.dumps({"4151": 100}),
        )
        result = self._command().check_threshold_alert(alert, self._prices(**{"4151": {"high": 150, "low": 90}}))
        self._record_case(
            name="single_value_missing_target",
            goal="A value threshold without a target should not trigger.",
            expected="False",
            observed=str(result),
            setup="Single-item value threshold missing target_price.",
            assumptions="The checker should reject incomplete value-based configs.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_all_items_does_not_trigger_when_changes_are_too_small(self):
        alert = self._alert(is_all_items=True, direction="up", percentage=50.0)
        alert.reference_prices = json.dumps({"4151": 100, "11802": 200})
        result = self._command().check_threshold_alert(
            alert,
            self._prices(
                **{
                    "4151": {"high": 120, "low": 100},
                    "11802": {"high": 240, "low": 200},
                }
            ),
        )
        self._record_case(
            name="all_items_too_small",
            goal="All-items thresholds should stay quiet when the market move is under the configured threshold.",
            expected="False",
            observed=str(result),
            setup="No item reaches a +50% move.",
            assumptions="Threshold comparisons remain inclusive only at or above the configured value.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)
