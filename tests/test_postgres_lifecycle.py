"""Synthetic PostgreSQL checks for private lifecycle migration/store only."""
import json
import os
from pathlib import Path
import re
import unittest
import uuid

from leadhunter.lifecycle import IdempotencyConflict, OptOutProtected
from leadhunter.lifecycle_store import read_stage, record_transition


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "isolated test Postgres required")
class PostgresLifecycleTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.schema = "synthetic_lifecycle_" + uuid.uuid4().hex
        self.db = psycopg.connect(os.environ["TEST_POSTGRES_DSN"], autocommit=True)
        self.db.execute(f'CREATE SCHEMA "{self.schema}"')
        self.db.execute(
            f'CREATE TABLE "{self.schema}".owner_leads ('
            "osm_id text PRIMARY KEY, lead_data jsonb NOT NULL, status text NOT NULL)"
        )
        self.addCleanup(self._cleanup)
        migration = Path("migrations/017_owner_lead_lifecycle.sql").read_text(encoding="utf-8")
        migration = migration.replace("public.", f'"{self.schema}".')
        self.db.execute(migration)

    def _cleanup(self):
        self.db.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.db.close()

    def _insert_lead(self, lead_id="node/7654321", lead_data=None, status="review"):
        data = lead_data or {"name": "Synthetic business"}
        self.db.execute(
            f'INSERT INTO "{self.schema}".owner_leads VALUES (%s,%s::jsonb,%s)',
            (lead_id, json.dumps(data), status),
        )
        return lead_id

    def _move(self, lead_id, stage, key, *, reason="Synthetic evidence reviewed",
              refs=("manual://synthetic-acceptance",)):
        return record_transition(
            self.db, lead_id, stage, idempotency_key=key, reason=reason,
            evidence_refs=refs, schema=self.schema)

    def test_idempotency_stage_history_and_state_are_atomic(self):
        lead_id = self._insert_lead()
        first = self._move(lead_id, "new_discovered", "discover:node/7654321")
        self.assertTrue(first["changed"])
        replay = self._move(lead_id, "new_discovered", "discover:node/7654321")
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["event_id"], replay["event_id"])

        with self.assertRaises(IdempotencyConflict):
            self._move(lead_id, "researched", "discover:node/7654321")

        self._move(lead_id, "researched", "research:node/7654321")
        self._move(lead_id, "need_verified", "need:node/7654321")
        self._move(lead_id, "communication_eligible", "eligible:node/7654321")
        current = read_stage(self.db, lead_id, schema=self.schema)
        self.assertEqual(current["stage"], "communication_eligible")

        with self.db.cursor() as cur:
            cur.execute(
                f'SELECT count(*) FROM "{self.schema}".owner_lead_lifecycle_events '
                "WHERE lead_id=%s", (lead_id,))
            self.assertEqual(cur.fetchone()[0], 4)
            cur.execute(
                f'SELECT lead_data FROM "{self.schema}".owner_leads WHERE osm_id=%s',
                (lead_id,))
            data = cur.fetchone()[0]
            self.assertNotIn("marketing_eligibility", data)
            self.assertNotIn("_auto_mail", data)

    def test_event_history_rejects_update_delete_and_opt_out_is_terminal(self):
        lead_id = self._insert_lead(
            lead_data={"marketing_eligibility": {"opted_out": True}})
        with self.assertRaises(OptOutProtected):
            self._move(lead_id, "new_discovered", "bad:initial-opt-in")
        result = self._move(
            lead_id, "do_not_contact", "suppression:node/7654321",
            reason="Verified opt-out", refs=("gmail-message://synthetic-42",))
        self.assertEqual(result["current_stage"], "do_not_contact")
        with self.assertRaises(OptOutProtected):
            self._move(lead_id, "researched", "bad:reopen-opt-out")

        with self.assertRaises(self.psycopg.errors.RaiseException):
            self.db.execute(
                f'UPDATE "{self.schema}".owner_lead_lifecycle_events '
                "SET reason='rewritten' WHERE lead_id=%s", (lead_id,))
        with self.assertRaises(self.psycopg.errors.RaiseException):
            self.db.execute(
                f'DELETE FROM "{self.schema}".owner_lead_lifecycle_events '
                "WHERE lead_id=%s", (lead_id,))

    def test_missing_crm_lead_is_not_created_by_lifecycle(self):
        with self.assertRaises(ValueError):
            self._move("node/does-not-exist", "new_discovered", "discover:missing-1")


if __name__ == "__main__":
    unittest.main()
