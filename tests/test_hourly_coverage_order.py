"""Hourly owner report must reflect *committed* OSM coverage, not prior hour."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from leadhunter.core import live
from leadhunter.tile_progress import aggregate


class HourlyCoverageOrderTests(unittest.TestCase):
    def test_hourly_telegram_uses_newly_confirmed_tiles_and_only_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, all_urls = [], []
            env={"TELEGRAM_BOT_TOKEN":"synthetic-owner-token",
                 "TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(Path(temp)/"seen.json"),
                 "TILE_PROGRESS_FILE":str(Path(temp)/"tiles.json"),
                 "SCAN_ROTATE_BBOX":"true","SCAN_TILE_LEDGER":"true",
                 "OSM_SOURCE_MODE":"coverage",
                 "AUTO_MAIL_ENABLED":"false",
                 "OWNER_HOURLY_SUMMARY":"true",
                 "GITHUB_RUN_ID":"42388888888",
                 "GITHUB_RUN_ATTEMPT":"1"}
            def opener(req,timeout=None):
                all_urls.append(req.full_url)
                if "/api/interpreter" in req.full_url:
                    return io.BytesIO(b'{"elements":[]}')
                if "/sendMessage" in req.full_url:
                    body=json.loads(req.data)
                    self.assertEqual(body["chat_id"], "123")
                    messages.append(body["text"])
                    return io.BytesIO(b'{"ok":true,"result":{"message_id":117}}')
                self.fail("Unsafe or redundant request")
            self.assertEqual(live(env=env,opener=opener,output=lambda _:None),0)
            self.assertEqual(len(messages),1)
            self.assertIn("Kanıtlı OSM kapsaması: 2/402",messages[0])
            self.assertEqual(aggregate(env["TILE_PROGRESS_FILE"])[0],2)
            self.assertEqual(sum("/api/interpreter" in url for url in all_urls),2)
            self.assertFalse(any("api.openstreetmap.org" in url for url in all_urls))
            self.assertNotIn("@",messages[0])

    def test_discovery_and_command_workflows_share_serial_write_group(self):
        lead=Path(".github/workflows/lead-digest.yml").read_text()
        cmds=Path(".github/workflows/telegram-buttons-inbox.yml").read_text()
        self.assertIn("group: telegram-lead-digest",lead)
        self.assertIn("group: telegram-lead-digest",cmds)
        self.assertIn("cancel-in-progress: false",cmds)


if __name__ == "__main__":
    unittest.main()
