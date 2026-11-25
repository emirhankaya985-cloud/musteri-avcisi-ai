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
            self.assertTrue(all("ARAŞTIRMA GEREKLİ" in msg["text"] for msg in calls))
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
        self.assertEqual(recommend(wash)["focus"], "research")
        self.assertEqual(recommend(salon)["focus"], "research")
        self.assertNotIn("premium bir web sitesi", offer(wash))
        self.assertNotIn("premium bir web sitesi", offer(salon))
        self.assertIn("Demo &amp; Wash", format_telegram(wash))
        self.assertIn("ARAŞTIRMA GEREKLİ", format_telegram(wash))
        self.assertIn("ARAŞTIRMA GEREKLİ", format_telegram(salon))
        self.assertIn("doğrulanmadı", recommend(wash)["evidence"])
        self.assertIn("doğrulanmadı", recommend(salon)["evidence"])
        self.assertNotIn("web siteniz yok", offer(wash).lower())

    def test_opportunity_tiers_follow_requested_2_1_3_order(self):
        from leadhunter.core import classify_opportunity, lead_priority_key, select_leads
        now = __import__("datetime").datetime.now().astimezone().isoformat()
        def verified(signal, url):
            return {signal:True, f"{signal}_evidence_url":url,
                    f"{signal}_verified_at":now,
                    f"{signal}_source_type":"documented_human_review",
                    f"{signal}_confidence":90,
                    f"{signal}_rationale":"Synthetic reviewed evidence for a unit test."}
        def score_component(name):
            return {"value":80,"evidence_ref":"https://example.invalid/score/"+name,
                    "verified_at":now,"source_type":"documented_human_review",
                    "confidence":90,"rationale":"Synthetic score evidence for a unit test."}
        tier2 = {"id":"node/2","name":"WA need","category":"Kuaför/berber",
                 "website":"","score":50, "qualification":{
                    **verified("whatsapp_automation_need_verified","https://example.invalid/wa")}}
        tier1 = {"id":"node/1","name":"No site verified","category":"Kuaför/berber",
                 "website":"https://example.invalid","score":99, "qualification":{
                    **verified("website_absence_verified","https://example.invalid/site")}}
        tier3 = {"id":"node/3","name":"Verified dual fit","category":"Kuaför/berber",
                 "website":"https://example.invalid","score":60,
                 "qualification":{
                    **verified("website_presence_verified","https://example.invalid/site"),
                    **verified("whatsapp_presence_verified","https://example.invalid/wa"),
                    **verified("automation_need_verified","https://example.invalid/need"),
                    "commercial_components":{name:score_component(name) for name in (
                        "service_need","contact_accuracy","service_fit",
                        "commercial_potential","digital_gap","data_freshness")}}}
        self.assertEqual([classify_opportunity(x)["tier"] for x in (tier2,tier1,tier3)],
                         [2,1,3])
        from leadhunter.core import recommend, offer
        self.assertEqual(recommend(tier3)["focus"],"combined")
        self.assertIn("birlikte",offer(tier3))
        stale = {**tier3,"qualification":{**tier3["qualification"],
                  "website_presence_verified_verified_at":"2020-01-01T00:00:00+00:00"}}
        self.assertEqual(classify_opportunity(stale)["tier"],None)
        self.assertEqual([x["id"] for x in select_leads(
            [{"type":"node","id":1,"tags":{"name":"tier1","shop":"hairdresser",
               "website":"https://example.invalid"}},
             {"type":"node","id":2,"tags":{"name":"tier2","shop":"hairdresser"}}],
            set(),maximum=2)], ["node/2","node/1"])
        self.assertLess(lead_priority_key(tier2),lead_priority_key(tier1))
        self.assertLess(lead_priority_key(tier1),lead_priority_key(tier3))
        # OSM presence alone never proves an automation gap.
        self.assertEqual(classify_opportunity({"id":"x","website":"https://example.invalid"})["focus"],"research")
        self.assertNotEqual(classify_opportunity({**tier1,"qualification":{}})["tier"],3)

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
