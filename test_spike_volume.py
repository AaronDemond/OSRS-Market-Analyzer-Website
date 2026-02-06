"""
Spike Alert Volume Filter Test Suite
=====================================

What: Comprehensive tests for spike alerts with minimum volume (min_volume) filtering.
Why: Spike alerts must respect the min_volume threshold to avoid triggering on low-activity
     items whose prices can fluctuate wildly without meaningful market activity. These tests
     verify that the volume filter works correctly across all three spike alert variants
     (single-item, multi-item, all-items), including the recent bug fix where
     all_within_threshold was incorrectly set AFTER the volume check in multi-item spikes.
How: Each test class creates real HourlyItemVolume records in the Django test database
     (no mocking of volume lookups), pre-populates the Command's price_history with
     baseline data old enough to pass warmup, then calls check_alert() directly and
     asserts the expected behavior.

Running all tests:
    python manage.py test test_spike_volume --verbosity=2

Running a specific test class:
    python manage.py test test_spike_volume.SingleItemSpikeVolumeTests --verbosity=2

Running a single test:
    python manage.py test test_spike_volume.SingleItemSpikeVolumeTests.test_volume_above_threshold_triggers --verbosity=2
"""

import json
import sys
import time
from datetime import timedelta
from collections import defaultdict
from io import StringIO

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from Website.models import Alert, HourlyItemVolume
from Website.management.commands.check_alerts import Command


# =============================================================================
# SHARED TEST HELPERS
# =============================================================================
# What: Reusable helper functions and a mixin for setting up spike alert tests
# Why: All spike alert test classes share the same pattern of creating a Command
#      instance, pre-populating price history, and creating volume records.
#      Extracting these into a mixin avoids code duplication across test classes.
# How: SpikeTestMixin provides methods for common setup tasks:
#      - _make_command(): Creates and configures a Command instance
#      - _seed_price_history(): Populates price_history with baseline data
#      - _create_volume_record(): Creates HourlyItemVolume rows in the test DB
# =============================================================================

class SpikeTestMixin:
    """
    Mixin providing shared helpers for spike alert test classes.

    What: Contains factory methods for creating Command instances, seeding
          price history with warm-up data, and inserting HourlyItemVolume rows.
    Why: Every spike alert test needs the same boilerplate: a Command with
         stdout captured, a price_history defaultdict, and an item_mapping.
         Centralising this logic keeps individual test methods focused on the
         scenario they are actually testing.
    How: Mixed into each TestCase subclass via multiple inheritance.
    """

    # ITEM_MAPPING: Shared mapping of item IDs to human-readable names used
    # across all test classes. Mirrors the format returned by get_item_mapping().
    ITEM_MAPPING = {
        '100': 'Dragon Bones',
        '200': 'Abyssal Whip',
        '300': 'Bandos Chestplate',
        '400': 'Armadyl Godsword',
        '500': 'Twisted Bow',
    }

    def _make_command(self):
        """
        Create a fully initialised Command instance ready for check_alert().

        What: Instantiates the check_alerts management command and wires up
              the internal state it would normally initialise in handle().
        Why: We call check_alert() directly (bypassing the infinite loop in
             handle()), so we must manually set up stdout, price_history, and
             get_item_mapping.
        How:
            1. Create Command()
            2. Replace stdout with a StringIO to capture output
            3. Initialise price_history as a defaultdict(list)
            4. Monkey-patch get_item_mapping to return our test mapping

        Returns:
            Command: A configured Command instance
        """
        # cmd: The management command instance that contains check_alert()
        cmd = Command()
        # Capture management command output so it doesn't pollute test runner
        cmd.stdout = StringIO()
        # price_history: Rolling window of (unix_timestamp, price) tuples per
        # "item_id:reference" key. Needs to be a defaultdict so new keys
        # automatically get an empty list.
        cmd.price_history = defaultdict(list)
        # Override get_item_mapping to avoid hitting the real API/file
        cmd.get_item_mapping = lambda: self.ITEM_MAPPING
        return cmd

    def _seed_price_history(self, cmd, item_id, reference, baseline_price,
                            time_frame_minutes):
        """
        Pre-populate price_history with a baseline data point old enough to
        pass the warmup check but young enough to survive cutoff pruning.

        What: Inserts a single (timestamp, price) tuple into cmd.price_history
              for the given item+reference combination, backdated to a precise
              position that satisfies two constraints:
              1. Old enough: must be older than warmup_threshold
                 (now - time_frame_minutes * 60) so the warmup check passes.
              2. Young enough: must be newer than cutoff
                 (now - time_frame_minutes * 60 - 60) so it is NOT pruned
                 when check_alert() filters the price_history window.
        Why: Spike alerts require price data from at least [time_frame_minutes]
             ago before they will evaluate. But check_alert() also prunes any
             data older than cutoff (time_frame + 60 seconds). If the baseline
             is placed too far in the past (e.g., 2× time_frame), it gets
             pruned before the warmup check can use it.
        How: Places the baseline at exactly (time_frame_minutes * 60 + 30)
             seconds in the past. This is:
             - 30 seconds older than warmup_threshold → passes warmup
             - 30 seconds younger than cutoff → survives pruning

        Args:
            cmd: Command instance whose price_history to populate
            item_id: Item ID (str or int) — will be converted to str for the key
            reference: Price reference type ('high', 'low', 'average')
            baseline_price: The baseline price value to store
            time_frame_minutes: The alert's time frame in minutes
        """
        # key: The price_history lookup key, e.g. "100:high"
        key = f"{item_id}:{reference}"
        # baseline_ts: Unix timestamp placed (time_frame + 30 seconds) in the past.
        # This is carefully positioned between two boundaries:
        #   - warmup_threshold = now - (time_frame * 60)        → baseline is 30s older ✓
        #   - cutoff           = now - (time_frame * 60) - 60   → baseline is 30s younger ✓
        # This ensures the data point passes warmup AND survives pruning.
        baseline_ts = time.time() - (time_frame_minutes * 60) - 30
        cmd.price_history[key].append((baseline_ts, baseline_price))

    def _create_volume_record(self, item_id, item_name, volume):
        """
        Insert a HourlyItemVolume row into the test database.

        What: Creates a volume snapshot record for a specific item.
        Why: The spike alert's volume filter queries HourlyItemVolume via
             get_volume_from_timeseries(). We create real DB rows instead of
             mocking so that the full query path is exercised, including the
             model's Meta.ordering by -timestamp.
        How: Uses HourlyItemVolume.objects.create() with a fixed timestamp
             string (the exact value doesn't matter for these tests because
             the alert checker only cares about the most recent row per item).

        Args:
            item_id: OSRS item ID (int)
            item_name: Human-readable item name for the DB record
            volume: Hourly volume in GP (gold pieces)

        Returns:
            HourlyItemVolume: The created database record
        """
        # volume_timestamp: Recent timestamp inside the 130-minute (2h10m) freshness window.
        # What: Represents the "current" hour snapshot time for the volume record.
        # Why: The alert checker now rejects stale volume snapshots, so tests must
        #      ensure timestamps are fresh enough to pass the recency filter.
        # How: Use timezone.now() minus a small buffer (5 minutes) to stay well
        #      inside the allowed freshness window.
        volume_timestamp = timezone.now() - timedelta(minutes=5)
        # volume_timestamp_epoch: Unix epoch seconds string matching production format.
        # What: Mirrors the RuneScape Wiki API timestamp that update_volumes.py stores.
        # Why: Ensures the Unix-timestamp parsing path is exercised in tests.
        # How: Convert the aware datetime to integer seconds and cast to string.
        volume_timestamp_epoch = str(int(volume_timestamp.timestamp()))
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=item_name,
            volume=volume,
            timestamp=volume_timestamp_epoch,
        )


# =============================================================================
# 1. SPIKE ALERT VALIDATION TESTS
# =============================================================================

class SpikeAlertValidationTests(SpikeTestMixin, TestCase):
    """
    Tests that spike alerts correctly reject invalid configurations.

    What: Verifies that check_alert() returns False immediately when required
          fields (percentage, price/time_frame, min_volume) are missing.
    Why: Invalid spike alerts should fail fast at the validation stage rather
         than proceeding to price history evaluation with incomplete config.
    How: Create Alert instances with one required field missing at a time,
         call check_alert(), and assert it returns False.
    """

    def setUp(self):
        """
        Create a test user that all alerts in this class will reference.

        What: Provides a User foreign key for Alert.user
        Why: The Alert model has a ForeignKey to User (nullable but still
             needed for realistic test data)
        How: Django's create_user helper with minimal required fields
        """
        # test_user: Shared user instance for all validation test alerts
        self.test_user = User.objects.create_user(
            username='validation_user',
            email='validation@example.com',
            password='testpass123',
        )

    def test_missing_percentage_returns_false(self):
        """
        Spike alert with percentage=None should return False immediately.

        What: Verifies the first validation gate (line 1870 in check_alerts.py)
        Why: Cannot calculate percent change without a threshold percentage
        How: Create alert with percentage=None, call check_alert, assert False
        """
        # alert: Spike alert missing the required percentage field
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Missing Percentage',
            type='spike',
            percentage=None,       # <-- missing
            price=60,              # time frame in minutes
            min_volume=1000,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_active=True,
        )

        cmd = self._make_command()
        # all_prices: Minimal price data — should never be reached
        all_prices = {'100': {'high': 5000, 'low': 4800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, 'Alert with percentage=None should return False')

    def test_missing_price_returns_false(self):
        """
        Spike alert with price=None (no time frame) should return False.

        What: Verifies the first validation gate checks for alert.price
        Why: Spike alerts store the time frame in the price field; without it,
             the rolling window size is undefined
        How: Create alert with price=None, call check_alert, assert False
        """
        # alert: Spike alert missing the price field (time frame)
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Missing Price',
            type='spike',
            percentage=10.0,
            price=None,            # <-- missing
            min_volume=1000,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_active=True,
        )

        cmd = self._make_command()
        all_prices = {'100': {'high': 5000, 'low': 4800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, 'Alert with price=None should return False')

    def test_missing_min_volume_returns_false(self):
        """
        Spike alert with min_volume=None should return False.

        What: Verifies the min_volume validation gate (line 1879)
        Why: Spike alerts REQUIRE a min_volume; None is treated as invalid
        How: Create alert with min_volume=None, call check_alert, assert False
        """
        # alert: Spike alert missing the required min_volume field
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Missing Min Volume',
            type='spike',
            percentage=10.0,
            price=60,
            min_volume=None,       # <-- missing
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_active=True,
        )

        cmd = self._make_command()
        all_prices = {'100': {'high': 5000, 'low': 4800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, 'Alert with min_volume=None should return False')

    def test_zero_time_frame_returns_false(self):
        """
        Spike alert with price=0 (zero-minute time frame) should return False.

        What: Verifies the time_frame_minutes <= 0 check
        Why: A zero-minute window makes no sense for spike detection
        How: Create alert with price=0, call check_alert, assert False
        """
        # alert: Spike alert with an invalid zero-minute time frame
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Zero Time Frame',
            type='spike',
            percentage=10.0,
            price=0,               # <-- invalid
            min_volume=1000,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_active=True,
        )

        cmd = self._make_command()
        all_prices = {'100': {'high': 5000, 'low': 4800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result, 'Alert with price=0 should return False')


# =============================================================================
# 2. SINGLE-ITEM SPIKE VOLUME TESTS
# =============================================================================

class SingleItemSpikeVolumeTests(SpikeTestMixin, TestCase):
    """
    Tests for single-item spike alerts and their volume filtering behavior.

    What: Verifies that single-item spike alerts correctly trigger or block
          based on the HourlyItemVolume data relative to the alert's min_volume.
    Why: Single-item spikes are the simplest spike variant — one item, one
         volume check. Getting this right is the foundation for multi-item
         and all-items variants.
    How: Each test creates a fully valid spike alert, seeds price_history with
         a baseline, provides spiked current prices, and varies only the
         HourlyItemVolume data to test different volume scenarios.
    """

    def setUp(self):
        """
        Create shared fixtures for single-item spike tests.

        What: Sets up a test user and a baseline single-item spike alert
        Why: Every test in this class needs the same alert configuration;
             only the volume records and price data differ
        How: Create a valid spike alert with price=60 (60 min window),
             percentage=10 (10% threshold), min_volume=1_000_000 (1M GP),
             direction='both', reference='high', item_id=100
        """
        # test_user: User instance for associating alerts
        self.test_user = User.objects.create_user(
            username='single_spike_user',
            email='single@example.com',
            password='testpass123',
        )

        # TIME_FRAME_MINUTES: Rolling window duration for the spike alert
        self.TIME_FRAME_MINUTES = 60

        # MIN_VOLUME: Minimum hourly GP volume required for the alert to fire
        self.MIN_VOLUME = 1_000_000

        # BASELINE_PRICE: The price seeded into history as the "old" baseline
        self.BASELINE_PRICE = 10_000

        # alert: A fully valid single-item spike alert
        # What: Watches item 100 (Dragon Bones) for a >=10% price change
        #       over a 60-minute window, requiring at least 1M GP hourly volume
        # Why: Serves as the base alert for all tests in this class
        # How: price=60 stores the time frame, min_volume=1000000 is the filter
        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Single Spike Volume Test',
            type='spike',
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

    def _build_spiked_prices(self, current_high):
        """
        Build an all_prices dict with a spiked price for item 100.

        What: Constructs the price data dict that check_alert expects
        Why: Keeps test methods concise by extracting price dict construction
        How: Returns {'100': {'high': current_high, 'low': current_high - 200}}

        Args:
            current_high: The current high price (should be >10% above
                          BASELINE_PRICE to exceed the 10% spike threshold)

        Returns:
            dict: Price data keyed by item_id string
        """
        return {'100': {'high': current_high, 'low': current_high - 200}}

    def test_volume_above_threshold_triggers(self):
        """
        Single-item spike should trigger when volume >= min_volume.

        What: Verifies the happy path — item has spiked AND has sufficient
              trading volume, so the alert should fire.
        Why: This is the expected normal behavior for a correctly configured
             spike alert with adequate market activity.
        How:
            1. Create HourlyItemVolume with volume > min_volume
            2. Seed price_history with baseline from 2× time_frame ago
            3. Provide current prices showing a 20% spike
            4. Assert check_alert returns True
        """
        # high_volume: Volume well above the 1M GP threshold
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        # 12000 is a 20% increase from baseline of 10000 → exceeds 10% threshold
        all_prices = self._build_spiked_prices(12_000)

        result = cmd.check_alert(self.alert, all_prices)

        self.assertTrue(result, 'Alert should trigger when volume is above min_volume')
        # Verify triggered_data was populated with correct fields
        # triggered_data_parsed: The JSON-decoded triggered data dict
        triggered_data_parsed = json.loads(self.alert.triggered_data)
        self.assertEqual(triggered_data_parsed['baseline'], self.BASELINE_PRICE)
        self.assertEqual(triggered_data_parsed['current'], 12_000)
        self.assertAlmostEqual(triggered_data_parsed['percent_change'], 20.0,
                               places=1)

    def test_volume_below_threshold_blocks(self):
        """
        Single-item spike should NOT trigger when volume < min_volume.

        What: Verifies that items with insufficient trading volume are filtered
              out even when the price spike exceeds the percentage threshold.
        Why: Low-volume items can have volatile prices that don't represent
             real market movement; the volume filter prevents false alerts.
        How:
            1. Create HourlyItemVolume with volume < min_volume
            2. Seed price_history and provide spiked prices
            3. Assert check_alert returns False
        """
        # low_volume: Volume below the 1M GP threshold (only 500K)
        self._create_volume_record(100, 'Dragon Bones', 500_000)

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        all_prices = self._build_spiked_prices(12_000)  # 20% spike

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result,
                         'Alert should NOT trigger when volume is below min_volume')

    def test_volume_none_blocks(self):
        """
        Single-item spike should NOT trigger when no volume data exists.

        What: Verifies that missing volume data (None from DB) blocks the alert
        Why: If the update_volumes.py script hasn't run yet, there are no
             HourlyItemVolume rows. The alert should not fire on items with
             unknown trading activity.
        How:
            1. Do NOT create any HourlyItemVolume records
            2. Seed price_history and provide spiked prices
            3. Assert check_alert returns False
        """
        # No HourlyItemVolume records created — get_volume_from_timeseries
        # will return None

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        all_prices = self._build_spiked_prices(12_000)  # 20% spike

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result,
                         'Alert should NOT trigger when volume data is None')

    def test_volume_exactly_at_threshold_triggers(self):
        """
        Single-item spike should trigger when volume == min_volume exactly.

        What: Verifies the boundary condition where volume equals the threshold
        Why: The filter uses strict less-than (volume < min_volume_threshold),
             so volume exactly at the threshold should PASS the filter.
        How:
            1. Create HourlyItemVolume with volume == min_volume (1,000,000)
            2. Seed price_history and provide spiked prices
            3. Assert check_alert returns True
        """
        # exact_volume: Volume exactly at the boundary — should pass
        self._create_volume_record(100, 'Dragon Bones', self.MIN_VOLUME)

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        all_prices = self._build_spiked_prices(12_000)  # 20% spike

        result = cmd.check_alert(self.alert, all_prices)

        self.assertTrue(result,
                        'Alert should trigger when volume exactly equals min_volume')

    def test_warmup_blocks_even_with_good_volume(self):
        """
        Alert should NOT trigger during warmup even when volume is sufficient.

        What: Verifies that the warmup period takes precedence over volume
        Why: Without enough historical data, the percent change calculation
             would be meaningless — warmup must complete first
        How:
            1. Create HourlyItemVolume with high volume
            2. Do NOT seed price_history (so there's no baseline data)
            3. Provide spiked current prices
            4. Assert check_alert returns False (warmup not complete)
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        # Deliberately NOT seeding price_history — warmup won't be satisfied

        all_prices = self._build_spiked_prices(12_000)

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result,
                         'Alert should NOT trigger during warmup period')

    def test_no_spike_with_good_volume_does_not_trigger(self):
        """
        Alert should NOT trigger when volume is good but price hasn't spiked.

        What: Verifies that volume alone is not sufficient — the price must
              actually exceed the percentage threshold
        Why: Volume is a filter, not a trigger condition
        How:
            1. Create HourlyItemVolume with high volume
            2. Seed price_history with baseline
            3. Provide current prices only 2% above baseline (below 10% threshold)
            4. Assert check_alert returns False
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        # 10200 is only 2% above 10000 — below the 10% threshold
        all_prices = self._build_spiked_prices(10_200)

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result,
                         'Alert should NOT trigger when price change is below threshold')


# =============================================================================
# 3. MULTI-ITEM SPIKE VOLUME TESTS
# =============================================================================

class MultiItemSpikeVolumeTests(SpikeTestMixin, TestCase):
    """
    Tests for multi-item spike alerts and their volume filtering behavior.

    What: Verifies that multi-item spike alerts (using the item_ids field)
          correctly filter individual items by volume while maintaining
          proper deactivation logic (all_within_threshold).
    Why: Multi-item spikes have the most complex interaction with volume
         filtering because each item is checked independently, and the
         recent bug fix changed when all_within_threshold is set.
    How: Create alerts with multiple items, vary volume records per item,
         and verify which items appear in the triggered matches list and
         whether the alert's state (is_triggered, triggered_data) is correct.
    """

    def setUp(self):
        """
        Create shared fixtures for multi-item spike tests.

        What: Sets up a test user and a multi-item spike alert watching 3 items
        Why: Provides a consistent base configuration for all multi-item tests
        How: Creates an alert with item_ids=[100, 200, 300], 10% threshold,
             60-minute window, min_volume=1,000,000
        """
        # test_user: User instance for associating alerts
        self.test_user = User.objects.create_user(
            username='multi_spike_user',
            email='multi@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 60
        self.MIN_VOLUME = 1_000_000

        # item_ids_list: The three items this alert monitors
        self.item_ids_list = [100, 200, 300]

        # BASELINE_PRICES: Starting prices for each item (seeded into history)
        self.BASELINE_PRICES = {
            '100': 10_000,     # Dragon Bones
            '200': 2_500_000,  # Abyssal Whip
            '300': 15_000_000, # Bandos Chestplate
        }

        # alert: Multi-item spike alert watching 3 items
        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Multi Spike Volume Test',
            type='spike',
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction='both',
            reference='high',
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Dragon Bones',
            item_id=100,
            is_active=True,
            is_triggered=False,
        )

    def _seed_all_baselines(self, cmd):
        """
        Seed price_history for all 3 items with their baseline prices.

        What: Pre-populates history for items 100, 200, 300
        Why: All items need warmed-up history for spike evaluation
        How: Calls _seed_price_history for each item using BASELINE_PRICES
        """
        for item_id_str, baseline_price in self.BASELINE_PRICES.items():
            self._seed_price_history(cmd, item_id_str, 'high', baseline_price,
                                     self.TIME_FRAME_MINUTES)

    def test_all_items_spike_all_pass_volume(self):
        """
        All 3 items spike and all have sufficient volume → all 3 in matches.

        What: Verifies the happy path where every item both spikes and has
              enough volume to pass the filter.
        Why: Confirms that volume filtering doesn't incorrectly remove items
             that should be in the triggered list.
        How:
            1. Create volume records above threshold for all 3 items
            2. Seed baselines and provide 15%+ spiked prices for all items
            3. Assert check_alert returns a list with all 3 items
        """
        # Create high-volume records for all items
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        self._create_volume_record(200, 'Abyssal Whip', 3_000_000)
        self._create_volume_record(300, 'Bandos Chestplate', 2_000_000)

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        # All items spike ~15% above their baselines
        # all_prices: Current price data with all items showing significant spikes
        all_prices = {
            '100': {'high': 11_500, 'low': 11_300},            # +15%
            '200': {'high': 2_875_000, 'low': 2_800_000},      # +15%
            '300': {'high': 17_250_000, 'low': 17_000_000},    # +15%
        }

        result = cmd.check_alert(self.alert, all_prices)

        # _handle_multi_item_spike_trigger returns the triggered_items list
        # on first trigger (data_changed=True)
        self.assertIsInstance(result, list,
                             'Result should be a list of triggered items')
        self.assertEqual(len(result), 3,
                         'All 3 items should appear in triggered matches')

        # triggered_ids: Set of item IDs that appeared in the result
        triggered_ids = {item['item_id'] for item in result}
        self.assertEqual(triggered_ids, {'100', '200', '300'})

    def test_mixed_volume_filters_low_volume_items(self):
        """
        Items that spike but have low volume should be excluded from matches.

        What: Verifies that the volume filter correctly removes individual
              items from the triggered list while keeping high-volume items.
        Why: This is the core volume filtering behavior — only actively traded
             items should appear in the alert notification.
        How:
            1. Item 100: high volume (passes)
            2. Item 200: low volume (filtered out)
            3. Item 300: high volume (passes)
            4. All items spike 15%
            5. Assert only items 100 and 300 appear in matches
        """
        # Item 100: passes volume filter
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        # Item 200: FAILS volume filter (below 1M threshold)
        self._create_volume_record(200, 'Abyssal Whip', 500_000)
        # Item 300: passes volume filter
        self._create_volume_record(300, 'Bandos Chestplate', 2_000_000)

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        # All 3 items spike 15%
        all_prices = {
            '100': {'high': 11_500, 'low': 11_300},
            '200': {'high': 2_875_000, 'low': 2_800_000},
            '300': {'high': 17_250_000, 'low': 17_000_000},
        }

        result = cmd.check_alert(self.alert, all_prices)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2,
                         'Only 2 items should pass volume filter')
        triggered_ids = {item['item_id'] for item in result}
        self.assertIn('100', triggered_ids, 'Item 100 should pass (high volume)')
        self.assertIn('300', triggered_ids, 'Item 300 should pass (high volume)')
        self.assertNotIn('200', triggered_ids,
                         'Item 200 should be filtered out (low volume)')

    def test_all_items_spike_none_pass_volume(self):
        """
        All items spike but none have sufficient volume → no matches, but
        all_within_threshold should still be False.

        What: Verifies that when all spiking items are filtered by volume,
              the alert does not trigger with any matches, but the alert
              stays active (not deactivated) because items DID spike.
        Why: This tests the bug fix where all_within_threshold was previously
             set AFTER the volume check. Even though no items pass the volume
             filter, the fact that they spiked means all_within_threshold should
             be False, preventing premature deactivation.
        How:
            1. Give all items low volume
            2. All items spike 15%
            3. Assert result is False (no matches passed volume)
            4. Assert alert is still active (not deactivated)
        """
        # All items have low volume
        self._create_volume_record(100, 'Dragon Bones', 100_000)
        self._create_volume_record(200, 'Abyssal Whip', 200_000)
        self._create_volume_record(300, 'Bandos Chestplate', 300_000)

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        # All items spike 15%
        all_prices = {
            '100': {'high': 11_500, 'low': 11_300},
            '200': {'high': 2_875_000, 'low': 2_800_000},
            '300': {'high': 17_250_000, 'low': 17_000_000},
        }

        result = cmd.check_alert(self.alert, all_prices)

        # No matches should pass volume → _handle_multi_item_spike_trigger
        # receives an empty matches list → returns False
        self.assertFalse(result,
                         'Result should be False when no items pass volume filter')
        # Refresh from DB to get the saved state
        self.alert.refresh_from_db()
        # The alert should still be active — it was NOT deactivated because
        # all_within_threshold is False (items DID spike, just filtered by volume)
        self.assertTrue(self.alert.is_active,
                        'Alert should remain active — items spiked even though '
                        'volume filtered them out (all_within_threshold=False)')

    def test_no_volume_data_filters_all_spiking_items(self):
        """
        When no HourlyItemVolume records exist, all spiking items are filtered.

        What: Verifies that missing volume data (None) blocks all items
        Why: If update_volumes.py hasn't populated the DB yet, the alert
             should not fire on any items
        How: Do not create any volume records, assert result is False
        """
        # No HourlyItemVolume records created at all

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        all_prices = {
            '100': {'high': 11_500, 'low': 11_300},
            '200': {'high': 2_875_000, 'low': 2_800_000},
            '300': {'high': 17_250_000, 'low': 17_000_000},
        }

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result,
                         'Should not trigger when no volume data exists')

    def test_only_spiking_items_get_volume_checked(self):
        """
        Items that don't spike should NOT have their volume checked.

        What: Verifies that volume is only queried for items that exceed the
              spike threshold — non-spiking items are skipped before volume.
        Why: Efficiency — don't waste DB queries on items that won't trigger
        How:
            1. Item 100: spikes 20%, has low volume → filtered by volume
            2. Item 200: spikes 15%, has high volume → passes
            3. Item 300: only 2% change, has high volume → never checked
            4. Assert only item 200 appears in matches
        """
        # Item 100: low volume — would be filtered IF it spikes (and it does)
        self._create_volume_record(100, 'Dragon Bones', 100_000)
        # Item 200: high volume — passes if it spikes
        self._create_volume_record(200, 'Abyssal Whip', 5_000_000)
        # Item 300: high volume, but it won't spike, so volume is irrelevant
        self._create_volume_record(300, 'Bandos Chestplate', 10_000_000)

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},            # +20% spike
            '200': {'high': 2_875_000, 'low': 2_800_000},      # +15% spike
            '300': {'high': 15_300_000, 'low': 15_100_000},    # +2% no spike
        }

        result = cmd.check_alert(self.alert, all_prices)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1,
                         'Only item 200 should be in matches')
        self.assertEqual(result[0]['item_id'], '200')

    def test_bug_fix_all_within_threshold_set_before_volume_check(self):
        """
        BUG FIX TEST: all_within_threshold must be False when items spike,
        regardless of whether they pass the volume filter.

        What: Verifies the bug fix where all_within_threshold was previously
              set AFTER the volume check (inside `if exceeds_threshold:` block,
              after the `continue` for volume filtering).
        Why: When all items spike but ALL are filtered by low volume:
             - OLD (buggy): all_within_threshold stays True → alert could
               be deactivated incorrectly
             - NEW (fixed): all_within_threshold is set to False BEFORE the
               volume check → alert stays active
        How:
            1. Give all items low volume (all will be volume-filtered)
            2. All items spike well above threshold
            3. Call check_alert twice — first to set baseline, second to verify
               the alert remains active and is not deactivated
            4. Assert alert.is_active is True after the check
        """
        # All items have low volume — every item will fail the volume filter
        self._create_volume_record(100, 'Dragon Bones', 100)
        self._create_volume_record(200, 'Abyssal Whip', 200)
        self._create_volume_record(300, 'Bandos Chestplate', 300)

        cmd = self._make_command()
        self._seed_all_baselines(cmd)

        # All 3 items spike massively (50% increase)
        all_prices = {
            '100': {'high': 15_000, 'low': 14_800},
            '200': {'high': 3_750_000, 'low': 3_700_000},
            '300': {'high': 22_500_000, 'low': 22_000_000},
        }

        result = cmd.check_alert(self.alert, all_prices)

        # Even though all items were volume-filtered, the alert must stay active
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.is_active,
                        'BUG FIX: Alert must remain active when items spike '
                        'but are filtered by volume (all_within_threshold=False)')
        # Result is False because no items passed volume, but the alert wasn't
        # deactivated — which is the correct behavior after the fix
        self.assertFalse(result)


# =============================================================================
# 4. ALL-ITEMS SPIKE VOLUME TESTS
# =============================================================================

class AllItemsSpikeVolumeTests(SpikeTestMixin, TestCase):
    """
    Tests for all-items spike alerts and their volume filtering behavior.

    What: Verifies that all-items spike alerts (is_all_items=True) correctly
          filter the entire market by volume when items exceed the spike
          threshold.
    Why: All-items mode iterates over every item in all_prices, which can
         include hundreds of low-volume items with volatile prices. The
         volume filter is critical to avoid a flood of false alerts.
    How: Create an all-items spike alert, provide a variety of items in
         all_prices with different volume levels, and verify only high-volume
         spiking items appear in the returned matches list.
    """

    def setUp(self):
        """
        Create shared fixtures for all-items spike tests.

        What: Sets up a test user and an all-items spike alert
        Why: All tests in this class use the same base alert configuration
        How: Alert with is_all_items=True, no item_id or item_ids
        """
        self.test_user = User.objects.create_user(
            username='all_items_spike_user',
            email='allitems@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 60
        self.MIN_VOLUME = 1_000_000

        # alert: All-items spike alert scanning the entire market
        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='All Items Spike Volume Test',
            type='spike',
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction='both',
            reference='high',
            is_all_items=True,
            is_active=True,
            is_triggered=False,
        )

    def test_only_high_volume_spiking_items_appear(self):
        """
        Only items that BOTH spike AND have sufficient volume should appear.

        What: Simulates a market with 4 items in different states:
              - Item A: spikes + high volume → appears
              - Item B: spikes + low volume → filtered out
              - Item C: no spike + high volume → not triggered
              - Item D: spikes + no volume data → filtered out
        Why: Validates that the volume filter works correctly in the all-items
             scan loop where hundreds of items may be evaluated
        How: Create volume records for items A-C, omit D, provide price data,
             seed baselines, and check which items appear in the result
        """
        # Item A (100): High volume, will spike
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        # Item B (200): Low volume, will spike but should be filtered
        self._create_volume_record(200, 'Abyssal Whip', 500_000)
        # Item C (300): High volume, but won't spike
        self._create_volume_record(300, 'Bandos Chestplate', 10_000_000)
        # Item D (400): No volume record at all, will spike

        cmd = self._make_command()

        # Seed baselines for all 4 items
        # BASELINES: Starting prices for the 4 simulated market items
        baselines = {
            '100': 10_000,
            '200': 2_500_000,
            '300': 15_000_000,
            '400': 30_000_000,
        }
        for item_id, price in baselines.items():
            self._seed_price_history(cmd, item_id, 'high', price,
                                     self.TIME_FRAME_MINUTES)

        # all_prices: Current market prices
        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},            # +20% spike
            '200': {'high': 3_000_000, 'low': 2_900_000},      # +20% spike
            '300': {'high': 15_300_000, 'low': 15_100_000},    # +2% no spike
            '400': {'high': 36_000_000, 'low': 35_500_000},    # +20% spike
        }

        result = cmd.check_alert(self.alert, all_prices)

        # Only item 100 should appear: it spiked AND has high volume
        # Item 200: spiked but low volume → filtered
        # Item 300: high volume but no spike → not triggered
        # Item 400: spiked but no volume data → filtered
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1,
                         'Only 1 item should pass both spike + volume filters')
        self.assertEqual(result[0]['item_id'], '100')

    def test_no_matches_returns_false(self):
        """
        All-items spike with no qualifying items should return False.

        What: When no items both spike AND pass volume, result is False
        Why: Ensures the all-items spike returns a clean False (not empty list)
             when no items qualify
        How: All spiking items have low volume; non-spiking items have high volume
        """
        # Only high-volume item doesn't spike
        self._create_volume_record(100, 'Dragon Bones', 100_000)  # low vol
        self._create_volume_record(200, 'Abyssal Whip', 5_000_000)  # high vol

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', 10_000,
                                 self.TIME_FRAME_MINUTES)
        self._seed_price_history(cmd, '200', 'high', 2_500_000,
                                 self.TIME_FRAME_MINUTES)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},           # spikes but low vol
            '200': {'high': 2_550_000, 'low': 2_500_000},     # high vol but no spike
        }

        result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result, 'Should return False when no items qualify')

    def test_min_max_price_filters_combined_with_volume(self):
        """
        Min/max price filters should be applied BEFORE volume is checked.

        What: Verifies that items excluded by minimum_price / maximum_price
              are skipped before even reaching the volume filter.
        Why: Price filters are an early exit — items outside the price range
             should never trigger, regardless of volume.
        How:
            1. Set minimum_price on the alert
            2. Item 100: baseline below min price → skipped by price filter
            3. Item 200: baseline above min price, spikes, high volume → triggers
            4. Assert only item 200 appears
        """
        # Update alert with a minimum price filter
        self.alert.minimum_price = 1_000_000  # Only items priced >= 1M GP
        self.alert.save()

        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        self._create_volume_record(200, 'Abyssal Whip', 5_000_000)

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', 10_000,
                                 self.TIME_FRAME_MINUTES)
        self._seed_price_history(cmd, '200', 'high', 2_500_000,
                                 self.TIME_FRAME_MINUTES)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},            # spikes but price < 1M
            '200': {'high': 3_000_000, 'low': 2_900_000},      # spikes and price > 1M
        }

        result = cmd.check_alert(self.alert, all_prices)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['item_id'], '200',
                         'Only item 200 should pass (above minimum_price + volume)')


# =============================================================================
# 5. SPIKE DIRECTION WITH VOLUME TESTS
# =============================================================================

class SpikeDirectionWithVolumeTests(SpikeTestMixin, TestCase):
    """
    Tests that direction filtering works correctly alongside volume filtering.

    What: Verifies that direction='up', 'down', and 'both' correctly interact
          with the volume filter — a spiking item must pass BOTH the direction
          check AND the volume check to trigger.
    Why: Direction and volume are independent filters applied in sequence;
         both must pass for an item to be included in matches.
    How: Create single-item spike alerts with different direction settings,
         vary the price movement direction and volume, and verify triggering.
    """

    def setUp(self):
        """
        Create shared fixtures for direction + volume tests.

        What: Sets up a test user with baseline prices and volume records
        Why: Each test creates its own alert with a specific direction, but
             shares the same user, baseline prices, and volume setup
        """
        self.test_user = User.objects.create_user(
            username='direction_vol_user',
            email='direction@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 60
        self.MIN_VOLUME = 1_000_000
        self.BASELINE_PRICE = 10_000

    def _make_alert(self, direction):
        """
        Create a single-item spike alert with the given direction.

        What: Factory method for creating direction-specific spike alerts
        Why: Each test needs a different direction value but identical other config
        How: Creates Alert with the specified direction and all other fields fixed

        Args:
            direction: 'up', 'down', or 'both'

        Returns:
            Alert: The created alert instance
        """
        return Alert.objects.create(
            user=self.test_user,
            alert_name=f'Direction {direction} Volume Test',
            type='spike',
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction=direction,
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
        )

    def test_direction_up_spike_up_good_volume_triggers(self):
        """
        direction='up' + upward spike + good volume → triggers.

        What: The simplest positive case for directional spike alerts
        Why: Confirms the happy path for up-only direction filtering
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        alert = self._make_alert('up')

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        # +20% upward spike
        all_prices = {'100': {'high': 12_000, 'low': 11_800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, 'Up spike with good volume should trigger')

    def test_direction_up_spike_up_low_volume_blocks(self):
        """
        direction='up' + upward spike + low volume → does NOT trigger.

        What: Volume filter should block even when direction matches
        Why: Confirms volume takes precedence after direction passes
        """
        self._create_volume_record(100, 'Dragon Bones', 500_000)  # low
        alert = self._make_alert('up')

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        all_prices = {'100': {'high': 12_000, 'low': 11_800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result,
                         'Up spike with low volume should NOT trigger')

    def test_direction_up_spike_down_good_volume_does_not_trigger(self):
        """
        direction='up' + downward spike + good volume → does NOT trigger.

        What: Even with sufficient volume, direction mismatch prevents trigger
        Why: Direction check happens before volume; a down spike with up
             direction never reaches the volume check
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        alert = self._make_alert('up')

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        # -20% downward movement
        all_prices = {'100': {'high': 8_000, 'low': 7_800}}

        result = cmd.check_alert(alert, all_prices)
        self.assertFalse(result,
                         'Down spike should NOT trigger up-only alert')

    def test_direction_down_spike_down_good_volume_triggers(self):
        """
        direction='down' + downward spike + good volume → triggers.

        What: Verifies down-direction spike with passing volume
        Why: Down direction needs its own test — the threshold comparison
             uses negative percent_change
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        alert = self._make_alert('down')

        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)

        # -15% downward spike (10000 → 8500)
        all_prices = {'100': {'high': 8_500, 'low': 8_300}}

        result = cmd.check_alert(alert, all_prices)
        self.assertTrue(result, 'Down spike with good volume should trigger')

    def test_direction_both_spike_either_direction_triggers(self):
        """
        direction='both' should trigger on spikes in either direction.

        What: Verifies that direction='both' triggers on both up and down spikes
              as long as volume is sufficient
        Why: 'both' uses abs(percent_change) >= threshold, which should catch
             movements in either direction
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        # Test upward spike
        alert_up = self._make_alert('both')
        cmd = self._make_command()
        self._seed_price_history(cmd, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)
        all_prices = {'100': {'high': 12_000, 'low': 11_800}}
        result_up = cmd.check_alert(alert_up, all_prices)
        self.assertTrue(result_up, 'Both direction should trigger on up spike')

        # Test downward spike with a fresh alert and command
        alert_down = self._make_alert('both')
        cmd2 = self._make_command()
        self._seed_price_history(cmd2, '100', 'high', self.BASELINE_PRICE,
                                 self.TIME_FRAME_MINUTES)
        all_prices_down = {'100': {'high': 8_000, 'low': 7_800}}
        result_down = cmd2.check_alert(alert_down, all_prices_down)
        self.assertTrue(result_down,
                        'Both direction should trigger on down spike')


# =============================================================================
# 6. SPIKE RE-TRIGGER TESTS
# =============================================================================

class SpikeRetriggerTests(SpikeTestMixin, TestCase):
    """
    Tests for multi-item spike alert re-triggering behavior with volume.

    What: Verifies that multi-item spike alerts correctly re-trigger when
          triggered_data changes and do NOT re-trigger when data is unchanged,
          all while respecting the volume filter.
    Why: Multi-item spikes stay active and re-check every cycle. The
         _handle_multi_item_spike_trigger method compares old vs new
         triggered_data to decide whether to send a notification. Volume
         filtering affects which items appear in triggered_data.
    How: Call check_alert multiple times with different price/volume scenarios
         and verify the alert's triggered state, triggered_data, and return
         value reflect the expected re-trigger behavior.
    """

    def setUp(self):
        """
        Create shared fixtures for re-trigger tests.

        What: Sets up a test user and multi-item spike alert watching 3 items
        Why: Re-trigger tests need multiple check_alert calls on the same alert
        """
        self.test_user = User.objects.create_user(
            username='retrigger_user',
            email='retrigger@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 60
        self.MIN_VOLUME = 1_000_000
        self.item_ids_list = [100, 200, 300]

        self.BASELINE_PRICES = {
            '100': 10_000,
            '200': 2_500_000,
            '300': 15_000_000,
        }

        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Retrigger Volume Test',
            type='spike',
            percentage=10.0,
            price=self.TIME_FRAME_MINUTES,
            min_volume=self.MIN_VOLUME,
            direction='both',
            reference='high',
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Dragon Bones',
            item_id=100,
            is_active=True,
            is_triggered=False,
        )

    def test_retrigger_when_new_item_passes_volume(self):
        """
        Re-trigger should occur when a new item starts passing volume filter.

        What: First check triggers with item 100. Second check should re-trigger
              because item 200 now also passes (triggered_data changed).
        Why: The user should be notified when new items start spiking.
        How:
            1. First call: only item 100 spikes + passes volume
            2. Create volume record for item 200
            3. Second call: items 100 AND 200 spike + pass volume
            4. Assert second call returns a list (re-triggered)
        """
        # First call: only item 100 has volume
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        for item_id, price in self.BASELINE_PRICES.items():
            self._seed_price_history(cmd, item_id, 'high', price,
                                     self.TIME_FRAME_MINUTES)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},            # spikes
            '200': {'high': 2_875_000, 'low': 2_800_000},      # spikes
            '300': {'high': 15_300_000, 'low': 15_100_000},    # no spike
        }

        # First check — only item 100 triggers (200 has no volume record)
        result1 = cmd.check_alert(self.alert, all_prices)
        self.assertIsInstance(result1, list)
        self.assertEqual(len(result1), 1)
        self.assertEqual(result1[0]['item_id'], '100')

        # Now add volume for item 200
        self._create_volume_record(200, 'Abyssal Whip', 3_000_000)

        # Second check — item 200 should now also appear → data changed → re-trigger
        result2 = cmd.check_alert(self.alert, all_prices)
        self.assertIsInstance(result2, list,
                             'Should re-trigger when new item passes volume')
        self.assertEqual(len(result2), 2,
                         'Should now have 2 items in triggered data')
        triggered_ids = {item['item_id'] for item in result2}
        self.assertIn('100', triggered_ids)
        self.assertIn('200', triggered_ids)

    def test_no_retrigger_when_same_items_same_data(self):
        """
        No re-trigger when the same items spike with the same values.

        What: Calling check_alert twice with identical data should NOT return
              triggered items on the second call.
        Why: Prevents notification spam — user already knows about these items.
        How:
            1. First call: item 100 triggers → returns list
            2. Second call: identical data → returns False (no change)
        """
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        for item_id, price in self.BASELINE_PRICES.items():
            self._seed_price_history(cmd, item_id, 'high', price,
                                     self.TIME_FRAME_MINUTES)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},            # spikes
            '200': {'high': 2_550_000, 'low': 2_500_000},      # no spike
            '300': {'high': 15_300_000, 'low': 15_100_000},    # no spike
        }

        # First call — triggers
        result1 = cmd.check_alert(self.alert, all_prices)
        self.assertIsInstance(result1, list)

        # Second call — same data, should NOT re-trigger
        result2 = cmd.check_alert(self.alert, all_prices)
        self.assertFalse(result2,
                         'Should NOT re-trigger when triggered_data unchanged')

    def test_retrigger_when_item_drops_out_of_volume(self):
        """
        Re-trigger should NOT occur when an item drops out of the matches
        due to volume data changing — but triggered_data should update.

        What: When an item's volume record is deleted (simulating stale data),
              the item is filtered out on the next check, changing triggered_data.
        Why: The _has_triggered_data_changed method detects item removal as a
             change, but since triggered_items is now empty (or reduced), the
             behavior depends on whether any items remain.
        How:
            1. First call: item 100 triggers (high volume)
            2. Delete item 100's volume record
            3. Second call: item 100 now has None volume → filtered out
            4. triggered_data changes (item removed) → but with empty matches,
               _handle_multi_item_spike_trigger returns False
        """
        vol_record = self._create_volume_record(100, 'Dragon Bones', 5_000_000)

        cmd = self._make_command()
        for item_id, price in self.BASELINE_PRICES.items():
            self._seed_price_history(cmd, item_id, 'high', price,
                                     self.TIME_FRAME_MINUTES)

        all_prices = {
            '100': {'high': 12_000, 'low': 11_800},
            '200': {'high': 2_550_000, 'low': 2_500_000},
            '300': {'high': 15_300_000, 'low': 15_100_000},
        }

        # First call — triggers with item 100
        result1 = cmd.check_alert(self.alert, all_prices)
        self.assertIsInstance(result1, list)
        self.assertEqual(len(result1), 1)

        # Delete the volume record — simulates data becoming stale/unavailable
        vol_record.delete()

        # Second call — item 100 now filtered (None volume) → empty matches
        result2 = cmd.check_alert(self.alert, all_prices)

        # With no items passing volume, triggered_data changes to empty list
        # _handle_multi_item_spike_trigger returns False for empty matches
        self.assertFalse(result2,
                         'Should return False when sole triggering item loses volume')


# =============================================================================
# MAIN: Allow running directly with `python test_spike_volume.py`
# =============================================================================
if __name__ == '__main__':
    import django
    import os

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')
    django.setup()

    from django.test.utils import get_runner
    from django.conf import settings

    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(['test_spike_volume'])
    sys.exit(bool(failures))
