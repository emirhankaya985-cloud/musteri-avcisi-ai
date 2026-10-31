"""Synthetic PostgreSQL concurrency checks. No production DSN or mail services."""
import json
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from leadhunter.automatic_mail import AutoMailStore
from leadhunter.review_private import ReviewStore


@unittest.skipUnless(os.environ.get('TEST_POSTGRES_DSN'), 'isolated test Postgres required')
class PostgresDedupTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.schema = 'synthetic_' + uuid.uuid4().hex
        self.db = psycopg.connect(os.environ['TEST_POSTGRES_DSN'], autocommit=True)
        self.db.execute('CREATE SCHEMA ' + self.schema)
        self.db.execute('SET search_path TO ' + self.schema)
        self.db.execute("CREATE TABLE owner_leads (osm_id text PRIMARY KEY, lead_data jsonb NOT NULL, "
                        "status text NOT NULL, updated_at timestamptz DEFAULT now())")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.db.execute('DROP SCHEMA ' + self.schema + ' CASCADE')
        self.db.close()

    def insert(self, lid, state='draft'):
        record = {'state':state,'recipient':'synthetic@example.invalid',
                  'subject':'Synthetic','body':'Synthetic only','id':lid}
        self.db.execute("INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
                        (lid, json.dumps({'_auto_mail':record})))

    def race(self, ids, env=None):
        barrier = Barrier(2)
        def claim(lid):
            with self.psycopg.connect(os.environ['TEST_POSTGRES_DSN'], autocommit=True) as db:
                db.execute('SET search_path TO ' + self.schema)
                db.execute("SET statement_timeout = '5s'")
                barrier.wait(timeout=5)
                return AutoMailStore(ReviewStore(db)).claim(lid, env)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(claim, ids))

    def test_same_business_concurrent_claim_only_once(self):
        self.insert('node/1')
        results = self.race(['node/1', 'node/1'])
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_different_businesses_same_recipient_only_once(self):
        self.insert('node/1'); self.insert('node/2')
        results = self.race(['node/1', 'node/2'])
        self.assertEqual(sum(r is not None for r in results), 1)
        states = [r[0] for r in self.db.execute(
            "SELECT lead_data->'_auto_mail'->>'state' FROM owner_leads")]
        self.assertCountEqual(states, ['sending', 'duplicate'])

    def test_same_business_new_recipient_concurrent_claim_still_only_once(self):
        site = "https://owned-shop.example.invalid"
        for lid, email in (("node/21", "first@example.invalid"),
                           ("node/22", "second@example.invalid")):
            lead = {
                "name": "Synthetic Barbershop", "website": site,
                "address": "Test sokak no 14", "email": email,
                "_auto_mail": {"state":"draft", "recipient":email,
                               "subject":"Synthetic", "body":"Synthetic", "id":lid}
            }
            self.db.execute(
                "INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
                (lid,json.dumps(lead)))
        outcomes = self.race(["node/21", "node/22"])
        self.assertEqual(sum(x is not None for x in outcomes), 1)
        states = [x[0] for x in self.db.execute(
            "SELECT lead_data->'_auto_mail'->>'state' FROM owner_leads "
            "WHERE osm_id IN ('node/21','node/22')")]
        self.assertCountEqual(states, ["sending", "duplicate"])

    def test_delivery_feedback_is_additive_idempotent_and_preserves_claim(self):
        import io
        from leadhunter.mail_watch import reconcile_mail, deliver_pending
        self.insert("node/91", "accepted")
        recipient="synthetic@example.invalid"
        changed,pending=reconcile_mail(self.db, [(recipient,"delayed")])
        self.assertEqual(changed,1)
        self.assertEqual(len(pending),1)
        changed,pending=reconcile_mail(self.db, [(recipient,"delayed")])
        self.assertEqual(changed,0)
        self.assertEqual(len(pending),1)
        # A subsequent failure supersedes a temporary delivery delay.
        changed,pending=reconcile_mail(self.db, [(recipient,"failed")])
        self.assertEqual(changed,1)
        self.assertEqual(pending, [("node/91","failed")])
        responses=[]
        def telegram(req,timeout=None):
            responses.append(json.loads(req.data))
            return io.BytesIO(b'{"ok":true,"result":{"message_id":117}}')
        env={"TELEGRAM_BOT_TOKEN":"fake", "TELEGRAM_CHAT_ID":"123"}
        self.assertEqual(deliver_pending(self.db,pending,env,telegram),117)
        self.assertEqual(len(responses),1)
        self.assertIn("Başarısız",responses[0]["text"])
        changed,pending=reconcile_mail(self.db, [(recipient,"failed")])
        self.assertEqual((changed,pending),(0,[]))
        row=self.db.execute("SELECT lead_data->'_auto_mail' FROM owner_leads "
                            "WHERE osm_id='node/91'").fetchone()[0]
        self.assertEqual(row["state"],"accepted")
        self.assertEqual(row["delivery_feedback"]["state"],"failed")
        self.assertEqual(row["delivery_feedback"]["telegram_message_id"],117)
        self.insert("node/92")
        self.assertIsNone(AutoMailStore(ReviewStore(self.db)).claim("node/92"))

    def test_gmail_reply_reference_is_recorded_once_without_smtp_or_body(self):
        import io
        from leadhunter.mail_watch import reconcile_mail, deliver_pending
        self.insert('node/192','accepted')
        frozen_id='b'*24
        self.db.execute(
            "UPDATE owner_leads SET lead_data=jsonb_set(lead_data,"
            "'{_auto_mail,id}',%s::jsonb) WHERE osm_id='node/192'",
            (json.dumps(frozen_id),))
        recipient="synthetic@example.invalid"
        self.assertEqual(reconcile_mail(
            self.db,[(recipient,"reply:<wrong-id@gmail.com>")]),(0,[]))
        changed,pending=reconcile_mail(
            self.db,[(recipient,"reply:<"+frozen_id+"@gmail.com>")])
        self.assertEqual(changed,1)
        self.assertEqual(pending,[("node/192","reply")])
        messages=[]
        def private_bot(req,timeout=None):
            messages.append(json.loads(req.data))
            return io.BytesIO(b'{"ok":true,"result":{"message_id":193}}')
        env={"TELEGRAM_BOT_TOKEN":"fixture", "TELEGRAM_CHAT_ID":"123"}
        self.assertEqual(deliver_pending(self.db,pending,env,private_bot),193)
        self.assertEqual(len(messages),1)
        self.assertIn("eşleşen yanıt: 1",messages[0]["text"])
        self.assertNotIn(recipient,messages[0]["text"])
        self.assertEqual(reconcile_mail(
            self.db,[(recipient,"reply:<"+frozen_id+"@gmail.com>")]),(0,[]))
        record=self.db.execute(
            "SELECT lead_data->'_auto_mail' FROM owner_leads "
            "WHERE osm_id='node/192'").fetchone()[0]
        self.assertEqual(record["state"],"accepted")
        self.assertEqual(record["reply_feedback"]["telegram_message_id"],193)
        self.assertNotIn("delivery_feedback",record)

    def test_daily_quota_one_is_global_across_concurrent_claims(self):
        for lid, recipient in (("node/301","a301@example.invalid"),
                               ("node/302","a302@example.invalid")):
            data={"name":lid,"_auto_mail":{"id":lid,"state":"draft",
                  "recipient":recipient,"subject":"Synthetic","body":"Synthetic"}}
            self.db.execute(
                "INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
                (lid,json.dumps(data)))
        results=self.race(["node/301","node/302"],{"AUTO_MAIL_DAILY_LIMIT":"1"})
        self.assertEqual(sum(v is not None for v in results),1)
        rows=list(self.db.execute("SELECT lead_data->'_auto_mail' FROM owner_leads "
                                  "WHERE osm_id IN ('node/301','node/302')"))
        self.assertCountEqual([row[0]["state"] for row in rows],["sending","draft"])
        sending=next(row[0] for row in rows if row[0]["state"]=="sending")
        self.assertRegex(sending["claimed_day"],r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")
        # Restarting with another independent business is still blocked.
        self.db.execute("INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
            ("node/303",json.dumps({"_auto_mail":{"id":"node/303","state":"draft",
                      "recipient":"a303@example.invalid"}})))
        self.assertIsNone(AutoMailStore(ReviewStore(self.db)).claim(
            "node/303",{"AUTO_MAIL_DAILY_LIMIT":"1"}))

    def test_existing_delivery_failures_pause_scheduled_auto_mail_no_claim(self):
        for i in range(10):
            data={"_auto_mail":{"id":"old-"+str(i),"state":"accepted",
                  "recipient":f"old-{i}@example.invalid"}}
            if i < 2:
                data["_auto_mail"]["delivery_feedback"]={"state":"failed"}
            self.db.execute("INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
                ("node/"+str(i+500),json.dumps(data)))
        self.db.execute("INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
            ("node/520",json.dumps({"_auto_mail":{"id":"new","state":"draft",
                      "recipient":"new520@example.invalid"}})))
        store=AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim("node/520"))
        record=self.db.execute(
            "SELECT lead_data->'_auto_mail' FROM owner_leads WHERE osm_id='node/520'"
        ).fetchone()[0]
        self.assertEqual(record["state"],"draft")
        self.assertNotIn("claimed_day",record)
        self.assertEqual(sum(1 for row in self.db.execute(
            "SELECT lead_data->'_auto_mail'->>'state' FROM owner_leads "
            "WHERE osm_id='node/520'") if row[0]=="sending"),0)

    def test_restart_after_uncertain_result_blocks_recipient(self):
        self.insert('node/1', 'uncertain'); self.insert('node/2')
        store = AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim('node/1'))
        self.assertIsNone(store.claim('node/2'))
