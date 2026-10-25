import io
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.review_messages import compact_telegram, button_markup, parse_callback
from leadhunter.telegram_buttons import process_review_callback, poll
from leadhunter.core import lead_from_osm, live


class FakeDecisions:
    def __init__(self):
        self.actions = []
    def decide(self, osm_id, message_id, action):
        self.actions.append((osm_id, message_id, action))
        return {"yes": "email_pending", "no": "rejected",
                "later": "deferred"}[action]


class DecisionWiringTests(unittest.TestCase):
    def setUp(self):
        self.owner = "123"
        self.lead = lead_from_osm({"type":"node","id":42,
                                   "tags":{"name":"ÖRNEK Kuaför",
                                           "shop":"hairdresser"}})

    def test_three_inline_buttons_each_bound_to_osm_id(self):
        keyboard = button_markup("node/42")["inline_keyboard"][0]
        self.assertEqual([b["text"] for b in keyboard],
                         ["✅ Evet", "❌ Hayır", "⏳ Beklet"])
        self.assertEqual([b["callback_data"] for b in keyboard],
                         ["lead:v1:yes:node/42", "lead:v1:no:node/42",
                          "lead:v1:later:node/42"])
        self.assertTrue(all(len(b["callback_data"].encode()) <= 64 for b in keyboard))

    def test_malformed_callback_discarded(self):
        for v in ("lead:v1:yes:bad", "lead:v1:delete:node/42",
                  "demo:v1:yes", "lead:v1:yes:node/42@other"):
            self.assertIsNone(parse_callback(v))

    def test_compact_notification_uses_new_colors(self):
        text = compact_telegram(self.lead)
        self.assertIn("🟣 WEB SİTESİ", text)
        self.assertNotIn("🔴", text)
        self.assertIn("ÖRNEK Kuaför", text)
        self.assertLessEqual(text.count("\\n"), 8)
        self.lead["website"] = "https://example.com"
        self.assertIn("🔵 OTOMASYON", compact_telegram(self.lead))

    def test_compact_escapes_business_html(self):
        self.lead["name"] = "<script>&"
        text = compact_telegram(self.lead)
        self.assertIn("&lt;script&gt;&amp;", text)
        self.assertNotIn("<script>", text)

    def _callback(self, *, owner=123, chat=123, action="yes", message_id=21):
        return {"callback_query": {"id":"q", "data":f"lead:v1:{action}:node/42",
                "from":{"id":owner},
                "message":{"message_id":message_id,
                           "text":"🟣 WEB SİTESİ FIRSATI\\nÖRNEK Kuaför",
                           "chat":{"id":chat, "type":"private"}}}}

    def test_owner_yes_queues_but_no_email_sent(self):
        store = FakeDecisions()
        calls = []
        def opener(req, timeout=None):
            calls.append((req.full_url.split("/")[-1], json.loads(req.data)))
            return io.BytesIO(b'{"ok":true,"result":true}')
        self.assertTrue(process_review_callback(self._callback(), "fake", self.owner,
                                                store, opener))
        self.assertEqual(store.actions, [("node/42",21,"yes")])
        self.assertIn("e-posta gönderilmedi", calls[0][1]["text"])
        self.assertEqual(calls[0][1]["reply_markup"]["inline_keyboard"], [])
        self.assertEqual(len(calls), 2)

    def test_no_and_later_edit_correctly(self):
        for action, label in (("no","listeden çıkarıldı"),("later","sonraki taramada")):
            with self.subTest(action=action):
                store = FakeDecisions()
                edited = []
                def opener(req, timeout=None):
                    edited.append(json.loads(req.data))
                    return io.BytesIO(b'{"ok":true,"result":true}')
                self.assertTrue(process_review_callback(
                    self._callback(action=action),"fake",self.owner,store,opener))
                self.assertIn(label, edited[0]["text"])

    def test_foreign_chat_or_user_not_allowed(self):
        store = FakeDecisions()
        for params in ({"owner":999}, {"chat":999}):
            self.assertFalse(process_review_callback(
                self._callback(**params),"fake",self.owner,store,
                opener=lambda *a,**k: self.fail("unexpected network")))
        self.assertEqual(store.actions, [])

    def test_no_real_buttons_without_db_configuration(self):
        sent = []
        def opener(req, timeout=None):
            if "api.telegram.org" in req.full_url:
                sent.append(json.loads(req.data))
                return io.BytesIO(b'{"ok":true,"result":{"message_id":4}}')
            rows = [{"type":"node","id":42,"tags":{"name":"ÖRNEK Kuaför","shop":"hairdresser"}}]
            return io.BytesIO(json.dumps({"elements": rows}).encode())
        with tempfile.TemporaryDirectory() as d:
            env={"TELEGRAM_BOT_TOKEN":"fake","TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(Path(d)/"seen.json")}
            self.assertEqual(live(env, opener, lambda _:None),1)
        self.assertNotIn("reply_markup", sent[0])
        self.assertIn("🟣 WEB SİTESİ",sent[0]["text"])

    def test_no_private_state_in_public_seen_file(self):
        with tempfile.TemporaryDirectory() as d:
            from leadhunter.core import save_seen
            p=Path(d)/"seen.json"
            save_seen(p,{"node/42"})
            v=json.loads(p.read_text())
            self.assertEqual(v,{"seen_ids":["node/42"]})

    def test_pre_registered_unsent_review_can_be_retried(self):
        from leadhunter.review_flow import prioritized_leads
        statuses = {"node/42": "review"}
        seen = set()
        filtered = {lead_id: status for lead_id, status in statuses.items()
                    if status != "review" or lead_id in seen}
        self.assertEqual(prioritized_leads(filtered, [self.lead])[0]["id"], "node/42")
        seen.add("node/42")
        filtered = {lead_id: status for lead_id, status in statuses.items()
                    if status != "review" or lead_id in seen}
        self.assertEqual(prioritized_leads(filtered, [self.lead]), [])


if __name__=="__main__":
    unittest.main()
