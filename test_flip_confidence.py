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

class FlipConfidenceAlertTests(TestCase):
    """
    Tests for the check_flip_confidence_alert() method in check_alerts.py.
    
    What: Verifies that flip_confidence alerts correctly trigger based on
          confidence scores computed from mocked timeseries data.
    Why: Users rely on these alerts firing correctly when conditions are met.
    How: Creates Alert instances, mocks external API calls, and verifies trigger behavior.
    """

    def setUp(self):
        """
        Set up shared fixtures for each test.
        
        What: Creates a test user and a basic flip_confidence alert.
        Why: Each test needs a consistent starting alert configuration.
        How: Creates a User and Alert with reasonable default settings.
        """
        # test_user: User instance to own the alert
        self.test_user = User.objects.create_user(
            username='confidence_user',
            email='confidence_user@example.com',
            password='testpass123'
        )
        
        # item_id: The OSRS item ID being monitored
        self.item_id = 4151  # Abyssal whip

    def _create_alert(self, **overrides):
        """
        Helper to create a flip_confidence alert with sensible defaults.
        
        What: Factory method for creating test alerts with override capability.
        Why: Avoids repeating all fields in every test case.
        How: Merges overrides with defaults, then creates Alert instance.
        
        Args:
            **overrides: Any Alert field values to override.
        
        Returns:
            Alert: The created Alert instance.
        """
        defaults = {
            'user': self.test_user,
            'alert_name': 'Test Confidence Alert',
            'type': 'flip_confidence',
            'item_name': 'Abyssal whip',
            'item_id': self.item_id,
            'is_active': True,
            'is_triggered': False,
            'confidence_timestep': '1h',
            'confidence_lookback': 24,
            'confidence_threshold': 60.0,
            'confidence_trigger_rule': 'crosses_above',
        }
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
        data = []
        for i in range(24):
            # Gradually increasing prices with 3% spread and decent volume
            high_price = 100000 + (i * 500)
            low_price = int(high_price * 0.97)  # ~3% spread
            data.append({
                "avgHighPrice": high_price,
                "avgLowPrice": low_price,
                "highPriceVolume": 300 + i * 10,
                "lowPriceVolume": 200 + i * 5,
                "timestamp": int(time.time()) - (24 - i) * 3600,
            })
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
        data = []
        for i in range(24):
            # Declining prices with tiny spread and low volume
            high_price = 100000 - (i * 1000)
            low_price = high_price - 100  # Very small spread
            data.append({
                "avgHighPrice": high_price,
                "avgLowPrice": low_price,
                "highPriceVolume": 5,
                "lowPriceVolume": 10,
                "timestamp": int(time.time()) - (24 - i) * 3600,
            })
        return data

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
            command, 'fetch_timeseries_data',
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
            command, 'fetch_timeseries_data',
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
            command, 'fetch_timeseries_data',
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
        How: Mock fetch_timeseries_data to return only 2 points.
        """
        alert = self._create_alert(confidence_threshold=10.0)
        command = Command()

        all_prices = {
            str(self.item_id): {'high': 112000, 'low': 97000}
        }

        with patch.object(
            command, 'fetch_timeseries_data',
            return_value=[
                {"avgHighPrice": 100, "avgLowPrice": 95, "highPriceVolume": 10, "lowPriceVolume": 10},
                {"avgHighPrice": 101, "avgLowPrice": 96, "highPriceVolume": 10, "lowPriceVolume": 10},
            ]
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
