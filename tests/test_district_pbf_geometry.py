"""Offline tests for the bounded Pyosmium district relation extractor."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leadhunter.district_pbf_geometry import extract_district_geometries

try:
    import osmium
except ImportError:  # The normal CI job does not install the optional PBF parser.
    osmium = None


class DistrictPbfGeometryValidationTests(unittest.TestCase):
    def test_rejects_bad_digest_before_opening_source(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            extract_district_geometries("missing.pbf", ["relation/12"], "not-a-digest")

    def test_rejects_duplicate_or_malformed_expected_ids(self):
        good_digest = "0" * 64
        for values in (["relation/12", "relation/12"], ["way/12"], ["relation/0"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                extract_district_geometries("missing.pbf", values, good_digest)

    def test_rejects_unbounded_expected_relation_set(self):
        with self.assertRaisesRegex(ValueError, "1 to 1000"):
            extract_district_geometries(
                "missing.pbf", [f"relation/{value}" for value in range(1, 1002)], "0" * 64
            )


@unittest.skipIf(osmium is None, "Pyosmium is not installed")
class DistrictPbfGeometryOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="district-pbf-test-")
        cls.pbf_path = Path(cls.temp_dir.name) / "synthetic.osm.pbf"
        cls.snapshot_at = datetime.now(timezone.utc).replace(microsecond=0)
        timestamp = cls.snapshot_at.isoformat().replace("+00:00", "Z")
        header = osmium.io.Header()
        header.set("osmosis_replication_timestamp", timestamp)
        with osmium.SimpleWriter(cls.pbf_path, header=header) as writer:
            coords = [(-1.0, 0.0), (-1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
            for node_id, point in enumerate(coords, start=1):
                writer.add_node(osmium.osm.mutable.Node(id=node_id, location=point))
            writer.add_way(osmium.osm.mutable.Way(id=101, nodes=[1, 2, 3, 4, 1]))
            writer.add_relation(osmium.osm.mutable.Relation(
                id=501,
                members=[("w", 101, "outer")],
                tags={"type": "multipolygon", "boundary": "administrative", "admin_level": "6"},
            ))
        cls.digest = hashlib.sha256(cls.pbf_path.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_extracts_exact_relation_geometry_and_source_receipt(self):
        result = extract_district_geometries(
            self.pbf_path, ["relation/501"], self.digest, now=self.snapshot_at + timedelta(minutes=1)
        )
        self.assertEqual(set(result), {"geometries", "source"})
        self.assertEqual(set(result["geometries"]), {"relation/501"})
        geometry = result["geometries"]["relation/501"]
        self.assertEqual(geometry["type"], "MultiPolygon")
        ring = geometry["coordinates"][0][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 5)
        self.assertEqual(result["source"]["sha256"], self.digest)
        self.assertEqual(result["source"]["relation_count"], 1)
        self.assertEqual(result["source"]["coordinate_count"], 5)
        self.assertEqual(result["source"]["location_storage"], "sparse_file_array")
        self.assertIs(result["source"]["official_boundary"], False)

    def test_fails_closed_when_expected_relation_is_missing(self):
        with self.assertRaisesRegex(ValueError, "relation set mismatch"):
            extract_district_geometries(
                self.pbf_path, ["relation/501", "relation/502"], self.digest,
                now=self.snapshot_at + timedelta(minutes=1),
            )

    def test_rejects_stale_snapshot(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            extract_district_geometries(
                self.pbf_path, ["relation/501"], self.digest,
                now=self.snapshot_at + timedelta(days=3), max_age=timedelta(days=1),
            )

    def test_rejects_checksum_mismatch_and_source_size_overrun(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            extract_district_geometries(
                self.pbf_path, ["relation/501"], "0" * 64,
                now=self.snapshot_at + timedelta(minutes=1),
            )
        with self.assertRaisesRegex(ValueError, "size bound"):
            extract_district_geometries(
                self.pbf_path, ["relation/501"], self.digest,
                now=self.snapshot_at + timedelta(minutes=1), max_pbf_bytes=1,
            )

    def test_rejects_coordinate_bound_smaller_than_polygon(self):
        with self.assertRaisesRegex(ValueError, "coordinate limit"):
            extract_district_geometries(
                self.pbf_path, ["relation/501"], self.digest,
                now=self.snapshot_at + timedelta(minutes=1), max_total_coordinates=4,
                max_relation_coordinates=4,
            )


if __name__ == "__main__":
    unittest.main()
