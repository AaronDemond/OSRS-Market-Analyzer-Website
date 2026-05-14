import re
import time

from django.utils import timezone

from Website.management.commands.check_alerts import Command as AlertNotificationCommand
from Website.models import (
    FlipAlert,
    FlipProfit,
    get_all_current_prices,
    build_flip_alert_position_snapshot,
    flip_alert_threshold_is_met,
)


FLIP_ALERT_STATE_FIELDS = [
    'active_item_ids',
    'triggered_items',
    'is_triggered',
    'triggered_at',
    'updated_at',
]

GENERIC_FLIP_ALERT_ITEM_NAME_RE = re.compile(r'^Item\s+\d+$', re.IGNORECASE)


class Command(AlertNotificationCommand):
    help = 'Checks My Flips FlipAlerts against current held-position profit and loss thresholds.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run one FlipAlert evaluation cycle and exit.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=30,
            help='Seconds between checks when running continuously.',
        )

    def handle(self, *args, **options):
        interval = max(options['interval'], 1)
        self.stdout.write(self.style.SUCCESS('Starting FlipAlert checker...'))

        while True:
            self.check_once()
            if options['once']:
                break
            time.sleep(interval)

    def check_once(self):
        alerts = list(FlipAlert.objects.select_related('user').filter(is_active=True))
        if not alerts:
            self.stdout.write('No active FlipAlerts to check.')
            return

        all_prices = get_all_current_prices()
        if not all_prices:
            self.stdout.write(self.style.WARNING('No current price data available for FlipAlert evaluation.'))
            return

        tracked_item_ids = set()
        user_ids = set()
        for alert in alerts:
            user_ids.add(alert.user_id)
            tracked_item_ids.update(alert.tracked_item_ids())

        flip_profit_map = {
            (flip_profit.user_id, int(flip_profit.item_id)): flip_profit
            for flip_profit in FlipProfit.objects.filter(
                user_id__in=user_ids,
                item_id__in=tracked_item_ids,
            )
        }

        now = timezone.now()
        alerts_with_new_triggers = 0
        items_newly_triggered = 0

        for alert in alerts:
            current_triggered_items = []
            current_active_item_ids = []

            for item_id in alert.tracked_item_ids():
                flip_profit = flip_profit_map.get((alert.user_id, item_id))
                if not flip_profit:
                    continue

                snapshot = build_flip_alert_position_snapshot(
                    flip_profit,
                    all_prices.get(str(item_id)),
                )
                if not snapshot:
                    continue

                if flip_alert_threshold_is_met(snapshot, alert.threshold_kind, alert.threshold_value):
                    current_active_item_ids.append(snapshot['item_id'])
                    current_triggered_items.append(snapshot)

            previous_active_item_ids = set()
            for raw_item_id in alert.active_item_ids or []:
                try:
                    previous_active_item_ids.add(int(raw_item_id))
                except (TypeError, ValueError):
                    continue

            current_active_item_id_set = set(current_active_item_ids)
            newly_triggered_item_ids = current_active_item_id_set - previous_active_item_ids
            newly_triggered_items = [
                item for item in current_triggered_items
                if item['item_id'] in newly_triggered_item_ids
            ]

            alert.active_item_ids = current_active_item_ids
            alert.triggered_items = current_triggered_items
            alert.is_triggered = bool(current_active_item_ids)

            if newly_triggered_items:
                alert.triggered_at = now
            elif not current_active_item_ids:
                alert.triggered_at = None

            alert.save(update_fields=FLIP_ALERT_STATE_FIELDS)

            if newly_triggered_items and (alert.email_notification or alert.sms_notification):
                alerts_with_new_triggers += 1
                items_newly_triggered += len(newly_triggered_items)
                self.send_alert_notification(
                    alert,
                    self.build_flip_alert_notification_message(alert, newly_triggered_items),
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Checked {len(alerts)} FlipAlert(s); '
                f'{alerts_with_new_triggers} alert(s) had new triggers '
                f'covering {items_newly_triggered} item(s).'
            )
        )

    def describe_flip_alert_value(self, alert, item):
        gp_profit = abs(int(item.get('gp_profit') or 0))
        percent_profit = abs(float(item.get('percent_profit') or 0))

        if alert.threshold_kind == 'gp_profit':
            return f'profit of {gp_profit:,} gp'
        if alert.threshold_kind == 'gp_loss':
            return f'loss of {gp_profit:,} gp'
        if alert.threshold_kind == 'percent_profit':
            return f'profit of {percent_profit:.2f}%'
        if alert.threshold_kind == 'percent_loss':
            return f'loss of {percent_profit:.2f}%'

        return f'profit/loss of {gp_profit:,} gp'

    def describe_flip_alert_threshold(self, alert):
        threshold_value = abs(float(alert.threshold_value or 0))

        if alert.threshold_kind == 'gp_profit':
            return f'profit {int(round(threshold_value)):,} gp'
        if alert.threshold_kind == 'gp_loss':
            return f'loss {int(round(threshold_value)):,} gp'
        if alert.threshold_kind == 'percent_profit':
            return f'profit {threshold_value:g}%'
        if alert.threshold_kind == 'percent_loss':
            return f'loss {threshold_value:g}%'

        return str(alert.threshold_value)

    def get_flip_alert_item_name_mapping(self):
        item_name_mapping = getattr(self, '_flip_alert_item_name_mapping', None)
        if item_name_mapping is None:
            from Website.views.views import get_item_id_to_name_mapping

            item_name_mapping = get_item_id_to_name_mapping() or {}
            self._flip_alert_item_name_mapping = item_name_mapping
        return item_name_mapping

    def resolve_flip_alert_item_name(self, alert, item):
        item_id = item.get('item_id')
        raw_name = str(item.get('item_name') or '').strip()

        if raw_name and not GENERIC_FLIP_ALERT_ITEM_NAME_RE.fullmatch(raw_name):
            return raw_name

        for tracked_item in alert.tracked_items or []:
            if not isinstance(tracked_item, dict):
                continue
            try:
                tracked_item_id = int(tracked_item.get('item_id'))
            except (TypeError, ValueError):
                continue
            if tracked_item_id != item_id:
                continue

            tracked_item_name = str(tracked_item.get('item_name') or '').strip()
            if tracked_item_name and not GENERIC_FLIP_ALERT_ITEM_NAME_RE.fullmatch(tracked_item_name):
                return tracked_item_name

        resolved_name = self.get_flip_alert_item_name_mapping().get(str(item_id))
        if resolved_name:
            return resolved_name

        if raw_name:
            return raw_name
        if item_id is not None:
            return f'Item {item_id}'
        return 'Unknown item'

    def build_flip_alert_notification_message(self, alert, triggered_items):
        lines = [
            f'FlipAlert triggered: {alert}',
            f'Threshold met: {self.describe_flip_alert_threshold(alert)}',
            '',
            'The following held positions crossed your alert threshold:',
        ]

        for item in triggered_items:
            quantity_held = int(item.get('quantity_held') or 0)
            current_price = int(item.get('current_price') or 0)
            trigger_value = self.describe_flip_alert_value(alert, item)
            item_name = self.resolve_flip_alert_item_name(alert, item)
            lines.append(
                f"- {item_name} reached a {trigger_value}. "
                f"Quantity held: {quantity_held:,}. "
                f"Current price: {current_price:,} gp."
            )

        return '\n'.join(lines)