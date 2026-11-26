"""Fail-closed inventory manifest for a pinned OSM-derived boundary release.

The manifest contains province/district relation IDs and province bounding
boxes, not official cadastral boundaries or permission to call the data
official. Geometry scanning and CRM writes are intentionally outside this
module. The pinned Topografya source is ODbL and explicitly non-official.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime

from .province_coverage import PROVINCES

SCHEMA_VERSION = 1
SOURCE_REPOSITORY = "https://github.com/topografya/veri"
SOURCE_LICENSE = "ODbL 1.0"
SOURCE_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
SOURCE_README = "https://github.com/topografya/veri#t%C3%BCrkiye-il-ve-il%C3%A7e-s%C4%B1n%C4%B1rlar%C4%B1"
_RELEASE = re.compile(r"v(20[0-9]{2})\.([0-9]{2})\.([0-9]+)\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


def _relation_id(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive OSM relation ID")
    return f"relation/{value}"


def _bbox(value, label):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{label} must contain four WGS84 coordinates")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError(f"{label} contains an invalid coordinate")
    west, south, east, north = map(float, value)
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError(f"{label} is outside WGS84 bounds or reversed")
    return [west, south, east, north]


def _source_date(value):
    if not isinstance(value, str):
        raise ValueError("Source data date is missing")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Source data date must be an ISO calendar date") from None
    return value


def build_manifest(raw_summary: bytes, *, release_tag: str, tag_commit_sha: str) -> dict:
    """Validate the entire pinned summary and return an immutable inventory.

    ``tag_commit_sha`` must come from the source repository's tag metadata.
    The SHA-256 in the result binds the exact downloaded summary bytes.
    """
    if not isinstance(raw_summary, bytes) or not raw_summary:
        raise ValueError("Boundary summary must be non-empty bytes")
    release_match = (_RELEASE.fullmatch(release_tag)
                     if isinstance(release_tag, str) else None)
    if not release_match or not 1 <= int(release_match.group(2)) <= 12:
        raise ValueError("A pinned Topografya release tag is required")
    if not isinstance(tag_commit_sha, str) or not _SHA.fullmatch(tag_commit_sha):
        raise ValueError("Pinned source commit must be a full lowercase Git SHA")
    try:
        summary = json.loads(raw_summary.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Boundary summary is not valid UTF-8 JSON") from None
    if not isinstance(summary, dict):
        raise ValueError("Boundary summary must be a JSON object")
    if summary.get("lisans") != SOURCE_LICENSE:
        raise ValueError("Boundary source license is missing or unsupported")
    if summary.get("lisans_url") != SOURCE_LICENSE_URL:
        raise ValueError("Boundary source license URL does not match ODbL 1.0")
    source_label = str(summary.get("kaynak") or "").casefold()
    if "openstreetmap" not in source_label:
        raise ValueError("Boundary source does not identify OpenStreetMap")
    expected = PROVINCES
    entries = summary.get("iller")
    if summary.get("il_sayisi") != 81 or not isinstance(entries, list) or len(entries) != 81:
        raise ValueError("Boundary source must contain exactly 81 provinces")

    provinces = []
    seen_province_codes = set()
    seen_relations = set()
    district_count = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Province entry must be an object")
        code, name = item.get("kod"), item.get("ad")
        if not isinstance(code, str) or (code, name) not in expected:
            raise ValueError("Province code/name is unknown or ambiguous")
        if code in seen_province_codes:
            raise ValueError("Duplicate province code")
        seen_province_codes.add(code)
        province_relation = _relation_id(item.get("osm_id"), f"Province {code}")
        if province_relation in seen_relations:
            raise ValueError("OSM relation ID is duplicated")
        seen_relations.add(province_relation)
        bounds = _bbox(item.get("bbox"), f"Province {code} bbox")
        raw_districts = item.get("ilceler")
        if not isinstance(raw_districts, list) or not raw_districts:
            raise ValueError(f"Province {code} has no district relations")
        districts = []
        local_names = set()
        for district in raw_districts:
            if not isinstance(district, dict):
                raise ValueError(f"Province {code} contains an invalid district entry")
            district_name = district.get("ad")
            if not isinstance(district_name, str) or not district_name.strip():
                raise ValueError(f"Province {code} contains an unnamed district")
            relation = _relation_id(district.get("osm_id"), f"District in province {code}")
            if relation in seen_relations:
                raise ValueError("OSM relation ID is duplicated or assigned ambiguously")
            seen_relations.add(relation)
            # Names are descriptive only. IDs, not names, key all scan work.
            if district_name.casefold() in local_names:
                raise ValueError(f"Province {code} has duplicate district names")
            local_names.add(district_name.casefold())
            districts.append({"relation_id": relation, "name": district_name.strip()})
        districts.sort(key=lambda row: row["relation_id"])
        district_count += len(districts)
        provinces.append({
            "code": code,
            "name": name,
            "relation_id": province_relation,
            "bbox_wgs84": bounds,
            "district_count": len(districts),
            "districts": districts,
        })

    if seen_province_codes != {code for code, _ in expected}:
        raise ValueError("Boundary source is missing province codes")
    reported_districts = summary.get("ilce_sayisi")
    if type(reported_districts) is not int or reported_districts != district_count:
        raise ValueError("District relation count does not match the published total")
    # The source's own release QA requires 950-1000 districts. This catches
    # partial files without assuming one permanent Turkish district count.
    if not 950 <= district_count <= 1000:
        raise ValueError("District count is outside the source's documented QA range")

    provinces.sort(key=lambda row: row["code"])
    source_url = (f"https://raw.githubusercontent.com/topografya/veri/"
                  f"{release_tag}/sinirlar/ozet.json")
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "osm_derived_non_official_admin_boundaries",
        "official_boundary": False,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "release_tag": release_tag,
            "tag_commit_sha": tag_commit_sha,
            "summary_url": source_url,
            "summary_sha256": hashlib.sha256(raw_summary).hexdigest(),
            "source_data_date": _source_date(summary.get("veri_tarihi")),
            "generated_at": summary.get("derleme_zamani"),
            "license": SOURCE_LICENSE,
            "license_url": SOURCE_LICENSE_URL,
            "attribution": "© OpenStreetMap contributors",
            "readme_url": SOURCE_README,
        },
        "province_count": len(provinces),
        "district_count": district_count,
        "provinces": provinces,
    }
