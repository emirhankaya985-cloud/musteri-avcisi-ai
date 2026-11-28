"""Offline synthetic benchmark for national district PBF scan stages.

Generates a temporary, country-shaped OSM PBF and measures the production
district geometry extractor, index builder, and business attribution scanner
separately. No network, database, customer email, or production data is used.
Timings characterize this synthetic fixture only; they are not a full-country
runtime estimate.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import osmium
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from leadhunter.district_pbf_geometry import extract_district_geometries
from leadhunter.national_district_scan import (
    DISTRICT_QUERY_BATCH_SIZE,
    build_district_index,
    collect_district_leads,
    unique_district_for_point,
    _query_districts_for_valid_points,
)


def _make_fixture(path: Path, district_count: int, irrelevant_count: int,
                  business_count: int) -> tuple[list[str], dict[str, str]]:
    """Write disjoint district multipolygons and named tagged point features."""
    header = osmium.io.Header()
    snapshot_at = datetime.now(timezone.utc).replace(microsecond=0)
    header.set("osmosis_replication_timestamp", snapshot_at.isoformat().replace("+00:00", "Z"))

    columns = 32
    districts: list[tuple[str, str, int, int, float, float]] = []
    for offset in range(district_count):
        col, row = offset % columns, offset // columns
        relation_id = f"relation/{1_000_000 + offset}"
        way_id = 2_000_000 + offset
        first_node_id = 10_000_000 + offset * 4
        lon, lat = 26.0 + col * 0.02, 36.0 + row * 0.02
        districts.append((relation_id, str(1 + offset // 32), way_id,
                          first_node_id, lon, lat))

    with osmium.SimpleWriter(path, header=header) as writer:
        for relation_id, _province, _way_id, first_node, lon, lat in districts:
            for node_id, point in zip(
                range(first_node, first_node + 4),
                ((lon, lat), (lon + 0.01, lat), (lon + 0.01, lat + 0.01), (lon, lat + 0.01)),
            ):
                writer.add_node(osmium.osm.mutable.Node(id=node_id, location=point))

        next_node = 20_000_000
        for offset in range(irrelevant_count):
            district = districts[offset % district_count]
            lon, lat = district[4] + 0.005, district[5] + 0.005
            writer.add_node(osmium.osm.mutable.Node(
                id=next_node + offset, location=(lon, lat),
                tags={"name": f"Unrelated place {offset}", "amenity": "bench"},
            ))
        business_start = next_node + irrelevant_count
        for offset in range(business_count):
            district = districts[offset % district_count]
            lon, lat = district[4] + 0.005, district[5] + 0.005
            writer.add_node(osmium.osm.mutable.Node(
                id=business_start + offset, location=(lon, lat),
                tags={"name": f"Synthetic florist {offset}", "shop": "florist"},
            ))

        for _relation_id, _province, way_id, first_node, *_ in districts:
            writer.add_way(osmium.osm.mutable.Way(
                id=way_id,
                nodes=[first_node, first_node + 1, first_node + 2,
                       first_node + 3, first_node],
            ))
        for relation_id, _province, way_id, *_ in districts:
            writer.add_relation(osmium.osm.mutable.Relation(
                id=int(relation_id.split("/")[1]),
                members=[("w", way_id, "outer")],
                tags={"type": "multipolygon", "boundary": "administrative",
                      "admin_level": "6", "name": relation_id},
            ))

    relation_ids = [district[0] for district in districts]
    district_to_province = {district[0]: district[1] for district in districts}
    return relation_ids, district_to_province


def benchmark(district_count: int, irrelevant_count: int,
              business_count: int) -> dict[str, float | int]:
    if (not 1 <= district_count <= 1000 or irrelevant_count < 0
            or not 1 <= business_count <= 200_000):
        raise ValueError("districts must be 1..1000, irrelevant >= 0, and businesses 1..200000")

    with tempfile.TemporaryDirectory(prefix="national-scan-stages-") as directory:
        pbf = Path(directory) / "synthetic-country.osm.pbf"
        build_started = time.perf_counter()
        relation_ids, district_to_province = _make_fixture(
            pbf, district_count, irrelevant_count, business_count,
        )
        fixture_seconds = time.perf_counter() - build_started
        digest = hashlib.sha256(pbf.read_bytes()).hexdigest()
        now = datetime.now(timezone.utc) + timedelta(minutes=1)

        started = time.perf_counter()
        extraction = extract_district_geometries(
            pbf, relation_ids, digest, now=now,
        )
        geometry_seconds = time.perf_counter() - started

        started = time.perf_counter()
        index = build_district_index(extraction["geometries"], district_to_province)
        index_seconds = time.perf_counter() - started

        points = []
        for offset in range(business_count):
            district = offset % district_count
            col, row = district % 32, district // 32
            points.append(Point(26.0 + col * 0.02 + 0.005,
                                36.0 + row * 0.02 + 0.005))

        started = time.perf_counter()
        reference_ids = [unique_district_for_point(point, index) for point in points]
        reference_lookup_seconds = time.perf_counter() - started
        started = time.perf_counter()
        indexed_ids = []
        for offset in range(0, len(points), DISTRICT_QUERY_BATCH_SIZE):
            indexed_ids.extend(_query_districts_for_valid_points(
                points[offset:offset + DISTRICT_QUERY_BATCH_SIZE], index,
            ))
        indexed_lookup_seconds = time.perf_counter() - started
        if reference_ids != indexed_ids:
            raise RuntimeError("Indexed STRtree attribution changed district assignments")

        started = time.perf_counter()
        result = collect_district_leads(pbf, index)
        attribution_seconds = time.perf_counter() - started

        if len(extraction["geometries"]) != district_count:
            raise RuntimeError("Synthetic geometry extraction lost district boundaries")
        if result["candidate_count"] != business_count:
            raise RuntimeError("Synthetic attribution changed the candidate count")
        if result["unassigned_count"] != 0:
            raise RuntimeError("Synthetic attribution left in-boundary businesses unassigned")
        if sum(map(len, result["leads_by_district"].values())) != business_count:
            raise RuntimeError("Synthetic district assignment lost business records")

        return {
            "districts": district_count,
            "irrelevant": irrelevant_count,
            "businesses": business_count,
            "pbf_bytes": pbf.stat().st_size,
            "fixture_seconds": fixture_seconds,
            "geometry_seconds": geometry_seconds,
            "index_seconds": index_seconds,
            "reference_lookup_seconds": reference_lookup_seconds,
            "indexed_lookup_seconds": indexed_lookup_seconds,
            "attribution_seconds": attribution_seconds,
            "candidates": result["candidate_count"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--districts", type=int, default=973)
    parser.add_argument("--irrelevant", type=int, default=100_000)
    parser.add_argument("--businesses", type=int, default=5_000)
    args = parser.parse_args()
    result = benchmark(args.districts, args.irrelevant, args.businesses)
    print(
        "NATIONAL_SCAN_STAGE_BENCHMARK: "
        f"districts={result['districts']}; irrelevant={result['irrelevant']}; "
        f"businesses={result['businesses']}; pbf_bytes={result['pbf_bytes']}; "
        f"fixture_s={result['fixture_seconds']:.3f}; "
        f"geometry_s={result['geometry_seconds']:.3f}; "
        f"index_s={result['index_seconds']:.3f}; "
        f"lookup_reference_s={result['reference_lookup_seconds']:.3f}; "
        f"lookup_indexed_s={result['indexed_lookup_seconds']:.3f}; "
        f"attribution_s={result['attribution_seconds']:.3f}; "
        f"candidates={result['candidates']}; full_country_runtime_estimate=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

