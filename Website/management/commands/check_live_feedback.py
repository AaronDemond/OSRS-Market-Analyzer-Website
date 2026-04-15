import time

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from Website.live_feedback import (
    STATUS_NO_PRICE,
    STATUS_WATCHING,
    evaluate_watch,
    fetch_latest_prices,
)
from Website.models import LiveFeedbackWatch


LIVE_FEEDBACK_STATE_FIELDS = [
    'is_triggered',
    'is_dismissed',
    'last_checked_at',
    'last_market_price',
    'last_market_time',
    'last_status',
    'triggered_at',
]


class Command(BaseCommand):
    help = 'Checks Live Feedback watches for buy overcuts and sell undercuts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run one Live Feedback check and exit.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Seconds between checks when running continuously.',
        )

    def handle(self, *args, **options):
        interval = max(options['interval'], 1)

        while True:
            self.check_once()
            if options['once']:
                break
            time.sleep(interval)

    def check_once(self):
        watches = list(
            LiveFeedbackWatch.objects.select_related('user').filter(is_active=True)
        )
        if not watches:
            self.stdout.write('No active Live Feedback watches to check.')
            return

        try:
            latest_prices = fetch_latest_prices()
        except (requests.RequestException, ValueError) as exc:
            self.stdout.write(self.style.ERROR(f'Failed to fetch latest Wiki prices: {exc}'))
            return

        if not isinstance(latest_prices, dict):
            self.stdout.write(self.style.ERROR('Latest Wiki response did not include price data.'))
            return

        checked_at = timezone.now()
        triggered_count = 0

        for watch in watches:
            result = evaluate_watch(watch, latest_prices)
            was_triggered = bool(watch.is_triggered)
            is_new_trigger = result.is_triggered and not was_triggered

            watch.last_checked_at = checked_at
            watch.last_market_price = result.market_price
            watch.last_market_time = result.market_time
            watch.last_status = result.status

            if result.is_triggered:
                watch.is_triggered = True
                if is_new_trigger:
                    watch.is_dismissed = False
                    watch.triggered_at = checked_at
                    triggered_count += 1
            elif result.status == STATUS_WATCHING:
                watch.is_triggered = False
                watch.is_dismissed = False
                watch.triggered_at = None
            elif result.status == STATUS_NO_PRICE and not was_triggered:
                watch.is_triggered = False

            watch.save(update_fields=LIVE_FEEDBACK_STATE_FIELDS)

            if is_new_trigger:
                self.send_live_feedback_notification(watch, result)

        self.stdout.write(
            self.style.SUCCESS(
                f'Checked {len(watches)} Live Feedback watch(es); {triggered_count} new trigger(s).'
            )
        )

    def send_live_feedback_notification(self, watch, result):
        recipients = []
        if watch.email_notification and watch.user.email:
            recipients.append(watch.user.email)
        if watch.sms_notification and watch.sms_recipient:
            recipients.append(watch.sms_recipient)

        if not recipients:
            return

        subject = 'Live Feedback Triggered'
        message = self.build_notification_message(watch, result)

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                recipient_list=recipients,
                fail_silently=False,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Notification sent for Live Feedback watch {watch.id}.'
                )
            )
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(
                    f'Failed to send notification for Live Feedback watch {watch.id}: {exc}'
                )
            )

    def build_notification_message(self, watch, result):
        side_label = 'buying' if watch.side == 'buy' else 'selling'
        market_label = 'Highest buy' if watch.side == 'buy' else 'Lowest sell'
        return (
            f'Live Feedback triggered for {watch.item_name}.\n\n'
            f'You are {side_label} at: {watch.target_price:,} gp\n'
            f'{market_label} now: {result.market_price:,} gp\n'
            f'Difference: {result.difference:,} gp\n\n'
            f'{result.message}'
        )
