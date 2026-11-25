import unittest

from leadhunter.province_coverage import (
    INITIAL_PHASE_CITY_CODES, PROVINCES, begin_attempt, configure_plan,
    coverage_table, finish_attempt, new_registry, record_item_result,
)


NOW = "2026-11-25T10:00:00+00:00"
SOURCE = "https://download.geofabrik.de/europe/turkey/index.html"
HASH = "a" * 64


class ProvinceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.registry = new_registry()

    def plan(self, code="34", items=("chunk-a", "chunk-b", "pilot-coverage")):
        return configure_plan(
            self.registry, code, source_url=SOURCE, source_sha256=HASH,
            work_item_ids=items, excluded_item_ids=("pilot-coverage",),
            configured_at=NOW)

    def test_registry_has_81_rows_and_exact_first_phase_targets(self):
        self.assertEqual(len(PROVINCES), 81)
        rows = coverage_table(self.registry)
        self.assertEqual(len(rows), 81)
        self.assertEqual(sum(row["initial_phase_target"] for row in rows), 10)
        self.assertEqual({row["status"] for row in rows}, {"pending"})
        self.assertEqual({row["status"] for row in rows if row["initial_phase_target"]},
                         {"pending"})
        self.assertEqual(next(r for r in rows if r["code"] == "34")["province"], "İstanbul")

    def test_coverage_table_exposes_persisted_source_digest(self):
        self.registry = self.plan("34")
        row = next(r for r in coverage_table(self.registry) if r["code"] == "34")
        self.assertEqual(row["source_sha256"], HASH)

    def test_no_boundary_manifest_means_no_attempt(self):
        with self.assertRaisesRegex(ValueError, "manifest is not configured"):
            begin_attempt(self.registry, "06", attempt_id="run-1", started_at=NOW)

    def test_resume_uses_only_not_yet_confirmed_items_and_excludes_pilot(self):
        planned = self.plan()
        running = begin_attempt(planned, "34", attempt_id="run-1", started_at=NOW)
        with self.assertRaisesRegex(ValueError, "already has a running"):
            begin_attempt(running, "34", attempt_id="run-parallel", started_at=NOW)
        running = record_item_result(
            running, "34", "run-1", "chunk-a", succeeded=True, observed_at=NOW,
            source_url=SOURCE, source_data_at=NOW, records_count=12)
        running = record_item_result(
            running, "34", "run-1", "chunk-b", succeeded=False, observed_at=NOW,
            error_code="rate_limited")
        partial = finish_attempt(running, "34", "run-1", finished_at=NOW)
        row = next(r for r in coverage_table(partial) if r["code"] == "34")
        self.assertEqual((row["status"], row["completed_items"], row["total_items"]),
                         ("partial", 1, 2))
        resumed = begin_attempt(partial, "34", attempt_id="run-2", started_at=NOW)
        attempt = next(a for a in resumed["provinces"] if a["code"] == "34")["attempts"][-1]
        self.assertEqual(attempt["planned_item_ids"], ["chunk-b"])
        self.assertNotIn("pilot-coverage", attempt["planned_item_ids"])
        resumed = record_item_result(
            resumed, "34", "run-2", "chunk-b", succeeded=True, observed_at=NOW,
            source_url=SOURCE, source_data_at=NOW, records_count=0)
        completed = finish_attempt(resumed, "34", "run-2", finished_at=NOW)
        row = next(r for r in coverage_table(completed) if r["code"] == "34")
        self.assertEqual((row["status"], row["completed_items"], row["coverage_percent"]),
                         ("completed", 2, 100))
        with self.assertRaisesRegex(ValueError, "cannot be scanned again"):
            begin_attempt(completed, "34", attempt_id="run-3", started_at=NOW)

    def test_failures_and_empty_attempts_never_claim_coverage(self):
        planned = self.plan("06", ("chunk-1", "pilot-coverage"))
        running = begin_attempt(planned, "06", attempt_id="run-empty", started_at=NOW)
        failed = finish_attempt(running, "06", "run-empty", finished_at=NOW)
        row = next(r for r in coverage_table(failed) if r["code"] == "06")
        self.assertEqual((row["status"], row["coverage_percent"]), ("failed", 0))
        running = begin_attempt(failed, "06", attempt_id="run-fail", started_at=NOW)
        running = record_item_result(
            running, "06", "run-fail", "chunk-1", succeeded=False,
            observed_at=NOW, error_code="source_unavailable")
        failed = finish_attempt(running, "06", "run-fail", finished_at=NOW)
        self.assertEqual(next(r for r in coverage_table(failed) if r["code"] == "06")["status"],
                         "failed")

    def test_evidence_and_idempotency_gates_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "HTTPS source"):
            configure_plan(self.registry, "35", source_url="http://example.test",
                           source_sha256=HASH, work_item_ids=("x",), configured_at=NOW)
        planned = self.plan("35", ("chunk-1", "pilot-coverage"))
        running = begin_attempt(planned, "35", attempt_id="run-1", started_at=NOW)
        with self.assertRaisesRegex(ValueError, "timezone"):
            record_item_result(running, "35", "run-1", "chunk-1", succeeded=True,
                               observed_at=NOW, source_url=SOURCE,
                               source_data_at="2026-11-25T10:00:00", records_count=0)
        success = record_item_result(
            running, "35", "run-1", "chunk-1", succeeded=True, observed_at=NOW,
            source_url=SOURCE, source_data_at=NOW, records_count=0)
        with self.assertRaisesRegex(ValueError, "already has a result"):
            record_item_result(success, "35", "run-1", "chunk-1", succeeded=True,
                               observed_at=NOW, source_url=SOURCE,
                               source_data_at=NOW, records_count=0)

    def test_plan_cannot_be_rewritten_after_source_receipts_exist(self):
        planned = self.plan("41", ("chunk-1", "pilot-coverage"))
        running = begin_attempt(planned, "41", attempt_id="run-1", started_at=NOW)
        running = record_item_result(
            running, "41", "run-1", "chunk-1", succeeded=True, observed_at=NOW,
            source_url=SOURCE, source_data_at=NOW, records_count=1)
        partial = finish_attempt(running, "41", "run-1", finished_at=NOW)
        with self.assertRaisesRegex(ValueError, "immutable after source receipts"):
            configure_plan(partial, "41", source_url=SOURCE,
                           source_sha256="b" * 64,
                           work_item_ids=("new-chunk", "pilot-coverage"),
                           excluded_item_ids=("pilot-coverage",), configured_at=NOW)


if __name__ == "__main__":
    unittest.main()
