from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from Website.models import HourlyItemVolume


def load_backfill_volumes_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_volumes.py"
    spec = importlib.util.spec_from_file_location("backfill_volumes_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BACKFILL_VOLUMES = load_backfill_volumes_module()


class BuildVolumeObjectsTests(SimpleTestCase):
    def test_build_volume_objects_keeps_one_sided_and_zero_volume_rows(self):
        results = [
            {
                "id": 4151,
                "data": [
                    {
                        "timestamp": 123456,
                        "avgHighPrice": None,
                        "avgLowPrice": 10,
                        "highPriceVolume": 0,
                        "lowPriceVolume": 2,
                    },
                    {
                        "timestamp": 123457,
                        "avgHighPrice": None,
                        "avgLowPrice": None,
                        "highPriceVolume": None,
                        "lowPriceVolume": None,
                    },
                ],
            }
        ]

        objects = BACKFILL_VOLUMES.build_volume_objects(results, {4151: "Abyssal whip"})

        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[0].item_name, "Abyssal whip")
        self.assertEqual(objects[0].volume, 20)
        self.assertEqual(objects[0].timestamp, "123456")
        self.assertEqual(objects[1].volume, 0)
        self.assertEqual(objects[1].timestamp, "123457")


class BulkCreateCommittedChunksTests(TestCase):
    def test_bulk_create_committed_chunks_skips_existing_item_timestamp_pairs(self):
        HourlyItemVolume.objects.create(
            item_id=4151,
            item_name="Abyssal whip",
            volume=10,
            timestamp="123456",
        )

        objects = [
            HourlyItemVolume(
                item_id=4151,
                item_name="Abyssal whip",
                volume=20,
                timestamp="123456",
            ),
            HourlyItemVolume(
                item_id=4151,
                item_name="Abyssal whip",
                volume=30,
                timestamp="123457",
            ),
        ]

        attempted, inserted, duplicates_skipped = BACKFILL_VOLUMES.bulk_create_committed_chunks(
            HourlyItemVolume,
            objects,
            "HourlyItemVolume",
        )

        self.assertEqual(attempted, 2)
        self.assertEqual(inserted, 1)
        self.assertEqual(duplicates_skipped, 1)
        self.assertEqual(HourlyItemVolume.objects.count(), 2)
        self.assertTrue(
            HourlyItemVolume.objects.filter(
                item_id=4151,
                timestamp="123457",
                volume=30,
            ).exists()
        )
