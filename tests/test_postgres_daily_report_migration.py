"""Repeatable provenance migration test against the isolated CI PostgreSQL."""
import os
from pathlib import Path
import unittest


class DailyReportMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get("TEST_POSTGRES_DSN")
        if not dsn:
            raise unittest.SkipTest("TEST_POSTGRES_DSN is unavailable")
        import psycopg
        cls.conn = psycopg.connect(dsn, autocommit=True)
        db_name = cls.conn.execute("SELECT current_database()").fetchone()[0]
        if "synthetic" not in db_name:
            cls.conn.close()
            raise RuntimeError("Refusing migration test outside synthetic database")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "conn") and not cls.conn.closed:
            cls.conn.execute("DROP TABLE IF EXISTS public.owner_daily_report_receipts CASCADE")
            cls.conn.close()

    def test_migration_is_repeatable_and_checks_target_table(self):
        self.conn.execute("DROP TABLE IF EXISTS public.owner_daily_report_receipts CASCADE")
        self.conn.execute("CREATE TABLE public.owner_daily_report_receipts (report_day date PRIMARY KEY)")
        sql = Path("migrations/015_owner_daily_report_provenance.sql").read_text(encoding="utf-8")
        self.conn.execute(sql)
        self.conn.execute(sql)
        constraints = self.conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid='public.owner_daily_report_receipts'::regclass "
            "ORDER BY conname").fetchall()
        self.assertEqual(len(constraints), 5)
        with self.assertRaises(Exception):
            self.conn.execute(
                "INSERT INTO public.owner_daily_report_receipts "
                "(report_day,github_run_attempt) VALUES ('2026-01-01',0)")
        self.conn.execute("ROLLBACK")


if __name__ == "__main__":
    unittest.main()
