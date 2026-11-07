"""Production coverage uses bounded read-only Overpass, never OSM editing API."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.core import live, bbox_parse
from leadhunter.scan_regions import select_bbox
from leadhunter.tile_progress import plan


class CoverageModeTests(unittest.TestCase):
    def test_successful_two_tile_visits_resume_and_dedupe(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "TELEGRAM_BOT_TOKEN": "synthetic-token",
                "TELEGRAM_CHAT_ID": "123",
                "STATE_FILE": str(Path(temp)/"seen.json"),
                "TILE_PROGRESS_FILE": str(Path(temp)/"tiles.json"),
                "SCAN_ROTATE_BBOX":"true", "SCAN_TILE_LEDGER":"true",
                "OSM_SOURCE_MODE":"coverage", "AUTO_MAIL_ENABLED":"false"}
            output, calls = [], []
            sample = {"elements":[{"type":"node","id":2001,"tags":{
                "name":"Synthetic Flowers", "shop":"florist"}}]}
            def opener(req,timeout=None):
                calls.append(req.full_url)
                if "/api/interpreter" in req.full_url:
                    return io.BytesIO(json.dumps(sample).encode())
                if "/sendMessage" in req.full_url:
                    return io.BytesIO(b'{"ok":true,"result":{"message_id":18}}')
                self.fail("Healthy read-only tile must not use editing API")
            self.assertEqual(live(env=env,opener=opener,output=output.append),1)
            region=select_bbox(env)[1]
            bbox=bbox_parse(select_bbox(env)[0])
            first=plan(env["TILE_PROGRESS_FILE"],region,bbox)
            self.assertEqual(first["completed"],2)
            self.assertEqual(live(env=env,opener=opener,output=output.append),0)
            second=plan(env["TILE_PROGRESS_FILE"],region,bbox)
            self.assertEqual(second["completed"],4)
            self.assertEqual(sum("/sendMessage" in url for url in calls),1)
            self.assertTrue(any("OSM_TILE_PROGRESS" in line for line in output))
            self.assertEqual(sum("/api/interpreter" in url for url in calls),4)
            self.assertFalse(any("api.openstreetmap.org" in url for url in calls))

    def test_covered_tiles_do_not_refresh_historical_objects(self):
        with tempfile.TemporaryDirectory() as temp:
            env={"TELEGRAM_BOT_TOKEN":"synthetic","TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(Path(temp)/"seen.json"),
                 "TILE_PROGRESS_FILE":str(Path(temp)/"tiles.json"),
                 "SCAN_ROTATE_BBOX":"true","SCAN_TILE_LEDGER":"true",
                 "OSM_SOURCE_MODE":"coverage","AUTO_MAIL_ENABLED":"false"}
            from leadhunter.core import save_seen
            save_seen(Path(env["STATE_FILE"]),{"node/123","way/456","relation/789"})
            calls=[]
            def opener(req,timeout=None):
                calls.append(req.full_url)
                if "/api/interpreter" in req.full_url:
                    return io.BytesIO(b'{"elements":[]}')
                if "/sendMessage" in req.full_url:
                    return io.BytesIO(b'{"ok":true,"result":{"message_id":12}}')
                self.fail("Historical ID fetch or editing API is unnecessary")
            self.assertEqual(live(env=env,opener=opener,output=lambda _:None),0)
            self.assertEqual(sum("/api/interpreter" in url for url in calls),2)
            self.assertEqual(plan(env["TILE_PROGRESS_FILE"],select_bbox(env)[1],
                                  bbox_parse(select_bbox(env)[0]))["completed"],2)

    def test_api_429_stops_before_second_tile_or_provider_fallback(self):
        from urllib.error import HTTPError
        from leadhunter.osm_direct import OSMProviderStop
        with tempfile.TemporaryDirectory() as temp:
            env={"TELEGRAM_BOT_TOKEN":"synthetic","TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(Path(temp)/"seen.json"),
                 "TILE_PROGRESS_FILE":str(Path(temp)/"tiles.json"),
                 "SCAN_ROTATE_BBOX":"true","SCAN_TILE_LEDGER":"true",
                 "OSM_SOURCE_MODE":"coverage","AUTO_MAIL_ENABLED":"false"}
            calls=[]
            def opener(req,timeout=None):
                calls.append(req.full_url)
                if "/api/interpreter" in req.full_url:
                    raise HTTPError(req.full_url,429,"rate limited",None,None)
                self.fail("Rate-limit bypass or Telegram delivery not permitted")
            with self.assertRaisesRegex(OSMProviderStop,"429"):
                live(env=env,opener=opener,output=lambda _:None)
            self.assertEqual(len(calls),1)
            # A 429 is a failed request, never covered progress. The public
            # stall ledger can record that denial without switching hosts.
            status=plan(env["TILE_PROGRESS_FILE"],select_bbox(env)[1],
                        bbox_parse(select_bbox(env)[0]))
            self.assertEqual(status["completed"],0)
            self.assertEqual(status["stalls"],1)

    def test_network_failure_does_not_fall_back_to_full_region_or_fake_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "TELEGRAM_BOT_TOKEN":"synthetic","TELEGRAM_CHAT_ID":"123",
                "STATE_FILE":str(Path(temp)/"seen.json"),
                "TILE_PROGRESS_FILE":str(Path(temp)/"tiles.json"),
                "SCAN_ROTATE_BBOX":"true","SCAN_TILE_LEDGER":"true",
                "OSM_SOURCE_MODE":"coverage", "AUTO_MAIL_ENABLED":"false"}
            api_calls=[]
            def opener(req,timeout=None):
                api_calls.append(req.full_url)
                if "/api/interpreter" in req.full_url:
                    raise TimeoutError("synthetic provider offline")
                self.fail("No alternative host, OSM editing API or Telegram permitted")
            output=[]
            with self.assertRaisesRegex(RuntimeError,"No confirmed read-only Overpass tile"):
                live(env=env,opener=opener,output=output.append)
            self.assertEqual(len(api_calls),1)
            self.assertTrue(any("OVERPASS_TILE_FAILURE: class=timeout; tile_offset=0"
                                in line for line in output))
            state=plan(env["TILE_PROGRESS_FILE"],
                       select_bbox(env)[1],bbox_parse(select_bbox(env)[0]))
            self.assertEqual(state["completed"],0)
            self.assertEqual(state["stalls"],1)


if __name__ == "__main__":
    unittest.main()
