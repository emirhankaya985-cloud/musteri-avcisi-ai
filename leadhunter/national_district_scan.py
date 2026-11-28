"""Offline, receipt-gated national OSM district business scan.

The worker only reads a checksum-verified local country PBF. It resolves each
eligible OSM object's point-on-surface against the exact pinned district
polygons, then commits one bounded district at a time to private Neon. It
never sends outreach or notifications.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .core import lead_from_osm
from .district_pbf_geometry import extract_district_geometries, verify_pbf_snapshot
from .district_work_plan import compile_province_plans, load_inventory
from .province_coverage_store import (
    begin_attempt,
    commit_district_batch,
    finish_attempt,
    read,
    record_item_result,
)

PBF_SOURCE_URL = "https://download.geofabrik.de/europe/turkey-latest.osm.pbf"
MAX_PBF_BYTES = 2 * 1024 * 1024 * 1024
MAX_DISTRICT_LEADS = 10_000
MAX_TOTAL_LEADS = 200_000
MAX_RELATION_LEADS = 50_000
WORKER_LOCK_ID = 985_402_620
RUN_ID = re.compile(r"[0-9]{6,24}\Z", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
ALLOWED_TAGS = frozenset((
    "name", "shop", "amenity", "website", "contact:website",
    "contact:phone", "phone", "email", "contact:email",
    "addr:street", "addr:housenumber", "addr:district",
))


@contextmanager
def _scan_phase(output, name):
    """Log boundaries and elapsed time for potentially long scan phases."""
    started = time.monotonic()
    output(f"NATIONAL_SCAN_PHASE: name={name}; state=started")
    try:
        yield
    except BaseException:
        output(f"NATIONAL_SCAN_PHASE: name={name}; state=failed; "
               f"elapsed_s={time.monotonic() - started:.1f}")
        raise
    output(f"NATIONAL_SCAN_PHASE: name={name}; state=completed; "
           f"elapsed_s={time.monotonic() - started:.1f}")


def _aware_timestamp(value, label):
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def safe_metadata(env):
    """Validate caller-supplied identity and the locally downloaded source."""
    run_id = str(env.get("GITHUB_RUN_ID", ""))
    run_attempt = str(env.get("GITHUB_RUN_ATTEMPT", "1"))
    digest = str(env.get("OSM_SNAPSHOT_SHA256", "")).lower()
    source_url = str(env.get("OSM_PBF_SOURCE_URL", PBF_SOURCE_URL))
    timestamp = _aware_timestamp(env.get("OSM_SNAPSHOT_TIMESTAMP"), "PBF timestamp")
    pbf_path = Path(env.get("OSM_PBF_FILE", ""))
    if not RUN_ID.fullmatch(run_id) or not re.fullmatch(r"[1-9][0-9]{0,2}", run_attempt):
        raise ValueError("GitHub run ID and attempt are required for deterministic receipts")
    if not SHA256.fullmatch(digest):
        raise ValueError("Expected lowercase PBF SHA-256 is required")
    if source_url != PBF_SOURCE_URL:
        raise ValueError("Only the configured Geofabrik Turkey PBF source is accepted")
    if (env.get("AUTO_MAIL_ENABLED") != "false"
            or env.get("OWNER_APPROVED_MAIL_ENABLED") != "false"
            or env.get("OWNER_NEW_LEAD_NOTICES") != "false"):
        raise ValueError("National discovery requires all outbound mail and notices locked OFF")
    if not pbf_path.is_file() or not 0 < pbf_path.stat().st_size <= MAX_PBF_BYTES:
        raise ValueError("A nonempty local PBF within the 2 GiB bound is required")
    return f"pbf-{run_id}-{run_attempt}", digest, timestamp, pbf_path, source_url


def _shapely():
    try:
        from shapely.geometry import LineString, Point, Polygon, shape
        from shapely.strtree import STRtree
    except ImportError as exc:  # pragma: no cover - depends on runner setup
        raise RuntimeError("Shapely 2.1.2 is required for exact district attribution") from exc
    return Point, LineString, Polygon, shape, STRtree


def build_district_index(geometries, district_to_province):
    """Build a validated Shapely STRtree over the exact district polygons."""
    _Point, _LineString, _Polygon, shape, STRtree = _shapely()
    if not isinstance(geometries, dict) or set(geometries) != set(district_to_province):
        raise ValueError("District geometry and province attribution sets must match exactly")
    relation_ids = sorted(geometries)
    polygons = []
    for relation_id in relation_ids:
        polygon = shape(geometries[relation_id])
        if polygon.geom_type not in ("Polygon", "MultiPolygon") or polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"District boundary {relation_id} is not a valid polygon")
        if polygon.area <= 0:
            raise ValueError(f"District boundary {relation_id} has no area")
        polygons.append(polygon)
    return {
        "relation_ids": relation_ids,
        "provinces": dict(district_to_province),
        "polygons": polygons,
        "tree": STRtree(polygons),
    }


def unique_district_for_point(point, district_index):
    """Return one containing district; ambiguous boundary hits fail closed."""
    if point.is_empty or not point.is_valid:
        raise ValueError("OSM object has an invalid point-on-surface")
    hits = []
    for index in district_index["tree"].query(point):
        offset = int(index)
        if district_index["polygons"][offset].covers(point):
            hits.append(district_index["relation_ids"][offset])
    if len(hits) > 1:
        raise ValueError("OSM object lies in multiple district polygons; refusing ambiguous attribution")
    return hits[0] if hits else None


def _object_point(obj, tags, district_index=None):
    """Resolve an OSM node/way to Shapely's exact point-on-surface."""
    Point, LineString, Polygon, _shape, _STRtree = _shapely()
    if obj.is_node():
        location = obj.location
        if not location.valid():
            raise ValueError("Eligible OSM node has no source location")
        point = Point(float(location.lon), float(location.lat))
        return point
    if not obj.is_way():
        raise ValueError("Eligible OSM object type has no supported source geometry")
    coordinates = []
    for node in obj.nodes:
        location = node.location
        if not location.valid():
            raise ValueError("Eligible OSM way has an unresolved node location")
        lon, lat = float(location.lon), float(location.lat)
        coordinates.append((lon, lat))
    if len(coordinates) < 2:
        raise ValueError("Eligible OSM way has too few resolved vertices")
    is_closed_area = (len(coordinates) >= 4 and coordinates[0] == coordinates[-1]
                      and tags.get("area") != "no")
    if is_closed_area:
        feature = Polygon(coordinates)
    else:
        feature = LineString(coordinates)
    # OSM closed ways can self-intersect or otherwise fail polygon validity.
    # Never repair them by guessing a polygon; use their actual ordered source
    # vertices as a line and let exact district attribution fail closed if the
    # representative point lies on an ambiguous boundary.
    if feature.is_empty:
        raise ValueError(f"Eligible OSM way/{int(obj.id)} has empty source geometry")
    used_invalid_area_fallback = not feature.is_valid and is_closed_area
    if used_invalid_area_fallback:
        feature = LineString(coordinates)
    if feature.is_empty or not feature.is_valid:
        raise ValueError(f"Eligible OSM way/{int(obj.id)} has invalid source geometry")
    point = feature.representative_point()
    if point.is_empty or not point.is_valid:
        raise ValueError(f"Eligible OSM way/{int(obj.id)} has no valid point-on-surface")
    if used_invalid_area_fallback:
        if district_index is None:
            raise ValueError(f"Eligible OSM way/{int(obj.id)} invalid polygon needs district validation")
        line_hits = {
            district_index["relation_ids"][int(index)]
            for index in district_index["tree"].query(feature)
            if district_index["polygons"][int(index)].covers(feature)
        }
        if len(line_hits) != 1 or unique_district_for_point(point, district_index) not in line_hits:
            raise ValueError(f"Eligible OSM way/{int(obj.id)} invalid polygon crosses or ambiguously meets districts")
    return point


def _area_to_shapely(area):
    """Convert a Pyosmium relation area through its official GeoJSON factory."""
    import osmium
    from shapely.geometry import shape

    try:
        raw = osmium.geom.GeoJSONFactory().create_multipolygon(area)
        geom = shape(json.loads(raw))
    except Exception:
        raise ValueError("Eligible OSM relation has no valid assembled multipolygon") from None
    if geom.is_empty or not geom.is_valid or geom.geom_type != "MultiPolygon":
        raise ValueError("Eligible OSM relation has an invalid assembled multipolygon")
    return geom.representative_point()


def _tag_map(obj):
    return {tag.k: tag.v for tag in obj.tags if tag.k in ALLOWED_TAGS}


def _business_candidate_processor(osmium, pbf_path):
    """Keep location caching in C++, but yield only possible named businesses.

    ``with_locations`` runs first so it still sees every node required to
    resolve way geometries. The following native filters prevent unrelated
    tagged OSM objects from crossing into the Python loop.
    """
    from .sector_taxonomy import overpass_tag_selectors

    candidate_types = osmium.osm.NODE | osmium.osm.WAY | osmium.osm.RELATION
    # Match only the keys this scanner already passes through _tag_map so the
    # native prefilter cannot introduce candidates the Python path rejects.
    candidate_tags = tuple(
        (key, value) for key, value in overpass_tag_selectors()
        if key in ALLOWED_TAGS
    )
    return (
        osmium.FileProcessor(str(pbf_path))
        .with_locations("sparse_file_array")
        .with_filter(osmium.filter.KeyFilter("name").enable_for(candidate_types))
        .with_filter(osmium.filter.TagFilter(*candidate_tags).enable_for(candidate_types))
    )


def collect_district_leads(pbf_path, district_index, *,
                          max_total_leads=MAX_TOTAL_LEADS,
                          max_relation_leads=MAX_RELATION_LEADS,
                          max_district_leads=MAX_DISTRICT_LEADS):
    """Read a local PBF and attribute eligible leads to one exact district.

    Node locations are read directly and way vertices come from Pyosmium's
    disk-backed ``with_locations('sparse_file_array')`` cache. Tagged relation
    leads are resolved in a second pass using Pyosmium assembled multipolygons.
    Every object gets a unique point-on-surface owner; ambiguous hits abort the
    whole attribution before any Neon attempt begins.
    """
    try:
        import osmium
    except ImportError as exc:  # pragma: no cover - depends on runner setup
        raise RuntimeError("Pyosmium 4.2.0 is required to scan the local PBF") from exc
    if (not 1 <= max_total_leads <= 1_000_000
            or not 1 <= max_relation_leads <= max_total_leads
            or not 1 <= max_district_leads <= MAX_DISTRICT_LEADS):
        raise ValueError("OSM candidate bounds are invalid")

    leads_by_district = defaultdict(dict)
    overflow_districts = set()
    seen_objects = set()
    relation_leads = {}
    unassigned = 0
    total = 0

    def retain(lead, point):
        nonlocal total, unassigned
        if total >= max_total_leads:
            raise ValueError("Eligible OSM lead count exceeds the configured safety bound")
        total += 1
        relation_id = unique_district_for_point(point, district_index)
        if relation_id is None:
            unassigned += 1
            return
        bucket = leads_by_district[relation_id]
        if lead["id"] in bucket:
            raise ValueError("PBF contains a duplicate eligible OSM object ID")
        if len(bucket) >= max_district_leads:
            overflow_districts.add(relation_id)
            return
        bucket[lead["id"]] = lead

    processor = _business_candidate_processor(osmium, pbf_path)
    for obj in processor:
        if not (obj.is_node() or obj.is_way() or obj.is_relation()):
            continue
        tags = _tag_map(obj)
        if not tags.get("name"):
            continue
        osm_type = "node" if obj.is_node() else "way" if obj.is_way() else "relation"
        lead = lead_from_osm({"type": osm_type, "id": int(obj.id), "tags": tags})
        if lead is None:
            continue
        osm_id = lead["id"]
        if osm_id in seen_objects:
            raise ValueError("PBF contains a duplicate eligible OSM object ID")
        seen_objects.add(osm_id)
        if obj.is_relation():
            if len(relation_leads) >= max_relation_leads:
                raise ValueError("Eligible OSM relation count exceeds the configured safety bound")
            relation_leads[int(obj.id)] = lead
            continue
        retain(lead, _object_point(obj, tags, district_index))

    if relation_leads:
        relation_filter = osmium.filter.IdFilter(relation_leads).enable_for(osmium.osm.RELATION)
        area_processor = (osmium.FileProcessor(str(pbf_path))
                          .with_locations("sparse_file_array")
                          .with_areas(relation_filter))
        resolved_relations = set()
        for obj in area_processor:
            if not obj.is_area() or obj.from_way():
                continue
            relation_number = int(obj.orig_id())
            lead = relation_leads.get(relation_number)
            if lead is None:
                continue
            if relation_number in resolved_relations:
                raise ValueError("PBF contains duplicate multipolygon geometry for a business relation")
            resolved_relations.add(relation_number)
            retain(lead, _area_to_shapely(obj))
        if resolved_relations != set(relation_leads):
            missing = sorted(set(relation_leads) - resolved_relations)
            raise ValueError(f"Eligible business relations lack exact multipolygon geometry: {missing[:5]}")

    return {
        "leads_by_district": {
            relation_id: sorted(leads.values(), key=lambda lead: lead["id"])
            for relation_id, leads in leads_by_district.items()
        },
        "overflow_districts": frozenset(overflow_districts),
        "candidate_count": total,
        "unassigned_count": unassigned,
    }


def _validate_registry(registry, plans, inventory):
    provinces = {row["code"]: row for row in registry["provinces"]}
    if set(provinces) != set(plans):
        raise ValueError("Neon province coverage must contain the exact 81 planned provinces")
    for code, plan in plans.items():
        stored = provinces[code].get("plan")
        if (not isinstance(stored, dict)
                or stored.get("source_url") != plan["source_url"]
                or stored.get("source_sha256") != plan["source_sha256"]
                or set(stored.get("work_item_ids", ())) != set(plan["work_item_ids"])
                or set(stored.get("excluded_item_ids", ())) != set(plan["excluded_item_ids"])):
            raise ValueError(f"Neon plan for province {code} disagrees with the pinned district manifest")
    expected = set(inventory["district_ids"])
    planned = {item for plan in plans.values() for item in plan["work_item_ids"]}
    if planned != expected:
        raise ValueError("Neon province plans do not cover the exact pinned district relation set")
    return provinces


def districts_needing_refresh(province_state, plan, source_sha256):
    """Return planned district IDs whose latest successful receipt is not this PBF."""
    completed = province_state.get("completed_items", {})
    required = set(plan["work_item_ids"]) - set(plan["excluded_item_ids"])
    if set(completed) - set(plan["work_item_ids"]):
        raise ValueError(f"Province {province_state.get('code')} has receipts outside its plan")
    return [relation_id for relation_id in plan["work_item_ids"]
            if relation_id in required
            and (relation_id not in completed
                 or completed[relation_id].get("source_sha256") != source_sha256)]


def _reject_older_snapshot(province_states, plans, source_at):
    """Do not let a delayed older PBF run replace newer district receipts."""
    current_source_at = _aware_timestamp(source_at, "PBF header timestamp")
    for code, plan in plans.items():
        completed = province_states[code].get("completed_items", {})
        for relation_id in set(plan["work_item_ids"]) - set(plan["excluded_item_ids"]):
            receipt = completed.get(relation_id)
            if not receipt or not receipt.get("source_data_at"):
                continue
            receipt_source_at = _aware_timestamp(
                receipt["source_data_at"], f"District {relation_id} receipt timestamp",
            )
            if receipt_source_at > current_source_at:
                raise RuntimeError(
                    f"Verified PBF snapshot is older than the stored receipt for district {relation_id}"
                )


def _finalize_province(connection, code, attempt_id, finished_at):
    finish_attempt(connection, code, attempt_id, finished_at=finished_at)


def _acquire_worker_lock(connection):
    """Hold a session lock while recovering or writing national receipts."""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (WORKER_LOCK_ID,))
        row = cur.fetchone()
    if not row or row[0] is not True:
        raise RuntimeError("Another national district scan owns the Neon worker lock")


def _release_worker_lock(connection):
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (WORKER_LOCK_ID,))
        row = cur.fetchone()
    if not row or row[0] is not True:
        raise RuntimeError("National district scan lost its Neon worker lock")


def _close_connection(connection):
    """Close a worker connection without masking the primary scan result."""
    try:
        connection.close()
    except Exception:
        pass


def _require_review_queue(connection):
    """Verify migration 009 exists before opening any district attempt."""
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.owner_osm_incremental_changes')")
        row = cur.fetchone()
    if not row or row[0] is None:
        raise RuntimeError("Migration 009 review queue is required before national district scanning")


def recover_orphaned_attempts(connection, registry, *, finished_at):
    """Close hard-terminated worker attempts after the exclusive lock is held."""
    recovered = []
    for province in registry["provinces"]:
        if province.get("status") != "running":
            continue
        unfinished = [attempt for attempt in province.get("attempts", ())
                      if not attempt.get("finished_at")]
        if len(unfinished) != 1:
            raise RuntimeError("Running province has no unique unfinished attempt")
        attempt_id = unfinished[0].get("attempt_id", "")
        if not isinstance(attempt_id, str) or not attempt_id.startswith("pbf-"):
            raise RuntimeError("Cannot recover a running attempt owned by another scanner")
        finish_attempt(connection, province["code"], attempt_id,
                       finished_at=finished_at)
        recovered.append((province["code"], attempt_id))
    return recovered


def run(env=None, *, connection=None, output=print, now=None):
    """Run deterministic resume over all 81 configured province plans."""
    env = os.environ if env is None else env
    attempt_prefix, digest, expected_timestamp, pbf_path, source_url = safe_metadata(env)
    run_now = now or datetime.now(timezone.utc)
    if not isinstance(run_now, datetime) or run_now.tzinfo is None or run_now.utcoffset() is None:
        raise ValueError("National district scan clock must be timezone-aware")
    run_now = run_now.astimezone(timezone.utc)

    inventory = load_inventory()
    plans = compile_province_plans()
    district_to_province = {}
    for code, province in inventory["provinces"].items():
        for relation_id in province["district_ids"]:
            if relation_id in district_to_province:
                raise ValueError("Pinned district relation is assigned to multiple provinces")
            district_to_province[relation_id] = code
    if set(district_to_province) != set(inventory["district_ids"]):
        raise ValueError("Pinned province-to-district relation attribution is incomplete")
    with _scan_phase(output, "snapshot_verification"):
        verified_source = verify_pbf_snapshot(
            pbf_path, digest, now=run_now, max_pbf_bytes=MAX_PBF_BYTES,
        )
    source_at = verified_source["snapshot_timestamp"]
    if _aware_timestamp(source_at, "PBF header timestamp") != expected_timestamp:
        raise ValueError("Provided source timestamp does not match the checksum-verified PBF header")

    owns_connection = connection is None
    provided_connection = connection
    db_url = env.get("REVIEW_DATABASE_URL")

    def open_connection():
        if not owns_connection:
            return provided_connection
        from .review_private import connect_private_database
        return connect_private_database(db_url)

    connection = open_connection()
    active = None
    lock_acquired = False
    new_leads = 0
    changed_existing = 0
    failures = 0
    old_handlers = {}

    def interrupt(signum, _frame):
        raise InterruptedError(f"National district scan interrupted by signal {signum}")

    if hasattr(signal, "SIGTERM"):
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, interrupt)

    try:
        _acquire_worker_lock(connection)
        lock_acquired = True
        _require_review_queue(connection)
        registry = read(connection)
        province_states = _validate_registry(registry, plans, inventory)
        _reject_older_snapshot(province_states, plans, source_at)
        recovered = recover_orphaned_attempts(
            connection, registry, finished_at=datetime.now(timezone.utc).isoformat()
        )
        for code, attempt_id in recovered:
            output(f"DISTRICT_ATTEMPT_RECOVERED: province={code}; attempt={attempt_id}")
        if recovered:
            registry = read(connection)
            province_states = _validate_registry(registry, plans, inventory)
        refresh_by_province = {
            code: districts_needing_refresh(province_states[code], plans[code], digest)
            for code in plans
        }
        target_count = sum(len(items) for items in refresh_by_province.values())
        if target_count == 0:
            receipts = sum(
                1 for state in province_states.values()
                for receipt in state.get("completed_items", {}).values()
                if receipt.get("source_sha256") == digest
            )
            output("NATIONAL_DISTRICT_SCAN: skipped=same_snapshot; "
                   f"source_sha256={digest}; districts_current={receipts}; "
                   "business_mail_sent=0; notifications_sent=0")
            return {"district_receipts": receipts, "candidate_count": 0,
                    "unassigned_count": 0, "new_leads": 0,
                    "changed_existing": 0, "districts_over_limit": 0,
                    "skipped_same_snapshot": True}

        # Neon session advisory locks are connection-scoped. Keep the initial
        # claim short, then close this connection while parsing the country PBF
        # (which can take tens of minutes) and reacquire/validate before writes.
        if lock_acquired:
            _release_worker_lock(connection)
            lock_acquired = False
        if owns_connection:
            _close_connection(connection)
        connection = None

        with _scan_phase(output, "district_geometry_extraction"):
            extraction = extract_district_geometries(
                pbf_path, inventory["district_ids"], digest,
                now=run_now, max_pbf_bytes=MAX_PBF_BYTES,
            )
        if extraction["source"]["snapshot_timestamp"] != source_at:
            raise ValueError("Verified PBF source changed before district geometry extraction")
        with _scan_phase(output, "district_spatial_index"):
            district_index = build_district_index(extraction["geometries"], district_to_province)
        with _scan_phase(output, "business_candidate_attribution"):
            attribution = collect_district_leads(pbf_path, district_index)
        output("NATIONAL_SCAN_ATTRIBUTION: "
               f"candidates={attribution['candidate_count']}; "
               f"unassigned={attribution['unassigned_count']}; "
               f"districts_with_leads={len(attribution['leads_by_district'])}; "
               f"districts_over_limit={len(attribution['overflow_districts'])}")

        connection = open_connection()
        _acquire_worker_lock(connection)
        lock_acquired = True
        _require_review_queue(connection)
        registry = read(connection)
        province_states = _validate_registry(registry, plans, inventory)
        _reject_older_snapshot(province_states, plans, source_at)
        refresh_by_province = {
            code: districts_needing_refresh(province_states[code], plans[code], digest)
            for code in plans
        }
        target_count = sum(len(items) for items in refresh_by_province.values())
        if target_count == 0:
            receipts = sum(
                1 for state in province_states.values()
                for receipt in state.get("completed_items", {}).values()
                if receipt.get("source_sha256") == digest
            )
            output("NATIONAL_DISTRICT_SCAN: skipped=claimed_by_other_worker; "
                   f"source_sha256={digest}; districts_current={receipts}; "
                   "business_mail_sent=0; notifications_sent=0")
            return {"district_receipts": receipts, "candidate_count": 0,
                    "unassigned_count": 0, "new_leads": 0,
                    "changed_existing": 0, "districts_over_limit": 0,
                    "skipped_same_snapshot": True}

        for code in sorted(plans):
            remaining = refresh_by_province[code]
            if not remaining:
                continue
            attempt_id = f"{attempt_prefix}-{code}"
            province_started = time.monotonic()
            registry = begin_attempt(connection, code, attempt_id=attempt_id,
                                     started_at=run_now.isoformat(),
                                     source_sha256=digest)
            active = (code, attempt_id)
            active_state = next(row for row in registry["provinces"] if row["code"] == code)
            attempt = active_state["attempts"][-1]
            if (attempt.get("source_sha256") != digest
                    or set(attempt["planned_item_ids"]) != set(remaining)):
                raise RuntimeError("Active attempt does not match the verified snapshot refresh set")
            try:
                for relation_id in remaining:
                    observed_at = datetime.now(timezone.utc).isoformat()
                    if relation_id in attribution["overflow_districts"]:
                        record_item_result(
                            connection, code, attempt_id, relation_id,
                            succeeded=False, observed_at=observed_at, error_code="other",
                        )
                        failures += 1
                        continue
                    leads = attribution["leads_by_district"].get(relation_id, [])
                    result = commit_district_batch(
                        connection, code, attempt_id, relation_id,
                        leads=leads, records_count=len(leads),
                        observed_at=observed_at, source_url=source_url,
                        source_data_at=source_at, source_sha256=digest,
                    )
                    new_leads += int(result.get("new_leads", 0))
                    changed_existing += int(result.get("changed_existing", 0))
                finish_attempt(connection, code, attempt_id,
                               finished_at=datetime.now(timezone.utc).isoformat())
                active = None
            except BaseException:
                if active is not None:
                    try:
                        _finalize_province(
                            connection, code, attempt_id,
                            datetime.now(timezone.utc).isoformat(),
                        )
                        active = None
                    except Exception:
                        output(f"DISTRICT_ATTEMPT_FINALIZATION_FAILED: province={code}; attempt={attempt_id}")
                raise
            # Re-read after the serialized province attempt so subsequent work
            # and final reporting use durable receipts, never local assumptions.
            registry = read(connection)
            province_states = {row["code"]: row for row in registry["provinces"]}
            province_current = sum(
                1 for item, receipt in province_states[code].get("completed_items", {}).items()
                if item in set(plans[code]["work_item_ids"])
                and receipt.get("source_sha256") == digest
            )
            failed_items = sum(item in attribution["overflow_districts"] for item in remaining)
            output(f"NATIONAL_DISTRICT_PROVINCE: code={code}; "
                   f"snapshot_receipts={province_current}; failed={failed_items}; "
                   f"source_sha256={digest}; "
                   f"elapsed_s={time.monotonic() - province_started:.1f}")

        coverage = {row["code"]: row for row in read(connection)["provinces"]}
        completed_total = sum(
            1 for state in coverage.values()
            for receipt in state.get("completed_items", {}).values()
            if receipt.get("source_sha256") == digest
        )
        output(
            "NATIONAL_DISTRICT_SCAN: "
            f"source_sha256={digest}; source_timestamp={source_at}; "
            f"district_receipts={completed_total}; candidates={attribution['candidate_count']}; "
            f"unassigned={attribution['unassigned_count']}; new_crm={new_leads}; "
            f"changed_existing_queued={changed_existing}; "
            f"districts_over_limit={failures}; business_mail_sent=0; notifications_sent=0"
        )
        return {
            "district_receipts": completed_total,
            "candidate_count": attribution["candidate_count"],
            "unassigned_count": attribution["unassigned_count"],
            "new_leads": new_leads,
            "changed_existing": changed_existing,
            "districts_over_limit": failures,
            "skipped_same_snapshot": False,
        }
    finally:
        if active is not None:
            try:
                _finalize_province(connection, active[0], active[1],
                                   datetime.now(timezone.utc).isoformat())
            except Exception:
                output(f"DISTRICT_ATTEMPT_FINALIZATION_FAILED: province={active[0]}; attempt={active[1]}")
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if lock_acquired and connection is not None:
            try:
                _release_worker_lock(connection)
            except Exception:
                # Preserve the scan exception/result; stale connections can
                # disappear during long-running provider operations.
                output("NATIONAL_DISTRICT_LOCK_RELEASE_WARNING: connection unavailable")
        if owns_connection and connection is not None:
            _close_connection(connection)


def preflight(env=None, *, connection=None, output=print):
    """Read-only check for migration 016, exact plans, and migration 009."""
    env = os.environ if env is None else env
    inventory = load_inventory()
    plans = compile_province_plans()
    owns_connection = connection is None
    if connection is None:
        from .review_private import connect_private_database
        connection = connect_private_database(env.get("REVIEW_DATABASE_URL"))
    try:
        _require_review_queue(connection)
        registry = read(connection)
        states = _validate_registry(registry, plans, inventory)
        total = sum(len(plan["work_item_ids"]) for plan in plans.values())
        complete = sum(len(state.get("completed_items", {})) for state in states.values())
        output(f"NATIONAL_DISTRICT_PREFLIGHT: provinces=81; districts={total}; "
               f"receipt_confirmed={complete}; plans_valid=1; "
               "migration_009=ready; scan_started=0; crm_rows_written=0")
        return {"provinces": 81, "districts": total,
                "receipt_confirmed": complete, "scan_started": 0}
    finally:
        if owns_connection:
            connection.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--preflight":
        preflight()
    else:
        run()

