"""One owner error alert attempt per local day; no private data persisted."""
import json
import tempfile
import unittest
from pathlib import Path
from leadhunter.alert_gate import alerted_today, mark_attempt
from leadhunter.hourly_summary import compose
from leadhunter.daily_scan import run


class AlertGateTests(unittest.TestCase):
    def test_only_date_persists_and_next_day_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alert.json"
            self.assertFalse(alerted_today(path, "2026-11-07"))
            mark_attempt(path, "2026-11-07")
            self.assertEqual(json.loads(path.read_text()),
                             {"alert_attempt_day": "2026-11-07"})
            self.assertTrue(alerted_today(path, "2026-11-07"))
            self.assertFalse(alerted_today(path, "2026-11-08"))

    def test_broken_state_suppresses_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alert.json"
            path.write_text("{truncated")
            self.assertTrue(alerted_today(path, "2026-11-07"))

    def test_same_day_failed_scans_send_one_owner_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alert.json"
            messages = []
            env = {"TELEGRAM_BOT_TOKEN": "synthetic",
                   "TELEGRAM_CHAT_ID": "123",
                   "OWNER_ERROR_ALERT_DAILY_GUARD": "true",
                   "ERROR_ALERT_STATE_FILE": str(path)}
            def fail(**kwargs):
                raise RuntimeError("synthetic source failed")
            for i in range(2):
                with self.assertRaises(RuntimeError):
                    run(env,handler=fail,sender=lambda *args: messages.append(args) or 24,
                        today="2026-11-07",output=lambda *_:None)
            self.assertEqual(len(messages),1)
            self.assertNotIn("synthetic source failed",messages[0][0])

    def test_hourly_mail_status_carries_counts_only(self):
        stats = dict(fetched=5,eligible=4,rejected=1,duplicates=0,already_seen=2,new=2)
        summary = compose(stats, 2, "pilot_1_of_8",
                          {"accepted":15,"failed":4,"replied":0})
        self.assertIn("Geçmiş SMTP kabul: 15",summary)
        self.assertIn("Başarısız teslimat: 4",summary)
        self.assertNotIn("@",summary)


if __name__ == "__main__":
    unittest.main()
