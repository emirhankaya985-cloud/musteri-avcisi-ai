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

    def test_machine_readable_dsn_code_classification(self):
        from leadhunter.mail_watch import dsn_details
        from email import policy
        from email.parser import BytesParser
        def dsn(status, diagnostic, action="failed"):
            raw = (
                "From: mailer-daemon@googlemail.com\r\n"
                "Subject: Delivery Status Notification (Failure)\r\n"
                "MIME-Version: 1.0\r\n"
                'Content-Type: multipart/report; boundary="bound"; report-type=delivery-status\r\n'
                "\r\n--bound\r\nContent-Type: text/plain\r\n\r\nDelivery failed\r\n"
                "--bound\r\nContent-Type: message/delivery-status\r\n\r\n"
                "Reporting-MTA: dns; gmail.example.invalid\r\n\r\n"
                "Final-Recipient: rfc822; owner@example.invalid\r\n"
                f"Action: {action}\r\nStatus: {status}\r\n"
                f"Diagnostic-Code: smtp; {diagnostic}\r\n"
                "--bound--\r\n"
            )
            return BytesParser(policy=policy.default).parsebytes(raw.encode())
        permanent = dsn("5.1.1", "550 5.1.1 mailbox unavailable")
        temporary = dsn("4.2.0", "450 4.2.0 temporarily unavailable", "delayed")
        self.assertEqual(dsn_details(permanent)["smtp_code"], "550")
        self.assertEqual(dsn_details(permanent)["failure_kind"], "permanent")
        self.assertEqual(dsn_details(temporary)["failure_kind"], "temporary")
        self.assertEqual(dsn_details(temporary)["enhanced_status"], "4.2.0")
        # No mailbox address, SMTP diagnostics or personal text in metadata.
        self.assertNotIn("@", str(dsn_details(permanent)))
        self.assertNotIn("mailbox unavailable", str(dsn_details(permanent)))

    def test_realistic_gmail_plaintext_bounces_have_safe_reasons(self):
        cases = [
            ("Failure", "550 No Such User Here", "550", "mailbox_missing", "permanent"),
            ("Failure", "554 5.7.1 : Relay access denied", "554", "relay_denied", "permanent"),
            ("Failure", "DNS type mx lookup responded with code NXDOMAIN", None,
             "dns_nxdomain", "permanent"),
            ("Delay", "Recipient server: connect error (111): Connection refused",
             None, "connection_refused", "temporary"),
        ]
        for subject, diagnostic, code, reason, kind in cases:
            with self.subTest(reason=reason):
                msg = EmailMessage()
                msg["From"] = "mailer-daemon@googlemail.com"
                msg["Subject"] = f"Delivery Status Notification ({subject})"
                msg.set_content("Delivery problem for owner@example.invalid\n" + diagnostic)
                value = bounce_feedback(msg.as_bytes())
                self.assertEqual(value[2].get("smtp_code"), code)
                self.assertEqual(value[2]["reason"], reason)
                self.assertEqual(value[2]["failure_kind"], kind)
                self.assertNotIn("@", str(value[2]))
                self.assertNotIn("owner@example.invalid", str(value[2]))

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

    def test_mixed_bounce_and_reply_shapes_do_not_confuse_matching(self):
        from leadhunter.mail_watch import matching_reply
        notices = [
            ("undelivered to owner@example.invalid", "failed",
             {"smtp_code":"550", "failure_kind":"permanent"}),
            ("owner@example.invalid", "reply:<abcdefghijklmnopqrstuv@gmail.com>"),
        ]
        self.assertTrue(matching_reply(notices, "owner@example.invalid",
                                       "abcdefghijklmnopqrstuv"))
        self.assertFalse(matching_reply(notices, "other@example.invalid",
                                        "abcdefghijklmnopqrstuv"))
        self.assertFalse(matching_reply(notices[:1], "owner@example.invalid",
                                        "abcdefghijklmnopqrstuv"))

    def test_missing_credentials_never_attempts_connection(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            read_delivery_messages({}, imap_factory=lambda *a,**kw:
                                   self.fail("Network must not be reached"))


if __name__ == "__main__":
    unittest.main()
