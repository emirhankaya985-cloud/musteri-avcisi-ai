"""Owner-only hourly status is bounded, retry-safe and contains no PII."""
import unittest
from leadhunter.hourly_summary import compose, eligible_run


class HourlySummaryTests(unittest.TestCase):
    def setUp(self):
        self.stats = dict(fetched=73, eligible=70, rejected=3,
                          duplicates=0, already_seen=60, new=10)

    def test_no_schedule_run_id_means_no_send(self):
        self.assertFalse(eligible_run({'OWNER_HOURLY_SUMMARY': 'true'}))
        self.assertFalse(eligible_run({'OWNER_HOURLY_SUMMARY': 'false',
                                       'GITHUB_RUN_ID': '42358369495'}))

    def test_retry_attempt_never_sends_same_hour_summary(self):
        env = dict(OWNER_HOURLY_SUMMARY='true', GITHUB_RUN_ID='42358369495')
        self.assertTrue(eligible_run(env))
        env['GITHUB_RUN_ATTEMPT'] = '2'
        self.assertFalse(eligible_run(env))

    def test_no_private_data_and_no_smtp_claim(self):
        msg = compose(self.stats, 4, 'pilot_2_of_4')
        self.assertIn('Ham kayıt: 73', msg)
        self.assertIn('Sahibe yeni fırsat bildirimi: 4', msg)
        self.assertIn('otomatik SMTP gönderimi: 0', msg)
        self.assertNotIn('@', msg)
        self.assertNotIn('1234567', msg)

    def test_invalid_counters_do_not_form_report(self):
        with self.assertRaises(ValueError):
            compose({**self.stats, 'new': -1}, 0, 'default')


if __name__ == '__main__':
    unittest.main()
