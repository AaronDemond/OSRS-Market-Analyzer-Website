import json
from datetime import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Website.models import Flip, TwentyFourHourTimeSeries


class FlipsEquityApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="equity_api_tester",
            password="test-password",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _aware_datetime(self, year, month, day):
        return timezone.make_aware(datetime(year, month, day, 12, 0, 0))

    def _flip(self, *, item_id, item_name, price, quantity, flip_type, date):
        return Flip.objects.create(
            user=self.user,
            item_id=item_id,
            item_name=item_name,
            price=price,
            quantity=quantity,
            type=flip_type,
            date=date,
        )

    def _snapshot(self, *, item_id, item_name, timestamp, high, low):
        return TwentyFourHourTimeSeries.objects.create(
            item_id=item_id,
            item_name=item_name,
            avg_high_price=high,
            avg_low_price=low,
            high_price_volume=100,
            low_price_volume=100,
            timestamp=str(timestamp),
        )

    def test_equity_api_starts_at_first_available_24h_bucket_and_respects_prior_flips(self):
        item_id = 4151
        item_name = "Abyssal whip"
        first_bucket = 1_735_689_600  # 2025-01-01 00:00:00 UTC
        second_bucket = first_bucket + 86_400

        self._flip(
            item_id=item_id,
            item_name=item_name,
            price=100,
            quantity=10,
            flip_type='buy',
            date=self._aware_datetime(2024, 12, 20),
        )
        self._snapshot(item_id=item_id, item_name=item_name, timestamp=first_bucket, high=120, low=120)
        self._snapshot(item_id=item_id, item_name=item_name, timestamp=second_bucket, high=125, low=125)

        response = self.client.get(reverse('flips_equity_api'), {'range': '1y'})
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload['start_timestamp'], first_bucket)
        self.assertEqual(payload['point_count'], 2)
        self.assertEqual(payload['points'][0]['timestamp'], first_bucket)
        self.assertEqual(payload['points'][0]['y'], 176)

    def test_equity_api_caps_results_to_one_year(self):
        item_id = 11802
        item_name = "Dragon crossbow"
        latest_bucket = 1_750_000_000
        older_than_year_bucket = latest_bucket - (366 * 86_400)
        inside_year_bucket = latest_bucket - (200 * 86_400)

        self._flip(
            item_id=item_id,
            item_name=item_name,
            price=200,
            quantity=5,
            flip_type='buy',
            date=self._aware_datetime(2024, 1, 10),
        )
        self._snapshot(item_id=item_id, item_name=item_name, timestamp=older_than_year_bucket, high=210, low=210)
        self._snapshot(item_id=item_id, item_name=item_name, timestamp=inside_year_bucket, high=220, low=220)
        self._snapshot(item_id=item_id, item_name=item_name, timestamp=latest_bucket, high=230, low=230)

        response = self.client.get(reverse('flips_equity_api'), {'range': '1y'})
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        timestamps = [point['timestamp'] for point in payload['points']]
        self.assertNotIn(older_than_year_bucket, timestamps)
        self.assertIn(inside_year_bucket, timestamps)
        self.assertEqual(payload['end_timestamp'], latest_bucket)
