"""Extended hourly coverage preserves bounds, honest proposals, and dedupe."""
import io
import json
import unittest
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs
from leadhunter.core import get_osm, lead_from_osm, recommend, select_leads, bbox_parse
from leadhunter.scan_regions import PILOT_BBOXES, select_bbox


class ExpandedDiscoveryTests(unittest.TestCase):
    def test_eight_distinct_safe_regions(self):
        self.assertEqual(len(PILOT_BBOXES), 8)
        self.assertEqual(len(set(PILOT_BBOXES)), 8)
        for region in PILOT_BBOXES:
            south, west, north, east = bbox_parse(region)
            self.assertLess(north - south, .05)
            self.assertLess(east - west, .05)

    def test_hourly_cycle_and_explicit_override(self):
        start = datetime(2026, 11, 6, 21, tzinfo=timezone.utc)
        slots = [select_bbox({'SCAN_ROTATE_BBOX': 'true'}, start + timedelta(hours=i))[0]
                 for i in range(9)]
        self.assertEqual(slots[:8], list(PILOT_BBOXES))
        self.assertEqual(slots[-1], PILOT_BBOXES[0])
        self.assertEqual(select_bbox({'SCAN_BBOX': '40.96,29.01,40.97,29.02',
                                      'SCAN_ROTATE_BBOX': 'true'})[1], 'explicit_override')

    def test_two_additional_sectors_are_queried_in_same_bounded_request(self):
        requests = []
        def fake_open(req, timeout=None):
            requests.append(parse_qs(req.data.decode())['data'][0])
            return io.BytesIO(json.dumps({'elements': [
                {'type': 'node', 'id': 9, 'tags': {'name': 'Sample', 'shop': 'florist'}}]}).encode())
        rows = get_osm(bbox_parse(PILOT_BBOXES[0]), fake_open)
        self.assertEqual(len(requests), 1)
        self.assertIn('"shop"="florist"', requests[0])
        self.assertIn('"shop"="optician"', requests[0])
        self.assertIn('out center tags 200', requests[0])
        self.assertEqual(lead_from_osm(rows[0])['category'], 'Çiçekçi')

    def test_new_sectors_remain_hypotheses_and_repeat_safe(self):
        for index, shop in enumerate(('florist', 'optician')):
            row = {'type': 'node', 'id': 100+index,
                   'tags': {'name': 'Synthetic business', 'shop': shop}}
            lead = lead_from_osm(row)
            self.assertEqual(recommend(lead)['focus'], 'website')
            self.assertIn('manuel doğrula', recommend(lead)['evidence'])
            self.assertEqual(select_leads([row], {lead['id']}), [])


if __name__ == '__main__':
    unittest.main()
