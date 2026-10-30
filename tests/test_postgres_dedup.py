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

    def race(self, ids):
        barrier = Barrier(2)
        def claim(lid):
            with self.psycopg.connect(os.environ['TEST_POSTGRES_DSN'], autocommit=True) as db:
                db.execute('SET search_path TO ' + self.schema)
                db.execute("SET statement_timeout = '5s'")
                barrier.wait(timeout=5)
                return AutoMailStore(ReviewStore(db)).claim(lid)
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

    def test_restart_after_uncertain_result_blocks_recipient(self):
        self.insert('node/1', 'uncertain'); self.insert('node/2')
        store = AutoMailStore(ReviewStore(self.db))
        self.assertIsNone(store.claim('node/1'))
        self.assertIsNone(store.claim('node/2'))
