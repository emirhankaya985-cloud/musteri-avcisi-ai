"""Read-only Gmail DSN parsing. Tests use fake IMAP, no credentials or mail sends."""
from email.message import EmailMessage
import unittest

from leadhunter.mail_watch import bounce_feedback, reply_feedback, read_delivery_messages


def message(sender="Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
            subject="Delivery Status Notification (Failure)",
            recipient="owner@example.invalid"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "system@example.invalid"
    msg["Subject"] = subject
    msg.set_content("Delivery could not complete for: " + recipient)
    return msg.as_bytes()


class MailWatchSafetyTests(unittest.TestCase):
    def test_only_trusted_mailer_and_failure_or_delay_subject(self):
        self.assertEqual(
            bounce_feedback(message())[1], "failed")
        self.assertEqual(
            bounce_feedback(message(subject="Delivery Status Notification (Delay)"))[1],
            "delayed")
        self.assertIsNone(bounce_feedback(message(sender="spam@example.invalid")))
        self.assertIsNone(bounce_feedback(message(subject="Special Offer")))
        self.assertIsNone(bounce_feedback(b"X" * 600_000))

    def test_gmail_imap_is_readonly_and_smtp_never_invoked(self):
        calls = []
        class FakeIMAP:
            def __init__(self, host, port, ssl_context=None, timeout=None):
                calls.append(("connect", host, port))
            def login(self, address, password):
                calls.append(("login",))
                return "OK", []
            def select(self, folder, readonly=False):
                calls.append(("select", folder, readonly))
                return "OK", [b"1"]
            def uid(self, op, *args):
                calls.append(("uid", op))
                if op == "SEARCH":
                    return "OK", [b"123"]
                if op == "FETCH":
                    return "OK", [(b"1 (RFC822)", message()), b")"]
                raise AssertionError("unexpected IMAP operation")
            def logout(self):
                calls.append(("logout",))
        env = {"GMAIL_SENDER_ADDRESS":"synthetic@example.invalid", "GMAIL_APP_PASSWORD":"fixture"}
        result = read_delivery_messages(env, imap_factory=FakeIMAP)
        self.assertEqual(result[0][1], "failed")
        self.assertEqual(len(result),1)
        self.assertIn(("select","INBOX",True), calls)
        self.assertEqual([c[1] for c in calls if c[0]=="uid"],["SEARCH","FETCH"])
        self.assertNotIn("STORE",str(calls))
        self.assertNotIn("SMTP",str(calls))

    def test_replies_require_a_thread_reference_and_not_a_bounce(self):
        msg = EmailMessage()
        msg["From"] = "owner-mailbox@example.invalid"
        msg["To"] = "sender@example.invalid"
        msg["Subject"] = "Re: Previous outreach"
        msg["In-Reply-To"] = "<bbbbbbbbbbbbbbbbbbbbbbbb@gmail.com>"
        msg.set_content("Reply body is private and must never be stored.")
        value = reply_feedback(msg.as_bytes())
        self.assertEqual(value[0], "owner-mailbox@example.invalid")
        self.assertIn("bbbbbbbbbbbbbbbbbbbbbbbb", value[1])
        self.assertNotIn("Reply body is private", str(value))
        del msg["In-Reply-To"]
        self.assertIsNone(reply_feedback(msg.as_bytes()))

    def test_missing_credentials_never_attempts_connection(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            read_delivery_messages({}, imap_factory=lambda *a,**kw:
                                   self.fail("Network must not be reached"))


if __name__ == "__main__":
    unittest.main()
