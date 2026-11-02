"""Private, bounded scan totals: exactly once for each GitHub Actions run.

No customer addresses or source objects enter workflow logs. Metrics count
only CRM persisted changes, not mere OSM sightings or Telegram notifications.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .outreach import valid_recipient

TR = ZoneInfo("Europe/Istanbul")


def snapshot(conn, osm_ids):
    """Keep pre-run contact states in RAM only; do not log identities."""
    if not osm_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT osm_id,lower(btrim(coalesce(lead_data->>'email',''))) "
            "FROM owner_leads WHERE osm_id=ANY(%s)", (sorted(set(osm_ids)),))
        return {osm_id: email for osm_id, email in cur.fetchall()}


def persist(conn, run_id, day, scanned, before, osm_ids):
    """Idempotent committed counts; retry with same run ID adds no totals."""
    if not re.fullmatch(r"[0-9]{6,24}", str(run_id)):
        raise RuntimeError("Valid GitHub run ID required for scan totals")
    if not isinstance(day, str) or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day):
        raise RuntimeError("Valid Turkey scan day required")
    if not isinstance(scanned,int) or scanned < 0:
        raise RuntimeError("Invalid scan count")
    ids = sorted(set(osm_ids))
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT osm_id,lead_data FROM owner_leads WHERE osm_id=ANY(%s)",
                (ids,))
            rows = cur.fetchall()
            new_registered = new_addresses = new_mx = 0
            for osm_id, data in rows:
                old = before.get(osm_id)
                # Separate first-time CRM inserts from rediscovery/reprocessing.
                if osm_id not in before:
                    new_registered += 1
                address = str(data.get("email") or "").strip().casefold()
                if not valid_recipient(address) or (old and old == address):
                    continue
                # Count one new valid address only if the stored address was
                # absent or changed; a contact from OSM alone is not consent.
                new_addresses += 1
                if data.get("email_check") == "mx_present":
                    new_mx += 1
            cur.execute(
                "INSERT INTO owner_scan_run_metrics "
                "(scan_run_id,report_day,scanned_count,new_registered,new_addresses,new_mx) "
                "VALUES (%s,%s::date,%s,%s,%s,%s) ON CONFLICT (scan_run_id) DO NOTHING "
                "RETURNING scan_run_id",
                (str(run_id),day,scanned,new_registered,new_addresses,new_mx))
            recorded = cur.fetchone() is not None
    print("SCAN_METRICS: recorded="+str(int(recorded))+
          "; run_id="+str(run_id)+"; mail_sent=0")
    return recorded


def scan_day(now=None):
    return (now or datetime.now(TR)).astimezone(TR).date().isoformat()
