import unittest
from unittest.mock import MagicMock

from leadhunter.smtp_auth_check import check


class SMTPAuthCheckTests(unittest.TestCase):
    def test_authenticates_but_never_sends_message(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        result = check({"GMAIL_SENDER_ADDRESS": "sender@gmail.com",
                        "GMAIL_APP_PASSWORD": "abcdefghijklmnop"},
                       smtp_factory=lambda *args, **kwargs: smtp)
        smtp.ehlo.assert_called_once_with()
        smtp.login.assert_called_once_with("sender@gmail.com", "abcdefghijklmnop")
        smtp.send_message.assert_not_called()
        smtp.sendmail.assert_not_called()
        self.assertEqual(result, {"authenticated": True, "message_sent": False})

    def test_auth_failure_is_redacted(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.login.side_effect = RuntimeError("secret recipient@example.com")
        with self.assertRaisesRegex(RuntimeError, "details redacted") as raised:
            check({"GMAIL_SENDER_ADDRESS": "sender@gmail.com",
                   "GMAIL_APP_PASSWORD": "abcdefghijklmnop"},
                  smtp_factory=lambda *args, **kwargs: smtp)
        self.assertNotIn("recipient@example.com", str(raised.exception))
        smtp.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
