"""Synthetic source/restore inventory tests. No real customer DB access."""
import unittest
from leadhunter.restore_acceptance import row_fingerprint, compare_inventory, run


class RestoreAcceptanceTests(unittest.TestCase):
    def test_full_row_hash_independent_of_query_order(self):
        rows=[(1,{"z":1,"a":2},"review"), (2,{"name":"Synthetic"},"sent")]
        expected=row_fingerprint(rows)
        self.assertEqual(expected,row_fingerprint(reversed(rows)))
        self.assertEqual(expected[0],2)

    def test_changed_private_value_or_missing_row_fails(self):
        before=row_fingerprint([(1,{"a":"synthetic"})])
        after=row_fingerprint([(1,{"a":"changed"})])
        self.assertNotEqual(before,after)
        self.assertFalse(compare_inventory({"owner_leads":before},
                                           {"owner_leads":after}))
        self.assertFalse(compare_inventory({},{}))

    def test_target_must_be_local_isolated_postgres(self):
        for target in ("postgresql://some-host.invalid:5432/db",
                       "postgresql://localhost:5433/db",
                       "postgresql://127.0.0.1/db"):
            with self.subTest(target=target), self.assertRaisesRegex(
                    RuntimeError,"non-local restore target"):
                run({"REVIEW_DATABASE_URL":"postgresql://source.example.invalid/db",
                     "ISOLATED_POSTGRES_URL":target})

    def test_missing_or_same_database_fails_before_network(self):
        with self.assertRaisesRegex(RuntimeError,"distinct configured"):
            run({})
        with self.assertRaisesRegex(RuntimeError,"distinct configured"):
            run({"REVIEW_DATABASE_URL":"postgresql://localhost:5432/db",
                 "ISOLATED_POSTGRES_URL":"postgresql://localhost:5432/db"})


if __name__=="__main__":
    unittest.main()
