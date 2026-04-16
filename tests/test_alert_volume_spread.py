"""
Spread alert volume coverage.

What:
    Verifies that spread alerts obey hourly volume restrictions in all supported
    modes: single-item, multi-item, and all-items.

Why:
    The spread checker is the alert type most likely to surface low-volume false
    positives. These tests lock down the expected hourly GP volume behavior so
    future changes do not quietly reintroduce stale, missing, or under-threshold
    items.

How:
    Build small Alert and HourlyItemVolume fixtures, call
    Website.management.commands.check_alerts.Command.check_alert(), and assert
    the spread logic respects minimum-volume thresholds as well as the
    "min_volume disabled" edge cases.
"""

import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


ITEM_A = {'id': 4151, 'name': 'Abyssal whip'}
ITEM_B = {'id': 11802, 'name': 'Dragon crossbow'}
ITEM_C = {'id': 11235, 'name': 'Dragon chainbody'}

REPORT_PATH = Path(__file__).resolve().parents[1] / 'test_output' / 'alert_volume_spread.md'
_REPORT_INITIALIZED = False


class SpreadVolumeReportMixin:
    """
    Write a markdown summary whenever this suite runs.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        global _REPORT_INITIALIZED
        if not _REPORT_INITIALIZED:
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(
                '# Alert Spread Volume Tests\n\n'
                'This file is rewritten whenever `tests.test_alert_volume_spread` runs.\n\n'
                '## Scope\n'
                '- Single-item spread alerts\n'
                '- Multi-item spread alerts\n'
                '- All-items spread alerts\n'
                '- Fresh, stale, missing, and optional volume behavior\n\n'
                '## Assumptions\n'
                '- Hourly volume means GP volume, not item count.\n'
                '- `min_volume=None` and `min_volume=0` both behave as disabled volume gates in the current checker.\n\n',
                encoding='utf-8',
            )
            _REPORT_INITIALIZED = True

    @classmethod
    def tearDownClass(cls):
        if cls.__name__ != 'SpreadVolumeBase':
            with REPORT_PATH.open('a', encoding='utf-8') as handle:
                handle.write(f'## {cls.__name__}\n')
                handle.write(
                    f'- Generated: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
                )
                handle.write('- Covered tests:\n')
                for test_name in sorted(name for name in dir(cls) if name.startswith('test_')):
                    handle.write(f'  - `{test_name}`\n')
                handle.write('\n')
        super().tearDownClass()


class SpreadVolumeBase(SpreadVolumeReportMixin, TestCase):
    """
    Shared fixtures for spread-volume tests.
    """

    spread_threshold = 6.0
    min_volume_threshold = 10_000_000
    base_timestamp = timezone.now()

    def setUp(self):
        self.user = User.objects.create_user(
            username=f'spread-volume-{self.__class__.__name__.lower()}',
            email=f'{self.__class__.__name__.lower()}@example.com',
            password='testpass123',
        )
        self.command = Command()

    def _log(self, message):
        print(f'[{self.__class__.__name__}.{self._testMethodName}] {message}')

    def _ts(self, minutes_ago=0):
        moment = self.base_timestamp - timedelta(minutes=minutes_ago)
        return str(int(moment.timestamp()))

    def _volume(self, item, volume, minutes_ago=0):
        return HourlyItemVolume.objects.create(
            item_id=item['id'],
            item_name=item['name'],
            volume=volume,
            timestamp=self._ts(minutes_ago),
        )

    def _spread_alert(self, **overrides):
        defaults = {
            'user': self.user,
            'alert_name': 'Spread Volume Test',
            'type': 'spread',
            'percentage': self.spread_threshold,
            'minimum_price': 1,
            'maximum_price': 100_000_000,
            'min_volume': self.min_volume_threshold,
            'is_active': True,
        }
        defaults.update(overrides)
        return Alert.objects.create(**defaults)

    def _all_prices(self, *rows):
        return {
            str(item_id): {
                'high': high,
                'low': low,
            }
            for item_id, high, low in rows
        }

    def _assert_list_has_item_ids(self, result, expected_ids):
        self.assertIsInstance(result, list)
        self.assertEqual({entry['item_id'] for entry in result}, set(expected_ids))


class SpreadVolumeCoreTests(SpreadVolumeBase):
    def test_single_item_triggers_when_spread_and_volume_pass(self):
        self._log('goal: single-item spread should trigger when both spread and volume pass')
        self._log('setup: one item with 10% spread and fresh hourly volume above threshold')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        self._volume(ITEM_A, volume=self.min_volume_threshold + 1)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: True, observed: {result}')
        self.assertTrue(result)

    def test_single_item_does_not_trigger_when_spread_is_below_threshold(self):
        self._log('goal: spread must meet the configured percentage threshold')
        self._log('setup: one item with 5% spread and volume far above threshold')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        self._volume(ITEM_A, volume=self.min_volume_threshold + 5_000_000)
        prices = self._all_prices((ITEM_A['id'], 105, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: False, observed: {result}')
        self.assertFalse(result)

    def test_single_item_does_not_trigger_when_volume_is_below_threshold(self):
        self._log('goal: low hourly volume must block an otherwise valid spread')
        self._log('setup: one item with 10% spread and volume just below threshold')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        self._volume(ITEM_A, volume=self.min_volume_threshold - 1)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: False, observed: {result}')
        self.assertFalse(result)

    def test_single_item_exact_min_volume_still_triggers(self):
        self._log('goal: min_volume should be inclusive, not strict-greater-than')
        self._log('setup: one item with 10% spread and volume exactly at threshold')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        self._volume(ITEM_A, volume=self.min_volume_threshold)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: True, observed: {result}')
        self.assertTrue(result)

    def test_single_item_without_min_volume_ignores_volume_gate(self):
        self._log('goal: optional min_volume should disable the volume gate when omitted')
        self._log('setup: one item with tiny volume and no min_volume configured')
        alert = self._spread_alert(item_id=ITEM_A['id'], min_volume=None)
        self._volume(ITEM_A, volume=1)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: True, observed: {result}')
        self.assertTrue(result)


class SpreadVolumeEdgeTests(SpreadVolumeBase):
    def test_zero_min_volume_behaves_like_disabled_gate(self):
        self._log('goal: a zero volume threshold should behave like a disabled gate under current logic')
        self._log('setup: one item with tiny volume and min_volume set to 0')
        alert = self._spread_alert(item_id=ITEM_A['id'], min_volume=0)
        self._volume(ITEM_A, volume=1)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: True, observed: {result}')
        self.assertTrue(result)

    def test_multi_item_returns_only_volume_qualified_items(self):
        self._log('goal: multi-item spread alerts must drop low-volume items individually')
        self._log('setup: two items match spread, only one meets the hourly volume threshold')
        alert = self._spread_alert(
            item_ids=json.dumps([ITEM_A['id'], ITEM_B['id']]),
        )
        self._volume(ITEM_A, volume=self.min_volume_threshold + 500_000)
        self._volume(ITEM_B, volume=self.min_volume_threshold - 1)
        prices = self._all_prices(
            (ITEM_A['id'], 110, 100),
            (ITEM_B['id'], 112, 100),
        )

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: one matching item, observed: {result}')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['item_id'], str(ITEM_A['id']))
        self.assertEqual(result[0]['volume'], self.min_volume_threshold + 500_000)

    def test_multi_item_returns_false_when_every_match_is_under_volume_threshold(self):
        self._log('goal: if every multi-item candidate is under volume, the alert should not trigger')
        self._log('setup: two spread matches, both below the hourly volume threshold')
        alert = self._spread_alert(
            item_ids=json.dumps([ITEM_A['id'], ITEM_B['id']]),
        )
        self._volume(ITEM_A, volume=self.min_volume_threshold - 1)
        self._volume(ITEM_B, volume=self.min_volume_threshold - 100)
        prices = self._all_prices(
            (ITEM_A['id'], 110, 100),
            (ITEM_B['id'], 112, 100),
        )

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: False, observed: {result}')
        self.assertFalse(result)

    def test_all_items_payload_includes_volume_for_each_match(self):
        self._log('goal: all-items spread results should carry the qualifying hourly volume in payloads')
        self._log('setup: two qualifying items, both with fresh volume above threshold')
        alert = self._spread_alert(is_all_items=True)
        self._volume(ITEM_A, volume=self.min_volume_threshold + 111)
        self._volume(ITEM_B, volume=self.min_volume_threshold + 222)
        prices = self._all_prices(
            (ITEM_A['id'], 110, 100),
            (ITEM_B['id'], 112, 100),
            (ITEM_C['id'], 101, 100),
        )

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: list with volume field on each entry, observed: {result}')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertTrue(all('volume' in entry for entry in result))
        self.assertEqual(
            {entry['volume'] for entry in result},
            {self.min_volume_threshold + 111, self.min_volume_threshold + 222},
        )

    def test_all_items_without_min_volume_keeps_low_volume_items(self):
        self._log('goal: when min_volume is omitted, all-items spread should not filter by volume')
        self._log('setup: two spread matches, one with tiny volume and one with no volume row at all')
        alert = self._spread_alert(is_all_items=True, min_volume=None)
        self._volume(ITEM_A, volume=1)
        prices = self._all_prices(
            (ITEM_A['id'], 110, 100),
            (ITEM_B['id'], 112, 100),
        )

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: both items returned, observed: {result}')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual({entry['volume'] for entry in result}, {None})

    def test_stale_volume_is_rejected(self):
        self._log('goal: stale volume must be treated as missing volume')
        self._log('setup: one item with a fresh spread but a stale hourly volume row')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        self._volume(ITEM_A, volume=self.min_volume_threshold + 1, minutes_ago=240)
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: False, observed: {result}')
        self.assertFalse(result)

    def test_missing_volume_is_rejected(self):
        self._log('goal: items without any hourly volume row must not trigger when min_volume is set')
        self._log('setup: one item with a valid spread but no HourlyItemVolume record')
        alert = self._spread_alert(item_id=ITEM_A['id'])
        prices = self._all_prices((ITEM_A['id'], 110, 100))

        result = self.command.check_alert(alert, prices)

        self._log(f'expected: False, observed: {result}')
        self.assertFalse(result)

