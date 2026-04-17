import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Website.models import Alert, HourlyItemVolume


class AlertDetailDumpVolumeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='alert_detail_dump_volume',
            password='test-password',
        )

    def setUp(self):
        self.client.force_login(self.user)

    @patch('Website.views.get_all_current_prices', return_value={})
    def test_dump_alert_detail_backfills_hourly_volume_for_legacy_triggered_rows(self, _mock_prices):
        item_id = 4151
        item_name = 'Abyssal whip'

        HourlyItemVolume.objects.create(
            item_id=item_id,
            item_name=item_name,
            volume=150_000_000,
            timestamp=str(int(timezone.now().timestamp())),
        )

        alert = Alert.objects.create(
            user=self.user,
            alert_name='Legacy dump alert',
            type='dump',
            item_name=item_name,
            item_ids=json.dumps([item_id]),
            is_active=True,
            is_triggered=True,
            triggered_at=timezone.now(),
            triggered_data=json.dumps([
                {
                    'item_id': item_id,
                    'item_name': item_name,
                    'fair_value': 1_000,
                    'current_low': 900,
                    'discount_pct': 10.0,
                    'sell_ratio': 0.8,
                    'rel_vol': 2.5,
                    'shock_sigma': -3.1,
                }
            ]),
        )

        response = self.client.get(reverse('alert_detail', args=[alert.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '150,000,000')
        self.assertNotContains(response, 'Vol: N/A')
