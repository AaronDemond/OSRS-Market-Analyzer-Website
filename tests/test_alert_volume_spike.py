"""
Dedicated spike alert volume restriction tests.

What: Exercises the live spike alert checker against a set of volume-focused
      scenarios.
Why: Spike alerts should respect hourly GP volume limits across single-item,
     multi-item, and all-items modes, while also handling stale and missing
     volume snapshots safely.
How: Build real Alert and HourlyItemVolume fixtures, seed the command's
     rolling price history, and call Command.check_alert() directly.

The test suite writes a markdown report to:
    C:\\Users\\19024\\OSRSWebsite\\test_output\\alert_volume_spike.md

That report is rewritten every time the suite runs.
"""

from collections import defaultdict
import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


ROOT_DIR = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT_DIR / "test_output" / "alert_volume_spike.md"
REPORT_CASES = []


def _render_result(result):
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, sort_keys=True)
    return repr(result)


def _write_report():
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Alert Volume Spike Test Report",
        "",
        f"Generated at: {timezone.now().isoformat()}",
        "",
        "This file is rewritten by `tests/test_alert_volume_spike.py` every time the suite runs.",
        "",
    ]

    if not REPORT_CASES:
        lines.extend([
            "No cases have been recorded yet.",
            "",
        ])
    else:
        for index, case in enumerate(REPORT_CASES, start=1):
            lines.extend([
                f"## {index}. {case['name']}",
                "",
                f"- Goal: {case['goal']}",
                f"- What is being tested: {case['tested']}",
                f"- How it is being tested: {case['how']}",
                f"- Setup: {case['setup']}",
                f"- Assumptions: {case['assumptions']}",
                f"- Expected result: {case['expected']}",
                f"- Observed result: {case['observed']}",
                "",
                "### Captured Output",
                "```text",
            ])
            output_lines = case.get("output") or ["(no command output captured)"]
            lines.extend(output_lines)
            lines.extend([
                "```",
                "",
            ])
            notes = case.get("notes")
            if notes:
                lines.extend([
                    "### Notes",
                    notes,
                    "",
                ])

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SpikeVolumeTests(TestCase):
    ITEM_MAPPING = {
        "100": "Dragon Bones",
        "200": "Abyssal Whip",
        "300": "Bandos Chestplate",
        "400": "Armadyl Godsword",
    }

    TIME_FRAME_MINUTES = 60
    MIN_VOLUME = 1_000_000
    BASELINES = {
        "100": 10_000,
        "200": 2_500_000,
        "300": 15_000_000,
        "400": 30_000_000,
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        REPORT_CASES.clear()
        _write_report()

    @classmethod
    def tearDownClass(cls):
        _write_report()
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"spike_volume_{timezone.now().timestamp()}",
            email="spike_volume@example.com",
            password="testpass123",
        )

    def _make_command(self):
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        cmd.get_item_mapping = lambda: self.ITEM_MAPPING
        return cmd

    def _seed_baseline(self, cmd, item_id, reference="high", baseline_price=None):
        baseline_price = baseline_price if baseline_price is not None else self.BASELINES[str(item_id)]
        baseline_ts = time.time() - (self.TIME_FRAME_MINUTES * 60) - 30
        cmd.price_history[f"{item_id}:{reference}"].append((baseline_ts, baseline_price))

    def _fresh_volume_timestamp(self, minutes_ago=5, format_style="epoch"):
        volume_timestamp = timezone.now() - timedelta(minutes=minutes_ago)
        if format_style == "iso":
            return volume_timestamp.isoformat()
        if format_style == "epoch":
            return str(int(volume_timestamp.timestamp()))
        if format_style == "datetime":
            return volume_timestamp
        raise ValueError(f"Unsupported format_style: {format_style}")

    def _create_volume(self, item_id, volume, minutes_ago=5, format_style="epoch"):
        return HourlyItemVolume.objects.create(
            item_id=int(item_id),
            item_name=self.ITEM_MAPPING[str(item_id)],
            volume=volume,
            timestamp=self._fresh_volume_timestamp(minutes_ago=minutes_ago, format_style=format_style),
        )

    def _build_prices(self, price_map):
        all_prices = {}
        for item_id, current_high in price_map.items():
            all_prices[str(item_id)] = {
                "high": current_high,
                "low": max(1, current_high - 200),
            }
        return all_prices

    def _build_spike_price(self, baseline_price, percent_change):
        return int(round(baseline_price * (1 + (percent_change / 100.0))))

    def _record_case(self, name, goal, tested, how, setup, assumptions, expected, observed, cmd, notes=None):
        REPORT_CASES.append({
            "name": name,
            "goal": goal,
            "tested": tested,
            "how": how,
            "setup": setup,
            "assumptions": assumptions,
            "expected": expected,
            "observed": observed,
            "output": [line for line in cmd.stdout.getvalue().splitlines() if line.strip()],
            "notes": notes,
        })
        _write_report()

    def _summarize_single_trigger(self, result, alert):
        payload = json.loads(alert.triggered_data) if alert.triggered_data else {}
        return {
            "result": result,
            "triggered_data": payload,
        }

    def _summarize_list_trigger(self, result, alert):
        payload = json.loads(alert.triggered_data) if alert.triggered_data else []
        return {
            "result_count": len(result) if isinstance(result, list) else 0,
            "triggered_ids": [item["item_id"] for item in result] if isinstance(result, list) else [],
            "triggered_data": payload,
        }

    def test_single_item_triggers_when_volume_is_above_minimum(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Above Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 5_000_000, minutes_ago=5, format_style="epoch")
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_above_minimum",
            goal="A single spike alert should trigger when volume is comfortably above the minimum.",
            tested="single-item spike volume gating",
            how="Seed warm price history, provide a 20% spike, and attach a fresh high-volume snapshot.",
            setup="Single-item spike alert watching item 100 with min_volume=1,000,000 and a fresh 5,000,000 GP volume row.",
            assumptions="Hourly volume is stored as a recent Unix epoch string and the warmup window has already elapsed.",
            expected="The alert should return True and persist a triggered_data payload.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertTrue(result)
        self.assertEqual(observed["triggered_data"]["baseline"], self.BASELINES["100"])
        self.assertEqual(observed["triggered_data"]["reference"], "high")

    def test_single_item_blocks_when_volume_is_below_minimum(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Below Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 500_000, minutes_ago=5, format_style="epoch")
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_below_minimum",
            goal="A single spike alert should stay silent when hourly volume falls below the minimum.",
            tested="single-item spike below-threshold volume",
            how="Use the same price spike as the happy path, but give the item only 500,000 GP of hourly volume.",
            setup="Single-item spike alert watching item 100 with a fresh low-volume snapshot.",
            assumptions="The volume filter must be checked after the price spike threshold is met.",
            expected="The alert should return False because volume is under the configured floor.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_single_item_blocks_when_volume_snapshot_is_missing(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Missing Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_missing_volume",
            goal="A single spike alert should not trigger when no hourly volume row exists.",
            tested="single-item spike missing-volume handling",
            how="Provide a valid spike and baseline, but skip creating any HourlyItemVolume row.",
            setup="Single-item spike alert watching item 100 with no volume snapshot at all.",
            assumptions="Missing volume should be treated as unsafe and block the trigger.",
            expected="The alert should return False because the item has no volume data.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_single_item_blocks_when_volume_snapshot_is_stale(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Stale Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 5_000_000, minutes_ago=131, format_style="iso")
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_stale_volume",
            goal="A single spike alert should reject stale hourly volume rows.",
            tested="single-item spike stale-volume rejection",
            how="Store a strong spike and baseline, but make the volume snapshot older than the 130-minute freshness window.",
            setup="Single-item spike alert watching item 100 with a 131-minute-old ISO volume timestamp.",
            assumptions="Hourly volume rows older than the freshness window should behave like missing data.",
            expected="The alert should return False because the volume snapshot is stale.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_single_item_triggers_at_exact_minimum_volume(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Exact Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", self.MIN_VOLUME, minutes_ago=5, format_style="epoch")
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_exact_minimum",
            goal="A single spike alert should trigger when volume matches the minimum exactly.",
            tested="single-item spike exact-threshold volume",
            how="Use the same 20% spike, but set hourly volume to exactly 1,000,000 GP.",
            setup="Single-item spike alert watching item 100 with a volume row equal to min_volume.",
            assumptions="The filter uses a strict less-than comparison, so equality should pass.",
            expected="The alert should return True because exact-threshold volume is allowed.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertTrue(result)
        self.assertEqual(observed["triggered_data"]["time_frame_minutes"], self.TIME_FRAME_MINUTES)

    def test_single_item_blocks_during_warmup_even_with_good_volume(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Single Warmup",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 5_000_000, minutes_ago=5, format_style="epoch")
        cmd = self._make_command()
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="single_item_warmup_blocks",
            goal="A single spike alert should not trigger until the warmup baseline exists.",
            tested="single-item spike warmup interaction",
            how="Deliberately skip price-history seeding, even though the item has fresh and high volume.",
            setup="Single-item spike alert watching item 100 with good volume but no old baseline price.",
            assumptions="Warmup must happen before volume checks can matter.",
            expected="The alert should return False because the rolling window is not warmed up.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_multi_item_returns_only_items_that_meet_minimum_volume(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Multi Mixed Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            item_ids=json.dumps([100, 200, 300]),
            is_active=True,
        )
        self._create_volume("100", 5_000_000)
        self._create_volume("200", 500_000)
        self._create_volume("300", 2_000_000)
        cmd = self._make_command()
        for item_id in ("100", "200", "300"):
            self._seed_baseline(cmd, item_id)
        all_prices = self._build_prices({
            "100": self._build_spike_price(self.BASELINES["100"], 20),
            "200": self._build_spike_price(self.BASELINES["200"], 20),
            "300": self._build_spike_price(self.BASELINES["300"], 20),
        })

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_list_trigger(result, alert)
        self._record_case(
            name="multi_item_mixed_volume",
            goal="A multi-item spike alert should keep high-volume items and filter low-volume ones.",
            tested="multi-item spike volume filtering",
            how="Trigger three watched items at once, but make one of them fall below the hourly volume floor.",
            setup="Multi-item spike alert watching items 100, 200, and 300 with one low-volume row.",
            assumptions="Every item meets the price spike threshold, so only volume should decide inclusion.",
            expected="The alert should return a list with the high-volume items only.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertIsInstance(result, list)
        self.assertEqual(set(observed["triggered_ids"]), {"100", "300"})
        self.assertEqual(len(result), 2)

    def test_multi_item_blocks_when_every_candidate_is_under_volume(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Multi All Low Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            item_ids=json.dumps([100, 200, 300]),
            is_active=True,
        )
        self._create_volume("100", 100_000)
        self._create_volume("200", 200_000)
        self._create_volume("300", 300_000)
        cmd = self._make_command()
        for item_id in ("100", "200", "300"):
            self._seed_baseline(cmd, item_id)
        all_prices = self._build_prices({
            "100": self._build_spike_price(self.BASELINES["100"], 20),
            "200": self._build_spike_price(self.BASELINES["200"], 20),
            "300": self._build_spike_price(self.BASELINES["300"], 20),
        })

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_list_trigger(result, alert)
        self._record_case(
            name="multi_item_all_low_volume",
            goal="A multi-item spike alert should return False when every spiking item is under volume.",
            tested="multi-item spike all-low-volume handling",
            how="Make every watched item spike hard, but keep all hourly volume rows below the minimum.",
            setup="Multi-item spike alert watching three items, all with low hourly volume.",
            assumptions="Items that spike but fail the volume filter must not appear in the match list.",
            expected="The alert should return False and should not invent any triggered items.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_all_items_returns_only_high_volume_items(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="All Items Mixed Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            is_all_items=True,
            is_active=True,
        )
        self._create_volume("100", 5_000_000)
        self._create_volume("200", 500_000)
        self._create_volume("400", 2_000_000)
        cmd = self._make_command()
        for item_id in ("100", "200", "300", "400"):
            self._seed_baseline(cmd, item_id)
        all_prices = self._build_prices({
            "100": self._build_spike_price(self.BASELINES["100"], 20),
            "200": self._build_spike_price(self.BASELINES["200"], 20),
            "300": self._build_spike_price(self.BASELINES["300"], 20),
            "400": self._build_spike_price(self.BASELINES["400"], 20),
        })

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_list_trigger(result, alert)
        self._record_case(
            name="all_items_mixed_volume",
            goal="An all-items spike alert should include only the items that meet the volume floor.",
            tested="all-items spike volume filtering",
            how="Evaluate four spiking items, then let the hourly volume filter trim the low-volume ones.",
            setup="All-items spike alert with a mix of high-volume, low-volume, and missing-volume candidates.",
            assumptions="The list should include only items that both spike and meet min_volume.",
            expected="The alert should return a list containing the high-volume items only.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertIsInstance(result, list)
        self.assertEqual(set(observed["triggered_ids"]), {"100", "400"})
        self.assertEqual(len(result), 2)

    def test_all_items_blocks_when_every_candidate_is_under_volume(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="All Items Low Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            is_all_items=True,
            is_active=True,
        )
        self._create_volume("100", 100_000)
        self._create_volume("200", 200_000)
        self._create_volume("300", 300_000)
        cmd = self._make_command()
        for item_id in ("100", "200", "300"):
            self._seed_baseline(cmd, item_id)
        all_prices = self._build_prices({
            "100": self._build_spike_price(self.BASELINES["100"], 20),
            "200": self._build_spike_price(self.BASELINES["200"], 20),
            "300": self._build_spike_price(self.BASELINES["300"], 20),
        })

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_list_trigger(result, alert)
        self._record_case(
            name="all_items_all_low_volume",
            goal="An all-items spike alert should return False when nothing clears the volume filter.",
            tested="all-items spike all-low-volume handling",
            how="Make every candidate spike, but keep every hourly volume row below the minimum.",
            setup="All-items spike alert with only low-volume spiking items.",
            assumptions="The alert should not emit an empty list as if it were a hit.",
            expected="The alert should return False because no item satisfies the volume restriction.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_spike_requires_min_volume_to_be_configured(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Spike Needs Min Volume",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=None,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 5_000_000)
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="spike_requires_min_volume",
            goal="Spike alerts should reject configurations that do not define min_volume.",
            tested="spike alert configuration validation",
            how="Build an otherwise valid spike alert, but leave min_volume unset.",
            setup="Single-item spike alert watching item 100 with a fresh volume row but no minimum volume field.",
            assumptions="The command validates min_volume before it does any real work.",
            expected="The alert should return False because min_volume is required.",
            observed=_render_result(observed),
            cmd=cmd,
        )
        self.assertFalse(result)

    def test_newest_fresh_volume_snapshot_wins_over_older_higher_snapshot(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_name="Fresh Volume Wins",
            type="spike",
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction="both",
            reference="high",
            item_id=100,
            item_name=self.ITEM_MAPPING["100"],
            is_active=True,
        )
        self._create_volume("100", 5_000_000, minutes_ago=180, format_style="iso")
        self._create_volume("100", 500_000, minutes_ago=5, format_style="epoch")
        cmd = self._make_command()
        self._seed_baseline(cmd, "100")
        all_prices = self._build_prices({"100": self._build_spike_price(self.BASELINES["100"], 20)})

        result = cmd.check_alert(alert, all_prices)
        observed = self._summarize_single_trigger(result, alert)
        self._record_case(
            name="fresh_volume_overrides_old_snapshot",
            goal="The command should prefer the freshest parseable volume snapshot, even if an older row is larger.",
            tested="volume recency and row ordering edge case",
            how="Write a stale high-volume row first, then a newer low-volume row and verify the newer row wins.",
            setup="Single-item spike alert with two volume rows for the same item.",
            assumptions="The freshness filter should reject stale volume, not just sort by timestamp text.",
            expected="The alert should return False because the freshest usable snapshot is below the volume floor.",
            observed=_render_result(observed),
            cmd=cmd,
            notes="This is the most important regression guard for the volume-recency fix.",
        )
        self.assertFalse(result)


