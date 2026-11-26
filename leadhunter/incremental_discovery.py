"""Incremental OSM business discovery after the 402-cell historical baseline.

Uses a newer, checksum-verified Geofabrik PBF, not 402 Overpass tile requests.
Only new OSM IDs are inserted. Existing leads with changed source attributes
go to a private review queue; no automatic merge, deletion, or marketing.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from .core import bbox_parse
from .scan_regions import PILOT_BBOXES
from .snapshot_coverage import (parse_pilot, overlaps, safe_metadata)
from .review_private import connect_private_database

SOURCE_FIELDS=("name","category","website","phone","email","address")
MIN_INTERVAL=timedelta(days=3)
AREAS=tuple(bbox_parse(b) for b in PILOT_BBOXES)


def source_latest(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT greatest("
            "coalesce((SELECT max(source_data_at) FROM owner_osm_tile_snapshot_provenance),"
            "'epoch'::timestamptz),"
            "coalesce((SELECT max(source_data_at) FROM owner_osm_incremental_runs),"
            "'epoch'::timestamptz))")
        return cur.fetchone()[0]


def due(db, now=None):
    now=datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None:
        raise ValueError("Source refresh clock must be timezone-aware")
    most_recent=source_latest(db)
    if most_recent is None or most_recent.year < 2026:
        raise RuntimeError("Missing real initial OSM snapshot; cannot refresh blind")
    if most_recent > now:
        raise RuntimeError("Source timestamp is future-dated")
    return now-most_recent>=MIN_INTERVAL


def within_pilot(features):
    return {key:pair for key,pair in features.items()
            if any(overlaps(pair[1],area) for area in AREAS)}


def changed_fields(prior, fresh):
    """Never infer closures or overwrite historic business contact details."""
    return tuple(k for k in SOURCE_FIELDS
                 if str(prior.get(k) or "").strip().casefold()
                 != str(fresh.get(k) or "").strip().casefold())


def ingest(db, features, digest, source_at, run_id, *, output=print):
    if not features:
        raise RuntimeError("Source pilot is empty; no incremental success reported")
    selected=within_pilot(features)
    if not selected:
        raise RuntimeError("Source contains no businesses within pilot; fail closed")
    new=changed=0
    with db.transaction():
        with db.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(985402617)")
            previous=source_latest(db)
            if source_at <= previous:
                output("INCREMENTAL_SOURCE: skipped=already_observed; source_newer=0; "
                       "new_registered=0; outbound_business_mail=0")
                return (0,0,False)
            # This is an OSM-object-level comparison, not a revisit of 402
            # historical cells. Never touch owner_osm_tile_ledger or its cursor.
            cur.execute("SELECT osm_id,lead_data FROM owner_leads WHERE osm_id=ANY(%s)",
                        (list(selected),))
            prior={x:(json.loads(y) if isinstance(y,str) else y)
                   for x,y in cur.fetchall()}
            for lead_id,(lead,geometry) in sorted(selected.items()):
                if lead_id not in prior:
                    cur.execute(
                        "INSERT INTO owner_leads(osm_id,lead_data,status)"
                        " VALUES (%s,%s::jsonb,'review')"
                        " ON CONFLICT(osm_id) DO NOTHING RETURNING osm_id",
                        (lead_id,json.dumps(lead,ensure_ascii=False)))
                    inserted = cur.fetchone() is not None
                    new += int(inserted)
                    if inserted:
                        cur.execute("SELECT to_regclass('owner_lead_lifecycle_state')")
                        lifecycle_ready = cur.fetchone()[0] is not None
                        if lifecycle_ready:
                            from .lifecycle_store import record_transition
                            record_transition(
                                db, lead_id, "new_discovered",
                                idempotency_key=f"discover:{lead_id}",
                                reason="New OSM business registered from verified PBF snapshot",
                                evidence_refs=(f"osm://{lead_id}",
                                              "https://download.geofabrik.de/europe/turkey/"),
                            )
                else:
                    fields=changed_fields(prior[lead_id],lead)
                    if fields:
                        # Existing contact eligibility, SMTP proofs and owner
                        # decisions are immutable. A human must review changes.
                        cur.execute(
                            "INSERT INTO owner_osm_incremental_changes"
                            "(osm_id,snapshot_sha256,source_data_at,fields_changed,"
                            "proposed_lead) VALUES (%s,%s,%s,%s,%s::jsonb)"
                            " ON CONFLICT(osm_id) DO UPDATE SET "
                            "snapshot_sha256=EXCLUDED.snapshot_sha256,"
                            "source_data_at=EXCLUDED.source_data_at,"
                            "fields_changed=EXCLUDED.fields_changed,"
                            "proposed_lead=EXCLUDED.proposed_lead,"
                            "review_state='needs_review',observed_at=now()",
                            (lead_id,digest,source_at,list(fields),
                             json.dumps(lead,ensure_ascii=False)))
                        changed+=1
            cur.execute(
                "INSERT INTO owner_osm_incremental_runs"
                "(snapshot_sha256,source_data_at,github_run_id,candidate_count,"
                "newly_registered,changed_existing) VALUES (%s,%s,%s,%s,%s,%s)",
                (digest,source_at,run_id,len(selected),new,changed))
    output("INCREMENTAL_SOURCE: verified_newer=1; objects="+str(len(selected))+
           "; new_registered="+str(new)+
           "; changed_for_review="+str(changed)+
           "; historical_tiles_unchanged=402; outbound_business_mail=0")
    return new,changed,True


def run(env=None,output=print,db=None):
    env=os.environ if env is None else env
    run_id,digest,source_at,pbf=safe_metadata(env)
    owned=db is None
    conn=connect_private_database(env.get("REVIEW_DATABASE_URL")) if owned else db
    try:
        # Old source timestamps cannot write a new CRM row.
        if source_at<=source_latest(conn):
            output("INCREMENTAL_SOURCE: skipped=already_observed; no_change=1; "
                   "business_mail_sent=0")
            return (0,0,False)
        features,_=parse_pilot(pbf)
        return ingest(conn,features,digest,source_at,run_id,output=output)
    finally:
        if owned:
            conn.close()


def preflight(env=None,db=None,output=print):
    env=os.environ if env is None else env
    owned=db is None
    conn=connect_private_database(env.get("REVIEW_DATABASE_URL")) if owned else db
    try:
        refresh=due(conn)
    finally:
        if owned:
            conn.close()
    output("INCREMENTAL_PREFLIGHT: source_refresh_due="+str(int(refresh))+
           "; initial_coverage_preserved=402; smtp_sent=0")
    return refresh


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--preflight":
        print("true" if preflight() else "false")
    else:
        run()
