"""Synthetic PostgreSQL concurrency checks. No production DSN or mail services."""
import json
import os
import unittest
import uuid
from pathlib import Path
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

    def test_owner_daily_summary_is_at_most_once_and_preserves_leads(self):
        from leadhunter.daily_status import run
        self.db.execute("ALTER TABLE owner_leads ADD COLUMN first_seen_at timestamptz DEFAULT now()")
        self.db.execute("ALTER TABLE owner_leads ADD COLUMN sent_at timestamptz")
        self.db.execute("CREATE TABLE owner_daily_report_receipts ("
                        "report_day text PRIMARY KEY,state text NOT NULL,"
                        "telegram_message_id bigint,telegram_document_message_id bigint,"
                        "github_run_id text,github_run_attempt int,crm_row_count int,"
                        "source_snapshot_at timestamptz,crm_snapshot_sha256 text,"
                        "workbook_sha256 text,generated_at timestamptz,document_sent_at timestamptz,"
                        "failure_stage text,"
                        "updated_at timestamptz DEFAULT now())")
        self.db.execute("CREATE TABLE owner_duplicate_review_pairs ("
                        "lead_a text,lead_b text,review_state text,confidence_score smallint,evidence jsonb,"
                        "first_detected_at timestamptz DEFAULT now(),last_observed_at timestamptz DEFAULT now())")
        self.db.execute("CREATE TABLE owner_province_scan_coverage ("
                        "province_code text PRIMARY KEY,province_name text NOT NULL,"
                        "initial_phase_target boolean NOT NULL,status text NOT NULL,"
                        "province_state jsonb NOT NULL,created_at timestamptz DEFAULT now(),updated_at timestamptz)")
        self.db.execute("CREATE TABLE owner_scan_run_metrics ("
                        "scan_run_id text PRIMARY KEY,report_day date NOT NULL,"
                        "scanned_count int NOT NULL,new_registered int NOT NULL,"
                        "new_addresses int NOT NULL,new_mx int NOT NULL)")
        self.db.execute("CREATE TABLE owner_mail_notice_metrics ("
                        "notice_digest text PRIMARY KEY,report_day date NOT NULL,"
                        "kind text NOT NULL)")
        self.db.execute("CREATE TABLE owner_mail_watch_runs ("
                        "watch_run_id text PRIMARY KEY,report_day date NOT NULL)")
        self.db.execute("INSERT INTO owner_leads "
            "(osm_id,lead_data,status,updated_at) VALUES (%s,%s::jsonb,'review',now())",
            ("node/5001",json.dumps({"_auto_mail":{"state":"draft",
                "recipient":"synthetic@example.invalid"}})))
        messages=[]
        documents=[]
        def fake_bot(token,method,data):
            self.assertEqual(method,"sendMessage")
            messages.append(data['text'])
            return {"message_id":501}
        def fake_document(token,chat_id,content,filename,caption):
            self.assertEqual((token,chat_id),("fake","123"))
            self.assertTrue(content.startswith(b"PK\x03\x04"))
            self.assertTrue(filename.startswith("Musteri-Avcisi-CRM-2026-11-"))
            documents.append(filename)
            return 502
        env={"TELEGRAM_BOT_TOKEN":"fake","TELEGRAM_CHAT_ID":"123",
             "AUTO_MAIL_ENABLED":"true", "GITHUB_RUN_ID":"98765", "GITHUB_RUN_ATTEMPT":"2"}
        self.assertEqual(run(env,self.db,fake_bot,"2026-11-01",fake_document),501)
        self.assertEqual(run(env,self.db,fake_bot,"2026-11-01",fake_document),0)
        self.assertEqual(len(messages),1)
        self.assertEqual(len(documents),1)
        self.assertIn("KAPALI",messages[0])
        self.assertNotIn("synthetic@example.invalid",messages[0])
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM owner_leads").fetchone()[0],1)
        receipt = self.db.execute(
            "SELECT state,telegram_message_id,telegram_document_message_id,github_run_id,"
            "github_run_attempt,crm_row_count,crm_snapshot_sha256,workbook_sha256,generated_at,document_sent_at "
            "FROM owner_daily_report_receipts").fetchone()
        self.assertEqual(receipt[:6], ("confirmed",501,502,"98765",2,1))
        self.assertRegex(receipt[6], r"^[a-f0-9]{64}$")
        self.assertRegex(receipt[7], r"^[a-f0-9]{64}$")
        self.assertIsNotNone(receipt[8])
        self.assertIsNotNone(receipt[9])

        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            run(env, self.db, lambda *args: (_ for _ in ()).throw(OSError("synthetic")),
                "2026-11-02", fake_document)
        uncertain = self.db.execute(
            "SELECT state,telegram_document_message_id,telegram_message_id,failure_stage "
            "FROM owner_daily_report_receipts WHERE report_day='2026-11-02'").fetchone()
        self.assertEqual(uncertain, ("uncertain",502,None,"summary_send"))
        self.assertEqual(run(env, self.db, fake_bot, "2026-11-02", fake_document), 0)
        self.assertEqual(len(documents), 2)

    def test_dns_nxdomain_and_relay_domain_quarantines_are_durable(self):
        for i,reason in enumerate(("dns_nxdomain","relay_denied")):
            domain=f"blocked-{i}.example.invalid"
            prior={"name":"Unreachable","_auto_mail":{
                "state":"accepted","recipient":"old@"+domain,
                "delivery_feedback":{"state":"failed","reason":reason}}}
            new={"name":"New Shop","_auto_mail":{
                "state":"draft","recipient":"new@"+domain,
                "subject":"Synthetic","body":"Synthetic","id":f"blocked-{i}"}}
            self.db.execute("INSERT INTO owner_leads "
                "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
                (f"node/{8800+i}",json.dumps(prior)))
            self.db.execute("INSERT INTO owner_leads "
                "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
                (f"node/{8900+i}",json.dumps(new)))
            self.assertIsNone(AutoMailStore(ReviewStore(self.db)).claim(
                f"node/{8900+i}"))
            state=self.db.execute(
                "SELECT lead_data->'_auto_mail'->>'state' FROM owner_leads "
                "WHERE osm_id=%s",(f"node/{8900+i}",)).fetchone()[0]
            self.assertEqual(state,"duplicate")

    def test_recipient_hold_audit_is_repeat_safe(self):
        from leadhunter.recipient_audit import run
        records = [
            ("node/91001", {"email":"synthetic@example.invalid","name":"Synthetic"}),
            ("node/91002", {"_auto_mail":{"state":"accepted",
                "recipient":"old@example.invalid"}}),
        ]
        for lid, data in records:
            self.db.execute("INSERT INTO owner_leads "
                "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
                (lid, json.dumps(data)))
        self.assertEqual(run(self.db),2)
        self.assertEqual(run(self.db),0)
        from leadhunter.recipient_audit import dry_run
        check = dry_run(self.db)
        self.assertEqual(check['contacts'],2)
        self.assertEqual(check['audited'],2)
        self.assertEqual(check['legally_verified'],0)
        self.assertEqual(check['sendable'],0)
        rows=self.db.execute(
            "SELECT lead_data->'recipient_eligibility_audit' FROM owner_leads "
            "ORDER BY osm_id").fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r[0]['decision']=='hold' for r in rows))
        self.assertEqual([r[0]['reason'] for r in rows],
                         ['legal_basis_unverified','previous_contact'])

    def test_rescan_preserves_eligibility_evidence_only_for_same_address(self):
        seed={"name":"old","email":"synthetic@example.invalid",
              "recipient_eligibility_audit":{"decision":"hold","reason":"legal_basis_unverified"},
              "marketing_eligibility":{"opted_out":True}}
        self.db.execute("INSERT INTO owner_leads "
            "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
            ("node/92001",json.dumps(seed)))
        store=ReviewStore(self.db)
        store.register({"id":"node/92001","name":"new",
                        "email":"synthetic@example.invalid"})
        data=self.db.execute(
            "SELECT lead_data FROM owner_leads WHERE osm_id='node/92001'").fetchone()[0]
        self.assertEqual(data["name"],"new")
        self.assertEqual(data["recipient_eligibility_audit"]["decision"],"hold")
        self.assertTrue(data["marketing_eligibility"]["opted_out"])
        store.register({"id":"node/92001","name":"changed",
                        "email":"different@example.invalid"})
        after=self.db.execute(
            "SELECT lead_data FROM owner_leads WHERE osm_id='node/92001'").fetchone()[0]
        self.assertNotIn("recipient_eligibility_audit",after)
        self.assertNotIn("marketing_eligibility",after)

    def test_run_scoped_metrics_are_idempotent_and_count_persisted_mx_only(self):
        from leadhunter.scan_metrics import snapshot, persist
        self.db.execute("CREATE TABLE owner_scan_run_metrics ("
                        "scan_run_id text PRIMARY KEY,report_day date NOT NULL,"
                        "scanned_count int NOT NULL,new_registered int NOT NULL,"
                        "new_addresses int NOT NULL,new_mx int NOT NULL)")
        before = snapshot(self.db,["node/9950","node/9951"])
        candidate={"name":"Synthetic shop", "email":"synthetic@example.invalid",
                   "email_check":"mx_present"}
        self.db.execute("INSERT INTO owner_leads "
                        "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
                        ("node/9950",json.dumps(candidate)))
        self.assertTrue(persist(self.db,"41499900000","2026-11-02",3,before,
                                ["node/9950","node/9951"]))
        self.assertFalse(persist(self.db,"41499900000","2026-11-02",3,before,
                                 ["node/9950","node/9951"]))
        row=self.db.execute("SELECT scanned_count,new_registered,new_addresses,new_mx "
                            "FROM owner_scan_run_metrics").fetchone()
        self.assertEqual(row,(3,1,1,1))
        self.assertEqual(self.db.execute("SELECT count(*) FROM owner_leads").fetchone()[0],1)
        before=snapshot(self.db,["node/9950"])
        self.assertTrue(persist(self.db,"41499900001","2026-11-02",3,before,
                                ["node/9950"]))
        second=self.db.execute("SELECT new_registered,new_addresses,new_mx "
                              "FROM owner_scan_run_metrics WHERE scan_run_id='41499900001'"
                              ).fetchone()
        self.assertEqual(second,(0,0,0))

    def test_scan_without_email_is_not_reported_as_new_technical_address(self):
        from leadhunter.scan_metrics import snapshot,persist
        self.db.execute("CREATE TABLE owner_scan_run_metrics ("
                        "scan_run_id text PRIMARY KEY,report_day date NOT NULL,"
                        "scanned_count int NOT NULL,new_registered int NOT NULL,"
                        "new_addresses int NOT NULL,new_mx int NOT NULL)")
        before=snapshot(self.db,["node/9960"])
        self.db.execute("INSERT INTO owner_leads "
                        "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review')",
                        ("node/9960",json.dumps({"name":"No email","email":""})))
        self.assertTrue(persist(self.db,"41499900002","2026-11-02",1,before,
                                ["node/9960"]))
        self.assertEqual(self.db.execute(
            "SELECT new_registered,new_addresses,new_mx FROM owner_scan_run_metrics"
            ).fetchone(),(1,0,0))

    def test_gmail_immutable_notice_ledger_deduplicates_repeat_reads(self):
        from leadhunter.mail_watch import reconcile_mail
        self.db.execute("CREATE TABLE owner_mail_notice_metrics ("
                        "notice_digest text PRIMARY KEY,report_day date NOT NULL,"
                        "kind text NOT NULL)")
        recipient="bounced@example.invalid"
        record={"_auto_mail":{"state":"accepted","recipient":recipient,
                              "id":"a"*24}}
        self.db.execute("INSERT INTO owner_leads "
                        "(osm_id,lead_data,status) VALUES (%s,%s::jsonb,'email_sent')",
                        ("node/9965",json.dumps(record)))
        notice=("The recipient "+recipient+" failed","failed",
                {"smtp_code":"550"},
                {"digest":"a"*64,"day":"2026-11-02"})
        other=(recipient,"reply:<"+("a"*24)+"@gmail.com>",{},
               {"digest":"b"*64,"day":"2026-11-02"})
        for _ in range(2):
            reconcile_mail(self.db,[notice,other])
        results=self.db.execute(
            "SELECT kind,count(*) FROM owner_mail_notice_metrics "
            "GROUP BY kind ORDER BY kind").fetchall()
        self.assertEqual(results,[("failed",1),("reply",1)])
        row=self.db.execute(
            "SELECT lead_data->'_auto_mail' FROM owner_leads "
            "WHERE osm_id='node/9965'").fetchone()[0]
        self.assertEqual(row["state"],"accepted")
        self.assertEqual(row["delivery_feedback"]["state"],"failed")
        self.assertEqual(row["reply_feedback"]["state"],"sender_matched_reply")

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

    def test_later_exact_thread_optout_overrides_prior_reply_feedback(self):
        from leadhunter.mail_watch import reconcile_mail
        self.insert("node/193", "accepted")
        frozen_id = "c" * 24
        recipient = "synthetic-optout@example.invalid"
        self.db.execute(
            "UPDATE owner_leads SET lead_data=jsonb_set(lead_data,"
            "'{_auto_mail,id}',%s::jsonb,true) WHERE osm_id='node/193'",
            (json.dumps(frozen_id),),
        )
        self.db.execute(
            "UPDATE owner_leads SET lead_data=jsonb_set(lead_data,"
            "'{_auto_mail,reply_feedback}',%s::jsonb,true) WHERE osm_id='node/193'",
            (json.dumps({"state": "sender_matched_reply",
                         "intent": "positive_review"}),),
        )
        changed, pending = reconcile_mail(self.db, [(
            recipient,
            "reply:<" + frozen_id + "@gmail.com>",
            {"intent": "opt_out"},
        )])
        self.assertEqual(changed, 1)
        self.assertEqual(pending, [("node/193", "reply")])
        record = self.db.execute(
            "SELECT lead_data->'_auto_mail',lead_data->'marketing_eligibility' "
            "FROM owner_leads WHERE osm_id='node/193'",
        ).fetchone()
        self.assertEqual(record[0]["reply_feedback"]["intent"], "opt_out")
        self.assertIs(record[1]["opted_out"], True)

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

    def test_scheduled_outreach_never_claims_the_configured_sender_address(self):
        self.insert("node/703")
        env={"AUTO_MAIL_ENABLED":"true",
             "GMAIL_SENDER_ADDRESS":"synthetic@example.invalid"}
        store=AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim("node/703",env))
        record=self.db.execute("SELECT lead_data->'_auto_mail' FROM owner_leads "
                               "WHERE osm_id='node/703'").fetchone()[0]
        self.assertEqual(record["state"],"draft")
        self.assertNotIn("claimed_day",record)

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

    def test_duplicate_review_audit_migration_is_repeatable_and_immutable(self):
        """Exercise migration DDL/triggers on this isolated synthetic schema only."""
        self.db.execute(
            "CREATE TABLE owner_duplicate_review_pairs ("
            "lead_a text NOT NULL,lead_b text NOT NULL,evidence text[] NOT NULL,"
            "review_state text NOT NULL DEFAULT 'needs_review',"
            "last_observed_at timestamptz NOT NULL DEFAULT now(),"
            "PRIMARY KEY(lead_a,lead_b))")
        migration = (Path(__file__).resolve().parents[1] /
                     "migrations/014_duplicate_confidence_audit.sql").read_text(
                         encoding="utf-8")
        # The checked-in migration is schema-qualified for production. Rewrite
        # only its schema identifier so every object stays inside this random
        # synthetic test schema; no production DSN is used by the CI job.
        migration = migration.replace("public.", self.schema + ".")
        migration = migration.replace("pg_catalog, public",
                                      "pg_catalog, " + self.schema)
        self.db.execute(migration)
        self.db.execute(migration)  # must remain safe on a second application

        details = {"method":"heuristic-v1","automatic_merge_allowed":False}
        self.db.execute(
            "INSERT INTO owner_duplicate_review_pairs "
            "(lead_a,lead_b,evidence,confidence_score,confidence_details) "
            "VALUES (%s,%s,%s,%s,%s::jsonb)",
            ("node/100", "way/200", ["same_name_category_review"],
             20, json.dumps(details)))
        # A human decision transition is captured as a second immutable event.
        self.db.execute(
            "UPDATE owner_duplicate_review_pairs SET review_state='not_duplicate' "
            "WHERE lead_a='node/100' AND lead_b='way/200'")
        audit = self.schema + ".owner_duplicate_review_audit"
        pairs = self.schema + ".owner_duplicate_review_pairs"
        self.assertEqual(self.db.execute("SELECT count(*) FROM " + audit).fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT event_type FROM " + audit +
            " ORDER BY audit_id").fetchall(),
            [("candidate_detected",), ("decision_changed",)])

        # Routine sync heartbeats are not decision/evidence changes and do not
        # flood the audit log.
        self.db.execute("UPDATE " + pairs + " SET last_observed_at=now()")
        self.assertEqual(self.db.execute("SELECT count(*) FROM " + audit).fetchone()[0], 2)

        for statement in (
            "UPDATE " + audit + " SET event_type='candidate_detected' WHERE audit_id=1",
            "DELETE FROM " + audit + " WHERE audit_id=1",
            "TRUNCATE " + audit,
        ):
            with self.assertRaisesRegex(self.psycopg.Error, "append-only"):
                self.db.execute(statement)
        self.assertEqual(self.db.execute("SELECT count(*) FROM " + audit).fetchone()[0], 2)

    def test_restart_after_uncertain_result_blocks_recipient(self):
        self.insert('node/1', 'uncertain'); self.insert('node/2')
        store = AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim('node/1'))
        self.assertIsNone(store.claim('node/2'))

