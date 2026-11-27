"""Idempotently install pinned district work plans into private Neon.

This prepares queue metadata only. It never downloads OSM data, scans a
district, writes CRM leads, or starts outreach.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .district_work_plan import compile_province_plans
from .province_coverage_store import configure_plan, read
from .review_private import connect_private_database


def _same_plan(existing, desired):
    if not isinstance(existing, dict):
        return False
    return all(existing.get(key) == desired[key]
               for key in ("source_url", "source_sha256", "work_item_ids",
                           "excluded_item_ids"))


def apply(connection, plans, configured_at=None, read_registry=read,
          configure=configure_plan):
    """Add missing plans; preserve exact existing plans and fail on drift."""
    configured_at = configured_at or datetime.now(timezone.utc).isoformat()
    registry = read_registry(connection)
    states = {row["code"]: row for row in registry["provinces"]}
    if set(states) != set(plans) or len(plans) != 81:
        raise ValueError("District plan set must cover the exact 81-province ledger")
    conflicts = [code for code, desired in plans.items()
                 if states[code].get("plan") is not None
                 and not _same_plan(states[code]["plan"], desired)]
    if conflicts:
        raise RuntimeError("Existing district plan differs; refusing to replace it")
    created = existing_count = 0
    for code, desired in plans.items():
        current = states[code].get("plan")
        if current is not None:
            existing_count += 1
            continue
        registry = configure(
            connection, code,
            source_url=desired["source_url"],
            source_sha256=desired["source_sha256"],
            work_item_ids=desired["work_item_ids"],
            excluded_item_ids=desired["excluded_item_ids"],
            configured_at=configured_at)
        states = {row["code"]: row for row in registry["provinces"]}
        created += 1
    return {"provinces": len(plans),
            "districts": sum(len(row["work_item_ids"]) for row in plans.values()),
            "created": created, "already_configured": existing_count,
            "scans_started": 0}


def run(env=None, connection=None, output=print):
    env = os.environ if env is None else env
    plans = compile_province_plans()
    owns = connection is None
    conn = connection or connect_private_database(env.get("REVIEW_DATABASE_URL"))
    try:
        result = apply(conn, plans)
    finally:
        if owns:
            conn.close()
    output("DISTRICT_PLANS: " + "; ".join(f"{key}={value}" for key, value in result.items()) +
           "; crm_rows_written=0; outbound_requests=0; business_mail_sent=0")
    return result


if __name__ == "__main__":
    run()
