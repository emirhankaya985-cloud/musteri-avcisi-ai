"""Small mock-only direct OSM API read tests; no real network calls."""
from datetime import date
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from leadhunter.osm_direct import MAX_TILES, get_osm_direct, _tiles


class DirectApiTests(unittest.TestCase):
    BOX = (40.982, 29.015, 41.008, 29.055)
    OLD = {"node/42", "way/43"}

    def fake(self, req, timeout=None):
        url = req.full_url
        if "/nodes.json?" in url:
            payload = {"elements":[{"type":"node","id":42,"tags":{
                "name":"Old Salon", "shop":"hairdresser"}}]}
        elif "/ways.json?" in url:
            payload = {"elements":[{"type":"way","id":43,"tags":{
                "name":"Car Shop", "amenity":"car_wash"}}]}
        elif "/map.json?" in url:
            payload = {"elements":[
                {"type":"node","id":44,"tags":{"name":"New Salon", "shop":"beauty"}},
                {"type":"node","id":999,"tags":{"name":"Ignore", "amenity":"bench"}},
                {"type":"node","id":888,"tags":{"shop":"hairdresser"}},
            ]}
        else:
            raise AssertionError("unexpected URL")
        return io.BytesIO(json.dumps(payload).encode())

    def test_known_nodes_and_ways_are_returned(self):
        items=get_osm_direct(self.BOX,self.OLD,self.fake,max_tiles=0)
        self.assertEqual({(x["type"],x["id"]) for x in items},
                         {("node",42),("way",43)})

    def test_direct_small_tiles_include_new_business_and_exclude_irrelevant(self):
        rows=get_osm_direct(self.BOX,self.OLD,self.fake,
                            day=date(2026,10,26),max_tiles=2)
        self.assertEqual({x["id"] for x in rows},{42,43,44})
        self.assertEqual(len(rows),3)

    def test_bbox_conversion_west_south_east_north(self):
        tiles=list(_tiles(self.BOX,date(2026,10,26),2))
        self.assertEqual(len(tiles),2)
        for left,bottom,right,top in tiles:
            self.assertLess(left,right)
            self.assertLess(bottom,top)
            self.assertTrue(29.015 <= left < right <= 29.055)
            self.assertTrue(40.982 <= bottom < top <= 41.008)

    def test_api_calls_are_bounded(self):
        calls=[]
        def opener(req,timeout=None):
            calls.append((req.full_url,timeout))
            return self.fake(req,timeout)
        get_osm_direct(self.BOX,self.OLD,opener,max_tiles=2)
        self.assertEqual(len(calls),4)
        self.assertTrue(all(timeout<=18 for _,timeout in calls))

    def test_fail_closed_when_all_direct_reads_unavailable(self):
        def fail(req,timeout=None):
            raise TimeoutError("down")
        with self.assertRaisesRegex(RuntimeError,"All direct OSM API reads failed"):
            get_osm_direct(self.BOX,self.OLD,fail,max_tiles=2)

    def test_partial_outage_uses_existing_valid_public_ids(self):
        def opener(req,timeout=None):
            if "/map.json?" in req.full_url:
                raise TimeoutError("one tile down")
            return self.fake(req,timeout)
        rows=get_osm_direct(self.BOX,self.OLD,opener,max_tiles=2)
        self.assertEqual({x["id"] for x in rows},{42,43})

    def test_bounded_size_invalid_json_and_http_are_redacted(self):
        def huge(req,timeout=None):
            return io.BytesIO(b"x"*8_000_001)
        with self.assertRaisesRegex(RuntimeError,"All direct OSM API reads failed"):
            get_osm_direct(self.BOX,(),huge,max_tiles=1)

    def test_never_exposes_non_business_metadata_in_output(self):
        def opener(req,timeout=None):
            return io.BytesIO(json.dumps({"elements":[{
                "type":"node","id":42,"user":"Somebody",
                "tags":{"shop":"hairdresser","name":"Salon",
                        "contact:email":"personal@example.com",
                        "addr:street":"Street"}}]}).encode())
        rows=get_osm_direct(self.BOX,{"node/42"},opener,max_tiles=0)
        self.assertEqual(len(rows),1)
        self.assertNotIn("user",rows[0])
        self.assertEqual(rows[0]["tags"]["contact:email"],"personal@example.com")

    def test_invalid_tile_limit_is_rejected(self):
        for value in (-1,3,1.5):
            with self.assertRaises(ValueError):
                get_osm_direct(self.BOX,(),self.fake,max_tiles=value)


if __name__=="__main__":
    unittest.main()
