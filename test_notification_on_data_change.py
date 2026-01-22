"""
Test: Notification appears when triggered_data values change (same items, different values)

What: Verifies that a notification is shown when a spread alert's triggered_data has
      the same items but with different high/low/spread values.
      
Why: Users should be notified when market data changes, even if the same items are 
     triggering. A change in spread percentage or price values is meaningful information.
     
How: 
    1. Create a multi-item spread alert with show_notification=True
    2. Simulate initial trigger with specific high/low/spread values
    3. Dismiss the notification (is_dismissed=True)
    4. Simulate another check where same items trigger but with different values
    5. Verify is_dismissed is reset to False (notification would appear)
"""
import os
import sys
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Website.settings')
import django
django.setup()

from django.test import TestCase
from django.contrib.auth.models import User
from Website.models import Alert
from Website.management.commands.check_alerts import Command


class SpreadAlertNotificationChangeTest(TestCase):
    """
    Test that notifications appear when triggered_data values change,
    even when the same items are present in both old and new data.
    """
    
    def setUp(self):
        """
        Set up test fixtures.
        
        Creates:
            - test_user: A test user for the alert
            - cmd: Instance of the check_alerts Command for testing
        """
        self.test_user = User.objects.create_user(
            username='test_notification_user',
            password='testpass123'
        )
        self.cmd = Command()
        self.cmd.stdout = sys.stdout
    
    def tearDown(self):
        """Clean up test data after each test."""
        Alert.objects.filter(user=self.test_user).delete()
        self.test_user.delete()
    
    def test_notification_shown_when_spread_values_change(self):
        """
        Test: Notification appears when spread values change for same items.
        
        Scenario:
            - Alert has items A, B, C triggered with spreads 5%, 3%, 2%
            - User dismisses notification
            - Next check: same items A, B, C but spreads are now 6%, 4%, 2.5%
            - Expected: is_dismissed should be False (notification re-appears)
        """
        # Create a multi-item spread alert
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Spread Change Notification',
            type='spread',
            percentage=1.0,  # 1% threshold
            is_all_items=False,
            item_ids='[100, 200, 300]',  # Three test items
            item_id=100,
            item_name='Test Item 1',
            is_active=True,
            is_triggered=True,
            show_notification=True,
            is_dismissed=False
        )
        
        # Set initial triggered_data with specific values
        initial_data = [
            {'item_id': '100', 'item_name': 'Test Item 1', 'high': 1050, 'low': 1000, 'spread': 5.0},
            {'item_id': '200', 'item_name': 'Test Item 2', 'high': 1030, 'low': 1000, 'spread': 3.0},
            {'item_id': '300', 'item_name': 'Test Item 3', 'high': 1020, 'low': 1000, 'spread': 2.0},
        ]
        alert.triggered_data = json.dumps(initial_data)
        alert.save()
        
        # Simulate user dismissing the notification
        alert.is_dismissed = True
        alert.save()
        
        # Verify alert is dismissed
        self.assertTrue(alert.is_dismissed, "Alert should be dismissed before re-trigger")
        
        # New data: SAME items but DIFFERENT spread/high/low values
        new_triggered_items = [
            {'item_id': '100', 'item_name': 'Test Item 1', 'high': 1060, 'low': 1000, 'spread': 6.0},  # Changed
            {'item_id': '200', 'item_name': 'Test Item 2', 'high': 1040, 'low': 1000, 'spread': 4.0},  # Changed
            {'item_id': '300', 'item_name': 'Test Item 3', 'high': 1025, 'low': 1000, 'spread': 2.5},  # Changed
        ]
        
        # Verify _has_triggered_data_changed detects the change
        data_changed = self.cmd._has_triggered_data_changed(alert.triggered_data, new_triggered_items)
        self.assertTrue(data_changed, "_has_triggered_data_changed should return True when spread values change")
        
        # Run the handler (simulating what happens during check_alert)
        self.cmd._handle_multi_item_spread_trigger(alert, new_triggered_items)
        
        # Refresh from database
        alert.refresh_from_db()
        
        # Verify notification would appear (is_dismissed should be False)
        self.assertFalse(alert.is_dismissed, "is_dismissed should be False when data changes - notification should appear")
        
        # Verify triggered_data was updated with new values
        updated_data = json.loads(alert.triggered_data)
        self.assertEqual(updated_data[0]['spread'], 6.0, "Spread should be updated to new value")
        self.assertEqual(updated_data[0]['high'], 1060, "High price should be updated to new value")
        
        print("✓ PASS: Notification shown when spread values change for same items")
    
    def test_notification_shown_when_high_price_changes(self):
        """
        Test: Notification appears when only high price changes (spread stays same due to rounding).
        
        Scenario:
            - Alert has item A with high=1050, low=1000, spread=5.0%
            - User dismisses notification
            - Next check: same item A but high=1051 (spread rounds to same 5.1% vs 5.0%)
            - Expected: is_dismissed should be False because high value changed
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test High Price Change',
            type='spread',
            percentage=1.0,
            is_all_items=False,
            item_ids='[100]',
            item_id=100,
            item_name='Test Item',
            is_active=True,
            is_triggered=True,
            show_notification=True,
            is_dismissed=False
        )
        
        # Initial data
        initial_data = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1050, 'low': 1000, 'spread': 5.0},
        ]
        alert.triggered_data = json.dumps(initial_data)
        alert.is_dismissed = True
        alert.save()
        
        # New data: only high price changed
        new_triggered_items = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1055, 'low': 1000, 'spread': 5.5},
        ]
        
        # Verify change is detected
        data_changed = self.cmd._has_triggered_data_changed(alert.triggered_data, new_triggered_items)
        self.assertTrue(data_changed, "Should detect high price change")
        
        # Run handler
        self.cmd._handle_multi_item_spread_trigger(alert, new_triggered_items)
        alert.refresh_from_db()
        
        # Verify notification appears
        self.assertFalse(alert.is_dismissed, "Notification should appear when high price changes")
        
        print("✓ PASS: Notification shown when high price changes")
    
    def test_notification_shown_when_low_price_changes(self):
        """
        Test: Notification appears when only low price changes.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Low Price Change',
            type='spread',
            percentage=1.0,
            is_all_items=False,
            item_ids='[100]',
            item_id=100,
            item_name='Test Item',
            is_active=True,
            is_triggered=True,
            show_notification=True,
            is_dismissed=False
        )
        
        # Initial data
        initial_data = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1050, 'low': 1000, 'spread': 5.0},
        ]
        alert.triggered_data = json.dumps(initial_data)
        alert.is_dismissed = True
        alert.save()
        
        # New data: only low price changed
        new_triggered_items = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1050, 'low': 995, 'spread': 5.53},
        ]
        
        # Verify change is detected
        data_changed = self.cmd._has_triggered_data_changed(alert.triggered_data, new_triggered_items)
        self.assertTrue(data_changed, "Should detect low price change")
        
        # Run handler
        self.cmd._handle_multi_item_spread_trigger(alert, new_triggered_items)
        alert.refresh_from_db()
        
        # Verify notification appears
        self.assertFalse(alert.is_dismissed, "Notification should appear when low price changes")
        
        print("✓ PASS: Notification shown when low price changes")
    
    def test_no_notification_when_data_identical(self):
        """
        Test: No notification when triggered_data is identical.
        
        Scenario:
            - Alert triggers with specific values
            - User dismisses notification
            - Next check: exact same data
            - Expected: is_dismissed should stay True (no notification)
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test No Change',
            type='spread',
            percentage=1.0,
            is_all_items=False,
            item_ids='[100, 200]',
            item_id=100,
            item_name='Test Item 1',
            is_active=True,
            is_triggered=True,
            show_notification=True,
            is_dismissed=False
        )
        
        # Initial data
        initial_data = [
            {'item_id': '100', 'item_name': 'Test Item 1', 'high': 1050, 'low': 1000, 'spread': 5.0},
            {'item_id': '200', 'item_name': 'Test Item 2', 'high': 1030, 'low': 1000, 'spread': 3.0},
        ]
        alert.triggered_data = json.dumps(initial_data)
        alert.is_dismissed = True
        alert.save()
        
        # New data: IDENTICAL to initial
        new_triggered_items = [
            {'item_id': '100', 'item_name': 'Test Item 1', 'high': 1050, 'low': 1000, 'spread': 5.0},
            {'item_id': '200', 'item_name': 'Test Item 2', 'high': 1030, 'low': 1000, 'spread': 3.0},
        ]
        
        # Verify no change detected
        data_changed = self.cmd._has_triggered_data_changed(alert.triggered_data, new_triggered_items)
        self.assertFalse(data_changed, "Should NOT detect change when data is identical")
        
        # Run handler
        self.cmd._handle_multi_item_spread_trigger(alert, new_triggered_items)
        alert.refresh_from_db()
        
        # Verify notification does NOT appear (is_dismissed stays True)
        self.assertTrue(alert.is_dismissed, "is_dismissed should stay True when data is identical")
        
        print("✓ PASS: No notification when data is identical")
    
    def test_no_notification_when_show_notification_disabled(self):
        """
        Test: No notification when show_notification is False, even with data changes.
        
        Scenario:
            - Alert has show_notification=False
            - Data changes
            - Expected: is_dismissed should stay True (no notification regardless of changes)
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Notifications Disabled',
            type='spread',
            percentage=1.0,
            is_all_items=False,
            item_ids='[100]',
            item_id=100,
            item_name='Test Item',
            is_active=True,
            is_triggered=True,
            show_notification=False,  # Notifications disabled
            is_dismissed=True
        )
        
        # Initial data
        initial_data = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1050, 'low': 1000, 'spread': 5.0},
        ]
        alert.triggered_data = json.dumps(initial_data)
        alert.save()
        
        # New data: values changed
        new_triggered_items = [
            {'item_id': '100', 'item_name': 'Test Item', 'high': 1100, 'low': 1000, 'spread': 10.0},
        ]
        
        # Verify change IS detected by the function
        data_changed = self.cmd._has_triggered_data_changed(alert.triggered_data, new_triggered_items)
        self.assertTrue(data_changed, "Data change should still be detected")
        
        # Run handler
        self.cmd._handle_multi_item_spread_trigger(alert, new_triggered_items)
        alert.refresh_from_db()
        
        # Verify notification does NOT appear because show_notification=False
        self.assertTrue(alert.is_dismissed, "is_dismissed should stay True when show_notification=False")
        
        # But triggered_data should still be updated
        updated_data = json.loads(alert.triggered_data)
        self.assertEqual(updated_data[0]['spread'], 10.0, "Data should still be updated even without notification")
        
        print("✓ PASS: No notification when show_notification is disabled")


if __name__ == '__main__':
    import unittest
    
    # Create a test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(SpreadAlertNotificationChangeTest)
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
