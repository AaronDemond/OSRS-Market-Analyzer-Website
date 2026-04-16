from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume

from .trigger_suite_base import TriggerReportMixin


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "spread_trigger_test.md"


class SpreadTriggerTests(TriggerReportMixin):
    REPORT_PATH = REPORT_PATH
    REPORT_TITLE = "Spread Trigger Test Report"
    REPORT_SCOPE = "Scope: spread alert trigger behavior."

    ITEMS = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11235": "Dragonfire shield",
        "2001": "Bronze arrow",
    }

    SPREAD_THRESHOLD = 6.0
    MIN_VOLUME = 1_000_000

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="spread_trigger_tester",
            email="spread_trigger@example.com",
            password="test-password",
        )

    def _command(self):
        cmd = Command()
        cmd.stdout = type("Stdout", (), {"write": lambda self, msg: None})()
        cmd.get_item_mapping = lambda: self.ITEMS
        return cmd

    def _alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Spread Trigger Test",
            "type": "spread",
            "percentage": self.SPREAD_THRESHOLD,
            "min_volume": self.MIN_VOLUME,
            "minimum_price": 1,
            "maximum_price": 100_000_000,
            "item_id": None,
            "item_ids": None,
            "is_all_items": False,
        }
        base.update(overrides)
        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        return Alert.objects.create(**base)

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

    def test_single_item_triggers_when_spread_and_volume_pass(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        self._volume("4151", 5_000_000)
        result = self._command().check_alert(alert, self._prices(**{"4151": {"high": 112, "low": 100}}))
        self._record_case(
            name="single_trigger_basic",
            goal="Single-item spread alerts should trigger when spread and volume both pass.",
            expected="True",
            observed=str(result),
            setup="One watched item at 12% spread with fresh volume above the minimum.",
            assumptions="Spread uses ((high - low) / low) * 100 and the volume gate is inclusive.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_single_item_triggers_at_exact_threshold(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], percentage=6.0)
        self._volume("4151", self.MIN_VOLUME)
        result = self._command().check_alert(alert, self._prices(**{"4151": {"high": 106, "low": 100}}))
        self._record_case(
            name="single_trigger_exact_threshold",
            goal="Spread thresholds should trigger when the spread exactly matches the configured percentage.",
            expected="True",
            observed=str(result),
            setup="One watched item at exactly 6% spread with volume exactly at the threshold.",
            assumptions="Both spread and min_volume comparisons are inclusive.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_multi_item_triggers_with_all_matching_watched_items(self):
        alert = self._alert(item_ids=[4151, 11802])
        self._volume("4151", 2_000_000)
        self._volume("11802", 3_000_000)
        result = self._command().check_alert(
            alert,
            self._prices(
                **{
                    "4151": {"high": 112, "low": 100},
                    "11802": {"high": 160, "low": 140},
                    "11235": {"high": 120, "low": 100},
                }
            ),
        )
        self._record_case(
            name="multi_trigger_watched_items",
            goal="Multi-item spread alerts should return all watched items that qualify.",
            expected="List containing both watched items",
            observed=str(result),
            setup="Two watched items both clear spread and volume; an unwatched item is also present in market data.",
            assumptions="Only item_ids members are considered for multi-item spread alerts.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertEqual({entry["item_id"] for entry in result}, {"4151", "11802"})

    def test_all_items_triggers_and_sorts_by_spread_desc(self):
        alert = self._alert(is_all_items=True)
        self._volume("4151", 2_500_000)
        self._volume("11802", 2_000_000)
        self._volume("11235", 5_000_000)
        result = self._command().check_alert(
            alert,
            self._prices(
                **{
                    "4151": {"high": 112, "low": 100},
                    "11802": {"high": 155, "low": 140},
                    "11235": {"high": 140, "low": 100},
                }
            ),
        )
        self._record_case(
            name="all_items_trigger_sorted",
            goal="All-items spread alerts should return every qualifying item sorted by spread descending.",
            expected="List of three items ordered by spread descending",
            observed=str(result),
            setup="Three items all pass spread and volume with clearly different spreads.",
            assumptions="Triggered payload ordering reflects highest spreads first.",
            output=[f"return={result}"],
        )
        self.assertIsInstance(result, list)
        self.assertEqual([entry["item_id"] for entry in result], ["11235", "4151", "11802"])

    def test_single_item_does_not_trigger_below_threshold(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], percentage=10.0)
        self._volume("4151", 5_000_000)
        result = self._command().check_alert(alert, self._prices(**{"4151": {"high": 106, "low": 100}}))
        self._record_case(
            name="single_no_trigger_below_threshold",
            goal="A spread below the configured threshold should not trigger.",
            expected="False",
            observed=str(result),
            setup="One watched item at 6% spread against a 10% threshold.",
            assumptions="Volume passes, so the spread comparison alone decides the outcome.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_too_low(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        self._volume("4151", 999_999)
        result = self._command().check_alert(alert, self._prices(**{"4151": {"high": 112, "low": 100}}))
        self._record_case(
            name="single_no_trigger_low_volume",
            goal="Spread alerts should stay silent when the item fails the minimum hourly volume requirement.",
            expected="False",
            observed=str(result),
            setup="One watched item clears spread but is one unit under the hourly volume minimum.",
            assumptions="Volume gating happens before the item is accepted into triggered_data.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_low_price_is_missing(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        self._volume("4151", 5_000_000)
        result = self._command().check_alert(alert, {"4151": {"high": 112, "low": None}})
        self._record_case(
            name="single_no_trigger_missing_low",
            goal="Spread alerts should not trigger when market data is incomplete.",
            expected="False",
            observed=str(result),
            setup="The watched item has a high price but no low price in the market snapshot.",
            assumptions="Spread calculation returns None when low is missing.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)
