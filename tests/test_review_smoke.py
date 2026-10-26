"""Offline smoke safety tests; no network or real database access."""
import unittest
from leadhunter import review_smoke


class SafeSmokeTests(unittest.TestCase):
    def test_fixture_uses_unambiguous_synthetic_names(self):
        self.assertEqual(len(review_smoke.TEST_IDS), 3)
        self.assertEqual(len(set(review_smoke.TEST_IDS)), 3)
        for lead_id in review_smoke.TEST_IDS:
            self.assertIn("NOT A REAL BUSINESS", review_smoke._fixture(lead_id)["name"])

    def test_missing_secret_blocks_connection(self):
        invoked = []
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            review_smoke.run({}, connector=lambda x: invoked.append(x))
        self.assertEqual(invoked, [])

    def test_bad_connection_redacts_private_string(self):
        def broken(url):
            raise ValueError("postgresql://super_secret_credentials")
        with self.assertRaisesRegex(RuntimeError, "credentials redacted") as ctx:
            review_smoke.run({"REVIEW_DATABASE_URL":"postgresql://super_secret_credentials"},
                             connector=broken)
        self.assertNotIn("super_secret_credentials", str(ctx.exception))

    def test_no_success_if_verification_raises(self):
        class FakeConn:
            closed = False
            def close(self):
                self.closed = True
        db = FakeConn()
        old_verify = review_smoke.verify
        review_smoke.verify = lambda conn: (_ for _ in ()).throw(ValueError("secret text"))
        try:
            with self.assertRaisesRegex(RuntimeError, "credentials redacted") as ctx:
                review_smoke.run({"REVIEW_DATABASE_URL":"postgresql://hidden"},
                                 connector=lambda _: db, output=lambda _:self.fail("should not report PASS"))
            self.assertNotIn("secret text", str(ctx.exception))
        finally:
            review_smoke.verify = old_verify
        self.assertTrue(db.closed)


if __name__ == "__main__":
    unittest.main()
