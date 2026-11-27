"""Offline transaction-boundary tests for district lead/receipt commits."""
from __future__ import annotations

import copy
import json
import unittest
from contextlib import contextmanager

from leadhunter import province_coverage as model
from leadhunter.province_coverage_store import commit_district_batch


NOW = "2026-11-25T10:00:00+00:00"
SOURCE = "https://download.example.org/turkey.osm.pbf"
PBF_SHA = "a" * 64


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.db.statements.append(sql)
        if sql.startswith("SELECT pg_advisory_xact_lock"):
            self.result = None
        elif sql.startswith("SELECT province_code,province_name"):
            self.result = [
                (code, row["name"], row["initial_phase_target"], row["status"],
                 copy.deepcopy(row))
                for code, row in sorted(self.db.provinces.items())
            ]
        elif sql.startswith("INSERT INTO owner_leads"):
            lead_id, raw = params
            if lead_id in self.db.leads:
                self.result = None
            else:
                self.db.leads[lead_id] = json.loads(raw)
                self.result = (lead_id,)
        elif sql.startswith("SELECT osm_id,lead_data FROM owner_leads"):
            self.result = [(lead_id, self.db.leads[lead_id])
                           for lead_id in params[0] if lead_id in self.db.leads]
        elif sql.startswith("INSERT INTO owner_osm_incremental_changes"):
            lead_id, digest, source_at, fields, proposed = params
            prior = self.db.incremental_changes.get(lead_id)
            if prior is None or prior["source_data_at"] < source_at:
                self.db.incremental_changes[lead_id] = {
                    "snapshot_sha256": digest, "source_data_at": source_at,
                    "fields_changed": list(fields), "proposed_lead": json.loads(proposed),
                    "review_state": "needs_review",
                }
                self.result = (lead_id,)
            else:
                self.result = None
        elif sql.startswith("SELECT to_regclass"):
            self.result = ("owner_osm_incremental_changes"
                           if self.db.incremental_changes_ready else None,)
        elif sql.startswith("UPDATE owner_province_scan_coverage"):
            if self.db.fail_coverage_update:
                raise RuntimeError("synthetic update failure")
            name, target, status, raw, code = params
            self.db.provinces[code] = json.loads(raw)
            self.db.provinces[code]["name"] = name
            self.db.provinces[code]["initial_phase_target"] = target
            self.db.provinces[code]["status"] = status
            self.rowcount = 1
            self.result = None
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self):
        registry = model.new_registry()
        registry = model.configure_plan(
            registry, "06", source_url="https://example.org/boundaries.json",
            source_sha256="b" * 64, work_item_ids=("relation/101",),
            configured_at=NOW)
        registry = model.begin_attempt(registry, "06", attempt_id="run-1",
                                       started_at=NOW, source_sha256=PBF_SHA)
        self.provinces = {row["code"]: copy.deepcopy(row)
                          for row in registry["provinces"]}
        self.leads = {}
        self.incremental_changes = {}
        self.incremental_changes_ready = False
        self.statements = []
        self.fail_coverage_update = False

    @contextmanager
    def transaction(self):
        old = copy.deepcopy((self.provinces, self.leads, self.incremental_changes,
                             self.statements))
        try:
            yield
        except Exception:
            (self.provinces, self.leads, self.incremental_changes,
             self.statements) = old
            raise

    def cursor(self):
        return _Cursor(self)


class ProvinceCoverageStoreBatchTests(unittest.TestCase):
    def setUp(self):
        self.db = _Connection()
        self.leads = [{"id": "node/9001", "name": "Örnek İşletme",
                       "category": "restaurant"}]

    def commit(self, *, item_id="relation/101", leads=None):
        return commit_district_batch(
            self.db, "06", "run-1", item_id,
            leads=self.leads if leads is None else leads,
            records_count=len(self.leads if leads is None else leads),
            observed_at=NOW, source_url=SOURCE,
            source_data_at=NOW, source_sha256=PBF_SHA)

    def test_lead_and_success_receipt_commit_together_with_provenance(self):
        result = self.commit()
        self.assertFalse(result["replayed"])
        self.assertEqual(result["new_leads"], 1)
        self.assertEqual(set(self.db.leads), {"node/9001"})
        stored = self.db.leads["node/9001"]["discovery_provenance"]
        self.assertEqual(stored["province_code"], "06")
        self.assertEqual(stored["district_relation_id"], "relation/101")
        self.assertEqual(stored["source_sha256"], PBF_SHA)
        state = self.db.provinces["06"]
        receipt = state["completed_items"]["relation/101"]
        self.assertEqual(receipt["source_sha256"], PBF_SHA)
        self.assertEqual(receipt["lead_count"], 1)
        self.assertEqual(state["attempts"][-1]["results"]["relation/101"], receipt)

    def test_identical_retry_is_noop_and_does_not_rewrite_crm(self):
        self.commit()
        statements = list(self.db.statements)
        result = self.commit()
        self.assertTrue(result["replayed"])
        self.assertEqual(result["new_leads"], 0)
        self.assertEqual(len(self.db.statements), len(statements) + 2)  # lock + read only
        self.assertFalse(any(sql.startswith(("INSERT", "UPDATE"))
                             for sql in self.db.statements[len(statements):]))

    def test_different_retry_is_rejected_without_overwriting_anything(self):
        self.commit()
        before = copy.deepcopy((self.db.provinces, self.db.leads))
        with self.assertRaises(ValueError):
            self.commit(leads=[{"id": "node/9001", "name": "Changed"}])
        self.assertEqual((self.db.provinces, self.db.leads), before)

    def test_invalid_and_duplicate_ids_fail_before_writes(self):
        with self.assertRaises(ValueError):
            self.commit(leads=[{"id": "not-osm"}])
        with self.assertRaises(ValueError):
            self.commit(leads=[{"id": "node/2"}, {"id": "node/2"}])
        self.assertEqual(self.db.leads, {})

    def test_batch_source_digest_must_match_persisted_attempt_digest(self):
        with self.assertRaisesRegex(ValueError, "does not match its active attempt"):
            commit_district_batch(
                self.db, "06", "run-1", "relation/101", leads=self.leads,
                records_count=1, observed_at=NOW, source_url=SOURCE,
                source_data_at=NOW, source_sha256="c" * 64,
            )
        self.assertEqual(self.db.leads, {})

    def test_out_of_plan_district_rolls_back_without_lead_or_receipt(self):
        with self.assertRaises(ValueError):
            self.commit(item_id="relation/999")
        self.assertEqual(self.db.leads, {})
        self.assertEqual(self.db.provinces["06"]["completed_items"], {})

    def test_database_failure_rolls_back_lead_and_receipt_as_one_unit(self):
        before = copy.deepcopy((self.db.provinces, self.db.leads))
        self.db.fail_coverage_update = True
        with self.assertRaises(RuntimeError):
            self.commit()
        self.assertEqual((self.db.provinces, self.db.leads), before)

    def test_changed_existing_osm_business_is_queued_without_overwriting_crm(self):
        self.db.leads["node/9001"] = {
            "id": "node/9001", "name": "Eski Ad", "category": "restaurant",
            "website": "https://old.example", "phone": "111", "email": "old@example.org",
            "address": "Eski adres", "status": "sent",
        }
        self.db.incremental_changes_ready = True
        changed = [{"id": "node/9001", "name": "Yeni Ad", "category": "restaurant",
                    "website": "https://new.example", "phone": "222",
                    "email": "new@example.org", "address": "Yeni adres"}]
        result = commit_district_batch(
            self.db, "06", "run-1", "relation/101", leads=changed,
            records_count=1, observed_at=NOW, source_url=SOURCE,
            source_data_at=NOW, source_sha256=PBF_SHA,
        )
        self.assertEqual(result["new_leads"], 0)
        self.assertEqual(result["changed_existing"], 1)
        self.assertEqual(self.db.leads["node/9001"]["name"], "Eski Ad")
        self.assertEqual(self.db.leads["node/9001"]["status"], "sent")
        proposal = self.db.incremental_changes["node/9001"]
        self.assertEqual(set(proposal["fields_changed"]),
                         {"name", "website", "phone", "email", "address"})
        self.assertEqual(proposal["proposed_lead"]["name"], "Yeni Ad")

    def test_changed_existing_requires_review_queue_migration(self):
        self.db.leads["node/9001"] = {"id": "node/9001", "name": "Eski Ad"}
        with self.assertRaisesRegex(RuntimeError, "migration 009"):
            self.commit(leads=[{"id": "node/9001", "name": "Yeni Ad"}])
        self.assertEqual(self.db.leads["node/9001"]["name"], "Eski Ad")
        self.assertEqual(self.db.provinces["06"]["completed_items"], {})

    def test_older_snapshot_cannot_replace_a_newer_pending_change_proposal(self):
        self.db.leads["node/9001"] = {
            "id": "node/9001", "name": "Eski Ad", "category": "restaurant",
        }
        self.db.incremental_changes_ready = True
        self.db.incremental_changes["node/9001"] = {
            "source_data_at": "2026-11-26T10:00:00+00:00",
            "snapshot_sha256": "c" * 64,
            "fields_changed": ["name"],
            "proposed_lead": {"id": "node/9001", "name": "Daha Yeni"},
            "review_state": "needs_review",
        }
        result = commit_district_batch(
            self.db, "06", "run-1", "relation/101",
            leads=[{"id": "node/9001", "name": "Eski Snapshot Adı"}],
            records_count=1, observed_at=NOW, source_url=SOURCE,
            source_data_at=NOW, source_sha256=PBF_SHA,
        )
        self.assertEqual(result["changed_existing"], 0)
        self.assertEqual(self.db.incremental_changes["node/9001"]["proposed_lead"]["name"],
                         "Daha Yeni")

    def test_atomic_batch_accepts_more_than_the_old_one_thousand_limit(self):
        many = [{"id": f"node/{value}", "name": f"Business {value}"}
                for value in range(1, 1002)]
        result = self.commit(leads=many)
        self.assertEqual(result["new_leads"], 1001)
        self.assertEqual(result["changed_existing"], 0)
        self.assertEqual(len(self.db.leads), 1001)


if __name__ == "__main__":
    unittest.main()
