"""Mock-only Gmail tests; never touch Google's network or private accounts."""
import smtplib
import unittest

from leadhunter.gmail_selftest import (
    APPROVAL, PORT, SERVER, make_self_test_message, prepare_offer_draft,
    send_to_self, sender_credentials,
)

OWNER = "test.owner@gmail.com"
SECRETS = {"GMAIL_SENDER_ADDRESS": OWNER, "GMAIL_APP_PASSWORD": "abcdefghijklmnop"}
APPROVED = {**SECRETS, "GMAIL_SELF_TEST_APPROVED": APPROVAL}


class FakeSMTP:
    events = []

    def __init__(self, host, port, *, context, timeout):
        self.events.append(("connect", host, port, bool(context), timeout))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def login(self, address, password):
        self.events.append(("login", address, password))

    def send_message(self, message, *, from_addr, to_addrs):
        self.events.append(("send", from_addr, list(to_addrs), message))
        return {}


class GmailSelfTest(unittest.TestCase):
    def setUp(self):
        FakeSMTP.events = []

    def test_deny_unapproved_even_with_secrets(self):
        with self.assertRaisesRegex(RuntimeError, "approval required"):
            send_to_self(SECRETS, FakeSMTP, lambda _: None)
        self.assertEqual(FakeSMTP.events, [])

    def test_no_email_when_secrets_missing(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            send_to_self({"GMAIL_SELF_TEST_APPROVED": APPROVAL},
                         FakeSMTP, lambda _: None)
        self.assertEqual(FakeSMTP.events, [])

    def test_sender_only_valid_free_gmail_address(self):
        for bad in ("other@outlook.com", "mail@example.com",
                    "foo@gmail.com\nBcc:bad@example.com", "bad@gmail.com,malicious@other.com"):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                sender_credentials({**SECRETS, "GMAIL_SENDER_ADDRESS": bad})

    def test_app_password_not_regular_account_password(self):
        for bad in ("", "short", "contains punctuation!", "a" * 24):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                sender_credentials({**SECRETS, "GMAIL_APP_PASSWORD": bad})

    def test_google_app_password_whitespace_is_allowed(self):
        address, secret = sender_credentials({**SECRETS, "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop"})
        self.assertEqual(address, OWNER)
        self.assertEqual(secret, "abcdefghijklmnop")

    def test_self_test_only_to_configured_sender(self):
        report = []
        env = {**APPROVED, "EXTERNAL_RECIPIENT": "client@example.com"}
        self.assertTrue(send_to_self(env, FakeSMTP, report.append))
        self.assertEqual(FakeSMTP.events[0], ("connect", SERVER, PORT, True, 30))
        self.assertEqual(FakeSMTP.events[1], ("login", OWNER, "abcdefghijklmnop"))
        send = FakeSMTP.events[2]
        self.assertEqual(send[0], "send")
        self.assertEqual(send[1], OWNER)
        self.assertEqual(send[2], [OWNER])
        self.assertEqual(send[3]["To"], OWNER)
        self.assertNotIn("client@example.com", send[3].as_string())
        self.assertEqual(len(report), 1)
        self.assertNotIn(OWNER, report[0])

    def test_utf8_self_test_mime(self):
        msg = make_self_test_message(OWNER)
        self.assertIn("Gmail bağlantı testi", str(msg["Subject"]))
        self.assertIn("Gerçek işletmelere", msg.get_content())
        self.assertEqual(msg["To"], OWNER)

    def test_failed_smtp_redacts_password_and_does_not_claim_success(self):
        class BrokenSMTP(FakeSMTP):
            def login(self, *_):
                raise smtplib.SMTPAuthenticationError(
                    535, b"abcdefghijklmnop AUTHENTICATION FAILED")
        reports = []
        with self.assertRaisesRegex(RuntimeError, "sensitive details redacted") as caught:
            send_to_self(APPROVED, BrokenSMTP, reports.append)
        self.assertNotIn("abcdefghijklmnop", str(caught.exception))
        self.assertEqual(reports, [])

    def test_refused_recipient_not_success(self):
        class RefusingSMTP(FakeSMTP):
            def send_message(self, message, *, from_addr, to_addrs):
                return {OWNER: (550, b"refused")}
        with self.assertRaisesRegex(RuntimeError, "self-test failed"):
            send_to_self(APPROVED, RefusingSMTP, lambda _: None)

    def test_personalized_draft_never_attempts_send(self):
        draft = prepare_offer_draft({
            "name": "Örnek Salon", "category": "Kuaför/berber", "website": "",
        })
        self.assertIn("Örnek Salon", draft["subject"])
        self.assertIn("premium bir web sitesi", draft["body"])
        self.assertEqual(FakeSMTP.events, [])

    def test_crlf_business_name_cannot_add_email_headers(self):
        draft = prepare_offer_draft({"name": "Firma\nBcc:someone@example.com",
                                     "category": "Oto yıkama", "website": ""})
        self.assertNotIn("\nBcc:", draft["subject"])
        self.assertNotIn("\r", draft["subject"])

    def test_missing_business_rejected(self):
        for lead in ({}, {"name": " "}):
            with self.assertRaises(ValueError):
                prepare_offer_draft(lead)


if __name__ == "__main__":
    unittest.main()
