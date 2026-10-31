"""Synthetic, credential-free daily retry and failure alert tests."""
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter import daily_scan


class DailyScannerTests(unittest.TestCase):
    def test_ignores_successful_date_on_backup(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "date.json"
            p.write_text('{"last_sent_date": "2026-10-26"}')
            called = []
            self.assertEqual(daily_scan.run(
                {"DIGEST_DAILY_GUARD":"true", "DIGEST_DAY_STATE_FILE":str(p)},
                handler=lambda **kwargs: called.append(1),
                today="2026-10-26", output=lambda *_: None), 0)
            self.assertEqual(called, [])

    def test_records_date_only_after_confirmed_owner_send(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "date.json"
            env = {"DIGEST_DAILY_GUARD":"true","DIGEST_DAY_STATE_FILE":str(p)}
            self.assertEqual(daily_scan.run(env,handler=lambda **kw: 3,
                                            today="2026-10-26"),3)
            self.assertEqual(json.loads(p.read_text()), {"last_sent_date":"2026-10-26"})

    def test_empty_scan_does_not_prevent_backup(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "date.json"
            env = {"DIGEST_DAILY_GUARD":"true","DIGEST_DAY_STATE_FILE":str(p)}
            self.assertEqual(daily_scan.run(env,handler=lambda **kw:0,
                                            today="2026-10-26"),0)
            self.assertFalse(p.exists())

    def test_hourly_scan_continues_same_day_without_resending_old_leads(self):
        # A successful owner delivery no longer prevents hourly research.
        # The real scanner's persisted seen IDs and private DB still dedupe.
        with tempfile.TemporaryDirectory() as td:
            day=Path(td)/"last_digest_day.json"
            day.write_text('{"last_sent_date":"2026-11-01"}')
            calls=[]
            def fake_scan(**kw):
                calls.append(1)
                return 1 if len(calls)==1 else 0
            env={"DIGEST_DAILY_GUARD":"false","DIGEST_DAY_STATE_FILE":str(day)}
            self.assertEqual(daily_scan.run(env,handler=fake_scan,
                                            today="2026-11-01",output=lambda *_: None),1)
            self.assertEqual(daily_scan.run(env,handler=fake_scan,
                                            today="2026-11-01",output=lambda *_: None),0)
            self.assertEqual(len(calls),2)
            self.assertEqual(json.loads(day.read_text()),{"last_sent_date":"2026-11-01"})

    def test_production_hourly_workflow_has_protected_smtp(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/
                ".github/workflows/lead-digest.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '13 * * * *'",source)
        self.assertNotIn("cron: '23 7 * * 1-5'",source)
        self.assertIn("AUTO_MAIL_ENABLED: 'false'",source)
        self.assertIn("AUTO_MAIL_DAILY_LIMIT: '5'",source)
        self.assertIn("secrets.GMAIL_APP_PASSWORD",source)
        self.assertIn("DIGEST_DAILY_GUARD: 'false'",source)
        self.assertIn("concurrency:",source)

    def test_manual_run_bypasses_previous_date_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"date.json"
            p.write_text('{"last_sent_date": "2026-10-26"}')
            self.assertEqual(daily_scan.run(
                {"DIGEST_DAILY_GUARD":"false","DIGEST_DAY_STATE_FILE":str(p)},
                handler=lambda **kw: 1,today="2026-10-26"),1)
            self.assertEqual(json.loads(p.read_text()), {"last_sent_date":"2026-10-26"})

    def test_errors_send_only_one_redacted_owner_alert(self):
        outputs, calls = [], []
        def failed(**_):
            raise RuntimeError("sensitive network detail")
        def sender(text, token, chat):
            calls.append((text, token, chat))
        with self.assertRaisesRegex(RuntimeError, "sensitive network detail"):
            daily_scan.run({"TELEGRAM_BOT_TOKEN":"fixture-secret",
                            "TELEGRAM_CHAT_ID":"123"},
                           handler=failed,sender=sender,output=outputs.append,
                           today="2026-10-26")
        self.assertEqual(len(calls),1)
        self.assertNotIn("fixture-secret",calls[0][0])
        self.assertIn("HATA",calls[0][0])
        self.assertNotIn("sensitive network detail",calls[0][0])
        self.assertNotIn("fixture-secret"," ".join(outputs))

    def test_missing_bot_does_not_attempt_network(self):
        def failed(**_):
            raise RuntimeError("source down")
        with self.assertRaisesRegex(RuntimeError, "source down"):
            daily_scan.run({},handler=failed,
                           sender=lambda *a: self.fail("no owner secrets"),
                           today="2026-10-26",output=lambda *_: None)

    def test_corrupt_guard_never_calls_scanner(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"date.json"
            p.write_text("{broken")
            with self.assertRaisesRegex(RuntimeError,"Corrupt daily delivery guard"):
                daily_scan.run({"DIGEST_DAILY_GUARD":"true",
                                "DIGEST_DAY_STATE_FILE":str(p)},
                                handler=lambda **kw: self.fail("duplicate scan"),
                                today="2026-10-26",output=lambda *_: None)


if __name__=="__main__":
    unittest.main()
