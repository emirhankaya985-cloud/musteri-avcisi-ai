"""Read-only outcome audit: never claim SMTP acceptance is delivery."""
import unittest
from leadhunter.mail_outcome import summarize_counts, run


class DummyCursor:
    def execute(self, sql):
        assert 'SELECT count' in sql and 'FROM owner_leads' in sql
    def fetchone(self):
        return (15, 4, 0, 0)
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

    def test_private_aggregate_only_no_smtp(self):
        messages = []
        state = run(env={}, connection=DummyConnection(), output=messages.append)
        self.assertEqual(state['failed'], 4)
        self.assertIn('delivery_confirmed=unverified', messages[0])
        self.assertIn('new_business_smtp_sent=0', messages[0])
        self.assertNotIn('@', messages[0])


if __name__ == '__main__':
    unittest.main()
