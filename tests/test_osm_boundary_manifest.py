"""Pinned OSM-derived boundary inventory validation; fixtures only."""
import json
import unittest

from leadhunter.osm_boundary_manifest import build_manifest
from leadhunter.province_coverage import PROVINCES


def raw_fixture():
    provinces = []
    next_relation = 10_000
    remaining = 973
    for index, (code, name) in enumerate(PROVINCES):
        count = remaining - (80 - index) * 12 if index == 0 else 12
        if index == 0:
            count = 13
        remaining -= count
        province_relation = next_relation
        next_relation += 1
        districts = []
        for within in range(count):
            districts.append({"ad": f"District {code}-{within + 1}",
                              "osm_id": next_relation})
            next_relation += 1
        provinces.append({"kod": code, "ad": name,
                          "osm_id": province_relation,
                          "bbox": [26.0, 36.0, 45.0, 42.0],
                          "ilceler": districts})
    summary = {
        "veri_tarihi": "2026-11-01",
        "derleme_zamani": "2026-11-03T04:04:28Z",
        "kaynak": "© OpenStreetMap contributors",
        "lisans": "ODbL 1.0",
        "lisans_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "il_sayisi": 81,
        "ilce_sayisi": 973,
        "iller": provinces,
    }
    return summary


class OSMBoundaryManifestTests(unittest.TestCase):
    def build(self, summary=None, *, raw=None, tag="v2026.11.0", sha="a" * 40):
        data = raw if raw is not None else json.dumps(
            raw_fixture() if summary is None else summary,
            ensure_ascii=False, separators=(",", ":")).encode()
        return build_manifest(data, release_tag=tag, tag_commit_sha=sha)

    def test_pinned_complete_inventory_is_marked_non_official_and_source_bound(self):
        import hashlib
        raw = json.dumps(raw_fixture(), ensure_ascii=False,
                         separators=(",", ":")).encode()
        manifest = self.build(raw=raw, sha="b" * 40)
        self.assertFalse(manifest["official_boundary"])
        self.assertEqual(manifest["manifest_type"],
                         "osm_derived_non_official_admin_boundaries")
        self.assertEqual(manifest["province_count"], 81)
        self.assertEqual(manifest["district_count"], 973)
        self.assertEqual(manifest["source"]["release_tag"], "v2026.11.0")
        self.assertEqual(manifest["source"]["tag_commit_sha"], "b" * 40)
        self.assertEqual(manifest["source"]["summary_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(manifest["source"]["license"], "ODbL 1.0")
        self.assertEqual(manifest["provinces"][0]["code"], "01")
        self.assertTrue(manifest["provinces"][0]["districts"][0]["relation_id"].startswith("relation/"))

    def test_wrong_release_or_commit_identity_fails_closed(self):
        for tag, sha in (("latest", "a" * 40), ("v2026.11.0", "a" * 39),
                         ("v2026.13.0", "A" * 40)):
            with self.subTest(tag=tag, sha=sha), self.assertRaises(ValueError):
                self.build(tag=tag, sha=sha)

    def test_missing_province_or_published_total_mismatch_fails_closed(self):
        for mutation in (
            lambda x: x["iller"].pop(),
            lambda x: x.update(il_sayisi=80),
            lambda x: x.update(ilce_sayisi=972),
        ):
            data = raw_fixture()
            mutation(data)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.build(data)

    def test_missing_or_duplicate_relation_id_fails_closed(self):
        data = raw_fixture()
        data["iller"][0]["ilceler"][0]["osm_id"] = None
        with self.assertRaisesRegex(ValueError, "relation ID"):
            self.build(data)

        data = raw_fixture()
        duplicate = data["iller"][0]["osm_id"]
        data["iller"][1]["osm_id"] = duplicate
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.build(data)

    def test_duplicate_province_code_or_ambiguous_district_name_fails(self):
        data = raw_fixture()
        data["iller"][1]["kod"] = data["iller"][0]["kod"]
        data["iller"][1]["ad"] = data["iller"][0]["ad"]
        with self.assertRaises(ValueError):
            self.build(data)

        data = raw_fixture()
        data["iller"][0]["ilceler"][1]["ad"] = data["iller"][0]["ilceler"][0]["ad"]
        with self.assertRaisesRegex(ValueError, "duplicate district names"):
            self.build(data)

    def test_wrong_license_source_or_bbox_fails_closed(self):
        for mutation in (
            lambda x: x.update(lisans="unknown"),
            lambda x: x.update(kaynak="unknown map"),
            lambda x: x["iller"][0].update(bbox=[28, 45, 26, 35]),
        ):
            data = raw_fixture()
            mutation(data)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.build(data)


if __name__ == "__main__":
    unittest.main()
