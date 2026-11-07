"""Owner-only /durum aggregate acceptance; synthetic data and no network."""
import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from leadhunter.owner_status_private import collect, safe_text
from leadhunter.telegram_buttons import process_owner_command, poll


class Cursor:
    def __init__(self, now):
        self.now=now
        self.last=None
        self.sql=[]
    def execute(self,query,params=()):
        self.last=query
        self.sql.append(query)
    def fetchone(self):
        if "COALESCE(sum(new_registered)" in self.last:
            return (32,)
        if "owner_scan_run_metrics" in self.last:
            return (self.now-timedelta(minutes=35),)
        if "owner_mail_watch_runs" in self.last:
            return (self.now-timedelta(minutes=65),)
        raise AssertionError("Unexpected private SQL query")
    def fetchall(self):
        if "GROUP BY 1" in self.last:
            return [("Kuaför/berber",81),("Oto yıkama",7),
                    ("Güzellik salonu",6),("Çiçekçi",3),("Optik mağazası",2)]
        raise AssertionError("Unexpected private SQL query")
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False


class Database:
    def __init__(self,now):
        self.cur=Cursor(now)
    def cursor(self):
        return self.cur
    def close(self):
        pass


class Review:
    def __init__(self,now):
        self.db=Database(now)
    def mail_summary(self):
        return {"total":99, "accepted":15, "uncertain":0,
                "skipped":2,"duplicate":1,"failed":4,
                "delayed":0,"replied":0}


def owner_message(*,stamp=None):
    return {"message":{"chat":{"id":123,"type":"private"},
                       "from":{"id":123,"is_bot":False},
                       "text":"/durum",
                       "date":stamp if stamp is not None else int(time.time())}}


def fake_open(request,timeout=None):
    method=request.full_url.rsplit("/",1)[-1]
    if method=="getWebhookInfo":
        response={"url":""}
    elif method=="getUpdates":
        response=[{"update_id":100,**owner_message(
            stamp=int(time.time())-90*60)}]
    elif method=="sendMessage":
        response={"message_id":201}
    else:
        raise AssertionError("Unexpected Telegram method")
    return io.BytesIO(json.dumps({"ok":True,"result":response}).encode())


class OwnerOperationalTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,7,15,55,tzinfo=timezone.utc)

    def test_private_summary_is_aggregate_readonly_and_safe(self):
        private=Review(self.now)
        result=collect(private,now=self.now)
        message=safe_text(result)
        self.assertIn("Bugün Neon'a yeni aday: 32",message)
        self.assertIn("Kuaför: 81",message)
        self.assertIn("Optik: 2",message)
        self.assertIn("tarama güncel",message)
        self.assertIn("Gmail güncel",message)
        self.assertNotIn("@",message)
        self.assertNotIn("example.invalid",message)
        self.assertTrue(all(q.lstrip().upper().startswith("SELECT ")
                            for q in private.db.cur.sql))

    def test_private_summary_distinguishes_stale_from_healthy(self):
        private=Review(self.now-timedelta(hours=8))
        text=safe_text(collect(private,now=self.now))
        self.assertIn("tarama gecikmiş",text)
        self.assertIn("Gmail gecikmiş",text)

    def test_owner_only_command_includes_live_aggregate_no_contact_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def opener(req,timeout=None):
                calls.append(json.loads(req.data))
                return io.BytesIO(b'{"ok":true,"result":{"message_id":201}}')
            private=Review(datetime.now(timezone.utc))
            env={"STATE_FILE":str(Path(tmp)/"seen.json"),
                 "TILE_PROGRESS_FILE":str(Path(tmp)/"missing.json")}
            self.assertTrue(process_owner_command(owner_message(),
                    "fixture","123",env,opener,review_store=private))
            message=calls[0]["text"]
            self.assertIn("Toplam aday: 99",message)
            self.assertIn("Beş sektör",message)
            self.assertIn("Bugün Neon'a yeni aday: 32",message)
            self.assertIn("doğrulanmadı",message)  # absent map progress
            self.assertEqual(calls[0]["chat_id"],"123")
            self.assertNotIn("example.invalid",message)
            self.assertLess(len(message),4096)

    def test_private_read_failure_sends_unverified_not_fake_green(self):
        class BrokenReview:
            def mail_summary(self):
                raise RuntimeError("private@example.invalid password")
        sent=[]
        def opener(req,timeout=None):
            sent.append(json.loads(req.data)["text"])
            return io.BytesIO(b'{"ok":true,"result":{"message_id":202}}')
        self.assertTrue(process_owner_command(owner_message(),"fixture","123",
                        {},opener,review_store=BrokenReview()))
        self.assertIn("doğrulanamadı",sent[0])
        self.assertNotIn("private@example.invalid",sent[0])

    def test_delayed_real_owner_command_is_not_lost_when_database_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={"TELEGRAM_BOT_TOKEN":"fixture","TELEGRAM_CHAT_ID":"123",
                 "REVIEW_DATABASE_URL":"postgresql://offline.invalid/",
                 "OWNER_APPROVED_MAIL_ENABLED":"false",
                 "LEGACY_REVIEW_BUTTONS_ENABLED":"false",
                 "CALLBACK_OFFSET_FILE":str(Path(tmp)/"offset.json"),
                 "OWNER_COMMAND_RECEIPT_FILE":str(Path(tmp)/"receipt.json")}
            output=[]
            with patch("leadhunter.review_private.connect_private_database",
                       side_effect=RuntimeError("synthetic secret error")):
                self.assertEqual(poll(env,opener=fake_open,output=output.append),1)
            proof=json.loads(Path(env["OWNER_COMMAND_RECEIPT_FILE"]).read_text())
            self.assertEqual(proof,{"update_id":100,"command":"durum",
                                    "telegram_message_id":201})
            self.assertTrue(any("unverified" in line for line in output))
            self.assertEqual(json.loads(Path(env["CALLBACK_OFFSET_FILE"]).read_text()),
                             {"next_offset":101})

    def test_enabled_owner_mail_never_consumes_updates_on_database_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env={"TELEGRAM_BOT_TOKEN":"fixture","TELEGRAM_CHAT_ID":"123",
                 "REVIEW_DATABASE_URL":"postgresql://offline.invalid/",
                 "OWNER_APPROVED_MAIL_ENABLED":"true",
                 "CALLBACK_OFFSET_FILE":str(Path(tmp)/"offset.json")}
            with patch("leadhunter.review_private.connect_private_database",
                       side_effect=RuntimeError("private connection")):
                with self.assertRaisesRegex(RuntimeError,"Private review storage"):
                    poll(env,opener=lambda *_: (_ for _ in ()).throw(
                        AssertionError("No owner updates may be consumed")))
            self.assertFalse(Path(env["CALLBACK_OFFSET_FILE"]).exists())


if __name__ == "__main__":
    unittest.main()
