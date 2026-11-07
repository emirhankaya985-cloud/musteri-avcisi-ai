"""Read-only outcome audit: never claim SMTP acceptance is delivery."""
import unittest
from leadhunter.mail_outcome import summarize_counts, run, audit_failure_reasons


class DummyCursor:
    def execute(self, sql):
        assert 'FROM owner_leads' in sql and (
            'SELECT count' in sql or 'GROUP BY 1' in sql)
    def fetchone(self):
        return (15, 4, 0, 0)
    def fetchall(self):
        return [
            ("dns_nxdomain", 1), ("mailbox_missing", 1),
            ("relay_denied", 1), ("connection_refused", 1),
        ]
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


class DummyConnection:
    def cursor(self):
        return DummyCursor()


class OutcomeTests(unittest.TestCase):
    def test_all_successful_smtp_accepts_remain_unverified_delivery(self):
        result = summarize_counts(15, 4, 0, 0)
        self.assertEqual(result['unverified_delivery'], 11)
        self.assertIsNone(result['verified_delivery'])
        self.assertTrue(result['paused'])

    def test_invalid_counts_fail_closed(self):
        for counts in ((5, 6, 0, 0), (-1, 0, 0, 0), (2, 1, 3, 0), (1, 0, 0, 'x')):
            with self.subTest(counts=counts):
                with self.assertRaises(ValueError):
                    summarize_counts(*counts)

    def test_failure_reasons_strictly_match_failed_count(self):
        self.assertEqual(
            sum(audit_failure_reasons(DummyConnection(), 4).values()),4)
        with self.assertRaisesRegex(RuntimeError, "inconsistent"):
            audit_failure_reasons(DummyConnection(), 3)

    def test_reason_values_are_fixed_safe_labels(self):
        class OtherCursor(DummyCursor):
            def fetchall(self):
                return [("secret-unknown-raw-error", 4)]
        class OtherConn:
            def cursor(self):
                return OtherCursor()
        result = audit_failure_reasons(OtherConn(),4)
        self.assertEqual(result["unknown"],4)
        self.assertNotIn("secret-unknown-raw-error",repr(result))

    def test_private_aggregate_only_no_smtp(self):
        messages = []
        state = run(env={}, connection=DummyConnection(), output=messages.append)
        self.assertEqual(state['failed'], 4)
        self.assertIn('delivery_confirmed=unverified', messages[0])
        self.assertIn('new_business_smtp_sent=0', messages[0])
        self.assertNotIn('@', messages[0])
        self.assertIn("dns_nxdomain=1", messages[1])
        self.assertIn("business_mail_sent=0", messages[1])


if __name__ == '__main__':
    unittest.main()
