"""Sanitized per-run evidence. This module never scans, sends or contacts users."""
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone

from .tile_progress import _load
from .review_private import connect_private_database

RUN_ID = re.compile(r"[0-9]{6,24}\Z")
REGION = re.compile(r"pilot_[1-8]_of_8\Z")
REASONS = frozenset((
    "none","unverified","timeout","dns","tls","connection","network",
    "http_5xx","http_other","response_oversize","response_invalid",
    "provider_remark","provider_refusal"))
OUTCOMES = frozenset(("success","failure","skipped","cancelled"))
REFUSALS = frozenset((400,401,403,406,429))


def _path(env):
    return Path(env.get("SCAN_OBSERVATION_FILE", "data/.scan_observation.json"))


def _write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,sort_keys=True)+"\n",encoding="utf-8")
    tmp.replace(path)


def begin(env, region, confirmed_before, provider_index=None):
    """Observe actual core selection before any public API or CRM operation."""
    run_id=str(env.get("GITHUB_RUN_ID",""))
    if not RUN_ID.fullmatch(run_id):
        return False  # Unit tests and local runs need no instrumentation.
    if not REGION.fullmatch(region):
        return False
    if type(confirmed_before) is not int or not 0<=confirmed_before<=54:
        raise ValueError("Invalid observed tile cursor")
    if provider_index is not None and (
            type(provider_index) is not int or not 0<=provider_index<=2):
        raise ValueError("Invalid Overpass provider index")
    _write(_path(env),{
        "run_id":run_id,"region":region,"confirmed_before":confirmed_before,
        "provider_index":provider_index,"source_reason":"none",
        "source_http_status":None,
        "started_at":datetime.now(timezone.utc).isoformat()})
    return True


def note_failure(env, reason, status=None):
    """Only enum + recognized 4xx code; never persist raw response/URL."""
    if reason not in REASONS - {"none","unverified"}:
        raise ValueError("Unexpected source failure code")
    if status is not None and (
            type(status) is not int or status not in REFUSALS
            or reason != "provider_refusal"):
        raise ValueError("Unexpected provider refusal status")
    path=_path(env)
    if not path.exists():
        return False
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return False
    if not isinstance(obj,dict) or obj.get("run_id") != env.get("GITHUB_RUN_ID"):
        return False
    obj["source_reason"]=reason
    obj["source_http_status"]=status
    _write(path,obj)
    return True


def collect(env, ledger_path="data/osm_tile_progress.json"):
    run_id=str(env.get("GITHUB_RUN_ID",""))
    if not RUN_ID.fullmatch(run_id):
        raise RuntimeError("GitHub run ID required")
    scanned=str(env.get("SCAN_STEP_OUTCOME","")).strip().lower()
    mirrored=str(env.get("MIRROR_STEP_OUTCOME","")).strip().lower()
    if scanned not in OUTCOMES or mirrored not in OUTCOMES:
        raise RuntimeError("Explicit GitHub step outcome required")
    region=before=after=provider=http=None
    reason="unverified"  # Missing source observation is never a verified clean scan.
    try:
        obj=json.loads(_path(env).read_text(encoding="utf-8"))
    except (OSError,ValueError):
        obj=None
    if (isinstance(obj,dict) and obj.get("run_id")==run_id
            and REGION.fullmatch(str(obj.get("region","")))
            and type(obj.get("confirmed_before")) is int
            and 0<=obj["confirmed_before"]<=54
            and (obj.get("provider_index") is None or
                 type(obj["provider_index"]) is int and
                 0<=obj["provider_index"]<=2)
            and obj.get("source_reason") in REASONS
            and (obj.get("source_http_status") is None or
                 type(obj["source_http_status"]) is int and
                 obj["source_http_status"] in REFUSALS)):
        region=obj["region"]
        before=obj["confirmed_before"]
        provider=obj.get("provider_index")
        reason=obj["source_reason"]
        http=obj.get("source_http_status")
        if http is not None and reason!="provider_refusal":
            raise RuntimeError("Inconsistent source observation")
        document=_load(ledger_path)
        entry=document["regions"].get(region,{})
        if entry:
            after=entry["next"]
        elif before==0:
            after=0
        # Never guess an "after" state if a public file is missing.
        if after is not None and after<before:
            raise RuntimeError("Tile ledger regressed")
    outcome=("partial" if scanned=="success" and reason not in ("none","unverified")
             else scanned)
    if scanned!="success" and reason=="none":
        reason="unverified"
    return (run_id,region,outcome,reason,http,provider,before,after,mirrored)


def persist(conn, row):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO owner_scan_attempts "
                "(scan_run_id,region,outcome,source_reason,source_http_status,"
                "provider_index,confirmed_before,confirmed_after,mirror_outcome) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (scan_run_id) DO NOTHING RETURNING scan_run_id",row)
            inserted=cur.fetchone() is not None
    return inserted


def run(env=None, output=print, conn=None):
    env=os.environ if env is None else env
    row=collect(env,env.get("TILE_PROGRESS_FILE","data/osm_tile_progress.json"))
    own=conn is None
    db=connect_private_database(env.get("REVIEW_DATABASE_URL")) if own else conn
    try:
        recorded=persist(db,row)
    finally:
        if own:
            db.close()
    output("SCAN_ATTEMPT: recorded="+str(int(recorded))+
           "; run_id="+row[0]+"; outcome="+row[2]+
           "; region="+str(row[1] or "unverified")+
           "; failure_class="+row[3]+"; business_mail_sent=0")
    return recorded


if __name__ == "__main__":
    run()
