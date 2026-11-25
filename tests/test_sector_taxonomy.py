import unittest

from leadhunter.core import lead_from_osm
from leadhunter.sector_taxonomy import classify_osm_tags, overpass_tag_selectors


class SectorTaxonomyTests(unittest.TestCase):
    def test_user_sectors_have_explicit_tag_subcategories(self):
        cases = [
            ({"amenity": "restaurant"}, "food_hospitality", "restaurant"),
            ({"amenity": "cafe"}, "food_hospitality", "cafe"),
            ({"tourism": "hotel"}, "accommodation", "hotel"),
            ({"office": "estate_agent"}, "real_estate", "estate_agent"),
            ({"shop": "car_repair"}, "automotive", "car_repair"),
            ({"office": "construction_company"}, "construction", "construction_company"),
            ({"man_made": "works"}, "manufacturing", "production_site"),
            ({"shop": "beauty"}, "beauty_personal_care", "beauty_salon"),
            ({"shop": "hairdresser"}, "beauty_personal_care", "hairdresser"),
            ({"office": "travel_agent"}, "tourism_travel", "travel_agent"),
        ]
        for tags, sector, subcategory in cases:
            with self.subTest(tags=tags):
                result = classify_osm_tags(tags, osm_type="node", osm_id=9)
                self.assertEqual(result["sector"], sector)
                self.assertEqual(result["subcategory"], subcategory)
                self.assertEqual(result["classification_status"], "source_tag_match")
                self.assertEqual(result["category_evidence"][0]["tag_key"], next(iter(tags)))
                self.assertEqual(result["category_evidence"][0]["tag_value"], next(iter(tags.values())))
                self.assertEqual(result["category_evidence"][0]["source_url"],
                                 "https://www.openstreetmap.org/node/9")

    def test_generic_company_is_not_guessed_to_be_a_service_sector_or_sme(self):
        result = classify_osm_tags({"office": "company"}, osm_type="way", osm_id=12)
        self.assertIsNone(result["sector"])
        self.assertEqual(result["subcategory"], "general_company_unknown_sector")
        self.assertEqual(result["business_size_status"], "unknown")
        self.assertEqual(result["classification_status"], "generic_company_manual_research")
        self.assertEqual(result["category_evidence"][0]["tag_key"], "office")

    def test_unknown_tag_stays_unknown_and_has_no_category_evidence(self):
        result = classify_osm_tags({"shop": "chemist"})
        self.assertIsNone(result["sector"])
        self.assertIsNone(result["subcategory"])
        self.assertEqual(result["classification_status"], "unknown_manual_research")
        self.assertEqual(result["category_evidence"], [])
        self.assertEqual(result["business_size_status"], "unknown")

    def test_conflicting_sector_tags_go_to_manual_review(self):
        result = classify_osm_tags({"amenity": "restaurant", "tourism": "hotel"})
        self.assertIsNone(result["sector"])
        self.assertIsNone(result["category"])
        self.assertEqual(result["classification_status"], "multiple_sectors_manual_review")
        self.assertEqual(len(result["category_evidence"]), 2)

    def test_lead_carries_source_evidence_and_leaves_size_unknown(self):
        lead = lead_from_osm({"type": "node", "id": 15,
                              "tags": {"name": "Synthetic Cafe", "amenity": "cafe"}})
        self.assertEqual(lead["sector"], "food_hospitality")
        self.assertEqual(lead["subcategory"], "cafe")
        self.assertEqual(lead["sector_evidence"][0]["source_url"],
                         "https://www.openstreetmap.org/node/15")
        self.assertEqual(lead["business_size_status"], "unknown")

    def test_generic_named_company_stays_in_research_queue(self):
        lead = lead_from_osm({"type": "node", "id": 17,
                              "tags": {"name": "Synthetic company", "office": "company"}})
        self.assertEqual(lead["sector_classification_status"],
                         "generic_company_manual_research")
        self.assertIsNone(lead["sector"])
        from leadhunter.core import recommend
        self.assertEqual(recommend(lead)["focus"], "research")

    def test_taxonomy_is_an_explicit_selector_catalog(self):
        selectors = set(overpass_tag_selectors())
        self.assertIn(("amenity", "restaurant"), selectors)
        self.assertIn(("office", "estate_agent"), selectors)
        self.assertIn(("man_made", "works"), selectors)


if __name__ == "__main__":
    unittest.main()
