"""
Test cases for threshold alert minimum hourly volume filtering.

What: Verifies that threshold alerts respect the min_volume filter when checking triggers.
Why: The feature requires threshold alerts to only trigger when HourlyItemVolume meets
     the user-configured minimum hourly GP volume.
How: Uses Django TestCase, creates HourlyItemVolume snapshots, and calls the
     check_threshold_alert method directly with mocked price data.
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command
from Website.models import Alert, HourlyItemVolume
import os
import django



class ThresholdMinVolumeTests(TestCase):
    """
    Test suite for threshold alerts with minimum hourly volume filtering.
    
    What: Ensures the threshold alert logic respects min_volume when evaluating triggers.
    Why: Users need threshold alerts to ignore low-liquidity items even if price thresholds are met.
    How: Create a threshold alert with reference prices, then vary HourlyItemVolume to
         confirm triggering behavior with below/above volume values.
    """

    def setUp(self):
        """
        Set up shared fixtures for each test.
        
        What: Creates a test user and a threshold alert with baseline reference prices.
        Why: Provides a consistent alert configuration for each min_volume scenario.
        How: Use the Alert model with threshold_type='percentage' and a reference_prices JSON blob.
        """


        # test_user: User instance to associate alerts with a valid account
        # What: Represents the owner of the alert in the test database
        # Why: Alerts require a user foreign key when user-based logic is used
        # How: Created via Django's built-in User model
        self.test_user = User.objects.create_user(
            username='volume_user',
            email='volume_user@example.com',
            password='testpass123'
        )

        # item_id: The OSRS item ID used for this threshold alert test
        # What: Identifier for the item whose prices and volume we will simulate
        # Why: Needed to align Alert, HourlyItemVolume, and price data
        # How: Fixed numeric ID for repeatable tests
        self.item_id = 123

        # reference_price: Baseline price stored in alert.reference_prices
        # What: The price value used to calculate percentage change
        # Why: Threshold alerts need a reference to determine percentage movement
        # How: Stored in JSON under the item_id key
        reference_price = 100

        # threshold_alert: Alert instance configured for percentage-based threshold monitoring
        # What: Represents the alert being evaluated in the test cases
        # Why: Ensures min_volume is enforced for threshold alert checks
        # How: Created with threshold_type='percentage' and min_volume set
        self.threshold_alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Threshold Volume Test',
            type='threshold',
            item_name='Test Item',
            item_id=self.item_id,
            threshold_type='percentage',
            percentage=5.0,
            direction='up',
            reference='average',
            min_volume=1000,
            reference_prices=json.dumps({str(self.item_id): reference_price})
        )

    def _build_prices(self, high_price, low_price):
        """
        Build a minimal all_prices dict for check_threshold_alert.
        
        What: Constructs the all_prices structure expected by check_threshold_alert.
        Why: The alert checker expects a dict keyed by item_id strings with high/low values.
        How: Wrap the provided prices into the API-like dictionary format.
        
        Args:
            high_price: High price value for the item (instant buy).
            low_price: Low price value for the item (instant sell).
        
        Returns:
            dict: Price data keyed by the item_id as a string.
        """
        return {
            str(self.item_id): {
                'high': high_price,
                'low': low_price
            }
        }

    def _fresh_volume_timestamp(self):
        """
        Build a fresh timestamp string that passes the 130-minute (2h10m) recency window.

        What: Provides a recent timestamp for HourlyItemVolume rows in tests.
        Why: The volume recency filter should allow alerts when data is current.
        How: Use timezone.now() minus 5 minutes, then serialize to ISO-8601.

        Returns:
            str: ISO-8601 timestamp string within the recency window.
        """
        # fresh_timestamp: Recent datetime within the allowed freshness window.
        # What: Represents a "current" volume snapshot time for testing.
        # Why: Ensures min_volume checks pass when volume data is recent.
        # How: Subtract a small buffer from now to avoid boundary flakiness.
        fresh_timestamp = timezone.now() - timedelta(minutes=5)
        # fresh_timestamp_iso: ISO-8601 string to exercise parse_datetime behavior.
        # What: Matches the string format used in previous tests.
        # Why: Ensures ISO parsing is still supported by the new recency logic.
        # How: Use datetime.isoformat() to produce a standard ISO string.
        fresh_timestamp_iso = fresh_timestamp.isoformat()
        return fresh_timestamp_iso

    def _stale_volume_timestamp(self):
        """
        Build a stale timestamp string that fails the 130-minute (2h10m) recency window.

        What: Provides an intentionally old timestamp for HourlyItemVolume rows.
        Why: Validates that stale volume snapshots do NOT pass min_volume checks.
        How: Use timezone.now() minus 131 minutes, then serialize to ISO-8601.

        Returns:
            str: ISO-8601 timestamp string outside the recency window.
        """
        # stale_timestamp: Datetime intentionally older than the recency cutoff.
        # What: Represents a stale volume snapshot time for negative testing.
        # Why: Ensures the recency filter rejects old volume data.
        # How: Subtract 131 minutes to exceed the 130-minute cutoff safely.
        stale_timestamp = timezone.now() - timedelta(minutes=131)
        # stale_timestamp_iso: ISO-8601 string for the stale timestamp.
        # What: Serialized timestamp used for HourlyItemVolume creation.
        # Why: Keeps timestamp format consistent with other tests.
        # How: Use datetime.isoformat() to produce a standard ISO string.
        stale_timestamp_iso = stale_timestamp.isoformat()
        return stale_timestamp_iso

    def test_threshold_min_volume_blocks_trigger(self):
        """
        Ensure threshold alerts do not trigger when volume is below min_volume.
        
        What: Validates that low hourly volume prevents a threshold trigger.
        Why: The min_volume filter should block alerts even if price threshold is met.
        How: Create HourlyItemVolume below threshold and confirm check returns False.
        """
        # below_volume: Hourly volume value intentionally below min_volume
        # What: Simulates a low-liquidity scenario
        # Why: Ensures the min_volume filter blocks triggering
        # How: Stored in HourlyItemVolume for the alert's item_id
        below_volume = 500

        HourlyItemVolume.objects.create(
            item_id=self.item_id,
            item_name='Test Item',
            volume=below_volume,
            timestamp=self._fresh_volume_timestamp()
        )

        # all_prices: Price data that would otherwise trigger the threshold alert
        # What: Baseline 100, current average 120 => 20% increase > 5% threshold
        # Why: Ensures price condition is satisfied so volume becomes the deciding factor
        # How: Provide matching high/low values to yield average 120
        all_prices = self._build_prices(high_price=120, low_price=120)

        # command: Command instance containing threshold evaluation logic
        # What: Provides access to check_threshold_alert
        # Why: We test the real alert logic without running the full loop
        # How: Instantiate the management command class directly
        command = Command()

        with patch.object(Command, 'get_item_mapping', return_value={str(self.item_id): 'Test Item'}):
            triggered = command.check_threshold_alert(self.threshold_alert, all_prices)

        self.assertFalse(triggered)

    def test_threshold_min_volume_allows_trigger(self):
        """
        Ensure threshold alerts trigger when volume meets min_volume.
        
        What: Validates that adequate hourly volume allows a threshold alert to trigger.
        Why: The min_volume filter should permit triggers when the volume is high enough.
        How: Create HourlyItemVolume above threshold and confirm check returns True.
        """
        # above_volume: Hourly volume value above min_volume
        # What: Simulates a sufficiently liquid market for the item
        # Why: Ensures the volume filter passes and threshold logic can trigger
        # How: Stored in HourlyItemVolume for the alert's item_id
        above_volume = 5000

        HourlyItemVolume.objects.create(
            item_id=self.item_id,
            item_name='Test Item',
            volume=above_volume,
            timestamp=self._fresh_volume_timestamp()
        )

        # all_prices: Price data that triggers the threshold alert
        # What: Baseline 100, current average 120 => 20% increase > 5% threshold
        # Why: Ensures the price condition is met so the alert should trigger
        # How: Provide matching high/low values to yield average 120
        all_prices = self._build_prices(high_price=120, low_price=120)

        # command: Command instance containing threshold evaluation logic
        # What: Provides access to check_threshold_alert
        # Why: We test the real alert logic without running the full loop
        # How: Instantiate the management command class directly
        command = Command()

        with patch.object(Command, 'get_item_mapping', return_value={str(self.item_id): 'Test Item'}):
            triggered = command.check_threshold_alert(self.threshold_alert, all_prices)

        self.assertTrue(triggered)

    def test_threshold_min_volume_stale_volume_blocks_trigger(self):
        """
        Ensure threshold alerts do not trigger when volume data is stale.

        What: Validates that stale HourlyItemVolume timestamps fail the recency gate.
        Why: The min_volume filter must only pass when volume data is current.
        How: Create a high-volume record with a stale timestamp and assert False.
        """
        # stale_volume: Hourly volume value above min_volume but intentionally stale.
        # What: Represents a volume snapshot that should be rejected due to age.
        # Why: Confirms the recency filter is enforced even when volume is high.
        # How: Use a value above min_volume with a stale timestamp.
        stale_volume = 5000

        HourlyItemVolume.objects.create(
            item_id=self.item_id,
            item_name='Test Item',
            volume=stale_volume,
            timestamp=self._stale_volume_timestamp()
        )

        # all_prices: Price data that would otherwise trigger the threshold alert.
        # What: Baseline 100, current average 120 => 20% increase > 5% threshold.
        # Why: Ensures the price condition is satisfied so staleness is the deciding factor.
        # How: Provide matching high/low values to yield average 120.
        all_prices = self._build_prices(high_price=120, low_price=120)

        # command: Command instance containing threshold evaluation logic.
        # What: Provides access to check_threshold_alert for the stale-volume scenario.
        # Why: We validate the real alert logic without running the full loop.
        # How: Instantiate the management command class directly.
        command = Command()

        with patch.object(Command, 'get_item_mapping', return_value={str(self.item_id): 'Test Item'}):
            triggered = command.check_threshold_alert(self.threshold_alert, all_prices)

        self.assertFalse(triggered)
