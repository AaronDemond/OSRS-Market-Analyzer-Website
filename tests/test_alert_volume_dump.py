"""
Dump alert volume restriction tests.

What:
    A dedicated 11-test suite focused on the dump alert's volume gates.
    The suite covers dump_liquidity_floor, relative volume minimum, missing
    volume, stale volume, single-item, multi-item, all-items, and a handful
    of boundary cases.

Why:
    Dump alerts should only fire on items that are sufficiently liquid and
    whose current 5-minute bucket volume is strong enough relative to the
    rolling expectation. These tests make those rules explicit and easy to
    regress-test.

How:
    1. Build a small synthetic market with a few dumping items plus some
       stable background items.
    2. Run the dump checker in the normal two-step pattern:
       call 1 initializes state, call 2 evaluates the dump.
    3. Vary only the hourly volume inputs and dump volume thresholds.
    4. Rewrite a markdown report in test_output/ after the suite finishes.

Notes:
    - No application code is modified by this file.
    - The suite is intentionally verbose on stdout so failures are easier to
      reason about from the terminal alone.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, FiveMinTimeSeries, HourlyItemVolume


REPORT_PATH = Path(__file__).resolve().parents[1] / 'test_output' / 'alert_volume_dump.md'
BACKGROUND_ITEM_IDS = list(range(90101, 90121))

ITEM_A_ID = 4151
ITEM_B_ID = 11802
ITEM_C_ID = 13576
ITEM_D_ID = 11832

ITEM_MAPPING = {
    str(ITEM_A_ID): 'Abyssal whip',
    str(ITEM_B_ID): 'Dragon crossbow',
    str(ITEM_C_ID): 'Dragon warhammer',
    str(ITEM_D_ID): 'Bandos chestplate',
}
ITEM_MAPPING.update({str(item_id): f'Background {item_id}' for item_id in BACKGROUND_ITEM_IDS})

DEFAULT_DUMP_BUCKET_HIGH = 950
DEFAULT_DUMP_BUCKET_LOW = 880
DEFAULT_DUMP_HIGH_VOL = 30
DEFAULT_DUMP_LOW_VOL = 170
DEFAULT_NORMAL_PRICE = 1000
DEFAULT_DUMP_PRICE = 900


def _epoch_string(minutes_ago):
    return str(int((timezone.now() - timedelta(minutes=minutes_ago)).timestamp()))


def _make_command():
    cmd = Command()
    cmd.stdout = StringIO()
    cmd.price_history = defaultdict(list)
    cmd.sustained_state = {}
    cmd.dump_market_state = {'last_mids': {}, 'market_drift': 0.0}
    cmd.get_item_mapping = lambda: ITEM_MAPPING
    return cmd


class DumpVolumeRestrictionTests(TestCase):
    """
    Focused coverage for dump-alert volume restrictions.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._suite_cases = []
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            "# Dump Alert Volume Test Report\n\n"
            "This file is rewritten by the dump-volume test suite each time it runs.\n",
            encoding='utf-8',
        )

    @classmethod
    def tearDownClass(cls):
        cls._write_report()
        super().tearDownClass()

    @classmethod
    def _write_report(cls):
        lines = []
        now = timezone.localtime(timezone.now())
        lines.append("# Dump Alert Volume Test Report")
        lines.append("")
        lines.append(f"Generated: {now:%Y-%m-%d %H:%M:%S %Z}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        if not cls._suite_cases:
            lines.append("No tests recorded.")
        else:
            lines.append("| Test | Result | Focus |")
            lines.append("| --- | --- | --- |")
            for case in cls._suite_cases:
                lines.append(f"| `{case['name']}` | {case['status']} | {case['goal']} |")
        lines.append("")
        lines.append("## Cases")
        lines.append("")
        for case in cls._suite_cases:
            lines.append(f"### {case['name']}")
            lines.append("")
            lines.append(f"- Goal: {case['goal']}")
            lines.append(f"- Scope: {case['scope']}")
            lines.append(f"- Setup: {case['setup']}")
            lines.append(f"- Assumptions: {case['assumptions']}")
            lines.append("- Output:")
            if case['output']:
                for line in case['output']:
                    lines.append(f"  - {line}")
            else:
                lines.append("  - (no output captured)")
            lines.append(f"- Expected: {case['expected']}")
            lines.append(f"- Actual: {case['actual']}")
            lines.append(f"- Result: {case['status']}")
            if case.get('failure'):
                lines.append(f"- Failure detail: {case['failure']}")
            lines.append("")

        REPORT_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding='utf-8')

    def setUp(self):
        self.user = User.objects.create_user(
            username=f'dump_volume_{self._testMethodName}',
            password='testpass',
        )
        self._log_lines = []

    def _log(self, message):
        print(message)
        self._log_lines.append(message)

    def _create_alert(self, **overrides):
        defaults = {
            'user': self.user,
            'alert_name': 'Dump Volume Test',
            'type': 'dump',
            'is_active': True,
            'is_triggered': False,
            'minimum_price': 1,
            'maximum_price': 1_000_000_000,
            'dump_discount_min': 0.5,
            'dump_shock_sigma': -0.5,
            'dump_sell_ratio_min': 0.40,
            'dump_rel_vol_min': 0.1,
            'dump_liquidity_floor': 100,
            'dump_cooldown': 0,
            'dump_confirmation_buckets': 1,
            'dump_consistency_required': False,
            'dump_fair_halflife': 120,
            'dump_vol_halflife': 360,
            'dump_var_halflife': 120,
        }
        defaults.update(overrides)
        return Alert.objects.create(**defaults)

    def _create_hourly_volume(self, item_id, volume_gp, minutes_ago=5):
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=ITEM_MAPPING.get(str(item_id), f'Item {item_id}'),
            volume=volume_gp,
            timestamp=_epoch_string(minutes_ago),
        )

    def _create_dump_bucket(self, item_id, high_vol=DEFAULT_DUMP_HIGH_VOL,
                            low_vol=DEFAULT_DUMP_LOW_VOL):
        return FiveMinTimeSeries.objects.create(
            item_id=item_id,
            item_name=ITEM_MAPPING.get(str(item_id), f'Item {item_id}'),
            avg_high_price=DEFAULT_DUMP_BUCKET_HIGH,
            avg_low_price=DEFAULT_DUMP_BUCKET_LOW,
            high_price_volume=high_vol,
            low_price_volume=low_vol,
            timestamp=_epoch_string(2),
        )

    def _add_background_market(self, prices_dict):
        for bg_id in BACKGROUND_ITEM_IDS:
            prices_dict[str(bg_id)] = {'high': 5000, 'low': 5000}
        return prices_dict

    def _build_fixture(self, volume_overrides=None, stale_volume_ids=None,
                       missing_volume_ids=None, bucket_overrides=None):
        volume_overrides = volume_overrides or {}
        stale_volume_ids = set(stale_volume_ids or set())
        missing_volume_ids = set(missing_volume_ids or set())
        bucket_overrides = bucket_overrides or {}

        tracked_ids = [ITEM_A_ID, ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]
        for item_id in tracked_ids:
            if item_id not in missing_volume_ids:
                volume_gp = volume_overrides.get(item_id, 20_000_000)
                minutes_ago = 180 if item_id in stale_volume_ids else 5
                self._create_hourly_volume(item_id, volume_gp, minutes_ago=minutes_ago)

            high_vol, low_vol = bucket_overrides.get(
                item_id, (DEFAULT_DUMP_HIGH_VOL, DEFAULT_DUMP_LOW_VOL)
            )
            self._create_dump_bucket(item_id, high_vol=high_vol, low_vol=low_vol)

        normal_prices = {str(item_id): {'high': DEFAULT_NORMAL_PRICE, 'low': DEFAULT_NORMAL_PRICE}
                         for item_id in tracked_ids}
        dumped_prices = {str(item_id): {'high': DEFAULT_DUMP_PRICE, 'low': DEFAULT_DUMP_PRICE}
                         for item_id in tracked_ids}

        self._add_background_market(normal_prices)
        self._add_background_market(dumped_prices)

        return normal_prices, dumped_prices

    def _run_two_cycle(self, alert, normal_prices, dumped_prices):
        cmd = _make_command()
        self._log(f"Running call 1 for alert #{alert.id} ({alert.alert_name})")
        first = cmd.check_dump_alert(alert, normal_prices)
        self._log(f"Call 1 result: {first!r}")
        self._log(f"Running call 2 for alert #{alert.id} ({alert.alert_name})")
        second = cmd.check_dump_alert(alert, dumped_prices)
        self._log(f"Call 2 result: {second!r}")
        return second

    def _extract_triggered_ids(self, result):
        if isinstance(result, list):
            return {row['item_id'] for row in result}
        return set()

    def _record_case(self, *, name, goal, scope, setup, assumptions, expected, actual, status, failure=None):
        self.__class__._suite_cases.append({
            'name': name,
            'goal': goal,
            'scope': scope,
            'setup': setup,
            'assumptions': assumptions,
            'expected': expected,
            'actual': actual,
            'status': status,
            'failure': failure,
            'output': list(self._log_lines),
        })

    def _assert_single_case(self, *, name, goal, setup, assumptions,
                            alert_kwargs, volume_overrides=None,
                            stale_volume_ids=None, missing_volume_ids=None,
                            bucket_overrides=None, expected):
        normal_prices, dumped_prices = self._build_fixture(
            volume_overrides=volume_overrides,
            stale_volume_ids=stale_volume_ids,
            missing_volume_ids=missing_volume_ids,
            bucket_overrides=bucket_overrides,
        )
        alert = self._create_alert(**alert_kwargs)
        self._log(f"Test: {name}")
        self._log(f"Goal: {goal}")
        self._log(f"Setup: {setup}")
        self._log(f"Assumptions: {assumptions}")
        self._log(f"Alert kwargs: {alert_kwargs}")
        try:
            result = self._run_two_cycle(alert, normal_prices, dumped_prices)
            actual = result
            self.assertIsInstance(actual, bool, 'Single-item dump alerts should return a boolean')
            self.assertEqual(actual, expected)
            status = 'PASS'
            failure = None
        except AssertionError as exc:
            actual = result if 'result' in locals() else None
            status = 'FAIL'
            failure = str(exc)
            self._record_case(
                name=name, goal=goal, scope='single',
                setup=setup, assumptions=assumptions,
                expected=expected, actual=actual,
                status=status, failure=failure,
            )
            raise
        self._record_case(
            name=name, goal=goal, scope='single',
            setup=setup, assumptions=assumptions,
            expected=expected, actual=actual,
            status=status, failure=failure,
        )

    def _assert_multi_case(self, *, name, goal, setup, assumptions,
                           alert_kwargs, volume_overrides=None,
                           stale_volume_ids=None, missing_volume_ids=None,
                           bucket_overrides=None, expected_ids=None):
        normal_prices, dumped_prices = self._build_fixture(
            volume_overrides=volume_overrides,
            stale_volume_ids=stale_volume_ids,
            missing_volume_ids=missing_volume_ids,
            bucket_overrides=bucket_overrides,
        )
        alert = self._create_alert(**alert_kwargs)
        self._log(f"Test: {name}")
        self._log(f"Goal: {goal}")
        self._log(f"Setup: {setup}")
        self._log(f"Assumptions: {assumptions}")
        self._log(f"Alert kwargs: {alert_kwargs}")
        try:
            result = self._run_two_cycle(alert, normal_prices, dumped_prices)
            actual = self._extract_triggered_ids(result)
            self.assertEqual(actual, expected_ids)
            status = 'PASS'
            failure = None
        except AssertionError as exc:
            actual = self._extract_triggered_ids(result) if 'result' in locals() else None
            status = 'FAIL'
            failure = str(exc)
            self._record_case(
                name=name, goal=goal, scope='multi/all',
                setup=setup, assumptions=assumptions,
                expected=sorted(expected_ids), actual=sorted(actual) if actual is not None else None,
                status=status, failure=failure,
            )
            raise
        self._record_case(
            name=name, goal=goal, scope='multi/all',
            setup=setup, assumptions=assumptions,
            expected=sorted(expected_ids), actual=sorted(actual),
            status=status, failure=failure,
        )

    def test_single_item_triggers_above_liquidity_floor(self):
        self._assert_single_case(
            name='single_item_triggers_above_liquidity_floor',
            goal='Confirm a dump alert still fires when hourly GP volume is comfortably above the liquidity floor.',
            setup='Item A has fresh 20M GP hourly volume and a clear dump bucket.',
            assumptions='All other dump thresholds are loose enough to let volume be the deciding factor.',
            alert_kwargs={
                'item_id': ITEM_A_ID,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_A_ID: 20_000_000},
            expected=True,
        )

    def test_multi_item_filters_low_volume_peer(self):
        self._assert_multi_case(
            name='multi_item_filters_low_volume_peer',
            goal='Confirm multi-item dump alerts keep the high-volume item and drop the low-volume peer.',
            setup='Item A has 20M GP hourly volume; Item B has 5M GP hourly volume.',
            assumptions='Both items otherwise satisfy dump conditions.',
            alert_kwargs={
                'item_ids': json.dumps([ITEM_A_ID, ITEM_B_ID]),
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_A_ID: 20_000_000, ITEM_B_ID: 5_000_000},
            expected_ids={str(ITEM_A_ID)},
        )

    def test_all_items_returns_only_high_volume_items(self):
        self._assert_multi_case(
            name='all_items_returns_only_high_volume_items',
            goal='Confirm all-items dump alerts only return items that clear the liquidity floor.',
            setup='Item A is liquid; Item B is under the floor; Item C has no volume row; Item D is stale.',
            assumptions='Only Item A should survive the hourly-volume gate.',
            alert_kwargs={
                'is_all_items': True,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_A_ID: 20_000_000, ITEM_B_ID: 5_000_000, ITEM_D_ID: 20_000_000},
            missing_volume_ids={ITEM_C_ID},
            stale_volume_ids={ITEM_D_ID},
            expected_ids={str(ITEM_A_ID)},
        )

    def test_single_item_triggers_with_loose_relative_volume_minimum(self):
        self._assert_single_case(
            name='single_item_triggers_with_loose_relative_volume_minimum',
            goal='Confirm a healthy item still triggers when relative volume is permissive.',
            setup='Item A has a current bucket volume that matches its expected EWMA volume.',
            assumptions='Relative volume is intentionally loose so the alert should pass.',
            alert_kwargs={
                'item_id': ITEM_A_ID,
                'dump_liquidity_floor': 1,
                'dump_rel_vol_min': 0.5,
            },
            volume_overrides={ITEM_A_ID: 20_000_000},
            expected=True,
        )

    def test_single_item_passes_when_volume_equals_floor(self):
        self._assert_single_case(
            name='single_item_passes_when_volume_equals_floor',
            goal='Confirm the liquidity gate is inclusive at the exact floor value.',
            setup='Item A volume is set to exactly 10,000,000 GP.',
            assumptions='Equality to the floor should be accepted, not rejected.',
            alert_kwargs={
                'item_id': ITEM_A_ID,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_A_ID: 10_000_000},
            expected=True,
        )

    def test_single_item_blocks_when_volume_below_floor(self):
        self._assert_single_case(
            name='single_item_blocks_when_volume_below_floor',
            goal='Confirm a single-item dump alert does not trigger when hourly volume is below the floor.',
            setup='Item B only has 5M GP hourly volume.',
            assumptions='A low-volume item should be filtered before dump math matters.',
            alert_kwargs={
                'item_id': ITEM_B_ID,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_B_ID: 5_000_000},
            expected=False,
        )

    def test_single_item_blocks_when_volume_missing(self):
        self._assert_single_case(
            name='single_item_blocks_when_volume_missing',
            goal='Confirm missing hourly volume data prevents a dump trigger.',
            setup='Item C has no HourlyItemVolume row at all.',
            assumptions='Missing data should behave like unavailable liquidity.',
            alert_kwargs={
                'item_id': ITEM_C_ID,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            missing_volume_ids={ITEM_C_ID},
            expected=False,
        )

    def test_single_item_blocks_when_volume_is_stale(self):
        self._assert_single_case(
            name='single_item_blocks_when_volume_is_stale',
            goal='Confirm stale hourly volume data is ignored by the dump checker.',
            setup='Item D has a large hourly volume row, but it is older than the freshness window.',
            assumptions='Stale volume should be treated as missing, not eligible.',
            alert_kwargs={
                'item_id': ITEM_D_ID,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_D_ID: 50_000_000},
            stale_volume_ids={ITEM_D_ID},
            expected=False,
        )

    def test_single_item_blocks_when_relative_volume_is_too_high(self):
        self._assert_single_case(
            name='single_item_blocks_when_relative_volume_is_too_high',
            goal='Confirm dump alerts reject items when the relative-volume minimum is not satisfied.',
            setup='Item A has a normal bucket volume ratio around 1.0, but the threshold is raised above that.',
            assumptions='This checks the relative volume gate rather than the liquidity floor.',
            alert_kwargs={
                'item_id': ITEM_A_ID,
                'dump_liquidity_floor': 1,
                'dump_rel_vol_min': 1.5,
            },
            volume_overrides={ITEM_A_ID: 20_000_000},
            expected=False,
        )

    def test_multi_item_blocks_when_every_candidate_lacks_volume(self):
        self._assert_multi_case(
            name='multi_item_blocks_when_every_candidate_lacks_volume',
            goal='Confirm a multi-item dump alert returns False when every selected item fails the hourly volume gate.',
            setup='Item B is below the floor, Item C is missing, and Item D is stale.',
            assumptions='The alert should not leak any item through when no candidate is liquid enough.',
            alert_kwargs={
                'item_ids': json.dumps([ITEM_B_ID, ITEM_C_ID, ITEM_D_ID]),
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_B_ID: 5_000_000, ITEM_D_ID: 30_000_000},
            stale_volume_ids={ITEM_D_ID},
            missing_volume_ids={ITEM_C_ID},
            expected_ids=set(),
        )

    def test_all_items_blocks_when_every_candidate_lacks_volume(self):
        self._assert_multi_case(
            name='all_items_blocks_when_every_candidate_lacks_volume',
            goal='Confirm all-items dump alerts return False when no item clears the liquidity floor.',
            setup='All four tracked items are either below the floor, missing, or stale.',
            assumptions='The all-items scan should end with no triggered rows.',
            alert_kwargs={
                'is_all_items': True,
                'dump_liquidity_floor': 10_000_000,
                'dump_rel_vol_min': 0.1,
            },
            volume_overrides={ITEM_A_ID: 5_000_000, ITEM_B_ID: 5_000_000, ITEM_D_ID: 5_000_000},
            stale_volume_ids={ITEM_D_ID},
            missing_volume_ids={ITEM_C_ID},
            expected_ids=set(),
        )


