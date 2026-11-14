"""Additive, aggregate-safe Neon mirror of the durable public tile cursor.

The public per-region tile cursor remains the scan source of truth. Neon is
only an auditable read model for Control Center; it never changes scan order.
No customer fields, email addresses, secrets, raw OSM payloads or SMTP here.
"""
import os
import re
from pathlib import Path

from .review_private import connect_private_database
from .scan_regions import PILOT_BBOXES
from .core import bbox_parse
from .tile_progress import _load, tile_total


def region_rows(path):
    """Return all 402 expected tile states, including those not yet scanned."""
    ledger = _load(path)
    states = []
    for index, source_box in enumerate(PILOT_BBOXES, 1):
        region = f"pilot_{index}_of_8"
        total = tile_total(bbox_parse(source_box))
        entry = ledger["regions"].get(region, {})
        completed = entry.get("next", 0)
        stalls = entry.get("stalls", 0)
        if entry and entry["total"] != total:
            raise RuntimeError("OSM tile geometry differs from saved ledger")
        reason = entry.get("last_error")
        if reason not in (
            "timeout", "dns", "tls", "connection", "network", "http_5xx",
            "http_other", "response_oversize", "response_invalid",
            "provider_remark", "provider_refusal"):
            reason = "unverified_source_failure"
        for tile in range(total):
            state = ("confirmed" if tile < completed else
                     "blocked" if tile == completed and stalls and reason == "provider_refusal" else
                     "retry" if tile == completed and stalls else "pending")
            states.append((region, tile, state,
                           reason if state in ("retry", "blocked") else None))
    if len(states) != 402:
        raise RuntimeError("Unexpected OSM coverage geometry")
    return states


UPSERT = """
INSERT INTO owner_osm_tile_ledger
 (region,tile_index,state,reason,last_observed_run_id,updated_at)
VALUES (%s,%s,%s,%s,%s,now())
ON CONFLICT (region,tile_index) DO UPDATE SET
 state = CASE WHEN owner_osm_tile_ledger.state='confirmed'
                   THEN 'confirmed' ELSE EXCLUDED.state END,
 reason = CASE WHEN owner_osm_tile_ledger.state='confirmed'
                  THEN NULL ELSE EXCLUDED.reason END,
 last_observed_run_id = CASE
   WHEN owner_osm_tile_ledger.state IS DISTINCT FROM EXCLUDED.state
     OR owner_osm_tile_ledger.reason IS DISTINCT FROM EXCLUDED.reason
   THEN EXCLUDED.last_observed_run_id
   ELSE owner_osm_tile_ledger.last_observed_run_id END,
 updated_at = CASE
   WHEN owner_osm_tile_ledger.state IS DISTINCT FROM EXCLUDED.state
     OR owner_osm_tile_ledger.reason IS DISTINCT FROM EXCLUDED.reason
   THEN now() ELSE owner_osm_tile_ledger.updated_at END
"""


def sync(conn, path, run_id):
    if not re.fullmatch(r"[0-9]{6,24}", str(run_id)):
        raise RuntimeError("GitHub Actions run ID required for tile mirror")
    states = region_rows(path)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(789654324)")
            cur.executemany(UPSERT, [(region,tile,state,reason,str(run_id))
                                    for region,tile,state,reason in states])
            cur.execute(
                "SELECT state,count(*) FROM owner_osm_tile_ledger GROUP BY state")
            counts = {name:int(value) for name,value in cur.fetchall()}
            if sum(counts.values()) != 402:
                raise RuntimeError("Tile mirror count inconsistent; preserve source ledger")
            if counts.get("confirmed",0) < sum(1 for row in states if row[2]=="confirmed"):
                raise RuntimeError("Tile mirror regressed; no false success")
    return counts


def run(env=None, output=print, conn=None):
    env = os.environ if env is None else env
    path = Path(env.get("TILE_PROGRESS_FILE","data/osm_tile_progress.json"))
    if conn is None and not env.get("REVIEW_DATABASE_URL"):
        raise RuntimeError("Neon mirror database URL missing")
    own = conn is None
    connection = connect_private_database(env["REVIEW_DATABASE_URL"]) if own else conn
    try:
        result = sync(connection, path, env.get("GITHUB_RUN_ID",""))
    finally:
        if own:
            connection.close()
    output("TILE_NEON_SYNC: " + "; ".join(
        key + "=" + str(result.get(key, 0))
        for key in ("confirmed","pending","retry","blocked")) + "; total=402")
    return result


if __name__ == "__main__":
    run()
