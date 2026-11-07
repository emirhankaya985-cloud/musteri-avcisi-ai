"""Public-only owner reports use persisted OSM tiles, never inferred progress."""
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.coverage_report import coverage_text
from leadhunter.hourly_summary import compose
from leadhunter.telegram_buttons import status_message


class CoverageOwnerReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"progress.json"
        self.path.write_text(json.dumps({"version":1,"regions":{
            "pilot_1_of_8":{"next":4,"total":48,"cycle":0},
            "pilot_8_of_8":{"next":2,"total":48,"cycle":0,"stalls":3}
        }}),encoding="utf-8")
        self.stats={"fetched":78,"eligible":75,"rejected":3,
                    "duplicates":0,"already_seen":74,"new":1}

    def test_per_region_coverage_from_actual_state(self):
        text=coverage_text(self.path,details=True)
        self.assertIn("6/402",text)
        self.assertIn("1:4/48",text)
        self.assertIn("8:2/48",text)
        self.assertIn("İlerlemeyen bölgeler: 8",text)
        self.assertNotIn("@",text)

    def test_hourly_telegram_reports_public_verified_progress(self):
        message=compose(self.stats,1,"pilot_1_of_8",
                        {"accepted":15,"failed":4,"replied":0},
                        coverage_path=self.path)
        self.assertIn("6/402",message)
        self.assertIn("SMTP kabul: 15",message)
        self.assertIn("yeni",message.casefold())
        self.assertNotIn("synthetic@example",message)

    def test_private_owner_command_uses_same_ledger(self):
        msg=status_message({"STATE_FILE":str(Path(self.tmp.name)/"seen.json"),
                            "TILE_PROGRESS_FILE":str(self.path)})
        self.assertIn("6/402",msg)
        self.assertIn("1:4/48",msg)

    def test_invalid_or_missing_ledger_fails_closed(self):
        self.assertIn("henüz kalıcı kanıt yok",coverage_text(self.path.parent/"absent.json"))
        self.path.write_text("{broken",encoding="utf-8")
        self.assertIn("doğrulanamadı",coverage_text(self.path))
        self.assertNotIn("6/402",coverage_text(self.path))


if __name__=="__main__":
    unittest.main()
