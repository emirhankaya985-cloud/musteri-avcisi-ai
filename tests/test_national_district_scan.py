"""Offline tests for exact, resumable national district attribution."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from leadhunter import national_district_scan as scan

try:
    import osmium
    import shapely
except ImportError:
    osmium = shapely = None


@unittest.skipIf(shapely is None, "Shapely 2.x is not installed")
class DistrictAttributionTests(unittest.TestCase):
    def setUp(self):
        self.geometries = {
            "relation/101": {
                "type": "Polygon", "coordinates": [[[0, 0], [0.5, 0], [0.5, 1],
                                                           [0, 1], [0, 0]]]},
            "relation/102": {
                "type": "Polygon", "coordinates": [[[0.5, 0], [1, 0], [1, 1],
                                                           [0.5, 1], [0.5, 0]]]},
        }
        self.index = scan.build_district_index(
            self.geometries,
            {"relation/101": "01", "relation/102": "01"},
        )

    def test_point_inside_one_district_gets_exact_relation(self):
        from shapely.geometry import Point
        self.assertEqual(scan.unique_district_for_point(Point(0.2, 0.5), self.index),
                         "relation/101")
        self.assertEqual(scan.unique_district_for_point(Point(0.8, 0.5), self.index),
                         "relation/102")

    def test_point_on_shared_district_edge_fails_closed(self):
        from shapely.geometry import Point
        with self.assertRaisesRegex(ValueError, "multiple district"):
            scan.unique_district_for_point(Point(0.5, 0.5), self.index)

    def test_geometry_and_province_relation_sets_must_match(self):
        with self.assertRaisesRegex(ValueError, "sets must match"):
            scan.build_district_index(self.geometries, {"relation/101": "01"})

    def test_snapshot_selection_skips_matching_receipts_even_when_province_complete(self):
        digest = "a" * 64
        province = {"code": "34", "status": "completed", "completed_items": {
            "relation/101": {"source_sha256": digest},
            "relation/102": {"source_sha256": digest},
        }}
        plan = {"work_item_ids": ["relation/101", "relation/102"],
                "excluded_item_ids": []}
        self.assertEqual(scan.districts_needing_refresh(province, plan, digest), [])

    def test_new_digest_rescans_completed_receipts_and_preserves_failed_old_receipts(self):
        province = {"code": "34", "status": "completed", "completed_items": {
            "relation/101": {"source_sha256": "a" * 64},
            "relation/102": {"source_sha256": "b" * 64},
        }}
        plan = {"work_item_ids": ["relation/101", "relation/102"],
                "excluded_item_ids": []}
        self.assertEqual(
            scan.districts_needing_refresh(province, plan, "b" * 64),
            ["relation/101"],
        )
        # Selection never removes the older receipt; it is replaced only after
        # the store records a success for the new source digest.
        self.assertEqual(province["completed_items"]["relation/101"]["source_sha256"],
                         "a" * 64)

    def test_delayed_older_snapshot_cannot_replace_newer_receipt(self):
        province_states = {"34": {"completed_items": {
            "relation/101": {"source_data_at": "2026-11-28T00:00:00Z"},
        }}}
        plans = {"34": {"work_item_ids": ["relation/101"], "excluded_item_ids": []}}
        with self.assertRaisesRegex(RuntimeError, "older than the stored receipt"):
            scan._reject_older_snapshot(
                province_states, plans, "2026-11-27T00:00:00Z")


@unittest.skipIf(osmium is None or shapely is None, "Pyosmium and Shapely are required")
class DistrictPbfAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="national-district-pbf-")
        self.pbf = Path(self.temp_dir.name) / "features.osm.pbf"
        header = osmium.io.Header()
        header.set("osmosis_replication_timestamp", "2026-11-27T00:00:00Z")
        with osmium.SimpleWriter(self.pbf, header=header) as writer:
            for node_id, xy in (
                (1, (0.20, 0.20)), (2, (0.30, 0.20)), (3, (0.30, 0.30)),
                (4, (0.20, 0.30)), (50, (0.25, 0.75)),
                (5, (0.35, 0.35)), (6, (0.40, 0.35)),
                (7, (0.40, 0.40)), (8, (0.35, 0.40)),
            ):
                writer.add_node(osmium.osm.mutable.Node(id=node_id, location=xy,
                    tags={"name": "Node Florist", "shop": "florist"} if node_id == 50 else None))
            writer.add_way(osmium.osm.mutable.Way(
                id=901, nodes=[1, 2, 3, 4, 1],
                tags={"name": "Area Florist", "shop": "florist"},
            ))
            writer.add_way(osmium.osm.mutable.Way(id=902, nodes=[5, 6, 7, 8, 5]))
            writer.add_relation(osmium.osm.mutable.Relation(
                id=903, members=[("w", 902, "outer")],
                tags={"type": "multipolygon", "name": "Relation Florist", "shop": "florist"},
            ))
        self.index = scan.build_district_index(
            {"relation/101": {
                "type": "Polygon", "coordinates": [[[0, 0], [0.5, 0], [0.5, 1],
                                                           [0, 1], [0, 0]]]},
             "relation/102": {
                "type": "Polygon", "coordinates": [[[0.5, 0], [1, 0], [1, 1],
                                                           [0.5, 1], [0.5, 0]]]}},
            {"relation/101": "01", "relation/102": "01"},
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_disk_backed_way_locations_and_node_points_are_attributed(self):
        result = scan.collect_district_leads(self.pbf, self.index)
        leads = result["leads_by_district"]["relation/101"]
        self.assertEqual({lead["id"] for lead in leads},
                         {"node/50", "way/901", "relation/903"})
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["overflow_districts"], frozenset())
        self.assertEqual(result["unassigned_count"], 0)

    def test_district_over_limit_is_flagged_without_truncation_as_success(self):
        result = scan.collect_district_leads(
            self.pbf, self.index, max_district_leads=2,
        )
        self.assertEqual(result["overflow_districts"], frozenset({"relation/101"}))
        self.assertEqual(len(result["leads_by_district"]["relation/101"]), 2)
        self.assertEqual(result["candidate_count"], 3)

    def test_invalid_closed_way_uses_source_line_for_unambiguous_attribution(self):
        import osmium
        pbf = Path(self.temp_dir.name) / "self-intersecting.osm.pbf"
        header = osmium.io.Header()
        header.set("osmosis_replication_timestamp", "2026-11-27T00:00:00Z")
        # A bow-tie ring is invalid as a polygon. Its actual OSM line is valid,
        # and its representative point remains unambiguously in district 101.
        with osmium.SimpleWriter(pbf, header=header) as writer:
            for node_id, xy in ((11, (.10, .10)), (12, (.30, .30)),
                                (13, (.10, .30)), (14, (.30, .10))):
                writer.add_node(osmium.osm.mutable.Node(id=node_id, location=xy))
            writer.add_way(osmium.osm.mutable.Way(
                id=904, nodes=[11, 12, 13, 14, 11],
                tags={"name": "Invalid Shape Florist", "shop": "florist"},
            ))
        result = scan.collect_district_leads(pbf, self.index)
        self.assertEqual(result["leads_by_district"]["relation/101"][0]["id"], "way/904")

    def test_invalid_closed_way_crossing_shared_boundary_fails_closed(self):
        class _Location:
            def __init__(self, lon, lat):
                self.lon, self.lat = lon, lat
            def valid(self): return True
        class _Node:
            def __init__(self, lon, lat): self.location = _Location(lon, lat)
        class _Way:
            id = 905
            def is_node(self): return False
            def is_way(self): return True
            nodes = [_Node(.4, .4), _Node(.6, .6), _Node(.4, .6),
                     _Node(.6, .4), _Node(.4, .4)]
        with self.assertRaisesRegex(ValueError, "crosses or ambiguously"):
            scan._object_point(_Way(), {"area": "yes"}, self.index)


class AttemptRecoveryTests(unittest.TestCase):
    def test_only_pbf_owned_orphan_attempts_are_finalized(self):
        registry = {"provinces": [
            {"code": "01", "status": "running", "attempts": [
                {"attempt_id": "pbf-123456-1-01", "finished_at": None}]},
            {"code": "02", "status": "partial", "attempts": []},
        ]}
        calls = []
        with patch.object(scan, "finish_attempt",
                          side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
            recovered = scan.recover_orphaned_attempts(
                object(), registry, finished_at="2026-11-28T10:00:00+00:00")
        self.assertEqual(recovered, [("01", "pbf-123456-1-01")])
        self.assertEqual(len(calls), 1)

    def test_foreign_running_attempt_is_not_auto_recovered(self):
        registry = {"provinces": [{
            "code": "01", "status": "running", "attempts": [
                {"attempt_id": "manual-other-worker", "finished_at": None}],
        }]}
        with self.assertRaisesRegex(RuntimeError, "another scanner"):
            scan.recover_orphaned_attempts(
                object(), registry, finished_at="2026-11-28T10:00:00+00:00")


class SameSnapshotNoopTests(unittest.TestCase):
    def test_same_verified_digest_skips_geometry_and_business_pbf_parsing(self):
        digest = "e" * 64
        state = {"code": "01", "status": "completed", "completed_items": {
            "relation/101": {"source_sha256": digest},
        }}
        registry = {"provinces": [state]}
        plans = {"01": {"work_item_ids": ["relation/101"], "excluded_item_ids": []}}
        inventory = {
            "district_ids": frozenset({"relation/101"}),
            "provinces": {"01": {"district_ids": ("relation/101",)}},
        }
        class _Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        class _Connection:
            def cursor(self): return _Cursor()

        with (
            patch.object(scan, "safe_metadata", return_value=(
                "pbf-123456-1", digest, datetime(2026, 11, 27, tzinfo=timezone.utc),
                Path("unused.pbf"), scan.PBF_SOURCE_URL)),
            patch.object(scan, "load_inventory", return_value=inventory),
            patch.object(scan, "compile_province_plans", return_value=plans),
            patch.object(scan, "verify_pbf_snapshot", return_value={
                "sha256": digest, "snapshot_timestamp": "2026-11-27T00:00:00Z",
            }),
            patch.object(scan, "_acquire_worker_lock"),
            patch.object(scan, "_release_worker_lock"),
            patch.object(scan, "_require_review_queue"),
            patch.object(scan, "read", return_value=registry),
            patch.object(scan, "_validate_registry", return_value={"01": state}),
            patch.object(scan, "extract_district_geometries") as extract,
            patch.object(scan, "collect_district_leads") as collect,
        ):
            result = scan.run(
                env={}, connection=_Connection(), output=lambda _line: None,
                now=datetime(2026, 11, 28, tzinfo=timezone.utc),
            )
        self.assertTrue(result["skipped_same_snapshot"])
        self.assertEqual(result["district_receipts"], 1)
        extract.assert_not_called()
        collect.assert_not_called()


class NeonConnectionLifecycleTests(unittest.TestCase):
    def test_neon_lock_is_released_and_connection_closed_during_pbf_parse(self):
        digest = "f" * 64
        source_at = "2026-11-27T00:00:00Z"
        pending = {"code": "01", "status": "pending", "completed_items": {}}
        registry = {"provinces": [pending]}
        plans = {"01": {"work_item_ids": ["relation/101"], "excluded_item_ids": []}}
        inventory = {
            "district_ids": frozenset({"relation/101"}),
            "provinces": {"01": {"district_ids": ("relation/101",)}},
        }
        events = []

        class _Connection:
            def __init__(self, label): self.label, self.closed = label, False
            def close(self):
                self.closed = True
                events.append(("close", self.label))

        all_connections = [_Connection("first"), _Connection("second")]
        connection_queue = list(all_connections)
        def connect(_url): return connection_queue.pop(0)
        def acquire(conn): events.append(("acquire", conn.label))
        def release(conn): events.append(("release", conn.label))
        def extract(*_args, **_kwargs):
            self.assertTrue(all_connections[0].closed)
            events.append(("extract", None))
            return {"source": {"snapshot_timestamp": source_at}, "geometries": {}}
        def collect(*_args, **_kwargs):
            self.assertTrue(all_connections[0].closed)
            events.append(("collect", None))
            return {"leads_by_district": {}, "overflow_districts": frozenset(),
                    "candidate_count": 0, "unassigned_count": 0}
        def begin(conn, _code, **kwargs):
            events.append(("begin", conn.label))
            return {"provinces": [{
                "code": "01", "status": "running", "completed_items": {},
                "attempts": [{"attempt_id": "pbf-123456-1-01",
                              "source_sha256": digest,
                              "planned_item_ids": ["relation/101"]}],
            }]}

        with (
            patch.object(scan, "safe_metadata", return_value=(
                "pbf-123456-1", digest, datetime(2026, 11, 27, tzinfo=timezone.utc),
                Path("unused.pbf"), scan.PBF_SOURCE_URL)),
            patch.object(scan, "load_inventory", return_value=inventory),
            patch.object(scan, "compile_province_plans", return_value=plans),
            patch.object(scan, "verify_pbf_snapshot", return_value={"snapshot_timestamp": source_at}),
            patch("leadhunter.review_private.connect_private_database", side_effect=connect),
            patch.object(scan, "_acquire_worker_lock", side_effect=acquire),
            patch.object(scan, "_release_worker_lock", side_effect=release),
            patch.object(scan, "_require_review_queue"),
            patch.object(scan, "read", return_value=registry),
            patch.object(scan, "_validate_registry", return_value={"01": pending}),
            patch.object(scan, "recover_orphaned_attempts", return_value=[]),
            patch.object(scan, "extract_district_geometries", side_effect=extract),
            patch.object(scan, "build_district_index", return_value={}),
            patch.object(scan, "collect_district_leads", side_effect=collect),
            patch.object(scan, "begin_attempt", side_effect=begin),
            patch.object(scan, "commit_district_batch", return_value={"new_leads": 0,
                                                                        "changed_existing": 0}),
            patch.object(scan, "finish_attempt"),
        ):
            result = scan.run(
                env={"REVIEW_DATABASE_URL": "postgresql://redacted"},
                output=lambda _line: None,
                now=datetime(2026, 11, 28, tzinfo=timezone.utc),
            )
        self.assertEqual(result["district_receipts"], 0)
        self.assertEqual([event[0] for event in events[:7]],
                         ["acquire", "release", "close", "extract", "collect", "acquire", "begin"])
        self.assertTrue(all_connections[0].closed)
        self.assertTrue(all_connections[1].closed)


if __name__ == "__main__":
    unittest.main()
