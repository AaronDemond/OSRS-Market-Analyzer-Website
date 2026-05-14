import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from Website.management.commands.check_flip_alerts import Command as FlipAlertCommand
from Website.models import FlipAlert, FlipProfit


class FlipAlertApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='flip_alert_api_user',
            password='test-password',
        )
        cls.other_user = User.objects.create_user(
            username='flip_alert_api_other',
            password='test-password',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _create_flip_profit(self, *, quantity_held):
        return FlipProfit.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            average_cost=100,
            realized_net=0,
            unrealized_net=0,
            quantity_held=quantity_held,
        )

    @patch('Website.views.views.get_all_current_prices')
    def test_create_flip_alert_seeds_current_trigger_state(self, mock_get_prices):
        self._create_flip_profit(quantity_held=10)
        mock_get_prices.return_value = {
            '4151': {'high': 120, 'low': 120},
        }

        response = self.client.post(
            reverse('create_flip_alert'),
            data=json.dumps({
                'item_ids': [4151],
                'threshold_kind': 'gp_profit',
                'threshold_value': 100,
                'email_notification': True,
                'sms_notification': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['alert']['tracked_item_ids'], [4151])
        self.assertTrue(payload['alert']['is_triggered'])
        self.assertEqual(payload['alert']['active_item_ids'], [4151])

        alert = FlipAlert.objects.get(user=self.user)
        self.assertEqual(alert.threshold_kind, 'gp_profit')
        self.assertEqual(alert.tracked_items, [{'item_id': 4151, 'item_name': 'Abyssal whip'}])

    @patch('Website.views.views.get_all_current_prices')
    @patch('Website.management.commands.check_flip_alerts.Command.send_alert_notification')
    def test_create_flip_alert_sends_immediate_notification_when_threshold_already_met(self, mock_send_notification, mock_get_prices):
        self._create_flip_profit(quantity_held=10)
        mock_get_prices.return_value = {
            '4151': {'high': 120, 'low': 120},
        }

        response = self.client.post(
            reverse('create_flip_alert'),
            data=json.dumps({
                'item_ids': [4151],
                'threshold_kind': 'gp_profit',
                'threshold_value': 100,
                'email_notification': True,
                'sms_notification': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        mock_send_notification.assert_called_once()
        sent_alert, sent_message = mock_send_notification.call_args.args
        self.assertEqual(sent_alert.user, self.user)
        self.assertIn('Abyssal whip', sent_message)
        self.assertIn('Threshold met: profit 100 gp', sent_message)
        self.assertIn('Abyssal whip reached a profit of 176 gp.', sent_message)

    @patch('Website.views.views.get_all_current_prices')
    def test_create_flip_alert_rejects_items_without_active_holdings(self, mock_get_prices):
        self._create_flip_profit(quantity_held=0)
        mock_get_prices.return_value = {
            '4151': {'high': 120, 'low': 120},
        }

        response = self.client.post(
            reverse('create_flip_alert'),
            data=json.dumps({
                'item_ids': [4151],
                'threshold_kind': 'percent_loss',
                'threshold_value': 5,
                'email_notification': True,
                'sms_notification': False,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn(4151, payload['invalid_item_ids'])
        self.assertEqual(FlipAlert.objects.count(), 0)

    @patch('Website.views.views.get_item_id_to_name_mapping')
    def test_list_and_delete_flip_alerts_are_user_scoped(self, mock_item_name_mapping):
        mock_item_name_mapping.return_value = {
            '4151': 'Abyssal whip',
            '11802': 'Armadyl godsword',
        }

        own_alert = FlipAlert.objects.create(
            user=self.user,
            tracked_items=[
                {'item_id': 4151, 'item_name': 'Item 4151'},
                {'item_id': 11802, 'item_name': 'Item 11802'},
            ],
            threshold_kind='percent_profit',
            threshold_value=1,
            email_notification=True,
        )
        other_alert = FlipAlert.objects.create(
            user=self.other_user,
            tracked_items=[{'item_id': 11802, 'item_name': 'Dragon crossbow'}],
            threshold_kind='gp_loss',
            threshold_value=500000,
            email_notification=True,
        )

        list_response = self.client.get(reverse('flip_alerts_api'))
        self.assertEqual(list_response.status_code, 200)
        alerts = list_response.json()['alerts']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['id'], own_alert.id)
        self.assertEqual(alerts[0]['tracked_item_label'], 'Abyssal whip, Armadyl godsword')
        self.assertEqual(alerts[0]['threshold_label'], 'profit 1%')
        self.assertEqual(alerts[0]['text'], 'Abyssal whip, Armadyl godsword profit 1%')

        delete_response = self.client.post(
            reverse('delete_flip_alerts'),
            data=json.dumps({'alert_ids': [own_alert.id, other_alert.id]}),
            content_type='application/json',
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(FlipAlert.objects.filter(id=own_alert.id).exists())
        self.assertTrue(FlipAlert.objects.filter(id=other_alert.id).exists())


class FlipAlertCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='flip_alert_command_user',
            password='test-password',
        )

    def setUp(self):
        self.flip_profit = FlipProfit.objects.create(
            user=self.user,
            item_id=4151,
            item_name='Abyssal whip',
            average_cost=100,
            realized_net=0,
            unrealized_net=0,
            quantity_held=10,
        )
        self.alert = FlipAlert.objects.create(
            user=self.user,
            tracked_items=[{'item_id': 4151, 'item_name': 'Abyssal whip'}],
            threshold_kind='gp_profit',
            threshold_value=100,
            email_notification=True,
            sms_notification=False,
            active_item_ids=[],
            triggered_items=[],
            is_triggered=False,
        )

    def test_checker_only_notifies_when_items_newly_enter_triggered_state(self):
        command = FlipAlertCommand()

        price_sequence = [
            {'4151': {'high': 105, 'low': 105}},
            {'4151': {'high': 120, 'low': 120}},
            {'4151': {'high': 120, 'low': 120}},
            {'4151': {'high': 100, 'low': 100}},
            {'4151': {'high': 125, 'low': 125}},
        ]

        with patch('Website.management.commands.check_flip_alerts.get_all_current_prices', side_effect=price_sequence):
            with patch.object(command, 'send_alert_notification') as mock_send:
                command.check_once()
                self.assertEqual(mock_send.call_count, 0)

                command.check_once()
                self.assertEqual(mock_send.call_count, 1)
                first_message = mock_send.call_args_list[0].args[1]
                self.assertIn('Abyssal whip', first_message)
                self.assertIn('Abyssal whip reached a profit of 176 gp.', first_message)

                command.check_once()
                self.assertEqual(mock_send.call_count, 1)

                command.check_once()
                self.alert.refresh_from_db()
                self.assertEqual(self.alert.active_item_ids, [])
                self.assertFalse(self.alert.is_triggered)
                self.assertEqual(mock_send.call_count, 1)

                command.check_once()
                self.assertEqual(mock_send.call_count, 2)
                second_message = mock_send.call_args_list[1].args[1]
                self.assertIn('Abyssal whip reached a profit of 225 gp.', second_message)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.active_item_ids, [4151])
        self.assertTrue(self.alert.is_triggered)

    def test_notification_message_uses_selected_percent_unit(self):
        self.alert.threshold_kind = 'percent_profit'

        message = FlipAlertCommand().build_flip_alert_notification_message(
            self.alert,
            [{
                'item_name': 'Abyssal whip',
                'gp_profit': 176,
                'percent_profit': 17.6,
                'quantity_held': 10,
                'current_price': 120,
            }],
        )

        self.assertIn('Threshold met: profit 100%', message)
        self.assertIn('Abyssal whip reached a profit of 17.60%.', message)

    @patch('Website.views.views.get_item_id_to_name_mapping')
    def test_checker_batches_multi_item_trigger_into_one_notification_with_resolved_names(self, mock_item_name_mapping):
        mock_item_name_mapping.return_value = {
            '4151': 'Abyssal whip',
            '11802': 'Armadyl godsword',
        }

        FlipProfit.objects.create(
            user=self.user,
            item_id=11802,
            item_name=None,
            average_cost=100,
            realized_net=0,
            unrealized_net=0,
            quantity_held=10,
        )
        self.alert.tracked_items = [
            {'item_id': 4151, 'item_name': 'Item 4151'},
            {'item_id': 11802, 'item_name': 'Item 11802'},
        ]
        self.alert.save(update_fields=['tracked_items'])

        command = FlipAlertCommand()

        with patch('Website.management.commands.check_flip_alerts.get_all_current_prices', return_value={
            '4151': {'high': 120, 'low': 120},
            '11802': {'high': 130, 'low': 130},
        }):
            with patch.object(command, 'send_alert_notification') as mock_send:
                command.check_once()

        self.assertEqual(mock_send.call_count, 1)
        message = mock_send.call_args.args[1]
        self.assertIn('Abyssal whip reached a profit of 176 gp.', message)
        self.assertIn('Armadyl godsword reached a profit of 274 gp.', message)