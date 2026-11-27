import json
import unittest
from datetime import datetime, timedelta, timezone

from leadhunter.import_iys_evidence import parse_document, import_records


class IysImportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)
        self.row = {
            "email": "contact@example.invalid",
            "merchant_evidence_ref": "official-registry-reference-123",
            "iys_evidence_ref": "iys-query-reference-12345",
            "checked_at": (self.now - timedelta(hours=1)).isoformat(),
            "merchant_verified": True,
            "iys_registered": True,
            "iys_rejected": False,
        }

    def parse(self, rows=None):
        return parse_document(json.dumps({"schema": "iys-business-evidence-v1",
                                          "records": rows or [self.row]}), self.now)

    def test_parses_fresh_exact_iys_evidence(self):
        record = self.parse()[0]
        self.assertEqual(record["recipient"], "contact@example.invalid")
        self.assertEqual(record["route"], "iys_verified_business")

    def test_fails_closed_on_missing_flags_stale_evidence_duplicates_and_bad_schema(self):
        for changes in (
            {"iys_registered": False}, {"merchant_verified": False},
            {"iys_rejected": True}, {"checked_at": "2020-01-01T00:00:00Z"},
            {"checked_at": "2026-11-27T12:00:00"},
            {"iys_evidence_ref": ""},
        ):
            row = {**self.row, **changes}
            with self.subTest(changes=changes):
                if changes.get("iys_rejected") or changes.get("iys_registered") is False or changes.get("merchant_verified") is False:
                    parsed = self.parse([row])[0]
                    self.assertTrue(parsed["iys_rejected"] or not parsed["iys_registered"] or not parsed["merchant_verified"])
                else:
                    with self.assertRaises(ValueError):
                        self.parse([row])
        with self.assertRaises(ValueError):
            self.parse([self.row, self.row])
        with self.assertRaises(ValueError):
            parse_document('{"schema":"unknown","records":[]}', self.now)

    def test_duplicate_crm_identity_is_held_and_no_smtp_is_possible(self):
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, sql, params=()): self.calls.append((sql, params))
            def fetchall(self): return [("node/1", {}), ("node/2", {})]
            def __enter__(self): return self
            def __exit__(self, *args): return False
        class Conn:
            def __init__(self): self.cur = Cursor()
            def transaction(self):
                class Tx:
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                return Tx()
            def cursor(self): return self.cur
        conn = Conn()
        result = import_records(conn, self.parse())
        self.assertEqual(result["held"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertFalse(any("SMTP" in sql.upper() or "SEND" in sql.upper()
                             for sql, _ in conn.cur.calls))


if __name__ == "__main__":
    unittest.main()
