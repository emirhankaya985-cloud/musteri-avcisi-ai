"""Synthetic read-only freshness checks; no Neon customer rows copied."""
import unittest
from datetime import datetime, timedelta, timezone
from leadhunter.ops_freshness import classify, run


class Cursor:
    def __init__(self, timestamps):
        self.values = iter(timestamps)
    def execute(self, sql):
        assert sql in ("SELECT max(created_at) FROM owner_scan_run_metrics",
                       "SELECT max(created_at) FROM owner_mail_watch_runs")
    def fetchone(self):
        return (next(self.values),)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class Conn:
    def __init__(self, values):
        self.values=values
    def cursor(self):
        return Cursor(self.values)


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,7,12,0,tzinfo=timezone.utc)

    def test_recent_both_are_healthy(self):
        self.assertEqual(classify(self.now-timedelta(minutes=95),
                                  self.now-timedelta(minutes=135),self.now),
                         {"scan":"fresh","gmail":"fresh"})

    def test_missing_and_delayed_slots_are_distinguished(self):
        self.assertEqual(classify(None,self.now-timedelta(minutes=181),self.now),
                         {"scan":"unverified","gmail":"stale"})
        self.assertEqual(classify(self.now+timedelta(minutes=1),self.now,self.now)["scan"],
                         "unverified")

    def test_aggregate_only_no_retries_or_smtp(self):
        messages=[]
        state=run(env={},connection=Conn([self.now,self.now]),
                  output=messages.append,now=self.now)
        self.assertEqual(state,{"scan":"fresh","gmail":"fresh"})
        self.assertEqual(len(messages),1)
        self.assertIn("new_smtp_sent=0",messages[0])
        self.assertNotIn("@",messages[0])

    def test_stale_fails_loudly_but_does_not_dispatch_scan(self):
        logs=[]
        with self.assertRaisesRegex(RuntimeError,"PARTIAL"):
            run(env={},connection=Conn([self.now-timedelta(days=2),
                                       self.now-timedelta(days=2)]),
                output=logs.append,now=self.now)
        self.assertIn("stale",logs[0])


if __name__ == "__main__":
    unittest.main()
