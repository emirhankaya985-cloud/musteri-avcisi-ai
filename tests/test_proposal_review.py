"""Proposal review labels evidence and never creates send authorization."""
import unittest
from datetime import datetime, timezone

from leadhunter.proposal_review import build_proposal_review

NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


def website_absence_evidence():
    return {
        "website_absence_verified": True,
        "website_absence_verified_evidence_url": "https://business.example/contact",
        "website_absence_verified_source_type": "business_first_party",
        "website_absence_verified_verified_at": "2026-11-26T11:00:00+00:00",
        "website_absence_verified_confidence": 90,
        "website_absence_verified_rationale": "Resmi iletişim sayfası kontrolünde site bağlantısı yok.",
    }


class ProposalReviewTests(unittest.TestCase):
    def test_missing_evidence_yields_question_not_a_verified_need(self):
        result = build_proposal_review(
            {"id": "node/42", "name": "Örnek İşletme", "category": "Çiçekçi"}, now=NOW)
        self.assertEqual(result["status"], "research_required")
        self.assertEqual(result["claim_level"], "exploratory_question")
        self.assertIsNone(result["service"])
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["recommendation_is_hypothesis"])
        self.assertIn("önce ihtiyacı doğrulayıp", result["draft"])
        self.assertFalse(result["email_send_authorized"])

    def test_osm_tags_alone_never_turn_a_hypothesis_into_verified_email_claim(self):
        result = build_proposal_review({
            "id": "node/44", "name": "Örnek İşletme", "category": "Çiçekçi",
            "website": "https://business.example", "phone": "+905551112233"}, now=NOW)
        self.assertEqual(result["claim_level"], "exploratory_question")
        self.assertNotIn("doğrulanmış", result["draft"].casefold())
        self.assertIsNone(result["service"])

    def test_current_first_party_evidence_is_attached_for_human_review(self):
        result = build_proposal_review({
            "id": "node/43", "name": "Örnek İşletme", "category": "Çiçekçi",
            "qualification": website_absence_evidence()}, now=NOW)
        self.assertEqual(result["status"], "ready_for_owner_review")
        self.assertEqual(result["service"], "Profesyonel web sitesi")
        self.assertEqual(result["claim_level"], "verified_need")
        self.assertEqual(result["evidence"][0]["url"],
                         "https://business.example/contact")
        self.assertTrue(result["human_review_required"])
        self.assertFalse(result["email_send_authorized"])

    def test_stale_evidence_does_not_support_personalized_claim(self):
        qualification = website_absence_evidence()
        qualification["website_absence_verified_verified_at"] = "2020-01-01T00:00:00+00:00"
        result = build_proposal_review({"category": "Çiçekçi",
                                        "qualification": qualification}, now=NOW)
        self.assertEqual(result["status"], "research_required")
        self.assertIsNone(result["service"])
        self.assertFalse(result["evidence"])
        self.assertFalse(result["email_send_authorized"])


if __name__ == "__main__":
    unittest.main()
