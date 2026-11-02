"""Daily owner-only reporting: no network, SMTP or sensitive user data."""
import unittest
from leadhunter.daily_status import compose, report_day
from datetime import datetime, timezone


class DailyStatusTests(unittest.TestCase):
    def test_delayed_schedule_uses_due_utc_date_not_next_istanbul_day(self):
        now=datetime(2026,11,1,21,22,56,tzinfo=timezone.utc)
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"schedule"},now),"2026-11-01")
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"push"},now),"2026-11-02")
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"schedule"},
                        datetime(2026,11,2,20,58,tzinfo=timezone.utc)),"2026-11-02")

    def test_missing_scan_measurements_remain_unknown_not_fake_zero(self):
        counts=dict(total=50,new=11,accepted=15,failed=4,delayed=0,
                    replies=0,duplicate=0,accepted_today=0,eligible=0)
        report=compose("2026-11-02",counts,True)
        self.assertIn("ölçülmedi",report)
        self.assertIn("CRM'e yeni benzersiz aday: 11",report)
        self.assertIn("KAPALI",report)

    def test_recorded_scan_counters_are_separate_and_explicitly_partial(self):
        counts=dict(total=61,new=11,accepted=15,failed=4,delayed=0,
                    replies=0,duplicate=0,accepted_today=0,eligible=0,
                    inspected=46,found_addresses=1,checked_mx=1,measured_runs=1)
        report=compose("2026-11-02",counts,True)
        self.assertIn("İncelenen işletme: 46",report)
        self.assertIn("Yeni kaydedilen teknik adres: 1",report)
        self.assertIn("format+DNS MX kontrolünü geçen: 1",report)
        self.assertIn("tekrarları içerir",report)

    def test_paused_reputation_is_not_labeled_live(self):
        counts=dict(total=50,new=0,accepted=15,failed=3,delayed=1,
                    replies=0,duplicate=0,accepted_today=0,eligible=0)
        text=compose("2026-11-01",counts,True)
        self.assertIn("KAPALI",text)
        self.assertIn("itibar",text)
        self.assertIn("15",text)
        self.assertNotIn("@",text)

    def test_eligible_does_not_imply_smtp_delivery(self):
        counts=dict(total=2,new=1,accepted=0,failed=0,delayed=0,
                    replies=0,duplicate=0,accepted_today=0,eligible=1)
        text=compose("2026-11-01",counts,True)
        self.assertIn("KOŞULLU",text)
        self.assertIn("teslim kanıtı değildir",text)


if __name__ == '__main__':
    unittest.main()
