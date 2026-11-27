"""Extract pinned OSM district relation geometries from a local PBF snapshot.

This module is deliberately offline and has no database or discovery side
effects. It accepts an expected relation-ID set and returns only GeoJSON
geometry plus source receipts; callers must manage scan progress separately.
"""
from __future__ import annotations

import hashlib
from itertools import islice
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_RELATION = re.compile(r"relation/([1-9][0-9]*)\Z", re.ASCII)
_MAX_EXPECTED_RELATIONS = 1000
_DEFAULT_MAX_PBF_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_MAX_TOTAL_COORDINATES = 2_000_000
_DEFAULT_MAX_RELATION_COORDINATES = 250_000
_LOCATION_STORAGE = "sparse_file_array"


def _relation_numbers(relation_ids):
    """Validate and normalize a bounded, duplicate-free relation-ID iterable."""
    if isinstance(relation_ids, (str, bytes)):
        raise ValueError("Expected district IDs must be an iterable of relation/id strings")
    try:
        values = list(islice(iter(relation_ids), _MAX_EXPECTED_RELATIONS + 1))
    except TypeError:
        raise ValueError("Expected district IDs must be an iterable of relation/id strings") from None
    if len(values) > _MAX_EXPECTED_RELATIONS:
        raise ValueError("Expected district relation set must contain 1 to 1000 IDs")
    if not 1 <= len(values) <= _MAX_EXPECTED_RELATIONS:
        raise ValueError("Expected district relation set must contain 1 to 1000 IDs")
    if any(not isinstance(value, str) or not _RELATION.fullmatch(value) for value in values):
        raise ValueError("Expected district IDs must use the relation/<positive integer> form")
    if len(values) != len(set(values)):
        raise ValueError("Expected district relation IDs contain duplicates")
    return {int(_RELATION.fullmatch(value).group(1)): value for value in values}


def _snapshot_timestamp(pbf_path):
    """Read the replication timestamp from the local PBF header."""
    try:
        import osmium
    except ImportError as exc:  # pragma: no cover - depends on runner setup
        raise RuntimeError("Pyosmium is required to inspect the local PBF") from exc

    reader = osmium.io.Reader(str(pbf_path))
    try:
        value = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("PBF header has no replication timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("PBF replication timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("PBF replication timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pbf_snapshot(pbf_path, expected_sha256, *, now=None,
                        max_age=timedelta(days=10),
                        max_pbf_bytes=_DEFAULT_MAX_PBF_BYTES):
    """Validate a local PBF checksum, embedded date, and freshness without parsing geometry."""
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("Expected PBF SHA-256 must be 64 lowercase hexadecimal characters")
    if (not isinstance(max_pbf_bytes, int) or isinstance(max_pbf_bytes, bool)
            or max_pbf_bytes <= 0):
        raise ValueError("PBF size bound must be a positive integer")
    if not isinstance(max_age, timedelta) or max_age <= timedelta(0):
        raise ValueError("Snapshot maximum age must be a positive timedelta")
    path = Path(pbf_path)
    if not path.is_file():
        raise ValueError("Local PBF snapshot does not exist")
    before_stat = path.stat()
    if before_stat.st_size <= 0 or before_stat.st_size > max_pbf_bytes:
        raise ValueError("Local PBF snapshot is empty or exceeds the configured size bound")
    actual_sha256 = _sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError("Local PBF snapshot SHA-256 does not match the expected digest")
    snapshot_at = _snapshot_timestamp(path)
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if snapshot_at > current + timedelta(minutes=5):
        raise ValueError("PBF snapshot timestamp is in the future")
    if current - snapshot_at > max_age:
        raise ValueError("PBF snapshot is stale")
    after_stat = path.stat()
    if (after_stat.st_size != before_stat.st_size
            or after_stat.st_mtime_ns != before_stat.st_mtime_ns
            or _sha256_file(path) != expected_sha256):
        raise ValueError("Local PBF snapshot changed while its source metadata was being checked")
    return {
        "sha256": actual_sha256,
        "snapshot_timestamp": snapshot_at.isoformat().replace("+00:00", "Z"),
        "size_bytes": before_stat.st_size,
    }


def _validated_geojson_ring(ring, *, relation_id, coordinate_budget):
    coordinates = []
    for node in ring:
        location = node.location
        if not location.valid():
            raise ValueError(f"District {relation_id} contains a way node without a location")
        lon, lat = float(location.lon), float(location.lat)
        if (not math.isfinite(lon) or not math.isfinite(lat)
                or not -180 <= lon <= 180 or not -90 <= lat <= 90):
            raise ValueError(f"District {relation_id} contains an invalid coordinate")
        coordinates.append([lon, lat])
        if len(coordinates) > coordinate_budget:
            raise ValueError(f"District {relation_id} exceeds the coordinate limit")
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        raise ValueError(f"District {relation_id} has an open or invalid polygon ring")
    return coordinates


def _area_geometry(area, relation_id, *, max_relation_coordinates, remaining_coordinates):
    """Convert a Pyosmium assembled relation Area into bounded GeoJSON coords."""
    polygons = []
    count = 0
    for outer in area.outer_rings():
        outer_coords = _validated_geojson_ring(
            outer, relation_id=relation_id,
            coordinate_budget=min(max_relation_coordinates - count, remaining_coordinates - count),
        )
        count += len(outer_coords)
        polygon = [outer_coords]
        for inner in area.inner_rings(outer):
            inner_coords = _validated_geojson_ring(
                inner, relation_id=relation_id,
                coordinate_budget=min(max_relation_coordinates - count, remaining_coordinates - count),
            )
            count += len(inner_coords)
            polygon.append(inner_coords)
        polygons.append(polygon)
    if not polygons:
        raise ValueError(f"District {relation_id} has no polygon geometry")
    return {"type": "MultiPolygon", "coordinates": polygons}, count


def extract_district_geometries(
    pbf_path,
    expected_relation_ids,
    expected_sha256,
    *,
    now=None,
    max_age=timedelta(days=10),
    max_pbf_bytes=_DEFAULT_MAX_PBF_BYTES,
    max_total_coordinates=_DEFAULT_MAX_TOTAL_COORDINATES,
    max_relation_coordinates=_DEFAULT_MAX_RELATION_COORDINATES,
):
    """Extract every expected district geometry from a verified local PBF.

    The PBF must already exist locally. Its SHA-256 is checked before and
    after parsing, and its header timestamp must be fresh. Pyosmium's
    ``sparse_file_array`` location store keeps node coordinates disk-backed;
    relation geometry is produced by Pyosmium's multipolygon area assembler.

    Returns a mapping with only ``geometries`` and ``source`` receipts. No
    business records, database writes, scan-completion markers, or network
    requests are made.
    """
    ids_by_number = _relation_numbers(expected_relation_ids)
    if (not isinstance(max_pbf_bytes, int) or isinstance(max_pbf_bytes, bool)
            or max_pbf_bytes <= 0
            or not isinstance(max_total_coordinates, int) or isinstance(max_total_coordinates, bool)
            or max_total_coordinates <= 0
            or not isinstance(max_relation_coordinates, int) or isinstance(max_relation_coordinates, bool)
            or max_relation_coordinates <= 0
            or max_relation_coordinates > max_total_coordinates):
        raise ValueError("PBF and coordinate bounds must be positive integers")
    path = Path(pbf_path)
    source = verify_pbf_snapshot(path, expected_sha256, now=now, max_age=max_age,
                                 max_pbf_bytes=max_pbf_bytes)
    before_stat = path.stat()
    actual_sha256 = source["sha256"]
    snapshot_at = _snapshot_timestamp(path)

    try:
        import osmium
    except ImportError as exc:  # pragma: no cover - depends on runner setup
        raise RuntimeError("Pyosmium is required to extract PBF geometries") from exc

    relation_filter = osmium.filter.IdFilter(ids_by_number).enable_for(osmium.osm.RELATION)
    processor = (osmium.FileProcessor(str(path))
                 .with_locations(_LOCATION_STORAGE)
                 .with_areas(relation_filter))
    geometries = {}
    coordinate_count = 0
    for obj in processor:
        if not obj.is_area():
            continue
        area = obj
        if area.from_way():
            continue
        number = area.orig_id()
        relation_id = f"relation/{number}"
        if number not in ids_by_number:
            raise ValueError(f"PBF produced unexpected district geometry {relation_id}")
        if relation_id in geometries:
            raise ValueError(f"PBF produced duplicate district geometry {relation_id}")
        remaining = max_total_coordinates - coordinate_count
        if remaining <= 0:
            raise ValueError("District geometry output exceeds the total coordinate limit")
        geometry, count = _area_geometry(
            area, relation_id,
            max_relation_coordinates=max_relation_coordinates,
            remaining_coordinates=remaining,
        )
        coordinate_count += count
        geometries[relation_id] = geometry

    actual_ids = set(geometries)
    expected_ids = set(ids_by_number.values())
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"District geometry relation set mismatch; missing={missing[:5]}, extra={extra[:5]}")

    after_stat = path.stat()
    if (after_stat.st_size != before_stat.st_size
            or after_stat.st_mtime_ns != before_stat.st_mtime_ns
            or _sha256_file(path) != expected_sha256):
        raise ValueError("Local PBF snapshot changed while geometries were being extracted")

    return {
        "geometries": geometries,
        "source": {
            "sha256": actual_sha256,
            "snapshot_timestamp": snapshot_at.isoformat().replace("+00:00", "Z"),
            "relation_count": len(geometries),
            "coordinate_count": coordinate_count,
            "location_storage": _LOCATION_STORAGE,
            "official_boundary": False,
        },
    }
