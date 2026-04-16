"""
Focused tests for HourlyItemVolume timestamp parsing and freshness gating.

What:
    Verifies that the alert checker can normalize mixed historical timestamp
    formats and reject stale volume snapshots.

Why:
    HourlyItemVolume.timestamp is a CharField and existing scripts have stored
    Unix epoch strings, ISO-8601 strings, and plain datetime strings. Alert
    checks must choose the truly newest row by real time and must treat rows
    older than VOLUME_RECENCY_MINUTES as missing.

How:
    Exercises the Command helper methods directly and creates HourlyItemVolume
    rows in several timestamp formats to confirm get_volume_from_timeseries()
    returns the expected volume or None.
"""

from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from Website.management.commands.check_alerts import Command, VOLUME_RECENCY_MINUTES
from Website.models import HourlyItemVolume


class VolumeTimestampParsingTests(SimpleTestCase):
    """
    Unit tests for the HourlyItemVolume timestamp normalization helper.
    """

    def setUp(self):
        self.command = Command()

    def test_normalize_volume_timestamp_accepts_datetime_instance(self):
        """
        Already-materialized datetime values should normalize cleanly.
        """
        raw_timestamp = timezone.now() - timedelta(minutes=5)

        normalized_timestamp = self.command._normalize_volume_timestamp(raw_timestamp)

        self.assertIsNotNone(normalized_timestamp)
        self.assertTrue(timezone.is_aware(normalized_timestamp))
        self.assertEqual(normalized_timestamp, raw_timestamp)


class VolumeRecencyLookupTests(TestCase):
    """
    Integration tests for volume lookup freshness and mixed timestamp formats.
    """

    ITEM_ID = 4151

    def setUp(self):
        self.command = Command()

    def _create_volume(self, timestamp, volume=50_000):
        """
        Create a HourlyItemVolume row for the shared test item.
        """
        return HourlyItemVolume.objects.create(
            item_id=self.ITEM_ID,
            item_name='Abyssal whip',
            volume=volume,
            timestamp=timestamp,
        )

    def _epoch_timestamp(self, minutes_ago):
        """
        Build a Unix epoch string offset from now.
        """
        record_time = timezone.now() - timedelta(minutes=minutes_ago)
        return str(int(record_time.timestamp()))

    def _iso_timestamp(self, minutes_ago):
        """
        Build an ISO-8601 timestamp string offset from now.
        """
        record_time = timezone.now() - timedelta(minutes=minutes_ago)
        return record_time.isoformat()

    def _datetime_string_timestamp(self, minutes_ago):
        """
        Build a plain datetime string offset from now.
        """
        record_time = timezone.now() - timedelta(minutes=minutes_ago)
        naive_local_time = timezone.localtime(record_time).replace(tzinfo=None)
        return naive_local_time.strftime('%Y-%m-%d %H:%M:%S')

    def test_get_volume_from_timeseries_accepts_fresh_epoch_timestamp(self):
        """
        Fresh Unix epoch strings should pass the recency gate.
        """
        self._create_volume(timestamp=self._epoch_timestamp(minutes_ago=5), volume=11_111)

        volume = self.command.get_volume_from_timeseries(self.ITEM_ID, 0)

        self.assertEqual(volume, 11_111)

    def test_get_volume_from_timeseries_rejects_stale_epoch_timestamp(self):
        """
        Unix epoch strings older than the recency window should be rejected.
        """
        self._create_volume(
            timestamp=self._epoch_timestamp(minutes_ago=VOLUME_RECENCY_MINUTES + 1),
            volume=22_222,
        )

        volume = self.command.get_volume_from_timeseries(self.ITEM_ID, 0)

        self.assertIsNone(volume)

    def test_get_volume_from_timeseries_accepts_fresh_iso_timestamp(self):
        """
        Fresh ISO-8601 timestamp strings should pass the recency gate.
        """
        self._create_volume(timestamp=self._iso_timestamp(minutes_ago=5), volume=33_333)

        volume = self.command.get_volume_from_timeseries(self.ITEM_ID, 0)

        self.assertEqual(volume, 33_333)

    def test_get_volume_from_timeseries_rejects_stale_datetime_string(self):
        """
        Plain datetime strings older than the recency window should be rejected.
        """
        self._create_volume(
            timestamp=self._datetime_string_timestamp(minutes_ago=VOLUME_RECENCY_MINUTES + 1),
            volume=44_444,
        )

        volume = self.command.get_volume_from_timeseries(self.ITEM_ID, 0)

        self.assertIsNone(volume)

    def test_get_volume_from_timeseries_picks_newest_record_across_mixed_formats(self):
        """
        Mixed timestamp formats should resolve to the truly newest fresh row.
        """
        self._create_volume(timestamp=self._iso_timestamp(minutes_ago=90), volume=10_000)
        self._create_volume(timestamp=self._datetime_string_timestamp(minutes_ago=15), volume=20_000)
        self._create_volume(timestamp=self._epoch_timestamp(minutes_ago=5), volume=30_000)

        volume = self.command.get_volume_from_timeseries(self.ITEM_ID, 0)

        self.assertEqual(volume, 30_000)
