"""Read-only Neon freshness watchdog, with no customer data or scan writes.

A skipped GitHub cron must never automatically dispatch a second customer
scan: the next normal scan resumes from the persisted OSM tile ledger.
"""
import os
from datetime import datetime, timezone, timedelta
from .review_private import connect_private_database


def classify(last_scan, last_gmail, now=None, max_age_minutes=180):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Aware current time required")
    if type(max_age_minutes) is not int or not 90 <= max_age_minutes <= 360:
        raise ValueError("Unsafe freshness threshold")
    result = {}
    for key, stamp in (("scan",last_scan), ("gmail",last_gmail)):
        if stamp is None or stamp.tzinfo is None:
            result[key] = "unverified"
            continue
        age = now - stamp.astimezone(timezone.utc)
        if age < timedelta(0):
            result[key] = "unverified"
        elif age > timedelta(minutes=max_age_minutes):
            result[key] = "stale"
        else:
            result[key] = "fresh"
    return result


def run(env=None, connection=None, output=print):
    env = os.environ if env is None else env
    own = connection is None
    if own and not env.get("REVIEW_DATABASE_URL"):
        raise RuntimeError("Private Neon read-only watchdog not configured")
    conn = connection if connection is not None else connect_private_database(
        env["REVIEW_DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(created_at) FROM owner_scan_run_metrics")
            scan = cur.fetchone()[0]
            cur.execute("SELECT max(created_at) FROM owner_mail_watch_runs")
            gmail = cur.fetchone()[0]
        states = classify(scan, gmail)
    finally:
        if own:
            conn.close()
    # Stable classes only: don't print connection strings, recipients,
    # private dates, record names or sensitive Gmail messages.
    output("OPS_FRESHNESS: scan=" + states["scan"] +
           "; gmail=" + states["gmail"] +
           "; new_smtp_sent=0; automatic_duplicate_scan=0")
    if any(state != "fresh" for state in states.values()):
        raise RuntimeError("OPS_FRESHNESS: PARTIAL; stale or unverified recurring job")
    return states


if __name__ == "__main__":
    run()
