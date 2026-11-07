"""Provider-policy checks: scheduled scanning never uses OSM editing API."""
import io
import json
import unittest
from datetime import date
from urllib.error import HTTPError
from urllib.parse import parse_qs

from leadhunter.osm_overpass_tiles import get_overpass_tiles, READONLY_OVERPASS
from leadhunter.osm_direct import OSMProviderStop


BOX = (40.982,29.015,41.008,29.055)


class ReadonlyOverpassTileTests(unittest.TestCase):
    def test_two_tiny_filtered_post_queries_and_no_editing_api(self):
        calls, slots = [], []
        reply={"elements":[{"type":"node","id":100,"tags":{
            "name":"Synthetic Florist","shop":"florist","contact:email":"s@example.invalid",
            "unsafe_metadata":"removed"}}]}
        def opener(req,timeout=None):
            calls.append(req)
            self.assertEqual(req.full_url,READONLY_OVERPASS)
            self.assertEqual(req.get_method(),"POST")
            self.assertLessEqual(timeout,22)
            self.assertIn("User-agent",req.headers)
            query=parse_qs(req.data.decode())["data"][0]
            self.assertIn('nwr["shop"="florist"]',query)
            self.assertIn('nwr["amenity"="car_wash"]',query)
            self.assertIn("[timeout:20]",query)
            return io.BytesIO(json.dumps(reply).encode())
        items=get_overpass_tiles(BOX,opener,day=date(2026,11,7),hour=0,
                                 tile_start=0,tile_results=slots)
        self.assertEqual(slots,[True,True])
        self.assertEqual(len(calls),2)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["tags"]["shop"],"florist")
        self.assertNotIn("unsafe_metadata",items[0]["tags"])
        self.assertFalse(any("api.openstreetmap.org" in q.full_url for q in calls))
        query0=parse_qs(calls[0].data.decode())["data"][0]
        query1=parse_qs(calls[1].data.decode())["data"][0]
        self.assertNotEqual(query0,query1)

    def test_all_disallowed_4xx_stop_without_mirror_hopping(self):
        for code in (400,401,403,406,429):
            with self.subTest(code=code):
                calls, results = [], []
                def blocked(req,timeout=None):
                    calls.append(req.full_url)
                    raise HTTPError(req.full_url,code,"Denied",None,None)
                with self.assertRaises(OSMProviderStop):
                    get_overpass_tiles(BOX,blocked,day=date(2026,11,7),
                                       tile_start=0,tile_results=results)
                self.assertEqual(len(calls),1)
                self.assertEqual(results,[False])

    def test_network_or_5xx_returns_no_leads_and_no_success(self):
        for failure in ("timeout",503):
            with self.subTest(failure=failure):
                calls, results = [], []
                def opener(req,timeout=None):
                    calls.append(req.full_url)
                    if failure=="timeout":
                        raise TimeoutError("synthetic down")
                    raise HTTPError(req.full_url,503,"Unavailable",None,None)
                with self.assertRaisesRegex(RuntimeError,"No confirmed read-only"):
                    get_overpass_tiles(BOX,opener,day=date(2026,11,7),
                                       tile_start=0,tile_results=results)
                self.assertEqual(results,[False])
                self.assertEqual(len(calls),1)

    def test_partial_success_retries_failed_suffix_on_later_visit(self):
        results, calls = [], []
        def opener(req,timeout=None):
            calls.append(req.full_url)
            if len(calls)==2:
                raise TimeoutError("synthetic second tile offline")
            return io.BytesIO(b'{"elements":[]}')
        items=get_overpass_tiles(BOX,opener,day=date(2026,11,7),
                                 tile_start=0,tile_results=results)
        self.assertEqual(items,[])
        self.assertEqual(results,[True,False])
        self.assertEqual(len(calls),2)

    def test_error_remark_is_not_empty_success(self):
        calls=[]
        def opener(req,timeout=None):
            calls.append(req.full_url)
            return io.BytesIO(b'{"elements":[],"remark":"Rate limit exceeded"}')
        results=[]
        with self.assertRaisesRegex(RuntimeError,"No confirmed read-only"):
            get_overpass_tiles(BOX,opener,day=date(2026,11,7),
                               tile_start=0,tile_results=results)
        self.assertEqual(results,[False])
        self.assertEqual(len(calls),1)

    def test_request_limit_never_exceeds_two(self):
        with self.assertRaises(ValueError):
            get_overpass_tiles(BOX,max_tiles=3)
        with self.assertRaises(ValueError):
            get_overpass_tiles(BOX,max_tiles=-1)


if __name__=="__main__":
    unittest.main()
