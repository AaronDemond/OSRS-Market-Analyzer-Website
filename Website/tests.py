import json
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Website.live_feedback import (
    STATUS_NO_PRICE,
    STATUS_OVERCUT,
    STATUS_UNDERCUT,
    STATUS_WATCHING,
    evaluate_live_feedback,
)
from Website.models import AllTimeData, LiveFeedbackWatch, TwentyFourHourTimeSeries


class FlipFinderPageTests(TestCase):
    def test_flip_finder_page_renders_public_mockup(self):
        response = self.client.get(reverse('flip_finder'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'flip_finder.html')
        self.assertContains(response, 'Flip Finder')
        self.assertContains(response, 'data-timeframe="custom"')
        self.assertContains(response, 'ffCustomDateModal')
        self.assertContains(response, 'ffSelectedIconSlot')
        self.assertContains(response, 'ffResultsCustomRange')


class FlipFinderApiTests(TestCase):
    """
    Verify the database-backed Flip Finder API contract.

    What: Exercises the result and history endpoints with small local fixtures.
    Why: The frontend depends on stable local-data payloads now that mock items
         have been removed.
    How: Seed the exact time-series models used by each timeframe source and
         assert the API chooses, filters, sorts, and caps rows correctly.
    """

    latest_timestamp = 1_700_000_000
    earlier_timestamp = latest_timestamp - 86_400

    def create_twentyfour_snapshot(self, item_id, item_name, price, timestamp, volume=10):
        """Create a 24h row whose midpoint equals price and volume is per side."""
        return TwentyFourHourTimeSeries.objects.create(
            item_id=item_id,
            item_name=item_name,
            avg_low_price=price - 1,
            avg_high_price=price + 1,
            high_price_volume=volume,
            low_price_volume=volume,
            timestamp=str(timestamp),
        )

    def create_all_time_snapshot(self, item_id, item_name, price, timestamp, volume=None):
        """Create one all-time row using the normalized price source."""
        return AllTimeData.objects.create(
            item_id=item_id,
            item_name=item_name,
            item_price=price,
            volume=volume,
            timestamp=timestamp,
        )

    def test_results_use_twentyfour_midpoints_for_bounded_ranges(self):
        self.create_twentyfour_snapshot(100, 'Low rune', 130, self.earlier_timestamp)
        self.create_twentyfour_snapshot(100, 'Low rune', 102, self.latest_timestamp, volume=25)
        self.create_twentyfour_snapshot(101, 'High rune', 200, self.earlier_timestamp)
        self.create_twentyfour_snapshot(101, 'High rune', 250, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '5',
            'signal': 'low',
            'sort': 'closest',
            'sortDirection': 'asc',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['source'], 'twenty_four_hour_time_series')
        self.assertEqual(payload['meta']['priceBasis'], 'midpoint')
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Low rune')
        self.assertEqual(payload['results'][0]['currentPrice'], 102)
        self.assertEqual(payload['results'][0]['periodLow'], 102)
        self.assertEqual(payload['results'][0]['periodHigh'], 130)
        self.assertEqual(payload['results'][0]['volume'], 5100)

    def test_results_are_paginated_at_50(self):
        # Every seeded item is exactly at its latest low, so all 105 match while
        # the response body still stays bounded for the UI table.
        for item_number in range(105):
            item_id = 1_000 + item_number
            item_name = f'Bulk item {item_number:03d}'
            self.create_twentyfour_snapshot(item_id, item_name, 150, self.earlier_timestamp)
            self.create_twentyfour_snapshot(item_id, item_name, 100, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['totalMatches'], 105)
        self.assertEqual(len(payload['results']), 50)
        self.assertEqual(payload['page'], 1)
        self.assertEqual(payload['pageSize'], 50)
        self.assertTrue(payload['hasNextPage'])
        self.assertTrue(payload['truncated'])

        page_two_response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
            'page': '2',
        })

        self.assertEqual(page_two_response.status_code, 200)
        page_two_payload = page_two_response.json()
        self.assertEqual(page_two_payload['totalMatches'], 105)
        self.assertEqual(len(page_two_payload['results']), 50)
        self.assertEqual(page_two_payload['page'], 2)
        self.assertTrue(page_two_payload['hasNextPage'])
        self.assertTrue(page_two_payload['hasPreviousPage'])

    def test_results_exclude_items_without_names(self):
        self.create_twentyfour_snapshot(260, '', 150, self.earlier_timestamp)
        self.create_twentyfour_snapshot(260, '', 100, self.latest_timestamp)
        self.create_twentyfour_snapshot(261, 'Named item', 150, self.earlier_timestamp)
        self.create_twentyfour_snapshot(261, 'Named item', 100, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Named item')

    def test_all_time_results_use_all_time_source(self):
        self.create_all_time_snapshot(200, 'All-time shard', 50, 10)
        self.create_all_time_snapshot(200, 'All-time shard', 90, 20)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '1',
            'signal': 'high',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['source'], 'all_time_data')
        self.assertEqual(payload['meta']['priceBasis'], 'item_price')
        self.assertEqual(payload['results'][0]['name'], 'All-time shard')
        self.assertEqual(payload['results'][0]['currentPrice'], 90)
        self.assertEqual(payload['results'][0]['periodLow'], 50)
        self.assertEqual(payload['results'][0]['periodHigh'], 90)

    def test_all_time_results_classify_against_full_history(self):
        self.create_all_time_snapshot(201, 'All low candidate', 200, 5)
        self.create_all_time_snapshot(201, 'All low candidate', 100, 10)
        self.create_all_time_snapshot(201, 'All low candidate', 104, 20)
        self.create_all_time_snapshot(202, 'All high candidate', 100, 10)
        self.create_all_time_snapshot(202, 'All high candidate', 196, 20)
        self.create_all_time_snapshot(203, 'All both candidate', 75, 20)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '5',
            'signal': 'both',
            'sort': 'name',
        })

        self.assertEqual(response.status_code, 200)
        results_by_name = {result['name']: result for result in response.json()['results']}
        self.assertEqual(results_by_name['All low candidate']['signal'], 'low')
        self.assertEqual(results_by_name['All low candidate']['periodLow'], 100)
        self.assertEqual(results_by_name['All high candidate']['signal'], 'high')
        self.assertEqual(results_by_name['All high candidate']['periodHigh'], 196)
        self.assertEqual(results_by_name['All both candidate']['signal'], 'both')

    def test_all_time_results_are_paginated_at_50(self):
        for item_number in range(55):
            item_id = 2_000 + item_number
            item_name = f'All bulk item {item_number:03d}'
            self.create_all_time_snapshot(item_id, item_name, 150, 10)
            self.create_all_time_snapshot(item_id, item_name, 100, 20)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '1',
            'signal': 'low',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['totalMatches'], 55)
        self.assertEqual(len(payload['results']), 50)
        self.assertTrue(payload['hasNextPage'])

        page_two_response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '1',
            'signal': 'low',
            'page': '2',
        })

        self.assertEqual(page_two_response.status_code, 200)
        page_two_payload = page_two_response.json()
        self.assertEqual(len(page_two_payload['results']), 5)
        self.assertTrue(page_two_payload['hasPreviousPage'])
        self.assertFalse(page_two_payload['hasNextPage'])

    def test_custom_timeframe_results_use_selected_start_date(self):
        selected_start = 1_704_067_200
        self.create_all_time_snapshot(205, 'Custom shard', 500, selected_start - 86_400)
        self.create_all_time_snapshot(205, 'Custom shard', 100, selected_start)
        self.create_all_time_snapshot(205, 'Custom shard', 200, selected_start + 86_400)
        self.create_all_time_snapshot(205, 'Custom shard', 104, selected_start + 172_800)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'custom',
            'customDate': '2024-01-01',
            'percent': '5',
            'signal': 'low',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['source'], 'all_time_data')
        self.assertEqual(payload['meta']['timeframe'], 'custom')
        self.assertEqual(payload['meta']['rangeStart'], selected_start)
        self.assertEqual(payload['results'][0]['name'], 'Custom shard')
        self.assertEqual(payload['results'][0]['currentPrice'], 104)
        self.assertEqual(payload['results'][0]['periodLow'], 100)
        self.assertEqual(payload['results'][0]['periodHigh'], 200)

    def test_custom_timeframe_requires_valid_date(self):
        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'custom',
            'percent': '5',
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('customDate', response.json()['error'])

    def test_min_volume_filters_by_latest_twentyfour_snapshot_gp_volume(self):
        self.create_twentyfour_snapshot(210, 'Thin volume', 150, self.earlier_timestamp, volume=500)
        self.create_twentyfour_snapshot(210, 'Thin volume', 100, self.latest_timestamp, volume=20)
        self.create_twentyfour_snapshot(211, 'Deep volume', 150, self.earlier_timestamp, volume=5)
        self.create_twentyfour_snapshot(211, 'Deep volume', 100, self.latest_timestamp, volume=30)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
            'minVolume': '5000',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['minVolume'], 5000)
        self.assertTrue(payload['meta']['volumeFilterApplied'])
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Deep volume')
        self.assertEqual(payload['results'][0]['volume'], 6000)

    def test_min_price_filters_by_current_price(self):
        self.create_twentyfour_snapshot(220, 'Cheap current', 180, self.earlier_timestamp)
        self.create_twentyfour_snapshot(220, 'Cheap current', 100, self.latest_timestamp)
        self.create_twentyfour_snapshot(221, 'Priced current', 180, self.earlier_timestamp)
        self.create_twentyfour_snapshot(221, 'Priced current', 125, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
            'min_price': '120',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['minPrice'], 120)
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Priced current')
        self.assertEqual(payload['results'][0]['currentPrice'], 125)

    def test_all_time_min_price_filters_current_price(self):
        self.create_all_time_snapshot(230, 'Low all current', 50, 10)
        self.create_all_time_snapshot(230, 'Low all current', 90, 20)
        self.create_all_time_snapshot(231, 'High all current', 80, 10)
        self.create_all_time_snapshot(231, 'High all current', 120, 20)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '1',
            'signal': 'high',
            'minPrice': '100',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['minPrice'], 100)
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'High all current')
        self.assertEqual(payload['results'][0]['currentPrice'], 120)

    def test_all_time_ignores_min_volume_filter(self):
        self.create_all_time_snapshot(240, 'Volume-free all', 50, 10)
        self.create_all_time_snapshot(240, 'Volume-free all', 90, 20)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': 'all',
            'percent': '1',
            'signal': 'high',
            'minVolume': '9999999999',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['minVolume'], 9_999_999_999)
        self.assertFalse(payload['meta']['volumeFilterApplied'])
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Volume-free all')
        self.assertIsNone(payload['results'][0]['volume'])

    def test_invalid_filter_values_default_without_error(self):
        self.create_twentyfour_snapshot(250, 'Safe defaults', 150, self.earlier_timestamp)
        self.create_twentyfour_snapshot(250, 'Safe defaults', 100, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_results_api'), {
            'timeframe': '24h',
            'percent': '1',
            'signal': 'low',
            'minVolume': 'not-a-number',
            'minPrice': '-5',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['meta']['minVolume'], 0)
        self.assertEqual(payload['meta']['minPrice'], 0)
        self.assertEqual(payload['totalMatches'], 1)
        self.assertEqual(payload['results'][0]['name'], 'Safe defaults')

    def test_history_returns_points_in_timestamp_order(self):
        self.create_twentyfour_snapshot(300, 'History seed', 150, self.earlier_timestamp)
        self.create_twentyfour_snapshot(300, 'History seed', 120, self.latest_timestamp)

        response = self.client.get(reverse('flip_finder_history_api'), {
            'timeframe': '24h',
            'itemId': '300',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['itemName'], 'History seed')
        self.assertEqual([point['timestamp'] for point in payload['points']], [
            self.earlier_timestamp,
            self.latest_timestamp,
        ])
        self.assertEqual(payload['periodLow'], 120)
        self.assertEqual(payload['periodHigh'], 150)

    def test_all_time_history_returns_valid_points_in_timestamp_order(self):
        self.create_all_time_snapshot(310, 'All history seed', 120, 300)
        self.create_all_time_snapshot(310, 'All history seed', 100, 100)
        self.create_all_time_snapshot(310, 'All history seed', 0, 200)

        response = self.client.get(reverse('flip_finder_history_api'), {
            'timeframe': 'all',
            'itemId': '310',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['itemName'], 'All history seed')
        self.assertEqual(payload['source'], 'all_time_data')
        self.assertEqual(payload['priceBasis'], 'item_price')
        self.assertEqual([point['timestamp'] for point in payload['points']], [100, 300])
        self.assertEqual(payload['periodLow'], 100)
        self.assertEqual(payload['periodHigh'], 120)
        self.assertEqual(payload['currentPrice'], 120)

    def test_custom_history_uses_selected_start_date(self):
        selected_start = 1_704_067_200
        self.create_all_time_snapshot(311, 'Custom history seed', 300, selected_start - 86_400)
        self.create_all_time_snapshot(311, 'Custom history seed', 100, selected_start)
        self.create_all_time_snapshot(311, 'Custom history seed', 0, selected_start + 86_400)
        self.create_all_time_snapshot(311, 'Custom history seed', 120, selected_start + 172_800)

        response = self.client.get(reverse('flip_finder_history_api'), {
            'timeframe': 'custom',
            'customDate': '2024-01-01',
            'itemId': '311',
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['timeframe'], 'custom')
        self.assertEqual([point['timestamp'] for point in payload['points']], [selected_start, selected_start + 172_800])
        self.assertEqual(payload['periodLow'], 100)
        self.assertEqual(payload['periodHigh'], 120)

    def test_unsupported_timeframe_returns_400(self):
        response = self.client.get(reverse('flip_finder_results_api'), {'timeframe': '1h'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('Unsupported timeframe', response.json()['error'])


class LiveFeedbackEvaluationTests(TestCase):
    def test_sell_triggers_only_when_low_is_below_target(self):
        result = evaluate_live_feedback('sell', 100, {'low': 99, 'lowTime': 123})
        self.assertEqual(result.status, STATUS_UNDERCUT)
        self.assertTrue(result.is_triggered)
        self.assertEqual(result.difference, 1)

        equal_result = evaluate_live_feedback('sell', 100, {'low': 100, 'lowTime': 123})
        self.assertEqual(equal_result.status, STATUS_WATCHING)
        self.assertFalse(equal_result.is_triggered)

    def test_buy_triggers_only_when_high_is_above_target(self):
        result = evaluate_live_feedback('buy', 100, {'high': 101, 'highTime': 123})
        self.assertEqual(result.status, STATUS_OVERCUT)
        self.assertTrue(result.is_triggered)
        self.assertEqual(result.difference, 1)

        equal_result = evaluate_live_feedback('buy', 100, {'high': 100, 'highTime': 123})
        self.assertEqual(equal_result.status, STATUS_WATCHING)
        self.assertFalse(equal_result.is_triggered)

    def test_missing_price_returns_no_price(self):
        result = evaluate_live_feedback('sell', 100, {})
        self.assertEqual(result.status, STATUS_NO_PRICE)
        self.assertFalse(result.is_triggered)


class LiveFeedbackApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='password123',
        )
        self.other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='password123',
        )
        self.item_mapping = {
            'abyssal whip': {'id': 4151, 'name': 'Abyssal whip', 'icon': 'Abyssal_whip.png'},
            'dragon scimitar': {'id': 4587, 'name': 'Dragon scimitar', 'icon': 'Dragon_scimitar.png'},
        }

    def login(self, user=None):
        self.client.force_login(user or self.user)

    @patch('Website.views.views.get_item_mapping')
    def test_create_requires_sms_recipient_when_sms_enabled(self, mock_mapping):
        mock_mapping.return_value = self.item_mapping
        self.login()

        response = self.client.post(
            reverse('create_live_feedback_watch'),
            data=json.dumps({
                'item_id': 4151,
                'side': 'buy',
                'target_price': 100,
                'sms_notification': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(LiveFeedbackWatch.objects.count(), 0)

    @patch('Website.views.views.get_item_mapping')
    def test_create_accepts_email_to_sms_gateway(self, mock_mapping):
        mock_mapping.return_value = self.item_mapping
        self.login()

        response = self.client.post(
            reverse('create_live_feedback_watch'),
            data=json.dumps({
                'item_id': 4151,
                'side': 'buy',
                'target_price': 100,
                'email_notification': True,
                'sms_notification': True,
                'sms_recipient': '15551234567@example-sms.test',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        watch = LiveFeedbackWatch.objects.get()
        self.assertTrue(watch.email_notification)
        self.assertTrue(watch.sms_notification)
        self.assertEqual(watch.sms_recipient, '15551234567@example-sms.test')

    @patch('Website.views.views.get_item_mapping')
    def test_update_changes_parameters_and_resets_runtime_state(self, mock_mapping):
        mock_mapping.return_value = self.item_mapping
        self.login()
        watch = LiveFeedbackWatch.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            side='buy',
            target_price=100,
            is_active=False,
            is_triggered=True,
            is_dismissed=True,
            last_status=STATUS_OVERCUT,
            last_checked_at=timezone.now(),
            last_market_price=120,
            last_market_time=123,
            triggered_at=timezone.now(),
        )

        response = self.client.post(
            reverse('update_live_feedback_watch', args=[watch.id]),
            data=json.dumps({
                'item_id': 4587,
                'side': 'sell',
                'target_price': 200,
                'email_notification': False,
                'sms_notification': True,
                'sms_recipient': '15557654321@example-sms.test',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        watch.refresh_from_db()
        self.assertEqual(watch.item_id, 4587)
        self.assertEqual(watch.item_name, 'Dragon scimitar')
        self.assertEqual(watch.side, 'sell')
        self.assertEqual(watch.target_price, 200)
        self.assertTrue(watch.sms_notification)
        self.assertEqual(watch.sms_recipient, '15557654321@example-sms.test')
        self.assertTrue(watch.is_active)
        self.assertFalse(watch.is_triggered)
        self.assertFalse(watch.is_dismissed)
        self.assertEqual(watch.last_status, STATUS_WATCHING)
        self.assertIsNone(watch.last_checked_at)
        self.assertIsNone(watch.last_market_price)
        self.assertIsNone(watch.last_market_time)
        self.assertIsNone(watch.triggered_at)

    @patch('Website.views.views.get_item_mapping')
    @patch('Website.views.views.get_all_current_prices')
    def test_list_returns_current_trigger_status(self, mock_prices, mock_mapping):
        mock_prices.return_value = {'4151': {'high': 110, 'low': 90, 'highTime': 123, 'lowTime': 120}}
        mock_mapping.return_value = self.item_mapping
        self.login()
        LiveFeedbackWatch.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            side='buy',
            target_price=100,
        )

        response = self.client.get(reverse('live_feedback_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['watches'][0]['status'], STATUS_OVERCUT)
        self.assertTrue(payload['watches'][0]['is_currently_triggered'])
        self.assertEqual(payload['stats']['triggered'], 1)
        self.assertEqual(payload['watches'][0]['market_data'], {
            'id': 4151,
            'name': 'Abyssal whip',
            'icon': 'Abyssal_whip.png',
            'high': 110,
            'low': 90,
            'highTime': 123,
            'lowTime': 120,
        })

    def test_user_cannot_delete_another_users_watch(self):
        watch = LiveFeedbackWatch.objects.create(
            user=self.other_user,
            item_id=4151,
            item_name='Abyssal whip',
            side='sell',
            target_price=100,
        )
        self.login(self.user)

        response = self.client.post(reverse('delete_live_feedback_watch', args=[watch.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(LiveFeedbackWatch.objects.filter(id=watch.id).exists())

    def test_user_cannot_update_another_users_watch(self):
        watch = LiveFeedbackWatch.objects.create(
            user=self.other_user,
            item_id=4151,
            item_name='Abyssal whip',
            side='sell',
            target_price=100,
        )
        self.login(self.user)

        response = self.client.post(
            reverse('update_live_feedback_watch', args=[watch.id]),
            data=json.dumps({
                'item_id': 4151,
                'side': 'buy',
                'target_price': 200,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        watch.refresh_from_db()
        self.assertEqual(watch.side, 'sell')
        self.assertEqual(watch.target_price, 100)

    def test_toggle_and_dismiss_are_user_owned(self):
        watch = LiveFeedbackWatch.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            side='sell',
            target_price=100,
            is_triggered=True,
        )
        self.login()

        dismiss_response = self.client.post(reverse('dismiss_live_feedback_watch', args=[watch.id]))
        self.assertEqual(dismiss_response.status_code, 200)
        watch.refresh_from_db()
        self.assertTrue(watch.is_dismissed)

        toggle_response = self.client.post(
            reverse('toggle_live_feedback_watch', args=[watch.id]),
            data=json.dumps({'is_active': False}),
            content_type='application/json',
        )
        self.assertEqual(toggle_response.status_code, 200)
        watch.refresh_from_db()
        self.assertFalse(watch.is_active)
        self.assertFalse(watch.is_triggered)


class LiveFeedbackCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='password123',
        )

    @patch('Website.management.commands.check_live_feedback.send_mail')
    @patch('Website.management.commands.check_live_feedback.fetch_latest_prices')
    def test_command_sends_only_on_trigger_transition(self, mock_prices, mock_send_mail):
        watch = LiveFeedbackWatch.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            side='buy',
            target_price=100,
            email_notification=True,
        )

        mock_prices.return_value = {'4151': {'high': 110, 'highTime': 123}}
        call_command('check_live_feedback', '--once')
        watch.refresh_from_db()
        self.assertTrue(watch.is_triggered)
        self.assertEqual(mock_send_mail.call_count, 1)

        call_command('check_live_feedback', '--once')
        self.assertEqual(mock_send_mail.call_count, 1)

        mock_prices.return_value = {'4151': {'high': 90, 'highTime': 124}}
        call_command('check_live_feedback', '--once')
        watch.refresh_from_db()
        self.assertFalse(watch.is_triggered)

        mock_prices.return_value = {'4151': {'high': 110, 'highTime': 125}}
        call_command('check_live_feedback', '--once')
        self.assertEqual(mock_send_mail.call_count, 2)

    @patch('Website.management.commands.check_live_feedback.fetch_latest_prices')
    def test_failed_wiki_call_does_not_overwrite_watch_state(self, mock_prices):
        mock_prices.side_effect = requests.RequestException('network down')
        watch = LiveFeedbackWatch.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            side='sell',
            target_price=100,
            is_triggered=True,
            last_status=STATUS_UNDERCUT,
            last_market_price=90,
        )

        call_command('check_live_feedback', '--once')
        watch.refresh_from_db()

        self.assertTrue(watch.is_triggered)
        self.assertEqual(watch.last_status, STATUS_UNDERCUT)
        self.assertEqual(watch.last_market_price, 90)
