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
from Website.models import LiveFeedbackWatch


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

    @patch('Website.views.get_item_mapping')
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

    @patch('Website.views.get_item_mapping')
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

    @patch('Website.views.get_item_mapping')
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

    @patch('Website.views.get_item_mapping')
    @patch('Website.views.get_all_current_prices')
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
