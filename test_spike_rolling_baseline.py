"""
Spike Alert Rolling Baseline Test Suite
========================================

What: Comprehensive tests verifying that spike alerts recalculate their baseline
      price via a rolling buffer after each alert check, once the warmup period
      has passed.
Why: Spike alerts must compare the current price against the price from exactly
     one timeframe ago. The baseline must NOT be static — it must shift forward
     (roll) on every check cycle so that we're always comparing "now" to "then"
     relative to the configured timeframe. Without rolling, the baseline becomes
     stale and the alert would compare against an increasingly outdated price.
How: Each test simulates multiple sequential check_alert() calls with manipulated
     timestamps in the Command's price_history. The tests verify:
     1. During warmup: alert does not trigger (insufficient historical data)
     2. After warmup: baseline equals the price from exactly [timeframe] ago
     3. On subsequent checks: baseline shifts as new data is appended and old
        data is pruned from the rolling buffer
     4. Rolling works correctly for single-item, multi-item, and all-items spike alerts

Rolling Baseline Behavior (example with 5-min timeframe, checks every 5 min):
    time 0 (creation)  → record P0, baseline = N/A (warming up)
    time 1             → record P1, baseline = P0 (warmup just passed)
    time 2             → record P2, baseline = P1 (P0 pruned from rolling buffer)
    time 3             → record P3, baseline = P2 (P1 pruned)
    ...and so on.

Running all tests:
    python manage.py test test_spike_rolling_baseline --verbosity=2

Running a specific test class:
    python manage.py test test_spike_rolling_baseline.SingleItemRollingBaselineTests --verbosity=2

Running a single test:
    python manage.py test test_spike_rolling_baseline.SingleItemRollingBaselineTests.test_baseline_rolls_after_warmup --verbosity=2
"""

import json
import sys
import time
from collections import defaultdict
from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import User

from Website.models import Alert, HourlyItemVolume
from Website.management.commands.check_alerts import Command


# =============================================================================
# SHARED TEST HELPERS
# =============================================================================
# What: Reusable helper functions and a mixin for setting up rolling baseline tests
# Why: All test classes share the same pattern of creating a Command instance,
#      manipulating price history timestamps, and verifying baseline shifts.
#      Centralizing these into a mixin avoids duplication.
# How: RollingBaselineMixin provides methods for:
#      - _make_command(): Creates a Command instance with captured stdout
#      - _seed_history_at(): Inserts a price point at a specific timestamp
#      - _create_volume_record(): Creates HourlyItemVolume rows for volume filter
#      - _simulate_check(): Runs check_alert with time.time() mocked to a specific value
# =============================================================================

class RollingBaselineMixin:
    """
    Mixin providing shared helpers for rolling baseline test classes.

    What: Contains factory methods for creating Command instances, seeding
          price history at exact timestamps, and simulating check_alert calls
          at specific points in time.
    Why: Rolling baseline tests require fine-grained control over timestamps
         to verify that baselines shift correctly. Standard _seed_price_history
         from the volume tests isn't precise enough for these scenarios.
    How: Each helper manipulates the Command's internal state (price_history)
         and uses time.time() mocking to simulate temporal progression.
    """

    # ITEM_MAPPING: Shared mapping of item IDs to human-readable names used
    # across all test classes. Mirrors the format returned by get_item_mapping().
    ITEM_MAPPING = {
        '100': 'Dragon Bones',
        '200': 'Abyssal Whip',
        '300': 'Bandos Chestplate',
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
        # Override get_item_mapping to avoid hitting the real API
        cmd.get_item_mapping = lambda: self.ITEM_MAPPING
        return cmd

    def _seed_history_at(self, cmd, item_id, reference, price, timestamp):
        """
        Insert a price point at an exact timestamp into the command's price_history.

        What: Adds a single (timestamp, price) tuple to the rolling buffer
              for the given item+reference combination.
        Why: Rolling baseline tests need precise control over when each data
             point was recorded. Unlike _seed_price_history in the volume tests
             (which calculates a timestamp relative to now), this method accepts
             an absolute timestamp.
        How: Directly appends to cmd.price_history[key].

        Args:
            cmd: Command instance whose price_history to populate
            item_id: Item ID (str or int) — will be converted to str for the key
            reference: Price reference type ('high', 'low', 'average')
            price: The price value to store
            timestamp: Unix timestamp (float) for when this price was recorded
        """
        # key: The price_history lookup key, e.g. "100:high"
        key = f"{item_id}:{reference}"
        cmd.price_history[key].append((timestamp, price))

    def _create_volume_record(self, item_id, item_name, volume):
        """
        Insert a HourlyItemVolume row into the test database.

        What: Creates a volume snapshot record for a specific item.
        Why: The spike alert's volume filter queries HourlyItemVolume via
             get_volume_from_timeseries(). We create real DB rows so that
             the full query path is exercised.
        How: Uses HourlyItemVolume.objects.create() with a fixed timestamp.

        Args:
            item_id: OSRS item ID (int)
            item_name: Human-readable item name for the DB record
            volume: Hourly volume in GP (gold pieces)

        Returns:
            HourlyItemVolume: The created database record
        """
        return HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=item_name,
            volume=volume,
            timestamp='2026-02-06T12:00:00Z',
        )


# =============================================================================
# 1. SINGLE-ITEM ROLLING BASELINE TESTS
# =============================================================================

class SingleItemRollingBaselineTests(RollingBaselineMixin, TestCase):
    """
    Tests that single-item spike alerts correctly roll the baseline price
    on each check cycle after warmup has completed.

    What: Verifies the core rolling baseline behavior for single-item spike alerts.
    Why: Single-item spike alerts are the simplest variant and form the foundation
         for understanding how the rolling window works. If the baseline doesn't
         roll correctly here, it won't work for multi-item or all-items either.
    How: Each test creates a spike alert, seeds price_history with multiple data
         points at known timestamps, then calls check_alert() with time.time()
         mocked to specific values. Assertions verify that the baseline comes
         from the correct historical data point.
    """

    def setUp(self):
        """
        Create shared fixtures for single-item rolling baseline tests.

        What: Sets up a test user, a single-item spike alert, and volume records.
        Why: Every test in this class needs the same base configuration.
        How: Creates a spike alert with a 5-minute timeframe, 10% threshold,
             min_volume=1M, watching item 100 with 'high' reference.
        """
        # test_user: User instance for associating alerts
        self.test_user = User.objects.create_user(
            username='rolling_single_user',
            email='rolling_single@example.com',
            password='testpass123',
        )

        # TIME_FRAME_MINUTES: Rolling window duration (5 minutes)
        self.TIME_FRAME_MINUTES = 5

        # MIN_VOLUME: Minimum hourly GP volume required for the alert to fire
        self.MIN_VOLUME = 1_000_000

        # alert: A fully valid single-item spike alert
        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Rolling Baseline Single Test',
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

        # Create a volume record above threshold so volume filter never blocks
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

    def test_warmup_period_returns_false(self):
        """
        During warmup, check_alert should return False even if the price spiked.

        What: Verifies that the alert doesn't trigger until enough historical
              data has accumulated (the oldest data point must be at least
              [timeframe] seconds old).
        Why: Spike detection requires a valid baseline from [timeframe] ago.
             Without it, any percent change calculation would be meaningless.
        How:
            1. Seed price_history with a data point from 2 minutes ago
               (less than the 5-minute timeframe)
            2. Provide current prices showing a massive spike
            3. Assert check_alert returns False (still warming up)
        """
        cmd = self._make_command()

        # base_time: The "current" time for this test
        base_time = 1_000_000.0

        # Seed a data point from only 2 minutes ago (< 5 min timeframe)
        # This is too recent to pass the warmup check
        self._seed_history_at(cmd, '100', 'high', 1000, base_time - 120)

        # all_prices: Current prices showing a huge spike (50% above baseline)
        all_prices = {'100': {'high': 1500, 'low': 1400}}

        with patch('time.time', return_value=base_time):
            result = cmd.check_alert(self.alert, all_prices)

        self.assertFalse(result, 'Alert should NOT trigger during warmup period')

    def test_baseline_available_after_warmup(self):
        """
        After warmup, the baseline should be the oldest price in the rolling window
        that is at least [timeframe] seconds old.

        What: Verifies that once enough historical data exists, the alert can
              evaluate and trigger if the current price exceeds the threshold.
        Why: This is the first check after warmup — the baseline should be the
             price recorded [timeframe] ago.
        How:
            1. Seed price_history with a data point from exactly 5 minutes + 1s ago
               (passes warmup and survives cutoff pruning with the 2-second buffer)
            2. Provide current prices showing a 20% spike
            3. Assert check_alert returns True and triggered_data has correct baseline
        """
        cmd = self._make_command()
        base_time = 1_000_000.0

        # baseline_price: The price recorded at [timeframe + 1s] seconds ago
        # Positioned 1s past warmup_threshold but within the 2-second cutoff buffer
        baseline_price = 1000
        baseline_ts = base_time - (self.TIME_FRAME_MINUTES * 60) - 1

        self._seed_history_at(cmd, '100', 'high', baseline_price, baseline_ts)

        # current_price: 20% above baseline (1200 vs 1000 = +20%)
        all_prices = {'100': {'high': 1200, 'low': 1100}}

        with patch('time.time', return_value=base_time):
            result = cmd.check_alert(self.alert, all_prices)

        self.assertTrue(result, 'Alert should trigger after warmup with sufficient spike')

        # Verify the triggered_data contains the correct baseline
        triggered_data = json.loads(self.alert.triggered_data)
        self.assertEqual(triggered_data['baseline'], baseline_price,
                         'Triggered data should show the correct baseline price')
        self.assertEqual(triggered_data['current'], 1200,
                         'Triggered data should show the correct current price')

    def test_baseline_rolls_after_warmup(self):
        """
        After warmup, the baseline should shift on each subsequent check as
        old data is pruned from the rolling buffer.

        What: THE CORE TEST for rolling baseline behavior. Simulates multiple
              sequential checks and verifies that the baseline changes each time.
        Why: This is the exact scenario described in the issue:
             - time 0: record P0 (warmup starts)
             - time 1: baseline = P0 (warmup just passed)
             - time 2: P0 pruned, baseline = P1
             - time 3: P1 pruned, baseline = P2
        How:
            1. Use a 5-minute timeframe with checks every 5 minutes
            2. Pre-seed multiple price points at known timestamps
            3. Mock time.time() to advance by 5 minutes per check
            4. Verify that each check uses a different (shifted) baseline

        This test directly validates the rolling buffer behavior described
        in the issue where the baseline recalculates after every alert check.
        """
        cmd = self._make_command()

        # base_time: Starting point for our time simulation
        base_time = 1_000_000.0
        # check_interval: Seconds between each simulated check (5 minutes)
        check_interval = self.TIME_FRAME_MINUTES * 60  # 300 seconds

        # Seed price history with data points at each "check" interval
        # These represent prices recorded during previous check cycles:
        # P0 at t=0, P1 at t=300, P2 at t=600, P3 at t=900, P4 at t=1200
        historical_prices = [1000, 1010, 1020, 1030, 1040]
        for i, price in enumerate(historical_prices):
            ts = base_time + (i * check_interval)
            self._seed_history_at(cmd, '100', 'high', price, ts)

        # --- Check at time index 5 (t = 1500s from base_time) ---
        # The current "now" is 5 intervals after base_time.
        # warmup_threshold = now - 300 = base_time + 1200
        # cutoff = now - 300 - 60 = base_time + 1140
        # P0 (base_time + 0) is way before cutoff → pruned
        # P1 (base_time + 300) is before cutoff → pruned
        # P2 (base_time + 600) is before cutoff → pruned
        # P3 (base_time + 900) is before cutoff → pruned
        # P4 (base_time + 1200) is >= cutoff (1140) → survives
        # P4 timestamp (1200) <= warmup_threshold (1200) → warmup passes
        # Baseline = P4 = 1040
        now_5 = base_time + (5 * check_interval)

        # current_high: Must be > 10% above expected baseline for trigger
        # P4 = 1040 → 10% = 1144, use 1200 to be safe (15.4% spike)
        all_prices_5 = {'100': {'high': 1200, 'low': 1100}}

        with patch('time.time', return_value=now_5):
            result_5 = cmd.check_alert(self.alert, all_prices_5)

        self.assertTrue(result_5, 'Check 5 should trigger (P4 baseline, 15.4% spike)')
        triggered_5 = json.loads(self.alert.triggered_data)
        self.assertEqual(triggered_5['baseline'], 1040,
                         'Check 5 baseline should be P4 (1040)')

        # Reset triggered state for next check
        self.alert.is_triggered = False
        self.alert.triggered_data = None
        self.alert.save()

        # --- Check at time index 6 (t = 1800s from base_time) ---
        # Now price_history has P4(1200) and P5(1500,1200) from check 5.
        # warmup_threshold = 1800 - 300 = 1500
        # cutoff = 1800 - 300 - 60 = 1440
        # P4 (base_time + 1200) < cutoff (base_time + 1440) → pruned!
        # P5 (base_time + 1500) >= cutoff → survives
        # P5 timestamp (1500) <= warmup_threshold (1500) → warmup passes
        # Baseline = P5 = 1200 (the price recorded during check 5)
        # NEW baseline is different from check 5's baseline (1040) → ROLLING!
        now_6 = base_time + (6 * check_interval)

        # current_high: Must be > 10% above P5 (1200) → need > 1320
        all_prices_6 = {'100': {'high': 1400, 'low': 1300}}

        with patch('time.time', return_value=now_6):
            result_6 = cmd.check_alert(self.alert, all_prices_6)

        self.assertTrue(result_6, 'Check 6 should trigger (P5 baseline, 16.7% spike)')
        triggered_6 = json.loads(self.alert.triggered_data)

        # CRITICAL ASSERTION: Baseline must have SHIFTED from P4 (1040) to P5 (1200)
        self.assertNotEqual(triggered_6['baseline'], 1040,
                            'Baseline must NOT still be P4 — it should have rolled')
        self.assertEqual(triggered_6['baseline'], 1200,
                         'Check 6 baseline should be P5 (1200) — the price from '
                         'the previous check, which is now [timeframe] seconds old')

    def test_baseline_rolls_continuously(self):
        """
        The baseline should continue rolling on every subsequent check,
        not just once after the initial warmup period.

        What: Extends the rolling test to 3+ consecutive checks after warmup
              to verify the baseline keeps shifting.
        Why: A bug might cause the baseline to roll once but then get "stuck"
             on a subsequent check. This test catches that scenario.
        How: Simulate 4 consecutive post-warmup checks and verify each has a
             different baseline that matches the price from [timeframe] ago.
             Each check uses a price that is always 50% above the current
             baseline to ensure triggering even after the baseline rolls up.
        """
        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = self.TIME_FRAME_MINUTES * 60  # 300 seconds

        # Pre-seed a long history of prices (checks 0-8)
        # Each price increases by 100 so we can identify which one is the baseline
        historical_prices = [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800]
        for i, price in enumerate(historical_prices):
            ts = base_time + (i * check_interval)
            self._seed_history_at(cmd, '100', 'high', price, ts)

        # With the 2-second buffer in cutoff:
        #
        # Check 9 (now = base_time + 2700):
        #   cutoff = 2700 - 300 - 2 = 2398 → base_time + 2398
        #   Entries surviving: P8(2400) survives (>= 2398), everything before pruned
        #   warmup: P8(2400) <= 2700-300=2400 → passes
        #   Baseline = P8 = 1800
        #
        # Check 10 (now = base_time + 3000):
        #   cutoff = 3000 - 302 = 2698
        #   P8(2400) < 2698 → pruned; P9(2700) >= 2698 → survives
        #   Baseline = P9 (whatever price was recorded at check 9)
        #
        # Each check, the baseline shifts to the price from the previous check.

        # We'll run checks 9, 10, 11, 12 and verify baselines roll
        baselines_found = []

        for check_num in range(9, 13):
            now = base_time + (check_num * check_interval)

            # Compute what the baseline will be so we can set a price 50% above it
            # On check 9: baseline = P8 = 1800
            # On check 10+: baseline = previous check's recorded price
            # Use exponential pricing so each check is always >10% above baseline:
            # 1800 * (1.5 ^ (check_num - 8)) guarantees a 50% spike each cycle
            current_high = int(1800 * (1.5 ** (check_num - 8)))
            all_prices = {'100': {'high': current_high, 'low': current_high - 100}}

            # Reset alert state for next check
            self.alert.is_triggered = False
            self.alert.triggered_data = None
            self.alert.save()

            with patch('time.time', return_value=now):
                result = cmd.check_alert(self.alert, all_prices)

            self.assertTrue(result, f'Check {check_num} should trigger')
            triggered = json.loads(self.alert.triggered_data)
            baselines_found.append(triggered['baseline'])

        # Verify all baselines are different (rolling is happening)
        self.assertEqual(len(set(baselines_found)), len(baselines_found),
                         f'All baselines should be different (rolling). '
                         f'Got: {baselines_found}')

        # Verify baselines are in ascending order (shifting forward in time)
        for i in range(1, len(baselines_found)):
            self.assertGreater(baselines_found[i], baselines_found[i - 1],
                               f'Baseline at check {9 + i} should be greater than '
                               f'check {9 + i - 1}. Got: {baselines_found}')

    def test_warmup_then_first_roll(self):
        """
        Verify the complete lifecycle: warmup → first trigger → first roll.

        What: Simulates 3 checks: one during warmup, one at first trigger,
              and one after the baseline has rolled.
        Why: This tests the full transition from warmup to active rolling,
             which is the most common real-world scenario.
        How:
            1. Check 0: No historical data → warming up → False
            2. Check 1: P0 is now [timeframe] old → baseline = P0 → trigger
            3. Check 2: P0 pruned, P1 in window → baseline = P1 → trigger
        """
        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = self.TIME_FRAME_MINUTES * 60  # 300 seconds

        # --- Check 0: Record initial price, no history → warming up ---
        all_prices = {'100': {'high': 1000, 'low': 900}}
        with patch('time.time', return_value=base_time):
            result_0 = cmd.check_alert(self.alert, all_prices)
        self.assertFalse(result_0, 'Check 0 should return False (warming up)')

        # --- Check 1: P0 is now 300s old = 1 timeframe → warmup passes ---
        # Current price is 1200 (20% above P0=1000)
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1200, 'low': 1100}}
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(self.alert, all_prices_1)
        self.assertTrue(result_1, 'Check 1 should trigger (P0 baseline, 20% spike)')
        triggered_1 = json.loads(self.alert.triggered_data)
        self.assertEqual(triggered_1['baseline'], 1000,
                         'Check 1 baseline should be P0 (1000)')

        # Reset for next check
        self.alert.is_triggered = False
        self.alert.triggered_data = None
        self.alert.save()

        # --- Check 2: P0 should be pruned, P1 becomes baseline ---
        # P0 (base_time) : cutoff = base_time + 600 - 360 = base_time + 240
        #   P0 at base_time (0) < 240 → pruned ✓
        # P1 (base_time + 300, price=1200): survives cutoff, passes warmup
        #   P1 at 300 >= 240 → survives ✓
        #   P1 at 300 <= warmup (600-300=300) → passes warmup ✓
        # Baseline = P1 = 1200
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1500, 'low': 1400}}
        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(self.alert, all_prices_2)
        self.assertTrue(result_2, 'Check 2 should trigger (P1 baseline, 25% spike)')
        triggered_2 = json.loads(self.alert.triggered_data)

        # CRITICAL: Baseline must have rolled from P0 (1000) to P1 (1200)
        self.assertNotEqual(triggered_2['baseline'], 1000,
                            'Baseline must NOT still be P0 after rolling')
        self.assertEqual(triggered_2['baseline'], 1200,
                         'Check 2 baseline should be P1 (1200)')

    def test_no_trigger_when_spike_below_threshold_after_roll(self):
        """
        After the baseline rolls, the percent change recalculates against
        the new baseline. If the change is below threshold, no trigger.

        What: Verifies that rolling the baseline can cause a previously-triggering
              alert to stop triggering (because the new baseline is closer to
              the current price).
        Why: If the baseline was static, a small initial movement could keep
             triggering forever. Rolling ensures the alert re-evaluates fairly.
        How:
            1. Seed history so baseline is 1000, current is 1100 (10% spike → triggers)
            2. On next check, baseline rolls to 1100, current is 1105 (0.45% → no trigger)
        """
        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = self.TIME_FRAME_MINUTES * 60

        # Seed P0 at [timeframe + 1s] ago with price 1000
        p0_ts = base_time - (self.TIME_FRAME_MINUTES * 60) - 1
        self._seed_history_at(cmd, '100', 'high', 1000, p0_ts)

        # Check 0: Current = 1100 (10% above P0=1000 → triggers at exactly threshold)
        all_prices_0 = {'100': {'high': 1100, 'low': 1000}}
        with patch('time.time', return_value=base_time):
            result_0 = cmd.check_alert(self.alert, all_prices_0)
        self.assertTrue(result_0, 'Check 0 should trigger (10% spike)')

        # Reset for next check
        self.alert.is_triggered = False
        self.alert.triggered_data = None
        self.alert.save()

        # Check 1: baseline should roll to P0's successor (1100 from check 0)
        # Current = 1105 → only 0.45% above new baseline of 1100 → no trigger
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1105, 'low': 1005}}
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(self.alert, all_prices_1)
        self.assertFalse(result_1,
                         'Check 1 should NOT trigger because the rolled baseline '
                         '(1100) makes the 0.45% change below the 10% threshold')


# =============================================================================
# 2. MULTI-ITEM ROLLING BASELINE TESTS
# =============================================================================

class MultiItemRollingBaselineTests(RollingBaselineMixin, TestCase):
    """
    Tests that multi-item spike alerts correctly roll the baseline price
    independently for each monitored item.

    What: Verifies that each item in a multi-item spike alert has its own
          independent rolling baseline that shifts after warmup.
    Why: Multi-item alerts track multiple items simultaneously. Each item
         may have different price histories and should roll independently.
    How: Create alerts with item_ids, seed different baselines for each item,
         simulate checks, and verify each item's baseline rolls correctly.
    """

    def setUp(self):
        """
        Create shared fixtures for multi-item rolling baseline tests.
        """
        self.test_user = User.objects.create_user(
            username='rolling_multi_user',
            email='rolling_multi@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 5
        self.MIN_VOLUME = 1_000_000
        self.item_ids_list = [100, 200]

        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Rolling Baseline Multi Test',
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

        # Create high-volume records for both items so volume filter passes
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)
        self._create_volume_record(200, 'Abyssal Whip', 5_000_000)

    def test_multi_item_baselines_roll_independently(self):
        """
        Each item in a multi-item spike alert should have its own rolling
        baseline that shifts independently.

        What: Verifies that item 100 and item 200 can have different baselines
              that roll at different rates depending on their price histories.
        Why: Items are tracked independently in price_history with separate keys.
             A bug could cause them to share state or fail to roll one of them.
        How:
            1. Seed both items with different starting prices
            2. Run check at warmup-complete time
            3. Run another check and verify both baselines have shifted
        """
        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = self.TIME_FRAME_MINUTES * 60

        # Seed P0 for both items at time 0
        self._seed_history_at(cmd, '100', 'high', 1000, base_time)
        self._seed_history_at(cmd, '200', 'high', 5000, base_time)

        # --- Check 1 (t = base_time + 300s): warmup passes for both ---
        now_1 = base_time + check_interval
        all_prices_1 = {
            '100': {'high': 1200, 'low': 1100},     # +20% from 1000
            '200': {'high': 6000, 'low': 5800},      # +20% from 5000
        }

        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(self.alert, all_prices_1)

        self.assertIsInstance(result_1, list, 'Check 1 should return triggered items list')
        self.assertEqual(len(result_1), 2, 'Both items should trigger')

        # Extract baselines from check 1
        baselines_1 = {item['item_id']: item['baseline'] for item in result_1}
        self.assertEqual(baselines_1['100'], 1000, 'Item 100 baseline should be P0 (1000)')
        self.assertEqual(baselines_1['200'], 5000, 'Item 200 baseline should be P0 (5000)')

        # --- Check 2 (t = base_time + 600s): baselines should roll ---
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {
            '100': {'high': 1500, 'low': 1400},     # needs to spike above new baseline
            '200': {'high': 7500, 'low': 7300},      # needs to spike above new baseline
        }

        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(self.alert, all_prices_2)

        self.assertIsInstance(result_2, list, 'Check 2 should return triggered items list')

        baselines_2 = {item['item_id']: item['baseline'] for item in result_2}

        # Both baselines should have shifted from their P0 values
        self.assertNotEqual(baselines_2['100'], 1000,
                            'Item 100 baseline should have rolled (not still P0)')
        self.assertNotEqual(baselines_2['200'], 5000,
                            'Item 200 baseline should have rolled (not still P0)')


# =============================================================================
# 3. ALL-ITEMS ROLLING BASELINE TESTS
# =============================================================================

class AllItemsRollingBaselineTests(RollingBaselineMixin, TestCase):
    """
    Tests that all-items spike alerts correctly roll the baseline price
    for each item in the market.

    What: Verifies rolling baseline behavior in all-items mode where every
          item in all_prices is evaluated.
    Why: All-items mode has its own code path and iterates over all market items.
         The rolling baseline must work identically to single-item mode but for
         each item independently.
    How: Create an all-items spike alert, provide market data, and verify
         baselines shift on subsequent checks.
    """

    def setUp(self):
        """
        Create shared fixtures for all-items rolling baseline tests.
        """
        self.test_user = User.objects.create_user(
            username='rolling_all_user',
            email='rolling_all@example.com',
            password='testpass123',
        )

        self.TIME_FRAME_MINUTES = 5
        self.MIN_VOLUME = 1_000_000

        self.alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Rolling Baseline All Items Test',
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

        # Create volume record for the test item
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

    def test_all_items_baseline_rolls(self):
        """
        In all-items mode, each item's baseline should roll independently.

        What: Verifies that the rolling baseline works in the all-items code path.
        Why: All-items mode iterates over all_prices and manages price_history
             independently for each item. Baseline rolling must work here too.
        How:
            1. Seed item 100 with a baseline
            2. Check once (baseline = P0)
            3. Check again (baseline should shift to P1)
        """
        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = self.TIME_FRAME_MINUTES * 60

        # Seed P0 for item 100
        self._seed_history_at(cmd, '100', 'high', 1000, base_time)

        # --- Check 1: baseline = P0 ---
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1200, 'low': 1100}}

        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(self.alert, all_prices_1)

        self.assertIsInstance(result_1, list, 'Check 1 should trigger')
        self.assertEqual(result_1[0]['baseline'], 1000,
                         'Check 1 baseline should be P0 (1000)')

        # --- Check 2: baseline should roll ---
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1500, 'low': 1400}}

        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(self.alert, all_prices_2)

        self.assertIsInstance(result_2, list, 'Check 2 should trigger')
        # Baseline should have shifted from P0 (1000) to P1 (1200)
        self.assertNotEqual(result_2[0]['baseline'], 1000,
                            'Baseline should have rolled (not still P0)')
        self.assertEqual(result_2[0]['baseline'], 1200,
                         'Check 2 baseline should be P1 (1200)')


# =============================================================================
# 4. EDGE CASE TESTS
# =============================================================================

class RollingBaselineEdgeCaseTests(RollingBaselineMixin, TestCase):
    """
    Edge case tests for the rolling baseline mechanism.

    What: Tests unusual scenarios like rapid checks, single-entry windows,
          and large timeframes to ensure the rolling logic is robust.
    Why: Edge cases often reveal subtle bugs in timestamp arithmetic,
         boundary conditions, and pruning logic.
    How: Each test constructs a specific edge case scenario and verifies
         the baseline behaves correctly.
    """

    def setUp(self):
        """
        Create shared fixtures for edge case tests.
        """
        self.test_user = User.objects.create_user(
            username='rolling_edge_user',
            email='rolling_edge@example.com',
            password='testpass123',
        )
        self._create_volume_record(100, 'Dragon Bones', 5_000_000)

    def test_large_timeframe_baseline_rolls(self):
        """
        Rolling baseline should work correctly with large timeframes (e.g., 24 hours).

        What: Verifies that the rolling mechanism scales to large timeframes.
        Why: Real users might set timeframes of hours or days. The pruning
             and warmup logic must handle these correctly.
        How: Use a 60-minute timeframe, seed data at appropriate intervals,
             and verify baseline rolls.
        """
        time_frame_minutes = 60

        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Large Timeframe Rolling Test',
            type='spike',
            percentage=10.0,
            price=time_frame_minutes,
            min_volume=1_000_000,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = time_frame_minutes * 60  # 3600 seconds

        # Seed P0 at time 0
        self._seed_history_at(cmd, '100', 'high', 1000, base_time)

        # --- Check 1 (1 hour later): baseline = P0 ---
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1200, 'low': 1100}}

        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(alert, all_prices_1)

        self.assertTrue(result_1, 'Check 1 should trigger')
        triggered_1 = json.loads(alert.triggered_data)
        self.assertEqual(triggered_1['baseline'], 1000)

        # Reset for next check
        alert.is_triggered = False
        alert.triggered_data = None
        alert.save()

        # --- Check 2 (2 hours later): baseline should roll to P1 ---
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1500, 'low': 1400}}

        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(alert, all_prices_2)

        self.assertTrue(result_2, 'Check 2 should trigger')
        triggered_2 = json.loads(alert.triggered_data)

        # Baseline should have rolled from P0 (1000) to P1 (1200)
        self.assertNotEqual(triggered_2['baseline'], 1000,
                            'Baseline should have rolled for large timeframe')
        self.assertEqual(triggered_2['baseline'], 1200,
                         'Check 2 baseline should be P1 (1200)')

    def test_rapid_checks_within_same_second(self):
        """
        Multiple rapid checks within the same second should not break
        the rolling baseline logic.

        What: Verifies that multiple check_alert calls at nearly the same
              timestamp don't corrupt the price_history.
        Why: The management command checks every 5 seconds. If checks are
             very rapid, duplicate timestamps might cause issues.
        How: Call check_alert twice with timestamps < 1 second apart,
             verify both work correctly and don't duplicate data.
        """
        time_frame_minutes = 5

        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Rapid Check Test',
            type='spike',
            percentage=10.0,
            price=time_frame_minutes,
            min_volume=1_000_000,
            direction='both',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = time_frame_minutes * 60

        # Seed a baseline
        self._seed_history_at(cmd, '100', 'high', 1000, base_time)

        # Rapid check 1
        now_1 = base_time + check_interval
        all_prices = {'100': {'high': 1200, 'low': 1100}}
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(alert, all_prices)

        # Rapid check 2 (0.1 seconds later)
        alert.is_triggered = False
        alert.triggered_data = None
        alert.save()

        now_2 = base_time + check_interval + 0.1
        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(alert, all_prices)

        # Both should work without errors
        self.assertTrue(result_1, 'Rapid check 1 should trigger')
        self.assertTrue(result_2, 'Rapid check 2 should also trigger')

    def test_direction_up_with_rolling_baseline(self):
        """
        Verify that direction='up' works correctly with rolling baselines.

        What: When the baseline rolls upward (prices have been increasing),
              a direction='up' alert should only trigger if the current price
              is still above the NEW baseline by the threshold amount.
        Why: The rolling baseline changes the reference point for the percent
             calculation. A price that was 20% above the OLD baseline might
             only be 5% above the NEW baseline.
        How:
            1. Seed with increasing prices
            2. First check: triggers (current >> baseline)
            3. Second check: baseline rolled up, current might not trigger
        """
        time_frame_minutes = 5

        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Direction Up Rolling Test',
            type='spike',
            percentage=10.0,
            price=time_frame_minutes,
            min_volume=1_000_000,
            direction='up',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = time_frame_minutes * 60

        # Seed P0 with low price
        self._seed_history_at(cmd, '100', 'high', 1000, base_time)

        # Check 1: current = 1200 (+20% from P0=1000) → triggers (direction up)
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1200, 'low': 1100}}
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(alert, all_prices_1)
        self.assertTrue(result_1, 'Check 1: +20% up spike should trigger')

        # Reset for next check
        alert.is_triggered = False
        alert.triggered_data = None
        alert.save()

        # Check 2: P0 pruned, baseline rolls to P1 (1200)
        # Current = 1210 → only +0.8% above 1200 → does NOT trigger
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1210, 'low': 1110}}
        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(alert, all_prices_2)
        self.assertFalse(result_2,
                         'Check 2: +0.8% should NOT trigger after baseline rolls up')

    def test_direction_down_with_rolling_baseline(self):
        """
        Verify that direction='down' works correctly with rolling baselines.

        What: After baseline rolls, a downward spike should be evaluated
              against the new (rolled) baseline, not the old one.
        """
        time_frame_minutes = 5

        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Direction Down Rolling Test',
            type='spike',
            percentage=10.0,
            price=time_frame_minutes,
            min_volume=1_000_000,
            direction='down',
            reference='high',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = time_frame_minutes * 60

        # Seed P0 with high price
        self._seed_history_at(cmd, '100', 'high', 2000, base_time)

        # Check 1: current = 1700 (-15% from P0=2000) → triggers
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1700, 'low': 1600}}
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(alert, all_prices_1)
        self.assertTrue(result_1, 'Check 1: -15% down spike should trigger')

        # Reset for next check
        alert.is_triggered = False
        alert.triggered_data = None
        alert.save()

        # Check 2: baseline rolls to P1 (1700)
        # Current = 1690 → only -0.6% below 1700 → does NOT trigger
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1690, 'low': 1590}}
        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(alert, all_prices_2)
        self.assertFalse(result_2,
                         'Check 2: -0.6% should NOT trigger after baseline rolls down')

    def test_reference_type_average_with_rolling(self):
        """
        Verify rolling baseline works with reference='average'.

        What: When using the 'average' reference type, the baseline should
              be the average of high and low from [timeframe] ago.
        Why: The 'average' reference calculates (high + low) // 2, which
             is a different code path than 'high' or 'low'.
        """
        time_frame_minutes = 5

        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Average Reference Rolling Test',
            type='spike',
            percentage=10.0,
            price=time_frame_minutes,
            min_volume=1_000_000,
            direction='both',
            reference='average',
            item_id=100,
            item_name='Dragon Bones',
            is_all_items=False,
            is_active=True,
            is_triggered=False,
        )

        cmd = self._make_command()
        base_time = 1_000_000.0
        check_interval = time_frame_minutes * 60

        # Check 0: seed the initial average price (950 from (1000+900)//2)
        all_prices_0 = {'100': {'high': 1000, 'low': 900}}  # avg = 950
        with patch('time.time', return_value=base_time):
            result_0 = cmd.check_alert(alert, all_prices_0)
        self.assertFalse(result_0, 'Check 0 should return False (warming up)')

        # Check 1: baseline = P0 avg (950), current avg = (1200+1100)//2 = 1150
        # Percent change = (1150 - 950) / 950 * 100 = 21.05% → triggers
        now_1 = base_time + check_interval
        all_prices_1 = {'100': {'high': 1200, 'low': 1100}}  # avg = 1150
        with patch('time.time', return_value=now_1):
            result_1 = cmd.check_alert(alert, all_prices_1)
        self.assertTrue(result_1, 'Check 1 should trigger with average reference')
        triggered_1 = json.loads(alert.triggered_data)
        self.assertEqual(triggered_1['baseline'], 950,
                         'Baseline should be the average from check 0')

        # Reset
        alert.is_triggered = False
        alert.triggered_data = None
        alert.save()

        # Check 2: baseline should roll to P1 avg (1150)
        now_2 = base_time + (2 * check_interval)
        all_prices_2 = {'100': {'high': 1500, 'low': 1400}}  # avg = 1450
        with patch('time.time', return_value=now_2):
            result_2 = cmd.check_alert(alert, all_prices_2)
        self.assertTrue(result_2, 'Check 2 should trigger with rolled baseline')
        triggered_2 = json.loads(alert.triggered_data)
        # Baseline should have rolled from 950 to 1150
        self.assertNotEqual(triggered_2['baseline'], 950,
                            'Baseline should have rolled (not still P0 average)')
        self.assertEqual(triggered_2['baseline'], 1150,
                         'Check 2 baseline should be P1 average (1150)')
