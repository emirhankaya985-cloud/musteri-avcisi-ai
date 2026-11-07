"""Read-only OSM eight-region acceptance is bounded and honest."""
import io
import json
import unittest
from urllib.error import HTTPError
from leadhunter.live_region_audit import osm_query, inspect_one, run
from leadhunter.scan_regions import PILOT_BBOXES


class RegionAcceptanceTests(unittest.TestCase):
    def test_every_pilot_query_includes_five_sectors(self):
        self.assertEqual(len(PILOT_BBOXES),8)
        for box in PILOT_BBOXES:
            q = osm_query(box)
            self.assertEqual(q.count('nwr['),5)
            self.assertIn('"shop"="optician"',q)
            self.assertIn('"shop"="florist"',q)
            self.assertIn('"amenity"="car_wash"',q)

    def test_read_only_counts_do_not_return_names(self):
        def fake(req, timeout):
            self.assertEqual(req.method,'POST')
            self.assertLessEqual(timeout,15)
            return io.BytesIO(json.dumps({'elements':[
                {'id':1,'type':'node','tags':{'name':'synthetic','shop':'optician'}},
                {'id':1,'type':'node','tags':{'name':'synthetic','shop':'optician'}},
                {'id':2,'type':'node','tags':{'shop':'beauty'}},
            ]}).encode())
        self.assertEqual(inspect_one(PILOT_BBOXES[0],fake),('ok',3,1))

    def test_all_eight_regions_checked_once_with_cooldown(self):
        calls, sleeps, logs = [], [], []
        def fake(req, timeout):
            calls.append(1)
            return io.BytesIO(b'{"elements":[]}')
        self.assertEqual(run(fake,sleeps.append,logs.append),['ok']*8)
        self.assertEqual(len(calls),8)
        self.assertEqual(sleeps,[2]*7)
        self.assertIn('PASS',logs[-1])

    def test_rate_limit_stops_all_requests_and_fails_closed(self):
        calls=[]
        def fake(req, timeout):
            calls.append(1)
            raise HTTPError(req.full_url,429,'busy',{},None)
        with self.assertRaisesRegex(RuntimeError,'PARTIAL'):
            run(fake,lambda _:None,lambda _:None)
        self.assertEqual(len(calls),1)


if __name__ == '__main__':
    unittest.main()
