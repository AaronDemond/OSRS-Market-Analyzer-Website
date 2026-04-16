from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "alert_volume_threshold.md"


class AlertVolumeThresholdTests(TestCase):
    """
    Dedicated threshold-volume coverage.

    This suite focuses on threshold alerts obeying hourly volume restrictions,
    including percentage and value thresholds, single-item, multi-item, all-items,
    stale and missing volume handling, and reference-price selection edge cases.
    """

    ITEM_NAMES = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11283": "Dragonfire shield",
        "2001": "Bronze arrow",
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._report_lines = []
        cls._reset_report()

    @classmethod
    def tearDownClass(cls):
        cls._report_lines.append("")
        cls._report_lines.append("## Suite Summary")
        cls._report_lines.append("- Status: completed in the test runner")
        cls._write_report()
        super().tearDownClass()

    @classmethod
    def _reset_report(cls):
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        cls._report_lines = [
            "# Alert Volume Threshold Suite",
            "",
            f"Last rewritten: {timestamp}",
            "",
            "This file is rewritten every time the suite runs.",
            "",
            "Scope: threshold alerts and hourly volume restrictions.",
        ]
        cls._write_report()

    @classmethod
    def _write_report(cls):
        REPORT_PATH.write_text("\n".join(cls._report_lines).rstrip() + "\n", encoding="utf-8")

    def _append_report(self, title, goal, explicit, how, setup, assumptions, observed, result):
        self.__class__._report_lines.extend(
            [
                "",
                f"## {title}",
                f"Goal: {goal}",
                f"Explicit check: {explicit}",
                f"How: {how}",
                f"Setup: {setup}",
                f"Assumptions: {assumptions}",
                "Observed output:",
            ]
        )
        self.__class__._report_lines.extend([f"- {line}" for line in observed])
        self.__class__._report_lines.extend(
            [
                f"Result: {result}",
            ]
        )
        self.__class__._write_report()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="threshold_volume_tester",
            password="test-password",
        )

    def _command(self):
        return Command()

    def _item_mapping(self):
        return dict(self.ITEM_NAMES)

    def _market_prices(self, **items):
        return {
            str(item_id): {
                "high": payload["high"],
                "low": payload["low"],
            }
            for item_id, payload in items.items()
        }

    def _fresh_volume(self, item_id, volume, minutes_ago=30):
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=self.ITEM_NAMES[str(item_id)],
            volume=volume,
            timestamp=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def _stale_volume(self, item_id, volume, minutes_ago=180):
        return self._fresh_volume(item_id, volume, minutes_ago=minutes_ago)

    def _threshold_alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Threshold Volume Test",
            "type": "threshold",
            "direction": "up",
            "threshold_type": "percentage",
            "percentage": 10.0,
            "target_price": None,
            "reference": "average",
            "item_id": None,
            "item_name": "Threshold Watch",
            "item_ids": None,
            "is_all_items": False,
            "reference_prices": None,
            "min_volume": 10_000_000,
            "minimum_price": None,
            "maximum_price": None,
        }
        base.update(overrides)

        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        if isinstance(base.get("reference_prices"), dict):
            base["reference_prices"] = json.dumps(base["reference_prices"])

        return Alert.objects.create(**base)

    def _evaluate(self, alert, all_prices):
        command = self._command()
        with patch.object(Command, "get_item_mapping", return_value=self._item_mapping()):
            return command.check_threshold_alert(alert, all_prices)

    def test_single_percentage_threshold_triggers_above_target_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="up",
            percentage=20.0,
            threshold_type="percentage",
            reference="high",
            reference_prices={"4151": 100},
        )
        self._fresh_volume(4151, 25_000_000)
        prices = self._market_prices(**{"4151": {"high": 150, "low": 90}})

        result = self._evaluate(alert, prices)
        expected = True
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is expected else "FAIL"
        self._append_report(
            "Single percentage threshold above",
            "Verify a single-item percentage threshold fires when the price rises above the configured threshold and hourly volume is fresh.",
            "A +20% threshold should trigger on a +50% change, provided the volume gate is open.",
            "Check one item with a fresh hourly volume snapshot and a high reference price.",
            "Created one threshold alert, one fresh HourlyItemVolume row, and one market snapshot.",
            "Fresh volume should satisfy the filter, and the checker should compare against the high price reference.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Single-item percentage threshold should trigger when volume is fresh and the change is above the threshold.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["item_id"], "4151")
        self.assertEqual(payload["reference_price"], 100)
        self.assertEqual(payload["current_price"], 150)

    def test_single_percentage_threshold_triggers_below_target_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="down",
            percentage=5.0,
            threshold_type="percentage",
            reference="low",
            reference_prices={"4151": 100},
        )
        self._fresh_volume(4151, 25_000_000)
        prices = self._market_prices(**{"4151": {"high": 150, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Single percentage threshold below",
            "Verify a single-item percentage threshold fires when the price falls below the configured threshold and hourly volume is fresh.",
            "A -5% threshold should trigger on a -10% move, provided the volume gate is open.",
            "Check one item with a fresh hourly volume snapshot and a low reference price.",
            "Created one threshold alert, one fresh HourlyItemVolume row, and one market snapshot.",
            "Fresh volume should satisfy the filter, and the checker should compare against the low price reference.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Single-item percentage threshold should trigger when volume is fresh and the change is below the threshold.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["item_id"], "4151")
        self.assertEqual(payload["reference_price"], 100)
        self.assertEqual(payload["current_price"], 90)

    def test_single_value_threshold_triggers_above_target_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="up",
            threshold_type="value",
            target_price=120,
            reference="high",
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 30_000_000)
        prices = self._market_prices(**{"4151": {"high": 150, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Single value threshold above",
            "Verify a single-item value threshold fires when the current price is at or above the target and the volume gate passes.",
            "A target of 120 gp should trigger when the high price is 150 gp.",
            "Check one item with fresh hourly volume and a high reference price.",
            "Created one value threshold alert and one fresh hourly volume snapshot.",
            "Fresh volume should allow the current price comparison to proceed.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Single-item value threshold should trigger when the current price is at or above target and volume is fresh.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["threshold_type"], "value")
        self.assertEqual(payload["target_price"], 120)
        self.assertEqual(payload["current_price"], 150)

    def test_single_value_threshold_triggers_below_target_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="down",
            threshold_type="value",
            target_price=120,
            reference="low",
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 30_000_000)
        prices = self._market_prices(**{"4151": {"high": 150, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Single value threshold below",
            "Verify a single-item value threshold fires when the current price falls to or below the target and the volume gate passes.",
            "A target of 120 gp should trigger when the low price is 90 gp.",
            "Check one item with fresh hourly volume and a low reference price.",
            "Created one value threshold alert and one fresh hourly volume snapshot.",
            "Fresh volume should allow the current price comparison to proceed.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Single-item value threshold should trigger when the current price is at or below target and volume is fresh.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["threshold_type"], "value")
        self.assertEqual(payload["target_price"], 120)
        self.assertEqual(payload["current_price"], 90)

    def test_multi_item_percentage_threshold_returns_every_qualifying_item_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_name="Multi threshold test",
            item_ids=[4151, 11802],
            percentage=20.0,
            direction="up",
            threshold_type="percentage",
            reference="average",
            reference_prices={"4151": 100, "11802": 200},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 12_000_000)
        self._fresh_volume(11802, 15_000_000)
        prices = self._market_prices(
            **{
                "4151": {"high": 150, "low": 90},
                "11802": {"high": 280, "low": 240},
            }
        )

        result = self._evaluate(alert, prices)
        result_ids = [item["item_id"] for item in result]
        observed = [f"return value: {result}", f"triggered item ids: {result_ids}"]
        outcome = "PASS" if result_ids == ["4151", "11802"] or result_ids == ["11802", "4151"] else "FAIL"
        self._append_report(
            "Multi-item percentage threshold with fresh volume",
            "Verify a multi-item threshold alert returns every qualifying item when each item has fresh volume and meets the percentage threshold.",
            "Both selected items should remain in the triggered list because their hourly volume is fresh.",
            "Check two tracked items with fresh hourly volume snapshots and percentage-based reference prices.",
            "Created one multi-item alert, two fresh volume rows, and two price snapshots.",
            "The checker should compare each item against its stored reference price and keep both when both qualify.",
            observed,
            f"{outcome}: expected both item IDs and got {result_ids}.",
        )
        self.assertEqual({item["item_id"] for item in result}, {"4151", "11802"})

    def test_all_items_percentage_threshold_returns_multiple_items_with_fresh_volume(self):
        alert = self._threshold_alert(
            item_name="All items threshold test",
            is_all_items=True,
            percentage=15.0,
            direction="up",
            threshold_type="percentage",
            reference="average",
            reference_prices={"4151": 100, "11802": 200, "11283": 300},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 12_000_000)
        self._fresh_volume(11802, 15_000_000)
        self._fresh_volume(11283, 18_000_000)
        prices = self._market_prices(
            **{
                "4151": {"high": 140, "low": 100},
                "11802": {"high": 300, "low": 220},
                "11283": {"high": 360, "low": 300},
            }
        )

        result = self._evaluate(alert, prices)
        result_ids = [item["item_id"] for item in result]
        observed = [f"return value: {result}", f"triggered item ids: {result_ids}"]
        outcome = "PASS" if len(result_ids) >= 2 else "FAIL"
        self._append_report(
            "All-items percentage threshold with fresh volume",
            "Verify an all-items threshold alert returns multiple qualifying items when the hourly volume for each item is fresh.",
            "Multiple items should survive the filter because all of them meet the threshold and the volume gate.",
            "Scan the market snapshot with three items, all of which have fresh volume rows.",
            "Created one all-items alert, three fresh volume rows, and three price snapshots.",
            "The checker should evaluate every item and keep more than one result.",
            observed,
            f"{outcome}: expected multiple items and got {result_ids}.",
        )
        self.assertGreaterEqual(len(result), 2)

    def test_single_percentage_threshold_blocks_when_volume_is_stale(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="up",
            percentage=5.0,
            threshold_type="percentage",
            reference="high",
            reference_prices={"4151": 100},
            min_volume=10_000_000,
        )
        self._stale_volume(4151, 40_000_000)
        prices = self._market_prices(**{"4151": {"high": 140, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", "expected: False because the hourly volume snapshot is stale"]
        outcome = "PASS" if result is False else "FAIL"
        self._append_report(
            "Single percentage threshold blocks stale volume",
            "Verify a single-item percentage threshold does not trigger when the most recent volume snapshot is stale.",
            "A stale hourly volume row must be treated as missing data and block the alert.",
            "Check one item whose only volume row is older than the freshness cutoff.",
            "Created one alert, one stale volume row, and one price snapshot that otherwise qualifies.",
            "Stale volume should be rejected even if the price move is large enough.",
            observed,
            f"{outcome}: expected False and got {result}.",
        )
        self.assertFalse(result, "Single-item percentage threshold should not trigger when the hourly volume row is stale.")

    def test_single_value_threshold_blocks_when_volume_is_missing(self):
        alert = self._threshold_alert(
            item_id=11802,
            item_name="Dragon crossbow",
            direction="up",
            threshold_type="value",
            target_price=220,
            reference="high",
            min_volume=10_000_000,
        )
        prices = self._market_prices(**{"11802": {"high": 260, "low": 200}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", "expected: False because no hourly volume row exists"]
        outcome = "PASS" if result is False else "FAIL"
        self._append_report(
            "Single value threshold blocks missing volume",
            "Verify a single-item value threshold does not trigger when there is no hourly volume data at all.",
            "A missing hourly volume row must block the alert just like stale data does.",
            "Check one item with a valid market move but no saved volume snapshot.",
            "Created one alert and one qualifying price snapshot, but intentionally no volume row.",
            "No volume should mean the item is treated as ineligible for threshold triggering.",
            observed,
            f"{outcome}: expected False and got {result}.",
        )
        self.assertFalse(result, "Single-item value threshold should not trigger when the hourly volume row is missing.")

    def test_multi_item_threshold_excludes_stale_volume_item(self):
        alert = self._threshold_alert(
            item_name="Multi threshold stale test",
            item_ids=[4151, 11802],
            percentage=15.0,
            direction="up",
            threshold_type="percentage",
            reference="average",
            reference_prices={"4151": 100, "11802": 200},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 12_000_000)
        self._stale_volume(11802, 40_000_000)
        prices = self._market_prices(
            **{
                "4151": {"high": 160, "low": 140},
                "11802": {"high": 300, "low": 260},
            }
        )

        result = self._evaluate(alert, prices)
        result_ids = [item["item_id"] for item in result]
        observed = [f"return value: {result}", f"triggered item ids: {result_ids}"]
        outcome = "PASS" if result_ids == ["4151"] else "FAIL"
        self._append_report(
            "Multi-item threshold excludes stale volume",
            "Verify a multi-item threshold alert keeps the fresh item and excludes the stale-volume item.",
            "Only the fresh item should survive the volume filter.",
            "Check two selected items with the same price behavior, but only one fresh volume row.",
            "Created one alert, one fresh volume row, one stale volume row, and two qualifying price snapshots.",
            "The checker should filter the stale item out before returning the triggered list.",
            observed,
            f"{outcome}: expected only 4151 and got {result_ids}.",
        )
        self.assertEqual(result_ids, ["4151"])

    def test_all_items_threshold_excludes_missing_volume_item(self):
        alert = self._threshold_alert(
            item_name="All threshold missing test",
            is_all_items=True,
            percentage=5.0,
            direction="up",
            threshold_type="percentage",
            reference="average",
            reference_prices={"4151": 100, "11802": 200, "11283": 300},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 12_000_000)
        self._fresh_volume(11802, 15_000_000)
        prices = self._market_prices(
            **{
                "4151": {"high": 130, "low": 100},
                "11802": {"high": 250, "low": 180},
                "11283": {"high": 380, "low": 260},
            }
        )

        result = self._evaluate(alert, prices)
        result_ids = {item["item_id"] for item in result}
        observed = [f"return value: {result}", f"triggered item ids: {sorted(result_ids)}"]
        outcome = "PASS" if "11283" not in result_ids else "FAIL"
        self._append_report(
            "All-items threshold excludes missing volume",
            "Verify an all-items threshold alert omits items with no hourly volume record while keeping qualifying items that do have volume.",
            "The missing-volume item must not appear in the triggered list even if its price move qualifies.",
            "Check three market items, two with fresh volume rows and one without any volume row.",
            "Created one alert, two fresh volume rows, one missing volume item, and three qualifying price snapshots.",
            "The checker should quietly skip the item with no volume row.",
            observed,
            f"{outcome}: expected the missing-volume item to be excluded.",
        )
        self.assertNotIn("11283", result_ids)
        self.assertEqual(result_ids, {"4151", "11802"})

    def test_percentage_threshold_uses_high_reference_price(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="up",
            percentage=15.0,
            threshold_type="percentage",
            reference="high",
            reference_prices={"4151": 100},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 15_000_000)
        prices = self._market_prices(**{"4151": {"high": 140, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Reference price edge case: high",
            "Verify percentage thresholds compare against the high price when the alert reference is set to high.",
            "The high reference should drive the percent-change calculation.",
            "Use a price snapshot where the high is well above baseline and the low is irrelevant for the calculation.",
            "Created one alert, one fresh volume row, and one price snapshot with a strong high-side move.",
            "A high reference should make the alert trigger on the buy-side price.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "High-reference threshold should use the high price for comparison.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["current_price"], 140)

    def test_percentage_threshold_uses_low_reference_price(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="down",
            percentage=5.0,
            threshold_type="percentage",
            reference="low",
            reference_prices={"4151": 100},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 15_000_000)
        prices = self._market_prices(**{"4151": {"high": 140, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Reference price edge case: low",
            "Verify percentage thresholds compare against the low price when the alert reference is set to low.",
            "The low reference should drive the percent-change calculation.",
            "Use a price snapshot where the low is below baseline and the high is irrelevant for the calculation.",
            "Created one alert, one fresh volume row, and one price snapshot with a strong low-side move.",
            "A low reference should make the alert trigger on the sell-side price.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Low-reference threshold should use the low price for comparison.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["current_price"], 90)

    def test_percentage_threshold_uses_average_reference_price(self):
        alert = self._threshold_alert(
            item_id=4151,
            item_name="Abyssal whip",
            direction="up",
            percentage=15.0,
            threshold_type="percentage",
            reference="average",
            reference_prices={"4151": 100},
            min_volume=10_000_000,
        )
        self._fresh_volume(4151, 15_000_000)
        prices = self._market_prices(**{"4151": {"high": 150, "low": 90}})

        result = self._evaluate(alert, prices)
        observed = [f"return value: {result}", f"triggered_data: {alert.triggered_data}"]
        outcome = "PASS" if result is True else "FAIL"
        self._append_report(
            "Reference price edge case: average",
            "Verify percentage thresholds compare against the midpoint price when the alert reference is set to average.",
            "The average reference should use the midpoint of high and low prices.",
            "Use a price snapshot where the midpoint is above baseline and the alert should cross the threshold exactly as intended.",
            "Created one alert, one fresh volume row, and one price snapshot with a midpoint high enough to trigger.",
            "Average price should be computed from the two market sides, not from one side alone.",
            observed,
            f"{outcome}: expected True and got {result}.",
        )
        self.assertTrue(result, "Average-reference threshold should use the midpoint price for comparison.")
        payload = json.loads(alert.triggered_data)
        self.assertEqual(payload["current_price"], 120)
