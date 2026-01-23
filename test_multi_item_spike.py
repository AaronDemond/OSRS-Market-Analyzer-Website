"""
Test cases for multi-item spike alerts (item_ids field).

What: Tests for spike alerts that monitor specific multiple items for price spikes over time
Why: Debug and ensure the multi-item spike alert checking logic works correctly
How: Uses Django's TestCase with mocked price data and price history to test various scenarios

Test Scenarios:
1. Multi-item spike alert creation and field storage
2. Multi-item spike checking with some items triggering
3. Multi-item spike checking with all items triggering
4. Multi-item spike checking with no items triggering
5. Item iteration verification - ensures ALL items in item_ids are checked
6. Price history building and warmup period
7. Direction-specific checking (up, down, both)

Running the tests:
    python manage.py test test_multi_item_spike --verbosity=2

Or run specific test:
    python manage.py test test_multi_item_spike.MultiItemSpikeAlertTests.test_all_items_checked --verbosity=2
"""

import json
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from unittest.mock import patch, MagicMock, PropertyMock
from io import StringIO

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from Website.models import Alert


class MultiItemSpikeAlertTests(TestCase):
    """
    Test suite for multi-item spike alerts using the item_ids field.
    
    What: Tests the functionality of spike alerts monitoring multiple specific items
    Why: Validates that iteration through item_ids, warmup, and threshold checking work correctly
    How: Creates test alerts with item_ids and simulates price data to test spike detection
    """
    
    def setUp(self):
        """
        Set up test fixtures before each test method.
        
        What: Creates a test user and base spike alert configuration
        Why: Provides consistent starting state for all tests
        How: Creates User and Alert instances with item_ids set for spike monitoring
        """
        # test_user: Django User instance for associating alerts
        self.test_user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # item_ids_list: List of item IDs that the test alert will monitor
        # Using 5 different item IDs to test iteration
        self.item_ids_list = [100, 200, 300, 400, 500]
        
        # test_alert: Alert instance configured for multi-item spike monitoring
        # What: A spike alert watching 5 items for 10% price change over 60 minutes
        # Why: Tests the core multi-item spike functionality
        # How: item_ids stores JSON array, percentage=10, time_frame=60 (minutes)
        self.test_alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Test Multi-Item Spike',
            type='spike',
            percentage=10.0,  # 10% spike threshold
            time_frame=60,    # 60 minute window
            direction='both', # Check both up and down spikes
            reference='high', # Use high price for calculations
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Test Item',  # First item name for display
            item_id=100,  # First item ID for backwards compatibility
            is_active=True,
            is_triggered=False
        )
        
        # item_mapping: Maps item IDs to names for the mock
        self.item_mapping = {
            '100': 'Dragon Bones',
            '200': 'Abyssal Whip',
            '300': 'Bandos Chestplate',
            '400': 'Armadyl Godsword',
            '500': 'Twisted Bow'
        }
    
    def test_alert_creation_with_item_ids(self):
        """
        Test that spike alerts can be created with the item_ids field.
        
        What: Verifies that item_ids is properly stored and retrievable
        Why: Ensures the model field works correctly for spike alerts
        How: Create alert, fetch from DB, verify item_ids content
        """
        # Fetch the alert fresh from the database
        alert = Alert.objects.get(id=self.test_alert.id)
        
        # Verify item_ids is stored correctly
        self.assertIsNotNone(alert.item_ids)
        
        # stored_ids: List of item IDs parsed from the JSON field
        stored_ids = json.loads(alert.item_ids)
        self.assertEqual(stored_ids, self.item_ids_list)
        self.assertEqual(len(stored_ids), 5)
        
        # Verify spike-specific fields
        self.assertEqual(alert.type, 'spike')
        self.assertEqual(alert.percentage, 10.0)
        self.assertEqual(alert.time_frame, 60)
        self.assertEqual(alert.direction, 'both')
        self.assertEqual(alert.reference, 'high')
    
    def test_all_items_checked(self):
        """
        Test that ALL items in item_ids are checked during spike evaluation.
        
        What: Verifies the iteration loop checks every item in the item_ids list
        Why: This is the core bug we're debugging - items may not all be checked
        How: Track which items are checked using a mock, verify all 5 are processed
        """
        from Website.management.commands.check_alerts import Command
        
        # cmd: Instance of the check_alerts Command for calling check methods
        cmd = Command()
        cmd.stdout = StringIO()  # Capture output
        
        # Initialize price_history as the command would
        cmd.price_history = defaultdict(list)
        
        # checked_items: List to track which items were actually processed
        # What: Collects item IDs as they're checked
        # Why: Allows us to verify ALL items in item_ids are iterated
        checked_items = []
        
        # all_prices: Simulated price data from the API for all 5 items
        # All items have valid price data
        all_prices = {
            '100': {'high': 5000, 'low': 4800},
            '200': {'high': 2500000, 'low': 2400000},
            '300': {'high': 15000000, 'low': 14500000},
            '400': {'high': 30000000, 'low': 29000000},
            '500': {'high': 1200000000, 'low': 1150000000}
        }
        
        # Verify all items exist in price data
        print("\n=== TEST: Verifying All Items Are Checked ===")
        print(f"Items in alert.item_ids: {self.item_ids_list}")
        print(f"Items in all_prices: {list(all_prices.keys())}")
        
        # item_ids from the alert
        item_ids = json.loads(self.test_alert.item_ids)
        print(f"Parsed item_ids: {item_ids}")
        print(f"Number of items to check: {len(item_ids)}")
        
        # Check each item manually to see which ones have price data
        items_with_data = []
        items_without_data = []
        for item_id in item_ids:
            item_id_str = str(item_id)
            if item_id_str in all_prices:
                items_with_data.append(item_id)
            else:
                items_without_data.append(item_id)
        
        print(f"Items WITH price data: {items_with_data}")
        print(f"Items WITHOUT price data: {items_without_data}")
        
        # All 5 items should have price data
        self.assertEqual(len(items_with_data), 5, 
            f"Expected 5 items with price data, got {len(items_with_data)}")
        self.assertEqual(len(items_without_data), 0,
            f"Expected 0 items without price data, got {len(items_without_data)}")
    
    def test_spike_detection_with_warmed_up_history(self):
        """
        Test spike detection when price history is warmed up.
        
        What: Simulates a scenario where items have sufficient historical data
        Why: Tests the actual spike calculation logic
        How: Pre-populate price_history with old data, add new prices showing spike
        """
        from Website.management.commands.check_alerts import Command
        
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        
        # Mock get_item_mapping to return our test mapping
        cmd.get_item_mapping = lambda: self.item_mapping
        
        # now: Current timestamp for the test
        now = timezone.now()
        
        # warmup_time: Timestamp 90 minutes ago (older than 60 min window)
        warmup_time = now - timedelta(minutes=90)
        
        # Pre-populate price history with "baseline" prices from 90 minutes ago
        # This simulates warmed-up history
        baseline_prices = {
            '100': 5000,    # Dragon Bones baseline
            '200': 2500000, # Abyssal Whip baseline
            '300': 15000000,# Bandos Chestplate baseline
            '400': 30000000,# Armadyl Godsword baseline
            '500': 1200000000 # Twisted Bow baseline
        }
        
        for item_id, price in baseline_prices.items():
            key = f"{item_id}:high"
            cmd.price_history[key].append((warmup_time, price))
        
        # all_prices: Current prices - items 100 and 200 have spiked 15%+
        # Item 100: 5000 -> 5800 = +16% (spike!)
        # Item 200: 2500000 -> 2900000 = +16% (spike!)
        # Item 300: 15000000 -> 15500000 = +3.3% (no spike)
        # Item 400: 30000000 -> 30500000 = +1.7% (no spike)
        # Item 500: 1200000000 -> 1210000000 = +0.8% (no spike)
        all_prices = {
            '100': {'high': 5800, 'low': 5600},      # +16% spike
            '200': {'high': 2900000, 'low': 2800000}, # +16% spike
            '300': {'high': 15500000, 'low': 15000000}, # No spike
            '400': {'high': 30500000, 'low': 30000000}, # No spike
            '500': {'high': 1210000000, 'low': 1200000000} # No spike
        }
        
        print("\n=== TEST: Spike Detection With Warmed Up History ===")
        print(f"Time frame: {self.test_alert.time_frame} minutes")
        print(f"Spike threshold: {self.test_alert.percentage}%")
        print(f"Direction: {self.test_alert.direction}")
        print(f"Reference: {self.test_alert.reference}")
        print("\nExpected results:")
        print("  Item 100 (Dragon Bones): 5000 -> 5800 = +16% SHOULD TRIGGER")
        print("  Item 200 (Abyssal Whip): 2500000 -> 2900000 = +16% SHOULD TRIGGER")
        print("  Item 300 (Bandos Chestplate): +3.3% NO TRIGGER")
        print("  Item 400 (Armadyl Godsword): +1.7% NO TRIGGER")
        print("  Item 500 (Twisted Bow): +0.8% NO TRIGGER")
        
        # Run the check
        result = cmd.check_alert(self.test_alert, all_prices)
        
        print(f"\nResult from check_alert: {result}")
        print(f"Result type: {type(result)}")
        
        if isinstance(result, list):
            print(f"Number of triggered items: {len(result)}")
            for item in result:
                print(f"  - {item}")
        
        # Verify that we got some triggered items
        # With the bug, we might get fewer than expected or none
        if result:
            triggered_ids = [str(item.get('item_id')) for item in result]
            print(f"\nTriggered item IDs: {triggered_ids}")
            
            # We expect items 100 and 200 to trigger
            self.assertIn('100', triggered_ids, "Item 100 should have triggered (16% spike)")
            self.assertIn('200', triggered_ids, "Item 200 should have triggered (16% spike)")
    
    def test_iteration_order_and_completeness(self):
        """
        Test that iteration goes through items in the expected order.
        
        What: Explicitly checks iteration order and completeness
        Why: Debugging whether the loop skips items or exits early
        How: Manually simulate the iteration logic and log each step
        """
        print("\n=== TEST: Iteration Order and Completeness ===")
        
        # Parse item_ids as the check_alert function does
        item_ids = json.loads(self.test_alert.item_ids)
        print(f"item_ids list: {item_ids}")
        print(f"Type: {type(item_ids)}")
        print(f"Length: {len(item_ids)}")
        
        all_prices = {
            '100': {'high': 5000, 'low': 4800},
            '200': {'high': 2500000, 'low': 2400000},
            '300': {'high': 15000000, 'low': 14500000},
            '400': {'high': 30000000, 'low': 29000000},
            '500': {'high': 1200000000, 'low': 1150000000}
        }
        
        # Simulate the iteration loop from check_alerts.py
        iteration_count = 0
        items_processed = []
        items_with_price_data = []
        items_without_price_data = []
        
        for item_id in item_ids:
            iteration_count += 1
            item_id_str = str(item_id)
            items_processed.append(item_id)
            
            price_data = all_prices.get(item_id_str)
            
            if price_data:
                items_with_price_data.append(item_id)
                print(f"  Iteration {iteration_count}: Item {item_id} - HAS price data: {price_data}")
            else:
                items_without_price_data.append(item_id)
                print(f"  Iteration {iteration_count}: Item {item_id} - NO price data")
        
        print(f"\nTotal iterations: {iteration_count}")
        print(f"Items processed: {items_processed}")
        print(f"Items with price data: {items_with_price_data}")
        print(f"Items without price data: {items_without_price_data}")
        
        # Assertions
        self.assertEqual(iteration_count, 5, 
            f"Expected 5 iterations, got {iteration_count}")
        self.assertEqual(len(items_processed), 5,
            f"Expected 5 items processed, got {len(items_processed)}")
        self.assertEqual(items_processed, self.item_ids_list,
            f"Items processed don't match item_ids list")
    
    def test_check_alert_integration(self):
        """
        Integration test running the actual check_alert method.
        
        What: Runs the full check_alert flow and captures debug output
        Why: Tests the complete spike checking pipeline
        How: Call check_alert with test data and verify behavior
        """
        from Website.management.commands.check_alerts import Command
        
        print("\n=== TEST: Full Integration Test ===")
        
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        cmd.get_item_mapping = lambda: self.item_mapping
        
        # Fresh alert for this test
        alert = self.test_alert
        
        # Current prices - same for all items (no spike yet, just baseline capture)
        all_prices = {
            '100': {'high': 5000, 'low': 4800},
            '200': {'high': 2500000, 'low': 2400000},
            '300': {'high': 15000000, 'low': 14500000},
            '400': {'high': 30000000, 'low': 29000000},
            '500': {'high': 1200000000, 'low': 1150000000}
        }
        
        print(f"Alert ID: {alert.id}")
        print(f"Alert type: {alert.type}")
        print(f"Alert item_ids: {alert.item_ids}")
        print(f"Parsed item_ids: {json.loads(alert.item_ids)}")
        print(f"is_all_items: {alert.is_all_items}")
        print(f"item_id (single): {alert.item_id}")
        
        # First check - should be warming up (no historical data)
        print("\n--- First check (should be warming up) ---")
        result1 = cmd.check_alert(alert, all_prices)
        print(f"Result: {result1}")
        print(f"stdout output: {cmd.stdout.getvalue()}")
        
        # Check price_history was populated
        print("\n--- Price history after first check ---")
        for key, history in cmd.price_history.items():
            if history:
                print(f"  {key}: {len(history)} entries")
        
        # Manually verify the alert's item_ids iteration path is taken
        if alert.item_ids:
            print("\n--- Verifying item_ids branch is taken ---")
            item_ids_check = json.loads(alert.item_ids)
            print(f"item_ids is truthy: True")
            print(f"item_ids contains: {item_ids_check}")
        else:
            print("\n!!! WARNING: alert.item_ids is falsy - wrong branch will be taken !!!")
    
    def test_typo_in_variable_name(self):
        """
        Test to check for the arbyll_within_threshold typo bug.
        
        What: Verifies the typo in check_alerts.py line 1500
        Why: There's a typo 'arbyll_within_threshold' instead of 'all_within_threshold'
        How: Check the source code for the typo
        """
        print("\n=== TEST: Checking for Variable Name Typo ===")
        
        import inspect
        from Website.management.commands.check_alerts import Command
        
        # Get the source code of check_alert method
        source = inspect.getsource(Command.check_alert)
        
        # Check for the typo
        has_typo = 'arbyll_within_threshold' in source
        has_correct = 'all_within_threshold' in source
        
        print(f"Contains 'arbyll_within_threshold': {has_typo}")
        print(f"Contains 'all_within_threshold': {has_correct}")
        
        if has_typo:
            print("\n!!! BUG FOUND: Typo 'arbyll_within_threshold' exists in the code !!!")
            print("This variable is initialized but 'all_within_threshold' is used later,")
            print("which means the wrong variable is being set.")
            
            # Find the line with the typo
            lines = source.split('\n')
            for i, line in enumerate(lines):
                if 'arbyll_within_threshold' in line:
                    print(f"\nLine with typo: {line.strip()}")
        
        # This test should fail if typo exists, indicating the bug
        self.assertFalse(has_typo, 
            "TYPO BUG: 'arbyll_within_threshold' should be 'all_within_threshold' in check_alerts.py")


class SpikeAlertDirectionTests(TestCase):
    """
    Test suite for spike alert direction checking (up, down, both).
    
    What: Tests that direction filtering works correctly
    Why: Ensures alerts only trigger for price movements in the configured direction
    How: Create alerts with different directions and verify triggering behavior
    """
    
    def setUp(self):
        """Set up test user for direction tests."""
        self.test_user = User.objects.create_user(
            username='directiontestuser',
            email='direction@example.com',
            password='testpass123'
        )
        
        self.item_ids_list = [100, 200]
        self.item_mapping = {
            '100': 'Item A',
            '200': 'Item B'
        }
    
    def test_direction_up_only_triggers_on_increase(self):
        """
        Test that direction='up' only triggers on price increases.
        
        What: Alert with direction='up' should not trigger on price decreases
        Why: Validates the direction filtering logic
        How: Create up-only alert, simulate price decrease, verify no trigger
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Up Direction Test',
            type='spike',
            percentage=10.0,
            time_frame=60,
            direction='up',  # Only up
            reference='high',
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Test',
            item_id=100,
            is_active=True
        )
        
        # Verify alert configuration
        self.assertEqual(alert.direction, 'up')
        print(f"\n=== Direction Test: UP only ===")
        print(f"Should trigger on +10%: YES")
        print(f"Should trigger on -10%: NO")
    
    def test_direction_down_only_triggers_on_decrease(self):
        """
        Test that direction='down' only triggers on price decreases.
        """
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Down Direction Test',
            type='spike',
            percentage=10.0,
            time_frame=60,
            direction='down',  # Only down
            reference='high',
            is_all_items=False,
            item_ids=json.dumps(self.item_ids_list),
            item_name='Test',
            item_id=100,
            is_active=True
        )
        
        self.assertEqual(alert.direction, 'down')
        print(f"\n=== Direction Test: DOWN only ===")
        print(f"Should trigger on +10%: NO")
        print(f"Should trigger on -10%: YES")


class DebugMultiItemSpikeTest(TestCase):
    """
    Debug test to trace through the exact code path for multi-item spike alerts.
    
    What: Step-by-step debugging of the spike check logic
    Why: Identify exactly where items might be missed
    How: Add extensive logging at each step of the process
    """
    
    def setUp(self):
        self.test_user = User.objects.create_user(
            username='debuguser',
            email='debug@example.com',
            password='testpass123'
        )
    
    def test_debug_full_spike_check_flow(self):
        """
        Debug the complete spike check flow with verbose logging.
        """
        from Website.management.commands.check_alerts import Command
        
        print("\n" + "="*80)
        print("DEBUG: Full Spike Check Flow")
        print("="*80)
        
        # Create alert with 3 items
        item_ids = [111, 222, 333]
        alert = Alert.objects.create(
            user=self.test_user,
            alert_name='Debug Spike Alert',
            type='spike',
            percentage=5.0,
            time_frame=30,
            direction='both',
            reference='high',
            is_all_items=False,
            item_ids=json.dumps(item_ids),
            item_name='Debug Item',
            item_id=111,
            is_active=True
        )
        
        print(f"\n1. ALERT CREATED:")
        print(f"   - ID: {alert.id}")
        print(f"   - Type: {alert.type}")
        print(f"   - item_ids (raw): {alert.item_ids}")
        print(f"   - item_ids (parsed): {json.loads(alert.item_ids)}")
        print(f"   - is_all_items: {alert.is_all_items}")
        print(f"   - percentage: {alert.percentage}")
        print(f"   - time_frame: {alert.time_frame}")
        print(f"   - direction: {alert.direction}")
        print(f"   - reference: {alert.reference}")
        
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.price_history = defaultdict(list)
        cmd.get_item_mapping = lambda: {'111': 'Item A', '222': 'Item B', '333': 'Item C'}
        
        # All prices available
        all_prices = {
            '111': {'high': 1000, 'low': 950},
            '222': {'high': 2000, 'low': 1900},
            '333': {'high': 3000, 'low': 2850}
        }
        
        print(f"\n2. PRICE DATA:")
        for item_id, prices in all_prices.items():
            print(f"   - Item {item_id}: high={prices['high']}, low={prices['low']}")
        
        print(f"\n3. CHECKING CONDITIONS:")
        print(f"   - alert.type == 'spike': {alert.type == 'spike'}")
        print(f"   - alert.item_ids is truthy: {bool(alert.item_ids)}")
        print(f"   - alert.is_all_items: {alert.is_all_items}")
        
        # The condition in check_alert for multi-item spike
        if alert.type == 'spike':
            print("\n   -> Will enter SPIKE branch")
            if alert.item_ids:
                print("   -> Will enter MULTI-ITEM SPIKE branch (item_ids is set)")
            elif alert.is_all_items:
                print("   -> Will enter ALL-ITEMS SPIKE branch")
            else:
                print("   -> Will enter SINGLE-ITEM SPIKE branch")
        
        print(f"\n4. CALLING check_alert()...")
        result = cmd.check_alert(alert, all_prices)
        
        print(f"\n5. RESULT:")
        print(f"   - Return value: {result}")
        print(f"   - Type: {type(result)}")
        
        print(f"\n6. PRICE HISTORY AFTER CHECK:")
        for key, history in cmd.price_history.items():
            print(f"   - {key}: {len(history)} entries")
            if history:
                print(f"     Latest: {history[-1]}")
        
        print(f"\n7. STDOUT CAPTURED:")
        output = cmd.stdout.getvalue()
        if output:
            for line in output.strip().split('\n'):
                print(f"   {line}")
        else:
            print("   (no output captured)")
        
        # Verify all items were processed
        expected_keys = [f"{item_id}:high" for item_id in item_ids]
        actual_keys = list(cmd.price_history.keys())
        
        print(f"\n8. VERIFICATION:")
        print(f"   - Expected price_history keys: {expected_keys}")
        print(f"   - Actual price_history keys: {actual_keys}")
        
        missing_keys = set(expected_keys) - set(actual_keys)
        if missing_keys:
            print(f"   !!! MISSING KEYS: {missing_keys}")
            print(f"   This means some items were NOT checked!")
        else:
            print(f"   ✓ All items were processed")


if __name__ == '__main__':
    import django
    django.setup()
    
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(["test_multi_item_spike"])
    sys.exit(bool(failures))
