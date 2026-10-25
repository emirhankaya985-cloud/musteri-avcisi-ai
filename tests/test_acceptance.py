"""Acceptance tests for owner-only Telegram and premium lead suggestions.

Mocks only: zero network calls to Overpass, Telegram or any actual business.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from leadhunter.core import format_telegram, lead_from_osm, live, offer, read_seen, recommend


def fixture_leads(count=8):
    return [
        {"type": "node", "id": 1000 + i,
         "tags": {"name": f"Fixture Business {i}", "amenity": "car_wash"}}
        for i in range(count)
    ]


class AcceptanceTests(unittest.TestCase):
    def test_only_five_owner_messages_and_dedupe(self):
        calls = []
        leads = fixture_leads(8)

        def fake_open(req, timeout=None):
            if req.full_url.startswith("https://api.telegram.org/"):
                payload = json.loads(req.data)
                calls.append(payload)
                return io.BytesIO(json.dumps({"ok": True, "result": {"message_id": len(calls)}}).encode())
            return io.BytesIO(json.dumps({"elements": leads}).encode())

        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "seen.json"
            env = {
                "TELEGRAM_BOT_TOKEN": "fake-token-no-network",
                "TELEGRAM_CHAT_ID": "fixture-owner-id",
                "STATE_FILE": str(file),
            }
            self.assertEqual(live(env=env, opener=fake_open, output=lambda _: None), 5)
            self.assertEqual(len(calls), 5)
            self.assertEqual(len(read_seen(file)), 5)
            self.assertTrue(all(msg["chat_id"] == env["TELEGRAM_CHAT_ID"] for msg in calls))
            self.assertTrue(all("🟣 WEB SİTESİ FIRSATI" in msg["text"] for msg in calls))
            self.assertTrue(all("OSM kaydı" in msg["text"] for msg in calls))
            self.assertEqual(live(env=env, opener=fake_open, output=lambda _: None), 3)
            self.assertEqual(len(read_seen(file)), 8)
            self.assertEqual(live(env=env, opener=fake_open, output=lambda _: None), 0)
            self.assertEqual(len(calls), 8)

    def test_partial_telegram_failure_persists_only_confirmed_send(self):
        sent = []
        leads = fixture_leads(3)

        def fake_open(req, timeout=None):
            if req.full_url.startswith("https://api.telegram.org/"):
                sent.append(json.loads(req.data))
                if len(sent) == 2:
                    raise HTTPError(req.full_url, 403, "fake failure", {}, None)
                return io.BytesIO(b'{"ok": true, "result": {"message_id": 1}}')
            return io.BytesIO(json.dumps({"elements": leads}).encode())

        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "seen.json"
            env = {
                "TELEGRAM_BOT_TOKEN": "FAKE_TOKEN_FOR_TEST_ONLY",
                "TELEGRAM_CHAT_ID": "owner-only",
                "STATE_FILE": str(file),
            }
            with self.assertRaisesRegex(RuntimeError, "Telegram API HTTP 403") as caught:
                live(env=env, opener=fake_open, output=lambda _: None)
            self.assertNotIn(env["TELEGRAM_BOT_TOKEN"], str(caught.exception))
            self.assertEqual(len(read_seen(file)), 1)
            self.assertEqual(len(sent), 2)

    def test_red_and_green_personalized_and_truthful(self):
        wash = lead_from_osm({
            "type": "node", "id": 1,
            "tags": {"name": "Demo & Wash", "amenity": "car_wash"},
        })
        salon = lead_from_osm({
            "type": "way", "id": 2,
            "tags": {"name": "Demo Hair", "shop": "hairdresser",
                     "website": "https://example.com"},
        })
        self.assertEqual(recommend(wash)["focus"], "website")
        self.assertEqual(recommend(salon)["focus"], "automation")
        self.assertIn("premium bir web sitesi", offer(wash))
        self.assertNotIn("premium bir web sitesi", offer(salon))
        self.assertIn("Demo &amp; Wash", format_telegram(wash))
        self.assertIn("🔴 WEB SİTESİ FIRSATI", format_telegram(wash))
        self.assertIn("🟢 OTOMASYON FIRSATI", format_telegram(salon))
        self.assertIn("manuel doğrula", recommend(wash)["evidence"])
        self.assertIn("bilinmiyor", recommend(salon)["evidence"])
        self.assertNotIn("web siteniz yok", offer(wash).lower())

    def test_public_state_contains_osm_ids_only(self):
        root = Path(__file__).resolve().parents[1]
        saved = json.loads((root / "data/seen.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved.keys()), {"seen_ids"})
        self.assertTrue(all(
            isinstance(x, str) and
            x.partition("/")[0] in {"node", "way", "relation"} and
            x.partition("/")[2].isdigit()
            for x in saved["seen_ids"]
        ))


if __name__ == "__main__":
    unittest.main()
