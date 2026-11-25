"""Synthetic PostgreSQL persistence/concurrency checks; no production DSN."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DSN"), "isolated test Postgres required")
class ProvinceCoveragePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.schema = "synthetic_province_" + uuid.uuid4().hex
        self.db = psycopg.connect(os.environ["TEST_POSTGRES_DSN"], autocommit=True)
        self.db.execute("CREATE SCHEMA " + self.schema)
        self.db.execute("SET search_path TO " + self.schema)
        migration = Path(__file__).resolve().parents[1] / "migrations" / "016_owner_province_scan_coverage.sql"
        sql = migration.read_text(encoding="utf-8")
        self.db.execute(sql)
        self.db.execute(sql)  # idempotent application
        from leadhunter.province_coverage_store import initialize, read
        self.initialize = initialize
        self.read = read
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.db.execute("DROP SCHEMA " + self.schema + " CASCADE")
        self.db.close()

    def test_initialization_is_idempotent_and_preserves_existing_rows(self):
        self.assertEqual(self.initialize(self.db), 81)
        first = self.read(self.db)
        self.assertEqual({row["status"] for row in first["provinces"]}, {"pending"})
        self.assertEqual(sum(row["initial_phase_target"] for row in first["provinces"]), 10)
        from leadhunter.province_coverage_store import configure_plan
        configure_plan(self.db, "34", source_url="https://example.org/boundary.json",
                       source_sha256="a"*64, work_item_ids=("tile-1",), configured_at=NOW)
        self.assertEqual(self.initialize(self.db), 81)
        after = self.read(self.db)
        self.assertEqual(next(x for x in after["provinces"] if x["code"] == "34")["plan"]["source_sha256"], "a"*64)
        self.assertEqual(self.db.execute("SELECT count(*) FROM owner_province_scan_coverage").fetchone()[0], 81)

    def test_partial_run_resumes_without_recounting_successful_items(self):
        from leadhunter.province_coverage_store import (
            begin_attempt, configure_plan, finish_attempt, record_item_result,
        )
        self.initialize(self.db)
        configure_plan(self.db, "06", source_url="https://example.org/boundary.json",
                       source_sha256="b"*64, work_item_ids=("tile-a", "tile-b"), configured_at=NOW)
        begin_attempt(self.db, "06", attempt_id="run-1", started_at=NOW)
        record_item_result(self.db, "06", "run-1", "tile-a", succeeded=True,
                           observed_at=NOW, source_url="https://example.org/osm.pbf",
                           source_data_at=NOW, records_count=0)
        record_item_result(self.db, "06", "run-1", "tile-b", succeeded=False,
                           observed_at=NOW, error_code="rate_limited")
        partial = finish_attempt(self.db, "06", "run-1", finished_at=NOW)
        row = next(x for x in partial["provinces"] if x["code"] == "06")
        self.assertEqual(row["status"], "partial")
        begin_attempt(self.db, "06", attempt_id="run-2", started_at=NOW)
        current = self.read(self.db)
        attempt = next(x for x in current["provinces"] if x["code"] == "06")["attempts"][-1]
        self.assertEqual(attempt["planned_item_ids"], ["tile-b"])
        record_item_result(self.db, "06", "run-2", "tile-b", succeeded=True,
                           observed_at=NOW, source_url="https://example.org/osm.pbf",
                           source_data_at=NOW, records_count=3)
        completed = finish_attempt(self.db, "06", "run-2", finished_at=NOW)
        self.assertEqual(next(x for x in completed["provinces"] if x["code"] == "06")["status"], "completed")

    def test_concurrent_attempts_cannot_start_for_same_province(self):
        from leadhunter.province_coverage_store import begin_attempt, configure_plan
        self.initialize(self.db)
        configure_plan(self.db, "35", source_url="https://example.org/boundary.json",
                       source_sha256="c"*64, work_item_ids=("tile-a", "tile-b"), configured_at=NOW)
        barrier = Barrier(2)

        def start(run_id):
            with self.psycopg.connect(os.environ["TEST_POSTGRES_DSN"], autocommit=True) as conn:
                conn.execute("SET search_path TO " + self.schema)
                conn.execute("SET statement_timeout='5s'")
                barrier.wait(timeout=5)
                try:
                    begin_attempt(conn, "35", attempt_id=run_id, started_at=NOW)
                    return "started"
                except ValueError:
                    return "already_running"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(start, ("run-a", "run-b")))
        self.assertEqual(outcomes.count("started"), 1)
        self.assertEqual(outcomes.count("already_running"), 1)
        current = self.read(self.db)
        attempts = next(x for x in current["provinces"] if x["code"] == "35")["attempts"]
        self.assertEqual(len(attempts), 1)


NOW = "2026-11-25T10:00:00+00:00"


if __name__ == "__main__":
    unittest.main()
