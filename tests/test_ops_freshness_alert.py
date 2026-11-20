"""No-network incident dedup and safe owner-only notification regressions."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from leadhunter.ops_freshness_alert import send_once


class FakeDatabase:
    def __init__(self, now, *, fresh=False):
        self.scan = now - timedelta(minutes=40 if fresh else 250)
        self.gmail = now - timedelta(minutes=40 if fresh else 260)
        self.source = now - timedelta(days=1)
        self.rows = {}
        self.sql = ""
        self.insert_result = None

    def cursor(self):
        return self

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.sql = sql
        if sql.startswith("INSERT INTO owner_telegram_alert_acceptance"):
            key = params[0]
            if key in self.rows:
                self.insert_result = None
            else:
                self.rows[key] = ("reserved", None)
                self.insert_result = (key,)
        elif sql.startswith("UPDATE owner_telegram_alert_acceptance"):
            state, mid, key = params
            self.rows[key] = (state, mid)

    def fetchone(self):
        if self.sql.startswith("INSERT INTO"):
            return self.insert_result
        if "max(recorded_at)" in self.sql:
            return (self.scan,)
        if "max(created_at)" in self.sql:
            return (self.gmail,)
        if "greatest(" in self.sql:
            return (self.source,)
        raise AssertionError("Unexpected private read")

    def close(self):
        pass


class OwnerFreshnessAlertTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)
        self.env = {"GITHUB_RUN_ID": "44828342221",
                    "TELEGRAM_BOT_TOKEN": "fixture",
                    "TELEGRAM_CHAT_ID": "123"}
        self.sent = []
        def messenger(token, method, payload):
            self.assertEqual((token, method), ("fixture", "sendMessage"))
            self.sent.append(payload)
            return {"message_id": 701}
        self.messenger = messenger

    def test_incident_is_deduplicated_by_local_day_and_module(self):
        db = FakeDatabase(self.now)
        self.assertTrue(send_once(self.env, db, self.messenger, lambda _: None,
                                  self.now))
        self.assertFalse(send_once(self.env, db, self.messenger, lambda _: None,
                                   self.now))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(db.rows), 1)
        self.assertEqual(next(iter(db.rows.values())), ("api_accepted", 701))
        text = self.sent[0]["text"]
        self.assertIn("Tarama: gecikmiş", text)
        self.assertIn("Gmail: gecikmiş", text)
        self.assertIn("44828342221", text)
        self.assertNotIn("fixture", text)

    def test_fresh_state_does_not_send_a_success_notification(self):
        db = FakeDatabase(self.now, fresh=True)
        self.assertFalse(send_once(self.env, db, self.messenger, lambda _: None,
                                   self.now))
        self.assertEqual(self.sent, [])

    def test_bad_telegram_credentials_never_access_private_database(self):
        env = dict(self.env, TELEGRAM_CHAT_ID="not-a-chat")
        with self.assertRaisesRegex(RuntimeError, "secrets"):
            send_once(env, FakeDatabase(self.now), self.messenger,
                      lambda _: None, self.now)
        self.assertEqual(self.sent, [])

    def test_neon_outage_is_reported_with_safe_owner_only_fallback(self):
        with patch("leadhunter.ops_freshness_alert.connect_private_database",
                   side_effect=RuntimeError("connection token@example.invalid")):
            self.assertTrue(send_once(self.env, messenger=self.messenger,
                                      output=lambda _: None, now=self.now))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Neon bağlantısı", self.sent[0]["text"])
        self.assertNotIn("token@example.invalid", self.sent[0]["text"])


if __name__ == "__main__":
    unittest.main()
