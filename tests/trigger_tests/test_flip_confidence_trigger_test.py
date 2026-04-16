from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User

from Website.management.commands.check_alerts import Command
from Website.models import Alert

from .trigger_suite_base import TriggerReportMixin


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "flip_confidence_trigger_test.md"


class FlipConfidenceTriggerTests(TriggerReportMixin):
    REPORT_PATH = REPORT_PATH
    REPORT_TITLE = "Flip Confidence Trigger Test Report"
    REPORT_SCOPE = "Scope: flip confidence alert trigger behavior."

    ITEMS = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11235": "Dragonfire shield",
        "2001": "Bronze arrow",
    }

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="flip_confidence_trigger_tester",
            email="flip_confidence_trigger@example.com",
            password="test-password",
        )

    def _command(self):
        cmd = Command()
        cmd.get_item_mapping = lambda: self.ITEMS
        return cmd

    def _timeseries(self, *, high=100, low=90, vol=10_000, rows=3):
        payload = []
        for idx in range(rows):
            payload.append(
                {
                    "avgHighPrice": high,
                    "avgLowPrice": low,
                    "highPriceVolume": vol,
                    "lowPriceVolume": vol,
                    "timestamp": str(1000 + idx),
                }
            )
        return payload

    def _prices(self, **items):
        return {str(item_id): {"high": values["high"], "low": values["low"]} for item_id, values in items.items()}

    def _alert(self, **overrides):
        base = {
            "user": self.user,
            "alert_name": "Flip Confidence Trigger Test",
            "type": "flip_confidence",
            "confidence_timestep": "1h",
            "confidence_lookback": 3,
            "confidence_threshold": 70.0,
            "confidence_trigger_rule": "crosses_above",
            "confidence_cooldown": 0,
            "confidence_sustained_count": 1,
            "confidence_eval_interval": 0,
            "confidence_min_spread_pct": None,
            "confidence_min_volume": 1_000_000,
            "confidence_filter_vol_concentration": None,
            "item_id": None,
            "item_ids": None,
            "is_all_items": False,
        }
        base.update(overrides)
        if isinstance(base.get("item_ids"), list):
            base["item_ids"] = json.dumps(base["item_ids"])
        if isinstance(base.get("confidence_last_scores"), dict):
            base["confidence_last_scores"] = json.dumps(base["confidence_last_scores"])
        return Alert.objects.create(**base)

    def _run(self, alert, all_prices, *, score, timeseries=None):
        timeseries = timeseries or self._timeseries()
        cmd = self._command()
        with patch.object(Command, "fetch_timeseries_from_db", return_value=timeseries), patch(
            "Website.management.commands.check_alerts.compute_flip_confidence", return_value=score
        ):
            return cmd.check_flip_confidence_alert(alert, all_prices)

    def test_single_item_triggers_when_score_crosses_threshold(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        result = self._run(alert, self._prices(**{"4151": {"high": 120, "low": 100}}), score=80)
        self._record_case(
            name="single_crosses_above",
            goal="Single-item flip confidence should trigger when the score crosses the threshold.",
            expected="True",
            observed=str(result),
            setup="One item with a score above the configured threshold.",
            assumptions="The patched confidence score represents the computed market signal.",
            output=[f"return={result}", f"payload={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_single_item_triggers_on_delta_increase(self):
        alert = self._alert(
            item_id=4151,
            item_name=self.ITEMS["4151"],
            confidence_trigger_rule="delta_increase",
            confidence_threshold=20.0,
            confidence_last_scores={"4151": {"score": 50, "consecutive": 0, "last_eval": 0}},
        )
        result = self._run(alert, self._prices(**{"4151": {"high": 120, "low": 100}}), score=80)
        self._record_case(
            name="single_delta_increase",
            goal="Delta-increase mode should trigger when the score rises by the configured amount.",
            expected="True",
            observed=str(result),
            setup="The score rises from 50 to 80 with a delta threshold of 20.",
            assumptions="Previous score state is loaded from confidence_last_scores.",
            output=[f"return={result}", f"payload={alert.triggered_data}"],
        )
        self.assertTrue(result)

    def test_multi_item_triggers_and_returns_matching_items(self):
        alert = self._alert(item_ids=[4151, 11802], confidence_threshold=70.0)
        result = self._run(
            alert,
            self._prices(**{"4151": {"high": 120, "low": 100}, "11802": {"high": 220, "low": 200}}),
            score=82,
        )
        self._record_case(
            name="multi_crosses_above",
            goal="Multi-item flip confidence should trigger when watched items all score above threshold.",
            expected="True",
            observed=str(result),
            setup="Two watched items share the same high confidence score.",
            assumptions="Multi-item mode returns a list of triggered items.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)
        self.assertIsInstance(result, list)

    def test_all_items_triggers_and_sorts_the_payload(self):
        alert = self._alert(is_all_items=True, confidence_threshold=70.0)
        result = self._run(
            alert,
            self._prices(
                **{
                    "4151": {"high": 120, "low": 100},
                    "11802": {"high": 220, "low": 200},
                    "11235": {"high": 310, "low": 300},
                }
            ),
            score=85,
        )
        self._record_case(
            name="all_items_crosses_above",
            goal="All-items flip confidence should return a sorted payload of qualifying items.",
            expected="True",
            observed=str(result),
            setup="Every item passes the confidence threshold.",
            assumptions="All-items mode returns a list of triggered items.",
            output=[f"return={result}", f"triggered_data={alert.triggered_data}"],
        )
        self.assertTrue(result)
        self.assertIsInstance(result, list)

    def test_single_item_does_not_trigger_below_threshold(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"])
        result = self._run(alert, self._prices(**{"4151": {"high": 120, "low": 100}}), score=60)
        self._record_case(
            name="single_below_threshold",
            goal="A score below the threshold should not trigger flip confidence.",
            expected="False",
            observed=str(result),
            setup="The patched score stays below the alert threshold.",
            assumptions="Below-threshold scores should leave the alert silent.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_too_low(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], confidence_threshold=70.0)
        low_volume_timeseries = self._timeseries(vol=100)
        result = self._run(alert, self._prices(**{"4151": {"high": 120, "low": 100}}), score=85, timeseries=low_volume_timeseries)
        self._record_case(
            name="single_low_volume",
            goal="Flip confidence should skip items that do not meet the minimum volume gate.",
            expected="False",
            observed=str(result),
            setup="The score is high, but total GP volume is below the configured minimum.",
            assumptions="The volume pre-filter runs before the score comparison.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_concentrated(self):
        alert = self._alert(item_id=4151, item_name=self.ITEMS["4151"], confidence_threshold=70.0, confidence_filter_vol_concentration=40.0)
        concentrated = [
            {"avgHighPrice": 100, "avgLowPrice": 90, "highPriceVolume": 10_000, "lowPriceVolume": 10_000, "timestamp": "1"},
            {"avgHighPrice": 100, "avgLowPrice": 90, "highPriceVolume": 10, "lowPriceVolume": 10, "timestamp": "2"},
            {"avgHighPrice": 100, "avgLowPrice": 90, "highPriceVolume": 10, "lowPriceVolume": 10, "timestamp": "3"},
        ]
        result = self._run(alert, self._prices(**{"4151": {"high": 120, "low": 100}}), score=85, timeseries=concentrated)
        self._record_case(
            name="single_concentrated_volume",
            goal="Flip confidence should skip items where a single bucket dominates the lookback window.",
            expected="False",
            observed=str(result),
            setup="The lookback volume is too concentrated in one bucket.",
            assumptions="The concentration filter is evaluated before the trigger rule.",
            output=[f"return={result}"],
        )
        self.assertFalse(result)
