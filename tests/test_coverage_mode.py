"""Production coverage mode: OSM sampling occurs even when Overpass works."""
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
                if "api.openstreetmap.org" in req.full_url:
                    return io.BytesIO(json.dumps(sample).encode())
                if "/sendMessage" in req.full_url:
                    return io.BytesIO(b'{"ok":true,"result":{"message_id":18}}')
                self.fail("Healthy direct mode must not use Overpass")
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
            self.assertFalse(any("/api/interpreter" in url for url in calls))

    def test_failed_direct_tiles_can_use_overpass_without_false_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "TELEGRAM_BOT_TOKEN":"synthetic","TELEGRAM_CHAT_ID":"123",
                "STATE_FILE":str(Path(temp)/"seen.json"),
                "TILE_PROGRESS_FILE":str(Path(temp)/"tiles.json"),
                "SCAN_ROTATE_BBOX":"true","SCAN_TILE_LEDGER":"true",
                "OSM_SOURCE_MODE":"coverage", "AUTO_MAIL_ENABLED":"false"}
            api_calls = []
            def opener(req,timeout=None):
                if "api.openstreetmap.org" in req.full_url:
                    api_calls.append(req.full_url)
                    raise TimeoutError("synthetic provider offline")
                if "/api/interpreter" in req.full_url:
                    return io.BytesIO(json.dumps({"elements":[{"type":"node",
                        "id":2002,"tags":{"name":"Synthetic Wash","amenity":"car_wash"}}]}).encode())
                if "/sendMessage" in req.full_url:
                    return io.BytesIO(b'{"ok":true,"result":{"message_id":19}}')
                self.fail("Unexpected external destination")
            self.assertEqual(live(env=env,opener=opener,output=lambda _:None),1)
            self.assertLessEqual(len(api_calls),2)
            # A failed tile must now leave a durable retry record, not false
            # completed coverage. Overpass discovery may still succeed.
            state=plan(env["TILE_PROGRESS_FILE"],
                       select_bbox(env)[1],bbox_parse(select_bbox(env)[0]))
            self.assertEqual(state["completed"],0)
            self.assertEqual(state["stalls"],1)


if __name__ == "__main__":
    unittest.main()
