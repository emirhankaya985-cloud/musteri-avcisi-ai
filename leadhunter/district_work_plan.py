"""Compile the pinned OSM-derived inventory into resumable district work.

This is a planner only: it does not extract geometries from PBF, query OSM,
write Neon, or claim any scan receipts. A scan worker must separately resolve
each relation's actual geometry from a checksum-verified source snapshot.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .osm_boundary_manifest import SOURCE_LICENSE, SOURCE_LICENSE_URL, SOURCE_REPOSITORY
from .province_coverage import PROVINCES

DEFAULT_MANIFEST = Path("data/osm_boundary_manifest_v2026.11.0.json")
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
RELATION = re.compile(r"relation/[1-9][0-9]*\Z", re.ASCII)


def load_inventory(path=DEFAULT_MANIFEST):
    """Read and validate the exact committed boundary inventory bytes."""
    raw = Path(path).read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("District inventory is not UTF-8 JSON") from None
    if (not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("manifest_type") != "osm_derived_non_official_admin_boundaries"
            or manifest.get("official_boundary") is not False):
        raise ValueError("District inventory must be the declared non-official OSM manifest")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("District inventory source metadata is missing")
    tag = source.get("release_tag")
    expected_url = f"https://raw.githubusercontent.com/topografya/veri/{tag}/sinirlar/ozet.json"
    if (source.get("repository") != SOURCE_REPOSITORY
            or source.get("license") != SOURCE_LICENSE
            or source.get("license_url") != SOURCE_LICENSE_URL
            or source.get("summary_url") != expected_url
            or not isinstance(tag, str)
            or not re.fullmatch(r"v20[0-9]{2}\.[0-9]{2}\.[0-9]+", tag)
            or not isinstance(source.get("tag_commit_sha"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", source["tag_commit_sha"])
            or not isinstance(source.get("summary_sha256"), str)
            or not SHA256.fullmatch(source["summary_sha256"])):
        raise ValueError("District inventory source identity or license is invalid")
    provinces = manifest.get("provinces")
    if (manifest.get("province_count") != 81 or not isinstance(provinces, list)
            or len(provinces) != 81):
        raise ValueError("District inventory must contain exactly 81 provinces")
    expected = {code: name for code, name in PROVINCES}
    by_code = {}
    relation_ids = set()
    for province in provinces:
        if not isinstance(province, dict):
            raise ValueError("District inventory province row is invalid")
        code = province.get("code")
        if code not in expected or province.get("name") != expected[code] or code in by_code:
            raise ValueError("District inventory province identity is invalid")
        if not RELATION.fullmatch(str(province.get("relation_id", ""))):
            raise ValueError("District inventory province relation is invalid")
        districts = province.get("districts")
        if not isinstance(districts, list) or not districts:
            raise ValueError("District inventory province has no district relations")
        district_ids = []
        for district in districts:
            if not isinstance(district, dict):
                raise ValueError("District inventory district row is invalid")
            relation_id = district.get("relation_id")
            if (not isinstance(relation_id, str) or not RELATION.fullmatch(relation_id)
                    or relation_id in relation_ids
                    or not isinstance(district.get("name"), str)
                    or not district["name"].strip()):
                raise ValueError("District relation identity is invalid or duplicated")
            relation_ids.add(relation_id)
            district_ids.append(relation_id)
        if province.get("district_count") != len(district_ids):
            raise ValueError("Province district count disagrees with its relation list")
        by_code[code] = {**province, "district_ids": tuple(sorted(district_ids))}
    if set(by_code) != set(expected) or manifest.get("district_count") != len(relation_ids):
        raise ValueError("District inventory totals are incomplete or inconsistent")
    if not 950 <= len(relation_ids) <= 1000:
        raise ValueError("District relation inventory is outside the pinned release QA range")
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "provinces": by_code,
        "district_ids": frozenset(relation_ids),
    }


def compile_province_plans(path=DEFAULT_MANIFEST):
    """Return 81 immutable ledger-plan payloads keyed by province code.

    Each plan is bound to the upstream boundary-summary SHA-256 and URL;
    excluded IDs remain empty. The list describes work only and marks none
    of it complete. `source_sha256` preserves the ledger's existing schema.
    """
    inventory = load_inventory(path)
    source = inventory["manifest"]["source"]
    result = {}
    for code, _ in PROVINCES:
        province = inventory["provinces"][code]
        result[code] = {
            "province_name": province["name"],
            "source_url": source["summary_url"],
            "source_sha256": source["summary_sha256"],
            "work_item_ids": list(province["district_ids"]),
            "excluded_item_ids": [],
            "boundary_manifest_sha256": inventory["manifest_sha256"],
            "official_boundary": False,
            "scan_started": False,
            "completed_items": 0,
        }
    return result


def next_district_batch(work_item_ids, completed_item_ids, *, limit=10):
    """Pick a deterministic, bounded suffix of district IDs still unreceipted."""
    items = list(work_item_ids)
    completed = set(completed_item_ids)
    if (not 1 <= limit <= 25 or not items
            or any(not isinstance(item, str) or not RELATION.fullmatch(item) for item in items)
            or len(items) != len(set(items))
            or any(not isinstance(item, str) or not RELATION.fullmatch(item) for item in completed)
            or not completed <= set(items)):
        raise ValueError("District batch plan or completed receipts are invalid")
    remaining = [item for item in items if item not in completed]
    return remaining[:limit]
