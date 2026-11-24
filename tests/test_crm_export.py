"""Private CRM workbook schema and owner-DM delivery; all data is synthetic."""
import io
import json
import unittest
from openpyxl import load_workbook

from leadhunter.crm_export import build_workbook, send_document


class CrmExportTests(unittest.TestCase):
    def test_xlsx_preserves_unknowns_and_does_not_invent_message_ids(self):
        row = {
            "osm_id": "node/123", "status": "review", "business_name": "Örnek Kafe",
            "sector": "Cafe", "website": "", "email": "biz@example.invalid",
            "research_score": "75", "email_preflight": "mx_present",
            "auto_mail_state": "draft", "last_verified_at": None,
        }
        binary = build_workbook([row], {
            "total": 1, "new": 1, "accepted": 0, "failed": 0,
            "replies": 0, "eligible": 0, "accepted_today": 0,
        }, "2026-11-24", send_enabled=True)
        self.assertTrue(binary.startswith(b"PK\x03\x04"))
        workbook = load_workbook(io.BytesIO(binary), data_only=True)
        sheet = workbook["Tüm işletmeler"]
        self.assertEqual(sheet["A9"].value, "Örnek Kafe")
        self.assertEqual(sheet["D9"].value, "biz@example.invalid")
        self.assertEqual(sheet["F9"].value, "Araştırılmadı")
        self.assertIn("Atanmadı", sheet["G9"].value)
        self.assertEqual(sheet["I9"].value, 75)
        self.assertIn("Gmail API kullanılmıyor", sheet["L9"].value)
        self.assertEqual(sheet["R9"].value, "Kayıt yok")
        self.assertEqual(sheet["Q9"].value, "https://www.openstreetmap.org/node/123")
        self.assertIn("gelen kutusu teslimi değildir", sheet["A5"].value)
        self.assertEqual(len(workbook.sheetnames), 12)
        self.assertIn("WhatsApp otomasyonu adayları", workbook.sheetnames)
        self.assertIn("Gönderime uygun olmayanlar", workbook.sheetnames)
        self.assertIn("doğrulanmadığından", workbook["WhatsApp otomasyonu adayları"]["A1"].value)

    def test_document_upload_requires_positive_private_chat_and_matching_receipt(self):
        reply = {"ok": True, "result": {"message_id": 77, "chat": {"id": 456}}}
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(json.dumps(reply).encode())

        message_id = send_document("token", "456", b"PK\x03\x04synthetic",
                                   "private.xlsx", opener=opener)
        self.assertEqual(message_id, 77)
        self.assertEqual(len(requests), 1)
        self.assertIn(b"name=\"chat_id\"", requests[0][0].data)
        self.assertIn(b"private.xlsx", requests[0][0].data)
        self.assertIn(b"PK\x03\x04synthetic", requests[0][0].data)

        with self.assertRaises(RuntimeError):
            send_document("token", "-100123", b"PK\x03\x04synthetic",
                          "private.xlsx", opener=opener)
        self.assertEqual(len(requests), 1)

    def test_document_upload_fails_closed_when_telegram_receipt_targets_other_chat(self):
        reply = {"ok": True, "result": {"message_id": 77, "chat": {"id": 999}}}
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            send_document("token", "456", b"PK\x03\x04synthetic", "private.xlsx",
                          opener=lambda request, timeout: io.BytesIO(json.dumps(reply).encode()))


if __name__ == "__main__":
    unittest.main()
