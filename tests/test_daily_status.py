"""Daily owner-only reporting: tests use synthetic data, no network or SMTP."""
import unittest
from leadhunter.daily_status import compose, district_coverage, report_day
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile


class DailyStatusTests(unittest.TestCase):
    def test_delayed_schedule_uses_due_utc_date_not_next_istanbul_day(self):
        now=datetime(2026,11,1,21,22,56,tzinfo=timezone.utc)
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"schedule"},now),"2026-11-01")
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"push"},now),"2026-11-02")
        self.assertEqual(report_day({"GITHUB_EVENT_NAME":"schedule"},
                        datetime(2026,11,2,20,59,tzinfo=timezone.utc)),"2026-11-02")

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

    def test_lifecycle_counts_are_reported_separately_from_mail_permission(self):
        counts=dict(total=8,new=1,accepted=0,failed=0,delayed=0,
                    replies=0,duplicate=0,accepted_today=0,eligible=0,
                    lifecycle_recorded=2,
                    lifecycle_stages={"meeting_scheduled":1,"do_not_contact":1})
        text=compose("2026-11-01",counts,True)
        self.assertIn("Kalıcı satış aşaması kaydı: 2 işletme",text)
        self.assertIn("toplantı: 1",text)
        self.assertIn("kaybedildi: 0",text)
        self.assertIn("Geçmişi olmayan CRM kayıtlarına aşama atanmaz",text)

    def test_public_email_research_is_not_reported_as_permission(self):
        counts=dict(total=8,new=1,accepted=0,failed=0,delayed=0,
                    replies=0,duplicate=0,accepted_today=0,eligible=0,
                    email_research_count=10,new_public_addresses=3,
                    email_research_no_address=7)
        text=compose("2026-11-01",counts,False)
        self.assertIn("Resmî işletme sitesi araştırması: 10",text)
        self.assertIn("yeni kamuya açık adres: 3",text)
        self.assertIn("Kamuya açık adres bulunması, e-posta gönderme izni değildir",text)

    def test_daily_report_is_explicit_about_districts_cost_and_system_errors(self):
        counts=dict(total=0,new=0,accepted=0,failed=0,delayed=0,replies=0,
                    duplicate=0,accepted_today=0,eligible=0,
                    districts_completed=0,districts_total=973,
                    system_errors=2,measured_scan_attempts=4)
        text=compose("2026-11-28",counts,False)
        self.assertIn("0/973 ilçe taraması kanıtlandı",text)
        self.assertIn("2 / 4",text)
        self.assertIn("maliyet: ölçülmedi",text)

    def test_district_coverage_counts_only_exact_planned_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"manifest.json"
            path.write_text(json.dumps({
                "province_count":81,"district_count":2,
                "provinces":[{"districts":[{"relation_id":"relation/123"},
                                                {"relation_id":"relation/456"}]}]
            }),encoding="utf-8")
            registry={"provinces":[
                {"plan":{"work_item_ids":["relation/123"]},
                 "completed_items":{"relation/123": {"state":"success"}}},
                {"plan":{"work_item_ids":["relation/456"]},
                 "completed_items":{}},
            ]}
            self.assertEqual(district_coverage(registry,path),(1,2))


if __name__ == '__main__':
    unittest.main()
