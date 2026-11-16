"""Prevent a stale hourly metric from hiding real snapshot-added CRM rows."""
import unittest
from pathlib import Path

class PanelActualNewTodayTests(unittest.TestCase):
    def test_view_counts_private_lead_first_seen_not_only_hourly_scans(self):
        sql=(Path(__file__).resolve().parents[1] /
             "migrations/008_control_center_actual_new_today.sql").read_text()
        self.assertIn("CREATE OR REPLACE VIEW control_center_musteri_v1",sql)
        self.assertIn("WITH (security_barrier=true)",sql)
        self.assertIn("(first_seen_at AT TIME ZONE 'Europe/Istanbul')::date",sql)
        self.assertIn("AS new_today",sql)
        self.assertNotIn("sum(new_registered)",sql)
        self.assertNotIn("UPDATE owner_leads ",sql)
        self.assertNotIn("DELETE FROM owner_leads",sql)

if __name__=="__main__":
    unittest.main()
