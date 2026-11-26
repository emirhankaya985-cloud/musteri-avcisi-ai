"""Bounded private research for existing CRM leads with no email address.

This worker reads public business websites and persists source-backed findings
to the private CRM. It never guesses addresses, verifies mailboxes, sends mail,
or changes any marketing permission or outbound-mail state.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .contact_email import discover_email
from .outreach import valid_recipient
from .review_private import connect_private_database

DEFAULT_BATCH_SIZE = 10
MAX_BATCH_SIZE = 50
HOST_COOLDOWN = timedelta(days=30)


def _host(website):
    try:
        value = str(website or "").strip()
        if value and "://" not in value:
            value = "https://" + value
        host = (urlsplit(value).hostname or "").casefold().removeprefix("www.")
        return host or None
    except ValueError:
        return None


def _json_object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _recent_attempt(data, now):
    item = data.get("email_research")
    if not isinstance(item, dict):
        return False
    stamp = item.get("checked_at")
    if not isinstance(stamp, str):
        return False
    try:
        checked = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked.tzinfo is None:
        return False
    return now - checked < HOST_COOLDOWN


def _eligible(row):
    lead_id, raw, status = row
    data = _json_object(raw)
    if status != "review" or not data.get("website"):
        return None
    if str(data.get("email") or "").strip():
        return None
    eligibility = data.get("marketing_eligibility")
    if isinstance(eligibility, dict) and eligibility.get("opted_out") is True:
        return None
    mail = data.get("_auto_mail") or {}
    manual = data.get("_mail") or {}
    if mail.get("state") in ("sending", "accepted", "uncertain"):
        return None
    if manual.get("state") in ("sending", "accepted", "uncertain"):
        return None
    host = _host(data.get("website"))
    if not host:
        return None
    return {"id": lead_id, **data, "_research_host": host}


def _persist(connection, lead, found, checked_at):
    if found:
        email = str(found.get("email") or "").strip().casefold()
        source = str(found.get("email_source") or "").strip()
        if not valid_recipient(email) or not source.startswith(("https://", "http://")):
            return False
        evidence = {
            "status": "public_address_found",
            "source_url": source,
            "checked_at": checked_at,
            "email_check": str(found.get("email_check") or "unchecked"),
        }
        update = {"email": email, "email_source": source,
                  "email_check": evidence["email_check"], "email_research": evidence}
    else:
        update = {"email_research": {
            "status": "no_unique_public_address",
            "checked_at": checked_at,
            "email_check": "not_found",
        }}
        email = None
    website = lead.get("website")
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE owner_leads SET lead_data=lead_data || %s::jsonb,updated_at=now() "
            "WHERE osm_id=%s AND status='review' "
            "AND coalesce(lead_data->>'website','')=%s "
            "AND coalesce(btrim(lead_data->>'email'),'')='' "
            "AND coalesce(lead_data->'_auto_mail'->>'state','') NOT IN "
            "('sending','accepted','uncertain') "
            "AND coalesce(lead_data->'_mail'->>'state','') NOT IN "
            "('sending','accepted','uncertain') "
            "AND coalesce(lead_data->'marketing_eligibility'->>'opted_out','false') <> 'true'",
            (json.dumps(update, ensure_ascii=False), lead["id"], website),
        )
        return cur.rowcount == 1


def run(connection=None, *, env=None, discover=discover_email, now=None,
        batch_size=DEFAULT_BATCH_SIZE, output=print):
    """Research a small batch and return aggregate-only result counts.

    Recent attempts on the same website host suppress repeat fetches for 30
    days, so branch-heavy CRM records cannot hammer the same website. A
    discovered address is only a public-source finding, not mailbox validation
    or legal permission to contact.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Research clock must be timezone-aware")
    stamp = now.astimezone(timezone.utc).isoformat()
    own = connection is None
    db = connection if connection is not None else connect_private_database(
        (os.environ if env is None else env).get("REVIEW_DATABASE_URL"))
    counts = {"considered": 0, "researched": 0, "addresses_found": 0,
              "not_found": 0, "drafts_prepared": 0,
              "host_cooldown": 0, "write_conflicts": 0}
    try:
        with db.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(985402619)")
            acquired = bool(cur.fetchone()[0])
        if not acquired:
            output("CONTACT_RESEARCH: skipped=another_worker; addresses=0")
            return {**counts, "skipped": True}
        try:
            with db.cursor() as cur:
                cur.execute("SELECT osm_id,lead_data,status FROM owner_leads "
                            "WHERE status='review' ORDER BY updated_at,osm_id")
                rows = cur.fetchall()
            leads = [item for row in rows if (item := _eligible(row)) is not None]
            recent_hosts = {
                _host(_json_object(raw).get("website"))
                for _, raw, _ in rows
                if _host(_json_object(raw).get("website"))
                and _recent_attempt(_json_object(raw), now)
            }
            selected = []
            used_hosts = set()
            for lead in leads:
                counts["considered"] += 1
                host = lead["_research_host"]
                if host in recent_hosts or host in used_hosts:
                    counts["host_cooldown"] += 1
                    continue
                selected.append(lead)
                used_hosts.add(host)
                if len(selected) >= batch_size:
                    break
            for lead in selected:
                # Existing crawler enforces same-host URLs, public IPs, three
                # pages, short timeouts, and unique-address-only results.
                result = discover(lead)
                result = result if isinstance(result, dict) else lead
                found = (result.get("email") and result.get("email_source")
                         and valid_recipient(str(result.get("email")).strip().casefold()))
                saved = _persist(db, lead, result if found else None, stamp)
                if not saved:
                    counts["write_conflicts"] += 1
                    continue
                counts["researched"] += 1
                if found:
                    counts["addresses_found"] += 1
                    # Prepare a deterministic, unsent owner-review draft. This
                    # never changes marketing eligibility or calls SMTP.
                    from .automatic_mail import AutoMailStore
                    from .review_private import ReviewStore
                    draft = AutoMailStore(ReviewStore(db)).prepare(
                        result, {"MAIL_DRAFT_MODE": "template"}, opener=None)
                    counts["drafts_prepared"] += int(
                        isinstance(draft, dict) and draft.get("state") == "draft")
                else:
                    counts["not_found"] += 1
        finally:
            with db.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(985402619)")
                cur.fetchone()
        output("CONTACT_RESEARCH: researched=" + str(counts["researched"])
               + "; public_addresses_found=" + str(counts["addresses_found"])
               + "; unsent_drafts_prepared=" + str(counts["drafts_prepared"])
               + "; no_unique_address=" + str(counts["not_found"])
               + "; host_cooldown=" + str(counts["host_cooldown"])
               + "; write_conflicts=" + str(counts["write_conflicts"])
               + "; smtp_attempts=0; recipient_details=0")
        return {**counts, "skipped": False}
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    raw_batch_size = os.environ.get("CONTACT_RESEARCH_BATCH_SIZE", "10")
    try:
        batch_size = int(raw_batch_size)
    except (TypeError, ValueError):
        raise SystemExit("CONTACT_RESEARCH_BATCH_SIZE must be an integer") from None
    run(batch_size=batch_size)
