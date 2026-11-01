"""Daily owner-only reporting: no network, SMTP or sensitive user data."""
import unittest
from leadhunter.daily_status import compose


class DailyStatusTests(unittest.TestCase):
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
