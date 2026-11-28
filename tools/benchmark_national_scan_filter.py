"""Offline microbenchmark for the national PBF candidate prefilter.

This measures Python-level object delivery and classification only. Both
processors still use Pyosmium's location cache; it is not a full-country PBF
runtime estimate and it performs no network or database access.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from leadhunter import national_district_scan as scan
from leadhunter.core import lead_from_osm


def _make_fixture(path: Path, irrelevant: int, eligible: int) -> None:
    with osmium.SimpleWriter(path) as writer:
        for object_id in range(1, irrelevant + eligible + 1):
            if object_id <= irrelevant:
                tags = {"name": f"Unrelated place {object_id}", "amenity": "bench"}
            else:
                tags = {"name": f"Florist {object_id}", "shop": "florist"}
            writer.add_node(osmium.osm.mutable.Node(
                id=object_id,
                location=(29.0 + (object_id % 1000) / 100_000, 41.0),
                tags=tags,
            ))


def _business_ids(processor) -> set[str]:
    result = set()
    for obj in processor:
        tags = scan._tag_map(obj)
        if not tags.get("name"):
            continue
        kind = "node" if obj.is_node() else "way" if obj.is_way() else "relation"
        lead = lead_from_osm({"type": kind, "id": int(obj.id), "tags": tags})
        if lead is not None:
            result.add(lead["id"])
    return result


def benchmark(irrelevant: int, eligible: int) -> dict[str, float | int | bool]:
    if irrelevant < 0 or eligible < 1:
        raise ValueError("irrelevant must be nonnegative and eligible must be positive")
    with tempfile.TemporaryDirectory(prefix="national-scan-filter-benchmark-") as directory:
        pbf = Path(directory) / "synthetic.osm.pbf"
        _make_fixture(pbf, irrelevant, eligible)

        start = time.perf_counter()
        baseline = _business_ids(
            osmium.FileProcessor(str(pbf)).with_locations("sparse_file_array")
        )
        baseline_seconds = time.perf_counter() - start

        start = time.perf_counter()
        filtered = _business_ids(scan._business_candidate_processor(osmium, pbf))
        filtered_seconds = time.perf_counter() - start

        ids_match = baseline == filtered
        if not ids_match:
            raise RuntimeError("Native prefilter changed the eligible OSM ID set")
        return {
            "objects": irrelevant + eligible,
            "irrelevant": irrelevant,
            "eligible": eligible,
            "baseline_seconds": baseline_seconds,
            "filtered_seconds": filtered_seconds,
            "speedup": baseline_seconds / max(filtered_seconds, 1e-9),
            "ids_match": ids_match,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--irrelevant", type=int, default=100_000)
    parser.add_argument("--eligible", type=int, default=250)
    args = parser.parse_args()
    result = benchmark(args.irrelevant, args.eligible)
    print(
        "NATIONAL_SCAN_FILTER_BENCHMARK: "
        f"objects={result['objects']}; irrelevant={result['irrelevant']}; "
        f"eligible={result['eligible']}; "
        f"baseline_s={result['baseline_seconds']:.3f}; "
        f"filtered_s={result['filtered_seconds']:.3f}; "
        f"speedup={result['speedup']:.2f}x; ids_match={int(result['ids_match'])}; "
        "full_country_runtime_estimate=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
