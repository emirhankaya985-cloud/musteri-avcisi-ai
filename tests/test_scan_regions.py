"""Hourly area rotation must not affect sending, deduplication or overrides."""
import unittest
from datetime import datetime, timezone
from leadhunter.core import bbox_parse
from leadhunter.scan_regions import DEFAULT_BBOX, PILOT_BBOXES, select_bbox


class ScanRegionsTests(unittest.TestCase):
    def test_disabled_preserves_existing_pilot(self):
        self.assertEqual(select_bbox({}), (DEFAULT_BBOX, "default"))
        self.assertEqual(select_bbox({"SCAN_ROTATE_BBOX": "false"}), (DEFAULT_BBOX, "default"))

    def test_explicit_bbox_always_wins(self):
        specified = "40.950,29.000,40.960,29.010"
        result = select_bbox({"SCAN_BBOX": specified, "SCAN_ROTATE_BBOX": "true"})
        self.assertEqual(result, (specified, "explicit_override"))

    def test_rotates_across_four_turkey_local_hours(self):
        # 21:00 UTC -> 00:00 TRT on the next day.
        first = datetime(2026, 11, 6, 21, tzinfo=timezone.utc)
        from datetime import timedelta
        found = [select_bbox({"SCAN_ROTATE_BBOX": "true"}, first + timedelta(hours=i))
                 for i in range(4)]
        self.assertEqual([v[0] for v in found], list(PILOT_BBOXES)[:4])
        self.assertEqual([v[1] for v in found],
                         ["pilot_1_of_8", "pilot_2_of_8",
                          "pilot_3_of_8", "pilot_4_of_8"])

    def test_regions_remain_bounded_and_nonidentical(self):
        self.assertEqual(len(PILOT_BBOXES), len(set(PILOT_BBOXES)))
        for bbox in PILOT_BBOXES:
            south, west, north, east = bbox_parse(bbox)
            self.assertLess(north - south, 0.05)
            self.assertLess(east - west, 0.05)

    def test_naive_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            select_bbox({"SCAN_ROTATE_BBOX": "true"}, datetime(2026, 11, 7, 0))


if __name__ == "__main__":
    unittest.main()
