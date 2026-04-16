import json
import traceback
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from Website.management.commands.check_alerts import Command
from Website.models import Alert


REPORT_PATH = Path(__file__).resolve().parents[1] / "test_output" / "alert_volume_flip_confidence.md"


class FlipConfidenceVolumeRestrictionTests(TestCase):
    """
    Dedicated flip-confidence volume restriction suite.

    The test-king guidance asks for:
    - at least 10 tests
    - the first half focused on generic functionality
    - the second half focused on edge cases
    - a markdown report rewritten whenever the suite runs
    """

    default_item_names = {
        "4151": "Abyssal whip",
        "11802": "Dragon crossbow",
        "11212": "Dragon arrow tips",
        "2425": "Saradomin brew(4)",
        "11230": "Dragon darts",
    }

    report_cases = []
    active_case = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.report_cases = []
        cls._flush_report("suite_start")

    def setUp(self):
        self.command = Command()
        self.user = User.objects.create_user(
            username=f"flip_volume_{self._testMethodName}",
            email=f"{self._testMethodName}@example.com",
            password="test-password",
        )

    @classmethod
    def _flush_report(cls, status):
        lines = [
            "# Flip Confidence Volume Restriction Test Suite",
            "",
            f"Report status: {status}",
            f"Generated: {datetime.now(dt_timezone.utc).isoformat()}",
            "",
            "This file is rewritten every time the suite runs.",
            "It records the goal, setup, assumptions, verbose trace output,",
            "and the final result for each test case.",
            "",
        ]

        if not cls.report_cases:
            lines.extend([
                "No test cases have run yet.",
                "",
            ])

        for index, case in enumerate(cls.report_cases, start=1):
            lines.extend([
                f"## {index}. {case['title']}",
                "",
                f"Goal: {case['goal']}",
                f"What is being tested: {case['what']}",
                f"How it is being tested: {case['how']}",
                f"Setup: {case['setup']}",
                f"Assumptions: {case['assumptions']}",
                "Output:",
            ])
            if case["output"]:
                lines.extend([f"- {line}" for line in case["output"]])
            else:
                lines.append("- No runtime output recorded yet.")
            lines.append(f"Result: {case['result']}")
            if case.get("failure"):
                lines.append("Failure details:")
                lines.extend([f"  {line}" for line in case["failure"].splitlines()])
            if case.get("remediation"):
                lines.append(f"Prevention / next check: {case['remediation']}")
            lines.append("")

        REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _trace(self, message):
        print(message)
        if self.active_case is not None:
            self.active_case["output"].append(message)
            self._flush_report("running")

    def _run_case(self, *, title, goal, what, how, setup, assumptions, remediation, body):
        case = {
            "title": title,
            "goal": goal,
            "what": what,
            "how": how,
            "setup": setup,
            "assumptions": assumptions,
            "remediation": remediation,
            "output": [],
            "result": "RUNNING",
            "failure": None,
        }
        self.__class__.report_cases.append(case)
        self.__class__.active_case = case
        self._flush_report("running")

        self._trace(f"[START] {title}")
        self._trace(f"[GOAL] {goal}")
        self._trace(f"[WHAT] {what}")
        self._trace(f"[HOW] {how}")
        self._trace(f"[SETUP] {setup}")
        self._trace(f"[ASSUMPTIONS] {assumptions}")

        try:
            body()
        except Exception:
            case["result"] = "FAIL"
            case["failure"] = traceback.format_exc()
            self._trace("[RESULT] FAIL")
            self._flush_report("failure")
            raise
        else:
            case["result"] = "PASS"
            self._trace("[RESULT] PASS")
            self._flush_report("pass")
        finally:
            self.__class__.active_case = None

    def _make_bucket(self, *, high_price=100, low_price=100, high_volume=10, low_volume=10, timestamp=None):
        return {
            "avgHighPrice": high_price,
            "avgLowPrice": low_price,
            "highPriceVolume": high_volume,
            "lowPriceVolume": low_volume,
            "timestamp": timestamp or "2026-04-16T00:00:00Z",
        }

    def _make_series(self, bucket_specs):
        return [self._make_bucket(**spec) for spec in bucket_specs]

    def _make_all_prices(self, item_ids, *, high=110, low=100):
        return {str(item_id): {"high": high, "low": low} for item_id in item_ids}

    def _make_alert(self, **overrides):
        defaults = {
            "user": self.user,
            "alert_name": "Flip Confidence Volume Test",
            "type": "flip_confidence",
            "is_all_items": False,
            "item_id": 4151,
            "item_ids": None,
            "item_name": "Abyssal whip",
            "minimum_price": None,
            "maximum_price": None,
            "confidence_timestep": "1h",
            "confidence_lookback": 3,
            "confidence_threshold": 60.0,
            "confidence_trigger_rule": "crosses_above",
            "confidence_min_volume": 1,
            "confidence_filter_vol_concentration": None,
            "confidence_cooldown": 0,
            "confidence_sustained_count": 1,
            "confidence_eval_interval": 0,
            "confidence_last_scores": "{}",
            "confidence_min_spread_pct": None,
            "is_active": True,
            "is_triggered": False,
            "is_dismissed": False,
            "show_notification": False,
        }
        defaults.update(overrides)
        return Alert.objects.create(**defaults)

    def _evaluate_alert(self, alert, all_prices, series_map, *, score=82.5, item_mapping=None, fetch_hook=None):
        if item_mapping is None:
            item_mapping = dict(self.default_item_names)

        def fetch_timeseries(item_id, timestep, lookback):
            if fetch_hook is not None:
                fetch_hook(item_id, timestep, lookback)
            return series_map.get(str(item_id), [])

        with patch("Website.management.commands.check_alerts.compute_flip_confidence", return_value=score) as mocked_score:
            with patch.object(self.command, "fetch_timeseries_from_db", side_effect=fetch_timeseries) as mocked_fetch:
                with patch.object(self.command, "get_item_mapping", return_value=item_mapping):
                    result = self.command.check_flip_confidence_alert(alert, all_prices)
        return result, mocked_fetch, mocked_score

    def test_single_item_triggers_when_min_volume_met(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=75.0,
                confidence_min_volume=10_000,
                item_id=4151,
                item_name="Abyssal whip",
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 50, "low_volume": 50},
                    {"high_price": 100, "low_price": 100, "high_volume": 50, "low_volume": 50},
                    {"high_price": 100, "low_price": 100, "high_volume": 50, "low_volume": 50},
                ])
            }
            self._trace("Configured single-item alert with a generous GP volume floor and a high score.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=82.5)
            self._trace(f"Result: {result}")
            self._trace(f"Fetch calls: {mocked_fetch.call_count}")
            self._trace(f"Score calls: {mocked_score.call_count}")

            self.assertTrue(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)
            alert.refresh_from_db()
            payload = json.loads(alert.triggered_data)
            self.assertEqual(payload["item_id"], "4151")
            self.assertEqual(payload["threshold"], 75.0)

        self._run_case(
            title="Single-item trigger respects the configured volume floor",
            goal="A single-item flip-confidence alert should trigger when the item's total GP volume exceeds the configured minimum.",
            what="Single-mode trigger path, min-volume filtering, and single-item trigger payload storage.",
            how="Use a synthetic three-bucket series whose GP volume is safely above the floor and force the confidence score above threshold.",
            setup="Create a saved single-item alert with min volume 10,000 GP and a score threshold of 75.",
            assumptions="The alert checker should accept a normal single-item configuration and return True when the item clears the floor.",
            remediation="If this fails, check the min-volume comparison in check_flip_confidence_alert and confirm the GP volume sum is being computed from all buckets.",
            body=body,
        )

    def test_single_item_blocks_when_total_gp_volume_is_too_low(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=75.0,
                confidence_min_volume=10_000,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                ])
            }
            self._trace("Configured single-item alert with a very low-volume series.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=92.0)
            self._trace(f"Result: {result}")
            self._trace("Expectation: the item should be filtered out before the confidence score is even used.")

            self.assertFalse(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 0)

        self._run_case(
            title="Single-item alert blocks low GP volume",
            goal="A single-item flip-confidence alert should not trigger when the total GP volume is below the configured floor.",
            what="Single-mode low-volume rejection and early return before scoring.",
            how="Use a tiny synthetic series whose total GP volume is far below the limit while keeping the confidence score artificially high.",
            setup="Create a saved single-item alert with a 10,000 GP minimum and feed it a tiny series that only totals a few hundred GP.",
            assumptions="The checker should reject the item before compute_flip_confidence is consulted.",
            remediation="If this fails, inspect the min-volume branch in check_flip_confidence_alert and the GP volume formula that sums high and low legs.",
            body=body,
        )

    def test_multi_item_returns_only_items_that_meet_min_volume(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=70.0,
                confidence_min_volume=10_000,
                item_id=None,
                item_ids=json.dumps([4151, 11802]),
                item_name=None,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 40, "low_volume": 40},
                    {"high_price": 100, "low_price": 100, "high_volume": 40, "low_volume": 40},
                    {"high_price": 100, "low_price": 100, "high_volume": 40, "low_volume": 40},
                ]),
                "11802": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                ]),
            }
            self._trace("Configured multi-item alert with one liquid item and one illiquid item.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=88.0)
            self._trace(f"Result items: {result}")

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["item_id"], "4151")
            self.assertEqual(mocked_fetch.call_count, 2)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="Multi-item mode keeps only liquid items",
            goal="A multi-item flip-confidence alert should return only the items that satisfy the minimum volume gate.",
            what="Multi-item return type, per-item volume filtering, and exclusion of low-volume items.",
            how="Provide two selected items with identical confidence scores but very different GP volume totals.",
            setup="Create a saved multi-item alert containing two item ids and give one of them a tiny series that falls below the floor.",
            assumptions="The checker should evaluate both items and return only the liquid one.",
            remediation="If this fails, look for a regression in the item loop that applies min_volume after scoring instead of before.",
            body=body,
        )

    def test_all_items_returns_only_items_that_meet_min_volume(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=70.0,
                confidence_min_volume=10_000,
                is_all_items=True,
                item_id=None,
                item_ids=None,
                minimum_price=1,
                maximum_price=100_000_000,
                item_name="All items",
            )
            all_prices = self._make_all_prices([4151, 11802, 11212], high=110, low=100)
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 60, "low_volume": 60},
                    {"high_price": 100, "low_price": 100, "high_volume": 60, "low_volume": 60},
                    {"high_price": 100, "low_price": 100, "high_volume": 60, "low_volume": 60},
                ]),
                "11802": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                    {"high_price": 100, "low_price": 100, "high_volume": 1, "low_volume": 1},
                ]),
                "11212": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 55, "low_volume": 55},
                    {"high_price": 100, "low_price": 100, "high_volume": 55, "low_volume": 55},
                    {"high_price": 100, "low_price": 100, "high_volume": 55, "low_volume": 55},
                ]),
            }
            self._trace("Configured all-items mode with two liquid items and one filtered-out item.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, all_prices, series_map, score=87.0)
            self._trace(f"Result items: {result}")

            self.assertIsInstance(result, list)
            self.assertEqual({row["item_id"] for row in result}, {"4151", "11212"})
            self.assertEqual(mocked_fetch.call_count, 3)
            self.assertEqual(mocked_score.call_count, 2)

        self._run_case(
            title="All-items mode keeps only liquid items",
            goal="An all-items flip-confidence alert should only return market items whose total GP volume clears the floor.",
            what="All-items prefilter path, GP-volume enforcement, and list output shape.",
            how="Feed three market items into the live checker, but only two of them are given enough synthetic volume to qualify.",
            setup="Create a saved all-items alert with minimum and maximum price filters that allow the synthetic items through.",
            assumptions="The checker should scan all market items and return a list containing only the liquid ones.",
            remediation="If this fails, inspect the all-items branch that prefilters by price and then applies the volume floor to each item.",
            body=body,
        )

    def test_min_volume_none_disables_the_volume_gate(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=50.0,
                confidence_min_volume=None,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 0, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 0, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 0, "low_volume": 0},
                ])
            }
            self._trace("Configured a single-item alert with no configured volume floor.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=80.0)
            self._trace(f"Result: {result}")

            self.assertTrue(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="No configured volume floor means no volume rejection",
            goal="When confidence_min_volume is not set, a valid flip-confidence alert should be allowed to trigger regardless of GP volume.",
            what="Disabled volume gate edge case for a supported single-item mode.",
            how="Leave confidence_min_volume as None and feed the checker a zero-volume series with a high confidence score.",
            setup="Create a saved alert with a threshold but no min-volume floor.",
            assumptions="The checker should skip the volume gate entirely when the floor is unset.",
            remediation="If this fails, the min-volume branch is treating None like a real threshold instead of a disabled filter.",
            body=body,
        )

    def test_missing_timeseries_data_short_circuits_before_scoring(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=50.0,
                confidence_min_volume=1_000,
                item_id=4151,
            )
            self._trace("Configured a single-item alert whose history lookup returns no rows at all.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, {"4151": []}, score=90.0)
            self._trace(f"Result: {result}")

            self.assertFalse(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 0)

        self._run_case(
            title="Missing historical data blocks the alert cleanly",
            goal="A flip-confidence alert should not trigger when the requested history is unavailable.",
            what="Empty history edge case and the early return that prevents scoring with too few buckets.",
            how="Return an empty timeseries list from the DB fetch stub.",
            setup="Create a saved single-item alert with a normal threshold and a minimum volume floor.",
            assumptions="The checker should stop before volume math or confidence scoring when there is no historical data.",
            remediation="If this fails, the history-fetch branch is no longer protecting compute_flip_confidence from empty data.",
            body=body,
        )

    def test_volume_concentration_filter_blocks_dominant_bucket(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=60.0,
                confidence_min_volume=1_000,
                confidence_filter_vol_concentration=75.0,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 1_000, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 10, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 10, "low_volume": 0},
                ])
            }
            self._trace("Configured a series where one bucket dominates more than 75 percent of the trade count.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=95.0)
            self._trace(f"Result: {result}")

            self.assertFalse(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 0)

        self._run_case(
            title="Volume concentration filter rejects a single dominant bucket",
            goal="A flip-confidence alert should skip items whose total volume is too concentrated in one bucket.",
            what="confidence_filter_vol_concentration rejection path.",
            how="Build a synthetic timeseries where one bucket accounts for more than 75 percent of total trade count.",
            setup="Create a single-item alert with a concentration ceiling of 75 percent.",
            assumptions="The concentration filter is supposed to run after GP volume passes and before confidence scoring.",
            remediation="If this fails, the concentration ratio check or the bucket-volume sum is not being applied correctly.",
            body=body,
        )

    def test_volume_concentration_filter_allows_balanced_distribution(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=60.0,
                confidence_min_volume=1_000,
                confidence_filter_vol_concentration=75.0,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 350, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 330, "low_volume": 0},
                    {"high_price": 100, "low_price": 100, "high_volume": 320, "low_volume": 0},
                ])
            }
            self._trace("Configured a balanced series where no single bucket dominates the total volume.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=91.0)
            self._trace(f"Result: {result}")

            self.assertTrue(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="Balanced volume distribution is allowed through",
            goal="A concentration filter should not block items that spread volume across several buckets.",
            what="confidence_filter_vol_concentration pass path.",
            how="Feed the checker a balanced three-bucket series that stays well below the 75 percent concentration limit.",
            setup="Create a single-item alert with the same 75 percent concentration ceiling used in the blocking case.",
            assumptions="The checker should evaluate the item and allow the score through when volume is spread out.",
            remediation="If this fails, the concentration filter may be too aggressive or using the wrong denominator.",
            body=body,
        )

    def test_delta_increase_mode_triggers_when_score_rises_and_volume_passes(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=15.0,
                confidence_trigger_rule="delta_increase",
                confidence_min_volume=1_000,
                confidence_last_scores=json.dumps({"4151": {"score": 40.0, "consecutive": 0, "last_eval": 0}}),
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                ])
            }
            self._trace("Configured delta_increase mode with a prior score of 40 and a current score above that by 15+.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=60.0)
            self._trace(f"Result: {result}")

            self.assertTrue(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="Delta increase mode still obeys the volume floor",
            goal="The delta_increase rule should trigger only when the item rises by the configured delta and still meets the GP volume filter.",
            what="Trigger-rule interaction with the min-volume gate.",
            how="Seed prior confidence state, force the score upward, and keep the synthetic volume safely above the configured floor.",
            setup="Create a single-item alert in delta_increase mode with a prior score recorded in confidence_last_scores.",
            assumptions="The checker should compare the new score against the saved prior score only after the volume gate passes.",
            remediation="If this fails, delta_increase may be bypassing the normal prefilters or reading previous scores incorrectly.",
            body=body,
        )

    def test_crosses_above_mode_blocks_when_score_is_below_threshold_even_with_volume(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=70.0,
                confidence_trigger_rule="crosses_above",
                confidence_min_volume=1_000,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                    {"high_price": 100, "low_price": 100, "high_volume": 100, "low_volume": 100},
                ])
            }
            self._trace("Configured crosses_above mode where the score remains under the threshold even though volume is healthy.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(alert, {}, series_map, score=65.0)
            self._trace(f"Result: {result}")

            self.assertFalse(result)
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="Crosses-above still respects the threshold after volume filtering",
            goal="A flip-confidence alert should not trigger if the confidence score stays below the configured threshold, even when volume is healthy.",
            what="Threshold interaction after the volume gate has passed.",
            how="Use a high-volume series, but force the confidence score to remain under the threshold.",
            setup="Create a single-item alert using the default crosses_above trigger rule and a reasonable volume floor.",
            assumptions="Healthy volume alone should never be enough to trigger the alert without the score crossing the threshold.",
            remediation="If this fails, the score-vs-threshold comparison is not being enforced after the volume checks.",
            body=body,
        )

    def test_lookback_under_three_is_clamped_before_timeseries_fetch(self):
        def body():
            alert = self._make_alert(
                confidence_threshold=60.0,
                confidence_lookback=1,
                confidence_min_volume=1_000,
                item_id=4151,
            )
            series_map = {
                "4151": self._make_series([
                    {"high_price": 100, "low_price": 100, "high_volume": 80, "low_volume": 80},
                    {"high_price": 100, "low_price": 100, "high_volume": 80, "low_volume": 80},
                    {"high_price": 100, "low_price": 100, "high_volume": 80, "low_volume": 80},
                ])
            }
            observed_lookbacks = []

            def capture_fetch(item_id, timestep, lookback):
                observed_lookbacks.append(lookback)

            self._trace("Configured a lookback shorter than the minimum allowed window.")
            result, mocked_fetch, mocked_score = self._evaluate_alert(
                alert,
                {},
                series_map,
                score=88.0,
                fetch_hook=capture_fetch,
            )
            self._trace(f"Observed lookbacks: {observed_lookbacks}")
            self._trace(f"Result: {result}")

            self.assertTrue(result)
            self.assertEqual(observed_lookbacks, [3])
            self.assertEqual(mocked_fetch.call_count, 1)
            self.assertEqual(mocked_score.call_count, 1)

        self._run_case(
            title="Lookback values below three are clamped to the minimum",
            goal="Flip-confidence alerts should normalize tiny lookback settings up to the minimum usable window.",
            what="Lookback clamp edge case and its interaction with the volume floor.",
            how="Set confidence_lookback to 1, then verify the fetch hook sees a lookback of 3 and the alert still evaluates normally.",
            setup="Create a single-item alert with a deliberately too-small lookback value.",
            assumptions="The checker should clamp lookback to 3 before asking for history.",
            remediation="If this fails, the lookback normalization path is not protecting compute_flip_confidence from undersized history windows.",
            body=body,
        )

    @classmethod
    def tearDownClass(cls):
        cls._flush_report("suite_complete")
        super().tearDownClass()
