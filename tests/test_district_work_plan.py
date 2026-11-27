"""Deterministic district plans only; no PBF, OSM, Neon or CRM access."""
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.district_work_plan import (
    compile_province_plans, load_inventory, next_district_batch,
)


class DistrictWorkPlanTests(unittest.TestCase):
    def test_pinned_inventory_compiles_81_province_973_district_work_items(self):
        inventory = load_inventory()
        plans = compile_province_plans()
        self.assertEqual(len(plans), 81)
        self.assertEqual(len(inventory["district_ids"]), 973)
        self.assertEqual(sum(len(p["work_item_ids"]) for p in plans.values()), 973)
        self.assertTrue(all(p["official_boundary"] is False for p in plans.values()))
        self.assertTrue(all(p["scan_started"] is False and p["completed_items"] == 0
                            for p in plans.values()))
        self.assertTrue(all(p["source_sha256"] == inventory["manifest"]["source"]["summary_sha256"]
                            for p in plans.values()))
        self.assertTrue(all(p["boundary_manifest_sha256"] == inventory["manifest_sha256"]
                            for p in plans.values()))

    def test_resume_batch_is_bounded_stable_and_excludes_receipted_ids(self):
        items = ["relation/11", "relation/12", "relation/13", "relation/14"]
        self.assertEqual(next_district_batch(items, {"relation/11"}, limit=2),
                         ["relation/12", "relation/13"])
        self.assertEqual(next_district_batch(items, set(), limit=25), items)
        self.assertEqual(next_district_batch(items, set(items)), [])

    def test_bad_or_ambiguous_inventory_fails_closed(self):
        original = json.loads(Path("data/osm_boundary_manifest_v2026.11.0.json").read_text(
            encoding="utf-8"))
        cases = []
        wrong_boundary = json.loads(json.dumps(original))
        wrong_boundary["official_boundary"] = True
        cases.append(wrong_boundary)
        wrong_total = json.loads(json.dumps(original))
        wrong_total["district_count"] = 972
        cases.append(wrong_total)
        duplicate = json.loads(json.dumps(original))
        duplicate["provinces"][0]["districts"][0]["relation_id"] = \
            duplicate["provinces"][1]["districts"][0]["relation_id"]
        cases.append(duplicate)
        for value in cases:
            with self.subTest(value=value["district_count"], official=value["official_boundary"]):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "manifest.json"
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_inventory(path)

    def test_resume_rejects_out_of_plan_receipts_and_unsafe_limits(self):
        items = ["relation/11", "relation/12"]
        for receipts, limit in (({"relation/99"}, 1), (set(), 0), (set(), 26)):
            with self.subTest(receipts=receipts, limit=limit), self.assertRaises(ValueError):
                next_district_batch(items, receipts, limit=limit)


if __name__ == "__main__":
    unittest.main()
