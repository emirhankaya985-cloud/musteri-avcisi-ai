"""Commercial scores require fresh, source-backed evidence."""
import unittest
from datetime import datetime, timezone

from leadhunter.commercial_scoring import WEIGHTS, match_service, score_prospect


NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
EVIDENCE = "https://example.com/business"
STAMP = "2026-11-24T11:00:00+00:00"


class CommercialScoringTests(unittest.TestCase):
    def test_absent_inputs_are_unknown_not_zero_or_a_commercial_score(self):
        result = score_prospect({"website": "", "phone": ""}, NOW)
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage"], 0)
        self.assertEqual((result["score_min"], result["score_max"]), (0, 100))
        self.assertEqual(result["band"], "review")
        self.assertEqual(match_service({"website": ""}, NOW)["category"], None)

    def test_complete_evidence_uses_the_requested_weighted_formula(self):
        values = {
            "service_need": 100,
            "contact_accuracy": 80,
            "service_fit": 75,
            "commercial_potential": 60,
            "digital_gap": 50,
            "data_freshness": 100,
        }
        components = {name: {"value": value, "evidence_ref": EVIDENCE,
                             "verified_at": STAMP}
                      for name, value in values.items()}
        expected = round(sum(WEIGHTS[name] * value / 100
                             for name, value in values.items()))
        result = score_prospect({"qualification":{"commercial_components":components}}, NOW)
        self.assertEqual(result["score"], expected)
        self.assertEqual(result["score_min"], expected)
        self.assertEqual(result["score_max"], expected)
        self.assertEqual(result["coverage"], 100)

    def test_stale_or_unreferenced_components_do_not_count_as_known(self):
        components = {
            "service_need":{"value":0,"evidence_ref":EVIDENCE,
                            "verified_at":"2020-01-01T00:00:00+00:00"},
            "contact_accuracy":{"value":100,"evidence_ref":"", "verified_at":STAMP},
        }
        result = score_prospect({"qualification":{"commercial_components":components}}, NOW)
        self.assertEqual(result["coverage"], 0)
        self.assertIsNone(result["components"]["service_need"])

    def test_partial_evidence_reports_only_a_safe_lower_bound_band(self):
        components = {name:{"value":100,"evidence_ref":EVIDENCE,"verified_at":STAMP}
                      for name in ("service_need", "contact_accuracy", "service_fit",
                                   "commercial_potential", "digital_gap")}
        result=score_prospect({"qualification":{"commercial_components":components}}, NOW)
        self.assertIsNone(result["score"])
        self.assertEqual(result["score_min"],95)
        self.assertEqual(result["score_max"],100)
        self.assertEqual(result["band"],"high")

    def test_service_matching_requires_independent_fresh_evidence(self):
        q = {"website_absence_verified":True,
             "website_absence_verified_evidence_url":EVIDENCE,
             "website_absence_verified_verified_at":STAMP}
        self.assertEqual(match_service({"qualification":q}, NOW)["category"], 1)
        # Missing WhatsApp metadata alone cannot create category 2.
        self.assertIsNone(match_service({"website":"", "qualification":{}}, NOW)["category"])
        q["whatsapp_automation_need_verified"] = True
        q["whatsapp_automation_need_verified_evidence_url"] = EVIDENCE
        q["whatsapp_automation_need_verified_verified_at"] = STAMP
        self.assertEqual(match_service({"qualification":q}, NOW)["category"], 2)
        q["whatsapp_automation_need_verified_verified_at"] = "2020-01-01T00:00:00+00:00"
        self.assertNotEqual(match_service({"qualification":q}, NOW)["category"], 2)


if __name__ == "__main__":
    unittest.main()
