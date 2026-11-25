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
        failed = {**row, "osm_id":"node/124", "business_name":"Another Cafe",
                  "auto_mail_state":"accepted", "delivery_state":"failed",
                  "delivery_error":"mailbox_missing"}
        province_rows = [{"code": f"{i:02d}", "province": f"İl {i}",
                          "initial_phase_target": i < 10, "status": "pending",
                          "completed_items": 0, "total_items": 0,
                          "coverage_percent": 0, "source_url": None,
                          "source_sha256": None, "source_data_at": None,
                          "updated_at": "2026-11-24T00:00:00Z"} for i in range(81)]
        binary = build_workbook([row, failed], {
            "total": 2, "new": 1, "accepted": 0, "failed": 0,
            "replies": 0, "eligible": 0, "accepted_today": 0,
        }, "2026-11-24", send_enabled=True, province_coverage=province_rows)
        self.assertTrue(binary.startswith(b"PK\x03\x04"))
        workbook = load_workbook(io.BytesIO(binary), data_only=False)
        sheet = workbook["Tüm işletmeler"]
        self.assertEqual(sheet["A9"].value, "Örnek Kafe")
        self.assertEqual(sheet["D9"].value, "biz@example.invalid")
        self.assertEqual(sheet["F9"].value, "Araştırılmadı")
        self.assertIn("Atanmadı", sheet["G9"].value)
        self.assertEqual(sheet["I9"].value, 75)
        self.assertIn("Gmail API kullanılmıyor", sheet["L9"].value)
        self.assertEqual(sheet["R9"].value, "Kayıt yok")
        self.assertEqual(sheet["Q9"].value, "https://www.openstreetmap.org/node/123")
        self.assertIn("İYS/onay", workbook["Gönderime uygun olmayanlar"]["Y4"].value)
        self.assertEqual(workbook["Başarısız gönderimler"]["A4"].value, "Another Cafe")
        self.assertEqual(workbook["Başarısız gönderimler"]["A4"].value, "Another Cafe")
        self.assertIn("gelen kutusu teslimi değildir", sheet["A5"].value)
        self.assertEqual(len(workbook.sheetnames), 12)
        self.assertEqual(workbook["Şehir kapsamı"].max_row, 84)
        self.assertEqual(workbook["Şehir kapsamı"]["D4"].value, "pending")
        self.assertIn("WhatsApp otomasyonu adayları", workbook.sheetnames)
        self.assertIn("Gönderime uygun olmayanlar", workbook.sheetnames)
        self.assertIn("Şehir kapsamı", workbook.sheetnames)
        self.assertIn("Sektör dağılımı", workbook.sheetnames)
        self.assertIn("Ticari puanlama", workbook.sheetnames)
        self.assertIn("Mükerrer adayları", workbook.sheetnames)
        self.assertIn("yokluk sayılmaz", workbook["WhatsApp otomasyonu adayları"]["A1"].value)

    def test_external_formula_like_strings_reload_as_literal_text(self):
        malicious = [" =1+1", "\t+cmd|' /C calc'!A0", "\n@SUM(1,1)", "-1"]
        rows = [{"osm_id": f"node/{i}", "business_name": value, "sector": "Cafe",
                 "city": "İstanbul", "email": value, "website": value,
                 "delivery_error": value, "qualification": {}}
                for i, value in enumerate(malicious, 10)]
        workbook = load_workbook(io.BytesIO(build_workbook(
            rows, {"total": len(rows)}, "2026-11-24")), data_only=False)
        sheet = workbook["Tüm işletmeler"]
        for index, value in enumerate(malicious, 9):
            for col in (1, 4, 15):
                cell = sheet.cell(index, col)
                self.assertEqual(cell.value, value)
                self.assertEqual(cell.data_type, "s")
        self.assertEqual(len(workbook.sheetnames), 12)

    def test_duplicate_rows_serialize_arrays_and_timestamps_as_safe_xlsx_cells(self):
        from datetime import datetime, timezone
        pair = ("node/1", "node/2", "needs_review", 72,
                "same_name, same_first_party_domain",
                datetime(2026, 11, 24, tzinfo=timezone.utc).isoformat(),
                datetime(2026, 11, 25, tzinfo=timezone.utc).isoformat(),
                '{"name":"=Injected","category":"Cafe"}',
                '{"name":"Branch","category":"Cafe"}')
        workbook = load_workbook(io.BytesIO(build_workbook(
            [], {"total": 0}, "2026-11-25", duplicate_pairs=[pair])), data_only=False)
        sheet = workbook["Mükerrer adayları"]
        self.assertEqual(sheet.max_column, 9)
        self.assertEqual(sheet["D4"].value, 72)
        self.assertEqual(sheet["E4"].value, "same_name, same_first_party_domain")
        self.assertEqual(sheet["F4"].value, "2026-11-24T00:00:00+00:00")
        self.assertEqual(sheet["H4"].data_type, "s")
        self.assertEqual(len(workbook.sheetnames), 12)

    def test_duplicate_query_normalizes_postgres_arrays_datetimes_and_records(self):
        from datetime import datetime, timezone
        from leadhunter.crm_export import fetch_duplicate_pairs

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query):
                self.query = query
            def fetchall(self):
                return [("node/1", "node/2", "needs_review", 72,
                         ["same_name", "same_first_party_domain"],
                         datetime(2026, 11, 24, tzinfo=timezone.utc),
                         datetime(2026, 11, 25, tzinfo=timezone.utc),
                         "=Cafe", "Cafe", "Address", None, "https://a.example",
                         "Cafe Branch", "Cafe", "Address 2", "555", "https://b.example")]

        class Connection:
            def cursor(self):
                return Cursor()

        pair, = fetch_duplicate_pairs(Connection())
        self.assertEqual(pair[3:7], (72, "same_name, same_first_party_domain",
                                     "2026-11-24T00:00:00+00:00",
                                     "2026-11-25T00:00:00+00:00"))
        self.assertIn('"name":"=Cafe"', pair[7])

    def test_illegal_xml_controls_are_removed_before_xlsx_write(self):
        row = {"osm_id": "node/88", "business_name": "Cafe\x01Name", "sector": "Cafe",
               "email": "safe\x0b@example.invalid", "qualification": {}}
        workbook = load_workbook(io.BytesIO(build_workbook(
            [row], {"total": 1}, "2026-11-25")), data_only=False)
        sheet = workbook["Tüm işletmeler"]
        self.assertEqual(sheet["A9"].value, "CafeName")
        self.assertEqual(sheet["D9"].value, "safe@example.invalid")

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
