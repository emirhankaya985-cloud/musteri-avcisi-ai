"""Silent CRM-only discovery tests; never contact customers or Telegram."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leadhunter.core import live, read_seen
from leadhunter.report_recovery import run as recovery_run


class SilentDiscoveryTests(unittest.TestCase):
    def test_silent_mode_requires_private_crm_before_marking_seen(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"seen.json"
            env={"TELEGRAM_BOT_TOKEN":"fake","TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(state),"OWNER_NEW_LEAD_NOTICES":"false"}
            calls=[]
            def opener(req,timeout=None):
                calls.append(req.full_url)
                return io.BytesIO(b'{"elements":[{"type":"node","id":42,"tags":{"name":"Synthetic Florist","shop":"florist"}}]}')
            with self.assertRaisesRegex(RuntimeError,"Silent lead capture requires"):
                live(env=env,opener=opener,output=lambda _:None)
            self.assertEqual(read_seen(state),set())
            self.assertEqual(sum("sendMessage" in url for url in calls),0)

    def test_silent_mode_registers_once_with_zero_owner_notices(self):
        class Connection:
            def close(self): pass
        class Review:
            def __init__(self): self.known=set()
            def statuses(self): return {v:"review" for v in self.known}
            def deferred(self): return []
            def register(self,item): self.known.add(item["id"])
        store=Review()
        calls=[]
        def opener(req,timeout=None):
            calls.append(req.full_url)
            return io.BytesIO(b'{"elements":[{"type":"node","id":42,"tags":{"name":"Synthetic Florist","shop":"florist"}}]}')
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"seen.json"
            env={"TELEGRAM_BOT_TOKEN":"fake","TELEGRAM_CHAT_ID":"123",
                 "STATE_FILE":str(state),"OWNER_NEW_LEAD_NOTICES":"false",
                 "REVIEW_DATABASE_URL":"postgresql://synthetic/?sslmode=require"}
            with patch("leadhunter.review_private.connect_private_database",return_value=Connection()),patch(
                 "leadhunter.review_private.ReviewStore",return_value=store):
                self.assertEqual(live(env=env,opener=opener,output=lambda _:None),0)
                self.assertEqual(live(env=env,opener=opener,output=lambda _:None),0)
            self.assertEqual(store.known,{"node/42"})
            self.assertEqual(read_seen(state),{"node/42"})
            self.assertEqual(sum("sendMessage" in url for url in calls),0)

    def test_report_backlog_audit_only_never_sends_or_blocks_scan(self):
        class DB:
            def close(self): pass
        class Auto:
            def __init__(self,store): pass
            def pending_reports(self): return [("one",{}),("two",{})]
        reports=[]
        with patch("leadhunter.report_recovery.connect_private_database",return_value=DB()),patch(
             "leadhunter.report_recovery.AutoMailStore",Auto):
            value=recovery_run({"REVIEW_DATABASE_URL":"postgresql://synthetic/?sslmode=require",
                                "OWNER_MAIL_REPORT_NOTICES":"false"},output=reports.append)
        self.assertEqual(value,0)
        self.assertIn("pending=2",reports[0])
        self.assertIn("telegram_sent=0",reports[0])


if __name__=="__main__":
    unittest.main()
