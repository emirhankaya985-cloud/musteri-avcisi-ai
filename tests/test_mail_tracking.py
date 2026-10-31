"""No live SMTP, no real customer data or DNS access in these tests."""
import io
import json
import unittest

from leadhunter.mail_tracking import already_contacted, assess_contact, identity_keys, mx_status
from leadhunter.review_messages import compact_telegram
from leadhunter.telegram_buttons import process_owner_command


class MailHistorySafetyTests(unittest.TestCase):
    def test_same_recipient_normalized_and_uncertain_are_never_recontacted(self):
        lead = {"id": "node/17", "name": "Other", "email": " INFO@SHOP.INVALID "}
        for status in ("sending", "accepted", "uncertain"):
            history = {"name": "Shop", "_auto_mail": {
                "state": status, "recipient": "info@shop.invalid"}}
            self.assertTrue(already_contacted(lead, history))
        self.assertFalse(already_contacted(lead, {
            "name": "Shop", "_auto_mail": {
                "state": "skipped", "recipient": "info@shop.invalid"}}))

    def test_same_real_business_different_email_is_suppressed(self):
        new = {"name": "SİNAN kuaför", "address": "Örnek Mahallesi No 12",
               "website": "https://sinan.example.invalid", "email": "new@else.invalid"}
        old = {"name": "Başka adı", "address": "Başka adres",
               "website": "https://sinan.example.invalid/contact", "_auto_mail": {
                   "state": "accepted", "recipient": "old@example.invalid"}}
        self.assertTrue(already_contacted(new, old))
        other = {"name": "Sinan kuaför", "address": "Başka şehir No 7",
                 "website": "https://unrelated.invalid", "_auto_mail": {
                     "state": "accepted", "recipient": "old@example.invalid"}}
        self.assertFalse(already_contacted(new, other))
        social_a = {"name": "A", "website": "https://facebook.com/one"}
        social_b = {"name": "B", "website": "https://facebook.com/two"}
        self.assertFalse(identity_keys(social_a) & identity_keys(social_b))

    def test_real_mx_lookup_not_mailbox_verification(self):
        class MX:
            exchange = "mx.example.invalid."
        lead = {"name": "Shop", "id": "node/1", "email": "info@shop.invalid"}
        result = assess_contact(lead, resolver=lambda *a, **kw: [MX()])
        self.assertEqual(result["email_check"], "mx_present")
        self.assertEqual(result["email_source"], "OSM business contact tag")
        self.assertIn("posta kutusu", compact_telegram({**result, "score": 75}).lower())
        self.assertEqual(mx_status("shop.invalid", resolver=lambda *a, **kw: []), "no_mx")
        self.assertEqual(mx_status("shop.invalid", resolver=lambda *a, **kw: (_ for _ in ()).throw(
            TimeoutError("unknown"))), "unchecked")

    def test_invalid_and_missing_address_never_guessed(self):
        self.assertEqual(assess_contact({"name": "Unknown"})["email_check"], "not_found")
        self.assertEqual(assess_contact({"name": "Unknown", "email": "bad"})["email_check"], "invalid")

    def test_owner_private_eposta_report_contains_totals_no_recipients(self):
        class FakePrivate:
            def mail_summary(self):
                return {"total": 35, "accepted": 15, "uncertain": 0,
                        "skipped": 20, "duplicate": 0}
        calls = []
        def opener(req, timeout=None):
            calls.append(json.loads(req.data))
            return io.BytesIO(b'{"ok":true,"result":{"message_id":35}}')
        data={"message":{"chat":{"id":123,"type":"private"},
                         "from":{"id":123,"is_bot":False}, "text":"/eposta"}}
        self.assertTrue(process_owner_command(data, "fixture", "123", {}, opener, FakePrivate()))
        body=calls[0]["text"]
        self.assertIn("15", body)
        self.assertIn("20", body)
        self.assertIn("SMTP kabulü teslim kanıtı değildir", body)
        self.assertNotIn("@", body)
        data["message"]["from"]["id"]=456
        self.assertFalse(process_owner_command(data, "fixture", "123", {}, opener, FakePrivate()))
        self.assertEqual(len(calls),1)


if __name__ == "__main__":
    unittest.main()
