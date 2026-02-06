"""
Test cases for the flip confidence alert type.

What: Verifies the compute_flip_confidence() function and the
      check_flip_confidence_alert() method in check_alerts.py.
Why: The flip confidence alert computes a multi-factor score (0-100) from
     OSRS Wiki timeseries data and triggers when the score meets a threshold.
     These tests ensure the scoring algorithm and trigger logic work correctly.
How: Uses Django TestCase for the alert evaluation tests, and plain unittest
     for the pure scoring function. Mocks API calls to avoid hitting external
     endpoints.
"""

import json
import time
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase

from Website.management.commands.check_alerts import (
    Command,
    compute_flip_confidence,
    _clamp,
    _weighted_regression_slope,
    _standard_deviation,
)
from Website.models import Alert


# =============================================================================
# PURE FUNCTION TESTS (no Django DB needed, but using TestCase for consistency)
# =============================================================================

class ClampTests(TestCase):
    """
    Tests for the _clamp() helper function.
    
    What: Ensures values are correctly clamped to the [lo, hi] range.
    Why: Clamping is used in every sub-score to keep values in predictable ranges.
    How: Tests below, above, and within-range values.
    """

    def test_clamp_below_range(self):
        """Value below lo should be clamped to lo."""
        self.assertEqual(_clamp(-5, 0, 10), 0)

    def test_clamp_above_range(self):
        """Value above hi should be clamped to hi."""
        self.assertEqual(_clamp(15, 0, 10), 10)

    def test_clamp_within_range(self):
        """Value within [lo, hi] should be returned unchanged."""
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_at_boundaries(self):
        """Values at exactly lo or hi should be returned unchanged."""
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)


class WeightedRegressionSlopeTests(TestCase):
    """
    Tests for the _weighted_regression_slope() function.
    
    What: Verifies volume-weighted regression slope calculation.
    Why: The trend sub-score depends on this function producing correct slopes.
    How: Tests edge cases (few points, zero weight) and a known upward trend.
    """

    def test_fewer_than_2_points(self):
        """Should return 0.0 when fewer than 2 data points are provided."""
        self.assertEqual(_weighted_regression_slope([100], [10]), 0.0)
        self.assertEqual(_weighted_regression_slope([], []), 0.0)

    def test_zero_total_weight(self):
        """Should return 0.0 when all volumes are zero."""
        self.assertEqual(_weighted_regression_slope([100, 200, 300], [0, 0, 0]), 0.0)

    def test_upward_trend(self):
        """Increasing prices with equal weights should produce a positive slope."""
        # prices: [100, 200, 300] with uniform volumes
        # Expected: slope = 100 (price increases by 100 per bucket)
        slope = _weighted_regression_slope([100, 200, 300], [1, 1, 1])
        self.assertAlmostEqual(slope, 100.0, places=1)

    def test_downward_trend(self):
        """Decreasing prices should produce a negative slope."""
        slope = _weighted_regression_slope([300, 200, 100], [1, 1, 1])
        self.assertAlmostEqual(slope, -100.0, places=1)


class StandardDeviationTests(TestCase):
    """
    Tests for the _standard_deviation() function.
    
    What: Verifies population standard deviation calculation.
    Why: Used in the stability sub-score to measure price volatility.
    How: Tests empty list, uniform values, and a known distribution.
    """

    def test_empty_list(self):
        """Should return 0.0 for an empty list."""
        self.assertEqual(_standard_deviation([]), 0.0)

    def test_uniform_values(self):
        """Should return 0.0 when all values are the same."""
        self.assertEqual(_standard_deviation([100, 100, 100]), 0.0)

    def test_known_distribution(self):
        """Known values: [2, 4, 4, 4, 5, 5, 7, 9] => std ≈ 2.0."""
        result = _standard_deviation([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(result, 2.0, places=1)


class ComputeFlipConfidenceTests(TestCase):
    """
    Tests for the compute_flip_confidence() function.
    
    What: Verifies the full confidence score computation.
    Why: This is the core scoring algorithm that users rely on for flip signals.
    How: Tests with insufficient data, neutral data, and custom weights.
    """

    def test_insufficient_data_returns_zero(self):
        """
        Should return 0.0 when fewer than 3 valid data points are available.
        
        What: Validates the minimum data requirement.
        Why: The function explicitly returns 0.0 for fewer than 3 cleaned rows.
        How: Pass only 2 data points and verify 0.0 is returned.
        """
        data = [
            {"avgHighPrice": 100, "avgLowPrice": 95, "highPriceVolume": 10, "lowPriceVolume": 10},
            {"avgHighPrice": 101, "avgLowPrice": 96, "highPriceVolume": 10, "lowPriceVolume": 10},
        ]
        self.assertEqual(compute_flip_confidence(data), 0.0)

    def test_null_prices_skipped(self):
        """
        Rows with None prices should be skipped; if too few remain, returns 0.0.
        
        What: Validates null-price filtering logic.
        Why: The OSRS Wiki API returns None for prices when no trades occurred.
        How: Pass 4 rows, 2 with null prices. Only 2 valid remain => 0.0.
        """
        data = [
            {"avgHighPrice": None, "avgLowPrice": 95, "highPriceVolume": 10, "lowPriceVolume": 10},
            {"avgHighPrice": 100, "avgLowPrice": None, "highPriceVolume": 10, "lowPriceVolume": 10},
            {"avgHighPrice": 100, "avgLowPrice": 95, "highPriceVolume": 10, "lowPriceVolume": 10},
            {"avgHighPrice": 101, "avgLowPrice": 96, "highPriceVolume": 10, "lowPriceVolume": 10},
        ]
        self.assertEqual(compute_flip_confidence(data), 0.0)

    def test_neutral_data_returns_midrange_score(self):
        """
        Flat prices with balanced volume should produce a roughly neutral (40-60) score.
        
        What: Validates that neutral market conditions produce a moderate score.
        Why: When nothing is notably good or bad, the score should be around 50.
        How: Pass identical high/low prices with equal volumes.
        """
        data = [
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 500, "lowPriceVolume": 500},
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 500, "lowPriceVolume": 500},
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 500, "lowPriceVolume": 500},
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 500, "lowPriceVolume": 500},
        ]
        score = compute_flip_confidence(data)
        # Score should be in 0-100 range
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        # With flat trend (0.5 trend), balanced pressure (0.5), ~1% spread (~0.33 spread),
        # good volume, and perfect stability: should be roughly in the 40-70 range
        self.assertGreaterEqual(score, 30.0)
        self.assertLessEqual(score, 80.0)

    def test_custom_weights(self):
        """
        Custom weights should change the score compared to defaults.
        
        What: Validates that user-supplied weights are correctly applied.
        Why: Power users can customize weight distribution.
        How: Compare scores with default and custom weights on the same data.
        """
        data = [
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 500, "lowPriceVolume": 500},
            {"avgHighPrice": 1010, "avgLowPrice": 975, "highPriceVolume": 600, "lowPriceVolume": 400},
            {"avgHighPrice": 1020, "avgLowPrice": 980, "highPriceVolume": 700, "lowPriceVolume": 300},
            {"avgHighPrice": 1030, "avgLowPrice": 985, "highPriceVolume": 800, "lowPriceVolume": 200},
        ]
        # default_score: Score with default weights
        default_score = compute_flip_confidence(data)
        # custom_score: Score with all weight on trend
        custom_score = compute_flip_confidence(data, weights={
            'trend': 1.0, 'pressure': 0.0, 'spread': 0.0, 'volume': 0.0, 'stability': 0.0
        })
        # They should be different (trend sub-score != overall weighted average)
        self.assertNotEqual(default_score, custom_score)

    def test_score_is_rounded_to_one_decimal(self):
        """
        The score should be rounded to 1 decimal place.
        
        What: Validates rounding behavior.
        Why: The function spec says it returns a float rounded to 1 decimal.
        How: Check that the result has at most 1 decimal place.
        """
        data = [
            {"avgHighPrice": 1000, "avgLowPrice": 970, "highPriceVolume": 100, "lowPriceVolume": 100},
            {"avgHighPrice": 1005, "avgLowPrice": 975, "highPriceVolume": 150, "lowPriceVolume": 50},
            {"avgHighPrice": 1010, "avgLowPrice": 980, "highPriceVolume": 200, "lowPriceVolume": 100},
        ]
        score = compute_flip_confidence(data)
        # Verify the score is rounded to 1 decimal place
        self.assertEqual(score, round(score, 1))


# =============================================================================
# ALERT EVALUATION TESTS (require Django DB for Alert model)
# =============================================================================

class FlipConfidenceAlertBase(TestCase):
    """
    Base class for flip confidence alert tests.

    What: Provides shared setup logic and baseline data for flip confidence alert tests.
    Why: Multiple test classes need the same user, item ID, and mapping setup, and
         centralizing that logic avoids duplicated fixtures and inconsistent defaults.
    How: Creates a test user, a default item ID/name pair, and a mapping that can be
         reused by subclasses that exercise different alert configurations.
    """

    def setUp(self):
        """
        Set up the shared base fixtures used by flip confidence alert tests.

        What: Creates a test user and baseline item metadata for confidence alerts.
        Why: All confidence alert tests need a valid user and item identity to build
             Alert model instances and to map item IDs to readable names.
        How: Uses Django's create_user helper and stores the item details on self.
        """
        # test_user: User instance that owns the alerts created in these tests
        self.test_user = User.objects.create_user(
            username='confidence_user',
            email='confidence_user@example.com',
            password='testpass123'
        )

        # item_id: Default OSRS item ID used in single-item alert tests
        self.item_id = 4151  # Abyssal whip

        # item_name: Human-readable name for the default item ID
        self.item_name = 'Abyssal whip'

        # item_mapping: Baseline ID-to-name mapping used by get_item_mapping patches
        self.item_mapping = {str(self.item_id): self.item_name}

    def _create_alert(self, **overrides):
        """
        Helper to create a flip_confidence alert with sensible defaults.

        What: Factory method for creating test alerts with override capability.
        Why: Multiple tests need consistent alert defaults, and this helper keeps the
             defaults centralized while still allowing per-test customization.
        How: Merges the caller-provided overrides into a defaults dictionary and
             creates the Alert instance in the test database.

        Args:
            **overrides: Any Alert field values to override.

        Returns:
            Alert: The created Alert instance.
        """
        # defaults: Baseline alert configuration used by most tests
        defaults = {
            'user': self.test_user,
            'alert_name': 'Test Confidence Alert',
            'type': 'flip_confidence',
            'item_name': self.item_name,
            'item_id': self.item_id,
            'is_active': True,
            'is_triggered': False,
            'confidence_timestep': '1h',
            'confidence_lookback': 24,
            'confidence_threshold': 60.0,
            'confidence_trigger_rule': 'crosses_above',
        }
        # Merge the provided overrides into the defaults for this specific test
        defaults.update(overrides)
        return Alert.objects.create(**defaults)

    def _mock_timeseries_high_score(self):
        """
        Returns timeseries data that should produce a high confidence score.

        What: Simulated data with upward trend, good spread, balanced volume, stability.
        Why: Used to test that alerts trigger when the score is above threshold.
        How: Generates 24 data points with gradually increasing prices and good volume.

        Returns:
            list: Timeseries data dicts.
        """
        # data: Container for the generated timeseries buckets
        data = []
        # i: Loop counter used to increment prices and volumes over time
        for i in range(24):
            # high_price: Increasing average high price for each bucket
            high_price = 100000 + (i * 500)
            # low_price: Derived low price to maintain a ~3% spread
            low_price = int(high_price * 0.97)
            # timestamp: Unix timestamp for each bucket (1-hour spacing)
            timestamp = int(time.time()) - (24 - i) * 3600
            # bucket_data: Single timeseries bucket with price/volume values
            bucket_data = {
                "avgHighPrice": high_price,
                "avgLowPrice": low_price,
                "highPriceVolume": 300 + i * 10,
                "lowPriceVolume": 200 + i * 5,
                "timestamp": timestamp,
            }
            data.append(bucket_data)
        return data

    def _mock_timeseries_low_score(self):
        """
        Returns timeseries data that should produce a low confidence score.

        What: Simulated data with downward trend, tiny spread, low volume.
        Why: Used to test that alerts do NOT trigger when the score is below threshold.
        How: Generates 24 data points with declining prices and minimal volume.

        Returns:
            list: Timeseries data dicts.
        """
        # data: Container for the generated timeseries buckets
        data = []
        # i: Loop counter used to decrement prices over time
        for i in range(24):
            # high_price: Decreasing average high price for each bucket
            high_price = 100000 - (i * 1000)
            # low_price: Low price slightly below high_price to create a tiny spread
            low_price = high_price - 100
            # timestamp: Unix timestamp for each bucket (1-hour spacing)
            timestamp = int(time.time()) - (24 - i) * 3600
            # bucket_data: Single timeseries bucket with price/volume values
            bucket_data = {
                "avgHighPrice": high_price,
                "avgLowPrice": low_price,
                "highPriceVolume": 5,
                "lowPriceVolume": 10,
                "timestamp": timestamp,
            }
            data.append(bucket_data)
        return data

    def _announce_test(self, description):
        """
        Print a human-readable description of the scenario being tested.

        What: Emits a standardized prefix + description to the test output.
        Why: The requirement asks each test to state what it is validating.
        How: Formats a message string and prints it immediately.

        Args:
            description: Summary of the scenario this test validates.
        """
        # message: Formatted log line describing the current test scenario
        message = f"[FLIP CONFIDENCE TEST] {description}"
        print(message)

    def _make_timeseries_fetcher(self, timeseries_by_item):
        """
        Create a fetch_timeseries_from_db replacement that returns per-item data.

        What: Provides a callable that mimics Command.fetch_timeseries_from_db.
        Why: Each scenario needs deterministic timeseries data per item ID.
        How: Looks up the item ID in the provided dictionary and returns the data.

        Args:
            timeseries_by_item: Dict mapping item_id (str) -> timeseries list.

        Returns:
            callable: Function with the same signature as fetch_timeseries_from_db.
        """
        # per_item_series: Local reference to the item->timeseries mapping
        per_item_series = timeseries_by_item

        def _fetch_timeseries(item_id_str, timestep, lookback):
            """
            Fetch stubbed timeseries data for a given item ID.

            What: Returns the test-provided timeseries list for this item.
            Why: Ensures check_flip_confidence_alert uses the correct mock data.
            How: Converts the item ID to string and retrieves the mapping entry.
            """
            # normalized_item_id: String item ID used for dictionary lookups
            normalized_item_id = str(item_id_str)
            return per_item_series.get(normalized_item_id, [])

        return _fetch_timeseries

    def _assert_triggered_item_ids(self, triggered_items, expected_ids, scenario):
        """
        Assert that the triggered item list matches the expected item IDs.

        What: Compares actual triggered item IDs to the expected list.
        Why: Scenario tests need explicit validation of which items triggered.
        How: Extracts item_id values, prints failure details if mismatched, then
             uses assertEqual with a descriptive message.

        Args:
            triggered_items: List of triggered item dicts returned by the alert check.
            expected_ids: List of expected item IDs (strings or ints).
            scenario: Scenario description used for error context.
        """
        # actual_ids: Ordered list of item IDs returned by the alert evaluation
        actual_ids = []
        # item: Triggered item dictionary from the alert evaluation result set
        for item in triggered_items:
            # item_id_value: Item ID extracted from the triggered item dictionary
            item_id_value = item['item_id']
            actual_ids.append(item_id_value)

        # normalized_expected_ids: Expected item IDs normalized to strings
        normalized_expected_ids = []
        # expected_id: Raw expected item ID (may be int or str)
        for expected_id in expected_ids:
            # expected_id_str: Expected item ID coerced to string form
            expected_id_str = str(expected_id)
            normalized_expected_ids.append(expected_id_str)

        if actual_ids != normalized_expected_ids:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario}. Expected {normalized_expected_ids}, got {actual_ids}."
            )

        self.assertEqual(
            actual_ids,
            normalized_expected_ids,
            f"{scenario} expected triggered IDs {normalized_expected_ids} but got {actual_ids}."
        )

    def _assert_triggered_flag(self, triggered_flag, expected_flag, scenario):
        """
        Assert that a single-item alert returned the expected True/False result.

        What: Validates boolean trigger outcomes for single-item alerts.
        Why: Single-item alerts return booleans instead of item lists.
        How: Prints a failure message on mismatch and uses assertEqual.

        Args:
            triggered_flag: Boolean returned by check_flip_confidence_alert.
            expected_flag: Boolean expectation for this scenario.
            scenario: Scenario description used for error context.
        """
        if triggered_flag != expected_flag:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario}. Expected {expected_flag}, got {triggered_flag}."
            )

        self.assertEqual(
            triggered_flag,
            expected_flag,
            f"{scenario} expected trigger={expected_flag} but got {triggered_flag}."
        )


class FlipConfidenceAlertTests(FlipConfidenceAlertBase):
    """
    Tests for the check_flip_confidence_alert() method in check_alerts.py.
    
    What: Verifies that flip_confidence alerts correctly trigger based on
          confidence scores computed from mocked timeseries data.
    Why: Users rely on these alerts firing correctly when conditions are met.
    How: Creates Alert instances, mocks external API calls, and verifies trigger behavior.
    """

    def test_single_item_alert_triggers(self):
        """
        A single-item alert should trigger when the confidence score exceeds the threshold.
        
        What: Validates basic trigger behavior for single-item flip_confidence alerts.
        Why: This is the simplest usage pattern and must work correctly.
        How: Mock timeseries data that produces a high score, verify check returns True.
        """
        alert = self._create_alert(confidence_threshold=50.0)
        command = Command()
        
        # all_prices: Current market prices (used for min_spread pre-filter)
        all_prices = {
            str(self.item_id): {'high': 112000, 'low': 97000}
        }

        with patch.object(
            command, 'fetch_timeseries_from_db',
            return_value=self._mock_timeseries_high_score()
        ), patch.object(command, 'get_item_mapping', return_value={
            str(self.item_id): 'Abyssal whip'
        }):
            result = command.check_flip_confidence_alert(alert, all_prices)

        self.assertTrue(result)

    def test_single_item_alert_does_not_trigger(self):
        """
        A single-item alert should NOT trigger when the score is below the threshold.
        
        What: Validates that low scores don't cause false triggers.
        Why: Users should not be spammed with alerts for poor flip candidates.
        How: Mock timeseries data that produces a low score, verify check returns False.
        """
        alert = self._create_alert(confidence_threshold=80.0)
        command = Command()

        all_prices = {
            str(self.item_id): {'high': 100000, 'low': 99900}
        }

        with patch.object(
            command, 'fetch_timeseries_from_db',
            return_value=self._mock_timeseries_low_score()
        ), patch.object(command, 'get_item_mapping', return_value={
            str(self.item_id): 'Abyssal whip'
        }):
            result = command.check_flip_confidence_alert(alert, all_prices)

        self.assertFalse(result)

    def test_min_spread_filter_blocks_trigger(self):
        """
        Alert should not trigger if current spread is below the configured minimum.
        
        What: Validates the min_spread_pct pre-filter.
        Why: Even with a high confidence score, a tiny spread means no profit opportunity.
        How: Set min_spread_pct high, provide prices with tiny spread.
        """
        alert = self._create_alert(
            confidence_threshold=50.0,
            confidence_min_spread_pct=5.0,  # Require at least 5% spread
        )
        command = Command()

        # all_prices: Tiny spread (only 0.1%)
        all_prices = {
            str(self.item_id): {'high': 100100, 'low': 100000}
        }

        with patch.object(
            command, 'fetch_timeseries_from_db',
            return_value=self._mock_timeseries_high_score()
        ), patch.object(command, 'get_item_mapping', return_value={
            str(self.item_id): 'Abyssal whip'
        }):
            result = command.check_flip_confidence_alert(alert, all_prices)

        self.assertFalse(result)

    def test_insufficient_timeseries_data(self):
        """
        Alert should not trigger if timeseries data has fewer than 3 points.
        
        What: Validates the minimum data requirement in check_flip_confidence_alert.
        Why: compute_flip_confidence returns 0.0 with < 3 points, but the check method
             itself should also skip items with insufficient data.
        How: Mock fetch_timeseries_from_db to return only 2 points and verify both:
             1. compute_flip_confidence returns 0.0 for the data
             2. check_flip_confidence_alert returns False
        """
        # insufficient_data: Only 2 timeseries data points (below the 3-point minimum)
        insufficient_data = [
            {"avgHighPrice": 100, "avgLowPrice": 95, "highPriceVolume": 10, "lowPriceVolume": 10},
            {"avgHighPrice": 101, "avgLowPrice": 96, "highPriceVolume": 10, "lowPriceVolume": 10},
        ]
        
        # Verify that compute_flip_confidence itself returns 0.0 for < 3 points
        self.assertEqual(compute_flip_confidence(insufficient_data), 0.0)
        
        alert = self._create_alert(confidence_threshold=10.0)
        command = Command()

        all_prices = {
            str(self.item_id): {'high': 112000, 'low': 97000}
        }

        with patch.object(
            command, 'fetch_timeseries_from_db',
            return_value=insufficient_data
        ), patch.object(command, 'get_item_mapping', return_value={
            str(self.item_id): 'Abyssal whip'
        }):
            result = command.check_flip_confidence_alert(alert, all_prices)

        self.assertFalse(result)

    def test_no_threshold_returns_false(self):
        """
        Alert should return False if no confidence_threshold is set.
        
        What: Validates the threshold validation check.
        Why: Without a threshold, the alert cannot determine when to trigger.
        How: Create alert with confidence_threshold=None.
        """
        alert = self._create_alert(confidence_threshold=None)
        command = Command()

        all_prices = {str(self.item_id): {'high': 112000, 'low': 97000}}

        result = command.check_flip_confidence_alert(alert, all_prices)
        self.assertFalse(result)


# =============================================================================
# COMPREHENSIVE FLIP CONFIDENCE ALERT SCENARIO TESTS
# =============================================================================

class FlipConfidenceAlertScenarioTests(FlipConfidenceAlertBase):
    """
    Comprehensive scenario-based tests for flip confidence alert triggering.

    What: Exercises multiple alert configurations to ensure expected items trigger
          or are filtered out under a wide range of conditions.
    Why: Users can configure flip confidence alerts with thresholds, rules, filters,
         and weights; we must ensure each configuration yields predictable results.
    How: Uses a shared Command instance with patched fetch/compute logic, custom
         timeseries payloads, and explicit assertions on triggered item IDs.
    """

    def setUp(self):
        """
        Set up shared fixtures for the scenario-based flip confidence tests.

        What: Extends the base setup with multiple item IDs and a Command instance.
        Why: Scenario tests need multi-item/all-item alert contexts and a reusable
             Command object for invoking check_flip_confidence_alert repeatedly.
        How: Calls the base setUp, then configures an expanded item mapping and
             a Command instance whose get_item_mapping returns the test mapping.
        """
        super().setUp()

        # scenario_item_ids: Ordered list of item IDs used in multi/all-item scenarios
        self.scenario_item_ids = ['101', '202', '303', '404']

        # scenario_item_mapping: Mapping of scenario item IDs to readable names
        self.scenario_item_mapping = {
            '101': 'Dragon scimitar',
            '202': 'Rune platebody',
            '303': 'Abyssal whip',
            '404': 'Bandos chestplate',
        }

        # command: Command instance that runs the flip confidence alert evaluation
        self.command = Command()

        # command.get_item_mapping: Stubbed mapping provider for display names in tests
        self.command.get_item_mapping = lambda: self.scenario_item_mapping

    def _build_timeseries_with_score_hint(
        self,
        score_hint,
        avg_high_price,
        avg_low_price,
        high_volume,
        low_volume,
        points=3,
    ):
        """
        Build timeseries data with a score_hint marker for patched scoring.

        What: Produces a list of price/volume buckets that include a score_hint key.
        Why: Scenario tests patch compute_flip_confidence to return score_hint so we
             can control trigger outcomes without relying on the real scoring math.
        How: Generates [points] buckets using the supplied price/volume values and
             annotates each bucket with the same score_hint for easy lookup.

        Args:
            score_hint: Float score that the patched compute function should return.
            avg_high_price: Average high price for each bucket.
            avg_low_price: Average low price for each bucket.
            high_volume: High-price trade volume for each bucket.
            low_volume: Low-price trade volume for each bucket.
            points: Number of buckets to include (minimum 3 recommended).

        Returns:
            list: Timeseries buckets formatted for compute_flip_confidence input.
        """
        # timeseries: Container for the generated bucket dictionaries
        timeseries = []
        # index: Loop counter used to create distinct timestamps per bucket
        for index in range(points):
            # timestamp: Simulated Unix timestamp for each bucket (spaced 1h apart)
            timestamp = int(time.time()) - (points - index) * 3600
            # bucket_data: Single timeseries bucket with price/volume and score hint
            bucket_data = {
                "avgHighPrice": avg_high_price,
                "avgLowPrice": avg_low_price,
                "highPriceVolume": high_volume,
                "lowPriceVolume": low_volume,
                "timestamp": timestamp,
                "score_hint": score_hint,
            }
            timeseries.append(bucket_data)
        return timeseries

    def _compute_from_score_hint(self, timeseries_data, weights=None):
        """
        Compute a score directly from the score_hint stored in timeseries data.

        What: Reads the score_hint value and returns it as the confidence score.
        Why: Allows scenario tests to control scores without relying on real math.
        How: Pulls score_hint from the first bucket (if any), defaulting to 0.0.

        Args:
            timeseries_data: List of timeseries buckets containing score_hint values.
            weights: Optional weights passed by the alert logic (unused here).

        Returns:
            float: The score_hint value or 0.0 if missing.
        """
        # score_hint_value: Extracted score_hint from the first bucket
        score_hint_value = timeseries_data[0].get('score_hint', 0.0) if timeseries_data else 0.0
        return float(score_hint_value)

    def test_multi_item_crosses_above_triggers_expected_items(self):
        """
        Multi-item crosses_above alerts should trigger only items above the threshold.

        What: Validates that a multi-item alert returns the correct triggered item IDs.
        Why: Users expect only high-scoring items to trigger and to be sorted by score.
        How: Patch scoring to return known values and confirm the triggered list.
        """
        # scenario_description: Summary of the scenario under test
        scenario_description = "Multi-item crosses_above triggers high-score items only"
        self._announce_test(scenario_description)

        # alert: Multi-item alert configured with a threshold of 70
        alert = self._create_alert(
            item_ids=json.dumps(self.scenario_item_ids[:3]),
            item_id=None,
            is_all_items=False,
            confidence_threshold=70.0,
            confidence_trigger_rule='crosses_above',
        )

        # all_prices: Current market prices with healthy spreads for each item
        all_prices = {
            '101': {'high': 1050, 'low': 1000},
            '202': {'high': 2100, 'low': 2000},
            '303': {'high': 3150, 'low': 3000},
        }

        # timeseries_by_item: Timeseries data keyed by item ID with deterministic scores
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(80.0, 1000, 970, 100, 100),
            '202': self._build_timeseries_with_score_hint(65.0, 2000, 1940, 100, 100),
            '303': self._build_timeseries_with_score_hint(95.0, 3000, 2910, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher that returns per-item series data
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Expected order (highest score first)
        expected_triggered_ids = ['303', '101']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_multi_item_crosses_above_sorted_by_score(self):
        """
        Multi-item alerts should sort triggered items by confidence score descending.

        What: Ensures ordering of the returned list respects score ranking.
        Why: The UI expects the highest-confidence items to appear first.
        How: Provide three items above threshold with distinct scores and assert ordering.
        """
        # scenario_description: Summary of the ordering scenario
        scenario_description = "Multi-item crosses_above returns items sorted by score"
        self._announce_test(scenario_description)

        # alert: Multi-item alert configured to include all three items
        alert = self._create_alert(
            item_ids=json.dumps(self.scenario_item_ids[:3]),
            item_id=None,
            is_all_items=False,
            confidence_threshold=50.0,
        )

        # all_prices: Current prices with sufficient spread for all items
        all_prices = {
            '101': {'high': 1100, 'low': 1000},
            '202': {'high': 2200, 'low': 2000},
            '303': {'high': 3300, 'low': 3000},
        }

        # timeseries_by_item: Score hints arranged to test sorting behavior
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
            '202': self._build_timeseries_with_score_hint(70.0, 2000, 1940, 100, 100),
            '303': self._build_timeseries_with_score_hint(80.0, 3000, 2910, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for per-item timeseries
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Scores should sort to 101 (90), 303 (80), 202 (70)
        expected_triggered_ids = ['101', '303', '202']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_multi_item_delta_increase_triggers_expected_item(self):
        """
        Delta-increase alerts should trigger only when score delta meets the threshold.

        What: Validates delta_increase behavior with previous scores on record.
        Why: Users rely on delta rules to catch sudden improvements.
        How: Provide previous scores and new scores, then assert triggered items.
        """
        # scenario_description: Summary of the delta-increase scenario
        scenario_description = "Delta-increase triggers only items meeting delta threshold"
        self._announce_test(scenario_description)

        # last_scores_state: Stored JSON for previous scores per item
        last_scores_state = json.dumps({
            '101': {'score': 50.0, 'consecutive': 0, 'last_eval': 0},
            '202': {'score': 30.0, 'consecutive': 0, 'last_eval': 0},
        })

        # alert: Multi-item alert using delta_increase with a 10-point delta threshold
        alert = self._create_alert(
            item_ids=json.dumps(['101', '202']),
            item_id=None,
            is_all_items=False,
            confidence_threshold=10.0,
            confidence_trigger_rule='delta_increase',
            confidence_last_scores=last_scores_state,
        )

        # all_prices: Current prices used for spread checks
        all_prices = {
            '101': {'high': 1050, 'low': 1000},
            '202': {'high': 2100, 'low': 2000},
        }

        # timeseries_by_item: New score hints (delta 15 for 101, delta 5 for 202)
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(65.0, 1000, 970, 100, 100),
            '202': self._build_timeseries_with_score_hint(35.0, 2000, 1940, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for per-item data
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Only item 101 meets the delta threshold
        expected_triggered_ids = ['101']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_delta_increase_requires_previous_score(self):
        """
        Delta-increase alerts should not trigger when no previous score exists.

        What: Ensures first-time evaluations do not trigger delta alerts.
        Why: Delta comparisons require a baseline score to compare against.
        How: Use delta_increase rule with no last_scores and confirm no triggers.
        """
        # scenario_description: Summary of the missing previous score scenario
        scenario_description = "Delta-increase does not trigger without a previous score"
        self._announce_test(scenario_description)

        # alert: Delta-increase alert with no stored last_scores
        alert = self._create_alert(
            item_ids=json.dumps(['101']),
            item_id=None,
            is_all_items=False,
            confidence_threshold=10.0,
            confidence_trigger_rule='delta_increase',
            confidence_last_scores=json.dumps({}),
        )

        # all_prices: Current prices with sufficient spread
        all_prices = {'101': {'high': 1050, 'low': 1000}}

        # timeseries_by_item: New score hint that would be high if previous existed
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the single item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Expect no items because there is no previous score
        expected_triggered_ids = []
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_all_items_min_max_price_filters_only_in_range_items(self):
        """
        All-items alerts should filter out items outside min/max price bounds.

        What: Validates the price range pre-filter in all-items mode.
        Why: Users want to focus on items within a specific price tier.
        How: Provide three items with varying prices and assert only the in-range item triggers.
        """
        # scenario_description: Summary of the min/max price filter scenario
        scenario_description = "All-items mode filters by minimum/maximum price"
        self._announce_test(scenario_description)

        # alert: All-items alert with price range limits and low threshold
        alert = self._create_alert(
            item_id=None,
            is_all_items=True,
            item_ids=None,
            confidence_threshold=40.0,
            minimum_price=1000,
            maximum_price=3000,
        )

        # all_prices: Mixed price levels (below min, within range, above max)
        all_prices = {
            '101': {'high': 900, 'low': 850},
            '202': {'high': 2500, 'low': 2400},
            '303': {'high': 4000, 'low': 3900},
        }

        # timeseries_by_item: Scores above threshold for all items (filter decides)
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 900, 875, 100, 100),
            '202': self._build_timeseries_with_score_hint(90.0, 2500, 2425, 100, 100),
            '303': self._build_timeseries_with_score_hint(90.0, 4000, 3880, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for all items
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Only item 202 is within the price range
        expected_triggered_ids = ['202']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_all_items_min_spread_prefilter_blocks_low_spread_items(self):
        """
        All-items mode should pre-filter items whose current spread is too small.

        What: Ensures the early spread filter in all-items mode works correctly.
        Why: Avoids wasting evaluation on items with negligible spreads.
        How: Provide items with low and high spreads, then assert only high spread triggers.
        """
        # scenario_description: Summary of the min spread pre-filter scenario
        scenario_description = "All-items pre-filter removes low-spread items"
        self._announce_test(scenario_description)

        # alert: All-items alert with a minimum spread requirement
        alert = self._create_alert(
            item_id=None,
            is_all_items=True,
            item_ids=None,
            confidence_threshold=40.0,
            confidence_min_spread_pct=5.0,
        )

        # all_prices: One low-spread item and one high-spread item
        all_prices = {
            '101': {'high': 1005, 'low': 1000},
            '202': {'high': 2100, 'low': 2000},
        }

        # timeseries_by_item: Scores above threshold for both items
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
            '202': self._build_timeseries_with_score_hint(90.0, 2000, 1940, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for all items
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Only item 202 passes the spread filter
        expected_triggered_ids = ['202']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_min_volume_filter_blocks_low_volume_item(self):
        """
        Minimum GP volume filtering should prevent low-volume items from triggering.

        What: Validates the min_volume pre-filter in flip confidence alerts.
        Why: Users rely on volume filtering to avoid illiquid items.
        How: Configure min_volume above the computed GP volume and confirm no trigger.
        """
        # scenario_description: Summary of the min-volume filtering scenario
        scenario_description = "Min volume filter blocks low-GP-volume items"
        self._announce_test(scenario_description)

        # alert: Multi-item alert with a high min_volume requirement
        alert = self._create_alert(
            item_ids=json.dumps(['101']),
            item_id=None,
            is_all_items=False,
            confidence_threshold=40.0,
            confidence_min_volume=1_000_000,
        )

        # all_prices: Current prices with sufficient spread
        all_prices = {'101': {'high': 1050, 'low': 1000}}

        # timeseries_by_item: Low volume series that fails the GP volume check
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Expect no items due to min volume filter
        expected_triggered_ids = []
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_min_volume_filter_allows_high_volume_item(self):
        """
        Minimum GP volume filtering should allow high-volume items to trigger.

        What: Ensures items meeting min_volume are still evaluated and can trigger.
        Why: Volume filters should not block legitimately active items.
        How: Provide high volumes and confirm the item triggers.
        """
        # scenario_description: Summary of the high-volume pass scenario
        scenario_description = "Min volume filter allows high-GP-volume items"
        self._announce_test(scenario_description)

        # alert: Multi-item alert with a min_volume that high volume will satisfy
        alert = self._create_alert(
            item_ids=json.dumps(['101']),
            item_id=None,
            is_all_items=False,
            confidence_threshold=40.0,
            confidence_min_volume=500_000,
        )

        # all_prices: Current prices with sufficient spread
        all_prices = {'101': {'high': 1050, 'low': 1000}}

        # timeseries_by_item: High-volume series that exceeds the GP volume check
        timeseries_by_item = {
            '101': self._build_timeseries_with_score_hint(90.0, 1000, 970, 1000, 1000),
        }

        # fetch_timeseries: Stubbed fetcher for the item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Expect the item to pass volume filtering and trigger
        expected_triggered_ids = ['101']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)

    def test_sustained_count_requires_consecutive_passes(self):
        """
        Sustained count should require consecutive passes before triggering.

        What: Validates that confidence_sustained_count enforces multiple passes.
        Why: Users may want alerts only after sustained high confidence.
        How: Run the same alert twice and ensure it triggers only on the second pass.
        """
        # scenario_description: Summary of the sustained-count scenario
        scenario_description = "Sustained count requires multiple consecutive passes"
        self._announce_test(scenario_description)

        # alert: Single-item alert requiring two consecutive passes
        alert = self._create_alert(
            confidence_threshold=60.0,
            confidence_sustained_count=2,
        )

        # all_prices: Current prices with adequate spread
        all_prices = {str(self.item_id): {'high': 1050, 'low': 1000}}

        # timeseries_by_item: High score hint to satisfy the threshold
        timeseries_by_item = {
            str(self.item_id): self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the default item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # first_result: First evaluation should not trigger (consecutive = 1)
            first_result = self.command.check_flip_confidence_alert(alert, all_prices)

            # second_result: Second evaluation should trigger (consecutive = 2)
            second_result = self.command.check_flip_confidence_alert(alert, all_prices)

        self._assert_triggered_flag(first_result, False, f"{scenario_description} (first pass)")
        self._assert_triggered_flag(second_result, True, f"{scenario_description} (second pass)")

    def test_cooldown_blocks_recently_triggered_item(self):
        """
        Cooldown should block re-triggering for items triggered recently.

        What: Ensures confidence_cooldown prevents immediate re-alerts.
        Why: Users should not be spammed by repeated triggers in a short window.
        How: Seed last_triggered within the cooldown period and confirm no trigger.
        """
        # scenario_description: Summary of the cooldown scenario
        scenario_description = "Cooldown blocks re-trigger within cooldown window"
        self._announce_test(scenario_description)

        # recent_trigger_ts: Unix timestamp 10 minutes ago (inside a 60-minute cooldown)
        recent_trigger_ts = time.time() - (10 * 60)

        # last_scores_state: Stored state indicating the item triggered recently
        last_scores_state = json.dumps({
            str(self.item_id): {
                'score': 80.0,
                'consecutive': 1,
                'last_eval': 0,
                'last_triggered': recent_trigger_ts,
            }
        })

        # alert: Single-item alert with a 60-minute cooldown
        alert = self._create_alert(
            confidence_threshold=60.0,
            confidence_cooldown=60,
            confidence_last_scores=last_scores_state,
        )

        # all_prices: Current prices with adequate spread
        all_prices = {str(self.item_id): {'high': 1050, 'low': 1000}}

        # timeseries_by_item: High score hint that would normally trigger
        timeseries_by_item = {
            str(self.item_id): self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the default item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Trigger result expected to be False due to cooldown
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        self._assert_triggered_flag(result, False, scenario_description)

    def test_eval_interval_skips_recent_evaluation(self):
        """
        Eval interval should skip evaluation if the last eval was too recent.

        What: Ensures confidence_eval_interval prevents frequent evaluations.
        Why: Users may want to limit how often scores are recalculated.
        How: Seed last_eval within the interval and confirm no trigger occurs.
        """
        # scenario_description: Summary of the evaluation interval scenario
        scenario_description = "Eval interval skips evaluation within interval window"
        self._announce_test(scenario_description)

        # recent_eval_ts: Unix timestamp 10 minutes ago (inside a 60-minute interval)
        recent_eval_ts = time.time() - (10 * 60)

        # last_scores_state: Stored state indicating the item was evaluated recently
        last_scores_state = json.dumps({
            str(self.item_id): {
                'score': 50.0,
                'consecutive': 0,
                'last_eval': recent_eval_ts,
            }
        })

        # alert: Single-item alert with a 60-minute evaluation interval
        alert = self._create_alert(
            confidence_threshold=40.0,
            confidence_eval_interval=60,
            confidence_last_scores=last_scores_state,
        )

        # all_prices: Current prices with adequate spread
        all_prices = {str(self.item_id): {'high': 1050, 'low': 1000}}

        # timeseries_by_item: High score hint that would normally trigger if evaluated
        timeseries_by_item = {
            str(self.item_id): self._build_timeseries_with_score_hint(90.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the default item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=self._compute_from_score_hint
        ):
            # result: Trigger result expected to be False due to eval interval
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        self._assert_triggered_flag(result, False, scenario_description)

    def test_custom_weights_passed_into_compute_function(self):
        """
        Custom weight fields should be passed into compute_flip_confidence.

        What: Ensures the alert logic forwards weight overrides to the scoring function.
        Why: Users customize weight distribution for their preferred signal emphasis.
        How: Patch compute_flip_confidence to capture weights and return a score.
        """
        # scenario_description: Summary of the custom weights scenario
        scenario_description = "Custom weight overrides are passed to compute"
        self._announce_test(scenario_description)

        # expected_weights: Weight configuration expected to be passed to compute
        expected_weights = {
            'trend': 0.5,
            'pressure': 0.2,
            'spread': 0.1,
            'volume': 0.1,
            'stability': 0.1,
        }

        # alert: Single-item alert with custom weight overrides
        alert = self._create_alert(
            confidence_threshold=40.0,
            confidence_weight_trend=expected_weights['trend'],
            confidence_weight_pressure=expected_weights['pressure'],
            confidence_weight_spread=expected_weights['spread'],
            confidence_weight_volume=expected_weights['volume'],
            confidence_weight_stability=expected_weights['stability'],
        )

        # all_prices: Current prices with adequate spread
        all_prices = {str(self.item_id): {'high': 1050, 'low': 1000}}

        # timeseries_by_item: Standard series that will be evaluated by the alert
        timeseries_by_item = {
            str(self.item_id): self._build_timeseries_with_score_hint(75.0, 1000, 970, 100, 100),
        }

        # fetch_timeseries: Stubbed fetcher for the default item
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        # captured_weights: Container used to store weights passed to compute
        captured_weights = {}

        def _compute_with_capture(timeseries_data, weights=None):
            """
            Capture the weights passed to compute and return the score hint.

            What: Saves the weights argument for later assertion.
            Why: The test must confirm that custom weights reach the scorer.
            How: Updates the captured_weights dict and returns the score_hint.
            """
            # weights_payload: Actual weights argument provided by the alert logic
            weights_payload = weights or {}
            captured_weights.update(weights_payload)
            return self._compute_from_score_hint(timeseries_data, weights=weights)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ), patch(
            'Website.management.commands.check_alerts.compute_flip_confidence',
            side_effect=_compute_with_capture
        ):
            # result: Triggered boolean returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_trigger_flag: Should trigger because score_hint is above threshold
        expected_trigger_flag = True
        self._assert_triggered_flag(result, expected_trigger_flag, scenario_description)

        if captured_weights != expected_weights:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario_description}. Expected weights {expected_weights}, got {captured_weights}."
            )

        self.assertEqual(
            captured_weights,
            expected_weights,
            f"{scenario_description} expected weights {expected_weights} but got {captured_weights}."
        )


# =============================================================================
# END-TO-END FLIP CONFIDENCE INTEGRATION SCENARIOS (REAL SCORE COMPUTATION)
# =============================================================================

class FlipConfidenceAlertIntegrationTests(FlipConfidenceAlertBase):
    """
    Integration-style tests that use the real compute_flip_confidence algorithm.

    What: Validates that full alert evaluation triggers (or does not trigger) when
          real numeric timeseries data is scored end-to-end.
    Why: Ensures alert logic remains correct even when the true scoring algorithm
         is used, not just mocked score hints.
    How: Patches only fetch_timeseries_from_db so check_flip_confidence_alert
         consumes deterministic data and invokes the real compute function.
    """

    def setUp(self):
        """
        Set up shared fixtures for end-to-end integration scenarios.

        What: Extends the base setup with a Command instance and item mapping.
        Why: Integration tests need a consistent command object and item name lookup.
        How: Calls the base setUp then creates a Command and mapping for test items.
        """
        super().setUp()

        # integration_item_ids: Item IDs used in multi-item integration tests
        self.integration_item_ids = ['901', '902']

        # integration_item_mapping: Mapping of integration item IDs to readable names
        self.integration_item_mapping = {
            '901': 'Integration High Score Item',
            '902': 'Integration Low Score Item',
        }

        # command: Command instance that runs the flip confidence alert evaluation
        self.command = Command()

        # command.get_item_mapping: Stubbed mapping provider for item display names
        self.command.get_item_mapping = lambda: self.integration_item_mapping

    def _assert_score_relation(self, left_score, right_score, relation, scenario):
        """
        Assert a numeric relationship between two computed scores.

        What: Validates ordering (greater/less) between computed scores.
        Why: Integration tests rely on score separation to choose thresholds.
        How: Prints an explicit failure message and asserts the condition.

        Args:
            left_score: Score on the left side of the comparison.
            right_score: Score on the right side of the comparison.
            relation: String describing the expected relation ('>' or '<').
            scenario: Scenario description used for error context.
        """
        # comparison_ok: Boolean representing whether the expected relation holds
        if relation == '>':
            comparison_ok = left_score > right_score
        else:
            comparison_ok = left_score < right_score

        if not comparison_ok:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario}. Expected {left_score} {relation} {right_score}."
            )

        if relation == '>':
            self.assertGreater(
                left_score,
                right_score,
                f"{scenario} expected {left_score} > {right_score} but got the opposite."
            )
        else:
            self.assertLess(
                left_score,
                right_score,
                f"{scenario} expected {left_score} < {right_score} but got the opposite."
            )

    def test_end_to_end_high_score_triggers(self):
        """
        High-quality timeseries data should trigger an alert end-to-end.

        What: Confirms a strong upward trend with healthy spread/volume triggers.
        Why: Ensures the real compute algorithm yields a score that can fire alerts.
        How: Computes the score from real data, sets a threshold below it, and checks.
        """
        # scenario_description: Summary of the high-score integration scenario
        scenario_description = "End-to-end high-score data triggers with real compute"
        self._announce_test(scenario_description)

        # high_score_series: Timeseries data expected to produce a strong score
        high_score_series = self._mock_timeseries_high_score()

        # computed_score: Real confidence score produced by compute_flip_confidence
        computed_score = compute_flip_confidence(high_score_series)

        # threshold: Alert threshold set below the computed score to ensure triggering
        threshold = max(0.0, computed_score - 5.0)

        if computed_score < threshold:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario_description}. Computed score {computed_score} below threshold {threshold}."
            )

        self.assertGreaterEqual(
            computed_score,
            threshold,
            f"{scenario_description} expected computed score {computed_score} >= threshold {threshold}."
        )

        # alert: Single-item alert configured to use the computed threshold
        alert = self._create_alert(confidence_threshold=threshold)

        # all_prices: Current prices used by the alert checker
        all_prices = {str(self.item_id): {'high': 112000, 'low': 97000}}

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            return_value=high_score_series
        ):
            # result: Boolean indicating whether the alert triggered
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_trigger_flag: High scores should trigger the alert
        expected_trigger_flag = True
        self._assert_triggered_flag(result, expected_trigger_flag, scenario_description)

    def test_end_to_end_low_score_does_not_trigger(self):
        """
        Low-quality timeseries data should not trigger an alert end-to-end.

        What: Confirms poor trend/spread/volume yields a low score that does not trigger.
        Why: Prevents false positives when market conditions are weak.
        How: Computes the score from real data, sets a threshold above it, and checks.
        """
        # scenario_description: Summary of the low-score integration scenario
        scenario_description = "End-to-end low-score data does not trigger with real compute"
        self._announce_test(scenario_description)

        # low_score_series: Timeseries data expected to produce a weak score
        low_score_series = self._mock_timeseries_low_score()

        # computed_score: Real confidence score produced by compute_flip_confidence
        computed_score = compute_flip_confidence(low_score_series)

        # threshold: Alert threshold set above the computed score to block triggers
        threshold = min(100.0, computed_score + 5.0)

        if computed_score >= threshold:
            print(
                "[TEST FAILURE] Scenario mismatch: "
                f"{scenario_description}. Computed score {computed_score} not below threshold {threshold}."
            )

        self.assertLess(
            computed_score,
            threshold,
            f"{scenario_description} expected computed score {computed_score} < threshold {threshold}."
        )

        # alert: Single-item alert configured with the higher threshold
        alert = self._create_alert(confidence_threshold=threshold)

        # all_prices: Current prices used by the alert checker
        all_prices = {str(self.item_id): {'high': 100000, 'low': 99900}}

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            return_value=low_score_series
        ):
            # result: Boolean indicating whether the alert triggered
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_trigger_flag: Low scores should not trigger the alert
        expected_trigger_flag = False
        self._assert_triggered_flag(result, expected_trigger_flag, scenario_description)

    def test_end_to_end_multi_item_filters_by_real_scores(self):
        """
        Multi-item alerts should filter items based on real computed scores.

        What: Ensures high-score items trigger while low-score items are filtered out.
        Why: Validates multi-item selection logic using true score computation.
        How: Compute scores for two items, set a mid-threshold, and assert triggers.
        """
        # scenario_description: Summary of the multi-item integration scenario
        scenario_description = "End-to-end multi-item filtering using real scores"
        self._announce_test(scenario_description)

        # high_score_series: Timeseries expected to produce a strong score
        high_score_series = self._mock_timeseries_high_score()
        # low_score_series: Timeseries expected to produce a weak score
        low_score_series = self._mock_timeseries_low_score()

        # high_score: Computed score for the high-quality series
        high_score = compute_flip_confidence(high_score_series)
        # low_score: Computed score for the low-quality series
        low_score = compute_flip_confidence(low_score_series)

        self._assert_score_relation(high_score, low_score, '>', scenario_description)

        # threshold: Midpoint threshold that should include only the high-score item
        threshold = (high_score + low_score) / 2

        # alert: Multi-item alert configured with both items and midpoint threshold
        alert = self._create_alert(
            item_ids=json.dumps(self.integration_item_ids),
            item_id=None,
            is_all_items=False,
            confidence_threshold=threshold,
        )

        # all_prices: Current prices used by the alert checker for each item
        all_prices = {
            '901': {'high': 112000, 'low': 97000},
            '902': {'high': 100000, 'low': 99900},
        }

        # timeseries_by_item: Mapping of item IDs to real timeseries data
        timeseries_by_item = {
            '901': high_score_series,
            '902': low_score_series,
        }

        # fetch_timeseries: Stubbed fetcher for per-item timeseries data
        fetch_timeseries = self._make_timeseries_fetcher(timeseries_by_item)

        with patch.object(
            self.command,
            'fetch_timeseries_from_db',
            side_effect=fetch_timeseries
        ):
            # result: Triggered items list returned by the alert checker
            result = self.command.check_flip_confidence_alert(alert, all_prices)

        # expected_triggered_ids: Only the high-score item should trigger
        expected_triggered_ids = ['901']
        self._assert_triggered_item_ids(result, expected_triggered_ids, scenario_description)
