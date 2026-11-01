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

    def test_auto_and_owner_approved_workers_share_one_atomic_claim(self):
        from datetime import datetime,timezone
        from unittest.mock import patch
        from leadhunter.outreach import MailStore
        self.db.execute("ALTER TABLE owner_leads ADD COLUMN telegram_message_id bigint")
        recipient="synthetic-race@example.invalid"
        proof={"route":"consent","recipient":recipient,
               "evidence_ref":"synthetic-mock-consent-001",
               "verified_at":datetime.now(timezone.utc).isoformat(),
               "opted_out":False,"consent_active":True}
        auto={"name":"Synthetic Auto","email":recipient,
              "marketing_eligibility":proof,
              "_auto_mail":{"state":"draft","recipient":recipient,
                            "subject":"Synthetic auto","body":"Synthetic",
                            "id":"a"*24}}
        manual={"name":"Synthetic Manual","email":recipient,
                "marketing_eligibility":proof,
                "_mail":{"state":"draft","recipient":recipient,
                         "subject":"Synthetic owner","body":"Synthetic",
                         "id":"b"*24}}
        self.db.execute("INSERT INTO owner_leads "
            "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
            ("node/7001",json.dumps(auto)))
        self.db.execute("INSERT INTO owner_leads "
            "(osm_id,lead_data,status,telegram_message_id) "
            "VALUES (%s,%s::jsonb,'email_pending',701)",
            ("node/7002",json.dumps(manual)))
        env={"AUTO_MAIL_ENABLED":"true","AUTO_MAIL_DAILY_LIMIT":"5",
             "OWNER_APPROVED_MAIL_ENABLED":"true",
             "GMAIL_SENDER_ADDRESS":"synthetic.sender@gmail.com",
             "GMAIL_APP_PASSWORD":"abcdefghijklmnop"}
        barrier=Barrier(2)
        def attempt(kind):
            with self.psycopg.connect(os.environ["TEST_POSTGRES_DSN"],autocommit=True) as db:
                db.execute("SET search_path TO "+self.schema)
                db.execute("SET statement_timeout = '5s'")
                barrier.wait(timeout=5)
                if kind=="automatic":
                    return bool(AutoMailStore(ReviewStore(db)).claim("node/7001",env))
                return MailStore(ReviewStore(db)).send("node/7002",701,"b"*24,env)=="accepted"
        with patch("leadhunter.outreach.send_mail",return_value=None) as fake_sender:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,["automatic","manual"]))
            self.assertEqual(sum(results),1)
            self.assertEqual(fake_sender.call_count,int(results[1]))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM owner_leads WHERE "
            "lead_data->'_auto_mail'->>'state' IN ('sending','accepted') "
            "OR lead_data->'_mail'->>'state' IN ('sending','accepted')").fetchone()[0],1)

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

    def test_production_auto_requires_verified_recipient_before_claim(self):
        self.insert("node/701")
        env={"AUTO_MAIL_ENABLED":"true","AUTO_MAIL_DAILY_LIMIT":"5"}
        store=AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim("node/701",env))
        row=self.db.execute(
            "SELECT lead_data->'_auto_mail' FROM owner_leads WHERE osm_id='node/701'"
        ).fetchone()[0]
        self.assertEqual(row["state"],"draft")
        self.assertNotIn("claimed_day",row)
        # A forged OSM shop tag, a valid-looking email and MX cannot grant
        # an IYS verified status to the sender.
        self.db.execute("UPDATE owner_leads SET lead_data=jsonb_set("
            "lead_data,'{shop}','\"hairdresser\"'::jsonb) WHERE osm_id='node/701'")
        self.assertIsNone(store.claim("node/701",env))

    def test_verified_synthetic_business_claim_is_single_use(self):
        from datetime import datetime, timezone
        self.insert("node/702")
        proof={"route":"consent","recipient":"synthetic@example.invalid",
               "evidence_ref":"synthetic-document-123456",
               "verified_at":datetime.now(timezone.utc).isoformat(),
               "opted_out":False,"consent_active":True}
        self.db.execute("UPDATE owner_leads SET lead_data=jsonb_set("
                        "lead_data,'{marketing_eligibility}',%s::jsonb,true)"
                        " WHERE osm_id='node/702'",(json.dumps(proof),))
        store=AutoMailStore(ReviewStore(self.db))
        env={"AUTO_MAIL_ENABLED":"true","AUTO_MAIL_DAILY_LIMIT":"5"}
        accepted=store.claim("node/702",env)
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["state"],"sending")
        self.assertIsNone(store.claim("node/702",env))
        row=self.db.execute("SELECT lead_data->'_auto_mail' FROM owner_leads"
                            " WHERE osm_id='node/702'").fetchone()[0]
        self.assertEqual(row["state"],"sending")
        self.assertTrue(row["claimed_day"])

    def test_bounce_pause_read_only_no_claims(self):
        for i in range(15):
            record={"state":"accepted","recipient":f"synthetic-{i}@example.invalid"}
            if i < 3:
                record["delivery_feedback"]={"state":"failed"}
            self.db.execute("INSERT INTO owner_leads VALUES (%s,%s::jsonb,'review',now())",
                ("node/"+str(800+i),json.dumps({"_auto_mail":record})))
        store=AutoMailStore(ReviewStore(self.db))
        self.assertTrue(store.reputation_paused())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM owner_leads WHERE"
            " lead_data->'_auto_mail'->>'state'='sending'").fetchone()[0],0)

    def test_restart_after_uncertain_result_blocks_recipient(self):
        self.insert('node/1', 'uncertain'); self.insert('node/2')
        store = AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim('node/1'))
        self.assertIsNone(store.claim('node/2'))
