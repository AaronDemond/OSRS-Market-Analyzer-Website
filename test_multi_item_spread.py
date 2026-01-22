"""
Test cases for multi-item spread alerts (item_ids field).

What: Tests for spread alerts that monitor specific multiple items instead of all items or a single item
Why: Ensures the new item_ids field works correctly for spread alert triggering and deactivation
How: Uses Django's TestCase with mocked price data to test various scenarios

Test Scenarios:
1. Multi-item spread alert with some items triggering (partial trigger)
2. Multi-item spread alert with all items triggering (full trigger - deactivation)
3. Multi-item spread alert with no items triggering
4. Alert string representation with item_ids
5. Triggered text display with item_ids

Running the tests:
    python manage.py test test_multi_item_spread --verbosity=2

Or run specific test:
    python manage.py test test_multi_item_spread.MultiItemSpreadAlertTests.test_partial_trigger --verbosity=2
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from Website.models import Alert


class MultiItemSpreadAlertTests(TestCase):
    """
    Test suite for multi-item spread alerts using the item_ids field.
    
    What: Tests the new functionality allowing spread alerts to monitor multiple specific items
    Why: Validates that partial/full triggering and deactivation logic works correctly
    How: Creates test alerts with item_ids and simulates price data to test triggering
    """
    
    def setUp(self):
        """
        Set up test fixtures before each test method.
        
        What: Creates a test user and base alert configuration
        Why: Provides consistent starting state for all tests
        How: Creates User and Alert instances with item_ids set
        """
        # test_user: Django User instance for associating alerts
        self.test_user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # item_ids_list: List of item IDs that the test alert will monitor
        # Using fake item IDs for testing purposes
        self.item_ids_list = [123, 456, 789]
        
        # test_alert: Alert instance configured for multi-item spread monitoring
        self.test_alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Multi-Item Spread',
            type='spread',
            percentage=5.0,  # 5% spread threshold
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Test Item',  # First item name for display
            item_id=123,  # First item ID for backwards compatibility
            is_active=True,
            is_triggered=False
        )
    
    def test_alert_creation_with_item_ids(self):
        """
        Test that alerts can be created with the item_ids field.
        
        What: Verifies that item_ids is properly stored and retrievable
        Why: Ensures the model field works correctly
        How: Create alert, fetch from DB, verify item_ids content
        """
        # Fetch the alert fresh from the database
        alert = Alert.objects.get(id=self.test_alert.id)
        
        # Verify item_ids is stored correctly
        self.assertIsNotNone(alert.item_ids)
        
        # stored_ids: List of item IDs parsed from the JSON field
        stored_ids = json.loads(alert.item_ids)
        self.assertEqual(stored_ids, self.item_ids_list)
        self.assertEqual(len(stored_ids), 3)
    
    def test_alert_str_with_item_ids(self):
        """
        Test the __str__ method for alerts with item_ids.
        
        What: Verifies the string representation shows item count correctly
        Why: Ensures alerts are displayed properly in admin and logs
        How: Check __str__ output contains item count
        """
        alert_str = str(self.test_alert)
        
        # Should show "3 items spread >= 5.0%"
        self.assertIn('3 items', alert_str)
        self.assertIn('spread', alert_str)
        self.assertIn('5.0%', alert_str)
    
    def test_triggered_text_with_item_ids(self):
        """
        Test the triggered_text method when some items have triggered.
        
        What: Verifies triggered text shows triggered/total item counts
        Why: Users need to know how many items have triggered vs total
        How: Set triggered_data with partial items, check triggered_text output
        """
        # Simulate partial trigger - 2 out of 3 items triggered
        triggered_data = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.5},
            {'item_id': '456', 'item_name': 'Item 2', 'spread': 5.5}
        ]
        self.test_alert.triggered_data = json.dumps(triggered_data)
        self.test_alert.is_triggered = True
        self.test_alert.save()
        
        triggered_text = self.test_alert.triggered_text()
        
        # Should show "2/3 items"
        self.assertIn('2/3', triggered_text)
        self.assertIn('Click for details', triggered_text)
    
    def test_check_spread_for_item_ids_partial_trigger(self):
        """
        Test _check_spread_for_item_ids when some items meet the threshold.
        
        What: Verifies that only items meeting the spread threshold are returned
        Why: Ensures accurate triggering based on individual item spreads
        How: Mock price data where 2/3 items have high spread, verify result
        """
        # Import the Command class to access the check method
        from check_alerts import Command
        
        # cmd: Instance of the check_alerts Command for calling check methods
        cmd = Command()
        
        # all_prices: Simulated price data from the API
        # Items 123 and 456 have 6%+ spread (above 5% threshold)
        # Item 789 has 3% spread (below threshold)
        all_prices = {
            '123': {'high': 106, 'low': 100},  # 6% spread
            '456': {'high': 110, 'low': 100},  # 10% spread  
            '789': {'high': 103, 'low': 100},  # 3% spread (below threshold)
        }
        
        # Mock the item mapping
        cmd.item_mapping = {
            '123': 'Test Item 1',
            '456': 'Test Item 2',
            '789': 'Test Item 3'
        }
        
        # Call the check method
        result = cmd._check_spread_for_item_ids(self.test_alert, all_prices)
        
        # Should return list of 2 triggered items (items 123 and 456)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        
        # Verify the triggered items are correct
        triggered_ids = [item['item_id'] for item in result]
        self.assertIn('123', triggered_ids)
        self.assertIn('456', triggered_ids)
        self.assertNotIn('789', triggered_ids)
    
    def test_check_spread_for_item_ids_all_trigger(self):
        """
        Test _check_spread_for_item_ids when all items meet the threshold.
        
        What: Verifies all items are returned when all meet the spread threshold
        Why: This is the condition for full deactivation of the alert
        How: Mock price data where all items have high spread
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # all_prices: All items have spread above 5% threshold
        all_prices = {
            '123': {'high': 106, 'low': 100},  # 6% spread
            '456': {'high': 110, 'low': 100},  # 10% spread
            '789': {'high': 108, 'low': 100},  # 8% spread
        }
        
        cmd.item_mapping = {
            '123': 'Test Item 1',
            '456': 'Test Item 2',
            '789': 'Test Item 3'
        }
        
        result = cmd._check_spread_for_item_ids(self.test_alert, all_prices)
        
        # Should return all 3 items
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)
    
    def test_check_spread_for_item_ids_no_trigger(self):
        """
        Test _check_spread_for_item_ids when no items meet the threshold.
        
        What: Verifies False is returned when no items have sufficient spread
        Why: Alert should not trigger if no items meet the condition
        How: Mock price data where all items have low spread
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # all_prices: All items have spread below 5% threshold
        all_prices = {
            '123': {'high': 102, 'low': 100},  # 2% spread
            '456': {'high': 103, 'low': 100},  # 3% spread
            '789': {'high': 101, 'low': 100},  # 1% spread
        }
        
        cmd.item_mapping = {
            '123': 'Test Item 1',
            '456': 'Test Item 2',
            '789': 'Test Item 3'
        }
        
        result = cmd._check_spread_for_item_ids(self.test_alert, all_prices)
        
        # Should return False - no items triggered
        self.assertFalse(result)
    
    def test_handle_multi_item_spread_partial_stays_active(self):
        """
        Test that multi-item spread alerts stay active when only some items trigger.
        
        What: Verifies alert remains active until ALL items have triggered
        Why: User specified they want to know when ALL items reach the threshold
        How: Simulate partial trigger, verify is_active remains True
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()  # Capture output
        
        # triggered_items: Only 2 of 3 items triggered
        triggered_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'high': 110, 'low': 100, 'spread': 10.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items)
        
        # Refresh from database
        self.test_alert.refresh_from_db()
        
        # Alert should still be active (not all items triggered)
        self.assertTrue(self.test_alert.is_active)
        self.assertTrue(self.test_alert.is_triggered)
        
        # triggered_data should contain the 2 triggered items
        triggered_data = json.loads(self.test_alert.triggered_data)
        self.assertEqual(len(triggered_data), 2)
    
    def test_handle_multi_item_spread_all_triggers_deactivates(self):
        """
        Test that multi-item spread alerts deactivate when all items trigger.
        
        What: Verifies alert deactivates (is_active=False) when ALL items trigger
        Why: Alert has fulfilled its purpose - all items met the condition
        How: Simulate all items triggering, verify is_active becomes False
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()  # Capture output
        
        # triggered_items: All 3 items triggered
        triggered_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'high': 110, 'low': 100, 'spread': 10.0},
            {'item_id': '789', 'item_name': 'Item 3', 'high': 108, 'low': 100, 'spread': 8.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items)
        
        # Refresh from database
        self.test_alert.refresh_from_db()
        
        # Alert should be deactivated (all items triggered)
        self.assertFalse(self.test_alert.is_active)
        self.assertTrue(self.test_alert.is_triggered)
        
        # triggered_data should contain all 3 items
        triggered_data = json.loads(self.test_alert.triggered_data)
        self.assertEqual(len(triggered_data), 3)
    
    def test_invalid_item_ids_json(self):
        """
        Test handling of invalid JSON in item_ids field.
        
        What: Verifies graceful handling of malformed item_ids JSON
        Why: Prevents crashes from corrupted data
        How: Set invalid JSON, verify check returns False without error
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # Set invalid JSON
        self.test_alert.item_ids = 'not valid json'
        self.test_alert.save()
        
        all_prices = {
            '123': {'high': 110, 'low': 100}
        }
        
        cmd.item_mapping = {'123': 'Test Item'}
        
        # Should return False without raising exception
        result = cmd._check_spread_for_item_ids(self.test_alert, all_prices)
        self.assertFalse(result)
    
    def test_empty_item_ids_list(self):
        """
        Test handling of empty item_ids list.
        
        What: Verifies check returns False for empty item_ids
        Why: No items to check means no trigger possible
        How: Set empty list, verify False returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        self.test_alert.item_ids = json.dumps([])
        self.test_alert.save()
        
        all_prices = {
            '123': {'high': 110, 'low': 100}
        }
        
        cmd.item_mapping = {'123': 'Test Item'}
        
        result = cmd._check_spread_for_item_ids(self.test_alert, all_prices)
        self.assertFalse(result)


class SingleItemSpreadAlertTests(TestCase):
    """
    Regression tests to ensure single-item spread alerts still work correctly.
    
    What: Tests that existing single-item spread alert functionality is not broken
    Why: The new item_ids feature should not affect existing behavior
    How: Tests standard single-item spread alerts without item_ids field
    """
    
    def setUp(self):
        """Set up test fixtures for single-item tests."""
        self.test_user = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123'
        )
        
        # single_item_alert: Traditional single-item spread alert (no item_ids)
        self.single_item_alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Single Item Spread',
            type='spread',
            percentage=5.0,
            is_all_items=False,
            item_ids=None,  # No item_ids - single item alert
            item_name='Test Item',
            item_id=123,
            is_active=True,
            is_triggered=False
        )
    
    def test_single_item_spread_str(self):
        """Test __str__ for single item spread (no item_ids)."""
        alert_str = str(self.single_item_alert)
        
        # Should show item name, not item count
        self.assertIn('Test Item', alert_str)
        self.assertIn('spread', alert_str)
    
    def test_single_item_spread_triggered_text(self):
        """Test triggered_text for single item spread."""
        self.single_item_alert.is_triggered = True
        
        triggered_text = self.single_item_alert.triggered_text()
        
        # Should show item name
        self.assertIn('Test Item', triggered_text)
        self.assertIn('spread', triggered_text)
    
    def test_check_alert_single_item_triggers(self):
        """Test check_alert for single item spread that triggers."""
        from check_alerts import Command
        
        cmd = Command()
        
        # Price data with spread above threshold
        all_prices = {
            '123': {'high': 110, 'low': 100}  # 10% spread
        }
        
        cmd.item_mapping = {'123': 'Test Item'}
        
        result = cmd.check_alert(self.single_item_alert, all_prices)
        
        # Should return True for single item trigger
        self.assertTrue(result)
    
    def test_check_alert_single_item_no_trigger(self):
        """Test check_alert for single item spread that doesn't trigger."""
        from check_alerts import Command
        
        cmd = Command()
        
        # Price data with spread below threshold
        all_prices = {
            '123': {'high': 102, 'low': 100}  # 2% spread
        }
        
        cmd.item_mapping = {'123': 'Test Item'}
        
        result = cmd.check_alert(self.single_item_alert, all_prices)
        
        # Should return False
        self.assertFalse(result)


class TriggeredDataChangeDetectionTests(TestCase):
    """
    Test suite for detecting changes in triggered data.
    
    What: Tests the _has_triggered_data_changed method and notification behavior
    Why: Ensures notifications are only sent when data meaningfully changes
    How: Creates test scenarios for same data, new items, removed items, and spread changes
    """
    
    def setUp(self):
        """
        Set up test fixtures for change detection tests.
        
        What: Creates a test user and multi-item spread alert
        Why: Provides consistent starting state for change detection tests
        How: Creates User and Alert instances with item_ids set
        """
        self.test_user = User.objects.create_user(
            username='testuser_change',
            email='change@example.com',
            password='testpass123'
        )
        
        # item_ids_list: List of item IDs for testing
        self.item_ids_list = [123, 456, 789]
        
        # test_alert: Multi-item spread alert for testing change detection
        self.test_alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Change Detection',
            type='spread',
            percentage=5.0,
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Test Item',
            item_id=123,
            is_active=True,
            is_triggered=False,
            email_notification=True  # Enable notifications for testing
        )
    
    def test_has_triggered_data_changed_no_previous_data(self):
        """
        Test that first trigger is always detected as a change.
        
        What: Verifies that when there's no previous triggered_data, any trigger is a change
        Why: First trigger should always notify the user
        How: Call with None as old_data, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # new_items: First batch of triggered items
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        
        # No previous data - should detect as change
        result = cmd._has_triggered_data_changed(None, new_items)
        self.assertTrue(result)
        
        # Empty string should also be treated as no previous data
        result = cmd._has_triggered_data_changed('', new_items)
        self.assertTrue(result)
    
    def test_has_triggered_data_changed_same_data(self):
        """
        Test that identical data is not detected as a change.
        
        What: Verifies that same items with same spreads don't trigger notification
        Why: Prevents spam when data doesn't change between checks
        How: Use same item list for old and new, verify False returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: Previously triggered items
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'spread': 7.5}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Same items with same spreads
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'spread': 7.5}
        ]
        
        # Same data - should NOT detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertFalse(result)
    
    def test_has_triggered_data_changed_new_item_added(self):
        """
        Test that a new item triggering is detected as a change.
        
        What: Verifies that when a new item meets the threshold, it's detected
        Why: User should be notified when more items start meeting the threshold
        How: Add new item to the list, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: One item was triggered
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Two items now triggered (item 456 is new)
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'spread': 7.5}
        ]
        
        # New item added - should detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertTrue(result)
    
    def test_has_triggered_data_changed_item_removed(self):
        """
        Test that an item no longer meeting threshold is detected as a change.
        
        What: Verifies that when an item drops below threshold, it's detected
        Why: User should know when items stop meeting the condition
        How: Remove item from new list, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: Two items were triggered
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'spread': 7.5}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Only one item still triggered (item 456 dropped out)
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        
        # Item removed - should detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertTrue(result)
    
    def test_has_triggered_data_changed_spread_increased(self):
        """
        Test that a spread value increase is detected as a change.
        
        What: Verifies that when an item's spread increases, it's detected
        Why: User may want to know spread is getting bigger (more profit potential)
        How: Increase spread value in new data, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: Item had 6% spread
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Item now has 8% spread (increased)
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 8.0}
        ]
        
        # Spread increased - should detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertTrue(result)
    
    def test_has_triggered_data_changed_spread_decreased(self):
        """
        Test that a spread value decrease is detected as a change.
        
        What: Verifies that when an item's spread decreases, it's detected
        Why: User should know spread is shrinking (less profit potential)
        How: Decrease spread value in new data, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: Item had 8% spread
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 8.0}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Item now has 5.5% spread (decreased but still above threshold)
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 5.5}
        ]
        
        # Spread decreased - should detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertTrue(result)
    
    def test_has_triggered_data_changed_minor_float_difference(self):
        """
        Test that minor floating point differences (rounding) don't cause false changes.
        
        What: Verifies that 6.00 and 6.001 are treated as same (after rounding)
        Why: Floating point precision issues shouldn't cause spam notifications
        How: Use values that differ only in insignificant decimal places
        """
        from check_alerts import Command
        
        cmd = Command()
        
        # old_items: Spread at 6.0
        old_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        old_data_json = json.dumps(old_items)
        
        # new_items: Spread at 6.001 (essentially the same after rounding to 2 decimals)
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.001}
        ]
        
        # Minor float difference - should NOT detect as change
        result = cmd._has_triggered_data_changed(old_data_json, new_items)
        self.assertFalse(result)
    
    def test_has_triggered_data_changed_invalid_old_json(self):
        """
        Test that invalid old JSON is treated as having no previous data.
        
        What: Verifies graceful handling of corrupted old triggered_data
        Why: Prevents crashes and ensures new data is still processed
        How: Pass invalid JSON as old data, verify True returned
        """
        from check_alerts import Command
        
        cmd = Command()
        
        new_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'spread': 6.0}
        ]
        
        # Invalid JSON should be treated as no previous data
        result = cmd._has_triggered_data_changed('not valid json', new_items)
        self.assertTrue(result)
        
        # Non-list JSON should also be treated as invalid
        result = cmd._has_triggered_data_changed('{"foo": "bar"}', new_items)
        self.assertTrue(result)
    
    def test_handle_multi_item_no_notification_when_unchanged(self):
        """
        Test that no notification is sent when triggered data doesn't change.
        
        What: Verifies email notification is NOT sent when same items keep triggering
        Why: Prevents email spam when nothing meaningful has changed
        How: Trigger with same data twice, verify is_dismissed stays True after second
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()
        
        # First trigger - set initial triggered data
        triggered_items = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'high': 110, 'low': 100, 'spread': 10.0}
        ]
        
        # First trigger - should set is_dismissed = False
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items)
        self.test_alert.refresh_from_db()
        self.assertFalse(self.test_alert.is_dismissed)
        
        # Simulate user dismissing the alert
        self.test_alert.is_dismissed = True
        self.test_alert.save()
        
        # Second trigger with SAME data - should NOT reset is_dismissed
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items)
        self.test_alert.refresh_from_db()
        
        # is_dismissed should STAY True because data didn't change
        self.assertTrue(self.test_alert.is_dismissed)
    
    def test_handle_multi_item_notification_when_spread_changes(self):
        """
        Test that notification IS sent when spread values change.
        
        What: Verifies is_dismissed is reset when spread values change
        Why: User should be notified when spread increases/decreases
        How: Trigger with changed spread, verify is_dismissed reset to False
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()
        
        # First trigger
        triggered_items_v1 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v1)
        self.test_alert.refresh_from_db()
        
        # Simulate user dismissing
        self.test_alert.is_dismissed = True
        self.test_alert.save()
        
        # Second trigger with DIFFERENT spread (8% instead of 6%)
        triggered_items_v2 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 108, 'low': 100, 'spread': 8.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v2)
        self.test_alert.refresh_from_db()
        
        # is_dismissed should be reset because data changed
        self.assertFalse(self.test_alert.is_dismissed)
    
    def test_handle_multi_item_notification_when_new_item_triggers(self):
        """
        Test that notification IS sent when a new item starts triggering.
        
        What: Verifies is_dismissed is reset when new item meets threshold
        Why: User should know when more items start meeting the condition
        How: Trigger with additional item, verify is_dismissed reset to False
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()
        
        # First trigger with one item
        triggered_items_v1 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v1)
        self.test_alert.refresh_from_db()
        
        # Simulate user dismissing
        self.test_alert.is_dismissed = True
        self.test_alert.save()
        
        # Second trigger with additional item (456 now triggers too)
        triggered_items_v2 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0},
            {'item_id': '456', 'item_name': 'Item 2', 'high': 108, 'low': 100, 'spread': 8.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v2)
        self.test_alert.refresh_from_db()
        
        # is_dismissed should be reset because new item triggered
        self.assertFalse(self.test_alert.is_dismissed)
    
    def test_triggered_data_updates_with_new_values(self):
        """
        Test that triggered_data is always updated with latest spread values.
        
        What: Verifies triggered_data reflects current spreads even when no notification
        Why: User should see current spread values when viewing alert details
        How: Trigger twice with different spreads, verify triggered_data has latest
        """
        from check_alerts import Command
        from io import StringIO
        
        cmd = Command()
        cmd.stdout = StringIO()
        
        # First trigger with 6% spread
        triggered_items_v1 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 106, 'low': 100, 'spread': 6.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v1)
        self.test_alert.refresh_from_db()
        
        # Verify initial triggered_data
        data_v1 = json.loads(self.test_alert.triggered_data)
        self.assertEqual(data_v1[0]['spread'], 6.0)
        
        # Second trigger with 8% spread
        triggered_items_v2 = [
            {'item_id': '123', 'item_name': 'Item 1', 'high': 108, 'low': 100, 'spread': 8.0}
        ]
        
        cmd._handle_multi_item_spread_trigger(self.test_alert, triggered_items_v2)
        self.test_alert.refresh_from_db()
        
        # triggered_data should now have 8% spread (updated)
        data_v2 = json.loads(self.test_alert.triggered_data)
        self.assertEqual(data_v2[0]['spread'], 8.0)
