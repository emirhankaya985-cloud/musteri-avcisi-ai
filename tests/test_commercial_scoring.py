"""Commercial scores require current, explainable source evidence."""
import unittest
from datetime import datetime, timezone

from leadhunter.commercial_scoring import WEIGHTS, match_service, score_prospect

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
URL = "https://example.com/business"
STAMP = "2026-11-24T11:00:00+00:00"


def component(value, **overrides):
    item = {
        "value": value,
        "evidence_ref": URL,
        "source_type": "business_first_party",
        "verified_at": STAMP,
        "confidence": 90,
        "rationale": "Resmi işletme sayfasında gözlemlenen güncel bilgi.",
    }
    item.update(overrides)
    return item


def signal(signal_name):
    return {
        signal_name: True,
        f"{signal_name}_evidence_url": URL,
        f"{signal_name}_source_type": "business_first_party",
        f"{signal_name}_verified_at": STAMP,
        f"{signal_name}_confidence": 90,
        f"{signal_name}_rationale": "Güncel ve açık birinci taraf kaynakta doğrulandı.",
    }


class CommercialScoringTests(unittest.TestCase):
    def test_absent_inputs_are_unknown_not_zero_or_a_commercial_score(self):
        result = score_prospect({"website": "", "phone": ""}, NOW)
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage"], 0)
        self.assertEqual((result["score_min"], result["score_max"]), (0, 100))
        self.assertIsNone(result["components"]["service_need"])
        self.assertEqual(result["component_evidence"]["service_need"]["reason"],
                         "evidence_not_recorded")
        self.assertEqual(result["confidence_summary"]["weighted_mean"], None)
        self.assertEqual(match_service({"website": ""}, NOW)["category"], None)

    def test_complete_evidence_uses_requested_weights_and_is_explainable(self):
        values = {
            "service_need": 100,
            "contact_accuracy": 80,
            "service_fit": 75,
            "commercial_potential": 60,
            "digital_gap": 50,
            "data_freshness": 100,
        }
        components = {name: component(value) for name, value in values.items()}
        expected = round(sum(WEIGHTS[name] * value / 100
                             for name, value in values.items()))
        lead = {"qualification": {"commercial_components": components}}
        result = score_prospect(lead, NOW)
        self.assertEqual(result["score"], expected)
        self.assertEqual(result["score_min"], expected)
        self.assertEqual(result["score_max"], expected)
        self.assertEqual(result["coverage"], 100)
        evidence = result["component_evidence"]["service_need"]
        self.assertEqual(evidence["status"], "counted")
        self.assertEqual(evidence["evidence_ref"], URL)
        self.assertEqual(evidence["source_type"], "business_first_party")
        self.assertEqual(evidence["confidence"], 90)
        self.assertIn("Resmi işletme sayfasında", evidence["rationale"])
        self.assertEqual(result["confidence_summary"]["weighted_mean"], 90)
        self.assertIn("not a probability", result["confidence_summary"]["interpretation"])
        self.assertEqual(score_prospect(lead, NOW), result)

    def test_missing_or_stale_inputs_are_excluded_with_reasons(self):
        components = {
            "service_need": component(0, verified_at="2020-01-01T00:00:00+00:00"),
            "contact_accuracy": component(100, confidence=None),
            "service_fit": component(80, source_type="unapproved_source"),
        }
        result = score_prospect({"qualification": {"commercial_components": components}}, NOW)
        self.assertEqual(result["coverage"], 0)
        self.assertIsNone(result["components"]["service_need"])
        self.assertEqual(result["component_evidence"]["service_need"]["reason"], "evidence_stale")
        self.assertEqual(result["component_evidence"]["contact_accuracy"]["reason"],
                         "confidence_not_recorded")
        self.assertEqual(result["component_evidence"]["service_fit"]["reason"],
                         "source_type_not_verified")

    def test_partial_evidence_exposes_bounds_but_never_a_point_score(self):
        names = ("service_need", "contact_accuracy", "service_fit",
                 "commercial_potential", "digital_gap")
        components = {name: component(100) for name in names}
        result = score_prospect({"qualification": {"commercial_components": components}}, NOW)
        self.assertIsNone(result["score"])
        self.assertEqual(result["score_min"], 95)
        self.assertEqual(result["score_max"], 100)
        self.assertEqual(result["band"], "high_unverified_range")
        self.assertEqual(result["component_evidence"]["data_freshness"]["reason"],
                         "evidence_not_recorded")

    def test_bad_numeric_url_timestamp_and_container_inputs_fail_closed(self):
        invalid = [
            component(float("nan")),
            component(True),
            component(101),
            component(10**1000),
            component(80, evidence_ref="javascript:alert(1)"),
            component(80, evidence_ref="https://user:password@example.com/x"),
            component(80, verified_at="2026-11-24T10:00:00"),
            component(80, verified_at="2027-01-01T00:00:00+00:00"),
        ]
        for bad in invalid:
            with self.subTest(bad=bad):
                result = score_prospect({"qualification": {"commercial_components": {
                    "service_need": bad}}}, NOW)
                self.assertEqual(result["coverage"], 0)
        for bad in ({"source_type": []}, {"confidence": {}}, {"rationale": 42}):
            with self.subTest(bad=bad):
                item = component(80)
                item.update(bad)
                result = score_prospect({"qualification": {"commercial_components": {
                    "service_need": item}}}, NOW)
                self.assertEqual(result["coverage"], 0)

    def test_score_bands_use_requested_boundaries(self):
        def complete(value):
            parts = {name: component(value) for name in WEIGHTS}
            return score_prospect({"qualification": {"commercial_components": parts}}, NOW)
        self.assertEqual(complete(80)["band"], "high")
        self.assertEqual(complete(60)["band"], "review")
        self.assertEqual(complete(59)["band"], "low")

    def test_service_categories_require_fresh_explained_source_signals(self):
        q1 = signal("website_absence_verified")
        result = match_service({"qualification": q1}, NOW)
        self.assertEqual(result["category"], 1)
        self.assertEqual(result["evidence"][0]["confidence"], 90)

        q2 = signal("whatsapp_automation_need_verified")
        q2.update(signal("website_absence_verified"))
        self.assertEqual(match_service({"qualification": q2}, NOW)["category"], 2)
        q2["whatsapp_automation_need_verified_confidence"] = None
        self.assertEqual(match_service({"qualification": q2}, NOW)["category"], 1)
        stale = signal("website_absence_verified")
        stale["website_absence_verified_verified_at"] = "2020-01-01T00:00:00+00:00"
        self.assertIsNone(match_service({"qualification": stale}, NOW)["category"])

    def test_category_three_requires_current_signal_evidence_and_complete_score(self):
        q = {}
        for name in ("website_presence_verified", "whatsapp_presence_verified",
                     "automation_need_verified"):
            q.update(signal(name))
        lead = {"qualification": q}
        self.assertIsNone(match_service(lead, NOW)["category"])
        q["commercial_components"] = {name: component(80) for name in WEIGHTS}
        match = match_service(lead, NOW)
        self.assertEqual(match["category"], 3)
        self.assertEqual(match["commercial_score"], 80)
        q["commercial_components"]["service_need"] = component(50)
        self.assertIsNone(match_service(lead, NOW)["category"])


if __name__ == "__main__":
    unittest.main()
