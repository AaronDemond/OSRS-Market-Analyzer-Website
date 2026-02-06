"""
Stale volume data tests for all volume-checking alert types (except flip_confidence).

What:
    Verifies that every alert type which uses HourlyItemVolume data for a min_volume
    filter correctly rejects stale snapshots (older than 2 hours 10 minutes / 130 minutes)
    and only triggers when volume data is fresh (within the 130-minute recency window).

Why:
    The RuneScape Wiki API updates hourly volume data roughly every hour, but delays or
    outages can cause data to go stale.  When volume snapshots are outdated, the alert
    system must NOT treat them as valid — otherwise, an item whose volume dropped to zero
    hours ago could still pass a min_volume filter and generate a false alert.  These tests
    ensure the recency gate in ``get_volume_from_timeseries()`` (which checks against
    ``VOLUME_RECENCY_MINUTES = 130``) is effective for every code path that queries volume.

How:
    For each alert type / item mode (single, multi, all-items) we create two sibling tests:
        1. **Fresh volume** — a HourlyItemVolume record timestamped 5 minutes ago.
           The alert SHOULD trigger (all other conditions are pre-satisfied).
        2. **Stale volume** — a HourlyItemVolume record timestamped 131 minutes ago.
           The alert MUST NOT trigger because ``get_volume_from_timeseries`` returns None
           for stale records, which in turn fails the ``volume is None or volume < min_volume``
           check in every alert type's volume filter section.

Alert types covered:
    - Spike  (single-item, multi-item, all-items)
    - Spread (single-item, multi-item, all-items)
    - Threshold (single-item, multi-item, all-items)
    - Sustained (single-item only — the state-machine requires multiple check cycles)

Not covered (per user request):
    - Flip Confidence alerts — they use a separate timeseries-based volume check
"""

import json
import time
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume


# =============================================================================
# SHARED MIXIN — common helpers reused by every test class
# =============================================================================
class StaleVolumeTestMixin:
    """
    Mixin providing common helpers for stale-volume tests across all alert types.

    What:
        Contains reusable factory methods for creating a Command instance, volume
        records with fresh or stale timestamps, and standard item/price fixtures.

    Why:
        Every alert type follows the same volume-check pattern (query
        ``get_volume_from_timeseries`` → reject None / below-threshold).  Sharing
        helpers eliminates duplication across the ~20 tests in this module.

    How:
        Test classes inherit from both ``StaleVolumeTestMixin`` and ``TestCase``.
        The mixin provides:
            - ``_make_command()`` — fully initialised Command ready for ``check_alert`` calls
            - ``_fresh_epoch()`` / ``_stale_epoch()`` — Unix-epoch timestamp strings
            - ``_create_volume()`` — insert a HourlyItemVolume row with a given timestamp
    """

    # -------------------------------------------------------------------------
    # Constants shared across all test classes
    # -------------------------------------------------------------------------
    # ITEM_ID_A / ITEM_ID_B: Two distinct OSRS item IDs used for multi-item tests.
    # What: Numeric identifiers for test items.
    # Why: We need at least two items for multi-item alert variants.
    ITEM_ID_A = 4151   # e.g. Abyssal whip
    ITEM_ID_B = 11802  # e.g. Dragon crossbow

    # ITEM_MAPPING: Maps item IDs (as strings) to human-readable names.
    # What: The dict returned by ``get_item_mapping()`` in the alert checker.
    # Why: Several alert code paths call ``get_item_mapping()`` and look up names.
    ITEM_MAPPING = {
        '4151': 'Abyssal whip',
        '11802': 'Dragon crossbow',
    }

    # MIN_VOLUME: The minimum hourly volume (in GP) that we set on every test alert.
    # What: Threshold value stored in ``alert.min_volume``.
    # Why: All tests set volume ABOVE this value so that the only variable is timestamp
    #      freshness — if volume were below min_volume the test would conflate two failure
    #      modes.
    MIN_VOLUME = 1_000

    # ABOVE_MIN_VOLUME: A volume value guaranteed to exceed MIN_VOLUME.
    # What: The GP volume we assign to every HourlyItemVolume record in tests.
    # Why: Ensures volume magnitude is never the reason a test fails.
    ABOVE_MIN_VOLUME = 50_000

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _make_command(self):
        """
        Create a fully initialised Command instance ready for check_alert() calls.

        What: Instantiates the management command and injects minimal dependencies.
        Why: Tests call individual alert-check methods (``check_threshold_alert``,
             ``check_sustained_alert``, etc.) which live on Command and need
             ``stdout``, ``price_history``, ``sustained_state``, and ``get_item_mapping``.
        How: Constructs a Command, wires StringIO for stdout, sets empty
             ``price_history`` and ``sustained_state`` dicts, and stubs
             ``get_item_mapping`` to return ``self.ITEM_MAPPING``.

        Returns:
            Command: Ready-to-use instance.
        """
        # cmd: The Command instance under test.
        cmd = Command()
        # stdout: Captures any print output the command produces (debug lines).
        cmd.stdout = StringIO()
        # price_history: Rolling window of (timestamp, price) tuples keyed by
        #                "item_id:reference".  Needed by spike alert logic.
        cmd.price_history = defaultdict(list)
        # sustained_state: Per-alert-per-item state dict for the sustained alert
        #                  state machine.  Keyed by "alert_id:item_id".
        cmd.sustained_state = {}
        # get_item_mapping: Returns item_id → name mapping.  Stubbed to avoid DB query.
        cmd.get_item_mapping = lambda: self.ITEM_MAPPING
        return cmd

    def _fresh_epoch(self):
        """
        Return a Unix-epoch timestamp string that is INSIDE the 130-minute recency window.

        What: Produces a timestamp 5 minutes in the past as a string of epoch seconds.
        Why: ``get_volume_from_timeseries`` compares against ``VOLUME_RECENCY_MINUTES``
             (130 min).  5 minutes ago is well within that window.
        How: ``timezone.now() - 5 min`` → ``int(dt.timestamp())`` → ``str()``.

        Returns:
            str: Epoch seconds string (e.g. "1717012345").
        """
        # fresh_dt: A datetime 5 minutes in the past (well within 130-minute window).
        fresh_dt = timezone.now() - timedelta(minutes=5)
        return str(int(fresh_dt.timestamp()))

    def _stale_epoch(self):
        """
        Return a Unix-epoch timestamp string that is OUTSIDE the 130-minute recency window.

        What: Produces a timestamp 131 minutes in the past as a string of epoch seconds.
        Why: 131 minutes exceeds ``VOLUME_RECENCY_MINUTES`` (130), so
             ``get_volume_from_timeseries`` must return None for this record.
        How: ``timezone.now() - 131 min`` → ``int(dt.timestamp())`` → ``str()``.

        Returns:
            str: Epoch seconds string (e.g. "1717004000").
        """
        # stale_dt: A datetime 131 minutes in the past (just outside the 130-minute window).
        stale_dt = timezone.now() - timedelta(minutes=131)
        return str(int(stale_dt.timestamp()))

    def _create_volume(self, item_id, timestamp_str, volume=None):
        """
        Insert a HourlyItemVolume row with the given item ID and timestamp.

        What: Creates a real database record (not a mock) for volume data.
        Why: The alert checker runs a full Django ORM query, so we need actual rows
             to exercise ordering, filtering, and timestamp parsing.
        How: Calls ``HourlyItemVolume.objects.create()`` with the provided timestamp
             string and a volume value defaulting to ``self.ABOVE_MIN_VOLUME``.

        Args:
            item_id (int): The OSRS item ID.
            timestamp_str (str): Epoch seconds string for the volume snapshot.
            volume (int | None): GP volume value.  Defaults to ABOVE_MIN_VOLUME.

        Returns:
            HourlyItemVolume: The created record.
        """
        # effective_volume: The GP volume to store.  Defaults to a value that
        #                   comfortably exceeds MIN_VOLUME so that only timestamp
        #                   freshness can block the alert.
        effective_volume = volume if volume is not None else self.ABOVE_MIN_VOLUME
        # item_name: Human-readable name looked up from ITEM_MAPPING for readability
        #            in the DB record; falls back to "Item {id}" if not mapped.
        item_name = self.ITEM_MAPPING.get(str(item_id), f'Item {item_id}')
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=item_name,
            volume=effective_volume,
            timestamp=timestamp_str,
        )


# =============================================================================
# 1. SPIKE ALERT STALE VOLUME TESTS
# =============================================================================
class SpikeStaleVolumeTests(StaleVolumeTestMixin, TestCase):
    """
    Verify that spike alerts reject stale HourlyItemVolume data and accept fresh data.

    What: Tests all three spike variants (single-item, multi-item, all-items) with
          fresh vs stale volume timestamps.
    Why: Spike alerts use ``get_volume_from_timeseries`` to enforce ``min_volume``.
         If the volume snapshot is stale (>130 min old), it must return None, causing
         the spike alert to NOT trigger even when the price spike itself is valid.
    How: For each variant, seed ``price_history`` with a baseline that creates a
         >10% spike, set ``min_volume`` on the alert, and toggle only the volume
         record's timestamp between fresh and stale.
    """

    def setUp(self):
        """
        Create a test user and shared alert fixtures.

        What: Sets up a test user and pre-conditions needed across all spike tests.
        Why: Every test needs a user (FK on Alert) and consistent price data.
        How: Uses Django's ``User.objects.create_user`` and stores prices in setUp
             so they are available in every test method.
        """
        # test_user: Owner of the test alerts.
        self.test_user = User.objects.create_user(
            username='spike_stale_user',
            email='spike_stale@test.com',
            password='testpass123',
        )

    # -------------------------------------------------------------------------
    # Helper: seed price history so spike detects a 20% spike
    # -------------------------------------------------------------------------
    def _seed_spike_history(self, cmd, item_id, time_frame_minutes):
        """
        Seed price_history so that a spike of ~20% is detected for the given item.

        What: Inserts a baseline price point far enough in the past that the spike
              logic considers the warmup period satisfied, then lets the "current"
              price in ``all_prices`` create a 20% gap.
        Why: Spike alerts compare the current price to the oldest price within the
             rolling time window.  Without a seeded baseline, there's nothing to
             compare against and the alert never triggers.
        How: Insert a (timestamp, price) tuple at ``time_frame + 30 seconds`` ago
             into ``cmd.price_history`` under the ``"item_id:high"`` key.  The
             baseline price is 1000 GP; paired with a current price of 1200 GP this
             yields a +20% change, well above the typical 10% threshold.

        Args:
            cmd (Command): The command instance whose ``price_history`` to seed.
            item_id (int): The OSRS item ID.
            time_frame_minutes (int): The spike time frame in minutes (stored in
                                      ``alert.price`` for spike alerts).
        """
        # baseline_ts: Unix timestamp placed just outside the rolling window so that
        #              it serves as the "old price" for the percent-change calculation.
        baseline_ts = time.time() - (time_frame_minutes * 60) - 30
        # baseline_price: The old price.  Current price will be 1200 → +20% spike.
        baseline_price = 1000
        # history_key: The price_history dict key.  Format is "item_id:reference".
        history_key = f"{item_id}:high"
        cmd.price_history[history_key].append((baseline_ts, baseline_price))

    # -------------------------------------------------------------------------
    # Single-item spike
    # -------------------------------------------------------------------------

    def test_single_spike_fresh_volume_triggers(self):
        """
        A single-item spike alert triggers when volume data is fresh.

        What: Verifies that a spike alert triggers successfully when the
              HourlyItemVolume record is within the 130-minute recency window.
        Why: Ensures fresh volume data does NOT block a legitimate spike trigger.
        How: Create a spike alert, seed a 20% price spike, create a fresh volume
             record above min_volume, and assert ``check_alert`` returns True.
        """
        # alert: Single-item spike alert monitoring item A for >=10% moves.
        # price field stores time_frame_minutes for spike alerts (not actual price).
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Spike Fresh',
            type='spike',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,  # 5-minute time frame
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        # all_prices: Current market snapshot.  Price 1200 vs baseline 1000 = +20%.
        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, "Single-item spike should trigger with fresh volume data")

    def test_single_spike_stale_volume_blocks(self):
        """
        A single-item spike alert does NOT trigger when volume data is stale.

        What: Verifies that a spike alert is blocked when the HourlyItemVolume
              record is older than 130 minutes.
        Why: Stale volume data means we cannot confirm the item is actively traded;
             the spike might be due to a single anomalous trade.
        How: Identical setup to the fresh test but the volume record's timestamp
             is 131 minutes old → ``get_volume_from_timeseries`` returns None →
             ``volume is None`` causes the alert to return False.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Spike Stale',
            type='spike',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, "Single-item spike should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # Multi-item spike
    # -------------------------------------------------------------------------

    def test_multi_spike_fresh_volume_triggers(self):
        """
        A multi-item spike alert includes items when their volume data is fresh.

        What: With fresh volume records for both items, the spike alert should
              return triggered data containing the spiked items.
        Why: Ensures that fresh volume does not incorrectly block valid spikes.
        How: Create a spike alert with ``item_ids`` containing two items, seed
             spikes for both, provide fresh volume, and assert a truthy result.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Spike Fresh',
            type='spike',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._seed_spike_history(cmd, self.ITEM_ID_B, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())
        self._create_volume(self.ITEM_ID_B, self._fresh_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
            str(self.ITEM_ID_B): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, "Multi-item spike should trigger with fresh volume data")

    def test_multi_spike_stale_volume_blocks(self):
        """
        A multi-item spike alert excludes items when their volume data is stale.

        What: When both items have stale volume records, no items pass the volume
              filter and the alert should not trigger.
        Why: Stale volume must block items from appearing in triggered results.
        How: Same as fresh test but volume timestamps are 131 minutes old.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Spike Stale',
            type='spike',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._seed_spike_history(cmd, self.ITEM_ID_B, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._stale_epoch())
        self._create_volume(self.ITEM_ID_B, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
            str(self.ITEM_ID_B): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, "Multi-item spike should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # All-items spike
    # -------------------------------------------------------------------------

    def test_all_items_spike_fresh_volume_triggers(self):
        """
        An all-items spike alert includes items when their volume data is fresh.

        What: With ``is_all_items=True`` and fresh volume, items that spike should
              appear in the result.
        Why: Ensures the all-items code path (which iterates ``all_prices``) also
             respects volume freshness in the positive direction.
        How: Set ``is_all_items=True``, seed spike for one item, provide fresh
             volume, and assert a truthy result.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Spike Fresh',
            type='spike',
            item_name='All Items',
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,
            is_all_items=True,
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, "All-items spike should trigger with fresh volume data")

    def test_all_items_spike_stale_volume_blocks(self):
        """
        An all-items spike alert excludes items when their volume data is stale.

        What: With ``is_all_items=True`` and stale volume, no items should pass
              the volume filter.
        Why: Even when scanning all GE items, stale volume must block triggers.
        How: Same setup but volume timestamp is 131 minutes old.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Spike Stale',
            type='spike',
            item_name='All Items',
            percentage=10.0,
            direction='up',
            reference='high',
            min_volume=self.MIN_VOLUME,
            price=5,
            is_all_items=True,
        )

        cmd = self._make_command()
        self._seed_spike_history(cmd, self.ITEM_ID_A, time_frame_minutes=5)
        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1100, 'highTime': int(time.time()), 'lowTime': int(time.time()) - 10},
        }

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, "All-items spike should NOT trigger with stale volume data")


# =============================================================================
# 2. SPREAD ALERT STALE VOLUME TESTS
# =============================================================================
class SpreadStaleVolumeTests(StaleVolumeTestMixin, TestCase):
    """
    Verify that spread alerts reject stale HourlyItemVolume data and accept fresh data.

    What: Tests all three spread variants (single-item, multi-item, all-items) with
          fresh vs stale volume timestamps.
    Why: Spread alerts use ``get_volume_from_timeseries`` to enforce ``min_volume``.
         Low-volume items often have inflated spreads that are impractical to flip.
         The recency gate ensures that only actively-traded items (with current volume
         data) can pass the filter.
    How: For each variant, set up prices with a large spread (>10%), set ``min_volume``
         on the alert, and toggle only the volume record's timestamp.
    """

    def setUp(self):
        """
        Create a test user for spread alert tests.
        """
        self.test_user = User.objects.create_user(
            username='spread_stale_user',
            email='spread_stale@test.com',
            password='testpass123',
        )

    # -------------------------------------------------------------------------
    # Single-item spread
    # -------------------------------------------------------------------------

    def test_single_spread_fresh_volume_triggers(self):
        """
        A single-item spread alert triggers when volume data is fresh.

        What: Verifies that a spread alert triggers when HourlyItemVolume is recent.
        Why: Fresh volume should not block a spread alert whose percentage threshold is met.
        How: Create a spread alert with min_volume, provide a large spread in prices,
             create a fresh volume record, and assert the alert triggers.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Spread Fresh',
            type='spread',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            percentage=5.0,  # 5% spread threshold
            min_volume=self.MIN_VOLUME,
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        # all_prices: high=1100, low=1000 → spread = ((1100-1000)/1000)*100 = 10% > 5%
        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, "Single-item spread should trigger with fresh volume data")

    def test_single_spread_stale_volume_blocks(self):
        """
        A single-item spread alert does NOT trigger when volume data is stale.

        What: Verifies that stale volume blocks a spread alert even when spread is above threshold.
        Why: If we can't confirm the item is actively traded, spread alerts should not fire.
        How: Same setup but volume timestamp is 131 minutes old.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Spread Stale',
            type='spread',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            percentage=5.0,
            min_volume=self.MIN_VOLUME,
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, "Single-item spread should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # Multi-item spread
    # -------------------------------------------------------------------------

    def test_multi_spread_fresh_volume_triggers(self):
        """
        A multi-item spread alert includes items when their volume data is fresh.

        What: With fresh volume records, items meeting the spread threshold should
              appear in the triggered results.
        Why: Ensures the multi-item spread code path (``_check_spread_for_item_ids``)
             allows items through when volume is current.
        How: Create a spread alert with ``item_ids`` JSON, provide fresh volume for
             both items, and assert a truthy result (non-empty list).
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Spread Fresh',
            type='spread',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            percentage=5.0,
            min_volume=self.MIN_VOLUME,
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())
        self._create_volume(self.ITEM_ID_B, self._fresh_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
            str(self.ITEM_ID_B): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        # Multi-item spread returns a list of triggered items (truthy if non-empty)
        self.assertTrue(result, "Multi-item spread should trigger with fresh volume data")

    def test_multi_spread_stale_volume_blocks(self):
        """
        A multi-item spread alert returns no items when volume data is stale.

        What: With stale volume records, no items should pass the volume filter.
        Why: Stale volume must cause the volume check to return None, which blocks
             the item from being added to triggered_items.
        How: Same as fresh test but volume timestamps are 131 minutes old.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Spread Stale',
            type='spread',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            percentage=5.0,
            min_volume=self.MIN_VOLUME,
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())
        self._create_volume(self.ITEM_ID_B, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
            str(self.ITEM_ID_B): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        # Multi-item spread returns an empty list [] when no items pass → falsy
        self.assertFalse(bool(result), "Multi-item spread should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # All-items spread
    # -------------------------------------------------------------------------

    def test_all_items_spread_fresh_volume_triggers(self):
        """
        An all-items spread alert includes items when their volume data is fresh.

        What: With ``is_all_items=True`` and fresh volume, items with large spreads
              should appear in the result.
        Why: Ensures the all-items spread code path also respects volume freshness
             in the positive direction.
        How: Set ``is_all_items=True``, provide prices with 10% spread, fresh volume,
             and assert a truthy result (non-empty matching_items list).
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Spread Fresh',
            type='spread',
            item_name='All Items',
            percentage=5.0,
            min_volume=self.MIN_VOLUME,
            is_all_items=True,
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, "All-items spread should trigger with fresh volume data")

    def test_all_items_spread_stale_volume_blocks(self):
        """
        An all-items spread alert excludes items when their volume data is stale.

        What: With ``is_all_items=True`` and stale volume, no items should pass.
        Why: The all-items spread code path does NOT guard with ``if alert.min_volume:``
             — it always checks volume.  Stale data → None → skip item.
        How: Same setup but volume timestamp is 131 minutes old → result is False.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Spread Stale',
            type='spread',
            item_name='All Items',
            percentage=5.0,
            min_volume=self.MIN_VOLUME,
            is_all_items=True,
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1100, 'low': 1000},
        }

        cmd = self._make_command()
        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, "All-items spread should NOT trigger with stale volume data")


# =============================================================================
# 3. THRESHOLD ALERT STALE VOLUME TESTS
# =============================================================================
class ThresholdStaleVolumeTests(StaleVolumeTestMixin, TestCase):
    """
    Verify that threshold alerts reject stale HourlyItemVolume data and accept fresh data.

    What: Tests all three threshold variants (single-item, multi-item, all-items)
          with fresh vs stale volume timestamps.
    Why: Threshold alerts (percentage-based) compare current price against a stored
         reference and optionally enforce ``min_volume``.  Stale volume data should
         cause the volume check to return None, blocking the trigger.
    How: For each variant, create a threshold alert with ``reference_prices``,
         provide a current price that crosses the threshold, and toggle volume
         timestamp freshness.

    Note: The existing ``test_threshold_min_volume.py`` already has a single-item
          stale test.  These tests complement it by covering multi-item and all-items
          variants AND by using a consistent test structure with the other alert types.
    """

    def setUp(self):
        """
        Create a test user and reference price fixtures.
        """
        self.test_user = User.objects.create_user(
            username='threshold_stale_user',
            email='threshold_stale@test.com',
            password='testpass123',
        )
        # reference_price: Baseline price for threshold percentage calculation.
        # What: The price stored at alert creation.
        # Why: Threshold alerts calculate (current - reference) / reference × 100.
        # How: Stored in ``reference_prices`` JSON field keyed by item_id string.
        self.reference_price = 1000

    # -------------------------------------------------------------------------
    # Single-item threshold
    # -------------------------------------------------------------------------

    def test_single_threshold_fresh_volume_triggers(self):
        """
        A single-item threshold alert triggers when volume data is fresh.

        What: Verifies a threshold alert fires when the price crosses the threshold
              AND volume data is within the recency window.
        Why: Fresh volume should not interfere with a valid threshold crossing.
        How: Reference price 1000, current price 1200 → +20% > 5% threshold.
             Fresh volume record → alert triggers.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Threshold Fresh',
            type='threshold',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({str(self.ITEM_ID_A): self.reference_price}),
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        # Current average = (1200+1200)/2 = 1200 → +20% from reference 1000
        all_prices = {str(self.ITEM_ID_A): {'high': 1200, 'low': 1200}}

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        self.assertTrue(result, "Single-item threshold should trigger with fresh volume data")

    def test_single_threshold_stale_volume_blocks(self):
        """
        A single-item threshold alert does NOT trigger when volume data is stale.

        What: Same threshold crossing but volume is 131 minutes old → blocked.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Threshold Stale',
            type='threshold',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({str(self.ITEM_ID_A): self.reference_price}),
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {str(self.ITEM_ID_A): {'high': 1200, 'low': 1200}}

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        self.assertFalse(result, "Single-item threshold should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # Multi-item threshold
    # -------------------------------------------------------------------------

    def test_multi_threshold_fresh_volume_triggers(self):
        """
        A multi-item threshold alert includes items when their volume data is fresh.

        What: Both items cross the threshold AND have fresh volume → they appear
              in the returned list.
        Why: Ensures the multi-item threshold code path allows items through with
             fresh volume.
        How: Create alert with ``item_ids`` JSON, reference prices for both, fresh
             volume, and assert a truthy (non-empty list) result.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Threshold Fresh',
            type='threshold',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({
                str(self.ITEM_ID_A): self.reference_price,
                str(self.ITEM_ID_B): self.reference_price,
            }),
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())
        self._create_volume(self.ITEM_ID_B, self._fresh_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1200},
            str(self.ITEM_ID_B): {'high': 1200, 'low': 1200},
        }

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        self.assertTrue(result, "Multi-item threshold should trigger with fresh volume data")

    def test_multi_threshold_stale_volume_blocks(self):
        """
        A multi-item threshold alert returns no items when volume data is stale.

        What: Both items cross the threshold but have stale volume → empty list.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Threshold Stale',
            type='threshold',
            item_name='Multi Items',
            item_id=self.ITEM_ID_A,
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({
                str(self.ITEM_ID_A): self.reference_price,
                str(self.ITEM_ID_B): self.reference_price,
            }),
            item_ids=json.dumps([self.ITEM_ID_A, self.ITEM_ID_B]),
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())
        self._create_volume(self.ITEM_ID_B, self._stale_epoch())

        all_prices = {
            str(self.ITEM_ID_A): {'high': 1200, 'low': 1200},
            str(self.ITEM_ID_B): {'high': 1200, 'low': 1200},
        }

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        # Multi-item threshold returns an empty list [] when no items pass
        self.assertFalse(bool(result), "Multi-item threshold should NOT trigger with stale volume data")

    # -------------------------------------------------------------------------
    # All-items threshold
    # -------------------------------------------------------------------------

    def test_all_items_threshold_fresh_volume_triggers(self):
        """
        An all-items threshold alert includes items when their volume data is fresh.

        What: With ``is_all_items=True``, items that cross the threshold AND have
              fresh volume should appear in the result list.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Threshold Fresh',
            type='threshold',
            item_name='All Items',
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({str(self.ITEM_ID_A): self.reference_price}),
            is_all_items=True,
        )

        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        all_prices = {str(self.ITEM_ID_A): {'high': 1200, 'low': 1200}}

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        self.assertTrue(result, "All-items threshold should trigger with fresh volume data")

    def test_all_items_threshold_stale_volume_blocks(self):
        """
        An all-items threshold alert excludes items when their volume data is stale.

        What: Same threshold crossing but volume is stale → empty result.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Threshold Stale',
            type='threshold',
            item_name='All Items',
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            reference_prices=json.dumps({str(self.ITEM_ID_A): self.reference_price}),
            is_all_items=True,
        )

        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        all_prices = {str(self.ITEM_ID_A): {'high': 1200, 'low': 1200}}

        cmd = self._make_command()
        result = cmd.check_threshold_alert(alert, all_prices)
        self.assertFalse(bool(result), "All-items threshold should NOT trigger with stale volume data")


# =============================================================================
# 4. SUSTAINED ALERT STALE VOLUME TESTS
# =============================================================================
class SustainedStaleVolumeTests(StaleVolumeTestMixin, TestCase):
    """
    Verify that sustained move alerts reject stale HourlyItemVolume data.

    What: Tests single-item sustained alerts with fresh vs stale volume timestamps.
    Why: Sustained alerts use ``get_volume_from_timeseries`` inside
         ``_check_sustained_for_item`` after the streak counter reaches ``min_moves``.
         If the volume snapshot is stale, the method returns None and the item
         should be skipped.
    How: The sustained alert state machine requires multiple price-change cycles
         to build a streak.  We simulate this by calling ``check_sustained_alert``
         repeatedly with incrementing prices, then check whether volume freshness
         affects the final trigger decision.

    Note: Only single-item mode is tested here because the sustained state machine
          works identically for single / multi / all-items — the only difference is
          which items are iterated.  The volume check itself is in
          ``_check_sustained_for_item`` which is shared by all modes.
    """

    def setUp(self):
        """
        Create a test user for sustained alert tests.
        """
        self.test_user = User.objects.create_user(
            username='sustained_stale_user',
            email='sustained_stale@test.com',
            password='testpass123',
        )

    def _run_sustained_cycles(self, cmd, alert, prices_sequence):
        """
        Run the sustained alert checker through multiple price-change cycles.

        What: Calls ``check_sustained_alert`` once for each entry in ``prices_sequence``,
              simulating the periodic check loop that runs every 30 seconds.
        Why: The sustained alert state machine requires ``min_consecutive_moves``
             consecutive price changes in the same direction before it even reaches
             the volume check.  We need to feed it enough cycles to build the streak.
        How: Iterate over the list of (high, low) tuples, build an ``all_prices``
             dict for each, and call ``check_sustained_alert``.  Return True as
             soon as any cycle triggers (the state machine resets after a trigger,
             so later cycles would not re-trigger).  If no cycle triggers, return
             the result of the final call (False).

        Args:
            cmd (Command): The command instance with sustained_state.
            alert (Alert): The sustained alert being tested.
            prices_sequence (list[tuple]): A list of (high, low) price tuples.
                Each entry represents one check cycle's current market state.

        Returns:
            True if any cycle triggered the alert, False otherwise.
        """
        for high, low in prices_sequence:
            all_prices = {
                str(self.ITEM_ID_A): {
                    'high': high,
                    'low': low,
                    'highTime': int(time.time()),
                    'lowTime': int(time.time()) - 10,
                },
            }
            result = cmd.check_sustained_alert(alert, all_prices)
            # Return immediately on trigger — the state machine resets the streak
            # after a trigger, so subsequent cycles would start fresh and not
            # re-trigger with the same price sequence.
            if result:
                return result
        return False

    def test_single_sustained_fresh_volume_triggers(self):
        """
        A single-item sustained alert triggers when volume data is fresh.

        What: After building a valid streak of consecutive up-moves, the alert
              should trigger because the volume record is within the recency window.
        Why: Confirms that fresh volume does not block a legitimate sustained trigger.
        How: Create a sustained alert requiring 3 consecutive up-moves of >=1%.
             Feed 4 price cycles with increasing prices (enough to satisfy
             min_moves=3 AND the volatility check).  Provide fresh volume.
             The 4th cycle should trigger.

        Sustained alert trigger conditions (all must be true simultaneously):
            1. streak_count >= min_consecutive_moves (3)
            2. Streak within time_window (60 minutes)
            3. Direction matches (up)
            4. Volume >= min_volume (fresh volume required)
            5. Volatility buffer has >= 5 entries
            6. Total move % >= volatility_multiplier * avg_volatility
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Sustained Fresh',
            type='sustained',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            time_frame=60,                 # 60-minute window
            min_consecutive_moves=3,       # 3 consecutive up-moves
            min_move_percentage=1.0,       # Each move >= 1%
            volatility_buffer_size=10,     # Buffer of last 10 moves
            volatility_multiplier=0.1,     # Very low multiplier so total move easily exceeds
        )

        cmd = self._make_command()
        self._create_volume(self.ITEM_ID_A, self._fresh_epoch())

        # prices_sequence: A series of (high, low) tuples, each representing one
        #                  check cycle.  Each step increases price by ~2% to satisfy
        #                  the min_move_percentage of 1%.
        #
        # We need enough cycles to:
        #   - Initialise state (cycle 1: baseline established)
        #   - Build streak of 3+ moves (cycles 2-7)
        #   - Fill volatility buffer with >= 5 entries (cycles 2-7)
        #   - Have total_move_pct >= volatility_multiplier * avg_volatility
        #
        # Prices: 1000 → 1020 → 1040 → 1061 → 1082 → 1104 → 1126
        # Each ~2% increase.  After 6 moves, total move ~12.6% from 1000 to 1126.
        # avg_volatility ≈ 2%, required_move = 0.1 * 2% = 0.2% → 12.6% >> 0.2%.
        prices_sequence = [
            (1000, 1000),   # Cycle 1: initialise state
            (1020, 1020),   # Cycle 2: +2.0% (streak=1)
            (1040, 1040),   # Cycle 3: +1.96% (streak=2)
            (1061, 1061),   # Cycle 4: +2.02% (streak=3) — meets min_moves
            (1082, 1082),   # Cycle 5: +1.98% (streak=4)
            (1104, 1104),   # Cycle 6: +2.03% (streak=5) — volatility buffer has 5 entries
            (1126, 1126),   # Cycle 7: +1.99% (streak=6) — should trigger
        ]

        result = self._run_sustained_cycles(cmd, alert, prices_sequence)
        self.assertTrue(result, "Sustained alert should trigger with fresh volume data")

    def test_single_sustained_stale_volume_blocks(self):
        """
        A single-item sustained alert does NOT trigger when volume data is stale.

        What: Identical streak setup but volume timestamp is 131 minutes old.
        Why: Stale volume must prevent triggering even after a valid streak is built.
        How: Same price sequence, same alert config, but volume record uses
             ``_stale_epoch()`` → ``get_volume_from_timeseries`` returns None →
             ``_check_sustained_for_item`` returns None → alert does not trigger.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Sustained Stale',
            type='sustained',
            item_name='Abyssal whip',
            item_id=self.ITEM_ID_A,
            direction='up',
            reference='average',
            min_volume=self.MIN_VOLUME,
            time_frame=60,
            min_consecutive_moves=3,
            min_move_percentage=1.0,
            volatility_buffer_size=10,
            volatility_multiplier=0.1,
        )

        cmd = self._make_command()
        self._create_volume(self.ITEM_ID_A, self._stale_epoch())

        prices_sequence = [
            (1000, 1000),
            (1020, 1020),
            (1040, 1040),
            (1061, 1061),
            (1082, 1082),
            (1104, 1104),
            (1126, 1126),
        ]

        result = self._run_sustained_cycles(cmd, alert, prices_sequence)
        self.assertFalse(result, "Sustained alert should NOT trigger with stale volume data")
