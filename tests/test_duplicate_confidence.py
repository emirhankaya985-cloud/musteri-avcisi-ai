"""No-network tests for evidence-only duplicate-candidate confidence."""
import unittest
import json

from leadhunter.duplicate_confidence import score_pair
from leadhunter.duplicate_review import sync


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT osm_id,lead_data"):
            self.rows = self.db.leads
        elif "FROM owner_duplicate_geo_evidence" in sql:
            self.rows = self.db.geo
        elif sql.startswith("SELECT count(*) FROM owner_duplicate_review_pairs"):
            self.rows = [(len(self.db.inserts),)]
        elif sql.startswith("INSERT INTO owner_duplicate_review_pairs"):
            self.db.inserts.append(params)
            self.rows = []
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0]


class _Db:
    def __init__(self):
        self.leads = [
            ("node/10", {"name":"Example Salon", "category":"Salon",
                         "website":"https://example.test", "phone":"+90 532 111 2233"}),
            ("way/20", {"name":"Example Salon", "category":"Salon",
                        "website":"https://example.test", "phone":"0532 111 22 33"}),
        ]
        self.geo = [("node/10", "way/20", "nearby")]
        self.inserts = []

    def cursor(self):
        return _Cursor(self)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DuplicateConfidenceTests(unittest.TestCase):
    def test_name_and_category_alone_is_weak_and_never_merge_authorized(self):
        score, details = score_pair(("same_name_category_review",))
        self.assertEqual(score, 20)
        self.assertEqual(details["branch_risk"], "unknown")
        self.assertFalse(details["automatic_merge_allowed"])

    def test_independent_signals_are_deterministic_and_explainable(self):
        reasons = ("same_first_party_domain", "same_phone", "same_name_address")
        first = score_pair(reasons)
        second = score_pair(reversed(reasons))
        self.assertEqual(first, second)
        self.assertEqual(first[0], 95)
        self.assertEqual(first[1]["independent_signal_count"], 3)
        self.assertEqual(set(first[1]["signal_weights"]), set(reasons))

    def test_same_name_address_beats_name_category_only(self):
        weak, _ = score_pair(("same_name_category_review",))
        stronger, _ = score_pair(("same_name_address", "same_name_category_review"))
        self.assertEqual(stronger, 65)
        self.assertGreater(stronger, weak)

    def test_distance_does_not_raise_identity_score_and_keeps_branch_risk(self):
        evidence = ("same_first_party_domain", "same_name_category_review")
        near, near_detail = score_pair(evidence, "nearby")
        far, far_detail = score_pair(evidence, "separated")
        colocated, colocated_detail = score_pair(evidence, "co_located")
        self.assertEqual((near, far, colocated), (55, 55, 55))
        self.assertEqual(near_detail["branch_risk"], "possible_different_branch")
        self.assertEqual(far_detail["branch_risk"], "possible_different_branch")
        self.assertEqual(colocated_detail["branch_risk"], "low_but_not_excluded")

    def test_unknown_reason_or_distance_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unknown duplicate evidence"):
            score_pair(("same_email_guess",))
        with self.assertRaisesRegex(ValueError, "Unknown duplicate location"):
            score_pair(("same_phone",), "address_missing")

    def test_sync_persists_score_and_branch_caution_without_merging(self):
        db = _Db()
        output = []
        count, added = sync(db, output.append)
        self.assertEqual((count, added), (1, 1))
        params = db.inserts[0]
        self.assertEqual((params[0], params[1]), ("node/10", "way/20"))
        self.assertEqual(params[3], 70)
        details = json.loads(params[4])
        self.assertEqual(details["branch_risk"], "possible_different_branch")
        self.assertFalse(details["automatic_merge_allowed"])
        self.assertIn("automatically_merged=0", output[0])


if __name__ == "__main__":
    unittest.main()
