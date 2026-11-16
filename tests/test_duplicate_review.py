"""No-network, no-contact duplicate-company review regressions."""
import unittest
from leadhunter.duplicate_review import normalized, domain, phone, candidates


def lead(name,category="Kuaför/berber",website="",telephone="",address=""):
    return {"name":name,"category":category,"website":website,
            "phone":telephone,"address":address}


class CompanyDuplicateReviewTests(unittest.TestCase):
    def test_distinct_osm_and_web_source_same_first_party_domain_needs_review(self):
        rows=[
            ("node/41",lead("Salon Alpha","Kuaför/berber","https://www.alpha.example/contact")),
            ("website/42",lead("Alpha Salon","Kuaför/berber","alpha.example")),
            ("node/43",lead("Other","Kuaför/berber","https://beta.example")),
        ]
        matched=candidates(rows)
        self.assertEqual(len(matched),1)
        self.assertIn(("node/41","website/42"),matched)
        self.assertIn("same_first_party_domain",matched[("node/41","website/42")])

    def test_turkish_phone_and_same_name_address_across_osm_ids(self):
        rows=[
            ("node/21",lead("Ali Kuaför","Kuaför/berber","",
                             "+90 (532) 111 22 33","Çiçek sokak 2")),
            ("way/22",lead("Ali kuaför","Kuaför/berber","",
                            "0532 111 22 33","Çiçek sokak 2")),
        ]
        reasons=candidates(rows)[("node/21","way/22")]
        self.assertIn("same_phone",reasons)
        self.assertIn("same_name_address",reasons)
        self.assertIn("same_name_category_review",reasons)

    def test_identical_chain_names_are_only_weak_review_not_auto_merge(self):
        rows=[
            ("node/21",lead("Zincir Market","Mağaza",address="Gül sokak 2")),
            ("way/22",lead("Zincir Market","Mağaza",address="Deniz cadde 20")),
        ]
        found=candidates(rows)
        self.assertEqual(found[("node/21","way/22")],
                         ("same_name_category_review",))
        # Independent company branches remain distinct IDs / CRM records.
        self.assertEqual(len(rows),2)

    def test_generic_social_profiles_not_considered_a_shared_company_domain(self):
        rows=[
            ("node/1",lead("Farklı A",website="instagram.com/test1")),
            ("node/2",lead("Farklı B",website="https://instagram.com/test2")),
            ("node/3",lead("Farklı C",website="facebook.com/test3")),
        ]
        self.assertEqual(candidates(rows),{})
        self.assertIsNone(domain("https://www.instagram.com/brand"))
        self.assertEqual(domain("www.example.org/about"),"example.org")

    def test_normalization_and_repeat_determinism(self):
        rows=[
            ("node/1",lead("   SALON  CEDAR  ","Kuaför/berber")),
            ("way/3",lead("salon cedar","Kuaför/berber"))
        ]
        self.assertEqual(candidates(rows),candidates(rows[::-1]))
        self.assertEqual(normalized("Hi   There"),"hi there")
        self.assertEqual(phone("+90 (555) 111 22 33"),"905551112233")
        self.assertNotIn(("node/1","node/1"),candidates(rows))
        with self.assertRaises(ValueError):
            candidates([("",lead("Shop"))])


if __name__=="__main__":
    unittest.main()
