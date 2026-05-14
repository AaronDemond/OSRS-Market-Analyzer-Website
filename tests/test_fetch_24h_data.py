from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from Website.models import AllTimeData, TwentyFourHourTimeSeries


def load_fetch_24h_data_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_24h_data.py"
    spec = importlib.util.spec_from_file_location("fetch_24h_data_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


FETCH_24H_DATA = load_fetch_24h_data_module()


class BuildAllTimeObjectsTests(SimpleTestCase):
    def test_build_all_time_objects_computes_weighted_average_price_and_gp_volume(self):
        snapshot_data = {
            "4151": {
                "avgHighPrice": 10,
                "avgLowPrice": 4,
                "highPriceVolume": 2,
                "lowPriceVolume": 1,
            }
        }

        objects = FETCH_24H_DATA.build_all_time_objects(snapshot_data, {4151: "Abyssal whip"}, 123456)

        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].item_id, 4151)
        self.assertEqual(objects[0].item_name, "Abyssal whip")
        self.assertEqual(objects[0].item_price, 8)
        self.assertEqual(objects[0].volume, 24)
        self.assertEqual(objects[0].timestamp, 123456)

    def test_build_all_time_objects_keeps_one_sided_and_zero_volume_rows(self):
        snapshot_data = {
            "4151": {
                "avgHighPrice": None,
                "avgLowPrice": 10,
                "highPriceVolume": 0,
                "lowPriceVolume": 2,
            },
            "4152": {
                "avgHighPrice": None,
                "avgLowPrice": None,
                "highPriceVolume": None,
                "lowPriceVolume": None,
            },
        }

        objects = FETCH_24H_DATA.build_all_time_objects(
            snapshot_data,
            {4151: "Abyssal whip", 4152: "Dragon scimitar"},
            123456,
        )

        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[0].item_price, 10)
        self.assertEqual(objects[0].volume, 20)
        self.assertEqual(objects[1].item_price, 0)
        self.assertEqual(objects[1].volume, 0)


class FetchAndStoreSnapshotTests(TestCase):
    @patch.object(FETCH_24H_DATA, "fetch_24h_snapshot")
    def test_fetch_and_store_snapshot_inserts_matching_twentyfour_and_all_time_rows(self, mock_fetch):
        mock_fetch.return_value = {
            "timestamp": 123456,
            "data": {
                "4151": {
                    "avgHighPrice": 10,
                    "avgLowPrice": 4,
                    "highPriceVolume": 2,
                    "lowPriceVolume": 1,
                }
            },
        }

        inserted_count = FETCH_24H_DATA.fetch_and_store_snapshot({4151: "Abyssal whip"})

        self.assertEqual(inserted_count, 1)
        self.assertTrue(
            TwentyFourHourTimeSeries.objects.filter(
                item_id=4151,
                item_name="Abyssal whip",
                avg_high_price=10,
                avg_low_price=4,
                high_price_volume=2,
                low_price_volume=1,
                timestamp="123456",
            ).exists()
        )
        self.assertTrue(
            AllTimeData.objects.filter(
                item_id=4151,
                item_name="Abyssal whip",
                item_price=8,
                volume=24,
                timestamp=123456,
            ).exists()
        )

    @patch.object(FETCH_24H_DATA, "fetch_24h_snapshot")
    def test_fetch_and_store_snapshot_skips_duplicates_for_all_time_rows(self, mock_fetch):
        mock_fetch.return_value = {
            "timestamp": 123456,
            "data": {
                "4151": {
                    "avgHighPrice": 10,
                    "avgLowPrice": 4,
                    "highPriceVolume": 2,
                    "lowPriceVolume": 1,
                }
            },
        }

        first_insert_count = FETCH_24H_DATA.fetch_and_store_snapshot({4151: "Abyssal whip"})
        second_insert_count = FETCH_24H_DATA.fetch_and_store_snapshot({4151: "Abyssal whip"})

        self.assertEqual(first_insert_count, 1)
        self.assertEqual(second_insert_count, 0)
        self.assertEqual(TwentyFourHourTimeSeries.objects.count(), 1)
        self.assertEqual(AllTimeData.objects.count(), 1)

    @patch.object(FETCH_24H_DATA, "fetch_24h_snapshot")
    def test_fetch_and_store_snapshot_does_not_insert_duplicate_all_time_item_timestamp_pair(self, mock_fetch):
        AllTimeData.objects.create(
            item_id=4151,
            item_name="Abyssal whip",
            item_price=999,
            volume=12345,
            timestamp=123456,
        )

        mock_fetch.return_value = {
            "timestamp": 123456,
            "data": {
                "4151": {
                    "avgHighPrice": 10,
                    "avgLowPrice": 4,
                    "highPriceVolume": 2,
                    "lowPriceVolume": 1,
                }
            },
        }

        inserted_count = FETCH_24H_DATA.fetch_and_store_snapshot({4151: "Abyssal whip"})

        self.assertEqual(inserted_count, 1)
        self.assertEqual(TwentyFourHourTimeSeries.objects.count(), 1)
        self.assertEqual(AllTimeData.objects.count(), 1)

        existing_all_time_row = AllTimeData.objects.get(item_id=4151, timestamp=123456)
        self.assertEqual(existing_all_time_row.item_price, 999)
        self.assertEqual(existing_all_time_row.volume, 12345)