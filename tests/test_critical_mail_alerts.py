"""Critical-only owner Gmail alerts never send routine temporary delays."""
import unittest
from leadhunter.mail_watch import select_alert_events, deliver_pending


class CriticalMailAlertTests(unittest.TestCase):
    def test_only_actionable_failures_and_replies(self):
        events=[("leadA","delayed"),("leadB","failed"),
                ("leadC","reply"),("leadD","delayed")]
        self.assertEqual(select_alert_events(events,True),
                         [("leadB","failed"),("leadC","reply")])
        self.assertEqual(select_alert_events(events,False),events)

    def test_delay_only_does_not_call_telegram_or_db(self):
        class NeverConnect:
            def __getattr__(self,field):
                raise AssertionError("DB access forbidden for filtered delays")
        self.assertEqual(deliver_pending(
            NeverConnect(),[("leadA","delayed")],
            {"MAIL_CRITICAL_ALERTS_ONLY":"true"},
            opener=lambda *a,**k: self.fail("unexpected Telegram send")),0)


if __name__=="__main__":
    unittest.main()
