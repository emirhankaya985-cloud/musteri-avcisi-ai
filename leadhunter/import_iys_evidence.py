"""Import owner-verified business eligibility from a private JSON file.

The input is never written to logs or the repository. It must contain only
business recipients independently checked in İYS and official merchant
evidence. A hold/opt-out in either the import or existing CRM always wins.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

from .mail_tracking import normalized_email
from .outreach import valid_recipient
from .review_private import connect_private_database

EVIDENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}\Z")
MAX_BYTES = 1_000_000


def parse_document(raw, now=None):
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise ValueError("Evidence file exceeds size limit")
        raw = raw.decode("utf-8-sig")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Evidence document is invalid or too large")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("schema") != "iys-business-evidence-v1":
        raise ValueError("Unsupported evidence schema")
    rows = doc.get("records")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("Evidence records must contain 1 to 5000 rows")
    now = now or datetime.now(timezone.utc)
    seen = set()
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid evidence row")
        email = normalized_email(row.get("email"))
        merchant_ref = row.get("merchant_evidence_ref")
        iys_ref = row.get("iys_evidence_ref")
        checked = row.get("checked_at")
        if (not valid_recipient(email) or email in seen
                or not isinstance(merchant_ref, str) or not EVIDENCE_ID.fullmatch(merchant_ref)
                or not isinstance(iys_ref, str) or not EVIDENCE_ID.fullmatch(iys_ref)
                or type(row.get("merchant_verified")) is not bool
                or type(row.get("iys_registered")) is not bool
                or type(row.get("iys_rejected")) is not bool):
            raise ValueError("Evidence row is missing exact recipient or source-backed verification")
        try:
            timestamp = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        except (ValueError, OverflowError):
            raise ValueError("Invalid evidence check time") from None
        if timestamp.tzinfo is None or timestamp > now or (now - timestamp).total_seconds() > 86400:
            raise ValueError("IYS status evidence must be timezone-aware and no older than 24 hours")
        seen.add(email)
        parsed.append({
            "recipient": email,
            "route": "iys_verified_business",
            "evidence_ref": merchant_ref,
            "merchant_evidence_ref": merchant_ref,
            "iys_evidence_ref": iys_ref,
            "verified_at": timestamp.astimezone(timezone.utc).isoformat(),
            "opted_out": row["iys_rejected"],
            "merchant_verified": row["merchant_verified"],
            "iys_registered": row["iys_registered"],
            "iys_rejected": row["iys_rejected"],
        })
    return parsed


def import_records(conn, records):
    """Attach proof only on exact CRM email match; never change mail history."""
    matched = updated = held = opted_out = 0
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(789654324)")
            for record in records:
                cur.execute(
                    "SELECT osm_id,lead_data FROM owner_leads WHERE "
                    "lower(btrim(coalesce(lead_data#>>'{_auto_mail,recipient}', "
                    "lead_data#>>'{_mail,recipient}',lead_data->>'email','')))=%s "
                    "FOR UPDATE", (record["recipient"],))
                rows = cur.fetchall()
                if not rows:
                    continue
                matched += 1
                # One address linked to multiple leads is ambiguous. Suppress
                # all matches so the importer cannot choose an identity.
                if len(rows) != 1:
                    held += 1
                    continue
                lead_id, data = rows[0]
                if isinstance(data, str):
                    data = json.loads(data)
                existing = data.get("marketing_eligibility") or {}
                old_email = normalized_email(existing.get("recipient"))
                if (existing.get("opted_out") is True or
                        existing.get("iys_rejected") is True or
                        existing.get("hold") is True or
                        (old_email and old_email != record["recipient"])):
                    held += 1
                    continue
                if not record["iys_registered"] or record["iys_rejected"] or not record["merchant_verified"]:
                    record_to_store = {**record, "hold": True}
                    opted_out += int(record["iys_rejected"])
                    held += 1
                else:
                    record_to_store = record
                cur.execute(
                    "UPDATE owner_leads SET lead_data=jsonb_set(lead_data,"
                    "'{marketing_eligibility}',%s::jsonb,true),updated_at=now() "
                    "WHERE osm_id=%s", (json.dumps(record_to_store), lead_id))
                updated += 1
    return {"input": len(records), "matched": matched, "updated": updated,
            "held": held, "opted_out": opted_out}


def run(path, env=None, connection=None, output=print):
    env = os.environ if env is None else env
    raw = open(path, "rb").read(MAX_BYTES + 1)
    records = parse_document(raw)
    owns = connection is None
    conn = connection or connect_private_database(env.get("REVIEW_DATABASE_URL"))
    try:
        result = import_records(conn, records)
    finally:
        if owns:
            conn.close()
    output("IYS_IMPORT: " + "; ".join(f"{k}={v}" for k, v in result.items()) +
           "; recipients_logged=0; smtp_attempts=0")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m leadhunter.import_iys_evidence PRIVATE_JSON_PATH")
    run(sys.argv[1])
