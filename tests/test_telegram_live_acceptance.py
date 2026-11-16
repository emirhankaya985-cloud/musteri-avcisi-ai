"""No-network owner-only Telegram notification and at-most-once tests."""
import io
import json
import unittest
from contextlib import contextmanager
from leadhunter.telegram_live_acceptance import send_once


class DB:
    def __init__(self):
        self.claimed=False
        self.state=None
        self.message=None
        self.reply=None
    @contextmanager
    def transaction(self):
        yield self
    @contextmanager
    def cursor(self):
        yield self
    def execute(self,query,args):
        if query.startswith("INSERT INTO owner_telegram_alert_acceptance"):
            if self.claimed:
                self.reply=None
            else:
                self.claimed=True
                self.reply=(args[0],)
        elif query.startswith("UPDATE owner_telegram_alert_acceptance"):
            self.state,self.message,_=args
            self.reply=None
        else:
            raise AssertionError("Unexpected SQL")
    def fetchone(self):
        return self.reply


class TelegramRealAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.env={"TELEGRAM_BOT_TOKEN":"1234567:"+("A"*35),
                  "TELEGRAM_CHAT_ID":"123456789",
                  "AUTO_MAIL_ENABLED":"false"}
    def test_one_owner_message_on_duplicate_workflow_replay(self):
        db=DB()
        observed=[]
        def fake(req,timeout=None):
            observed.append(req.full_url.rsplit("/",1)[-1])
            if req.full_url.endswith("/getMe"):
                return io.BytesIO(json.dumps({"ok":True,"result":{"id":123}}).encode())
            payload=json.loads(req.data)
            self.assertEqual(payload["chat_id"],"123456789")
            self.assertIn("kabul testi",payload["text"])
            self.assertNotIn("@",payload["text"])
            return io.BytesIO(b'{"ok":true,"result":{"message_id":42}}')
        msgs=[]
        self.assertTrue(send_once(self.env,db=db,opener=fake,output=msgs.append))
        self.assertFalse(send_once(self.env,db=db,opener=fake,output=msgs.append))
        self.assertEqual(observed,["getMe","sendMessage"])
        self.assertEqual(db.state,"api_accepted")
        self.assertEqual(db.message,42)
        self.assertIn("duplicate_sent=0",msgs[-1])
    def test_api_failure_never_retries_and_redacts_bot_secret(self):
        db=DB()
        def bad(req,timeout=None):
            if req.full_url.endswith("/getMe"):
                return io.BytesIO(b'{"ok":true,"result":{"id":123}}')
            raise RuntimeError("secret token must not leak")
        logs=[]
        with self.assertRaisesRegex(RuntimeError,"not confirmed"):
            send_once(self.env,db=db,opener=bad,output=logs.append)
        self.assertEqual(db.state,"failed")
        self.assertNotIn("secret",str(logs))
        self.assertFalse(send_once(self.env,db=db,opener=bad,output=logs.append))
    def test_missing_chat_fails_without_database_claim(self):
        db=DB()
        bad=dict(self.env);bad["TELEGRAM_CHAT_ID"]=""
        with self.assertRaisesRegex(RuntimeError,"chat ID"):
            send_once(bad,db=db,opener=lambda *args: self.fail("network used"))
        self.assertFalse(db.claimed)


if __name__=="__main__":
    unittest.main()
